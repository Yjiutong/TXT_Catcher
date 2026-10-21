# TXT_Catcher 阅读捕获浏览器

> 不再做“给几章网址就自动抓全本”。现在把它当**阅读浏览器**用：
> 从顶部输入网址进入小说页，浏览过的、疑似小说正文/目录的文本会被捕获，
> 最后导出一个捕获包，交给 Codex 的 `novel_pack_to_epub` skill 整理成 EPUB。

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB)
![Platform](https://img.shields.io/badge/Platform-Windows-0078D6)
![GUI](https://img.shields.io/badge/GUI-Tkinter-5C7CFA)
![License](https://img.shields.io/badge/License-MIT-green)
![Version](https://img.shields.io/badge/Version-2.0.0-blue)

---

## 快速开始

- 直接双击根目录 `run.bat`，优先启动 `dist\TXT_Catcher.exe`。
- 源码运行：

```bat
.\.buildenv\Scripts\pythonw.exe app.py
```

## 使用流程

1. 打开应用，首页是**阅读浏览**。
2. 在顶部地址栏输入小说页网址，点击 **前往**。
3. 应用会抓取并清洗当前页：
   - 目录页 → 显示“目录候选”，可点击章节链接继续浏览。
   - 正文页 → 显示“正文候选”，把正文段落收进捕获包。
   - 其他页面 → 仍记录 URL 与文本，方便 Codex 判断。
4. 右侧“已捕获页面”列表实时汇总你浏览过的页面。
5. 浏览完点击 **导出捕获包**，生成 zip / 文件夹。
6. 把捕获包交给 Codex，按 `skills/novel_pack_to_epub/SKILL.md` 整理为 EPUB + TXT。

## 捕获包结构

导出位置默认是：

```text
output/capture_packages/<书名或阅读捕获>_<时间戳>.zip
├── manifest.json   # 包说明、书名、作者、统计
├── pages.json      # 完整捕获包（schema_version=1）
└── all_text.txt    # 按页面拼接的可读文本
```

## Codex skill

仓库内已经提供 skill：

```text
skills/novel_pack_to_epub/
├── SKILL.md
└── scripts/build_epub_from_package.py
```

把捕获包 zip 交给 Codex 后，可以用这个命令直接整理：

```bat
.\.buildenv\Scripts\python.exe skills\novel_pack_to_epub\scripts\build_epub_from_package.py "output\capture_packages\xxx.zip" "output"
```

输出 `书名.epub` 和 `书名.txt`。skill 会按目录候选排序、按 URL 去重、把正文段落组装成章节。

## 项目结构

```text
├── app.py                          # 桌面应用入口：阅读浏览器 UI
├── run.bat                         # 一键启动
├── build.bat                       # 一键打包 exe
├── skills/novel_pack_to_epub/     # 捕获包 → EPUB skill
├── novel_catcher/
│   ├── capture.py                  # 捕获包：分类、去重、导出、组装 BookResult
│   ├── crawler/                    # HTTP / 正文提取 / 目录发现 / 站点规则
│   ├── exporter/                   # TXT / EPUB 导出
│   ├── config.py                   # 配置管理
│   └── manager.py                  # 历史下载任务（保留兼容）
├── tests/                          # 自动化测试
└── output/                         # 输出目录（不入库）
```

## 测试

```bat
.\.buildenv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
.\.buildenv\Scripts\python.exe tests\test_pipeline.py
.\.buildenv\Scripts\python.exe tests\test_integration.py
```

测试使用本地模拟小说站，不依赖外网。

## 使用边界

> ⚠️ 本工具只用于整理**非版权（公版）作品**和用户有权访问的内容。
> 不自动补抓缺失章节，不虚构内容。请遵守目标网站访问规则与当地法律。

## 许可证

[MIT](LICENSE) © TXT_Catcher Contributors
