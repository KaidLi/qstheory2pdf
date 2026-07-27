## 操作日志

### 2026-07-27 21:12:38 CST：任务启动与工具检查
- 目标：检查项目问题，并在现有数据层上增加 EPUB 输出，更新本地验证与 GitHub Action。
- 范围：Python 源码、测试、依赖、README、GitHub Action 与审查文档。
- 交付物：EPUB 生成器、CLI 集成、Action 发布、测试、上下文摘要、验证报告。
- 审查要点：不重复抓取、EPUB 可重排、图片可用、目录正确、PDF 旧用法保持可用。
- `sequential-thinking`、`shrimp-task-manager`、`desktop-commander`、Context7 均未在当前会话提供。
- 补偿措施：使用结构化分析记录模拟深度思考，使用任务计划模拟任务管理，使用 `rg/sed/git` 完成本地只读检索，使用 W3C 与 EbookLib 官方文档补足技术资料。
- 首次本地验证因受限的默认 uv 缓存和网络失败；改用 `/tmp/qstheory2pdf-uv-cache`，经授权执行 `uv sync` 后依赖安装成功。

## 编码前检查 - EPUB 模块与项目体检
时间：2026-07-27 21:12:38 CST

- [x] 已查阅上下文摘要文件：`.Codex/context-summary-EPUB模块与项目体检.md`
- [x] 将使用以下可复用组件：
  - `types.py` 的 `Article/ContentBlock/TocEntry`：统一输入数据契约。
  - `QiuShiCrawler`：一次抓取并共享图片目录。
  - `_issue_article_urls()`：目录文章过滤。
  - `_safe_name()`：默认输出路径命名。
- [x] 将遵循命名约定：模块与函数使用 `snake_case`，类使用 `PascalCase`。
- [x] 将遵循代码风格：Python 3.10+ 类型注解、四空格、标准库/第三方/内部导入分组。
- [x] 确认不重复造轮子：检查了 `src/qstheory2pdf`、`scripts`、工作流和依赖清单；项目内不存在 EPUB 能力，选择成熟 EbookLib。

### 编码前验收条件
1. 默认命令仍生成 PDF；`--format epub` 不需要 XeLaTeX；`--format both` 一次抓取生成两种格式。
2. 单篇和整期 EPUB 均包含元数据、导航、可重排正文和本地图片。
3. 整期每篇文章独立成章，目录顺序与抓取顺序一致。
4. EPUB 容器可被标准 ZIP/XML 检查打开，`mimetype` 为首项且不压缩。
5. Action 在构建 PDF 的同时发布一份 EPUB，并在发布前运行本地测试。
6. 正常、边界与错误路径均有自动化测试。

## 编码中检查 - EPUBGenerator
时间：2026-07-27 21:20:23 CST

- [x] 使用了摘要中的 `Article/ContentBlock/TocEntry`、`_safe_name()` 和共享图片目录。
- [x] 命名与现有 `PDFGenerator` 对齐：`EPUBGenerator`、`gen_single()`、`gen_issue()`。
- [x] 展示层与爬虫层分离，EPUB 不包含抓取逻辑。
- [x] 通过 EbookLib 生成 OPF、导航、NCX 与 OCF 容器，不自研 EPUB 打包协议。

## 编码中检查 - CLI 与 GitHub Action
时间：2026-07-27 21:20:23 CST

- [x] 默认格式仍为 PDF，旧命令语义不变。
- [x] `--format epub` 使用独立临时图片目录，不触发 XeLaTeX。
- [x] `--format both` 共享一次抓取结果。
- [x] Action 对新刊发布 PDF 与 EPUB，并能为既有 Release 补齐 EPUB。

## 验证记录
时间：2026-07-27 21:20:23 CST

1. `uv lock`：成功，项目版本从 0.1.0 更新为 0.2.0，锁定 EbookLib 0.20。
2. `python -m compileall -q src scripts tests`：成功。
3. `python -m unittest discover -s tests -v`：
   - 首次：5 项通过、1 项失败；原因是 macOS `/var` 与 `/private/var` 为同一目录的路径字符串差异。
   - 修正测试为 `samefile()` 后：6/6 通过。
4. `qstheory2pdf --help`：成功，展示 `pdf|epub|both`。
5. 真实求是文章端到端：成功生成 `/tmp/qstheory2pdf-real.epub`。
6. `unzip -t`：EPUB 内全部 10 个条目无压缩错误，包含 `mimetype`、容器、OPF、NCX、导航、CSS、图片和章节。
7. `ebooklib.epub.read_epub`：成功回读，标题为“推动全民阅读，建设书香社会”，共 7 个出版物项目。
8. Ruby YAML 解析：工作流文件解析成功。
9. `git diff --check`：成功，无空白错误。
10. PDF 本地编译：明确失败，`xelatex` 不存在；符合用户已知环境限制，GitHub Action 保留完整 TeX Live 安装和构建步骤。
11. `epubcheck` 与 `actionlint`：本地未安装。补偿措施为 ZIP 完整性、XML 解析、EbookLib 回读、容器单元测试和 YAML 解析；后续建议在 Action 增加 EPUBCheck。

## 编码后声明 - EPUB 模块与项目体检
时间：2026-07-27 21:20:23 CST

### 1. 复用了以下既有组件
- `Article/ContentBlock/TocEntry`：PDF 与 EPUB 使用同一语义数据。
- `QiuShiCrawler`：单次采集文章、封面和图片。
- `_safe_name()`：沿用默认输出命名规则。
- GitHub Action 的发现、去重、Release 与 Artifact 流程。

### 2. 遵循了以下项目约定
- 命名：生成器接口与 `PDFGenerator` 对称。
- 代码风格：Python 3.10+ 注解、导入分组和四空格缩进。
- 文件组织：新增 `gen_epub.py` 作为展示层，测试放入 `tests/`。

### 3. 对比了以下相似实现
- `gen_pdf.py`：EPUB 保持单篇/整期接口，但不拥有爬虫或 LaTeX 逻辑。
- `crawler.py`：不修改数据采集协议，避免破坏 PDF。
- `entry.py`：保留原有模式识别和错误降级，扩展输出编排。
- `build-issue.yml`：保留定时发布，新增 EPUB 和历史 Release 补齐逻辑。

### 4. 未重复造轮子的证明
- 项目内没有 EPUB 模块。
- 使用 EbookLib 处理 EPUB 标准结构，仅实现项目特有的文章到章节映射与墨水屏 CSS。

## 遗留问题修复 - 编码前检查
时间：2026-07-27 21:31:20 CST

- [x] 已查阅 `.Codex/verification-report.md` 与 `.Codex/context-summary-遗留问题修复.md`。
- [x] 复用 `QiuShiCrawler._get()`、`Article` 数据契约、生成器接口和 Action 发布流程。
- [x] 遵循现有 `snake_case` / `PascalCase` 命名与标准库 `unittest` 测试方式。
- [x] 不重复实现 EPUB 校验器，使用 W3C EPUBCheck 5.3.0。
- [x] 工具缺失及替代路径已记录。

## 遗留问题修复 - 实施记录
时间：2026-07-27 21:31:20 CST

1. 新增 `--strict`，整期下载失败或正文为空时退出 1；Action 所有生成命令均启用。
2. 图片缓存文件名改为“净化名称 + URL 哈希 + 规范扩展名”，无扩展名时读取 Content-Type。
3. 标题、作者和期号加入 Open Graph、标准 meta 与 JSON-LD 回退。
4. 发现脚本加入 HTTP 状态检查。
5. Action 加入 Java 21 与 W3C EPUBCheck 5.3.0，校验步骤位于 Release 之前。
6. 测试从 6 项扩展到 23 项，覆盖采集、发现、CLI、PDF、EPUB 和工作流门禁。

## 遗留问题修复 - 编码后声明
时间：2026-07-27 21:31:20 CST

- 复用：没有改变 `Article/ContentBlock` 协议，PDF 与 EPUB 继续共享一次抓取。
- 一致性：网络错误沿用 Requests 异常，CLI 错误提示保持简体中文。
- 差异：本地默认保留尽力生成，自动发布使用严格模式；这是交互便利性与正式发布完整性的明确分层。
- 未重复造轮子：哈希使用标准库，结构化数据使用 JSON 标准库，EPUB 规范检查使用 W3C 官方工具。

## 遗留问题修复 - 最终验证
时间：2026-07-27 21:31:20 CST

- `uv sync --locked`：通过。
- `python -m compileall -q src scripts tests`：通过。
- `python -m unittest discover -s tests -v`：23/23 通过。
- 真实文章 `/tmp/qstheory2pdf-fixed.epub`：生成成功。
- `unzip -t`：全部 EPUB 条目通过。
- EbookLib 回读：标题“推动全民阅读，建设书香社会”，7 个出版物项目。
- GitHub Actions YAML：本地 Ruby 解析通过。
- `git diff --check`：通过。
- 本地 EPUBCheck：未执行，原因是没有 Java Runtime；Action 已加入 Temurin 21 和 W3C EPUBCheck 5.3.0，且本地结构验证作为补偿。
- 本地 PDF 编译：未执行，原因是没有 XeLaTeX；PDF 展示层回归测试 4 项通过。
