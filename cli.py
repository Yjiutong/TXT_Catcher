# -*- coding: utf-8 -*-
"""TXT_Catcher 命令行模式：python cli.py <章节网址...> [-t 书名] [-a 作者] [-o 输出目录]"""
import argparse
import os
import sys

from novel_catcher.config import Config
from novel_catcher.crawler.http import HttpFetcher
from novel_catcher.crawler import discover
from novel_catcher.crawler.pipeline import BookCrawler
from novel_catcher.crawler.rules import get_rules
from novel_catcher.exporter.txt import export_txt, default_txt_path
from novel_catcher.exporter.epub import export_epub, default_epub_path


def progress(msg, pct, detail=""):
    bar_len = 30
    filled = int(bar_len * pct / 100)
    bar = "█" * filled + "░" * (bar_len - filled)
    print(f"\r[{bar}] {pct:5.1f}%  {msg}", flush=True)


def main():
    ap = argparse.ArgumentParser(description="TXT_Catcher 命令行抓取")
    ap.add_argument("urls", nargs="+", help="章节网址（可给多个）")
    ap.add_argument("-t", "--title", default="", help="书名")
    ap.add_argument("-a", "--author", default="", help="作者")
    ap.add_argument("-o", "--output", default="", help="输出目录")
    ap.add_argument("--discover-only", action="store_true", help="只做章节发现，不抓正文")
    args = ap.parse_args()

    cfg = Config()
    if args.output:
        cfg.set("output_dir", args.output)

    fetcher = HttpFetcher(cfg, logger=lambda m: print(f"  [log] {m}", flush=True))

    print("=" * 60)
    print("章节位置推测（发现阶段）")
    print("=" * 60)
    try:
        urls = discover.discover_chapters(fetcher, args.urls,
                                          max_chapters=cfg.get("max_chapters"),
                                          rules=get_rules(cfg),
                                          progress=lambda m: print(f"  * {m}", flush=True))
    except Exception as e:
        print(f"章节发现失败：{e}")
        return 1

    print(f"\n共推测到 {len(urls)} 个章节：")
    for u in urls[:10]:
        print(f"  {u}")
    if len(urls) > 10:
        print(f"  ... 共 {len(urls)} 个")
    if not args.discover_only:
        for u in urls:
            if u not in args.urls:
                print(f"  + 推测章节 {u}")

    if args.discover_only:
        return 0

    print("\n" + "=" * 60)
    print("正文抓取与整合")
    print("=" * 60)
    crawler = BookCrawler(fetcher, cfg, progress=progress)
    book = crawler.crawl(args.urls, title_hint=args.title, author_hint=args.author)
    print(f"\n书名：{book.title}  作者：{book.author}")
    print(f"章节数：{book.chapter_count}  总字数：{book.word_count}")

    output_dir = cfg.get("output_dir")
    os.makedirs(output_dir, exist_ok=True)
    txt = default_txt_path(output_dir, book)
    epub = default_epub_path(output_dir, book)
    export_txt(book, txt)
    try:
        export_epub(book, epub)
        print(f"EPUB：{epub}")
    except Exception as e:
        print(f"EPUB 生成失败（已保留 TXT）：{e}")
    print(f"TXT ：{txt}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
