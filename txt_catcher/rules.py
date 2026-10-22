# -*- coding: utf-8 -*-
"""站点规则层：按域名匹配 CSS 选择器，优先规则定位、失败回退启发式。

混合自 novel_spider（github.com/dyboy2017/novel_spider）的核心思路——
其按站点固定选择器抓取（标题 .jieqi_title、正文 #content、下一章 .next），
这里将其泛化为可配置的 per-host 规则表，供正文提取与条目发现优先使用。

规则来源：
  1) 内置规则（BUILTIN_RULES，含 novel_spider 原站点规则作为示例）
  2) config.json 的 site_rules（用户可扩展/覆盖，键为域名）

字段说明：
  host         域名匹配：精确或以后缀匹配（含子域名）
  title       内容标题 CSS 选择器
  content      正文容器 CSS 选择器
  next         下一个条目链接 CSS 选择器（a 元素，取其 href）
  toc          列表容器 CSS 选择器（条目列表所在元素）
  toc_link     列表页入口链接 CSS 选择器（a 元素，取其 href）
  title_strip  标题前缀裁剪（如 novel_spider 的 "章 节目录 "）
"""
import re
from urllib.parse import urlparse

# 内置规则（示例：novel_spider 原站 quanshuwang.com 的经典选择器）
BUILTIN_RULES = [
    {
        "host": "quanshuwang.com",
        "title": ".jieqi_title",
        "content": "#content",
        "next": ".next",
        "toc": "",
        "toc_link": "",
        "title_strip": "章 节目录 ",
    },
]


def get_rules(config=None) -> list:
    """返回生效的规则列表：内置规则 + config.json 的 site_rules（覆盖同名 host）。"""
    rules = [dict(r) for r in BUILTIN_RULES]
    if config is not None:
        custom = config.get("site_rules", {}) or {}
        for host, rule in custom.items():
            if not isinstance(rule, dict):
                continue
            merged = None
            for i, r in enumerate(rules):
                if r.get("host") == host:
                    merged = r
                    rules[i].update({k: v for k, v in rule.items() if v not in (None, "")})
                    break
            if merged is None:
                rules.append({"host": host, **{k: v for k, v in rule.items() if v not in (None, "")}})
    return rules


def _host_of(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def rule_for(url: str, rules=None) -> dict:
    """按 URL 匹配规则；无匹配返回空 dict（调用方走启发式）。"""
    if not rules:
        return {}
    host = _host_of(url)
    if not host:
        return {}
    # 精确匹配优先，其次父域名后缀
    best = None
    for r in rules:
        rh = (r.get("host") or "").lower().lstrip(".")
        if not rh:
            continue
        if host == rh:
            return r
        if host.endswith("." + rh) and (best is None or len(rh) > len(best.get("host", ""))):
            best = r
    return best or {}


def rule_encoding(rule: dict) -> str:
    """规则可携带编码提示（兼容 novel_spider 的 gbk 硬编码）；留作未来扩展。"""
    return (rule or {}).get("encoding", "")
