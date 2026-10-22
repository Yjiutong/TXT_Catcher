# -*- coding: utf-8 -*-
"""管线端到端测试：对本地模拟站跑完整流程并断言结果。"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from txt_catcher.config import Config
from txt_catcher.http import HttpFetcher
from txt_catcher import discover
from txt_catcher.pipeline import Collector
from txt_catcher.export import collection_to_package, export_package

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
        cfg.set("item_pool", 2)
        cfg.set("max_items", 500)
        fetcher = HttpFetcher(cfg)

        # ---------- 场景 A：列表页发现（UTF-8，含广告与分页） ----------
        print("== 场景A：列表页发现 ==")
        urls = discover.discover_items(
            fetcher, [f"{BASE}/ba/2.html", f"{BASE}/ba/7.html"],
            max_items=cfg.get("max_items"))
        check("A1 推测到全部12条", len(urls) == 12, f"got {len(urls)}")
        check("A2 按列表顺序排列", urls[0] == f"{BASE}/ba/1.html"
              and urls[11] == f"{BASE}/ba/12.html", urls[:3])
        coll = Collector(fetcher, cfg).crawl(
            [f"{BASE}/ba/2.html"], title_hint="测试小说", author_hint="罗贯中")
        check("A3 抓取12条", coll.item_count == 12, f"got {coll.item_count}")
        ch3 = coll.items[2]
        check("A4 第3条分页已合并（13段）", len(ch3.paragraphs) == 13,
              f"paras={len(ch3.paragraphs)} words={ch3.word_count}")
        check("A5 第1条正文含测试文本",
              "却说此人姓甚名谁" in coll.items[0].body)
        ad_hit = any("天才一秒记住" in p or "广告" in p or "版权所有" in p
                     for it in coll.items for p in it.paragraphs)
        check("A6 广告行已清除", not ad_hit)
        check("A7 条目标题正确", coll.items[0].title == "第01章·测试回目A",
              coll.items[0].title)

        # ---------- 场景 B：GBK + 零填充数字 URL 推断 ----------
        print("== 场景B：GBK编码 + 数字模式推断 ==")
        urls_b = discover.discover_items(
            fetcher, [f"{BASE}/bb/第001章.html", f"{BASE}/bb/第005章.html"],
            max_items=cfg.get("max_items"))
        check("B1 推测到全部8条", len(urls_b) == 8, f"got {len(urls_b)}")
        check("B2 零填充保持", f"{BASE}/bb/第002章.html" in urls_b, urls_b[:4])
        coll_b = Collector(fetcher, cfg).crawl([f"{BASE}/bb/第001章.html"],
                                               title_hint="GBK书")
        check("B3 GBK内容正确解码", coll_b.item_count == 8
              and "却说此人姓甚名谁" in coll_b.items[0].body,
              coll_b.items[0].body[:30])

        # ---------- 场景 C：无数字URL + 上下条目链接行走 ----------
        print("== 场景C：上下条目链接行走 ==")
        urls_c = discover.discover_items(
            fetcher, [f"{BASE}/bc/chapter-four.html"],
            max_items=cfg.get("max_items"))
        check("C1 行走得到全部6条", len(urls_c) == 6, f"got {len(urls_c)}")
        check("C2 顺序正确", urls_c[0].endswith("chapter-one.html")
              and urls_c[-1].endswith("chapter-six.html"), urls_c)

        # ---------- 场景 G：正文容器外数字页码分页（遍历链接找后续页） ----------
        print("== 场景G：容器外数字页码分页 ==")
        urls_g = discover.discover_items(
            fetcher, [f"{BASE}/bg/g1.html"],
            max_items=cfg.get("max_items"))
        check("G1 从内容页发现2条", len(urls_g) == 2, f"got {len(urls_g)}")
        coll_g = Collector(fetcher, cfg).crawl([f"{BASE}/bg/g1.html"],
                                               title_hint="分页测试")
        check("G2 抓取2条", coll_g.item_count == 2, f"got {coll_g.item_count}")
        ch1 = coll_g.items[0]
        check("G3 第1条三页分页已合并18段", len(ch1.paragraphs) == 18,
              f"paras={len(ch1.paragraphs)}")
        check("G4 标题取首页(无页码后缀)", ch1.title == "第1章·分页测试",
              ch1.title)
        check("G5 正文不含第2条内容",
              "第二章独有内容" not in ch1.body, ch1.body[:50])
        check("G6 第2条独立抓取", coll_g.items[1].title == "第2章·分页测试",
              coll_g.items[1].title)

        # ---------- 场景 D：导出 TXT / MD / JSON ----------
        tmp = tempfile.mkdtemp(prefix="txtcatcher_test_")
        try:
            pkg = collection_to_package(coll)
            txt = os.path.join(tmp, "测试小说.txt")
            md = os.path.join(tmp, "测试小说.md")
            js = os.path.join(tmp, "测试小说.json")
            export_package(pkg, fmt="txt", out=txt)
            export_package(pkg, fmt="md", out=md)
            export_package(pkg, fmt="json", out=js)
            check("D1 TXT 文件存在且非空", os.path.getsize(txt) > 5000,
                  f"size={os.path.getsize(txt)}")
            check("D2 MD 文件存在且非空", os.path.getsize(md) > 5000,
                  f"size={os.path.getsize(md)}")
            check("D3 JSON 文件存在且非空", os.path.getsize(js) > 3000,
                  f"size={os.path.getsize(js)}")
            with open(txt, encoding="utf-8") as f:
                content = f.read()
            check("D4 TXT 含全部条目", "12." in content and "第12章" in content)
            check("D5 TXT 含全书正文", content.count("这一去，果然凶多吉少，吉少凶多") >= 10
                  and "却说此人姓甚名谁" in content)
            with open(md, encoding="utf-8") as f:
                mdc = f.read()
            check("D6 MD 含条目标题与正文", "## 1. 第01章" in mdc
                  and "却说此人姓甚名谁" in mdc)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        print(f"\n结果：{PASS} 通过，{FAIL} 失败")
        return 1 if FAIL else 0
    finally:
        site.stop()


if __name__ == "__main__":
    sys.exit(main())
