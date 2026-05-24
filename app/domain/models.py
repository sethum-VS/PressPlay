from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, HttpUrl


class ProcessingMode(str, Enum):
    QUICK = "quick"
    FULL = "full"


class JobStatus(str, Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    MEMVID = "memvid"
    WATCHING = "watching"
    WRITING = "writing"
    MAPPING = "mapping"
    DONE = "done"
    FAILED = "failed"


STAGE_PROGRESS: dict[JobStatus, int] = {
    JobStatus.QUEUED: 5,
    JobStatus.DOWNLOADING: 15,
    JobStatus.MEMVID: 30,
    JobStatus.WATCHING: 50,
    JobStatus.WRITING: 70,
    JobStatus.MAPPING: 85,
    JobStatus.DONE: 100,
    JobStatus.FAILED: 0,
}


class JobCreate(BaseModel):
    youtube_url: str
    mode: ProcessingMode = ProcessingMode.QUICK
    quick_minutes: int | None = None
    secret: str | None = None


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
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_poll_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status.value,
            "stage": self.stage.value,
            "progress_pct": self.progress_pct,
            "mode": self.mode.value,
            "youtube_url": self.youtube_url,
            "error": self.error,
            "result_url": self.result_url,
        }


class WriterOutput(BaseModel):
    blog_post: str
    tweets: list[str]


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
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Manifest(BaseModel):
    id: str
    youtube_url: str
    mode: str
    title: str
    created_at: str
    status: str = "done"
    pipeline_mock: bool = False
    llm_mock: bool = False
