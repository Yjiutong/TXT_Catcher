# 贡献指南 / Git 规范

感谢你愿意为 TXT_Catcher 贡献力量。本文档约定仓库的**协作规范**，包括分支、提交信息、代码风格与提交流程。所有贡献默认遵循本规范，也默认接受 [MIT 许可证](LICENSE)。

---

## 1. 分支规范

| 分支 | 用途 | 命名 |
|---|---|---|
| `main` | 主分支，始终可发布 | 固定名 |
| `dev`（可选） | 集成分支 | 固定名 |
| 功能分支 | 新功能/修复，从 `main` 切出，合并后删除 | `feature/<简短描述>` |
| 修复分支 | bug 修复 | `fix/<简短描述>` |
| 杂项分支 | 文档/重构/CI 等 | `chore/<简短描述>`、`docs/<简短描述>` |

示例：`feature/url-pattern-inference`、`fix/gbk-decode`、`docs/readme-zh`.

> 规则：禁止直接向 `main` 推送代码（仓库维护者例外）；功能一律通过 PR 合入。

## 2. 提交信息规范（Conventional Commits）

提交信息采用 [Conventional Commits](https://www.conventionalcommits.org/zh-hans/) 格式：

```
<type>(<scope>): <subject>

<body>          # 可选：说明为什么改、怎么改
<footer>        # 可选：BREAKING CHANGE / 关联 issue
```

### type 类型

| type | 含义 |
|---|---|
| `feat` | 新功能 |
| `fix` | 缺陷修复 |
| `docs` | 仅文档改动 |
| `refactor` | 重构（不改变行为） |
| `perf` | 性能优化 |
| `test` | 新增或修改测试 |
| `build` | 构建/打包相关 |
| `ci` | CI 配置改动 |
| `chore` | 其他杂项（依赖、格式化等） |

### 示例

```
feat(crawler): 新增基于 URL 数字模式的章节推断

支持零填充编号（如 第001回 → 第002回），
并向两端扩展验证，连续 4 次未命中自动停止。

fix(extract): 修复正文分页链接被清洗逻辑误删

导航元素清理发生在分页链接查找之前，导致"下一页"丢失。
调整为先定位分页链接再做内容清洗。

docs(readme): 补充 Windows 运行环境说明

test(pipeline): 增加 GBK 编码与分页合并场景断言
```

### 规则

- `subject` 用祈使句、小写开头（中文提交可用中文）、不超过 72 字符、不加句号
- 一次提交只做一件事；不要混合无关改动
- 破坏性变更必须标注 `BREAKING CHANGE:` footer
- 关联 issue 使用 `Closes #12` / `Fixes #8`

## 3. 代码风格

- Python 遵循 [PEP 8](https://peps.python.org/pep-0008/)，行宽 ≤ 100
- 字符串统一使用双引号（本项目现有风格）
- 模块/docstring 使用中文或英文均可，但同一文件保持一致
- 新增对外行为必须同步更新 `README.md`；修改抓取/导出逻辑必须同步更新 `tests/`

## 4. 提交前检查

```bat
python tests\test_pipeline.py      :: 引擎测试必须全部通过
python tests\test_integration.py   :: 集成测试必须通过
```

- 提交前清理调试代码与临时文件
- 不提交：`output/`、`config.json`、`novel_catcher.db`、`logs/`、`dist/`（见 [.gitignore](.gitignore)）

## 5. PR 流程

1. 从最新 `main` 切功能分支
2. 完成改动并**补齐/更新测试**
3. 提交信息遵循上文规范，可多个提交
4. 推送分支并发起 PR 到 `main`，标题简述改动
5. 在 PR 描述中说明：改了什么、为什么、测试结果
6. 合入前确保测试通过；合入方式默认 **Squash and merge**

## 6. 发布流程（维护者）

- 版本号遵循 [SemVer](https://semver.org/lang/zh-CN/)（`MAJOR.MINOR.PATCH`）
- 每次发版：更新 `CHANGELOG.md` → 打 tag（如 `v1.0.1`）→ 构建 exe 并发布到 Releases
- 发布提交建议使用：`chore(release): v1.0.1`
