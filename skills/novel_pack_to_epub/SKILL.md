---
name: novel_pack_to_epub
description: Convert TXT_Catcher browser capture packages (manifest/pages/all_text or zip) into tidy EPUB/TXT novel documents when the user asks to organize captured browsing data.
---

# Novel Pack to EPUB

把 TXT_Catcher 阅读浏览器导出的“捕获包”整理成一本规范的 EPUB 小说文档。

## 何时使用

- 用户提供 `manifest.json` + `pages.json` + `all_text.txt` 组成的捕获包文件夹，或对应的 `.zip`。
- 用户说“把抓回来的数据整理成 EPUB / 整理成小说文档 / 交给 skill 整理”。
- 捕获包里每一页都记录了用户浏览过的网页文本，分为 `目录候选`、`正文候选`、`其他页面`。

不要用本 skill 去访问网络、补抓缺失章节；只整理用户已经捕获的数据。

## 处理流程

1. 找到捕获包：
   - zip：先读包内 `pages.json`；或把 zip 解压到临时目录后读取。
   - 文件夹：读取同目录下的 `pages.json`。
2. 解析包结构：
   - `book_title`：整本书书名，可能为空，需要从章节标题/目录推断。
   - `author`：作者，可能为空。
   - `pages`：页面记录数组。
   - 每条记录常见字段：`kind`（toc/chapter/other）、`title`、`paragraphs`、`text`、`toc_items`、`nav`、`final_url`。
3. 生成章节：
   - 正文候选优先使用 `paragraphs`；为空时用 `text` 按空行拆分。
   - 目录候选页里的 `toc_items` 是章节标题与 URL 候选，用于补全章节名和排序。
   - 同一个 URL 重复出现时只保留一份正文。
   - `other` 页面如果包含明显小说正文，也可以收进章节正文；如果是纯导航/空白页则丢弃。
4. 排序：
   - 优先按目录候选里章节出现的顺序排序。
   - 没有目录顺序时，按 URL 数字段（如 `123.html`）排序。
   - 都没有数字字段时保留捕获包中的访问顺序。
5. 导出：
   - 复用 `novel_catcher.exporter.epub` 和 `novel_catcher.exporter.txt`。
   - EPUB 包含可点击目录、内页标题与正文段落。
   - TXT 顶部分卷目录、随后逐章正文。
6. 验证：
   - 打开生成的 EPUB，检查目录项数量、章节标题、正文不夹带广告/导航。
   - 如果有明显空章或标题残缺，可在整理说明里报告给用户。

## 推荐实现

直接运行仓库内脚本：

```bat
E:\TXT_Catcher\.buildenv\Scripts\python.exe E:\TXT_Catcher\skills\novel_pack_to_epub\scripts\build_epub_from_package.py "E:\TXT_Catcher\captures\xxx.zip" "E:\TXT_Catcher\output"
```

输出：

- `适合阅读的书名.epub`
- `适合阅读的书名.txt`

如果捕获包结构比脚本预期更复杂，也可以直接调用：

```python
from novel_catcher.capture import build_book_from_package
from novel_catcher.exporter.epub import export_epub
from novel_catcher.exporter.txt import export_txt

book = build_book_from_package(pkg)
export_epub(book, out_epub)
export_txt(book, out_txt)
```

## 边界

- 不联网补页：用户没浏览过的章节不要自动下载。
- 不虚构内容：缺失正文的章节可以保留标题并在正文写成“此章未捕获/未浏览”。
- 保持版权边界：本 skill 用于整理用户合法浏览的非版权（公版）内容，不接受复制受版权保护作品。

