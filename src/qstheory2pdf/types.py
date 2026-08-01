"""Domain contracts for reconstructing QiuShi publications.

The types in this module mirror the ubiquitous language in ``CONTEXT.md``.
They are deliberately JSON-friendly so reconstruction status can be emitted by
both the CLI and CI without a second representation.
"""

from __future__ import annotations

from typing import List, Literal, TypedDict, Union

SourceArticleId = str
SourceDocumentKind = Literal["article", "issue_contents", "issue_catalog"]
ReconstructionState = Literal["complete", "partial"]
TextRole = Literal["body", "section_heading", "salutation", "signature"]
Alignment = Literal["default", "left", "center", "right"]


class _ReconstructionProblemRequired(TypedDict):
    code: str
    message: str


class ReconstructionProblem(_ReconstructionProblemRequired, total=False):
    location: str


class ReconstructionStatus(TypedDict):
    state: ReconstructionState
    problems: List[ReconstructionProblem]


class _InlineRunRequired(TypedDict):
    text: str


class InlineRun(_InlineRunRequired, total=False):
    """A contiguous piece of text with semantic inline annotations."""

    strong: bool
    emphasis: bool
    href: str


class ParagraphBlock(TypedDict):
    kind: Literal["paragraph"]
    role: TextRole
    runs: List[InlineRun]
    alignment: Alignment
    font_family: str
    font_size: int


class ListBlock(TypedDict):
    kind: Literal["list"]
    ordered: bool
    items: List[List[InlineRun]]


class TableCell(TypedDict):
    runs: List[InlineRun]
    header: bool
    rowspan: int
    colspan: int


class TableBlock(TypedDict):
    kind: Literal["table"]
    rows: List[List[TableCell]]


class QuoteBlock(TypedDict):
    kind: Literal["quote"]
    paragraphs: List[List[InlineRun]]


class _FigureImageRequired(TypedDict):
    src: str
    alt: str


class FigureImage(_FigureImageRequired, total=False):
    source_url: str
    missing: bool


class FigureBlock(TypedDict):
    kind: Literal["figure"]
    images: List[FigureImage]
    caption: List[InlineRun]


class UnsupportedBlock(TypedDict):
    kind: Literal["unsupported"]
    source_tag: str
    reason: str


BodyElement = Union[
    ParagraphBlock,
    ListBlock,
    TableBlock,
    QuoteBlock,
    FigureBlock,
    UnsupportedBlock,
]


class _ArticleRequired(TypedDict):
    source_id: SourceArticleId
    source_url: str
    title: str
    body: List[BodyElement]
    reconstruction: ReconstructionStatus


class Article(_ArticleRequired, total=False):
    subtitle: str
    byline: str
    issue_label: str
    source_publication_date: str
    qrcode: str


class IssueId(TypedDict):
    publication_year: int
    issue_number: int


class _IssueEntryRequired(TypedDict):
    ordinal: int
    source_article_id: SourceArticleId


class IssueEntry(_IssueEntryRequired, total=False):
    source_url: str
    directory_title: str
    directory_subtitle: str
    directory_byline: str
    section_label: str


class _IssueRequired(TypedDict):
    id: IssueId
    source_url: str
    entries: List[IssueEntry]
    reconstruction: ReconstructionStatus


class Issue(_IssueRequired, total=False):
    publication_date: str


class CatalogIssue(TypedDict):
    id: IssueId
    source_url: str


class _IssueCatalogRequired(TypedDict):
    source_url: str
    issues: List[CatalogIssue]


class IssueCatalog(_IssueCatalogRequired, total=False):
    publication_year: int


class ArticleDocument(TypedDict):
    kind: Literal["article"]
    article: Article


class IssueContentsDocument(TypedDict):
    kind: Literal["issue_contents"]
    issue: Issue


class IssueCatalogDocument(TypedDict):
    kind: Literal["issue_catalog"]
    catalog: IssueCatalog


SourceDocument = Union[ArticleDocument, IssueContentsDocument, IssueCatalogDocument]
