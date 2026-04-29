"""Generate PDF from article content via LaTeX + xelatex."""

import os
import re
import shutil
import subprocess
import tempfile

import qstheory2pdf


def _escape_latex(text: str) -> str:
    """Escape special LaTeX characters in text."""
    for ch in ["&", "%", "#", "_", "$", "~", "^"]:
        text = text.replace(ch, "\\" + ch)
    return text


_FIGURE_TEMPLATE = r"""
\begin{figure}[htbp]
    \centering
    \includegraphics[width=0.75\linewidth]{%s}
    \vspace{0.3em}\par
    {\kaishu\centering %s}
\end{figure}
""".strip()


class PDFGenerator:
    """Generate single-article or full-issue PDFs via LaTeX."""

    def __init__(self, device: str = "normal") -> None:
        resource_path = os.path.join(
            os.path.dirname(qstheory2pdf.__file__), "resource"
        )
        self.template_path = os.path.join(resource_path, "template.tex")
        self.cls_path = os.path.join(resource_path, "qiushi.cls")
        self.device = device
        self.tmpdir = None

    # ------------------------------------------------------------------ helpers

    def _setup_workdir(self) -> str:
        """Create a temp working dir, copy cls into it, return its path."""
        self.tmpdir = tempfile.mkdtemp(prefix="qiushi_")
        shutil.copy(self.cls_path, os.path.join(self.tmpdir, "qiushi.cls"))
        # also copy img dir if it exists
        img_src = os.path.join(os.getcwd(), "img")
        if os.path.isdir(img_src):
            img_dst = os.path.join(self.tmpdir, "img")
            if os.path.exists(img_dst):
                shutil.rmtree(img_dst)
            shutil.copytree(img_src, img_dst)
        return self.tmpdir

    def _compile(self, basename: str, verbose: bool = True) -> None:
        """Run xelatex twice (for TOC/cross-refs)."""
        cwd = self.tmpdir or os.getcwd()
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
            result = subprocess.run(
                [xelatex, "-interaction=nonstopmode", tex_file],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd,
                env=env,
                check=False,
            )
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

    def _cleanup(self) -> None:
        """Remove the temporary working directory."""
        if self.tmpdir and os.path.isdir(self.tmpdir):
            shutil.rmtree(self.tmpdir)

    # -------------------------------------------------------------- single mode

    def gen_single(self, info: dict, output_path: str | None = None) -> str:
        """Generate a PDF for a single article.

        Args:
            info: dict from QiuShiCrawler.fetch_info().
            output_path: Optional output PDF path. Defaults to
                         <title>.pdf in the current directory.

        Returns:
            Path to the generated PDF.
        """
        work = self._setup_workdir()

        # read & fill template
        with open(self.template_path, "r", encoding="utf-8") as f:
            tex = f.read()
        tex = tex.replace("[normal, black]", f"[{self.device}, black]")

        for key in ["title", "author", "volume"]:
            tex = tex.replace(f"==xx({key})xx==", info.get(key, ""))
        tex = tex.replace("==xx(qrcode)xx==", info.get("qrcode", "").replace("\\", "/"))

        # build body
        body = self._build_body(info["content"])
        tex = tex.replace("==xx(content)xx==", body)

        # write, compile, collect result
        basename = "output"
        tex_path = os.path.join(work, basename + ".tex")
        with open(tex_path, "w", encoding="utf-8") as f:
            f.write(tex)

        self._compile(basename)

        pdf_src = os.path.join(work, basename + ".pdf")
        if output_path is None:
            output_dir = os.path.join(os.getcwd(), "output")
            os.makedirs(output_dir, exist_ok=True)
            output_path = os.path.join(output_dir, _safe_name(info["title"]) + ".pdf")
        shutil.copy(pdf_src, output_path)
        self._cleanup()
        return output_path

    # --------------------------------------------------------------- issue mode

    def gen_issue(
        self,
        articles: list[dict],
        issue_volume: str,
        issue_date: str = "",
        toc_entries: list[dict] | None = None,
        cover_image: str | None = None,
        output_path: str | None = None,
    ) -> str:
        """Generate a combined PDF for a full magazine issue.

        Args:
            articles: List of dicts from QiuShiCrawler.fetch_info().
            issue_volume: e.g. "《求是》2026/08".
            issue_date: e.g. "2026-04-16".
            toc_entries: Optional list from fetch_toc_entries() for a
                         rich manual TOC. Falls back to auto-generated.
            cover_image: Optional path to a cover image for title page.
            output_path: Optional output PDF path.

        Returns:
            Path to the generated PDF.
        """
        work = self._setup_workdir()
        tex = self._build_issue_tex(
            articles, issue_volume, issue_date, toc_entries, cover_image
        )

        basename = "output"
        tex_path = os.path.join(work, basename + ".tex")
        with open(tex_path, "w", encoding="utf-8") as f:
            f.write(tex)

        self._compile(basename)

        pdf_src = os.path.join(work, basename + ".pdf")
        if output_path is None:
            output_dir = os.path.join(os.getcwd(), "output")
            os.makedirs(output_dir, exist_ok=True)
            safe_vol = _safe_name(issue_volume)
            output_path = os.path.join(output_dir, f"{safe_vol}.pdf")
        shutil.copy(pdf_src, output_path)
        self._cleanup()
        return output_path

    def _build_issue_tex(
        self,
        articles: list[dict],
        issue_volume: str,
        issue_date: str,
        toc_entries: list[dict] | None = None,
        cover_image: str | None = None,
    ) -> str:
        """Build the complete LaTeX source for an issue document."""
        lines = []

        # preamble
        lines.append(rf"\documentclass[{self.device}, black]{{qiushi}}")
        lines.append(r"\usepackage{indentfirst}")
        lines.append(r"\usepackage{hyperref}")
        lines.append(r"\hypersetup{colorlinks=true,linkcolor=black,urlcolor=black,bookmarks=true,bookmarksopen=true}")
        lines.append(r"\usepackage{caption}")
        lines.append(r"\graphicspath{{./img/}}")
        lines.append(r"\setlength{\parskip}{3mm}")
        lines.append(r"\setlength{\parindent}{2em}")
        lines.append(r"\linespread{1.3}")
        lines.append("")

        lines.append(r"\begin{document}")
        lines.append(r"\renewcommand{\issuevolume}{" + _escape_latex(issue_volume) + r"}")

        # ---- title page ----
        if cover_image:
            lines.append(r"\newgeometry{margin=0mm}")
            lines.append(r"\begin{titlepage}")
            lines.append(r"\centering")
            lines.append(r"\noindent")
            lines.append(r"\includegraphics[width=\paperwidth,height=\paperheight,keepaspectratio]{" + _escape_latex(cover_image) + r"}")
            lines.append(r"\end{titlepage}")
            lines.append(r"\restoregeometry")
        else:
            lines.append(r"\begin{titlepage}")
            lines.append(r"\centering")
            lines.append(r"\vspace*{3cm}")
            lines.append(r"{\Huge\bfseries 《求是》杂志\par}")
            lines.append(r"\vspace{0.8cm}")
            vol_display = _escape_latex(issue_volume.replace("《求是》", ""))
            lines.append(r"{\LARGE " + vol_display + r"\par}")
            if issue_date:
                lines.append(r"\vspace{1.5cm}")
                lines.append(r"{\large " + _escape_latex(issue_date) + r"\par}")
            lines.append(r"\vfill")
            lines.append(r"{\footnotesize 仅供内部人员学习参考\par}")
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
        for idx, art in enumerate(articles):
            title = art.get("title", "")
            subtitle = art.get("subtitle", "")
            author = art.get("author", "")
            volume = art.get("volume", "")
            content = art.get("content", [])

            lines.append(r"\clearpage")
            lines.append(r"\pagestyle{fancy-note}")

            # centered title block
            lines.append(r"\begin{center}")
            safe_title = _escape_latex(title)
            lines.append(r"{\LARGE\bfseries " + safe_title + r"\par}")
            if subtitle:
                safe_sub = _escape_latex(subtitle)
                lines.append(r"{\kaishu " + safe_sub + r"\par}")
            if author:
                lines.append(r"\vspace{0.5em}")
                lines.append(r"{\kaishu " + _escape_latex(author) + r"\par}")
            if volume:
                lines.append(r"{\small " + _escape_latex(volume) + r"\par}")
            lines.append(r"\end{center}")
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
    def _build_manual_toc(entries: list[dict]) -> list[str]:
        """Build a manual TOC matching the original magazine design.

        Original design:
        - Title in bold, author in kaishu after /
        - Column name in kaishu before │
        - Subtitle in kaishu on second line after <br/>
        - Page numbers right-aligned with dot leaders
        """
        result = []
        # heading
        result.append(r"\begin{center}")
        result.append(r"{\LARGE\bfseries 目\quad 录}")
        result.append(r"\end{center}")
        result.append(r"\vspace{1em}")
        result.append("")

        for idx, entry in enumerate(entries):
            title = _escape_latex(entry.get("title", ""))
            author = _escape_latex(entry.get("author", ""))
            column = _escape_latex(entry.get("column", ""))
            subtitle = _escape_latex(entry.get("subtitle", ""))
            author_role = _escape_latex(entry.get("author_role", ""))

            lines = []

            # build the entry line: [Column│]Title[ Subtitle]
            prefix = ""
            if column:
                prefix = r"{\kaishu " + column + r"}│"

            if subtitle:
                # two-line entry: column│title → newline → subtitle /author
                lines.append(
                    r"\indent " + prefix
                    + r"{\bfseries " + title + r"}"
                    + r"\hfill\pageref{art:" + str(idx) + r"}"
                    r"\\[0.1em]"
                )
                sub_line = r"\hspace*{3em}{\kaishu " + subtitle + r"}"
                if author:
                    sub_line += " /"
                    if author_role:
                        sub_line += r"{\kaishu " + author_role + r"}"
                    sub_line += r"{\kaishu " + author + r"}"
                lines.append(sub_line)
            else:
                # single-line entry
                line = r"\indent " + prefix + r"{\bfseries " + title + r"}"
                if author:
                    line += " /"
                    if author_role:
                        line += r"{\kaishu " + author_role + r"}"
                    line += r"{\kaishu " + author + r"}"
                line += r"\dotfill\pageref{art:" + str(idx) + r"}"
                lines.append(line)

            result.extend(lines)
            result.append(r"\\[0.8em]")
            result.append("")

        return result

    # ---------------------------------------------------------------- body gen

    @staticmethod
    def _size_cmd(px: int | None) -> str:
        """Map font-size in px to a LaTeX size command."""
        if px is None:
            return ""
        if px >= 26:
            return r"\Huge "
        if px >= 20:
            return r"\LARGE "
        if px >= 16:
            return r"\large "
        return ""

    @staticmethod
    def _font_cmd(family: str) -> str:
        """Map font-family string to a LaTeX CJK font command."""
        if family == "kai":
            return r"\kaishu "
        if family == "hei":
            return r"\heiti "
        if family == "fang":
            return r"\fangsong "
        return ""

    def _build_body(self, content: list[dict]) -> str:
        """Convert a list of content blocks into LaTeX body text.

        Chinese typography conventions:
        - Paragraph-level bold → \\heiti (\\textbf does not affect CJK)
        - Emphasis → \\kaishu (Chinese convention for italic-equivalent)
        - Large centered bold → magazine section heading with \\heiti
        """
        parts = []
        for block in content:
            if "img" in block:
                fig = _FIGURE_TEMPLATE % (
                    _escape_latex(block["img"]),
                    _escape_latex(block.get("caption", "")),
                )
                parts.append(fig)
            elif "text" in block:
                text = _escape_latex(block["text"])
                bold = block.get("bold", False)
                center = block.get("center", False)
                large = block.get("large", False)
                right = block.get("right", False)
                font_family = block.get("font_family", "")
                font_size = block.get("font_size", None)
                em = block.get("em", False)

                # --- magazine-style centered heading ---
                if large and bold and center:
                    text = r"{\heiti\Large " + text + r"}"
                    parts.append(r"\begin{center}" + text + r"\end{center}")
                    continue

                # --- font family (CJK) ---
                fm_cmd = self._font_cmd(font_family)
                if fm_cmd:
                    text = r"{" + fm_cmd + text + r"}"

                # --- font size ---
                sz_cmd = self._size_cmd(font_size or (18 if large else None))
                if sz_cmd:
                    text = r"{" + sz_cmd + text + r"}"

                # --- structural formatting ---
                if right:
                    text = r"\begin{flushright}" + text + r"\end{flushright}"
                elif center and bold:
                    # centered bold heading → heiti
                    text = r"{\heiti " + text + r"}"
                    text = r"\begin{center}" + text + r"\end{center}"
                elif center:
                    text = r"\begin{center}" + text + r"\end{center}"
                elif bold:
                    # paragraph-level bold → heiti (CJK convention)
                    text = r"\indent {\heiti " + text + r"}"
                elif em:
                    # emphasis → kaishu (Chinese italic convention)
                    text = r"\indent {\kaishu " + text + r"}"
                else:
                    text = r"\indent " + text

                parts.append(text)

        return "\n\n".join(parts)


def _safe_name(name: str) -> str:
    """Turn a string into a safe filename."""
    safe = name.strip().replace("\\", "").replace("/", "_")
    safe = re.sub(r"[^\w\u4e00-\u9fff\-_]", "_", safe)
    return safe.strip("_") or "output"
