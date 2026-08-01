# qstheory2pdf

从求是网（qstheory.cn）的公开来源重建《求是》文章或完整期次，并生成 PDF/EPUB 呈现版本。工具会区分文章、官方期次目录和期次目录集，默认拒绝把已知缺篇或缺少正文语义的结果冒充完整出版物。EPUB 为可重排版，不需要安装 LaTeX，适合墨水屏阅读器。

领域术语、身份与完整性规则见 [`CONTEXT.md`](CONTEXT.md)。

## 准备

### 1. 安装 uv

本项目使用 [uv](https://docs.astral.sh/uv/) 管理依赖。如果尚未安装：

```bash
# Windows
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. 安装 xelatex（仅生成 PDF 时需要）

xelatex 用于 PDF 编译。只生成 EPUB 时可以跳过这一步。

- **Ubuntu/Debian**: `sudo apt install texlive-xetex texlive-latex-extra texlive-lang-chinese`
- **macOS**: `brew install --cask mactex` 或安装 [MacTeX](https://tug.org/mactex/)
- **Windows**: 安装 [TeX Live](https://tug.org/texlive/) 并确保 xelatex 在 PATH 中

## 安装

```bash
git clone https://github.com/KaidLi/qstheory2pdf.git
cd qstheory2pdf
uv sync
```

如果你希望全局安装（之后可在任意目录直接使用 `qstheory2pdf` 命令），也可以用 pip：

```bash
pip install .
```

## 快速验证

没有安装 LaTeX 时，可先生成 EPUB 验证环境：

```bash
uv run qstheory2pdf --format epub https://www.qstheory.cn/20260415/eb2be76d239d4fa4a0ef3a9a9d82b970/c.html
```

## 使用方法

```
uv run qstheory2pdf [--format pdf|epub|both] [--allow-partial] [-d 设备] [-o 输出路径] [-s] <url>
```

| 参数 | 说明 |
|------|------|
| `url` | 文章、官方期次目录或期次目录集的来源 URL（必填） |
| `--format` | 输出格式：`pdf`（默认）、`epub` 或 `both` |
| `-d, --device` | 阅读设备预设，默认 `normal` |
| `-f, --font` | 字体方案：`auto`（默认，开源字体自动探测）/ `wenkai`（全文霞鹜文楷） |
| `-o, --output` | 输出路径；`both` 时作为基础路径；目录集模式下作为输出目录 |
| `-s, --single` | 声明期望输入为文章；若来源实际是期次目录或期次目录集则报错 |
| `--allow-partial` | 显式允许部分重建；文件名追加 `-partial`，内容中醒目标示缺失原因 |
| `--strict` | 已弃用的兼容别名；完整重建现在本来就是默认要求 |
| `--status-file` | 写入机器可读的完整性状态 JSON，供 CI 或外部工具检查 |

### 设备预设

| 预设 | 纸张尺寸 | 适用设备 |
|------|----------|----------|
| `normal` | A4 | 打印（默认） |
| `pad` | 6×8 in | 平板 |
| `kindle` | 3.68×4.92 in | Kindle（旧款） |
| `scribe` | 5.83×7.76 in | Kindle Scribe |
| `screen` | 25.4×19.05 cm | 显示器 |
| `pc` | 6.2×6 in | PC 窗口 |

彩色屏设备（normal/pad/screen/pc）使用「求是红」主题色；墨水屏设备（kindle/scribe）自动使用纯黑主题（彩色在墨水屏上会抖成脏灰）。

## 示例

单篇文章：

```bash
uv run qstheory2pdf https://www.qstheory.cn/20260415/eb2be76d239d4fa4a0ef3a9a9d82b970/c.html
```

单篇 EPUB（本地不需要 LaTeX）：

```bash
uv run qstheory2pdf --format epub https://www.qstheory.cn/20260415/eb2be76d239d4fa4a0ef3a9a9d82b970/c.html
```

整期杂志（工具会自动识别目录页，下载全部文章并合并为一个 PDF）：

```bash
uv run qstheory2pdf https://www.qstheory.cn/20260415/94280df5956349b0954c44d728bb75a1/c.html
```

期次目录集（自动识别年度目录，按期号分别生成独立文件）：

```bash
uv run qstheory2pdf --format both -o output/2026 \
  https://www.qstheory.cn/20251231/2d916da295774130ac2fb223fd208895/c.html
```

目录集模式不会把各期合并成“全年合刊”，而是生成
`求是_2026_01.pdf`、`求是_2026_01.epub`、`求是_2026_02.pdf`等独立文件。
不指定 `-o` 时仍输出到 `output/`。

指定设备和输出路径：

```bash
uv run qstheory2pdf -d kindle -o my.pdf https://www.qstheory.cn/20260415/eb2be76d239d4fa4a0ef3a9a9d82b970/c.html
```

一次抓取并同时生成 PDF 与 EPUB：

```bash
uv run qstheory2pdf --format both -d scribe -o output/qstheory-2026-08 <url>
```

声明输入必须是单篇文章（误传目录页时立即报错）：

```bash
uv run qstheory2pdf -s https://www.qstheory.cn/20260415/eb2be76d239d4fa4a0ef3a9a9d82b970/c.html
```

只有在预览或诊断时才应显式允许部分重建：

```bash
uv run qstheory2pdf --allow-partial --format epub <url>
```

部分产物会使用 `-partial` 后缀，并在扉页及缺失位置标明原因；自动发布不会使用该选项。

## 字体（三端一致的开源方案）

`qiushi.cls` 优先使用开源字体组合——只要装了这些字体，Windows / macOS / Linux(CI) 的输出**完全一致**，且生僻字（祎、頔、赟、曌……）全覆盖：

| 用途 | 字体 |
|------|------|
| 正文（宋体） | 思源宋体 / Noto Serif CJK SC |
| 标题（黑体） | 思源黑体 / Noto Sans CJK SC |
| 楷体（作者、图注、引文） | 霞鹜文楷 LXGW WenKai |

安装方法：

- **Linux / CI**：`sudo apt install fonts-noto-cjk fonts-lxgw-wenkai`（GitHub Actions 的 workflow 已包含）
- **Windows / macOS**：下载后安装即可（Windows 建议右键「为所有用户安装」，否则 xelatex 可能找不到）：
  - 霞鹜文楷：[lxgw/LxgwWenKai Releases](https://github.com/lxgw/LxgwWenKai/releases)（下载 `LXGWWenKai-Regular.ttf`、`-Medium.ttf`、`-Light.ttf` 三个）
  - 思源宋体：[adobe-fonts/source-han-serif](https://github.com/adobe-fonts/source-han-serif/releases)（SubsetOTF 的 SC 版）或 Noto Serif CJK
  - 思源黑体：[adobe-fonts/source-han-sans](https://github.com/adobe-fonts/source-han-sans/releases)（SubsetOTF 的 SC 版）或 Noto Sans CJK

没装也能用：会按「开源组合 → Windows 系统字体 → macOS 系统字体 → Fandol 兜底」的顺序自动回退（Fandol 生僻字覆盖有限，不推荐依赖）。

喜欢全文楷体的阅读风格？加 `-f wenkai` 即可让全文（含西文）都用霞鹜文楷：

```bash
uv run qstheory2pdf -f wenkai <url>
```

## 输出

PDF 和 EPUB 默认保存到当前目录下的 `output/` 文件夹，文件名由文章标题或期号自动生成。年度索引模式按期号分别生成文件，`-o` 表示这一批文件的输出目录。生成完成后自动清理下载的临时图片与编译目录。

## GitHub Actions CI 与自动发布

普通 push、Pull Request 和手动触发会运行独立的 _CI_ workflow：在 Python 3.10/3.12 上执行完整测试，并用 XeLaTeX 与 EPUBCheck 构建、校验确定性的 PDF/EPUB 冒烟产物。该 workflow 只有仓库只读权限，不会创建 Release。

发布 workflow 每月 1 日和 16 日自动发现并构建最新一期《求是》的 PDF 与 EPUB，发布到 [Releases](https://github.com/KaidLi/qstheory2pdf/releases)。因此本地没有 LaTeX 也不影响 PDF 发布。

**手动触发**：在 Actions 页面选择 _Build and Release Publications_ → _Run workflow_，可选填 TOC URL 和设备类型。

**工作原理**：

1. 定时触发（或手动）→ 从 [官方期次目录入口](https://www.qstheory.cn/qs/mulu.htm) 自动发现最新期 URL
2. 检查该期是否已发布过 Release（按 tag `qstheory-2026-08` 去重）
3. 未发布 → 构建 PDF 与 EPUB → 发布 Release 并上传附件
4. 已发布但缺少 EPUB → 自动补齐 EPUB；两种格式齐全则跳过

**字体**：workflow 安装 Noto CJK 与霞鹜文楷，`qiushi.cls` 自动检测使用，无需任何手动切换。手动触发时可在 `font` 下拉框选 `wenkai` 生成全文楷版本。

**发布门禁**：自动构建要求 CLI 写出的 `reconstruction-*.json` 状态为 `complete`，不允许 `--allow-partial`；EPUB 还会使用 W3C EPUBCheck 5.3.0 校验。只有领域完整性与文件格式校验都通过后才创建 Release。

## 故障排查

| 问题 | 可能原因 | 解决办法 |
|------|---------|---------|
| `command not found: uv` | uv 未安装 | 按上方「准备」章节安装 uv |
| 只想生成 EPUB，但没有 LaTeX | 默认格式仍是 PDF | 添加 `--format epub` |
| `xelatex not found` | TeX Live 未安装或未加入 PATH | 安装 TeX Live，确保 xelatex 在 PATH 中 |
| 编译时报字体错误 | 缺少中文字体 | 按「字体」章节安装开源字体 |
| 生僻字显示为空白或 � | 回退到了 Fandol 字体（覆盖不全） | 安装思源/Noto + 霞鹜文楷后重新生成 |
| Windows 装了字体但没生效 | 字体装到了当前用户目录 | 重新右键选「为所有用户安装」 |
| 终端输出中文乱码 | Windows 终端默认编码为 GBK | 升级到最新版，此问题已修复 |

## 致谢

本项目基于 [qiushi2pdf](https://github.com/fengdongfa1995/qiushi2pdf) 二次开发，感谢原作者 [@fengdongfa1995](https://github.com/fengdongfa1995) 的出色工作。
