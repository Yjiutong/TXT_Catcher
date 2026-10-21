# -*- coding: utf-8 -*-
"""抓取管线：章节抓取、正文分页合并、整本书整合。"""
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from .http import HttpFetcher, FetchError
from . import discover, extract
from .rules import get_rules, rule_for
from .. import utils
from ..config import Config


class CancelledError(Exception):
    """任务被用户取消。"""


class Chapter:
    """单章内容。"""

    __slots__ = ("url", "title", "paragraphs", "word_count")

    def __init__(self, url: str, title: str, paragraphs: list):
        self.url = url
        self.title = title or "未命名章节"
        self.paragraphs = paragraphs or []
        self.word_count = utils.text_word_count("\n".join(self.paragraphs))

    @property
    def body(self) -> str:
        return "\n\n".join(self.paragraphs)


class BookResult:
    """整本书抓取与整合结果。"""

    def __init__(self, title: str, author: str, chapters: list):
        self.title = title or "未命名书籍"
        self.author = author or "佚名"
        self.chapters = chapters
        self.word_count = sum(c.word_count for c in chapters)
        self.chapter_count = len(chapters)


class ChapterFetcher:
    """负责抓取单个章节（含正文分页合并）。"""

    def __init__(self, fetcher: HttpFetcher, config: Config, rules=None):
        self.fetcher = fetcher
        self.config = config
        self.rules = rules if rules is not None else get_rules(config)

    def fetch(self, url: str) -> Chapter:
        max_pages = self.config.get("max_chapter_pages", 5)
        rule = rule_for(url, self.rules)
        visited = []
        cur = url
        base_title = ""
        all_paras = []
        while cur and cur not in visited and len(visited) < max_pages:
            visited.append(cur)
            page = self.fetcher.fetch(cur)
            # 规则定位优先，失败回退启发式
            container = extract.extract_chapter_by_rule(page.soup, rule)
            if container is None:
                container = extract.find_content_container(page.soup)
            # 遍历全页链接找后续分页（正文清洗会删除导航元素，必须在清洗前找）
            cands = extract.find_pagination_candidates(page, container)
            paras = extract.extract_paragraphs(container)
            title = extract.extract_title_by_rule(page.soup, rule)
            if not title:
                title = extract.extract_chapter_title(page, container)
            if not base_title:
                base_title = title
            if paras:
                all_paras.extend(paras)
            if not cands:
                break
            # 逐个候选预取：章节核心与本章一致 → 是分页；不一致（下一章/目录）→ 跳过
            nxt = ""
            for cand in cands[:8]:
                if cand in visited:
                    continue
                try:
                    probe = self.fetcher.fetch(cand)
                except FetchError:
                    continue
                probe_cont = extract.extract_chapter_by_rule(probe.soup, rule)
                if probe_cont is None:
                    probe_cont = extract.find_content_container(probe.soup)
                probe_title = extract.extract_title_by_rule(probe.soup, rule)
                if not probe_title:
                    probe_title = extract.extract_chapter_title(probe, probe_cont)
                if probe_title and base_title:
                    t1 = extract.chapter_core(base_title)
                    t2 = extract.chapter_core(probe_title)
                    if t1 and t2 and t1 != t2:
                        continue  # 是下一章/目录页，不是本章分页
                nxt = cand
                break
            if not nxt:
                break
            cur = nxt
        return Chapter(url, base_title, all_paras)


class BookCrawler:
    """一本书的完整抓取流程。"""

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
              cancel_check=None, rules=None) -> BookResult:
        cancel_check = cancel_check or (lambda: False)
        if rules is None:
            rules = get_rules(self.config)

        self._report("正在分析章节位置...", 2, "推测整本书的章节列表")
        max_ch = self.config.get("max_chapters", 8000)
        urls = discover.discover_chapters(self.fetcher, seed_urls,
                                          max_chapters=max_ch,
                                          rules=rules,
                                          progress=lambda m: self._report(m, 3, ""))
        if not urls:
            raise FetchError("未能发现任何章节页面")
        if len(urls) > max_ch:
            urls = urls[:max_ch]
        self._report(f"已定位 {len(urls)} 个章节，开始抓取正文...", 5,
                     f"共 {len(urls)} 章")

        # 书名/作者留空时自动从首个章节页提取（NovelGetter 的元信息解析思路）
        if not title_hint or not author_hint:
            try:
                meta_page = self.fetcher.fetch(urls[0])
                page_title, page_author = extract.extract_book_metadata(meta_page)
                if not title_hint:
                    title_hint = page_title or ""
                if not author_hint:
                    author_hint = page_author or ""
                if title_hint or author_hint:
                    self._report(
                        f"自动识别：{title_hint or '?'} / {author_hint or '佚名'}",
                        5, "已提取页面元信息")
            except FetchError:
                pass

        # 并发抓取章节
        pool_size = max(1, int(self.config.get("chapter_pool", 3)))
        chapters = [None] * len(urls)
        cf = ChapterFetcher(self.fetcher, self.config, rules=rules)
        done = 0
        with ThreadPoolExecutor(max_workers=pool_size) as pool:
            futures = {pool.submit(cf.fetch, u): i for i, u in enumerate(urls)}
            for fut in as_completed(futures):
                idx = futures[fut]
                try:
                    chapters[idx] = fut.result()
                except FetchError as e:
                    chapters[idx] = Chapter(urls[idx], f"抓取失败：{urls[idx]}",
                                            [f"[章节抓取失败：{e}]"])
                done += 1
                if cancel_check():
                    pool.shutdown(wait=False, cancel_futures=True)
                    raise CancelledError("用户取消了下载任务")
                pct = 5 + 90 * done / max(1, len(urls))
                self._report(f"抓取正文 {done}/{len(urls)}", pct,
                             f"已完成 {done} 章")

        # 整合：去重章节（按 URL 与标题）
        seen_keys, final = set(), []
        for ch in chapters:
            if ch is None:
                continue
            key = ch.url
            if key in seen_keys:
                continue
            seen_keys.add(key)
            final.append(ch)

        book = BookResult(title_hint, author_hint, final)
        return book
