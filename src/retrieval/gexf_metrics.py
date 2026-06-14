"""Load precomputed GEXF node metrics for expert search enrichment."""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

INSTITUTION_FULL_GEXF = "institution_full.gexf"
RESEARCHER_GEXF_GLOB = "researcher_*.gexf"
_GEXF_NS = "http://www.gexf.net/1.2draft"

logger = logging.getLogger("polscience.retrieval.gexf_metrics")

_metrics_cache: GraphMetricsStore | None = None


@dataclass(frozen=True, slots=True)
class ResearcherGraphMetrics:
    coauth_degree: int
    network_pagerank: float
    cluster_id: int | None = None
    cluster_name: str | None = None
    betweenness: float | None = None
    closeness: float | None = None
    clustering: float | None = None


@dataclass(frozen=True, slots=True)
class InstitutionGraphMetrics:
    coauth_degree: int
    network_pagerank: float
    cluster_id: int | None = None
    cluster_name: str | None = None
    betweenness: float | None = None
    closeness: float | None = None
    clustering: float | None = None


@dataclass(frozen=True, slots=True)
class GraphMetricsStore:
    researchers: dict[str, ResearcherGraphMetrics]
    institutions: dict[str, InstitutionGraphMetrics]

    @property
    def has_researcher_metrics(self) -> bool:
        return bool(self.researchers)

    @property
    def has_institution_metrics(self) -> bool:
        return bool(self.institutions)

    def researcher_pagerank(self, profile_id: str) -> float | None:
        metrics = self.researchers.get(profile_id)
        return metrics.network_pagerank if metrics is not None else None

    def institution_pagerank(self, institution_id: str) -> float | None:
        metrics = self.institutions.get(institution_id)
        return metrics.network_pagerank if metrics is not None else None


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _required_int(value: Any, default: int = 0) -> int:
    parsed = _optional_int(value)
    return default if parsed is None else parsed


def _required_float(value: Any, default: float = 0.0) -> float:
    parsed = _optional_float(value)
    return default if parsed is None else parsed


def _parse_researcher_node(attrs: dict[str, Any]) -> ResearcherGraphMetrics:
    return ResearcherGraphMetrics(
        coauth_degree=_required_int(attrs.get("degree")),
        network_pagerank=_required_float(attrs.get("pagerank")),
        cluster_id=_optional_int(attrs.get("community")),
        cluster_name=str(attrs["community_name"]).strip()
        if attrs.get("community_name") not in (None, "")
        else None,
        betweenness=_optional_float(attrs.get("betweenness_centrality")),
        closeness=_optional_float(attrs.get("closeness_centrality")),
        clustering=_optional_float(attrs.get("clustering_coefficient")),
    )


def _parse_institution_node(attrs: dict[str, Any]) -> InstitutionGraphMetrics:
    return InstitutionGraphMetrics(
        coauth_degree=_required_int(attrs.get("degree")),
        network_pagerank=_required_float(attrs.get("pagerank")),
        cluster_id=_optional_int(attrs.get("community")),
        cluster_name=str(attrs["community_name"]).strip()
        if attrs.get("community_name") not in (None, "")
        else None,
        betweenness=_optional_float(attrs.get("betweenness_centrality")),
        closeness=_optional_float(attrs.get("closeness_centrality")),
        clustering=_optional_float(attrs.get("clustering_coefficient")),
    )


def _gexf_tag(local: str) -> str:
    return f"{{{_GEXF_NS}}}{local}"


def _local_tag(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _parse_gexf_node_attributes(path: Path) -> dict[str, dict[str, str]]:
    """Parse node attributes from GEXF without NetworkX strict typing.

    Some exports declare ``clustering_coefficient`` as ``long`` but store floats;
    NetworkX ``read_gexf`` rejects those files, so we read attvalues directly.
    """
    tree = ET.parse(path)
    root = tree.getroot()

    id_to_title: dict[str, str] = {}
    for elem in root.iter():
        if _local_tag(elem.tag) != "attributes" or elem.get("class") != "node":
            continue
        for attr in elem:
            if _local_tag(attr.tag) != "attribute":
                continue
            attr_id = attr.get("id")
            title = attr.get("title")
            if attr_id and title:
                id_to_title[attr_id] = title

    nodes: dict[str, dict[str, str]] = {}
    for elem in root.iter():
        if _local_tag(elem.tag) != "node":
            continue
        node_id = elem.get("id")
        if not node_id:
            continue
        data: dict[str, str] = {}
        for child in elem:
            if _local_tag(child.tag) != "attvalues":
                continue
            for attvalue in child:
                if _local_tag(attvalue.tag) != "attvalue":
                    continue
                title = id_to_title.get(attvalue.get("for") or "")
                if title:
                    data[title] = attvalue.get("value", "")
        nodes[str(node_id)] = data
    return nodes


def _load_nodes_from_gexf(
    path: Path,
    *,
    parse_node,
) -> dict[str, Any]:
    try:
        raw_nodes = _parse_gexf_node_attributes(path)
    except Exception as exc:
        logger.warning("Failed to parse GEXF %s: %s", path, exc)
        return {}
    out: dict[str, Any] = {}
    for node_id, attrs in raw_nodes.items():
        try:
            out[node_id] = parse_node(attrs)
        except Exception as exc:
            logger.warning("Skipping GEXF node %s in %s: %s", node_id, path.name, exc)
    return out


def load_graph_metrics(graphs_dir: Path) -> GraphMetricsStore:
    graphs_dir = graphs_dir.resolve()
    if not graphs_dir.is_dir():
        logger.info("Graph metrics directory not found: %s", graphs_dir)
        return GraphMetricsStore(researchers={}, institutions={})

    researchers: dict[str, ResearcherGraphMetrics] = {}
    for path in sorted(graphs_dir.glob(RESEARCHER_GEXF_GLOB)):
        loaded = _load_nodes_from_gexf(path, parse_node=_parse_researcher_node)
        researchers.update(loaded)
        logger.info("Loaded researcher GEXF metrics: %s (%d nodes)", path.name, len(loaded))

    institutions: dict[str, InstitutionGraphMetrics] = {}
    institution_path = graphs_dir / INSTITUTION_FULL_GEXF
    if institution_path.is_file():
        institutions = _load_nodes_from_gexf(
            institution_path,
            parse_node=_parse_institution_node,
        )
        logger.info(
            "Loaded institution GEXF metrics: %s (%d nodes)",
            institution_path.name,
            len(institutions),
        )

    return GraphMetricsStore(researchers=researchers, institutions=institutions)


def get_graph_metrics_store() -> GraphMetricsStore | None:
    return _metrics_cache


def preload_graph_metrics(
    graphs_dir: Path,
    artifacts_dir: Path | None = None,
) -> GraphMetricsStore:
    from src.retrieval.profile_graph_metrics import (
        load_profile_graph_metrics,
        merge_researcher_metrics,
    )

    global _metrics_cache
    gexf_store = load_graph_metrics(graphs_dir)
    index_metrics: dict[str, ResearcherGraphMetrics] = {}
    if artifacts_dir is not None:
        index_metrics = load_profile_graph_metrics(artifacts_dir)
        if index_metrics:
            logger.info(
                "Loaded build-index profile metrics: %d profiles",
                len(index_metrics),
            )
    researchers = merge_researcher_metrics(index_metrics, gexf_store.researchers)
    store = GraphMetricsStore(researchers=researchers, institutions=gexf_store.institutions)
    _metrics_cache = store
    logger.info(
        "Graph metrics preload complete: %d researchers, %d institutions",
        len(store.researchers),
        len(store.institutions),
    )
    return store


def clear_graph_metrics_cache() -> None:
    global _metrics_cache
    _metrics_cache = None


def max_institution_pagerank_for_profile(
    store: GraphMetricsStore,
    profile_institution_ids: list[str],
    filter_institution_ids: frozenset[str],
) -> float | None:
    """Max network PageRank among filter institutions the profile currently holds."""
    matched = [iid for iid in profile_institution_ids if iid in filter_institution_ids]
    if not matched:
        return None
    scores = [
        score
        for iid in matched
        if (score := store.institution_pagerank(iid)) is not None
    ]
    return max(scores) if scores else None
