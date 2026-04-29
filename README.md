# qiushi2pdf

将求是网（qstheory.cn）文章转换为 PDF，支持单篇文章和整期杂志两种模式。

## 系统依赖

需要 xelatex 用于 PDF 编译。

- **Ubuntu/Debian**: `sudo apt install texlive-xetex texlive-latex-extra texlive-lang-chinese`
- **macOS**: `brew install --cask mactex` 或安装 [MacTeX](https://tug.org/mactex/)
- **Windows**: 安装 [TeX Live](https://tug.org/texlive/) 并确保 xelatex 在 PATH 中

## 安装

```bash
git clone https://github.com/fengdongfa1995/qiushi2pdf.git
cd qiushi2pdf
uv sync
```

也可以使用 pip 安装：

```bash
pip install .
```

## 使用方法

```
qiushi2pdf [-d 设备] [-o 输出路径] [-s] <url>
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
qiushi2pdf https://www.qstheory.cn/20260415/eb2be76d239d4fa4a0ef3a9a9d82b970/c.html
```

整期杂志（工具会自动识别目录页，下载全部文章并合并为一个 PDF）：

```bash
qiushi2pdf https://www.qstheory.cn/20260415/94280df5956349b0954c44d728bb75a1/c.html
```

指定设备和输出路径：

```bash
qiushi2pdf -d kindle -o my.pdf https://www.qstheory.cn/20260415/xxx/c.html
```

强制单篇模式（目录页 URL 也只取当前页内容）：

```bash
qiushi2pdf -s https://www.qstheory.cn/20260415/94280df5956349b0954c44d728bb75a1/c.html
```

## 输出

PDF 文件默认保存到当前目录下的 `output/` 文件夹，文件名由文章标题或期号自动生成。
