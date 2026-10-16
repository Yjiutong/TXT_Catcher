# -*- coding: utf-8 -*-
"""集成测试：DownloadManager + SQLite + 导出，走完整下载流程（本地模拟站）。"""
import os
import sys
import time
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from novel_catcher.config import Config
from novel_catcher.db import DB, STATUS_DONE
from novel_catcher.manager import DownloadManager
from mock_site import MockSite, BASE


def main():
    site = MockSite().start()
    tmp = tempfile.mkdtemp(prefix="txtcatcher_int_")
    try:
        cfg = Config()
        cfg.set("output_dir", os.path.join(tmp, "out"))
        cfg.set("delay", 0.0)
        cfg.set("timeout", 10)
        cfg.set("retries", 1)
        cfg.set("concurrency", 2)
        cfg.set("chapter_pool", 2)

        db_path = os.path.join(tmp, "test.db")
        db = DB(db_path)
        logs = []
        mgr = DownloadManager(db, cfg, logger=logs.append)
        book_id = mgr.add_download("集成测试书", "测试作者",
                                   [f"{BASE}/ba/2.html", f"{BASE}/ba/7.html"])
        print(f"book_id={book_id}")

        # 等待完成事件（最长 60s）
        deadline = time.time() + 60
        done = False
        while time.time() < deadline:
            try:
                evt, payload = mgr.events.get(timeout=2)
                if evt == "progress":
                    print(f"  progress: {payload['pct']}% {payload['msg']}")
                elif evt == "book_done":
                    print("  DONE:", payload["title"], payload["chapters"], "章",
                          payload["words"], "字")
                    done = True
                    break
                elif evt == "book_failed":
                    print("  FAILED:", payload["error"])
                    break
            except Exception:
                continue
        if not done:
            print("  TIMEOUT waiting for completion")
            return 1

        book = db.get_book(book_id)
        assert book["status"] == STATUS_DONE, book["status"]
        assert book["chapters_found"] == 12, book["chapters_found"]
        assert book["word_count"] > 500, book["word_count"]
        assert os.path.exists(book["txt_path"]), book["txt_path"]
        assert os.path.exists(book["epub_path"]), book["epub_path"]
        size_txt = os.path.getsize(book["txt_path"])
        size_epub = os.path.getsize(book["epub_path"])
        print(f"TXT {size_txt}B EPUB {size_epub}B")
        assert size_txt > 3000 and size_epub > 2000

        # 列表接口
        books = db.list_books()
        assert len(books) == 1
        print("INTEGRATION OK")
        return 0
    finally:
        site.stop()


if __name__ == "__main__":
    sys.exit(main())
