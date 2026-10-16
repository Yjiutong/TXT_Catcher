# -*- coding: utf-8 -*-
"""抓取管线：章节抓取、正文分页合并、整本书整合。"""
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from .http import HttpFetcher, FetchError
from . import discover, extract
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

    def __init__(self, fetcher: HttpFetcher, config: Config):
        self.fetcher = fetcher
        self.config = config

    def fetch(self, url: str) -> Chapter:
        max_pages = self.config.get("max_chapter_pages", 5)
        visited = []
        cur = url
        base_title = ""
        all_paras = []
        while cur and cur not in visited and len(visited) < max_pages:
            visited.append(cur)
            page = self.fetcher.fetch(cur)
            container = extract.find_content_container(page.soup)
            # 先找分页链接（正文清洗会删除导航元素，必须在清洗前找）
            nxt = extract.find_pagination_link(page, container)
            paras = extract.extract_paragraphs(container)
            title = extract.extract_chapter_title(page, container)
            if not base_title:
                base_title = title
            if paras:
                all_paras.extend(paras)
            if not nxt:
                break
            # 防止跑到下一章：预取下一页标题比对（只比对一次）
            if len(visited) == 1:
                try:
                    probe = self.fetcher.fetch(nxt)
                    probe_cont = extract.find_content_container(probe.soup)
                    probe_title = extract.extract_chapter_title(probe, probe_cont)
                    if probe_title and base_title:
                        t1 = extract._TITLE_SEP_RE.sub("", base_title)
                        t2 = extract._TITLE_SEP_RE.sub("", probe_title)
                        if t1 and t2 and t1 != t2:
                            break  # 是下一章，不是分页
                except FetchError:
                    break
                cur = nxt
            else:
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
              cancel_check=None) -> BookResult:
        cancel_check = cancel_check or (lambda: False)

        self._report("正在分析章节位置...", 2, "推测整本书的章节列表")
        max_ch = self.config.get("max_chapters", 8000)
        urls = discover.discover_chapters(self.fetcher, seed_urls,
                                          max_chapters=max_ch,
                                          progress=lambda m: self._report(m, 3, ""))
        if not urls:
            raise FetchError("未能发现任何章节页面")
        if len(urls) > max_ch:
            urls = urls[:max_ch]
        self._report(f"已定位 {len(urls)} 个章节，开始抓取正文...", 5,
                     f"共 {len(urls)} 章")

        # 并发抓取章节
        pool_size = max(1, int(self.config.get("chapter_pool", 3)))
        chapters = [None] * len(urls)
        cf = ChapterFetcher(self.fetcher, self.config)
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
