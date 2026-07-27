## 项目上下文摘要（EPUB 模块与项目体检）
生成时间：2026-07-27 21:12:38 CST

### 1. 相似实现分析
- **实现 1**：`src/qstheory2pdf/crawler.py:32`
  - 模式：数据采集层通过 `QiuShiCrawler` 输出语义化 `Article`，图片生命周期由调用方提供的 `image_dir` 管理。
  - 可复用：`fetch_toc()`、`fetch_info()`、`download_toc_cover()`。
  - 需注意：元数据依赖网站的 `appellation` 结构；图片文件名直接取 URL 尾段，存在同名覆盖风险。
- **实现 2**：`src/qstheory2pdf/gen_pdf.py:92`
  - 模式：展示层生成器消费 `Article/ContentBlock`，负责格式转义、文档结构和输出文件。
  - 可复用：单篇/整期两个公开入口、默认输出目录、`_safe_name()`。
  - 需注意：临时图片目录目前由 PDF 生成器拥有，新增 EPUB 时应避免重复抓取。
- **实现 3**：`src/qstheory2pdf/entry.py:30`
  - 模式：CLI 负责模式识别、一次抓取、失败降级和生成器编排。
  - 可复用：`_issue_article_urls()`、目录条目补全、封面可选降级。
  - 需注意：当前 `main()` 职责过多且直接 `sys.exit()`，不利于单元测试；输出格式被写死为 PDF。
- **实现 4**：`.github/workflows/build-issue.yml:35`
  - 模式：定时或手动发现期刊，构建多设备 PDF，发布 Release 与 Artifact。
  - 可复用：依赖安装、期号去重、ASCII 文件名和失败日志。
  - 需注意：只有导入冒烟，没有单元测试；发布步骤只匹配 PDF。

### 2. 项目约定
- **命名约定**：Python 模块、函数与变量使用 `snake_case`，类使用 `PascalCase`，内部帮助函数使用前导下划线。
- **文件组织**：采集、类型契约、展示生成、CLI 分层；资源放在包内 `resource/`。
- **导入顺序**：标准库、第三方库、项目内模块，组间空行。
- **代码风格**：Python 3.10+ 类型注解，四空格缩进；现有英文文档字符串和注释属于历史风格，新写说明性内容使用简体中文。

### 3. 可复用组件清单
- `src/qstheory2pdf/types.py`：`Article`、`ContentBlock`、`TocEntry` 数据契约。
- `src/qstheory2pdf/crawler.py`：文章、目录和图片采集。
- `src/qstheory2pdf/gen_pdf.py:_safe_name`：默认输出文件名净化。
- `src/qstheory2pdf/entry.py:_issue_article_urls`：整期文章 URL 过滤。

### 4. 测试策略
- **现状**：仓库没有 `tests/`，也没有 pytest 等测试依赖；Action 仅执行导入冒烟和真实 PDF 构建。
- **采用框架**：Python 标准库 `unittest`，不新增测试工具。
- **覆盖要求**：EPUB 单篇、整期、目录顺序、文本转义、图片与封面、默认命名、缺图错误、容器结构。
- **本地验证**：`compileall`、`unittest`、ZIP/XML 结构校验；若可获得 `epubcheck` 再执行标准校验。

### 5. 依赖和集成点
- **外部依赖**：`requests`、`lxml`、`qrcode`、`Pillow`；计划复用成熟 `EbookLib` 生成 EPUB。
- **内部依赖**：EPUB 生成器只依赖 `types.py` 契约和抓取后的图片目录，与 LaTeX 解耦。
- **集成方式**：CLI 通过 `--format pdf|epub|both` 编排；Action 发布 `output/*.pdf` 与 `output/*.epub`。
- **配置来源**：`pyproject.toml`、`uv.lock`、`.github/workflows/build-issue.yml`。

### 6. 技术选型理由
- **为什么使用 EbookLib**：属于成熟的 Python EPUB 生成库，能生成 OPF、导航文档、NCX 和符合容器约束的 ZIP，减少自研标准打包逻辑。
- **标准依据**：W3C EPUB 3.3 要求包文档、导航文档、阅读顺序和 OCF 容器；生成结果需具备这些结构。
- **优势**：纯 Python、本地不依赖 LaTeX，适合墨水屏的可重排内容。
- **劣势和风险**：不同阅读器 CSS 支持不一致；必须保持简单排版并添加结构测试。

### 7. 关键风险点
- **并发问题**：当前无并发抓取；同名远端图片可能写入同一路径。
- **边界条件**：空标题、空正文、缺图、未知图片扩展名、重复标题、目录条目缺失。
- **性能瓶颈**：整期图片常驻临时目录和 EPUB ZIP；按文章拆分 XHTML 避免单个超大文档。
- **兼容考虑**：EPUB 使用简单 XHTML/CSS，同时写入 EPUB 3 导航与 NCX，兼顾较旧墨水屏阅读器。

### 8. 依赖与集成关系
```text
URL
 └─ QiuShiCrawler
     ├─ TocResult
     ├─ Article[]
     └─ image_dir
         ├─ PDFGenerator → XeLaTeX → PDF
         └─ EPUBGenerator → EbookLib → EPUB

GitHub Action
 ├─ 本地单元测试
 ├─ XeLaTeX 构建 PDF
 └─ Python 直接构建 EPUB
```

### 9. 工具与资料追溯
- GitHub 插件：确认远端 `KaidLi/qstheory2pdf`、默认分支和权限；搜索了开源 EPUB 容器实现。
- W3C EPUB 3.3：确认包文档、导航文档、spine 与 OCF 容器为必要结构。
- EbookLib 官方教程：确认 `EpubBook`、章节、导航、NCX 与写出流程。
- 工具缺失：`sequential-thinking`、`shrimp-task-manager`、`desktop-commander`、Context7 当前不可用；分别以结构化分析、任务计划、`rg/sed` 只读检索和官方文档检索补偿。

### 10. 充分性检查
- [x] 能定义接口契约：输入为 `Article`/`Article[]`、图片目录和元数据，输出为 EPUB 文件路径。
- [x] 理解技术选型：复用 EbookLib 和现有语义数据层。
- [x] 识别主要风险：图片冲突/缺失、阅读器 CSS 差异、现有测试空白、网站结构漂移。
- [x] 知道验证方式：单元测试、ZIP/XML 结构检查、CLI 冒烟和 Action 静态检查。
