# -*- coding: utf-8 -*-
"""抓取管线：条目抓取、正文分页合并、条目集合整合。"""
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from .http import HttpFetcher, FetchError
from . import discover, extract
from .rules import get_rules, rule_for
from . import utils
from .config import Config


class CancelledError(Exception):
    """任务被用户取消。"""


class Item:
    """单个内容条目。"""

    __slots__ = ("url", "title", "paragraphs", "word_count")

    def __init__(self, url: str, title: str, paragraphs: list):
        self.url = url
        self.title = title or "未命名条目"
        self.paragraphs = paragraphs or []
        self.word_count = utils.text_word_count("\n".join(self.paragraphs))

    @property
    def body(self) -> str:
        return "\n\n".join(self.paragraphs)


class Collection:
    """条目集合抓取与整合结果。"""

    def __init__(self, title: str, author: str = "", items: list = None):
        self.title = title or "未命名合集"
        self.author = author or ""
        self.items = items or []
        self.word_count = sum(c.word_count for c in self.items)
        self.item_count = len(self.items)


class ItemFetcher:
    """负责抓取单个内容条目（含正文分页合并）。"""

    def __init__(self, fetcher: HttpFetcher, config: Config, rules=None):
        self.fetcher = fetcher
        self.config = config
        self.rules = rules if rules is not None else get_rules(config)

    def fetch(self, url: str) -> Item:
        max_pages = self.config.get("max_item_pages", 5)
        rule = rule_for(url, self.rules)
        visited = []
        cur = url
        base_title = ""
        all_paras = []
        while cur and cur not in visited and len(visited) < max_pages:
            visited.append(cur)
            page = self.fetcher.fetch(cur)
            # 规则定位优先，失败回退启发式
            container = extract.extract_content_by_rule(page.soup, rule)
            if container is None:
                container = extract.find_content_container(page.soup)
            # 遍历全页链接找后续分页（正文清洗会删除导航元素，必须在清洗前找）
            cands = extract.find_pagination_candidates(page, container)
            paras = extract.extract_paragraphs(container)
            title = extract.extract_title_by_rule(page.soup, rule)
            if not title:
                title = extract.extract_content_title(page, container)
            if not base_title:
                base_title = title
            if paras:
                all_paras.extend(paras)
            if not cands:
                break
            # 逐个候选预取：条目核心与本条一致 → 是分页；不一致（下一条/列表）→ 跳过
            nxt = ""
            for cand in cands[:8]:
                if cand in visited:
                    continue
                try:
                    probe = self.fetcher.fetch(cand)
                except FetchError:
                    continue
                probe_cont = extract.extract_content_by_rule(probe.soup, rule)
                if probe_cont is None:
                    probe_cont = extract.find_content_container(probe.soup)
                probe_title = extract.extract_title_by_rule(probe.soup, rule)
                if not probe_title:
                    probe_title = extract.extract_content_title(probe, probe_cont)
                if probe_title and base_title:
                    t1 = extract.content_core(base_title)
                    t2 = extract.content_core(probe_title)
                    if t1 and t2 and t1 != t2:
                        continue  # 是下一条/列表页，不是本条分页
                nxt = cand
                break
            if not nxt:
                break
            cur = nxt
        return Item(url, base_title, all_paras)


class Collector:
    """从种子 URL 抓取完整条目集合。"""

    def __init__(self, fetcher: HttpFetcher, config: Config, progress=None):
        self.fetcher = fetcher
        self.config = config
        self.progress = progress or (lambda msg, pct, detail="": None)

    def _report(self, msg: str, pct: float, detail: str = ""):
        try:
            self.progress(msg, pct, detail)
        except Exception:
            pass

    def crawl(self, seed_urls: list, title_hint: str = "", author_hint: str = "",
              cancel_check=None, rules=None) -> Collection:
        cancel_check = cancel_check or (lambda: False)
        if rules is None:
            rules = get_rules(self.config)

        self._report("正在分析条目位置...", 2, "推测目标条目的列表")
        max_items = self.config.get("max_items", 8000)
        urls = discover.discover_items(self.fetcher, seed_urls,
                                       max_items=max_items,
                                       rules=rules,
                                       progress=lambda m: self._report(m, 3, ""))
        if not urls:
            raise FetchError("未能发现任何条目页面")
        if len(urls) > max_items:
            urls = urls[:max_items]
        self._report(f"已定位 {len(urls)} 个条目，开始抓取正文...", 5,
                     f"共 {len(urls)} 条")

        # 标题/作者留空时自动从首个条目页提取页面元信息
        if not title_hint or not author_hint:
            try:
                meta_page = self.fetcher.fetch(urls[0])
                page_title, page_author = extract.extract_metadata(meta_page)
                if not title_hint:
                    title_hint = page_title or ""
                if not author_hint:
                    author_hint = page_author or ""
                if title_hint or author_hint:
                    self._report(
                        f"自动识别：{title_hint or '?'} / {author_hint or '(无作者)'}",
                        5, "已提取页面元信息")
            except FetchError:
                pass

        # 并发抓取条目
        pool_size = max(1, int(self.config.get("item_pool", 4)))
        items = [None] * len(urls)
        cf = ItemFetcher(self.fetcher, self.config, rules=rules)
        done = 0
        with ThreadPoolExecutor(max_workers=pool_size) as pool:
            futures = {pool.submit(cf.fetch, u): i for i, u in enumerate(urls)}
            for fut in as_completed(futures):
                idx = futures[fut]
                try:
                    items[idx] = fut.result()
                except FetchError as e:
                    items[idx] = Item(urls[idx], f"抓取失败：{urls[idx]}",
                                      [f"[条目抓取失败：{e}]"])
                done += 1
                if cancel_check():
                    pool.shutdown(wait=False, cancel_futures=True)
                    raise CancelledError("用户取消了任务")
                pct = 5 + 90 * done / max(1, len(urls))
                self._report(f"抓取正文 {done}/{len(urls)}", pct,
                             f"已完成 {done} 条")

        # 整合：去重条目（按 URL 与标题）
        seen_keys, final = set(), []
        for it in items:
            if it is None:
                continue
            key = it.url
            if key in seen_keys:
                continue
            seen_keys.add(key)
            final.append(it)

        return Collection(title_hint, author_hint, final)
