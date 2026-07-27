## 质量验证报告

生成时间：2026-07-27 21:31:20 CST

### 1. 需求完整性

- **目标**：检查项目、增加 EPUB，并修复体检发现的遗留问题。
- **范围**：爬虫、期刊发现、PDF/EPUB 展示层、CLI、测试、GitHub Action、文档。
- **交付物**：
  - EPUB：`src/qstheory2pdf/gen_epub.py`
  - 稳健爬虫：`src/qstheory2pdf/crawler.py`
  - 严格发布：`src/qstheory2pdf/entry.py`
  - HTTP 状态修复：`scripts/discover_issue.py`
  - 发布门禁：`.github/workflows/build-issue.yml`
  - 回归测试：`tests/`
  - 文档和审计：`README.md`、`CLAUDE.md`、`.Codex/`
- **原始意图覆盖**：本地无 LaTeX 时可生成 EPUB；PDF 由 Action 编译；正式 Release 不发布残缺整期。

### 2. 遗留问题修复结果

| 原问题 | 结果 | 修复 |
|---|---|---|
| 整期下载失败仍发布 | 已修复 | `--strict` 检测下载失败与空正文，Action 强制启用 |
| 原核心链路无测试 | 已修复 | 测试从 6 项增至 23 项，覆盖爬虫、发现、CLI、PDF、EPUB、工作流 |
| 图片同名覆盖和查询参数文件名 | 已修复 | 文件名加入 URL 哈希，扩展名规范化 |
| 无扩展名网络图片 | 已修复 | 读取 Content-Type 选择扩展名 |
| 发现脚本不检查 HTTP 状态 | 已修复 | 解析前调用 `raise_for_status()` |
| `appellation` 元数据依赖脆弱 | 已修复 | Open Graph、标准 meta、JSON-LD 分层回退 |
| 缺少 EPUB 标准门禁 | 已修复 | Release 前执行 W3C EPUBCheck 5.3.0 |
| CLI 导入依赖终端 `reconfigure` | 已修复 | 对嵌入式输出流使用能力检查 |

### 3. 自动化验证

| 验证 | 结果 |
|---|---|
| `uv sync --locked` | 通过，锁文件一致 |
| `compileall` | 通过 |
| `unittest discover` | 23/23 通过 |
| CLI 帮助与参数 | 通过，包含 `pdf|epub|both` 和 `--strict` |
| 真实文章 EPUB 生成 | 通过 |
| EPUB ZIP 完整性 | 通过，所有条目无错误 |
| EbookLib 回读 | 通过，标题与出版物项目正确 |
| GitHub Actions YAML 解析 | 通过 |
| 工作流门禁契约测试 | 通过，EPUBCheck 位于 Release 前 |
| `git diff --check` | 通过 |

### 4. 验证限制与补偿

- 本机没有 XeLaTeX，因此未实际编译 PDF；已测试 LaTeX 转义、块渲染、整期 TeX 结构和缺编译器错误，Action 仍安装完整 TeX Live。
- 本机没有 Java，因此未执行本地 EPUBCheck；已执行 ZIP/XML、EbookLib 回读和 EPUB 结构测试。Action 显式安装 Temurin Java 21，并执行 W3C EPUBCheck 5.3.0。
- 未使用远程 CI 结果作为本次验收依据。

### 5. 依赖和风险

- 新运行依赖仅为 EbookLib 0.20 及其轻量传递依赖。
- 图片哈希计算为 O(URL 长度)，不会改变整期主要 I/O 成本。
- JSON-LD 无效时会安全跳过并继续使用其他元数据来源。
- 严格模式只改变显式启用者；旧 CLI 默认仍可生成成功抓取的部分内容。
- 自动发布统一启用严格模式，保证正式附件完整性。

### 6. 剩余低风险事项

1. `entry.py` 仍承担较多编排职责；只有继续增加更多输出格式时才需要拆分为采集服务和输出调度器。
2. 网站结构仍可能再次变化，但分层元数据回退和测试夹具已经显著降低回归概率。
3. 本地若需要与 Action 完全等价的 PDF/EPUBCheck 验证，仍需安装 XeLaTeX 和 Java。

### 7. 评分

#### 技术维度
- 代码质量：96/100
- 测试覆盖：95/100
- 规范遵循：96/100

技术维度加权：96/100

#### 战略维度
- 需求匹配：98/100
- 架构一致：96/100
- 风险评估：95/100

战略维度加权：96/100

### 8. 结论

- **综合评分：96/100**
- **建议：通过**

上一轮报告中的高、中优先级遗留问题均已关闭。剩余事项属于低风险维护建议，不阻塞 EPUB 或 GitHub 自动发布。
