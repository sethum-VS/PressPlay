import json
from pathlib import Path

from app.config import Settings, get_settings
from app.domain.errors import ResultsNotFoundError
from app.domain.models import (
    Claim,
    EditorReport,
    GraphData,
    Manifest,
    PressKitResult,
    StrategistOutput,
    WorkflowStatus,
)


class ResultsRepository:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.base = self.settings.results_path
        self.base.mkdir(parents=True, exist_ok=True)

    def _job_dir(self, job_id: str) -> Path:
        return self.base / job_id

    def save(
        self,
        result: PressKitResult,
        *,
        pipeline_mock: bool = False,
        llm_mock: bool = False,
        ingest_duration_sec: float | None = None,
        gemini_model: str | None = None,
        graph_source: str | None = None,
        unified_context: str | None = None,
        strategist_brief: StrategistOutput | None = None,
        editor_report: EditorReport | None = None,
        vertical: str | None = None,
    ) -> Path:
        job_dir = self._job_dir(result.id)
        job_dir.mkdir(parents=True, exist_ok=True)

        manifest = Manifest(
            id=result.id,
            youtube_url=result.youtube_url,
            mode=result.mode.value,
            title=result.title,
            created_at=result.created_at.isoformat(),
            status="done",
            workflow_status=result.workflow_status.value,
            pipeline_mock=pipeline_mock,
            llm_mock=llm_mock,
            ingest_duration_sec=ingest_duration_sec,
            gemini_model=gemini_model,
            graph_source=graph_source,  # type: ignore[arg-type]
        )
        (job_dir / "manifest.json").write_text(
            manifest.model_dump_json(indent=2), encoding="utf-8"
        )
        (job_dir / "blog.md").write_text(result.blog_post, encoding="utf-8")
        (job_dir / "tweets.json").write_text(
            json.dumps(result.tweets, indent=2), encoding="utf-8"
        )
        (job_dir / "graph.json").write_text(
            result.graph.model_dump_json(indent=2), encoding="utf-8"
        )
        (job_dir / "summary.txt").write_text(result.watcher_summary, encoding="utf-8")
        if result.claims:
            (job_dir / "claims.json").write_text(
                json.dumps(
                    [c.model_dump(mode="json") for c in result.claims],
                    indent=2,
                ),
                encoding="utf-8",
            )
        if unified_context and unified_context.strip():
            (job_dir / "unified_context.txt").write_text(
                unified_context.strip(), encoding="utf-8"
            )
        if strategist_brief is not None:
            (job_dir / "strategist_brief.json").write_text(
                strategist_brief.model_dump_json(indent=2), encoding="utf-8"
            )
        if editor_report is not None:
            (job_dir / "editor_report.json").write_text(
                editor_report.model_dump_json(indent=2), encoding="utf-8"
            )
        return job_dir

    def _load_claims(self, job_dir: Path) -> list[Claim]:
        claims_path = job_dir / "claims.json"
        if not claims_path.exists():
            return []
        raw = json.loads(claims_path.read_text(encoding="utf-8"))
        return [Claim.model_validate(c) for c in raw]

    def load(self, job_id: str) -> PressKitResult:
        job_dir = self._job_dir(job_id)
        if not job_dir.is_dir():
            raise ResultsNotFoundError(f"Press kit {job_id} not found.")

        manifest_path = job_dir / "manifest.json"
        if not manifest_path.exists():
            raise ResultsNotFoundError(f"Press kit {job_id} not found.")

        manifest = Manifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
        blog = (job_dir / "blog.md").read_text(encoding="utf-8")
        tweets = json.loads((job_dir / "tweets.json").read_text(encoding="utf-8"))
        graph = GraphData.model_validate_json((job_dir / "graph.json").read_text(encoding="utf-8"))
        summary_path = job_dir / "summary.txt"
        summary = summary_path.read_text(encoding="utf-8") if summary_path.exists() else ""
        claims = self._load_claims(job_dir)

        from datetime import datetime

        from app.domain.models import ProcessingMode

        try:
            wf = WorkflowStatus(manifest.workflow_status)
        except ValueError:
            wf = WorkflowStatus.DRAFT

        return PressKitResult(
            id=manifest.id,
            youtube_url=manifest.youtube_url,
            mode=ProcessingMode(manifest.mode),
            title=manifest.title,
            blog_post=blog,
            tweets=tweets,
            graph=graph,
            watcher_summary=summary,
            claims=claims,
            workflow_status=wf,
            created_at=datetime.fromisoformat(manifest.created_at),
        )

    def load_manifest(self, job_id: str) -> Manifest:
        manifest_path = self._job_dir(job_id) / "manifest.json"
        if not manifest_path.exists():
            raise ResultsNotFoundError(f"Press kit {job_id} not found.")
        return Manifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))

    def update_workflow_status(self, job_id: str, status: WorkflowStatus) -> Manifest:
        manifest = self.load_manifest(job_id)
        manifest.workflow_status = status.value
        path = self._job_dir(job_id) / "manifest.json"
        path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        return manifest

    def save_blog(self, job_id: str, blog_post: str) -> None:
        self._job_dir(job_id).joinpath("blog.md").write_text(blog_post, encoding="utf-8")

    def save_tweets(self, job_id: str, tweets: list[str]) -> None:
        self._job_dir(job_id).joinpath("tweets.json").write_text(
            json.dumps(tweets, indent=2), encoding="utf-8"
        )

    def save_graph(self, job_id: str, graph: GraphData) -> None:
        self._job_dir(job_id).joinpath("graph.json").write_text(
            graph.model_dump_json(indent=2), encoding="utf-8"
        )

    def load_summary(self, job_id: str) -> str:
        path = self._job_dir(job_id) / "summary.txt"
        if not path.exists():
            raise ResultsNotFoundError(f"Summary for {job_id} not found.")
        return path.read_text(encoding="utf-8")

    def list_recent(self, limit: int = 20) -> list[Manifest]:
        manifests: list[Manifest] = []
        if not self.base.exists():
            return manifests
        for path in sorted(self.base.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if not path.is_dir():
                continue
            manifest_file = path / "manifest.json"
            if manifest_file.exists():
                manifests.append(
                    Manifest.model_validate_json(manifest_file.read_text(encoding="utf-8"))
                )
            if len(manifests) >= limit:
                break
        return manifests


_results_repo: ResultsRepository | None = None


def get_results_repo() -> ResultsRepository:
    global _results_repo
    if _results_repo is None:
        _results_repo = ResultsRepository()
    return _results_repo
