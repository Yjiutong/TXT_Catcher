# -*- coding: utf-8 -*-
"""TXT_Catcher 通用命令行入口：任意 agent 或脚本可直接调用的文字抓取工具。

子命令：
  grab   抓取单个页面并输出干净正文
  crawl  从种子 URL 自动发现条目列表并抓取（生成集合包）
  pack   手动收集若干页面为捕获包
  export 把捕获包/集合包导出为 txt / md / json

示例：
  python -m txt_catcher grab https://example.com/article.html
  python -m txt_catcher grab https://example.com/article.html --json
  python -m txt_catcher crawl https://example.com/list.html --max 50 --out ./data
  python -m txt_catcher pack https://a.example/1 https://a.example/2 --out ./data
  python -m txt_catcher export ./data/xx.zip --format md --out book.md
"""
import argparse
import json
import os
import sys

from . import __version__
from .capture import CaptureSession
from .config import Config
from .export import (collection_to_package, export_package, load_package)
from .http import HttpFetcher
from .pipeline import Collector


def _load_rules(path: str):
    if not path:
        return None
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        return [dict(r, host=h) for h, r in data.items()]
    return data


def _fetcher(cfg: Config, rules_path: str):
    return HttpFetcher(cfg), _load_rules(rules_path)


def cmd_grab(args) -> int:
    cfg = Config()
    fetcher, rules = _fetcher(cfg, args.rules)
    page = fetcher.fetch(args.url)
    from . import extract
    from .rules import rule_for
    r = rule_for(page.url, rules or [])
    container = extract.extract_content_by_rule(page.soup, r)
    if container is None:
        container = extract.find_content_container(page.soup)
    paragraphs = extract.extract_paragraphs(container)
    title = extract.extract_title_by_rule(page.soup, r)
    if not title:
        title = extract.extract_content_title(page, container)
    coll_title, author = extract.extract_metadata(page, title)
    if args.json:
        print(json.dumps({
            "url": page.url,
            "final_url": page.final_url or page.url,
            "title": title or "",
            "collection_title": coll_title,
            "author": author,
            "char_count": sum(len(p) for p in paragraphs),
            "paragraphs": paragraphs,
        }, ensure_ascii=False, indent=2))
    else:
        print(f"# {title or '(无标题)'}")
        if coll_title or author:
            print(f"> {coll_title or ''} {('/ ' + author) if author else ''}".rstrip())
        print()
        print("\n\n".join(paragraphs) if paragraphs else "（未提取到正文）")
    return 0


def cmd_crawl(args) -> int:
    cfg = Config()
    if args.max:
        cfg.data["max_items"] = args.max  # 仅本次生效，不写回 config.json
    fetcher, rules = _fetcher(cfg, args.rules)
    collector = Collector(fetcher, cfg)
    collection = collector.crawl(args.urls, title_hint=args.title or "",
                                 author_hint=args.author or "", rules=rules)
    pkg = collection_to_package(collection)
    out_dir = args.out or cfg.get("output_dir")
    os.makedirs(out_dir, exist_ok=True)
    path = export_package(pkg, fmt=args.format, out=os.path.join(out_dir, "collection.json"))
    if args.format != "json":
        export_package(pkg, fmt=args.format, out=os.path.join(out_dir, f"collection.{args.format}"))
    print(f"已抓取 {collection.item_count} 个条目，约 {collection.word_count} 字")
    print(f"输出：{out_dir}")
    return 0


def cmd_pack(args) -> int:
    cfg = Config()
    fetcher, rules = _fetcher(cfg, args.rules)
    session = CaptureSession()
    for url in args.urls:
        session.add(fetcher.fetch(url), rules=rules)
    out_dir = args.out or cfg.get("output_dir")
    zip_path = session.save_package(out_dir)
    print(f"已收集 {len(session.records)} 个页面")
    print(f"捕获包：{zip_path}")
    return 0


def cmd_export(args) -> int:
    pkg = load_package(args.source)
    path = export_package(pkg, fmt=args.format, out=args.out or "")
    print(f"已导出：{path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="txt_catcher",
        description="TXT_Catcher：整理网络任意公开文字数据的抓取 skill。")
    p.add_argument("--version", action="version", version=f"TXT_Catcher {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("grab", help="抓取单个页面并输出干净正文")
    g.add_argument("url")
    g.add_argument("--json", action="store_true", help="以 JSON 输出结构化结果")
    g.add_argument("--rules", default="", help="站点规则 JSON 文件路径")

    c = sub.add_parser("crawl", help="从种子 URL 自动发现条目列表并抓取")
    c.add_argument("urls", nargs="+", help="一个或多个种子 URL（列表页或内容页）")
    c.add_argument("--max", type=int, default=0, help="条目数量上限（默认用配置）")
    c.add_argument("--title", default="", help="集合标题（留空自动提取）")
    c.add_argument("--author", default="", help="作者（留空自动提取）")
    c.add_argument("--out", default="", help="输出目录")
    c.add_argument("--format", default="md", choices=["txt", "md", "json"])
    c.add_argument("--rules", default="", help="站点规则 JSON 文件路径")

    pk = sub.add_parser("pack", help="手动收集若干页面为捕获包")
    pk.add_argument("urls", nargs="+", help="要收集的页面 URL（可混合列表页/内容页）")
    pk.add_argument("--out", default="", help="输出目录")
    pk.add_argument("--rules", default="", help="站点规则 JSON 文件路径")

    e = sub.add_parser("export", help="把捕获包/集合包导出为 txt/md/json")
    e.add_argument("source", help="包路径：zip 文件或包含 pages.json 的文件夹")
    e.add_argument("--format", default="md", choices=["txt", "md", "json"])
    e.add_argument("--out", default="", help="输出文件路径（默认按标题自动命名）")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "grab":
        return cmd_grab(args)
    if args.cmd == "crawl":
        return cmd_crawl(args)
    if args.cmd == "pack":
        return cmd_pack(args)
    if args.cmd == "export":
        return cmd_export(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
