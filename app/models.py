"""Typed records shared by PDF analysis, persistence, workers, and HTTP handlers.

TypedDict preserves the existing JSON representation. Pydantic adapters validate
records when they cross JSON or SQLite seams instead of trusting json.loads.
"""
from collections.abc import Callable
from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from typing_extensions import NotRequired, TypedDict

RenderMode: TypeAlias = Literal["original", "all-on", "all-off", "solo", "selected"]
JobState: TypeAlias = Literal["queued", "running", "succeeded", "failed", "interrupted", "cancelled"]
JobKind: TypeAlias = Literal["analysis", "render"]
Category: TypeAlias = Literal["paths", "text_shows", "images", "shadings"]
ObjectReference: TypeAlias = tuple[int, int]
ProgressCallback: TypeAlias = Callable[[str, int, int], None]


class Limits(TypedDict):
    upload_bytes: int
    pages: int
    queue: int
    pixels: int
    analysis_seconds: int
    render_seconds: int
    memory_bytes: int
    depth: int
    stream_bytes: int
    decoded_bytes: int
    cache_bytes: int


class ContentCounts(TypedDict):
    paths: int
    text_shows: int
    images: int
    shadings: int


class AnalysisSettings(TypedDict):
    visibility_dpi: int
    background: str
    colorspace: str
    annotations: bool
    depth: int
    stream_bytes: int
    decoded_bytes: int


class Engines(TypedDict):
    pypdf: str
    pymupdf: str


class AnalysisProfile(TypedDict):
    schema_version: str
    analyzer_version: str
    engines: Engines
    settings: AnalysisSettings


class PdfObjectReference(TypedDict):
    number: int
    generation: int


class VisibleOutput(TypedDict):
    width: int
    height: int
    nonwhite_pixels: int


class PageLayer(TypedDict):
    page: int
    counts: ContentCounts
    bounds: None
    visible_output: VisibleOutput | None
    source_empty: bool | None
    complete: bool


class Layer(TypedDict):
    id: str
    name: str
    object_reference: PdfObjectReference
    source_order: int
    default_visible: bool
    referenced_pages: list[int]
    content_pages: list[int]
    counts: ContentCounts
    complete: bool
    warnings: list[str]
    page_details: list[PageLayer]
    text_samples: list[str]
    source_empty: bool | None
    source_operations: int
    explanation: str


class PageFacts(TypedDict):
    page: int
    label: str
    rotation: int
    media_box: list[float]
    crop_box: list[float]
    width: float
    height: float
    layers: list[str]
    annotations: dict[str, int]
    layer_annotations: int
    shx_annotation_count: int


class BaseContent(TypedDict):
    page: int
    counts: ContentCounts


class ExpressionReference(TypedDict):
    object: int
    generation: int


type ConditionalExpression = str | ExpressionReference | list[ConditionalExpression]


class SourceCondition(TypedDict):
    kind: Literal["unknown", "ocg", "conditional"]
    members: list[ObjectReference]
    expression: NotRequired[ConditionalExpression]


class ManifestCondition(TypedDict):
    kind: Literal["unknown", "ocg", "conditional"]
    members: list[str]
    expression: NotRequired[ConditionalExpression]


class ConditionalOperation(TypedDict):
    category: Category
    conditions: list[ManifestCondition]


class ConditionalContent(TypedDict):
    page: int
    operations: list[ConditionalOperation]


class DocumentFacts(TypedDict):
    bytes: int
    pdf_version: str
    page_count: int
    has_layers: bool
    encrypted: bool
    annotation_count: int
    shx_annotation_count: int


class Capabilities(TypedDict):
    strict_solo: bool
    base_content_present: bool
    custom_visibility: bool
    modes: list[RenderMode]


class AnalysisBody(AnalysisProfile):
    source_sha256: str
    measurement: str
    document: DocumentFacts
    pages: list[PageFacts]
    layers: list[Layer]
    base_content: list[BaseContent]
    conditional_content: list[ConditionalContent]
    capabilities: Capabilities
    warnings: list[str]


class AnalysisManifest(AnalysisBody):
    analysis_identity: str


class NormalizedRender(TypedDict):
    page: int
    mode: RenderMode
    xrefs: list[int]
    scale: float
    annotations: bool


class AnalysisJob(TypedDict):
    document: str
    kind: Literal["analysis"]
    source: str
    request: None


class RenderJob(TypedDict):
    document: str
    kind: Literal["render"]
    source: str
    request: NormalizedRender


WorkerJob: TypeAlias = Annotated[AnalysisJob | RenderJob, Field(discriminator="kind")]


class JobError(TypedDict):
    code: str
    message: str


class Progress(TypedDict):
    stage: str
    completed: int
    total: int


class DocumentRecord(TypedDict):
    id: str
    generation: str
    filename: str
    size: int


class JobRecord(TypedDict):
    id: str
    document: str
    generation: str
    kind: JobKind
    state: JobState
    payload: str
    error: str | None
    sequence: int


class DocumentStatus(DocumentRecord, Progress):
    state: JobState
    error: JobError | None
    retry_action: Literal["POST analysis"] | None


class UploadResult(TypedDict):
    id: str
    state: Literal["queued", "succeeded"]
    job_id: str | None


class AnalysisReady(TypedDict):
    id: str
    state: Literal["succeeded"]


class RenderResult(TypedDict):
    key: str
    url: str
    state: Literal["queued", "succeeded"]
    request: NormalizedRender


class HealthResult(TypedDict):
    status: Literal["ok"]
    limits: Limits


manifest_adapter: TypeAdapter[AnalysisManifest] = TypeAdapter(AnalysisManifest)
worker_job_adapter: TypeAdapter[WorkerJob] = TypeAdapter(WorkerJob)
error_adapter: TypeAdapter[JobError] = TypeAdapter(JobError)
progress_adapter: TypeAdapter[Progress] = TypeAdapter(Progress)
document_adapter: TypeAdapter[DocumentRecord] = TypeAdapter(DocumentRecord)
job_adapter: TypeAdapter[JobRecord] = TypeAdapter(JobRecord)


class AnalysisQueued(TypedDict):
    job_id: str
    state: Literal["queued"]


class RenderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page: int = Field(ge=1)
    mode: RenderMode = "original"
    layers: list[str] = Field(default_factory=list, max_length=10000)
    scale: float = Field(default=1.0, ge=0.1, le=4, allow_inf_nan=False)
    annotations: bool = False
    uncached: bool = False
