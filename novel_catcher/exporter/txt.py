# -*- coding: utf-8 -*-
"""TXT 导出：合并整本书为单个 UTF-8 文本文件。"""
import os

from ..crawler.pipeline import BookResult


def export_txt(book: BookResult, path: str) -> str:
    """把整本书写为 TXT，返回实际写入路径。

    结构：书名/作者/简介占位/目录/正文（分卷分章）。
    """
    lines = []
    lines.append(book.title)
    lines.append(f"作者：{book.author}")
    lines.append("")
    lines.append("目 录")
    for i, ch in enumerate(book.chapters, 1):
        lines.append(f"{i:>4}. {ch.title}")
    lines.append("")
    lines.append("=" * 30)
    lines.append("")

    for ch in book.chapters:
        lines.append(ch.title)
        lines.append("")
        lines.append(ch.body)
        lines.append("")
        lines.append("=" * 30)
        lines.append("")

    content = "\n".join(lines)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    return path


def default_txt_path(output_dir: str, book: BookResult) -> str:
    from ..utils import safe_filename
    name = safe_filename(book.title, "未命名书籍")
    return os.path.join(output_dir, f"{name}.txt")
