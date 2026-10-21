# -*- coding: utf-8 -*-
"""从 TXT_Catcher 捕获包整理 EPUB + TXT。

用法：
    python skills/novel_pack_to_epub/scripts/build_epub_from_package.py <capture.zip|folder> [output_dir]
"""
import json
import os
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from novel_catcher import utils  # noqa: E402
from novel_catcher.capture import build_book_from_package  # noqa: E402
from novel_catcher.exporter.epub import export_epub  # noqa: E402
from novel_catcher.exporter.txt import export_txt  # noqa: E402


def load_package(path: str) -> dict:
    """从 zip 或文件夹读取 pages.json，返回完整包 dict。"""
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
            target = "pages.json" if "pages.json" in names else None
            if target is None:
                for n in names:
                    if n.endswith("pages.json"):
                        target = n
                        break
            if target is None:
                raise ValueError("zip 中未找到 pages.json")
            with z.open(target) as f:
                pkg = json.load(f)
        path_dir = os.path.dirname(os.path.abspath(path))
        manifest_path = os.path.join(path_dir, "manifest.json")
        if os.path.exists(manifest_path):
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            if manifest:
                pkg.setdefault("book_title", manifest.get("title", ""))
                pkg.setdefault("author", manifest.get("author", ""))
        return pkg
    if os.path.isdir(path):
        with open(os.path.join(path, "pages.json"), "r", encoding="utf-8") as f:
            return json.load(f)
    if path.lower().endswith(".json"):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    raise ValueError(f"无法识别捕获包：{path}")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    src = sys.argv[1]
    out_dir = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "output")
    pkg = load_package(src)
    book = build_book_from_package(pkg)
    os.makedirs(out_dir, exist_ok=True)
    name = utils.safe_filename(book.title, "未命名书籍")
    epub_path = os.path.join(out_dir, f"{name}.epub")
    txt_path = os.path.join(out_dir, f"{name}.txt")
    export_epub(book, epub_path)
    export_txt(book, txt_path)
    print(f"书名：{book.title}")
    print(f"作者：{book.author or '佚名'}")
    print(f"章节：{book.chapter_count}")
    print(f"字数：{utils.format_word_count(book.word_count)}")
    print(f"EPUB：{epub_path}")
    print(f"TXT：{txt_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

