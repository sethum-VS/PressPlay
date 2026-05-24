import json
from pathlib import Path

from app.config import Settings, get_settings
from app.domain.errors import ResultsNotFoundError
from app.domain.models import GraphData, Manifest, PressKitResult, WriterOutput


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
            pipeline_mock=pipeline_mock,
            llm_mock=llm_mock,
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
        return job_dir

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

        from datetime import datetime

        from app.domain.models import ProcessingMode

        return PressKitResult(
            id=manifest.id,
            youtube_url=manifest.youtube_url,
            mode=ProcessingMode(manifest.mode),
            title=manifest.title,
            blog_post=blog,
            tweets=tweets,
            graph=graph,
            watcher_summary=summary,
            created_at=datetime.fromisoformat(manifest.created_at),
        )

    def load_manifest(self, job_id: str) -> Manifest:
        manifest_path = self._job_dir(job_id) / "manifest.json"
        if not manifest_path.exists():
            raise ResultsNotFoundError(f"Press kit {job_id} not found.")
        return Manifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))

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
