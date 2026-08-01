"""Render domain reconstructions as PDF through XeLaTeX."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Mapping

import qstheory2pdf
from qstheory2pdf.domain import problem_summary, reconstruction_status
from qstheory2pdf.types import (
    Article,
    BodyElement,
    FigureBlock,
    InlineRun,
    Issue,
    IssueEntry,
    ParagraphBlock,
    ReconstructionStatus,
)

_LATEX_SPECIALS = ["&", "%", "#", "_", "$"]


def _escape_latex(text: str) -> str:
    text = text.replace("\\", "\x00")
    for character in _LATEX_SPECIALS:
        text = text.replace(character, "\\" + character)
    text = text.replace("{", r"\{").replace("}", r"\}")
    text = text.replace("~", r"\textasciitilde{}")
    text = text.replace("^", r"\textasciicircum{}")
    return text.replace("\x00", r"\textbackslash{}")


def format_text_to_latex(
    text: str,
    *,
    bold: bool = False,
    italic: bool = False,
    font_family: str = "",
) -> str:
    """Compatibility helper for plain text; semantic runs use `_render_runs`."""
    rendered = _escape_latex(text).replace(" ", r"\ ")
    if font_family == "fang":
        rendered = r"{\fangsong " + rendered + "}"
    elif font_family == "kai":
        rendered = r"{\kaishu " + rendered + "}"
    elif font_family == "hei":
        rendered = r"{\heiti " + rendered + "}"
    elif font_family == "song":
        rendered = r"{\songti " + rendered + "}"
    if italic:
        rendered = r"{\kaishu " + rendered + "}"
    if bold:
        rendered = r"{\heiti " + rendered + "}"
    return rendered


def _issue_label(issue: Issue) -> str:
    issue_id = issue.get("id", {})
    year = issue_id.get("publication_year", 0)
    number = issue_id.get("issue_number", 0)
    return f"《求是》{year}/{number:02d}" if year and number else "《求是》"


def _render_runs(runs: list[InlineRun]) -> str:
    parts: list[str] = []
    for run in runs:
        text = format_text_to_latex(run.get("text", ""))
        if run.get("emphasis"):
            text = r"{\kaishu " + text + "}"
        if run.get("strong"):
            text = r"{\heiti " + text + "}"
        href = run.get("href", "")
        if href:
            text = r"\href{" + _escape_latex(href) + "}{" + text + "}"
        parts.append(text)
    return "".join(parts)


class PDFGenerator:
    def __init__(self, device: str = "normal", font: str = "auto") -> None:
        resource_path = os.path.join(os.path.dirname(qstheory2pdf.__file__), "resource")
        self.cls_path = os.path.join(resource_path, "qiushi.cls")
        self.device = device
        self.font = font
        self.workdir: str | None = None
        self.image_dir: str | None = None

    @property
    def color_theme(self) -> str:
        return "black" if self.device in ("kindle", "scribe") else "qiushi"

    @property
    def class_options(self) -> str:
        options = f"{self.device}, {self.color_theme}"
        if self.font == "wenkai":
            options += ", chinesefont=wenkai"
        return options

    def start(self) -> str:
        self.workdir = tempfile.mkdtemp(prefix="qiushi_")
        self.image_dir = os.path.join(self.workdir, "img")
        os.makedirs(self.image_dir, exist_ok=True)
        shutil.copy(self.cls_path, os.path.join(self.workdir, "qiushi.cls"))
        return self.image_dir

    def finish(self) -> None:
        if self.workdir and os.path.isdir(self.workdir):
            shutil.rmtree(self.workdir)
        self.workdir = None
        self.image_dir = None

    @staticmethod
    def _find_xelatex() -> str:
        for name in ("xelatex", "xelatex.exe"):
            found = shutil.which(name)
            if found:
                return found
        for year in (2026, 2025, 2024):
            path = f"C:/texlive/{year}/bin/windows/xelatex.exe"
            if os.path.exists(path):
                return path
        raise FileNotFoundError("xelatex not found. Install TeX Live: https://tug.org/texlive/")

    def _compile(self, basename: str, verbose: bool = True) -> None:
        if self.workdir is None:
            raise RuntimeError("PDFGenerator.start() must be called before _compile()")
        executable = self._find_xelatex()
        environment = os.environ.copy()
        environment["PATH"] = os.path.dirname(executable) + os.pathsep + environment.get("PATH", "")
        for index in range(2):
            if verbose:
                print(f"  编译 PDF (第{index + 1}遍)...", end=" ", flush=True)
            try:
                result = subprocess.run(
                    [executable, "-interaction=nonstopmode", basename + ".tex"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=self.workdir,
                    env=environment,
                    check=False,
                    timeout=300,
                )
            except subprocess.TimeoutExpired:
                raise RuntimeError(f"xelatex timed out after 300s (run {index + 1}/2)") from None
            pdf_path = os.path.join(self.workdir, basename + ".pdf")
            if result.returncode != 0 and not os.path.exists(pdf_path):
                log_path = os.path.join(self.workdir, basename + ".log")
                if os.path.exists(log_path):
                    with open(log_path, encoding="utf-8", errors="replace") as stream:
                        print("\n--- xelatex 错误日志 (末尾) ---")
                        for line in stream.readlines()[-40:]:
                            print(line.rstrip())
                raise RuntimeError(f"xelatex failed (exit {result.returncode}) and no PDF was generated")
            if verbose:
                print("完成")

    def _write_and_compile(self, tex: str, output_path: str) -> str:
        if self.workdir is None:
            raise RuntimeError("PDFGenerator.start() must be called before generation")
        basename = "output"
        with open(os.path.join(self.workdir, basename + ".tex"), "w", encoding="utf-8") as stream:
            stream.write(tex)
        self._compile(basename)
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        shutil.copy(os.path.join(self.workdir, basename + ".pdf"), output_path)
        return output_path

    def gen_single(
        self,
        article: Article,
        output_path: str | None = None,
        status: ReconstructionStatus | None = None,
        *,
        allow_partial: bool = False,
    ) -> str:
        status = status or article.get("reconstruction") or reconstruction_status()
        if status["state"] == "partial" and not allow_partial:
            raise ValueError("部分文章重建必须显式设置 allow_partial=True")
        title = article.get("title", "") or article.get("source_id", "文章")
        tex = self._document_start(article.get("issue_label", ""))
        tex += self._partial_notice(status)
        tex += "\n" + r"\qstitle{" + _escape_latex(title) + "}\n"
        if article.get("subtitle"):
            tex += r"\qssubtitle{" + _escape_latex(article["subtitle"]) + "}\n"
        if article.get("byline"):
            tex += r"\qsauthor{" + _escape_latex(article["byline"]) + "}\n"
        tex += "\n" + self._build_body(article.get("body", []))
        qr = article.get("qrcode", "")
        if qr:
            tex += "\n" + r"\begin{center}\includegraphics[width=2cm]{img/" + _escape_latex(qr) + r"}\end{center}"
        tex += "\n" + r"\end{document}"
        if output_path is None:
            output_path = os.path.join(os.getcwd(), "output", _safe_name(title) + ("-partial" if status["state"] == "partial" else "") + ".pdf")
        return self._write_and_compile(tex, output_path)

    def gen_issue(
        self,
        issue: Issue,
        articles: Mapping[str, Article],
        *,
        cover_image: str | None = None,
        output_path: str | None = None,
        status: ReconstructionStatus | None = None,
        allow_partial: bool = False,
    ) -> str:
        status = status or issue.get("reconstruction") or reconstruction_status()
        if status["state"] == "partial" and not allow_partial:
            raise ValueError("部分期次重建必须显式设置 allow_partial=True")
        tex = self._build_issue_tex(issue, articles, status, cover_image=cover_image)
        label = _issue_label(issue)
        if output_path is None:
            output_path = os.path.join(os.getcwd(), "output", _safe_name(label) + ("-partial" if status["state"] == "partial" else "") + ".pdf")
        return self._write_and_compile(tex, output_path)

    def _document_start(self, issue_label: str) -> str:
        return "\n".join([
            rf"\documentclass[{self.class_options}]{{qiushi}}",
            r"\usepackage{multirow}",
            r"\hypersetup{colorlinks=true,linkcolor=black,urlcolor=black,bookmarks=true,bookmarksopen=true}",
            r"\graphicspath{{./img/}}",
            r"\begin{document}",
            r"\renewcommand{\issuevolume}{" + _escape_latex(issue_label) + "}",
        ])

    @staticmethod
    def _partial_notice(status: ReconstructionStatus) -> str:
        if status["state"] != "partial":
            return ""
        summary = _escape_latex(problem_summary(status))
        return "\n".join([
            r"\begin{center}",
            r"{\Huge\heiti\color{red} 部分重建}\par",
            r"\vspace{0.5em}{\kaishu " + summary + r"}\par",
            r"\end{center}\vspace{1em}",
        ])

    def _build_issue_tex(
        self,
        issue: Issue,
        articles: Mapping[str, Article],
        status: ReconstructionStatus,
        cover_image: str | None = None,
    ) -> str:
        label = _issue_label(issue)
        lines = [self._document_start(label)]
        if cover_image:
            lines.extend([
                r"\begin{titlepage}",
                r"\tikz[remember picture,overlay]\node at (current page.center) {\includegraphics[width=\paperwidth,height=\paperheight,keepaspectratio]{img/" + _escape_latex(cover_image) + "}};",
                r"\end{titlepage}",
            ])
        else:
            lines.extend([
                r"\begin{titlepage}\centering\vspace*{2.6cm}",
                r"{\color{ecolor}\heiti\fontsize{64}{72}\selectfont 求\hspace{0.35em}是\par}",
                r"\vspace{1.2cm}{\LARGE\kaishu " + _escape_latex(label.replace("《求是》", "")) + r"\par}",
            ])
            if issue.get("publication_date"):
                lines.append(r"\vspace{0.7cm}{\large\kaishu " + _escape_latex(issue["publication_date"]) + r"\par}")
            lines.append(r"\vfill\end{titlepage}")
        lines.append(self._partial_notice(status))

        chapter_units: list[tuple[str, IssueEntry]] = []
        index_by_id: dict[str, int] = {}
        page_by_ordinal: dict[int, int] = {}
        for entry in issue.get("entries", []):
            source_id = entry.get("source_article_id", "")
            ordinal = entry.get("ordinal", len(page_by_ordinal) + 1)
            if source_id in articles:
                if source_id not in index_by_id:
                    index_by_id[source_id] = len(chapter_units)
                    chapter_units.append((source_id, entry))
                page_by_ordinal[ordinal] = index_by_id[source_id]
            else:
                page_by_ordinal[ordinal] = len(chapter_units)
                chapter_units.append(("", entry))
        lines.extend(
            self._build_manual_toc(
                issue.get("entries", []),
                articles,
                page_by_ordinal,
            )
        )
        lines.append(r"\newpage")

        for chapter_index, (source_id, entry) in enumerate(chapter_units):
            article = articles.get(source_id)
            if article is None:
                title = entry.get("directory_title", "") or source_id or "未取得的入刊文章"
                lines.extend([
                    r"\clearpage",
                    r"\pagestyle{fancy-note}",
                    r"\qstitle{" + _escape_latex(title) + "}",
                    rf"\phantomsection\label{{art:{chapter_index}}}",
                    rf"\pdfbookmark[0]{{{_escape_latex(title)}}}{{art:{chapter_index}}}",
                    r"\begin{center}{\Huge\heiti\color{red} 部分重建}\par",
                    r"\vspace{0.8em}{\bfseries 此入刊条目的文章未能取得}\end{center}",
                ])
                continue
            title = article.get("title", "") or source_id
            lines.extend([
                r"\clearpage",
                r"\pagestyle{fancy-note}",
                r"\qstitle{" + _escape_latex(title) + "}",
            ])
            if article.get("subtitle"):
                lines.append(r"\qssubtitle{" + _escape_latex(article["subtitle"]) + "}")
            if article.get("byline"):
                lines.append(r"\qsauthor{" + _escape_latex(article["byline"]) + "}")
            lines.extend([
                rf"\phantomsection\label{{art:{chapter_index}}}",
                rf"\pdfbookmark[0]{{{_escape_latex(title)}}}{{art:{chapter_index}}}",
                self._build_body(article.get("body", [])),
            ])
        lines.append(r"\end{document}")
        return "\n".join(lines)

    @staticmethod
    def _build_manual_toc(
        entries: list[IssueEntry],
        articles: Mapping[str, Article],
        page_by_ordinal: Mapping[int, int],
    ) -> list[str]:
        result = [r"\qstocheader", ""]
        for entry in entries:
            source_id = entry.get("source_article_id", "")
            article = articles.get(source_id, {})
            directory_title = entry.get("directory_title", "")
            if directory_title:
                title = directory_title
            elif article.get("title"):
                title = article["title"] + "（文章页题）"
            else:
                title = "未取得的入刊文章" + (f"（{source_id}）" if source_id else "")
            section = entry.get("section_label", "")
            subtitle = entry.get("directory_subtitle", "")
            byline = entry.get("directory_byline", "")
            prefix = ""
            if section:
                prefix = r"{\small\kaishu\color{ecolor}" + _escape_latex(section) + r"}\hspace{0.5em}"
            text = prefix + r"{\bfseries " + _escape_latex(title) + "}"
            if byline:
                text += r"{\small\kaishu\color{qsgray}~/~" + _escape_latex(byline) + "}"
            ordinal = entry.get("ordinal", 0)
            if ordinal in page_by_ordinal:
                text += r"\qstocdots\nobreak\pageref{art:" + str(page_by_ordinal[ordinal]) + "}"
            if source_id not in articles:
                text += r"{\color{red}\bfseries\enspace[缺失]}"
            result.append(r"\noindent " + text + r"\par")
            if subtitle:
                result.append(
                    r"\noindent\hspace*{2em}{\small\kaishu\color{qsgray}"
                    + _escape_latex(subtitle)
                    + r"}\par"
                )
            result.append(r"\vspace{0.7em}")
        return result

    def _build_body(self, body: list[BodyElement]) -> str:
        return "\n\n".join(self._render_block(element) for element in body)

    def _render_block(self, element: BodyElement) -> str:
        kind = element.get("kind")
        if kind == "paragraph":
            return self._render_text_block(element)
        if kind == "figure":
            return self._render_figure(element)
        if kind == "list":
            environment = "enumerate" if element.get("ordered") else "itemize"
            items = "\n".join(r"\item " + _render_runs(item) for item in element.get("items", []))
            return rf"\begin{{{environment}}}" + "\n" + items + "\n" + rf"\end{{{environment}}}"
        if kind == "table":
            rows = element.get("rows", [])
            columns = max(
                (sum(cell.get("colspan", 1) for cell in row) for row in rows),
                default=1,
            )
            rendered_rows: list[str] = []
            for row in rows:
                rendered_cells: list[str] = []
                for cell in row:
                    text = _render_runs(cell.get("runs", []))
                    if cell.get("header"):
                        text = r"{\heiti " + text + "}"
                    rowspan = cell.get("rowspan", 1)
                    colspan = cell.get("colspan", 1)
                    if rowspan > 1:
                        text = rf"\multirow{{{rowspan}}}{{*}}{{{text}}}"
                    if colspan > 1:
                        text = rf"\multicolumn{{{colspan}}}{{|l|}}{{{text}}}"
                    rendered_cells.append(text)
                rendered_rows.append(" & ".join(rendered_cells) + r" \\")
            return r"\begin{center}\begin{tabular}{|" + "l|" * columns + r"}\hline " + r"\hline ".join(rendered_rows) + r"\hline\end{tabular}\end{center}"
        if kind == "quote":
            paragraphs = r"\par ".join(
                _render_runs(paragraph)
                for paragraph in element.get("paragraphs", [])
            )
            return r"\begin{quote}" + paragraphs + r"\end{quote}"
        return r"\begin{center}{\bfseries\color{red}[此处正文无法完整重建]}\end{center}"

    @staticmethod
    def _render_text_block(block: ParagraphBlock) -> str:
        text = _render_runs(block.get("runs", []))
        family = block.get("font_family", "")
        if family:
            text = "{" + "\\" + {"fang": "fangsong", "kai": "kaishu", "hei": "heiti", "song": "songti"}.get(family, "") + " " + text + "}"
        role = block.get("role", "body")
        if role == "section_heading":
            return r"\qsheading{" + text + "}"
        if role == "signature" or block.get("alignment") == "right":
            return r"\begin{flushright}" + text + r"\end{flushright}"
        if role == "salutation" or block.get("alignment") == "left":
            return r"\noindent " + text
        if block.get("alignment") == "center":
            return r"\begin{center}" + text + r"\end{center}"
        return r"\indent " + text

    @staticmethod
    def _render_figure(figure: FigureBlock) -> str:
        lines = [r"\begin{center}"]
        for image in figure.get("images", []):
            if image.get("missing") or not image.get("src"):
                alt = _escape_latex(image.get("alt", ""))
                lines.append(
                    r"{\bfseries\color{red}[正文图像未能取得"
                    + (r"：" + alt if alt else "")
                    + r"]}"
                )
            else:
                lines.append(r"\includegraphics[width=0.85\linewidth,height=0.72\textheight,keepaspectratio]{img/" + _escape_latex(image.get("src", "")) + "}")
            lines.append(r"\\[0.4em]")
        caption = _render_runs(figure.get("caption", []))
        if caption:
            lines.append(r"{\kaishu\footnotesize " + caption + "}")
        lines.append(r"\end{center}")
        return "\n".join(lines)


def _safe_name(name: str) -> str:
    safe = name.strip().replace("\\", "").replace("/", "_")
    safe = re.sub(r"[^\w\u4e00-\u9fff\-_]", "_", safe)
    return safe.strip("_") or "output"
