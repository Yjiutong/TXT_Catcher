# TXT_Catcher

![Version](https://img.shields.io/badge/Version-2.0.0-blue)

> 整理**网络任意公开文字数据**的抓取 Skill：抓取、清洗、分页合并、列表发现、结构化导出。
> 面向**任意 agent 通用**——提供 Python API 与命令行，不依赖任何特定平台；不限于小说，无 GUI。

TXT_Catcher 把一个或多个网页上的公开文字数据变成**干净、有序、结构化**的内容：

- 抓取单页正文（自动识别编码、清洗广告与导航噪音）
- 从列表页自动发现全部条目并依次抓取
- 把拆成多个分页的长文自动合并为完整正文
- 导出为结构化捕获包（JSON + 文本 + zip）或 Markdown / 纯文本

---

## 特性

- 🌐 **稳健抓取**：浏览器 TLS 指纹模拟（`curl_cffi`，自动回退 `requests`）、自动重试、限速、UTF-8/GBK/GB18030 编码识别
- 📄 **正文提取**：正文容器定位（站点规则优先 + 启发式）、段落清洗、广告/导航/版权声明剔除、重复段落去除
- 🔗 **遍历式分页合并**：一章/一篇文章拆成多个网页时，遍历当前页**全部可跳转链接**找后续页（"下一页"文本 / 数字页码 / `rel="next"` / 分页控件），预取比对标题核心确认**同一条目**后才合并，不会误抓下一个条目
- 📑 **列表发现**：目录/列表页解析、页面内嵌列表、URL 数字模式推断、上下条目链接行走，四层策略自动降级
- 🧩 **站点规则层**：按域名配置 CSS 选择器（`title/content/next/toc/toc_link`），内置示例规则，可用 JSON 覆盖扩展
- 📦 **结构化捕获包**：`manifest.json` + `pages.json` + `all_text.txt` + zip（schema_version=2），任何 agent 可直接消费
- 📝 **通用导出**：Markdown / 纯文本 / JSON 一键生成

---

## 快速开始

### 安装依赖

```bat
pip install -r requirements.txt
```

### 命令行

```bat
:: 抓单个页面正文（干净文本；--json 输出结构化结果）
python -m txt_catcher grab https://example.com/article.html --json

:: 从种子 URL 自动发现条目列表并抓取（输出集合包 + Markdown/文本）
python -m txt_catcher crawl https://example.com/list.html --max 50 --out ./data

:: 手动收集若干页面为捕获包
python -m txt_catcher pack https://a.example/1 https://a.example/2 --out ./data

:: 把捕获包导出为文档
python -m txt_catcher export ./data/xxx.zip --format md --out book.md
```

### Python API

```python
from txt_catcher.config import Config
from txt_catcher.http import HttpFetcher
from txt_catcher.pipeline import Collector
from txt_catcher.export import collection_to_package, export_package

cfg = Config()
collector = Collector(HttpFetcher(cfg), cfg)

# 自动发现列表条目 + 并发抓取 + 分页合并
collection = collector.crawl(["https://example.com/list.html"])
pkg = collection_to_package(collection)
export_package(pkg, fmt="md", out="book.md")
```

---

## 包结构

```
txt_catcher/            # 核心库
├── http.py             # 抓取层：TLS 指纹、会话、重试、编码识别、限速
├── extract.py          # 正文提取：容器定位、清洗、分页候选、标题/元信息
├── discover.py         # 列表发现：列表页/内嵌列表/数字推断/上下行走
├── pipeline.py         # 管线：Item / Collection / ItemFetcher / Collector
├── rules.py            # 站点规则层（per-host CSS 选择器）
├── capture.py          # 捕获包：页面分类、去重、排序、导出 zip
├── export.py           # 导出：包 → txt / md / json
├── cli.py              # 命令行入口（grab/crawl/pack/export）
├── config.py           # 配置（config.json 可覆盖）
└── utils.py            # 通用工具
skills/
└── capture_to_markdown/   # 示例 skill：捕获包 → Markdown
tests/                  # 单元与集成测试（mock_site 模拟多种站点形态）
SKILL.md                # 面向任意 agent 的接入说明（给 agent 看的入口）
```

## 捕获包格式

导出包为 zip，内含：

| 文件 | 内容 |
|---|---|
| `manifest.json` | 标题、作者、摘要、文件清单、下一步指引 |
| `pages.json` | 完整结构化数据（schema_version=2） |
| `all_text.txt` | 全部页面的纯文本视图（便于直接阅读） |

`pages.json` 中每条记录含：URL、分类（`list`/`item`/`other`）、标题、正文段落、
列表条目候选、导航链接、全部可点击链接、字数。详见根目录 `SKILL.md`。

## 站点规则

按域名配置 CSS 选择器，`config.json` 的 `site_rules` 可覆盖/补充内置规则：

```json
{
  "site_rules": {
    "example.com": {
      "title": "h1.article-title",
      "content": "#article-content",
      "next": "a.next",
      "toc": "ul.chapter-list",
      "toc_link": "a.toc",
      "title_strip": ""
    }
  }
}
```

命令行可用 `--rules rules.json` 传入外部规则（键为域名，值为同一结构）。

## 测试

```bat
python tests\test_pipeline.py    :: 引擎端到端测试（条目发现/抓取/分页合并/导出）
python tests\test_rules.py       :: 站点规则层测试
python tests\test_capture.py     :: 捕获包测试（分类/去重/导出/整理）
python tests\test_cli.py         :: 命令行冒烟测试
```

`tests/mock_site.py` 内置 7 种模拟站点形态（A–G），覆盖目录页、GBK 编码、上下链行走、
正文容器外数字页码分页等真实场景。

## 合规与边界

- 只处理用户合法访问的**公开 / 非版权**内容；不绕过付费墙、登录墙或反爬限制。
- 抓取保持礼貌限速（默认 0.3s 间隔），尊重站点条款与 robots。
- 本仓库 MIT 许可，作者不对使用者的抓取行为负责。

## 文档

- [SKILL.md](SKILL.md) — 面向任意 agent 的完整接入说明
- [CHANGELOG.md](CHANGELOG.md) — 版本历史
- [CONTRIBUTING.md](CONTRIBUTING.md) — 贡献与 Git 规范
