# qstheory2pdf

将求是网（qstheory.cn）文章转换为 PDF，支持单篇文章和整期杂志两种模式。

## 准备

### 1. 安装 uv

本项目使用 [uv](https://docs.astral.sh/uv/) 管理依赖。如果尚未安装：

```bash
# Windows
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. 安装 xelatex

xelatex 用于 PDF 编译，必须先安装。

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

安装完成后，运行下面这条命令，确认能生成 PDF 到 `output/` 目录：

```bash
uv run qstheory2pdf https://www.qstheory.cn/20260415/eb2be76d239d4fa4a0ef3a9a9d82b970/c.html
```

## 使用方法

```
uv run qstheory2pdf [-d 设备] [-o 输出路径] [-s] <url>
```

| 参数 | 说明 |
|------|------|
| `url` | 文章页或目录页 URL（必填） |
| `-d, --device` | 阅读设备预设，默认 `normal` |
| `-f, --font` | 字体方案：`auto`（默认，开源字体自动探测）/ `wenkai`（全文霞鹜文楷） |
| `-o, --output` | 输出 PDF 路径，默认自动命名到 `output/` 目录 |
| `-s, --single` | 强制按单篇文章模式处理（即使 URL 是目录页） |

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

整期杂志（工具会自动识别目录页，下载全部文章并合并为一个 PDF）：

```bash
uv run qstheory2pdf https://www.qstheory.cn/20260415/94280df5956349b0954c44d728bb75a1/c.html
```

指定设备和输出路径：

```bash
uv run qstheory2pdf -d kindle -o my.pdf https://www.qstheory.cn/20260415/eb2be76d239d4fa4a0ef3a9a9d82b970/c.html
```

强制单篇模式（目录页 URL 也只取当前页内容）：

```bash
uv run qstheory2pdf -s https://www.qstheory.cn/20260415/94280df5956349b0954c44d728bb75a1/c.html
```

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

PDF 文件默认保存到当前目录下的 `output/` 文件夹，文件名由文章标题或期号自动生成。生成完成后自动清理下载的临时文件（`img/` 图片缓存和 xelatex 编译临时目录）。

## GitHub Actions 自动发布

项目配置了 GitHub Actions，每月 1 日和 16 日自动发现并构建最新一期《求是》，发布到 [Releases](https://github.com/KaidLi/qstheory2pdf/releases)。

**手动触发**：在 Actions 页面选择 _Build and Release PDF_ → _Run workflow_，可选填 TOC URL 和设备类型。

**工作原理**：

1. 定时触发（或手动）→ 从 [全年目录页](https://www.qstheory.cn/qs/mulu.htm) 自动发现最新期 URL
2. 检查该期是否已发布过 Release（按 tag `qstheory-2026-08` 去重）
3. 未发布 → 构建 PDF → 发布 Release 并上传附件
4. 已发布 → 跳过

**字体**：workflow 安装 Noto CJK 与霞鹜文楷，`qiushi.cls` 自动检测使用，无需任何手动切换。手动触发时可在 `font` 下拉框选 `wenkai` 生成全文楷版本。

## 故障排查

| 问题 | 可能原因 | 解决办法 |
|------|---------|---------|
| `command not found: uv` | uv 未安装 | 按上方「准备」章节安装 uv |
| `xelatex not found` | TeX Live 未安装或未加入 PATH | 安装 TeX Live，确保 xelatex 在 PATH 中 |
| 编译时报字体错误 | 缺少中文字体 | 按「字体」章节安装开源字体 |
| 生僻字显示为空白或 � | 回退到了 Fandol 字体（覆盖不全） | 安装思源/Noto + 霞鹜文楷后重新生成 |
| Windows 装了字体但没生效 | 字体装到了当前用户目录 | 重新右键选「为所有用户安装」 |
| 终端输出中文乱码 | Windows 终端默认编码为 GBK | 升级到最新版，此问题已修复 |

## 致谢

本项目基于 [qiushi2pdf](https://github.com/fengdongfa1995/qiushi2pdf) 二次开发，感谢原作者 [@fengdongfa1995](https://github.com/fengdongfa1995) 的出色工作。
