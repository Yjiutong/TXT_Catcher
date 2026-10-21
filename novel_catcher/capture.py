# -*- coding: utf-8 -*-
"""阅读浏览捕获：把用户浏览过的网页整理为可交给 Codex 的捕获包。

本模块不再负责“自动推理整本书并全站抓取”，而是忠实记录用户在阅读浏览器里
打开过的页面。每个页面会被归类为目录候选 / 正文候选 / 其他，并附带可点击链接、
标题、正文段落与章节目录候选，方便后续 skill 整理成 EPUB。
"""
import json
import os
import re
import time
import zipfile
from datetime import datetime
from urllib.parse import urlparse

from . import utils
from .crawler import discover, extract
from .crawler.pipeline import BookResult, Chapter
from .crawler.rules import rule_for

KIND_TOC = "toc"
KIND_CHAPTER = "chapter"
KIND_OTHER = "other"

_KIND_LABEL = {
    KIND_TOC: "目录候选",
    KIND_CHAPTER: "正文候选",
    KIND_OTHER: "其他页面",
}

_TOC_IDCLASS_RE = re.compile(
    r"(catalog|chapterlist|chapter-list|booklist|book-list|mulu|toc|chapter_index|"
    r"zhangjie|chapter-list-container|listmain|dir|menu-main|chapterList)", re.I)


def kind_label(kind: str) -> str:
    return _KIND_LABEL.get(kind, kind or "其他页面")


def _abs_links(page) -> list:
    """收集页面里带文字的可点击链接，供阅读视图使用。"""
    out = []
    seen = set()
    if page is None or page.soup is None:
        return out
    for a in page.soup.find_all("a", href=True):
        text = a.get_text(" ", strip=True)
        href = a["href"].strip()
        if not text or not href or href.startswith(("javascript:", "#", "mailto:", "tel:")):
            continue
        url = utils.normalize_url(page.resolve(href))
        if not url.startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        out.append({"title": text[:80], "url": url})
        if len(out) >= 300:
            break
    return out


def _nav_links(page) -> dict:
    """常用导航链接：下一章 / 上一章 / 目录。"""
    out = {}
    nxt = extract.find_next_chapter_link(page)
    prev = extract.find_prev_chapter_link(page)
    toc = discover.find_toc_link(page)
    if nxt:
        out["next"] = {"title": "下一章", "url": nxt}
    if prev:
        out["prev"] = {"title": "上一章", "url": prev}
    if toc:
        out["toc"] = {"title": "目录", "url": toc}
    return out


def classify_page(page, rule=None) -> str:
    """判断页面更像目录页还是正文页；都不像则返回 other。"""
    if page is None or page.soup is None:
        return KIND_OTHER
    toc_items = discover.parse_toc_page(page, rule=rule)
    if _looks_like_toc_page(page, rule) or len(toc_items) >= 20:
        return KIND_TOC
    paras = extract.extract_paragraphs(extract.find_content_container(page.soup))
    if extract.looks_like_chapter_page(page) or sum(len(p) for p in paras) >= 100:
        return KIND_CHAPTER
    return KIND_OTHER


def _looks_like_toc_page(page, rule=None) -> bool:
    """仅在页面存在明确目录容器或规则目录选择器时判定为目录页。"""
    if page is None or page.soup is None:
        return False
    soup = page.soup
    if rule and (rule.get("toc") or ""):
        try:
            el = soup.select_one(rule["toc"])
            if el is not None and len(el.find_all("a", href=True)) >= 5:
                return True
        except Exception:
            pass
    for el in soup.find_all(["div", "ul", "ol", "dl"]):
        idc = extract._element_id_class(el)
        if _TOC_IDCLASS_RE.search(idc) and len(el.find_all("a", href=True)) >= 5:
            return True
    return False


def capture_page(page, rules=None) -> dict:
    """把一个抓回来的 Page 转成捕获包记录。"""
    rules = rules or []
    rule = rule_for(page.url, rules) if rules else {}
    container = extract.extract_chapter_by_rule(page.soup, rule)
    if container is None:
        container = extract.find_content_container(page.soup)
    paragraphs = extract.extract_paragraphs(container)
    title = extract.extract_title_by_rule(page.soup, rule)
    if not title:
        title = extract.extract_chapter_title(page, container)
    if not title and page.soup and page.soup.title:
        title = page.soup.title.get_text(" ", strip=True)
    toc_items = discover.parse_toc_page(page, rule=rule)
    kind = classify_page(page, rule)
    book_title, author = extract.extract_book_metadata(page, title)
    if not book_title and toc_items:
        book_title = _guess_book_from_toc(page, toc_items)

    return {
        "url": utils.normalize_url(page.url),
        "final_url": utils.normalize_url(page.final_url or page.url),
        "ts": datetime.now().isoformat(timespec="seconds"),
        "kind": kind,
        "kind_label": kind_label(kind),
        "title": title or "",
        "book_title": book_title,
        "author": author,
        "paragraphs": paragraphs,
        "text": "\n\n".join(paragraphs),
        "toc_items": [{"title": t, "url": u} for t, u in toc_items],
        "nav": _nav_links(page),
        "links": _abs_links(page),
        "char_count": utils.text_word_count("\n".join(paragraphs)),
    }


def _guess_book_from_toc(page, toc_items) -> str:
    """从目录页标题猜测书名。"""
    if not page or page.soup is None or not toc_items:
        return ""
    if page.soup.title:
        raw = page.soup.title.get_text(" ", strip=True)
        raw = re.sub(r"[_\-\—|·:：<>《》()（）【】\[\]\s]+", " ", raw).strip()
        parts = [p for p in raw.split(" ") if p]
        if parts:
            cleaned = re.sub(r"(目录|章节目录|章节列表|最新章节|小说阅读|阅读网)$", "", parts[0])
            if cleaned and len(cleaned) <= 40:
                return cleaned
    return toc_items[0][0] if toc_items else ""


class CaptureSession:
    """记录当前浏览会话里捕获到的页面，并导出 Codex 可读的包。"""

    def __init__(self):
        self.records = []
        self._url_seen = set()
        self.book_title = ""
        self.author = ""
        self.started_at = datetime.now().isoformat(timespec="seconds")

    def add(self, page, rules=None) -> dict:
        """添加一个页面；重复 URL 只保留首次，返回记录。"""
        rec = capture_page(page, rules)
        key = rec["final_url"] or rec["url"]
        if key in self._url_seen:
            return self._last_same(key)
        self._url_seen.add(key)
        self.records.append(rec)
        self._refresh_meta(rec)
        return rec

    def _last_same(self, key):
        for rec in reversed(self.records):
            if (rec.get("final_url") or rec.get("url")) == key:
                return rec
        return {"title": "", "kind": KIND_OTHER, "paragraphs": [], "text": ""}

    def _refresh_meta(self, rec):
        if rec.get("book_title") and not self.book_title:
            self.book_title = rec["book_title"]
        if rec.get("author") and not self.author:
            self.author = rec["author"]

    def summary(self) -> dict:
        toc_count = sum(1 for r in self.records if r.get("kind") == KIND_TOC)
        chapter_count = sum(1 for r in self.records if r.get("kind") == KIND_CHAPTER)
        other_count = sum(1 for r in self.records if r.get("kind") == KIND_OTHER)
        chars = sum(r.get("char_count", 0) for r in self.records)
        return {
            "pages": len(self.records),
            "toc_pages": toc_count,
            "chapter_pages": chapter_count,
            "other_pages": other_count,
            "chars": chars,
        }

    def to_package(self) -> dict:
        """构建与 Codex skill 约定的包结构。"""
        sorted_records = self._ordered_records()
        return {
            "schema_version": 1,
            "format": "txt_catcher_browser_capture",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "started_at": self.started_at,
            "book_title": self.book_title,
            "author": self.author,
            "summary": self.summary(),
            "pages": sorted_records,
        }

    def _ordered_records(self) -> list:
        """尝试按目录顺序排列章节记录；无目录时保留访问顺序。"""
        order_index = {}
        for rec in self.records:
            for i, item in enumerate(rec.get("toc_items", [])):
                order_index.setdefault(item.get("url", ""), (0, i))
        out = list(self.records)
        for idx, rec in enumerate(out):
            url = rec.get("final_url") or rec.get("url") or ""
            if url in order_index:
                rec = dict(rec)
                rec["_order"] = order_index[url]
                out[idx] = rec
        out.sort(key=lambda r: r.get("_order", (1, 0)))
        return out

    def save_package(self, out_dir: str) -> str:
        """导出捕获包：文件夹 + zip，返回 zip 路径。"""
        os.makedirs(out_dir, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = utils.safe_filename(self.book_title or "阅读捕获", "阅读捕获")
        folder = os.path.join(out_dir, f"{base}_{stamp}")
        os.makedirs(folder, exist_ok=True)
        pkg = self.to_package()
        manifest = {
            "title": self.book_title,
            "author": self.author,
            "format": pkg["format"],
            "schema_version": pkg["schema_version"],
            "created_at": pkg["created_at"],
            "summary": pkg["summary"],
            "files": ["pages.json", "all_text.txt"],
            "next_step": "把这些文件交给 Codex，使用 skills/novel_pack_to_epub 整理为 EPUB。",
        }
        with open(os.path.join(folder, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        with open(os.path.join(folder, "pages.json"), "w", encoding="utf-8") as f:
            json.dump(pkg, f, ensure_ascii=False, indent=2)
        with open(os.path.join(folder, "all_text.txt"), "w", encoding="utf-8", newline="\n") as f:
            f.write(_records_to_text(pkg["pages"]))
        zip_path = os.path.join(out_dir, f"{base}_{stamp}.zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for name in ("manifest.json", "pages.json", "all_text.txt"):
                z.write(os.path.join(folder, name), name)
        return zip_path


def _records_to_text(records: list) -> str:
    lines = []
    for rec in records:
        lines.append("=" * 24)
        lines.append(f"页面：{rec.get('title') or '(无标题)'}")
        lines.append(f"分类：{kind_label(rec.get('kind'))}")
        lines.append(f"地址：{rec.get('final_url') or rec.get('url')}")
        lines.append("")
        if rec.get("toc_items"):
            lines.append("目录候选：")
            for i, item in enumerate(rec["toc_items"], 1):
                lines.append(f"{i:>3}. {item['title']}")
                lines.append(f"     {item['url']}")
            lines.append("")
        if rec.get("paragraphs"):
            lines.append("正文候选：")
            lines.extend(rec["paragraphs"])
            lines.append("")
    return "\n".join(lines)


def build_book_from_package(pkg: dict) -> BookResult:
    """把捕获包转成 BookResult，供 TXT / EPUB 导出使用。"""
    records = pkg.get("pages") or []
    order_index = {}
    for rec in records:
        for i, item in enumerate(rec.get("toc_items", [])):
            order_index.setdefault(item.get("url", ""), (0, i))
    chapters = []
    seen = set()
    for rec in records:
        url = rec.get("final_url") or rec.get("url") or ""
        if url in seen:
            continue
        seen.add(url)
        paras = rec.get("paragraphs") or []
        if rec.get("toc_items") and not paras:
            continue
        title = rec.get("title") or "未命名章节"
        if not paras and len(title) < 2:
            continue
        chapters.append(Chapter(url, title, paras))
    # 按 URL 在目录里出现的顺序排序，其次保留原顺序
    chapters.sort(key=lambda ch: order_index.get(ch.url, (1, 0)))
    title = (pkg.get("book_title") or (
        chapters[0].title if chapters else "未命名书籍"))
    author = pkg.get("author") or "佚名"
    return BookResult(title, author, chapters)

