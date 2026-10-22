# 更新日志

本项目版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [2.0.0] - 2026-10-22

### 重大重构：从「公版小说抓取器」转为「任意 agent 通用的公开文字数据抓取 Skill」

- **删除一切应用层与小说特定代码**：GUI（`app.py`/Tkinter）、书籍库（`db.py`）、下载任务管理（`manager.py`）、TXT/EPUB 小说导出（`exporter/`）、exe 打包（`TXT_Catcher.spec`/`build.bat`/`run.bat`/`dist`）、图标与打包产物全部移除
- **包改名并扁平化**：`novel_catcher/` → `txt_catcher/`，`crawler/` 子包上提为顶层模块，导入路径全部更新
- **语义泛化**：
  - `Chapter` → `Item`（单个内容条目）、`BookResult` → `Collection`（条目集合）
  - `discover_chapters` → `discover_items`（列表发现）、`find_toc_link` → `find_list_link`
  - 页面分类 `toc/chapter` → `list/item`；捕获包 `schema_version` 升至 2，`format` 改为 `txt_catcher_capture`
  - `build_book_from_package` → `build_collection_from_package`
  - 正文提取/清洗/分页合并/编码识别/站点规则全部保留并通用化
- **新增通用 CLI**：`python -m txt_catcher grab|crawl|pack|export`，任意 agent 可直接调用
- **新增通用导出模块**：`export.py` 把捕获包/集合包导出为 txt / md / json
- **重写文档**：README、根目录 `SKILL.md`（面向任意 agent 的接入说明）、CHANGELOG、CONTRIBUTING 同步更新；`skills/novel_pack_to_epub` 替换为通用示例 `skills/capture_to_markdown`
- **清理仓库**：移除误入仓库的 `.py312/` 嵌入式 Python、`.venv/`、`.buildenv/`、构建与运行产物

### 保留（已通用化）的能力

- 浏览器 TLS 指纹模拟抓取（curl_cffi / requests 回退）、编码识别、重试、限速
- 正文容器定位与清洗（广告/导航剔除、去重）
- 遍历全页链接的分页合并（"下一页"文本 / 数字页码 / rel=next / 分页控件，预取比对标题核心确认同一条目）
- 列表发现四层策略（列表页解析 / 内嵌列表 / URL 数字推断 / 上下链接行走）
- 站点规则层（per-host CSS 选择器，外部 JSON 覆盖扩展）
- 结构化捕获包（manifest.json + pages.json + all_text.txt + zip）

### 破坏性变更

- 包名与导入路径全部变更：`novel_catcher.*` → `txt_catcher.*`
- 捕获包 schema 升级到 v2：`book_title` → `title`、`toc_items` → `list_items`、`kind` 值 `toc/chapter` → `list/item`
- 旧的小说 EPUB/TXT 导出与桌面应用能力不再提供
