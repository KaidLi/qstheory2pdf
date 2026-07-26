"""Generate PDF from article content via LaTeX + xelatex.

This module is the presentation layer. It consumes Article/ContentBlock
TypedDicts (defined in types.py) and applies all LaTeX formatting
(escape, font wrapping, structural layout) here. The data layer
(crawler.py) does not know about LaTeX.
"""

import os
import re
import shutil
import subprocess
import tempfile

import qstheory2pdf
from qstheory2pdf.types import Article, ContentBlock, ImageBlock, TextBlock, TocEntry

# LaTeX special characters escaped by prefixing a backslash.
_LATEX_SPECIALS = ["&", "%", "#", "_", "$"]


def _escape_latex(text: str) -> str:
    """Escape all LaTeX special characters in untrusted text.

    Handles backslash and braces (which would otherwise let page content
    inject LaTeX commands or break compilation), and uses the text-symbol
    commands for ``~``/``^`` — a bare ``\\~``/``\\^`` is an accent command
    that would decorate the following character instead of printing.
    """
    text = text.replace("\\", "\x00")  # placeholder; restored last
    for ch in _LATEX_SPECIALS:
        text = text.replace(ch, "\\" + ch)
    text = text.replace("{", r"\{").replace("}", r"\}")
    text = text.replace("~", r"\textasciitilde{}")
    text = text.replace("^", r"\textasciicircum{}")
    text = text.replace("\x00", r"\textbackslash{}")
    return text


def format_text_to_latex(
    text: str,
    *,
    bold: bool = False,
    italic: bool = False,
    font_family: str = "",
) -> str:
    """Convert plain text + formatting flags to a LaTeX fragment.

    Steps:
      1. Escape LaTeX special characters (so user text doesn't break .tex).
      2. Add ``\\`` before spaces (so multi-word text stays together inside
         ``{ ... }`` groups like ``{\\heiti ...}``).
      3. Wrap in CJK font command per ``font_family`` flag.

    Note: ``bold`` / ``italic`` flags are *not* applied here at the text
    level. They drive *structural* formatting in ``_render_text_block``
    (e.g. paragraph-level bold becomes ``\\indent {\\heiti ...}`` plus
    optional centering), which is a block-level concern, not text-level.
    """
    text = _escape_latex(text)
    text = text.replace(" ", r"\ ")

    if font_family == "fang":
        text = r"{\fangsong " + text + r"}"
    elif font_family == "kai":
        text = r"{\kaishu " + text + r"}"
    elif font_family == "hei":
        text = r"{\heiti " + text + r"}"
    elif font_family == "song":
        text = r"{\songti " + text + r"}"

    return text


# Non-floating figures: keep images at their position in the reading flow
# (magazine layout), cap height so tall images never overflow small pages.
_FIGURE_TEMPLATE = r"""
\begin{center}
    \includegraphics[width=0.85\linewidth, height=0.72\textheight, keepaspectratio]{%s}
    \\[0.5em]
    {\kaishu\footnotesize %s}
\end{center}
""".strip()

_FIGURE_TEMPLATE_NOCAPTION = r"""
\begin{center}
    \includegraphics[width=0.85\linewidth, height=0.72\textheight, keepaspectratio]{%s}
\end{center}
""".strip()


class PDFGenerator:
    """Generate single-article or full-issue PDFs via LaTeX.

    Lifecycle:
        gen = PDFGenerator(device="scribe")
        image_dir = gen.start()        # creates tempdir, returns image_dir
        crawler = QiuShiCrawler(image_dir=image_dir)
        info = crawler.fetch_info(...)
        output = gen.gen_single(info, args.output)
        gen.finish()                   # removes tempdir (and all images)
    """

    def __init__(self, device: str = "normal", font: str = "auto") -> None:
        resource_path = os.path.join(
            os.path.dirname(qstheory2pdf.__file__), "resource"
        )
        self.template_path = os.path.join(resource_path, "template.tex")
        self.cls_path = os.path.join(resource_path, "qiushi.cls")
        self.device = device
        self.font = font  # "auto" (开源字体优先自动探测) | "wenkai" (全文楷)
        self.workdir: str | None = None
        self.image_dir: str | None = None

    @property
    def color_theme(self) -> str:
        """Color theme for the current device.

        E-ink screens dither color into muddy gray, so kindle/scribe get
        pure black; LCD/paper devices get the red "qiushi" accent theme.
        """
        return "black" if self.device in ("kindle", "scribe") else "qiushi"

    @property
    def class_options(self) -> str:
        """\\documentclass option list for qiushi.cls."""
        opts = f"{self.device}, {self.color_theme}"
        if self.font == "wenkai":
            opts += ", chinesefont=wenkai"
        return opts

    # ------------------------------------------------------------------ lifecycle

    def start(self) -> str:
        """Create a temp working directory with cls and image subdir.

        Returns the image directory path (workdir/img). The caller passes
        this to QiuShiCrawler so it can write article figures there. The
        directory is removed by ``finish()``.
        """
        self.workdir = tempfile.mkdtemp(prefix="qiushi_")
        self.image_dir = os.path.join(self.workdir, "img")
        os.makedirs(self.image_dir, exist_ok=True)
        shutil.copy(self.cls_path, os.path.join(self.workdir, "qiushi.cls"))
        return self.image_dir

    def finish(self) -> None:
        """Remove the temp working directory created by ``start()``."""
        if self.workdir and os.path.isdir(self.workdir):
            shutil.rmtree(self.workdir)
        self.workdir = None
        self.image_dir = None

    # ------------------------------------------------------------------ compile

    def _compile(self, basename: str, verbose: bool = True) -> None:
        """Run xelatex twice (for TOC/cross-refs)."""
        if self.workdir is None:
            raise RuntimeError("PDFGenerator.start() must be called before _compile()")
        cwd = self.workdir
        tex_file = basename + ".tex"

        # find xelatex — on Windows it may be outside bash PATH
        xelatex = self._find_xelatex()

        env = os.environ.copy()
        # ensure texlive bin dir is on PATH for subprocess
        tex_bin = os.path.dirname(xelatex)
        env["PATH"] = tex_bin + os.pathsep + env.get("PATH", "")

        for i in range(2):
            if verbose:
                print(f"  编译 PDF (第{i+1}遍)...", end=" ", flush=True)
            try:
                result = subprocess.run(
                    [xelatex, "-interaction=nonstopmode", tex_file],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=cwd,
                    env=env,
                    check=False,
                    timeout=300,
                )
            except subprocess.TimeoutExpired:
                raise RuntimeError(
                    f"xelatex timed out after 300s (run {i + 1}/2)"
                ) from None
            pdf_path = os.path.join(cwd, basename + ".pdf")
            if result.returncode != 0 and not os.path.exists(pdf_path):
                # Real error — PDF wasn't produced; print log for diagnostics
                log_path = os.path.join(cwd, basename + ".log")
                if os.path.exists(log_path):
                    print("\n--- xelatex 错误日志 (末尾) ---")
                    with open(log_path, "r", encoding="utf-8", errors="replace") as lf:
                        lines = lf.readlines()
                        for line in lines[-40:]:
                            print(line.rstrip())
                    print("--- 日志结束 ---")
                raise RuntimeError(
                    f"xelatex failed (exit {result.returncode}) and no PDF was generated"
                )
            if verbose:
                # count pages from output for user feedback
                out = result.stdout.decode("utf-8", errors="replace")
                pages = "?"
                for line in out.splitlines():
                    if "Output written on" in line:
                        m = re.search(r"\((\d+) pages?", line)
                        if m:
                            pages = m.group(1)
                        break
                print(f"完成 ({pages} 页)")

    @staticmethod
    def _find_xelatex() -> str:
        """Locate xelatex executable."""
        # try PATH first
        for name in ["xelatex", "xelatex.exe"]:
            found = shutil.which(name)
            if found:
                return found

        # search common TeX Live install locations on Windows
        for year in [2026, 2025, 2024]:
            p = f"C:/texlive/{year}/bin/windows/xelatex.exe"
            if os.path.exists(p):
                return p

        raise FileNotFoundError(
            "xelatex not found. Install TeX Live: https://tug.org/texlive/"
        )

    # --------------------------------------------------------------- single mode

    def gen_single(self, info: Article, output_path: str | None = None) -> str:
        """Generate a PDF for a single article.

        Assumes ``start()`` was called and the article's images have been
        written to ``self.image_dir``.

        Returns the path to the generated PDF.
        """
        if self.workdir is None or self.image_dir is None:
            raise RuntimeError("PDFGenerator.start() must be called before gen_single()")

        # read & fill template
        with open(self.template_path, "r", encoding="utf-8") as f:
            tex = f.read()
        tex = tex.replace("[normal, black]", f"[{self.class_options}]")

        for key in ["title", "author", "volume"]:
            tex = tex.replace(f"==xx({key})xx==", _escape_latex(info.get(key, "")))
        # QR code and images are stored under image_dir; xelatex runs in
        # workdir so the path is "img/<filename>".
        qr_rel = info.get("qrcode", "")
        qr_path = f"img/{qr_rel}" if qr_rel else ""
        tex = tex.replace("==xx(qrcode)xx==", qr_path)

        # build body
        body = self._build_body(info.get("content", []))
        tex = tex.replace("==xx(content)xx==", body)

        # write, compile, collect result
        basename = "output"
        tex_path = os.path.join(self.workdir, basename + ".tex")
        with open(tex_path, "w", encoding="utf-8") as f:
            f.write(tex)

        self._compile(basename)

        pdf_src = os.path.join(self.workdir, basename + ".pdf")
        if output_path is None:
            output_dir = os.path.join(os.getcwd(), "output")
            os.makedirs(output_dir, exist_ok=True)
            output_path = os.path.join(output_dir, _safe_name(info.get("title", "output")) + ".pdf")
        else:
            os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        shutil.copy(pdf_src, output_path)
        return output_path

    # --------------------------------------------------------------- issue mode

    def gen_issue(
        self,
        articles: list[Article],
        issue_volume: str,
        issue_date: str = "",
        toc_entries: list[TocEntry] | None = None,
        cover_image: str | None = None,
        output_path: str | None = None,
    ) -> str:
        """Generate a combined PDF for a full magazine issue.

        Assumes ``start()`` was called and all articles' images have been
        written to ``self.image_dir``. ``cover_image`` is a path relative
        to ``self.image_dir``.
        """
        if self.workdir is None:
            raise RuntimeError("PDFGenerator.start() must be called before gen_issue()")

        tex = self._build_issue_tex(
            articles, issue_volume, issue_date, toc_entries, cover_image
        )

        basename = "output"
        tex_path = os.path.join(self.workdir, basename + ".tex")
        with open(tex_path, "w", encoding="utf-8") as f:
            f.write(tex)

        self._compile(basename)

        pdf_src = os.path.join(self.workdir, basename + ".pdf")
        if output_path is None:
            output_dir = os.path.join(os.getcwd(), "output")
            os.makedirs(output_dir, exist_ok=True)
            safe_vol = _safe_name(issue_volume)
            output_path = os.path.join(output_dir, f"{safe_vol}.pdf")
        else:
            os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        shutil.copy(pdf_src, output_path)
        return output_path

    def _build_issue_tex(
        self,
        articles: list[Article],
        issue_volume: str,
        issue_date: str,
        toc_entries: list[TocEntry] | None = None,
        cover_image: str | None = None,
    ) -> str:
        """Build the complete LaTeX source for an issue document."""
        lines = []

        # preamble
        lines.append(rf"\documentclass[{self.class_options}]{{qiushi}}")
        # indentfirst/hyperref/caption and paragraph metrics are set by the
        # class; do not override them here or device-specific tuning is lost.
        lines.append(r"\hypersetup{colorlinks=true,linkcolor=black,urlcolor=black,bookmarks=true,bookmarksopen=true}")
        lines.append(r"\graphicspath{{./img/}}")
        lines.append("")

        lines.append(r"\begin{document}")
        lines.append(r"\renewcommand{\issuevolume}{" + _escape_latex(issue_volume) + r"}")

        # ---- title page ----
        if cover_image:
            # Pin the cover as a zero-size tikz overlay at the page center:
            # an in-flow \includegraphics at full page height overflows the
            # text area (topskip/lineskip) and gets pushed to the next page,
            # leaving a blank first page.
            lines.append(r"\begin{titlepage}")
            lines.append(
                r"\tikz[remember picture,overlay]"
                r"\node at (current page.center)"
                r" {\includegraphics[width=\paperwidth,height=\paperheight,keepaspectratio]{img/"
                + _escape_latex(cover_image)
                + r"}};"
            )
            lines.append(r"\end{titlepage}")
        else:
            # magazine-style masthead: oversized red 求是, double rule,
            # issue number and date in quiet kai
            lines.append(r"\begin{titlepage}")
            lines.append(r"\centering")
            lines.append(r"\vspace*{2.6cm}")
            lines.append(r"{\color{ecolor}\heiti\fontsize{64}{72}\selectfont 求\hspace{0.35em}是\par}")
            lines.append(r"\vspace{1.1cm}")
            lines.append(r"{\color{ecolor}\rule{0.55\textwidth}{0.16em}\par}")
            lines.append(r"\vspace{0.12cm}")
            lines.append(r"{\color{ecolor}\rule{0.55\textwidth}{0.05em}\par}")
            vol_display = _escape_latex(issue_volume.replace("《求是》", ""))
            lines.append(r"\vspace{1.2cm}")
            lines.append(r"{\LARGE\kaishu " + vol_display + r"\par}")
            if issue_date:
                lines.append(r"\vspace{0.7cm}")
                lines.append(r"{\large\kaishu\color{qsgray} " + _escape_latex(issue_date) + r"\par}")
            lines.append(r"\vfill")
            lines.append(r"{\footnotesize\kaishu\color{qsgray} 仅供内部人员学习参考\par}")
            lines.append(r"\vspace*{1.4cm}")
            lines.append(r"\end{titlepage}")
        lines.append("")

        # ---- TOC ----
        lines.append(r"\pagestyle{plain}")
        if toc_entries:
            lines.extend(self._build_manual_toc(toc_entries))
        else:
            lines.append(r"\renewcommand{\contentsname}{目\quad 录}")
            lines.append(r"\tableofcontents")
        lines.append(r"\newpage")
        lines.append("")

        # ---- articles ----
        # 栏目 lookup: TOC entries carry the column name; match by title.
        # Entries may be a subset of the articles — skip silently on miss.
        column_by_title = {
            e["title"]: e["column"]
            for e in (toc_entries or [])
            if e.get("column") and e.get("title")
        }
        for idx, art in enumerate(articles):
            title = art.get("title", "")
            subtitle = art.get("subtitle", "")
            author = art.get("author", "")
            content = art.get("content", [])
            column = column_by_title.get(title, "")

            lines.append(r"\clearpage")
            lines.append(r"\pagestyle{fancy-note}")

            # centered title block via class macros (qiushi.cls): 栏目 tag,
            # heiti headline, kai subtitle, fangsong byline, short red rule
            lines.append(r"\vspace*{0.8em}")
            safe_title = _escape_latex(title)
            if column:
                lines.append(r"\qscolumn{" + _escape_latex(column) + r"}")
                lines.append(r"\vspace{0.5em}")
            lines.append(r"\qstitle{" + safe_title + r"}")
            if subtitle:
                safe_sub = _escape_latex(subtitle)
                lines.append(r"\vspace{0.45em}")
                lines.append(r"\qssubtitle{" + safe_sub + r"}")
            lines.append(r"\vspace{0.8em}")
            lines.append(r"\qstitlerule")
            if author:
                lines.append(r"\vspace{0.8em}")
                lines.append(r"\qsauthor{" + _escape_latex(author) + r"}")
            lines.append(r"\vspace{1.1em}")
            lines.append(r"\phantomsection")
            lines.append(rf"\label{{art:{idx}}}")
            lines.append(rf"\pdfbookmark[0]{{{safe_title}}}{{art:{idx}}}")
            lines.append("")

            body = self._build_body(content)
            lines.append(body)
            lines.append("")

        lines.append(r"\end{document}")

        return "\n".join(lines)

    @staticmethod
    def _build_manual_toc(entries: list[TocEntry]) -> list[str]:
        """Build a manual TOC matching the original magazine design.

        Original design:
        - Title in bold, author in kaishu after /
        - Column name in kaishu before │
        - Subtitle in kaishu on second line after <br/>
        - Page numbers right-aligned with dot leaders
        """
        result = []
        # heading (rule + spacing from the class)
        result.append(r"\qstocheader")
        result.append("")

        last_column = None
        for idx, entry in enumerate(entries):
            title = _escape_latex(entry.get("title", ""))
            author = _escape_latex(entry.get("author", ""))
            column = _escape_latex(entry.get("column", ""))
            subtitle = _escape_latex(entry.get("subtitle", ""))
            author_role = _escape_latex(entry.get("author_role", ""))

            # group consecutive entries under a red column header instead of
            # repeating the column on every line
            if column and column != last_column:
                result.append(r"\qstoccolumn{" + column + r"}")
                result.append("")
            if column:
                last_column = column

            lines = []

            # Real-world TOC rows can be long (long titles + institutional
            # authors) and wrap. Standard LaTeX \@dottedtocline treatment:
            # hang continuation lines, reserve the page-number margin via
            # \rightskip, pull the number box back to the edge with a
            # negative \parfillskip, and forbid a break before the number —
            # so a wrapped row never strands its page number on its own line.
            hang = (r"\hangindent=2em\hangafter=1"
                    r"\rightskip=2.4em\parfillskip=-2.4em"
                    r"\noindent\hspace*{1em}")
            pagebox = (r"\nobreak\makebox[2.4em][r]{\color{qsgray}\pageref{art:"
                       + str(idx) + r"}}\par")

            if subtitle:
                # two-line entry: title row → subtitle /author row
                lines.append(
                    r"{" + hang
                    + r"{\bfseries " + title + r"}"
                    + r"\qstocdots" + pagebox + r"}"
                )
                sub_line = (r"\vspace{-0.25em}\noindent\hspace*{2em}"
                            r"{\small\kaishu\color{qsgray}" + subtitle + r"}")
                if author:
                    sub_line += r"{\small\kaishu\color{qsgray}~/~"
                    if author_role:
                        sub_line += author_role
                    sub_line += author + r"}"
                lines.append(sub_line + r"\par")
            else:
                # single-line entry
                line = r"{" + hang + r"{\bfseries " + title + r"}"
                if author:
                    line += r"{\small\kaishu\color{qsgray}~/~"
                    if author_role:
                        line += author_role
                    line += author + r"}"
                line += r"\qstocdots" + pagebox + r"}"
                lines.append(line)

            result.extend(lines)
            result.append(r"\vspace{0.7em}")
            result.append("")

        return result

    # --------------------------------------------------------------- body

    def _build_body(self, content: list[ContentBlock]) -> str:
        """Convert a list of content blocks into LaTeX body text.

        Chinese typography conventions:
        - Paragraph-level bold → ``\\heiti`` (``\\textbf`` does not affect CJK)
        - Italic → ``\\kaishu`` (Chinese convention for italic-equivalent)
        - Large centered bold → magazine section heading with ``\\heiti``
        """
        parts = []
        for block in content:
            if "img" in block:
                # Image block: caption gets full LaTeX escaping, image path is
                # relative to workdir ("img/<filename>").
                img_block = block  # type: ImageBlock
                caption = format_text_to_latex(img_block.get("caption", ""))
                if caption.strip():
                    fig = _FIGURE_TEMPLATE % (f"img/{img_block['img']}", caption)
                else:
                    fig = _FIGURE_TEMPLATE_NOCAPTION % f"img/{img_block['img']}"
                parts.append(fig)
            elif "text" in block:
                parts.append(self._render_text_block(block))  # type: ignore[arg-type]
        return "\n\n".join(parts)

    @staticmethod
    def _render_text_block(block: TextBlock) -> str:
        """Render a single text content block to a LaTeX paragraph."""
        text = format_text_to_latex(
            block["text"],
            font_family=block.get("font_family", ""),
        )

        bold = block.get("bold", False)
        italic = block.get("italic", False)
        center = block.get("center", False)
        large = block.get("large", False)
        right = block.get("right", False)
        font_size = block.get("font_size", 0)

        # magazine-style centered heading (spacing + theme color from cls)
        if large and bold and center:
            return r"\qsheading{" + text + r"}"

        # font size
        sz_cmd = PDFGenerator._size_cmd(font_size or (18 if large else 0))
        if sz_cmd:
            text = r"{" + sz_cmd + text + r"}"

        # structural
        if right:
            return r"\begin{flushright}" + text + r"\end{flushright}"
        if center and bold:
            return r"\begin{center}{\heiti " + text + r"}\end{center}"
        if center:
            return r"\begin{center}" + text + r"\end{center}"
        if bold:
            return r"\indent {\heiti " + text + r"}"
        if italic:
            return r"\indent {\kaishu " + text + r"}"
        return r"\indent " + text

    @staticmethod
    def _size_cmd(px: int) -> str:
        """Map font-size in px to a LaTeX size command."""
        if px <= 0:
            return ""
        if px >= 26:
            return r"\Huge "
        if px >= 20:
            return r"\LARGE "
        if px >= 16:
            return r"\large "
        return ""


def _safe_name(name: str) -> str:
    """Turn a string into a safe filename."""
    safe = name.strip().replace("\\", "").replace("/", "_")
    safe = re.sub(r"[^\w\u4e00-\u9fff\-_]", "_", safe)
    return safe.strip("_") or "output"
