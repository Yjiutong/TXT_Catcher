# TXT_Catcher 公版小说抓取器

> 从网页抓取**非版权（公版）小说**并自动整合为 TXT + EPUB 的桌面工具。
> 只需提供书中**任意几章网址**，自动推测整本书章节位置并抓取整理。

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB)
![Platform](https://img.shields.io/badge/Platform-Windows-0078D6)
![GUI](https://img.shields.io/badge/GUI-Tkinter-5C7CFA)
![License](https://img.shields.io/badge/License-MIT-green)
![Version](https://img.shields.io/badge/Version-1.0.0-blue)

---

## 目录

- [功能特性](#功能特性)
- [使用边界](#使用边界)
- [快速开始](#快速开始)
- [使用说明](#使用说明)
- [章节推测原理](#章节推测原理)
- [命令行模式](#命令行模式)
- [项目结构](#项目结构)
- [测试](#测试)
- [常见问题](#常见问题)
- [贡献指南](#贡献指南)
- [许可证](#许可证)

---

## 功能特性

- 🔍 **章节位置自动推测**：只给几章网址，自动补齐全书（目录页 → 内嵌目录 → URL 数字推断 → 上下章链接，四层策略）
- 🧹 **正文智能清洗**：自动定位正文容器、剔除广告/导航/版权声明、识别 UTF-8/GBK/GB18030 编码、合并正文分页、去除重复段落
- 🖥️ **桌面可视化管理**：书籍库（打开/重下/删除）+ 下载任务（实时进度/日志/取消）+ 设置面板
- 📦 **TXT + EPUB 双格式输出**：TXT 含完整目录；EPUB 带可点击目录（NCX/NAV），可直接导入阅读器
- 🔒 **浏览器指纹模拟**：基于 curl_cffi 绕过常见 TLS 反爬，自动重试与限速

## 使用边界

> ⚠️ **本工具仅适用于非版权（公版）作品**（如四大名著、公版译著等）。
> 请勿用于抓取受版权保护的作品，并请遵守目标网站的访问规则与当地法律。

## 快速开始

### 方式 A：直接运行打包程序（推荐）

下载或构建 `TXT_Catcher.exe`，双击即用，无需安装 Python。

### 方式 B：源码运行

需要 Python 3.10+：

```bat
pip install -r requirements.txt
python app.py
```

或直接双击 `run.bat`。

## 使用说明

1. 点击 **「＋ 新建下载」**
2. 粘贴 **1 个或几个章节网址**（每行一个，例如只给第 2 回和第 57 回的链接）
3. 可选填写书名、作者（留空则自动从页面提取）
4. 点击 **「预览章节位置」**，确认工具推测出的章节总数
5. 点击 **「开始下载」**，完成后自动生成 `书名.txt` 与 `书名.epub` 到输出目录（默认 `output\`）

| 页签 | 功能 |
|---|---|
| 书籍库 | 已下载书籍：书名/作者/章节/字数/状态；打开 TXT/EPUB、重新下载、删除记录 |
| 下载任务 | 运行中任务进度、阶段与运行日志；可取消 |
| 设置 | 输出目录、并发数、超时、重试次数、请求间隔 |

## 章节推测原理

按以下优先级自动推测整本书章节（用户只需提供任意几章）：

1. **目录页发现**：从章节页找「目录 / 章节列表」链接并解析全部章节
2. **页面内嵌目录**：章节页侧栏/底部自带的章节列表直接解析
3. **URL 数字推断**：从已有网址提取数字模式（如 `…/book/123.html`），向两端扩展并逐页验证（自动识别零填充如 `第001回`）
4. **上下章链接行走**：沿「上一章 / 下一章」链接向前后遍历

## 命令行模式

```bat
:: 下载整本
python cli.py "https://example.com/book/2.html" "https://example.com/book/57.html" -t 书名 -a 作者

:: 仅预览章节发现结果
python cli.py "https://example.com/book/2.html" --discover-only
```

## 项目结构

```
├── app.py                    # 桌面应用入口
├── cli.py                    # 命令行模式
├── run.bat                   # 一键启动
├── build.bat                 # 一键打包 exe（PyInstaller）
├── requirements.txt
├── novel_catcher/
│   ├── config.py             # 配置管理（config.json）
│   ├── db.py                 # SQLite 书籍库
│   ├── manager.py            # 下载任务管理（并发/取消/进度）
│   ├── crawler/
│   │   ├── http.py           # HTTP 层（指纹模拟/重试/编码识别）
│   │   ├── discover.py       # 章节位置推测
│   │   ├── extract.py        # 正文提取与清洗
│   │   └── pipeline.py       # 抓取管线
│   └── exporter/
│       ├── txt.py            # TXT 导出
│       └── epub.py           # EPUB 导出
├── tests/                    # 自动化测试（本地模拟站 + 集成测试）
└── output/                   # 下载输出（不入库）
```

## 测试

```bat
python tests\test_pipeline.py   :: 引擎端到端测试（16 项断言）
python tests\test_integration.py :: 管理器+数据库+导出集成测试
```

测试使用本地模拟小说站（`tests/mock_site.py`），不依赖外网，可重复运行。

## 常见问题

| 现象 | 处理 |
|---|---|
| 403 / 连接被重置 | 站点可能封禁当前网络或开启反爬；稍后再试或换站点 |
| 预览只发现你给的几章 | 该站 URL 无数字规律且无目录/上下章链接，暂无法自动推断 |
| EPUB 生成失败 | 不影响 TXT 输出，可查看日志原因 |
| 下载速度慢 | 提高「设置 → 并发数」，注意控制礼貌性 |

## 贡献指南

请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)，其中包含提交信息规范、分支规范与开发约定。

## 许可证

[MIT](LICENSE) © TXT_Catcher Contributors
