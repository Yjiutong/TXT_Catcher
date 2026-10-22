# -*- coding: utf-8 -*-
"""把 TXT_Catcher 捕获包/集合包整理为 Markdown 文档（示例 skill 脚本）。

用法：
  python package_to_markdown.py <package.zip|folder> [--out 输出.md]
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))))

from txt_catcher.export import export_package, load_package  # noqa: E402


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="捕获包 → Markdown")
    p.add_argument("source", help="捕获包 zip 或包含 pages.json 的文件夹")
    p.add_argument("--out", default="", help="输出 Markdown 路径（默认按标题命名）")
    args = p.parse_args(argv)
    pkg = load_package(args.source)
    path = export_package(pkg, fmt="md", out=args.out)
    print(f"已导出：{path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
