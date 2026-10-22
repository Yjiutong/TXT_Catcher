# -*- coding: utf-8 -*-
"""集成测试：Collector 全流程抓取 → 结构化集合包 → 捕获包 → 导出（本地模拟站）。"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from txt_catcher.config import Config
from txt_catcher.capture import CaptureSession
from txt_catcher.http import HttpFetcher
from txt_catcher.pipeline import Collector
from txt_catcher.export import collection_to_package, export_package, load_package

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
        cfg.set("item_pool", 2)
        fetcher = HttpFetcher(cfg)

        # 1) 自动抓取：列表发现 + 并发抓取 + 分页合并
        collector = Collector(fetcher, cfg)
        coll = collector.crawl([f"{BASE}/ba/2.html", f"{BASE}/ba/7.html"],
                               title_hint="集成测试书", author_hint="测试作者")
        assert coll.item_count == 12, coll.item_count
        assert coll.word_count > 500, coll.word_count
        pkg = collection_to_package(coll)
        assert pkg["format"] == "txt_catcher_collection"
        assert len(pkg["items"]) == 12

        # 2) 导出 md / txt / json 并回读
        md = os.path.join(tmp, "集成测试书.md")
        js = os.path.join(tmp, "集成测试书.json")
        export_package(pkg, fmt="md", out=md)
        export_package(pkg, fmt="json", out=js)
        assert os.path.getsize(md) > 5000, os.path.getsize(md)
        assert os.path.getsize(js) > 3000, os.path.getsize(js)
        with open(md, encoding="utf-8") as f:
            assert "集成测试书" in f.read()

        # 3) 捕获包：手动收集若干页面（列表页 + 内容页 + 分页页）
        session = CaptureSession()
        session.add(fetcher.fetch(f"{BASE}/ba/index.html"))
        session.add(fetcher.fetch(f"{BASE}/ba/1.html"))
        session.add(fetcher.fetch(f"{BASE}/ba/3.html"))
        session.add(fetcher.fetch(f"{BASE}/ba/3_2.html"))
        zip_path = session.save_package(os.path.join(tmp, "captures"))
        assert os.path.getsize(zip_path) > 500, os.path.getsize(zip_path)

        # 4) 从捕获包 zip 回读并整理为 Collection
        pkg2 = load_package(zip_path)
        assert pkg2["format"] == "txt_catcher_capture"
        assert pkg2["schema_version"] == 2
        assert pkg2["summary"]["pages"] == 4
        from txt_catcher.capture import build_collection_from_package
        coll2 = build_collection_from_package(pkg2)
        assert coll2.item_count >= 3, coll2.item_count  # 1/3/3_2 合并为一条
        assert coll2.word_count > 0
        md2 = os.path.join(tmp, "回读.md")
        export_package(pkg2, fmt="md", out=md2)
        assert os.path.getsize(md2) > 1000

        print("INTEGRATION OK")
        return 0
    finally:
        site.stop()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
