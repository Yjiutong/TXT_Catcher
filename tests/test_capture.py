# -*- coding: utf-8 -*-
"""捕获包测试：页面分类、去重、导出包、整理为 Collection。"""
import json
import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from txt_catcher.capture import build_collection_from_package, capture_page
from txt_catcher.capture import CaptureSession, KIND_ITEM, KIND_LIST
from txt_catcher.config import Config
from txt_catcher.http import HttpFetcher
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

    def test_classify_list_and_item(self):
        list_page = self.fetcher.fetch(f"{BASE}/ba/index.html")
        item_page = self.fetcher.fetch(f"{BASE}/ba/1.html")
        self.assertEqual(capture_page(list_page)["kind"], KIND_LIST)
        self.assertEqual(capture_page(item_page)["kind"], KIND_ITEM)

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
        self.assertEqual(pkg["format"], "txt_catcher_capture")
        self.assertEqual(pkg["schema_version"], 2)
        self.assertEqual(len(pkg["pages"]), 3)

        coll = build_collection_from_package(pkg)
        self.assertGreaterEqual(coll.item_count, 2)
        self.assertTrue(coll.word_count > 0)

    def test_build_collection_uses_list_order(self):
        session = CaptureSession()
        session.add(self.fetcher.fetch(f"{BASE}/ba/index.html"))
        session.add(self.fetcher.fetch(f"{BASE}/ba/3.html"))
        session.add(self.fetcher.fetch(f"{BASE}/ba/1.html"))
        pkg = session.to_package()
        coll = build_collection_from_package(pkg)
        titles = [it.title for it in coll.items]
        self.assertIn("第01章·测试回目A", titles)
        self.assertIn("第03章·测试回目C", titles)
        self.assertLess(titles.index("第01章·测试回目A"),
                        titles.index("第03章·测试回目C"))


if __name__ == "__main__":
    unittest.main()
