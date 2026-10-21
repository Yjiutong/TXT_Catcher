# -*- coding: utf-8 -*-
"""站点规则层测试：规则提取 / 标题裁剪 / 规则下一章 / 规则目录 / 失效回退 / 全流程。

混合自 novel_spider 的站点固定选择器思路（.jieqi_title / #content / .next）。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bs4 import BeautifulSoup

from novel_catcher.config import Config
from novel_catcher.crawler.http import HttpFetcher, Page
from novel_catcher.crawler import discover, extract
from novel_catcher.crawler.rules import BUILTIN_RULES, get_rules, rule_for
from novel_catcher.crawler.pipeline import BookCrawler
from mock_site import MockSite, BASE

# 模拟站点规则（对应 BOOK_D/E，host 为 127.0.0.1）
RULE_D = {"host": "127.0.0.1", "title": ".jieqi_title", "content": "#content",
          "next": ".next", "title_strip": "章 节目录 "}
RULE_E = {"host": "127.0.0.1", "title": ".jieqi_title", "content": "#content",
          "toc_link": "#catalog", "toc": "#qingdan"}
RULE_BAD = {"host": "127.0.0.1", "content": "#content"}


class TestRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.site = MockSite().start()
        cls.cfg = Config()
        cls.fetcher = HttpFetcher(cls.cfg)

    @classmethod
    def tearDownClass(cls):
        cls.site.stop()

    def test_rule_for_host_matching(self):
        """内置规则（novel_spider 原站 quanshuwang）的域名匹配。"""
        r = rule_for("http://www.quanshuwang.com/book/44/44683/15379609.html",
                     BUILTIN_RULES)
        self.assertEqual(r.get("content"), "#content")
        self.assertEqual(r.get("title"), ".jieqi_title")
        self.assertEqual(r.get("next"), ".next")
        self.assertEqual(r.get("title_strip"), "章 节目录 ")
        r2 = rule_for("https://quanshuwang.com/a/b.html", BUILTIN_RULES)
        self.assertEqual(r2.get("content"), "#content")
        r3 = rule_for("http://other.example.org/x.html", BUILTIN_RULES)
        self.assertEqual(r3, {})

    def test_rule_extraction_and_title_clean(self):
        """BOOK_D：规则定位正文 + 标题前缀裁剪 + 广告/标记剔除。"""
        page = self.fetcher.fetch(f"{BASE}/bd/d1.html")
        cont = extract.extract_chapter_by_rule(page.soup, RULE_D)
        self.assertIsNotNone(cont)
        paras = extract.extract_paragraphs(cont)
        self.assertGreaterEqual(len(paras), 4)
        joined = "\n".join(paras)
        self.assertNotIn("style5", joined)
        self.assertNotIn("style6", joined)
        self.assertNotIn("天才一秒记住", joined)
        self.assertNotIn("www.example.com", joined)
        title = extract.extract_title_by_rule(page.soup, RULE_D)
        self.assertEqual(title, "第1章·测试回目A")

    def test_book_metadata_extraction(self):
        """从章节页/显式容器提取书名与作者（NovelGetter 元信息思路）。"""
        page = self.fetcher.fetch(f"{BASE}/ba/1.html")
        title, author = extract.extract_book_metadata(page)
        self.assertEqual(title, "测试小说")
        self.assertEqual(author, "")  # 无作者标记时保持空串

        html = ('<html><head><title>示例书名_第1章_示例站</title></head>'
                '<body><div class="bookname">示例书名</div>'
                '<div class="author"><span>作者：张三</span></div></body></html>')
        soup = BeautifulSoup(html, "lxml")
        page2 = Page("http://example.com/c1.html", "http://example.com/c1.html",
                     200, html, soup)
        t2, a2 = extract.extract_book_metadata(page2)
        self.assertEqual(t2, "示例书名")
        self.assertEqual(a2, "张三")

    def test_clean_title_prefix(self):
        self.assertEqual(extract.clean_title("正文 第3章·故事3"), "第3章·故事3")
        self.assertEqual(extract.clean_title("章 节目录 第2章·测试回目B", RULE_D),
                         "第2章·测试回目B")
        self.assertEqual(extract.clean_title("  第9章·标题  "), "第9章·标题")

    def test_rule_next_walk(self):
        """BOOK_D：按规则 next 选择器行走下一章。"""
        nxt = extract.find_next_chapter_link_by_rule(
            self.fetcher.fetch(f"{BASE}/bd/d1.html"), RULE_D)
        self.assertTrue(nxt.endswith("/bd/d2.html"))
        urls = discover.walk_by_next_link(
            self.fetcher, f"{BASE}/bd/d1.html", 20, forward=True, rule=RULE_D)
        self.assertEqual(len(urls), 6)
        self.assertEqual(urls[-1].split("/")[-1], "d6.html")

    def test_rule_toc_discovery(self):
        """BOOK_E：规则目录入口 + 容器（无规则时目录不可发现）。"""
        # 无规则：找不到目录（作品列表不在启发式关键词内），且 URL 无数字、无上下章
        plain = discover.discover_chapters(self.fetcher, [f"{BASE}/be/one.html"],
                                           max_chapters=50)
        self.assertEqual(len(plain), 1)
        # 有规则：通过 #catalog 进目录页、#qingdan 解析出 8 章
        with_rule = discover.discover_chapters(self.fetcher, [f"{BASE}/be/one.html"],
                                               max_chapters=50,
                                               rules=[RULE_E])
        self.assertEqual(len(with_rule), 8)
        self.assertTrue(with_rule[0].endswith("/be/one.html"))
        self.assertTrue(with_rule[-1].endswith("/be/eight.html"))

    def test_rule_invalid_falls_back(self):
        """规则 content 命中无效短文本 → 回退启发式。"""
        page = self.fetcher.fetch(f"{BASE}/bf/f1.html")
        self.assertIsNone(extract.extract_chapter_by_rule(page.soup, RULE_BAD))
        cont = extract.find_content_container(page.soup)
        self.assertIsNotNone(cont)
        paras = extract.extract_paragraphs(cont)
        self.assertGreaterEqual(len(paras), 4)

    def test_fallback_paragraphs_with_br(self):
        """无 <p> 标签时按 <br>/&nbsp; 切分正文（NovelGetter 兼容）。"""
        html = '<div id="content">第一段<br>第二段&nbsp;测试<br>第三段</div>'
        soup = BeautifulSoup(html, "lxml")
        paras = extract.extract_paragraphs(soup.find(id="content"))
        self.assertEqual(paras, ["第一段", "第二段 测试", "第三段"])

    def test_full_crawl_with_rules(self):
        """BookCrawler + 规则：全流程抓取 BOOK_D 6 章。"""
        crawler = BookCrawler(self.fetcher, self.cfg)
        book = crawler.crawl([f"{BASE}/bd/d1.html"], rules=[RULE_D])
        self.assertEqual(book.chapter_count, 6)
        self.assertEqual(book.title, "测试小说")
        self.assertEqual(book.author, "佚名")
        self.assertEqual(book.chapters[0].title, "第1章·测试回目A")
        self.assertEqual(book.chapters[5].title, "第6章·测试回目F")
        joined = book.chapters[0].body
        self.assertNotIn("style5", joined)
        self.assertNotIn("天才一秒记住", joined)
        self.assertGreater(book.word_count, 0)

    def test_get_rules_merges_config(self):
        """config.json 的 site_rules 扩展/覆盖内置规则。"""
        rules = get_rules(self.cfg)
        self.assertTrue(any(r.get("host") == "quanshuwang.com" for r in rules))
        cfg = Config()
        cfg.data["site_rules"] = {"quanshuwang.com": {"title": ".c_title"}}
        rules2 = get_rules(cfg)
        q = [r for r in rules2 if r.get("host") == "quanshuwang.com"][0]
        self.assertEqual(q.get("title"), ".c_title")
        self.assertEqual(q.get("content"), "#content")  # 其余字段保留
        cfg.data["site_rules"] = {"newbook.example": {"content": "#main"}}
        rules3 = get_rules(cfg)
        self.assertTrue(any(r.get("host") == "newbook.example" for r in rules3))


if __name__ == "__main__":
    unittest.main()
