# -*- coding: utf-8 -*-
"""通用导出：捕获包 / 条目集合 → 纯文本、Markdown、JSON。

输入包结构兼容两类：
  - 捕获包（capture 模块导出，schema_version=2，format="txt_catcher_capture"，
    记录含 kind/paragraphs/list_items/nav/links）
  - 集合包（Collector.crawl 的结果经 collection_to_package 转换，
    记录含 url/title/paragraphs）
导出时统一按记录里的 title + paragraphs 渲染。
"""
import json
import os

from . import utils


def _records(pkg: dict) -> list:
    """取包的记录列表（兼容 pages/items 两种键）。"""
    return pkg.get("pages") or pkg.get("items") or []


def _title_and_body(rec: dict):
    title = rec.get("title") or "未命名条目"
    paras = rec.get("paragraphs") or []
    body = "\n\n".join(paras)
    return title, body


def _summary_line(pkg: dict) -> str:
    summary = pkg.get("summary") or {}
    n = summary.get("item_pages") if summary.get("item_pages") is not None else len(_records(pkg))
    chars = summary.get("chars") or sum(
        utils.text_word_count(rec.get("text") or "") for rec in _records(pkg))
    bits = [f"条目数 {n}", f"约 {utils.format_word_count(chars)} 字"]
    if pkg.get("author"):
        bits.insert(0, f"作者：{pkg['author']}")
    return " · ".join(bits)


def package_to_text(pkg: dict) -> str:
    """整包 → 纯文本。"""
    lines = []
    title = pkg.get("title") or "未命名合集"
    lines.append(title)
    lines.append(_summary_line(pkg))
    lines.append("")
    lines.append("=" * 40)
    for i, rec in enumerate(_records(pkg), 1):
        t, body = _title_and_body(rec)
        lines.append("")
        lines.append(f"{i}. {t}")
        lines.append("-" * 24)
        if body:
            lines.append(body)
        else:
            lines.append("（本页无正文段落）")
    return "\n".join(lines)


def package_to_markdown(pkg: dict) -> str:
    """整包 → Markdown。"""
    lines = []
    title = pkg.get("title") or "未命名合集"
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"> {_summary_line(pkg)}")
    lines.append("")
    for i, rec in enumerate(_records(pkg), 1):
        t, body = _title_and_body(rec)
        lines.append(f"## {i}. {t}")
        lines.append("")
        if body:
            lines.append(body)
        else:
            lines.append("（本页无正文段落）")
        lines.append("")
    return "\n".join(lines)


def collection_to_package(collection) -> dict:
    """把 Collector 返回的 Collection 转成与捕获包同构的集合包。"""
    items = []
    chars = 0
    for it in collection.items:
        text = it.body
        chars += utils.text_word_count(text)
        items.append({
            "url": it.url,
            "title": it.title,
            "paragraphs": it.paragraphs,
            "text": text,
            "char_count": utils.text_word_count(text),
        })
    return {
        "schema_version": 2,
        "format": "txt_catcher_collection",
        "title": collection.title,
        "author": collection.author,
        "summary": {"items": len(items), "chars": chars},
        "items": items,
    }


def load_package(source: str) -> dict:
    """从 zip 或文件夹加载包。zip 内读 pages.json/items.json；文件夹先看 pages.json。"""
    import zipfile
    if zipfile.is_zipfile(source):
        with zipfile.ZipFile(source) as z:
            for name in ("pages.json", "items.json"):
                if name in z.namelist():
                    with z.open(name) as f:
                        return json.load(f)
            raise ValueError("包内找不到 pages.json / items.json")
    for name in ("pages.json", "items.json"):
        path = os.path.join(source, name)
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    raise ValueError(f"无法识别包：{source}")


def export_package(pkg: dict, fmt: str = "md", out: str = "") -> str:
    """导出整包为 txt/md/json，返回写入的文件路径（out 为空时用标题自动命名）。"""
    fmt = (fmt or "md").lower().lstrip(".")
    if fmt not in ("txt", "md", "markdown", "json"):
        raise ValueError(f"不支持的格式：{fmt}（支持 txt / md / json）")
    if fmt == "json":
        content = json.dumps(pkg, ensure_ascii=False, indent=2)
        ext = ".json"
    elif fmt in ("md", "markdown"):
        content = package_to_markdown(pkg)
        ext = ".md"
    else:
        content = package_to_text(pkg)
        ext = ".txt"
    if not out:
        base = utils.safe_filename(pkg.get("title") or "导出", "导出")
        out = base + ext
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    return out
