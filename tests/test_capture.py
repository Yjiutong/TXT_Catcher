# -*- coding: utf-8 -*-
"""阅读浏览器捕获包测试：分类、去重、导出包、整理为 BookResult。"""
import json
import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from novel_catcher.capture import build_book_from_package, capture_page
from novel_catcher.capture import CaptureSession, KIND_CHAPTER, KIND_TOC
from novel_catcher.config import Config
from novel_catcher.crawler.http import HttpFetcher
from mock_site import MockSite, BASE


class TestCapture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.site = MockSite().start()
        cls.cfg = Config()
        cls.fetcher = HttpFetcher(cls.cfg)

    @classmethod
    def tearDownClass(cls):
        cls.site.stop()

    def test_classify_toc_and_chapter(self):
        toc_page = self.fetcher.fetch(f"{BASE}/ba/index.html")
        chapter_page = self.fetcher.fetch(f"{BASE}/ba/1.html")
        self.assertEqual(capture_page(toc_page)["kind"], KIND_TOC)
        self.assertEqual(capture_page(chapter_page)["kind"], KIND_CHAPTER)

    def test_session_dedupe_and_package(self):
        session = CaptureSession()
        session.add(self.fetcher.fetch(f"{BASE}/ba/index.html"))
        session.add(self.fetcher.fetch(f"{BASE}/ba/1.html"))
        session.add(self.fetcher.fetch(f"{BASE}/ba/2.html"))
        session.add(self.fetcher.fetch(f"{BASE}/ba/1.html"))  # 重复 URL 不重复入库
        self.assertEqual(len(session.records), 3)

        out_dir = tempfile.mkdtemp()
        zip_path = session.save_package(out_dir)
        self.assertTrue(zipfile.is_zipfile(zip_path))
        with zipfile.ZipFile(zip_path) as z:
            with z.open("pages.json") as f:
                pkg = json.load(f)
        self.assertEqual(pkg["format"], "txt_catcher_browser_capture")
        self.assertEqual(len(pkg["pages"]), 3)

        book = build_book_from_package(pkg)
        self.assertGreaterEqual(book.chapter_count, 2)
        self.assertTrue(book.word_count > 0)

    def test_build_book_uses_toc_order(self):
        session = CaptureSession()
        session.add(self.fetcher.fetch(f"{BASE}/ba/index.html"))
        session.add(self.fetcher.fetch(f"{BASE}/ba/3.html"))
        session.add(self.fetcher.fetch(f"{BASE}/ba/1.html"))
        pkg = session.to_package()
        book = build_book_from_package(pkg)
        titles = [ch.title for ch in book.chapters]
        self.assertIn("第01章·测试回目A", titles)
        self.assertIn("第03章·测试回目C", titles)
        self.assertLess(titles.index("第01章·测试回目A"),
                        titles.index("第03章·测试回目C"))


if __name__ == "__main__":
    unittest.main()

