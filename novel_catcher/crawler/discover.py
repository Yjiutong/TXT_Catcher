# -*- coding: utf-8 -*-
"""章节位置推测：目录页解析 / 内嵌章节列表 / URL 数字模式推断 / 上下章链。

用户只提供书中某几章网址，本模块负责推测出整本书的章节 URL 列表。
"""
import re
import time
from urllib.parse import urljoin, urlparse

from .http import HttpFetcher, FetchError, Page
from . import extract
from .. import utils

# 目录页链接文本
_TOC_TEXT_RE = re.compile(
    r"^(章节目录|全部章节|章节列表|章节目录|小说目录|作品目录|本书目录|书目录|"
    r"查看目录|看目录|目录页|作品相关|目录|章节目录列表|章节|返回目录|回目录)$",
    re.I,
)
_TOC_TEXT_SUB_RE = re.compile(r"(章节目录|全部章节|章节列表|目录)", re.I)
_TOC_IDCLASS_RE = re.compile(
    r"(catalog|chapterlist|chapter-list|booklist|book-list|mulu|toc|chapter_index|"
    r"zhangjie|chapter-list-container|listmain|dir|menu-main|chapterList)", re.I)

# 目录页里应排除的非正文链接
_NON_CHAPTER_TEXT_RE = re.compile(
    r"(首页|登录|注册|书架|搜索|排行|完本|最近更新|最新更新|书评|论坛|"
    r"关于我们|联系我们|帮助|下载|分享|加入书签|收藏本页|设为首页|"
    r"返回|上一页|下一页|末页|第1页|第2页|作者的话|公告|简介|封面)",
    re.I,
)


def _anchor_text(a) -> str:
    return a.get_text(" ", strip=True)


def find_toc_link(page: Page) -> str:
    """从章节页找“目录”链接。"""
    soup = page.soup
    if soup is None:
        return ""
    # 1) 链接文本精确匹配
    for a in soup.find_all("a", href=True):
        text = _anchor_text(a)
        if not text or len(text) > 24:
            continue
        href = a["href"].strip()
        if href.startswith(("javascript:", "#", "mailto:")):
            continue
        if _TOC_TEXT_RE.search(text):
            abs_url = page.resolve(href)
            if abs_url and abs_url != page.url:
                return abs_url
    # 2) 链接文本模糊匹配（含“目录”）
    for a in soup.find_all("a", href=True):
        text = _anchor_text(a)
        if not text or len(text) > 24:
            continue
        href = a["href"].strip()
        if href.startswith(("javascript:", "#", "mailto:")):
            continue
        if _TOC_TEXT_SUB_RE.search(text):
            abs_url = page.resolve(href)
            if abs_url and abs_url != page.url:
                return abs_url
    return ""


def _toc_like_element(el) -> bool:
    idc = extract._element_id_class(el)
    return bool(_TOC_IDCLASS_RE.search(idc))


def find_embedded_chapter_list(page: Page) -> list:
    """查找章节页内嵌的完整章节列表元素（侧栏/底部目录）。

    返回 (title, url) 列表；找不到返回空列表。
    """
    soup = page.soup
    if soup is None:
        return []
    best_el, best_n = None, 0
    for el in soup.find_all(["div", "ul", "ol", "dl", "select"]):
        if el.name == "select":
            continue
        idc = extract._element_id_class(el)
        if not _TOC_IDCLASS_RE.search(idc):
            continue
        n = len(el.find_all("a", href=True))
        if n > best_n:
            best_n, best_el = n, el
    if best_el is None or best_n < 8:
        return []
    return _parse_link_list(best_el, page)


def parse_toc_page(page: Page) -> list:
    """解析目录页，返回 (title, url) 章节列表。"""
    soup = page.soup
    if soup is None:
        return []
    # 目录容器：优先 id/class 匹配；否则选链接最多的容器
    containers = []
    for el in soup.find_all(["div", "ul", "ol", "dl"]):
        if _toc_like_element(el):
            containers.append(el)
    if containers:
        containers.sort(key=lambda e: len(e.find_all("a", href=True)), reverse=True)
        for el in containers:
            links = _parse_link_list(el, page)
            if len(links) >= 5:
                return links
    # 兜底：全页链接聚类
    all_links = _parse_link_list(soup, page)
    return all_links


def _parse_link_list(scope, page: Page) -> list:
    """从元素内收集章节链接，过滤噪音，保持顺序去重。"""
    seen = set()
    out = []
    for a in scope.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("javascript:", "#", "mailto:", "tel:")):
            continue
        text = _anchor_text(a)
        if not text or len(text) > 80:
            continue
        if _NON_CHAPTER_TEXT_RE.search(text) and len(text) <= 12:
            continue
        abs_url = page.resolve(href)
        abs_url = utils.normalize_url(abs_url)
        if not abs_url or not abs_url.startswith(("http://", "https://")):
            continue
        if abs_url in seen:
            continue
        seen.add(abs_url)
        out.append((text, abs_url))
    return out


def _candidate_urls_from_seed(seed_url: str, count: int = 30) -> list:
    """基于 URL 数字模式生成候选 URL：向两端扩展。"""
    n = utils.extract_url_number(seed_url)
    if n is None:
        return []
    out = []
    # 先向后（n+1, n+2...），再向前（n-1, n-2...）
    for delta in range(1, count + 1):
        out.append(utils.replace_last_number(seed_url, n + delta))
    for delta in range(1, count + 1):
        out.append(utils.replace_last_number(seed_url, n - delta))
    return out


def infer_by_url_pattern(fetcher: HttpFetcher, seed_urls: list, max_chapters: int,
                         progress=None, gap_stop: int = 4) -> list:
    """URL 数字模式推断：验证候选页是否为章节正文页。

    返回有序章节 URL 列表（含种子本身）。连续 gap_stop 次未命中即停止。
    """
    result = set(seed_urls)
    for seed in seed_urls:
        n = utils.extract_url_number(seed)
        if n is None:
            continue
        if len(result) >= max_chapters:
            break
        cands = _candidate_urls_from_seed(seed, count=max_chapters)
        misses = 0
        for cand in cands:
            if len(result) >= max_chapters:
                break
            if cand in result:
                continue
            if not utils.is_same_host(seed, cand):
                continue
            try:
                page = fetcher.fetch(cand)
            except FetchError:
                misses += 1
                if misses >= gap_stop:
                    break
                continue
            if extract.looks_like_chapter_page(page):
                result.add(cand)
                misses = 0
                if progress:
                    progress(f"数字推断命中：{cand}")
            else:
                misses += 1
                if misses >= gap_stop:
                    break
            time.sleep(0.1)
    return result


def walk_by_next_link(fetcher: HttpFetcher, start_url: str, max_chapters: int,
                      forward: bool = True) -> list:
    """沿“下一章/上一章”链接行走，收集章节 URL。"""
    urls = []
    visited = set()
    cur = start_url
    while cur and len(urls) < max_chapters:
        if cur in visited:
            break
        visited.add(cur)
        urls.append(cur)
        try:
            page = fetcher.fetch(cur)
        except FetchError:
            break
        if forward:
            nxt = extract.find_next_chapter_link(page)
        else:
            nxt = extract.find_prev_chapter_link(page)
        if not nxt or not utils.is_same_host(cur, nxt):
            break
        cur = nxt
    return urls


def _sort_key(url: str, order_index: dict) -> tuple:
    """排序键：目录中的位置优先，其次 URL 数字。"""
    if url in order_index:
        return (0, order_index[url])
    n = utils.extract_url_number(url)
    return (1, n if n is not None else 0)


def discover_chapters(fetcher: HttpFetcher, seed_urls: list,
                      max_chapters: int = 8000, progress=None) -> list:
    """核心：根据用户提供的若干章节网址，推测整本书章节列表。

    策略优先级：
      1) 目录页（章节页里的“目录”链接）→ 完整目录
      2) 章节页内嵌章节列表（侧栏目录）
      3) URL 数字模式推断（向两端扩展并验证）
      4) “上一章/下一章”链接行走（向前后扩展）

    返回：有序、去重的章节 URL 列表（保证包含所有种子）。
    """
    seeds = [utils.normalize_url(u) for u in seed_urls if utils.normalize_url(u)]
    seeds = utils.dedupe_keep_order(seeds)
    if not seeds:
        raise FetchError("未提供任何有效章节网址")

    found = list(seeds)
    order_index = {u: i for i, u in enumerate(seeds)}

    def _log(msg):
        if progress:
            progress(msg)

    # 策略 1+2：目录
    try:
        first_page = fetcher.fetch(seeds[0])
        toc_link = find_toc_link(first_page)
        if toc_link:
            _log(f"发现目录页：{toc_link}")
            try:
                toc_page = fetcher.fetch(toc_link)
                toc_links = parse_toc_page(toc_page)
                if len(toc_links) >= 5:
                    found = [u for _, u in toc_links]
                    order_index = {u: i for i, u in enumerate(found)}
                    _log(f"目录解析到 {len(found)} 个章节")
                    return _finalize(found, seeds, order_index, max_chapters)
            except FetchError:
                _log("目录页抓取失败，尝试其他策略")
        # 内嵌列表
        embedded = find_embedded_chapter_list(first_page)
        if len(embedded) >= 8:
            found = [u for _, u in embedded]
            order_index = {u: i for i, u in enumerate(found)}
            _log(f"页面内嵌目录解析到 {len(found)} 个章节")
            return _finalize(found, seeds, order_index, max_chapters)
    except FetchError as e:
        _log(f"目录发现失败：{e}")

    # 策略 3：数字推断
    _log("未找到目录，尝试 URL 数字模式推断...")
    inferred = infer_by_url_pattern(fetcher, seeds, max_chapters, progress=_log)
    if len(inferred) > len(seeds):
        merged = utils.dedupe_keep_order(
            list(seeds) + [u for u in inferred if u not in set(seeds)])
        order_index = {}
        return _finalize(merged, seeds, order_index, max_chapters)

    # 策略 4：上下章行走
    _log("数字推断无结果，尝试沿上下章链接行走...")
    chain = []
    visited_all = set()
    for seed in seeds:
        if seed in visited_all:
            continue
        back = walk_by_next_link(fetcher, seed, max_chapters, forward=False)
        back.reverse()
        fwd = walk_by_next_link(fetcher, seed, max_chapters, forward=True)
        for u in back + fwd:
            if u not in visited_all:
                visited_all.add(u)
                chain.append(u)
    if len(chain) > len(seeds):
        return _finalize(chain, seeds, {}, max_chapters)

    # 全部失败：返回种子本身
    return _finalize(seeds, seeds, {}, max_chapters)


def _finalize(found: list, seeds: list, order_index: dict, max_chapters: int) -> list:
    """最终整理：去重、排序、裁剪、确保包含全部种子。"""
    seen, merged = set(), []
    for u in found:
        u = utils.normalize_url(u)
        if not u or u in seen:
            continue
        seen.add(u)
        merged.append(u)
    for s in seeds:
        if s not in seen:
            merged.append(s)
            seen.add(s)
    # 排序：优先目录顺序；否则按 URL 数字
    sorted_urls = sorted(merged, key=lambda u: _sort_key(u, order_index))
    if len(sorted_urls) > max_chapters:
        # 裁剪时保留种子
        keep = [u for u in sorted_urls if u in set(seeds)]
        extra = [u for u in sorted_urls if u not in set(seeds)]
        sorted_urls = (keep + extra)[:max_chapters]
    return sorted_urls
