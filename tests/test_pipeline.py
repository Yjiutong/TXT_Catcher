# -*- coding: utf-8 -*-
"""管线端到端测试：对本地模拟站跑完整流程并断言结果。"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from novel_catcher.config import Config
from novel_catcher.crawler.http import HttpFetcher
from novel_catcher.crawler import discover
from novel_catcher.crawler.pipeline import BookCrawler
from novel_catcher.exporter.txt import export_txt
from novel_catcher.exporter.epub import export_epub

from mock_site import MockSite, BASE

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {detail}")


def main():
    site = MockSite().start()
    try:
        cfg = Config()
        cfg.set("delay", 0.0)
        cfg.set("timeout", 10)
        cfg.set("retries", 1)
        cfg.set("chapter_pool", 2)
        cfg.set("max_chapters", 500)
        fetcher = HttpFetcher(cfg)

        # ---------- 场景 A：目录页发现（UTF-8，含广告与分页） ----------
        print("== 场景A：目录页发现 ==")
        urls = discover.discover_chapters(
            fetcher, [f"{BASE}/ba/2.html", f"{BASE}/ba/7.html"],
            max_chapters=cfg.get("max_chapters"))
        check("A1 推测到全部12章", len(urls) == 12, f"got {len(urls)}")
        check("A2 按目录顺序排列", urls[0] == f"{BASE}/ba/1.html"
              and urls[11] == f"{BASE}/ba/12.html", urls[:3])
        book = BookCrawler(fetcher, cfg).crawl(
            [f"{BASE}/ba/2.html"], title_hint="测试小说", author_hint="罗贯中")
        check("A3 抓取12章", book.chapter_count == 12, f"got {book.chapter_count}")
        ch3 = book.chapters[2]
        check("A4 第3章分页已合并（13段）", len(ch3.paragraphs) == 13,
              f"paras={len(ch3.paragraphs)} words={ch3.word_count}")
        check("A5 第1章正文含测试文本",
              "却说此人姓甚名谁" in book.chapters[0].body)
        ad_hit = any("天才一秒记住" in p or "广告" in p or "版权所有" in p
                     for ch in book.chapters for p in ch.paragraphs)
        check("A6 广告行已清除", not ad_hit)
        check("A7 章节标题正确", book.chapters[0].title == "第01章·测试回目A",
              book.chapters[0].title)

        # ---------- 场景 B：GBK + 零填充数字 URL 推断 ----------
        print("== 场景B：GBK编码 + 数字模式推断 ==")
        urls_b = discover.discover_chapters(
            fetcher, [f"{BASE}/bb/第001章.html", f"{BASE}/bb/第005章.html"],
            max_chapters=cfg.get("max_chapters"))
        check("B1 推测到全部8章", len(urls_b) == 8, f"got {len(urls_b)}")
        check("B2 零填充保持", f"{BASE}/bb/第002章.html" in urls_b, urls_b[:4])
        book_b = BookCrawler(fetcher, cfg).crawl([f"{BASE}/bb/第001章.html"],
                                                 title_hint="GBK书")
        check("B3 GBK内容正确解码", book_b.chapter_count == 8
              and "却说此人姓甚名谁" in book_b.chapters[0].body,
              book_b.chapters[0].body[:30])

        # ---------- 场景 C：无数字URL + 上下章链接行走 ----------
        print("== 场景C：上下章链接行走 ==")
        urls_c = discover.discover_chapters(
            fetcher, [f"{BASE}/bc/chapter-four.html"],
            max_chapters=cfg.get("max_chapters"))
        check("C1 行走得到全部6章", len(urls_c) == 6, f"got {len(urls_c)}")
        check("C2 顺序正确", urls_c[0].endswith("chapter-one.html")
              and urls_c[-1].endswith("chapter-six.html"), urls_c)

        # ---------- 场景 D：导出 TXT + EPUB ----------
        print("== 场景D：导出 ==")
        tmp = tempfile.mkdtemp(prefix="txtcatcher_test_")
        try:
            txt = os.path.join(tmp, "测试小说.txt")
            epub_p = os.path.join(tmp, "测试小说.epub")
            export_txt(book, txt)
            export_epub(book, epub_p)
            check("D1 TXT 文件存在且非空", os.path.getsize(txt) > 5000,
                  f"size={os.path.getsize(txt)}")
            check("D2 EPUB 文件存在且非空", os.path.getsize(epub_p) > 3000,
                  f"size={os.path.getsize(epub_p)}")
            with open(txt, encoding="utf-8") as f:
                content = f.read()
            check("D3 TXT 含目录", "目 录" in content and "第12章" in content)
            check("D4 TXT 含全书正文", content.count("=" * 30) >= 13)
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

        print(f"\n结果：{PASS} 通过，{FAIL} 失败")
        return 1 if FAIL else 0
    finally:
        site.stop()


if __name__ == "__main__":
    sys.exit(main())
