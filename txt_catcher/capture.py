# -*- coding: utf-8 -*-
"""页面捕获：把任意公开网页忠实记录为结构化的捕获包，供任意 agent 整理。

本模块不负责全站自动抓取，而是忠实记录用户浏览过的页面。每个页面会被归类为
列表页 / 内容页 / 其他，并附带可点击链接、标题、正文段落与条目列表候选，
方便后续任意 agent 整理为文档。
"""
import json
import os
import re
import time
import zipfile
from datetime import datetime
from urllib.parse import urlparse

from . import discover, extract, utils
from .pipeline import Collection, Item
from .rules import rule_for

KIND_LIST = "list"
KIND_ITEM = "item"
KIND_OTHER = "other"

_KIND_LABEL = {
    KIND_LIST: "列表页候选",
    KIND_ITEM: "内容页候选",
    KIND_OTHER: "其他页面",
}

_LIST_IDCLASS_RE = re.compile(
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
    """常用导航链接：下一个条目 / 上一个条目 / 列表。"""
    out = {}
    nxt = extract.find_next_link(page)
    prev = extract.find_prev_link(page)
    lst = discover.find_list_link(page)
    if nxt:
        out["next"] = {"title": "下一项", "url": nxt}
    if prev:
        out["prev"] = {"title": "上一项", "url": prev}
    if lst:
        out["list"] = {"title": "列表", "url": lst}
    return out


def classify_page(page, rule=None) -> str:
    """判断页面更像列表页还是内容页；都不像则返回 other。"""
    if page is None or page.soup is None:
        return KIND_OTHER
    list_items = discover.parse_list_page(page, rule=rule)
    if _looks_like_list_page(page, rule) or len(list_items) >= 20:
        return KIND_LIST
    paras = extract.extract_paragraphs(extract.find_content_container(page.soup))
    if extract.looks_like_content_page(page) or sum(len(p) for p in paras) >= 100:
        return KIND_ITEM
    return KIND_OTHER


def _looks_like_list_page(page, rule=None) -> bool:
    """仅在页面存在明确列表容器或规则列表选择器时判定为列表页。"""
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
        if _LIST_IDCLASS_RE.search(idc) and len(el.find_all("a", href=True)) >= 5:
            return True
    return False


def capture_page(page, rules=None) -> dict:
    """把一个抓回来的 Page 转成捕获包记录。"""
    rules = rules or []
    rule = rule_for(page.url, rules) if rules else {}
    container = extract.extract_content_by_rule(page.soup, rule)
    if container is None:
        container = extract.find_content_container(page.soup)
    paragraphs = extract.extract_paragraphs(container)
    title = extract.extract_title_by_rule(page.soup, rule)
    if not title:
        title = extract.extract_content_title(page, container)
    if not title and page.soup and page.soup.title:
        title = page.soup.title.get_text(" ", strip=True)
    list_items = discover.parse_list_page(page, rule=rule)
    kind = classify_page(page, rule)
    coll_title, author = extract.extract_metadata(page, title)
    if not coll_title and list_items:
        coll_title = _guess_title_from_list(page, list_items)

    return {
        "url": utils.normalize_url(page.url),
        "final_url": utils.normalize_url(page.final_url or page.url),
        "ts": datetime.now().isoformat(timespec="seconds"),
        "kind": kind,
        "kind_label": kind_label(kind),
        "title": title or "",
        "collection_title": coll_title,
        "author": author,
        "paragraphs": paragraphs,
        "text": "\n\n".join(paragraphs),
        "list_items": [{"title": t, "url": u} for t, u in list_items],
        "nav": _nav_links(page),
        "links": _abs_links(page),
        "char_count": utils.text_word_count("\n".join(paragraphs)),
    }


def _guess_title_from_list(page, list_items) -> str:
    """从列表页标题猜测集合标题。"""
    if not page or page.soup is None or not list_items:
        return ""
    if page.soup.title:
        raw = page.soup.title.get_text(" ", strip=True)
        raw = re.sub(r"[_\-\—|·:：<>《》()（）【】\[\]\s]+", " ", raw).strip()
        parts = [p for p in raw.split(" ") if p]
        if parts:
            cleaned = re.sub(r"(目录|章节目录|章节列表|最新章节|小说阅读|阅读网)$", "", parts[0])
            if cleaned and len(cleaned) <= 40:
                return cleaned
    return list_items[0][0] if list_items else ""


class CaptureSession:
    """记录当前会话里捕获到的页面，并导出任意 agent 可读的包。"""

    def __init__(self):
        self.records = []
        self._url_seen = set()
        self.title = ""
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
        if rec.get("collection_title") and not self.title:
            self.title = rec["collection_title"]
        if rec.get("author") and not self.author:
            self.author = rec["author"]

    def summary(self) -> dict:
        list_count = sum(1 for r in self.records if r.get("kind") == KIND_LIST)
        item_count = sum(1 for r in self.records if r.get("kind") == KIND_ITEM)
        other_count = sum(1 for r in self.records if r.get("kind") == KIND_OTHER)
        chars = sum(r.get("char_count", 0) for r in self.records)
        return {
            "pages": len(self.records),
            "list_pages": list_count,
            "item_pages": item_count,
            "other_pages": other_count,
            "chars": chars,
        }

    def to_package(self) -> dict:
        """构建与任意 agent skill 约定的包结构。"""
        sorted_records = self._ordered_records()
        return {
            "schema_version": 2,
            "format": "txt_catcher_capture",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "started_at": self.started_at,
            "title": self.title,
            "author": self.author,
            "summary": self.summary(),
            "pages": sorted_records,
        }

    def _ordered_records(self) -> list:
        """尝试按列表顺序排列条目记录；无列表时保留访问顺序。"""
        order_index = {}
        for rec in self.records:
            for i, item in enumerate(rec.get("list_items", [])):
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
        base = utils.safe_filename(self.title or "页面捕获", "页面捕获")
        folder = os.path.join(out_dir, f"{base}_{stamp}")
        os.makedirs(folder, exist_ok=True)
        pkg = self.to_package()
        manifest = {
            "title": self.title,
            "author": self.author,
            "format": pkg["format"],
            "schema_version": pkg["schema_version"],
            "created_at": pkg["created_at"],
            "summary": pkg["summary"],
            "files": ["pages.json", "all_text.txt"],
            "next_step": "把这些文件交给任意 agent，使用本仓库的 SKILL.md 与 skills/ 下的示例整理为文档。",
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
        if rec.get("list_items"):
            lines.append("列表页候选：")
            for i, item in enumerate(rec["list_items"], 1):
                lines.append(f"{i:>3}. {item['title']}")
                lines.append(f"     {item['url']}")
            lines.append("")
        if rec.get("paragraphs"):
            lines.append("内容页候选：")
            lines.extend(rec["paragraphs"])
            lines.append("")
    return "\n".join(lines)


def build_collection_from_package(pkg: dict) -> Collection:
    """把捕获包转成 Collection，供导出为纯文本 / Markdown 等格式使用。"""
    records = pkg.get("pages") or []
    order_index = {}
    for rec in records:
        for i, item in enumerate(rec.get("list_items", [])):
            order_index.setdefault(item.get("url", ""), (0, i))
    items = []
    seen = set()
    for rec in records:
        url = rec.get("final_url") or rec.get("url") or ""
        if url in seen:
            continue
        seen.add(url)
        paras = rec.get("paragraphs") or []
        if rec.get("list_items") and not paras:
            continue
        title = rec.get("title") or "未命名条目"
        if not paras and len(title) < 2:
            continue
        items.append(Item(url, title, paras))
    # 按 URL 在列表里出现的顺序排序，其次保留原顺序
    items.sort(key=lambda ch: order_index.get(ch.url, (1, 0)))
    title = (pkg.get("title") or (
        items[0].title if items else "未命名合集"))
    author = pkg.get("author") or ""
    return Collection(title, author, items)

