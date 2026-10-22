# -*- coding: utf-8 -*-
"""条目发现：列表页解析 / 内嵌条目列表 / URL 数字模式推断 / 上下条目链。

用户只提供若干内容页网址，本模块负责推测出完整条目的 URL 列表。
"""
import re
import time
from urllib.parse import urljoin, urlparse

from .http import HttpFetcher, FetchError, Page
from . import extract
from .rules import rule_for
from . import utils

# 目录页链接文本
_LIST_TEXT_RE = re.compile(
    r"^(章节目录|全部章节|章节列表|章节目录|小说目录|作品目录|本书目录|书目录|"
    r"查看目录|看目录|目录页|作品相关|目录|章节目录列表|章节|返回目录|回目录)$",
    re.I,
)
_LIST_TEXT_SUB_RE = re.compile(r"(章节目录|全部章节|章节列表|目录)", re.I)
_TOC_IDCLASS_RE = re.compile(
    r"(catalog|chapterlist|chapter-list|booklist|book-list|mulu|toc|chapter_index|"
    r"zhangjie|chapter-list-container|listmain|dir|menu-main|chapterList)", re.I)

# 目录页里应排除的非正文链接
_NON_ITEM_TEXT_RE = re.compile(
    r"(首页|登录|注册|书架|搜索|排行|完本|最近更新|最新更新|书评|论坛|"
    r"关于我们|联系我们|帮助|下载|分享|加入书签|收藏本页|设为首页|"
    r"返回|上一页|下一页|末页|第1页|第2页|作者的话|公告|简介|封面)",
    re.I,
)


def _anchor_text(a) -> str:
    return a.get_text(" ", strip=True)


def find_list_link(page: Page) -> str:
    """从内容页找“列表/目录”链接。"""
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
        if _LIST_TEXT_RE.search(text):
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
        if _LIST_TEXT_SUB_RE.search(text):
            abs_url = page.resolve(href)
            if abs_url and abs_url != page.url:
                return abs_url
    return ""


def _toc_like_element(el) -> bool:
    idc = extract._element_id_class(el)
    return bool(_TOC_IDCLASS_RE.search(idc))


def find_embedded_list(page: Page, rule=None) -> list:
    """查找内容页内嵌的完整条目列表元素（侧栏/底部列表）。

    有站点规则时优先用规则的 toc 选择器；返回 (title, url) 列表。
    """
    soup = page.soup
    if soup is None:
        return []
    if rule and (rule.get("toc") or ""):
        try:
            el = soup.select_one(rule["toc"])
        except Exception:
            el = None
        if el is not None and len(el.find_all("a", href=True)) >= 8:
            return _parse_link_list(el, page)
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


def parse_list_page(page: Page, rule=None) -> list:
    """解析列表页，返回 (title, url) 条目列表。

    有站点规则时优先用规则的 toc 选择器定位目录容器，否则启发式。
    """
    soup = page.soup
    if soup is None:
        return []
    if rule and (rule.get("toc") or ""):
        try:
            el = soup.select_one(rule["toc"])
        except Exception:
            el = None
        if el is not None:
            links = _parse_link_list(el, page)
            if len(links) >= 5:
                return links
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


def _find_list_link_rule(page: Page, rule) -> str:
    """按规则的 toc_link 选择器找“列表/目录”入口链接。"""
    if page is None or page.soup is None or not (rule or {}).get("toc_link"):
        return ""
    try:
        el = page.soup.select_one(rule["toc_link"])
    except Exception:
        return ""
    if el is None:
        return ""
    href = (el.get("href") or "").strip()
    if not href or href.startswith(("javascript:", "#", "mailto:")):
        return ""
    abs_url = page.resolve(href)
    return abs_url if abs_url and abs_url != page.url else ""


def _parse_link_list(scope, page: Page) -> list:
    """从元素内收集条目链接，过滤噪音，保持顺序去重。"""
    seen = set()
    out = []
    for a in scope.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("javascript:", "#", "mailto:", "tel:")):
            continue
        text = _anchor_text(a)
        if not text or len(text) > 80:
            continue
        if _NON_ITEM_TEXT_RE.search(text) and len(text) <= 12:
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


def infer_by_url_pattern(fetcher: HttpFetcher, seed_urls: list, max_items: int,
                         progress=None, gap_stop: int = 4) -> list:
    """URL 数字模式推断：验证候选页是否为内容页。

    返回有序条目 URL 列表（含种子本身）。连续 gap_stop 次未命中即停止。
    """
    result = set(seed_urls)
    for seed in seed_urls:
        n = utils.extract_url_number(seed)
        if n is None:
            continue
        if len(result) >= max_items:
            break
        cands = _candidate_urls_from_seed(seed, count=max_items)
        misses = 0
        for cand in cands:
            if len(result) >= max_items:
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
            if extract.looks_like_content_page(page):
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


def walk_by_next_link(fetcher: HttpFetcher, start_url: str, max_items: int,
                      forward: bool = True, rule=None) -> list:
    """沿“下一/上一”链接行走，收集条目 URL。有站点规则时用规则的 next 选择器。"""
    urls = []
    visited = set()
    cur = start_url
    while cur and len(urls) < max_items:
        if cur in visited:
            break
        visited.add(cur)
        urls.append(cur)
        try:
            page = fetcher.fetch(cur)
        except FetchError:
            break
        if forward:
            nxt = extract.find_next_link_by_rule(page, rule)
            if not nxt:
                nxt = extract.find_next_link(page)
        else:
            nxt = extract.find_prev_link(page)
        if not nxt or not utils.is_same_host(cur, nxt):
            break
        cur = nxt
    return urls


def _sort_key(url: str, order_index: dict) -> tuple:
    """排序键：列表中的位置优先，其次 URL 数字。"""
    if url in order_index:
        return (0, order_index[url])
    n = utils.extract_url_number(url)
    return (1, n if n is not None else 0)


def discover_items(fetcher: HttpFetcher, seed_urls: list,
                      max_items: int = 8000, rules=None, progress=None) -> list:
    """核心：根据用户提供的若干内容页网址，推测完整条目列表。

    策略优先级：
      0) 站点规则（列表入口 / 列表容器 / 下一个条目选择器，规则优先）
      1) 列表页（内容页里的“列表/目录”链接）→ 完整列表
      2) 内容页内嵌条目列表（侧栏列表）
      3) URL 数字模式推断（向两端扩展并验证）
      4) “上一/下一”链接行走（向前后扩展）

    返回：有序、去重的条目 URL 列表（保证包含所有种子）。
    """
    seeds = [utils.normalize_url(u) for u in seed_urls if utils.normalize_url(u)]
    seeds = utils.dedupe_keep_order(seeds)
    if not seeds:
        raise FetchError("未提供任何有效内容页网址")

    found = list(seeds)
    order_index = {u: i for i, u in enumerate(seeds)}
    # 站点规则：以第一个种子匹配（同站种子规则一致）
    rule = rule_for(seeds[0], rules) if seeds else {}

    def _log(msg):
        if progress:
            progress(msg)

    # 策略 1+2：列表
    try:
        first_page = fetcher.fetch(seeds[0])
        list_link = _find_list_link_rule(first_page, rule) or find_list_link(first_page)
        if list_link:
            _log(f"发现列表页：{list_link}")
            try:
                list_page = fetcher.fetch(list_link)
                list_links = parse_list_page(list_page, rule)
                if len(list_links) >= 5:
                    found = [u for _, u in list_links]
                    order_index = {u: i for i, u in enumerate(found)}
                    _log(f"列表解析到 {len(found)} 个条目")
                    return _finalize(found, seeds, order_index, max_items)
            except FetchError:
                _log("列表页抓取失败，尝试其他策略")
        # 内嵌列表
        embedded = find_embedded_list(first_page, rule)
        if len(embedded) >= 8:
            found = [u for _, u in embedded]
            order_index = {u: i for i, u in enumerate(found)}
            _log(f"页面内嵌列表解析到 {len(found)} 个条目")
            return _finalize(found, seeds, order_index, max_items)
    except FetchError as e:
        _log(f"列表发现失败：{e}")

    # 策略 3：数字推断
    _log("未找到列表，尝试 URL 数字模式推断...")
    inferred = infer_by_url_pattern(fetcher, seeds, max_items, progress=_log)
    if len(inferred) > len(seeds):
        merged = utils.dedupe_keep_order(
            list(seeds) + [u for u in inferred if u not in set(seeds)])
        order_index = {}
        return _finalize(merged, seeds, order_index, max_items)

    # 策略 4：上下条目行走
    _log("数字推断无结果，尝试沿上下条目链接行走...")
    chain = []
    visited_all = set()
    for seed in seeds:
        if seed in visited_all:
            continue
        back = walk_by_next_link(fetcher, seed, max_items, forward=False, rule=rule)
        back.reverse()
        fwd = walk_by_next_link(fetcher, seed, max_items, forward=True, rule=rule)
        for u in back + fwd:
            if u not in visited_all:
                visited_all.add(u)
                chain.append(u)
    if len(chain) > len(seeds):
        return _finalize(chain, seeds, {}, max_items)

    # 全部失败：返回种子本身
    return _finalize(seeds, seeds, {}, max_items)


def _finalize(found: list, seeds: list, order_index: dict, max_items: int) -> list:
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
    if len(sorted_urls) > max_items:
        # 裁剪时保留种子
        keep = [u for u in sorted_urls if u in set(seeds)]
        extra = [u for u in sorted_urls if u not in set(seeds)]
        sorted_urls = (keep + extra)[:max_items]
    return sorted_urls
