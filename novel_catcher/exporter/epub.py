# -*- coding: utf-8 -*-
"""EPUB 导出：使用 ebooklib 生成带目录（NCX/NAV）的电子书。"""
import os
import re
import uuid
from html import escape

from ebooklib import epub

from ..crawler.pipeline import BookResult

_ILLEGAL_XML_RE = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")


def _clean_xml(s: str) -> str:
    return _ILLEGAL_XML_RE.sub("", s or "")


def _chapter_html(ch) -> str:
    paras = []
    for p in ch.paragraphs:
        t = _clean_xml(p)
        if t:
            paras.append(f"<p>{escape(t)}</p>")
    body = "".join(paras) if paras else "<p>（本章无内容）</p>"
    title = escape(_clean_xml(ch.title))
    return (
        "<html xmlns=\"http://www.w3.org/1999/xhtml\">\n"
        f"<head><title>{title}</title></head>\n"
        f"<body>\n<h1>{title}</h1>\n{body}\n</body>\n</html>"
    )


def export_epub(book: BookResult, path: str, identifier: str = None) -> str:
    """把整本书导出为 EPUB，返回实际写入路径。"""
    eb = epub.EpubBook()
    eb.set_identifier(identifier or uuid.uuid4().hex)
    eb.set_title(_clean_xml(book.title))
    eb.set_language("zh")
    if book.author:
        eb.add_author(_clean_xml(book.author))

    eb.add_metadata(None, "description", _clean_xml(
        f"《{book.title}》由 TXT_Catcher 自动抓取整合，共 {len(book.chapters)} 章。"))

    spine = ["nav"]
    toc = []
    for i, ch in enumerate(book.chapters, 1):
        item = epub.EpubHtml(
            title=_clean_xml(ch.title),
            file_name=f"chap_{i:05d}.xhtml",
            lang="zh",
            content=_chapter_html(ch),
        )
        eb.add_item(item)
        toc.append(item)
        spine.append(item)

    eb.toc = tuple(toc)
    eb.add_item(epub.EpubNcx())
    eb.add_item(epub.EpubNav())
    eb.spine = spine

    epub.write_epub(path, eb, {})
    return path


def default_epub_path(output_dir: str, book: BookResult) -> str:
    from ..utils import safe_filename
    name = safe_filename(book.title, "未命名书籍")
    return os.path.join(output_dir, f"{name}.epub")
