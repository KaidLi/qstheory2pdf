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

## 跨平台字体设置

项目默认使用 Windows 中文字体集。如果你在 **macOS 或 Linux** 上运行，需要修改 `src/qstheory2pdf/resource/qiushi.cls` 第 122 行：

```diff
- \RequirePackage[UTF8,scheme=plain,fontset=windows]{ctex}
+ \RequirePackage[UTF8,scheme=plain,fontset=fandol]{ctex}
```

Fandol 字体随 `texlive-lang-chinese` 一起安装，通常无需额外配置。

## 输出

PDF 文件默认保存到当前目录下的 `output/` 文件夹，文件名由文章标题或期号自动生成。

## 故障排查

| 问题 | 可能原因 | 解决办法 |
|------|---------|---------|
| `command not found: uv` | uv 未安装 | 按上方「准备」章节安装 uv |
| `xelatex not found` | TeX Live 未安装或未加入 PATH | 安装 TeX Live，确保 xelatex 在 PATH 中 |
| 编译时报字体错误 | 非 Windows 系统缺少中文字体 | 按上方「跨平台字体设置」切换为 fandol |
| 终端输出中文乱码 | Windows 终端默认编码为 GBK | 升级到最新版，此问题已修复 |

## 致谢

本项目基于 [qiushi2pdf](https://github.com/fengdongfa1995/qiushi2pdf) 二次开发，感谢原作者 [@fengdongfa1995](https://github.com/fengdongfa1995) 的出色工作。
