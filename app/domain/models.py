from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class ProcessingMode(str, Enum):
    QUICK = "quick"
    FULL = "full"


class BrandVertical(str, Enum):
    SPORTS = "sports"
    EVENTS = "events"
    CORP = "corp"
    TECHNICAL = "technical"


class JobStatus(str, Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    MEMVID = "memvid"
    WATCHING = "watching"
    STRATEGIZING = "strategizing"
    WRITING = "writing"
    EDITING = "editing"
    MAPPING = "mapping"
    DONE = "done"
    FAILED = "failed"


class WorkflowStatus(str, Enum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    PUBLISHED = "published"


class ClaimSource(str, Enum):
    TRANSCRIPT = "transcript"
    VISUAL = "visual"


class RegeneratePart(str, Enum):
    TWEETS = "tweets"
    GRAPH = "graph"
    BLOG = "blog"


STAGE_PROGRESS: dict[JobStatus, int] = {
    JobStatus.QUEUED: 5,
    JobStatus.DOWNLOADING: 15,
    JobStatus.MEMVID: 30,
    JobStatus.WATCHING: 45,
    JobStatus.STRATEGIZING: 55,
    JobStatus.WRITING: 65,
    JobStatus.EDITING: 75,
    JobStatus.MAPPING: 90,
    JobStatus.DONE: 100,
    JobStatus.FAILED: 0,
}


class Claim(BaseModel):
    text: str
    start_sec: float | None = None
    end_sec: float | None = None
    source: ClaimSource = ClaimSource.TRANSCRIPT
    youtube_url: str | None = None


class WatcherOutput(BaseModel):
    summary: str
    claims: list[Claim] = Field(default_factory=list)


class StrategistOutput(BaseModel):
    angle: str
    target_audience: str
    thread_hook: str
    omit_topics: list[str] = Field(default_factory=list)


class EditorViolation(BaseModel):
    rule: str
    message: str
    location: str | None = None


class EditorReport(BaseModel):
    passed: bool
    violations: list[EditorViolation] = Field(default_factory=list)


class JobCreate(BaseModel):
    youtube_url: str
    mode: ProcessingMode = ProcessingMode.QUICK
    quick_minutes: int | None = None
    secret: str | None = None
    webhook_url: str | None = None
    vertical: BrandVertical = BrandVertical.EVENTS


class JobRecord(BaseModel):
    id: str
    status: JobStatus
    stage: JobStatus
    progress_pct: int = 0
    progress_message: str | None = None
    mode: ProcessingMode
    youtube_url: str
    quick_minutes: int | None = None
    error: str | None = None
    result_url: str | None = None
    webhook_url: str | None = None
    vertical: BrandVertical = BrandVertical.EVENTS
    guest_session_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_poll_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status.value,
            "stage": self.stage.value,
            "progress_pct": self.progress_pct,
            "mode": self.mode.value,
            "youtube_url": self.youtube_url,
            "vertical": self.vertical.value,
            "error": self.error,
            "result_url": self.result_url,
        }


class WriterOutput(BaseModel):
    blog_post: str
    tweets: list[str]
    claim_refs: list[int] | None = None


class GraphNode(BaseModel):
    id: str
    label: str
    group: str = "entity"


class GraphEdge(BaseModel):
    source: str
    target: str
    label: str = "related_to"


class GraphData(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class PressKitResult(BaseModel):
    id: str
    youtube_url: str
    mode: ProcessingMode
    title: str
    blog_post: str
    tweets: list[str]
    graph: GraphData
    watcher_summary: str
    claims: list[Claim] = Field(default_factory=list)
    workflow_status: WorkflowStatus = WorkflowStatus.DRAFT
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Manifest(BaseModel):
    id: str
    youtube_url: str
    mode: str
    title: str
    created_at: str
    status: str = "done"
    workflow_status: str = WorkflowStatus.DRAFT.value
    pipeline_mock: bool = False
    llm_mock: bool = False
    ingest_duration_sec: float | None = None
    gemini_model: str | None = None
    graph_source: Literal["graphify", "heuristic", "stub"] | None = None
    vertical: str | None = None


class JobCreateV1(BaseModel):
    youtube_url: str
    mode: ProcessingMode = ProcessingMode.QUICK
    quick_minutes: int | None = None
    webhook_url: str | None = None
    secret: str | None = None
    vertical: BrandVertical = BrandVertical.EVENTS


class JobCreateResponse(BaseModel):
    id: str
    status: str
    poll_url: str
    session_token: str | None = None
