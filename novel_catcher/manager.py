# -*- coding: utf-8 -*-
"""下载任务管理：并发调度、取消、进度事件（供 GUI 轮询）。"""
import os
import queue
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor

from .config import Config
from .db import DB, STATUS_QUEUED, STATUS_RUNNING, STATUS_DONE, STATUS_FAILED, STATUS_CANCELLED
from .crawler.http import HttpFetcher, FetchError
from .crawler.pipeline import BookCrawler, CancelledError
from .exporter.txt import export_txt, default_txt_path
from .exporter.epub import export_epub, default_epub_path
from . import utils


class DownloadManager:
    """管理书籍下载任务：并发执行、进度上报、取消。"""

    def __init__(self, db: DB, config: Config, logger=None):
        self.db = db
        self.config = config
        self.logger = logger or (lambda msg: None)
        self.events = queue.Queue()  # (event_type, payload)
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, config.get("concurrency", 2)),
            thread_name_prefix="book")
        self._futures = {}      # book_id -> future
        self._cancels = set()   # 已取消的 book_id
        self._lock = threading.Lock()

    # ---- 对外接口 ----
    def add_download(self, title: str, author: str, seed_urls: list) -> int:
        seeds = [utils.normalize_url(u) for u in seed_urls if utils.normalize_url(u)]
        if not seeds:
            raise ValueError("没有有效的章节网址")
        book_id = self.db.add_book(title, author, seeds)
        self.events.put(("book_added", {"book_id": book_id, "title": title}))
        fut = self._executor.submit(self._run_book, book_id, title, author, seeds)
        with self._lock:
            self._futures[book_id] = fut
        return book_id

    def cancel(self, book_id: int):
        with self._lock:
            self._cancels.add(book_id)

    def is_cancelled(self, book_id: int) -> bool:
        with self._lock:
            return book_id in self._cancels

    def clear_finished(self):
        """清理已结束任务（供 GUI 刷新用）。"""
        pass

    def shutdown(self):
        try:
            self._executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass

    # ---- 内部 ----
    def _log(self, msg: str):
        try:
            self.logger(msg)
        except Exception:
            pass

    def _run_book(self, book_id: int, title: str, author: str, seeds: list):
        self.db.set_status(book_id, STATUS_RUNNING)
        self.events.put(("status", {"book_id": book_id, "status": STATUS_RUNNING}))
        fetcher = HttpFetcher(self.config, logger=lambda m: self._log(f"[{title}] {m}"))

        def progress(msg: str, pct: float, detail: str = ""):
            if self.is_cancelled(book_id):
                raise CancelledError("用户取消了下载任务")
            self.events.put(("progress", {
                "book_id": book_id, "title": title, "pct": round(pct, 1),
                "msg": msg, "detail": detail}))

        def cancel_check():
            return self.is_cancelled(book_id)

        try:
            crawler = BookCrawler(fetcher, self.config, progress=progress)
            book = crawler.crawl(seeds, title_hint=title, author_hint=author,
                                 cancel_check=cancel_check)
            if self.is_cancelled(book_id):
                raise CancelledError("用户取消了下载任务")

            # 导出
            progress("正在生成 TXT / EPUB...", 96, "整合输出")
            output_dir = self.config.get("output_dir")
            os.makedirs(output_dir, exist_ok=True)
            txt_path = default_txt_path(output_dir, book)
            epub_path = default_epub_path(output_dir, book)
            export_txt(book, txt_path)
            try:
                export_epub(book, epub_path)
            except Exception as e:
                self._log(f"[{title}] EPUB 生成失败（已保留 TXT）：{e}")
                epub_path = ""

            self.db.update_book(
                book_id, status=STATUS_DONE, chapters_found=book.chapter_count,
                chapters_fetched=book.chapter_count, word_count=book.word_count,
                txt_path=txt_path, epub_path=epub_path, error="")
            self.events.put(("book_done", {
                "book_id": book_id, "title": book.title, "author": book.author,
                "chapters": book.chapter_count, "words": book.word_count,
                "txt_path": txt_path, "epub_path": epub_path}))
            self._log(f"[{title}] 完成：{book.chapter_count} 章，{utils.format_word_count(book.word_count)} 字")
        except CancelledError:
            self.db.set_status(book_id, STATUS_CANCELLED)
            self.events.put(("status", {"book_id": book_id, "status": STATUS_CANCELLED}))
        except Exception as e:
            msg = f"{type(e).__name__}: {e}"
            traceback.print_exc()
            self.db.set_status(book_id, STATUS_FAILED, error=msg)
            self.events.put(("book_failed", {"book_id": book_id, "error": msg}))
            self._log(f"[{title}] 失败：{msg}")
        finally:
            with self._lock:
                self._cancels.discard(book_id)
                self._futures.pop(book_id, None)
