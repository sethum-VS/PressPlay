"""Graphify CLI integration + normalization to D3 graph.json shape."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.config import get_settings
from app.domain.models import GraphData, GraphEdge, GraphNode
from app.services.mock_mode import graphify_llm_available, graphify_uses_heuristic

logger = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(text: str) -> str:
    return _SLUG_RE.sub("_", text.lower()).strip("_") or "entity"


def _stub_graph() -> GraphData:
    return GraphData(
        nodes=[
            GraphNode(id="spacex", label="SpaceX", group="org"),
            GraphNode(id="falcon9", label="Falcon 9", group="vehicle"),
            GraphNode(id="starlink_v2", label="Starlink V2 Mini", group="product"),
            GraphNode(id="b1073", label="Booster B1073", group="hardware"),
            GraphNode(id="asog", label="A Shortfall of Gravitas", group="location"),
        ],
        edges=[
            GraphEdge(source="spacex", target="falcon9", label="operates"),
            GraphEdge(source="falcon9", target="starlink_v2", label="deployed"),
            GraphEdge(source="falcon9", target="b1073", label="uses"),
            GraphEdge(source="b1073", target="asog", label="landed_on"),
        ],
    )


def _normalize_label(label: str) -> str:
    """Collapse whitespace so line breaks do not become entity names."""
    return re.sub(r"\s+", " ", label).strip()


def _heuristic_graph_from_markdown(blog_markdown: str) -> GraphData:
    """Lightweight entity graph when Graphify LLM extract is unavailable."""
    nodes: dict[str, GraphNode] = {}
    edges: list[GraphEdge] = []
    _STOPWORDS = frozenset({"the", "and", "for", "with", "in", "a", "an", "of", "to"})

    def add_node(label: str, group: str = "entity") -> str:
        clean = _normalize_label(label)
        if len(clean) < 2 or clean.lower() in _STOPWORDS:
            return ""
        nid = _slug(clean)[:48]
        if nid not in nodes:
            nodes[nid] = GraphNode(id=nid, label=clean, group=group)
        return nid

    title_match = re.search(r"^#\s+(.+)$", blog_markdown, re.M)
    if title_match:
        add_node(title_match.group(1), group="topic")

    for line in blog_markdown.splitlines():
        if line.startswith("#"):
            add_node(line.lstrip("# ").strip(), group="topic")
        for quoted in re.findall(r'"([^"]{2,80})"|“([^”]{2,80})”', line):
            label = next((q for q in quoted if q), "")
            if label:
                add_node(label, group="quote")
        for bold in re.findall(r"\*\*([^*]+)\*\*", line):
            add_node(bold, group="entity")

    caps = re.findall(
        r"\b(?:[A-Z][a-z]+(?:[ \t]+[A-Z][a-z0-9]+){0,4}|[A-Z]{2,}[0-9]*)\b",
        blog_markdown,
    )
    seen_caps: list[str] = []
    for token in caps:
        token = _normalize_label(token)
        if token.lower() in _STOPWORDS:
            continue
        if len(token) < 3 or token in seen_caps:
            continue
        seen_caps.append(token)
        add_node(token, group="entity")
        if len(seen_caps) > 12:
            break

    node_ids = list(nodes.keys())
    for i in range(len(node_ids) - 1):
        edges.append(
            GraphEdge(
                source=node_ids[i],
                target=node_ids[i + 1],
                label="related_to",
            )
        )

    if len(nodes) < 2:
        return _stub_graph()
    return GraphData(nodes=list(nodes.values()), edges=edges[:24])


def normalize_graphify_json(raw: dict) -> GraphData:
    """Map Graphify graph.json (nodes + links/edges) to PressPlay D3 contract."""
    raw_nodes = raw.get("nodes") or []
    raw_edges = raw.get("edges") or raw.get("links") or []

    nodes: list[GraphNode] = []
    seen_ids: set[str] = set()
    for n in raw_nodes:
        if not isinstance(n, dict):
            continue
        nid = str(n.get("id") or n.get("name") or "").strip()
        label = str(n.get("label") or n.get("name") or nid).strip()
        if not nid or not label:
            continue
        if nid in seen_ids:
            continue
        seen_ids.add(nid)
        group = str(
            n.get("group")
            or n.get("file_type")
            or n.get("type")
            or "entity"
        )
        nodes.append(GraphNode(id=nid, label=label, group=group))

    edges: list[GraphEdge] = []
    for e in raw_edges:
        if not isinstance(e, dict):
            continue
        src = e.get("source")
        tgt = e.get("target")
        if isinstance(src, dict):
            src = src.get("id")
        if isinstance(tgt, dict):
            tgt = tgt.get("id")
        if not src or not tgt:
            continue
        label = str(e.get("label") or e.get("relation") or "related_to")
        edges.append(GraphEdge(source=str(src), target=str(tgt), label=label))

    if not nodes:
        raise ValueError("Graphify output contained no nodes.")
    return GraphData(nodes=nodes, edges=edges)


def _resolve_graphify_bin() -> str | None:
    settings = get_settings()
    if settings.graphify_bin:
        path = Path(settings.graphify_bin)
        if path.is_file():
            return str(path)
    for name in ("graphify", "graphifyy"):
        found = shutil.which(name)
        if found:
            return found
    venv = settings.project_root / ".venv" / "bin" / "graphify"
    if venv.is_file():
        return str(venv)
    return None


def _graphify_env() -> dict[str, str]:
    env = os.environ.copy()
    settings = get_settings()
    project = settings.effective_gcp_project
    location = settings.effective_gcp_location
    if project:
        env.setdefault("VERTEX_PROJECT", project)
        env.setdefault("GOOGLE_CLOUD_PROJECT", project)
        env.setdefault("GCP_PROJECT_ID", project)
    if location:
        env.setdefault("VERTEX_LOCATION", location)
        env.setdefault("GOOGLE_CLOUD_LOCATION", location)
        env.setdefault("GCP_LOCATION", location)
    if settings.google_application_credentials:
        env.setdefault(
            "GOOGLE_APPLICATION_CREDENTIALS",
            settings.google_application_credentials,
        )
    if settings.gemini_model:
        env.setdefault("GRAPHIFY_GEMINI_MODEL", settings.gemini_model)
    return env


def _run_graphify_extract(work_dir: Path) -> Path:
    bin_path = _resolve_graphify_bin()
    if not bin_path:
        raise FileNotFoundError(
            "graphify CLI not found — install graphifyy or set GRAPHIFY_BIN."
        )

    cmd = [
        bin_path,
        "extract",
        str(work_dir),
        "--no-cluster",
        "--out",
        str(work_dir),
    ]
    if graphify_llm_available():
        cmd.extend(["--backend", "gemini"])
    else:
        raise RuntimeError("No LLM API key for graphify extract.")

    logger.info("Running Graphify: %s", " ".join(cmd))
    proc = subprocess.run(
        cmd,
        cwd=str(work_dir),
        env=_graphify_env(),
        capture_output=True,
        text=True,
        timeout=600,
    )
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-2000:]
        raise RuntimeError(f"graphify extract failed (exit {proc.returncode}): {tail}")

    graph_path = work_dir / "graphify-out" / "graph.json"
    if not graph_path.is_file():
        raise FileNotFoundError(f"Graphify did not write {graph_path}")
    return graph_path


class GraphifyService:
    """Run Graphify on blog markdown; normalize to D3 nodes/edges."""

    async def build_graph(self, blog_markdown: str) -> GraphData:
        if not blog_markdown.strip():
            return _heuristic_graph_from_markdown(blog_markdown)

        if graphify_uses_heuristic():
            return _heuristic_graph_from_markdown(blog_markdown)

        try:
            return await asyncio.to_thread(self._build_graph_sync, blog_markdown)
        except Exception as exc:
            logger.warning("Graphify failed, using heuristic graph: %s", exc)
            return _heuristic_graph_from_markdown(blog_markdown)

    def _build_graph_sync(self, blog_markdown: str) -> GraphData:
        with tempfile.TemporaryDirectory(prefix="pressplay-graphify-") as tmp:
            work = Path(tmp)
            (work / "blog.md").write_text(blog_markdown, encoding="utf-8")
            graph_path = _run_graphify_extract(work)
            raw = json.loads(graph_path.read_text(encoding="utf-8"))
            return normalize_graphify_json(raw)
