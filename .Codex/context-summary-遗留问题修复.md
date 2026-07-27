## 项目上下文摘要（遗留问题修复）
生成时间：2026-07-27 21:31:20 CST

### 1. 目标与范围
- 修复上一轮审查报告中的高、中优先级问题。
- 加入自动发布完整性门禁和 EPUB 标准校验。
- 补齐爬虫、发现脚本、PDF、CLI 与工作流回归测试。
- 不在本轮进行与缺陷无关的大规模 CLI 架构重写。

### 2. 复用的三个现有模式
- `crawler.py:_get()`：统一 HTTP 超时与状态检查；发现脚本补齐相同的 `raise_for_status()` 约束。
- `types.py` + 两个生成器：采集数据继续通过 `Article/ContentBlock` 输入 PDF 和 EPUB，不改变协议。
- `build-issue.yml`：沿用发现、构建、发布顺序，在发布前插入严格完整性与 EPUBCheck 门禁。

### 3. 修复设计
- **残缺整期**：CLI 增加 `--strict`；本地默认允许尽力生成，Action 强制严格失败。
- **图片冲突**：使用 URL SHA-256 前 12 位加规范扩展名，查询参数进入哈希但不进入文件名。
- **无扩展名图片**：使用响应 `Content-Type` 决定扩展名。
- **元数据漂移**：标题按 h1 → Open Graph → meta → JSON-LD 回退；作者按 appellation → meta → JSON-LD 回退；期号按 appellation → description → JSON-LD 回退。
- **HTTP 错误**：发现脚本解析 HTML 前执行 `raise_for_status()`。
- **发布校验**：GitHub Runner 安装 Java 21，下载 W3C EPUBCheck 5.3.0，校验成功后才发布。

### 4. 测试模式与覆盖
- 使用项目已采用的标准库 `unittest`，不新增测试框架。
- `test_crawler.py`：图片冲突、查询参数、Content-Type、Open Graph、JSON-LD。
- `test_discover_issue.py`：HTTP 状态、最新期排序、期号提取。
- `test_entry.py`：严格停止与默认降级。
- `test_pdf.py`：LaTeX 转义、文本渲染、整期结构、缺少 XeLaTeX。
- `test_epub.py`：EPUB 容器、目录、封面、图片、CLI 参数。
- `test_workflow.py`：严格模式、Java、EPUBCheck、发布顺序。

### 5. 依赖与集成点
```text
HTTP 响应
 ├─ 状态检查
 ├─ HTML 主选择器
 └─ meta / JSON-LD 回退
       ↓
Article + 哈希图片缓存
 ├─ PDFGenerator
 └─ EPUBGenerator
       ↓
CLI --strict 完整性门禁
       ↓
GitHub Action EPUBCheck
       ↓
Release
```

### 6. 风险与边界
- JSON-LD 允许字典、列表及 `@graph`，无效 JSON 会跳过而不影响主选择器。
- 未知图片类型在无法识别 Content-Type 时回退为 JPEG；测试覆盖常用网络图片类型。
- 严格模式只影响整期，单篇模式行为不变。
- 本地没有 Java 与 XeLaTeX，分别通过结构/回读测试和无编译 PDF 渲染测试补偿；Action 显式安装 Java 与 TeX Live。

### 7. 工具记录
- `sequential-thinking`、`shrimp-task-manager`、`desktop-commander`、Context7 仍不可用。
- 替代：结构化计划、`rg/sed/git` 本地检索、W3C EPUBCheck 官方文档和 GitHub 开源检索。
- 官方依据：W3C EPUBCheck 5.3.0 是 EPUB 3.3 的生产版本校验器。

### 8. 充分性检查
- [x] 明确严格模式输入、错误条件与退出行为。
- [x] 明确元数据回退顺序和图片缓存命名协议。
- [x] 明确 Action 校验必须早于 Release。
- [x] 每项修复均有本地自动化测试。
