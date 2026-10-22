---
name: txt_catcher
description: Grab and organize arbitrary public web text data (articles, chapters, lists, docs) into clean structured packages for any agent to consume. Fetch a page, discover item lists, merge paginated content, and export to txt/md/json.
---

# TXT_Catcher — 通用公开文字数据抓取 Skill

TXT_Catcher 是一个**任意 agent 通用**的公开文字抓取/整理工具包：把网页上的任意公开文字数据
（文章、章节、文档、列表条目）抓下来、清洗干净、合并分页、按列表排序，导出为结构化包或
纯文本 / Markdown。**不限于小说**，不提供 GUI，一切通过 Python API 或命令行完成。

## 何时使用

- 用户给了一个或几个网页链接，要求“抓取正文 / 保存全文 / 整理成文档 / 导出 Markdown”。
- 用户需要把某个列表页（目录页 / 索引页）里的全部条目依次抓取。
- 一篇文章被拆成多个分页（`?page=2`、`xxx_2.html`、数字页码），需要合并为完整正文。
- 用户提供了一批已浏览/已抓取的页面，要求整理成一份可读文档。

不要用本 skill 抓取受版权保护或未获授权的内容；只处理用户合法访问的公开/非版权数据。

## 快速使用（CLI）

```bat
:: 抓单个页面正文（默认输出干净文本，--json 输出结构化结果）
python -m txt_catcher grab https://example.com/article.html [--json]

:: 从种子 URL 自动发现条目列表并抓取（输出集合包 + Markdown/文本）
python -m txt_catcher crawl https://example.com/list.html --max 50 --out ./data

:: 手动收集若干页面为捕获包（zip + pages.json + all_text.txt）
python -m txt_catcher pack https://a.example/1 https://a.example/2 --out ./data

:: 把捕获包/集合包导出为文档
python -m txt_catcher export ./data/xxx.zip --format md --out book.md
```

## Python API

```python
from txt_catcher.config import Config
from txt_catcher.http import HttpFetcher
from txt_catcher.pipeline import Collector
from txt_catcher.export import collection_to_package, export_package

cfg = Config()
fetcher = HttpFetcher(cfg)
collector = Collector(fetcher, cfg)

# 1) 自动发现 + 抓取（列表发现 → 并发抓取 → 分页合并）
collection = collector.crawl(["https://example.com/list.html"])
pkg = collection_to_package(collection)          # 结构化包
export_package(pkg, fmt="md", out="book.md")     # → Markdown

# 2) 单页正文抓取
from txt_catcher import extract
page = fetcher.fetch("https://example.com/article.html")
container = extract.find_content_container(page.soup)
paragraphs = extract.extract_paragraphs(container)   # 已清洗噪音
```

## 核心能力

| 能力 | 说明 |
|---|---|
| 稳健抓取 | 浏览器 TLS 指纹模拟（curl_cffi / requests 回退）、自动重试、限速、编码识别（UTF-8/GBK/GB18030） |
| 正文提取 | 容器定位（规则优先 + 启发式）、段落清洗、广告/导航剔除、去重 |
| 分页合并 | 遍历全页可跳转链接找后续页（“下一页”文本 / 数字页码 / rel=next / 分页控件），预取比对标题核心确认同条目后才合并，不会误抓下一个条目 |
| 列表发现 | 目录页解析 / 页面内嵌列表 / URL 数字模式推断 / 上下条目链接行走，四层策略按优先级自动降级 |
| 站点规则 | 按域名配置 CSS 选择器（title/content/next/toc/toc_link），内置示例规则，可外部 JSON 扩展覆盖 |
| 结构化包 | `manifest.json` + `pages.json` + `all_text.txt` + zip，schema_version=2，任意 agent 可直接消费 |
| 导出 | 纯文本 / Markdown / JSON，一键生成 |

## 捕获包格式（schema_version=2）

```jsonc
{
  "schema_version": 2,
  "format": "txt_catcher_capture",       // 或 txt_catcher_collection（crawl 输出）
  "title": "集合标题",
  "author": "作者（可选）",
  "summary": { "pages": 3, "list_pages": 1, "item_pages": 2, "chars": 12345 },
  "pages": [
    {
      "url": "…", "final_url": "…", "ts": "2026-10-22T…",
      "kind": "item",                    // list=列表页 / item=内容页 / other=其他
      "title": "页面标题",
      "collection_title": "推断的集合标题",
      "author": "",
      "paragraphs": ["段落1", "段落2"],
      "text": "段落1\n\n段落2",
      "list_items": [{ "title": "条目", "url": "…" }],
      "nav": { "next": {"title": "下一项", "url": "…"}, "prev": …, "list": … },
      "links": [ { "title": "…", "url": "…" } ],
      "char_count": 1234
    }
  ]
}
```

`pages` 内条目建议按列表页顺序排序（无列表顺序时按 URL 数字/访问顺序）。

## 整理示例

`skills/capture_to_markdown/` 提供了“捕获包 → Markdown”的完整示例 skill：

```bat
python skills\capture_to_markdown\scripts\package_to_markdown.py captures\xxx.zip --out book.md
```

## 边界与合规

- 只处理用户合法访问的公开 / 非版权内容；不绕过付费墙、登录墙或反爬限制获取未授权数据。
- 尊重 robots / 站点条款，建议抓取时保持礼貌限速（默认 0.3s 间隔）。
- 不虚构内容：抓取不到的条目保留标题并标注“未捕获”，不编造正文。
