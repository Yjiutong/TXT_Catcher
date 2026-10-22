---
name: capture_to_markdown
description: Organize TXT_Catcher capture packages (manifest/pages/all_text or zip) into a tidy Markdown document when the user asks to organize captured public web text data.
---

# Capture to Markdown

把 TXT_Catcher 导出的“捕获包”（zip 或文件夹）整理成一份规范的 Markdown 文档。

## 何时使用

- 用户提供 `manifest.json` + `pages.json` + `all_text.txt` 组成的捕获包文件夹，或对应的 `.zip`。
- 用户说“把抓回来的文字整理成 Markdown / 整理成文档 / 交给 skill 整理”。
- 捕获包里每一页都记录了抓取到的公开网页文本，分为 `列表页候选`、`内容页候选`、`其他页面`。

不要用本 skill 去访问网络、补抓缺失内容；只整理用户已经捕获的数据。

## 处理流程

1. 找到捕获包：
   - zip：先读包内 `pages.json`；或把 zip 解压到临时目录后读取。
   - 文件夹：读取同目录下的 `pages.json`。
2. 解析包结构（schema_version=2，format="txt_catcher_capture"）：
   - `title`：集合标题，可能为空，需要从条目标题/列表页推断。
   - `author`：作者，可能为空。
   - `pages`：页面记录数组。
   - 每条记录常见字段：`kind`（list/item/other）、`title`、`paragraphs`、`text`、`list_items`、`nav`、`final_url`。
3. 生成条目：
   - 内容页候选优先使用 `paragraphs`；为空时用 `text` 按空行拆分。
   - 列表页候选里的 `list_items` 是条目标题与 URL 候选，用于补全条目名和排序。
   - 同一个 URL 重复出现时只保留一份正文。
   - `other` 页面如果包含明显正文，也可以收进条目；如果是纯导航/空白页则丢弃。
4. 排序：
   - 优先按列表页候选里条目出现的顺序排序。
   - 没有列表顺序时，按 URL 数字段（如 `123.html`）排序。
   - 都没有数字字段时保留捕获包中的访问顺序。
5. 导出为 Markdown：
   - 一级标题为集合标题，二级标题为条目，正文按段落展开。
6. 验证：
   - 打开生成的 Markdown，检查条目数量、标题、正文不夹带广告/导航。
   - 如果有明显空条目或标题残缺，可在整理说明里报告给用户。

## 推荐实现

直接运行仓库内脚本：

```bat
python E:\TXT_Catcher\skills\capture_to_markdown\scripts\package_to_markdown.py "E:\TXT_Catcher\captures\xxx.zip" --out "E:\TXT_Catcher\output\整理结果.md"
```

输出：`整理结果.md`（含集合标题、条目目录与正文）。

也可以直接用核心导出模块：

```python
from txt_catcher.export import load_package, package_to_markdown

pkg = load_package("captures/xxx.zip")
markdown_text = package_to_markdown(pkg)
```

## 边界

- 不联网补抓：用户没捕获过的内容不要自动下载。
- 不虚构内容：缺失正文的条目可以保留标题并在正文写明“此页未捕获”。
- 遵守版权边界：本 skill 只整理用户合法获取的公开/非版权内容，不接受复制受版权保护作品。
