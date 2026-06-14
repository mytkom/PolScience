from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any


# ── kind constants ────────────────────────────────────────────────────────────

KIND_RESEARCHER = "researcher"
KIND_INSTITUTION = "institution"
KIND_SPECIALTY = "specialty"

EDGE_CO_AUTHORSHIP = "co_authorship"
EDGE_INSTITUTION_COLLAB = "institution_collaboration"
EDGE_SPECIALTY_CO_OCC = "specialty_co_occurrence"


# ── types ─────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class GraphNode:
    id: str
    kind: str
    label: str
    weight: float = 1.0  # publication count — proxy for citations (no citation data in DB)
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GraphEdge:
    source: str
    target: str
    kind: str
    weight: float = 1.0
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Graph:
    nodes: dict[str, GraphNode]
    edges: list[GraphEdge]


# ── connection helpers ────────────────────────────────────────────────────────

def _ensure_indexes(conn: sqlite3.Connection) -> None:
    """Create graph-query indexes not already present in schema.sql."""
    for ddl in (
        "CREATE INDEX IF NOT EXISTS idx_authorship_profile ON authorship (profile_id)",
        "CREATE INDEX IF NOT EXISTS idx_ps_specialty ON profile_specialties (specialty_id)",
        "CREATE INDEX IF NOT EXISTS idx_ps_profile ON profile_specialties (profile_id)",
    ):
        conn.execute(ddl)


def _query(
    conn: sqlite3.Connection,
    sql: str,
    params: tuple[Any, ...] = (),
) -> list[sqlite3.Row]:
    """Execute a query returning sqlite3.Row objects; restores conn.row_factory afterward."""
    saved = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.row_factory = saved


# ── math ──────────────────────────────────────────────────────────────────────

def _jaccard_pct(shared: int, total_a: int, total_b: int) -> float:
    union = total_a + total_b - shared
    return (shared / union * 100) if union > 0 else 0.0


# ── node factories ────────────────────────────────────────────────────────────

def _make_researcher_node(row: sqlite3.Row) -> GraphNode:
    pub_count = int(row["pub_count"] or 0)
    label = " ".join(filter(None, [row["given_name"], row["surname"]])) or str(row["id"])
    return GraphNode(
        id=str(row["id"]),
        kind=KIND_RESEARCHER,
        label=label,
        weight=float(pub_count),
        data={
            "degree_code": row["degree_code"],
            "domain_code": row["domain_code"],
            "pub_count": pub_count,
        },
    )


def _make_institution_node(row: sqlite3.Row) -> GraphNode:
    total_pubs = int(row["total_pubs"] or 0)
    return GraphNode(
        id=str(row["id"]),
        kind=KIND_INSTITUTION,
        label=str(row["name"]),
        weight=float(total_pubs),
        data={
            "city": row["city"],
            "voivodeship": row["voivodeship"],
            "total_pubs": total_pubs,
        },
    )


def _make_specialty_node(row: sqlite3.Row) -> GraphNode:
    total_pubs = int(row["total_pubs"] or 0)
    return GraphNode(
        id=str(row["id"]),
        kind=KIND_SPECIALTY,
        label=str(row["label"]),
        weight=float(total_pubs),
        data={
            "total_pubs": total_pubs,
            "researcher_count": int(row["researcher_count"] or 0),
        },
    )


# ── SQL constants ─────────────────────────────────────────────────────────────
# Optional filters use (? IS NULL OR col = ?) so a single static string covers
# all filter combinations.  Pass None for unused filters.

_SQL_RESEARCHER_NODES = """
    SELECT p.id, p.given_name, p.surname, p.degree_code, p.domain_code,
           COUNT(a.publication_id) AS pub_count
    FROM profiles p
    LEFT JOIN authorship a ON p.id = a.profile_id
    WHERE p.is_stub = 0
      AND (? IS NULL OR p.domain_code = ?)
      AND (? IS NULL OR EXISTS (
          SELECT 1 FROM profile_institutions pi_f
          WHERE pi_f.profile_id = p.id AND pi_f.institution_id = ?
      ))
    GROUP BY p.id
"""
# params: (domain_code, domain_code, institution_id, institution_id)

_SQL_RESEARCHER_EDGES_FILL_TEMP = """
    INSERT INTO _rg_auth (profile_id, publication_id)
    SELECT a.profile_id, a.publication_id
    FROM authorship a
    JOIN profiles p ON a.profile_id = p.id
    WHERE p.is_stub = 0
      AND (? IS NULL OR p.domain_code = ?)
      AND (? IS NULL OR EXISTS (
          SELECT 1 FROM profile_institutions pi_f
          WHERE pi_f.profile_id = p.id AND pi_f.institution_id = ?
      ))
"""
# params: (domain_code, domain_code, institution_id, institution_id)

_SQL_RESEARCHER_EDGES_QUERY = """
    SELECT a1.profile_id AS source, a2.profile_id AS target,
           COUNT(*) AS shared_pubs
    FROM _rg_auth a1
    JOIN _rg_auth a2
      ON a1.publication_id = a2.publication_id
     AND a1.profile_id < a2.profile_id
    GROUP BY a1.profile_id, a2.profile_id
    HAVING shared_pubs >= ?
"""
# params: (min_shared_pubs,)

_SQL_INSTITUTION_NODES = """
    SELECT i.id, i.name, i.city, i.voivodeship,
           COUNT(DISTINCT a.publication_id) AS total_pubs
    FROM institutions i
    JOIN profile_institutions pi ON i.id = pi.institution_id
    JOIN authorship a ON pi.profile_id = a.profile_id
    GROUP BY i.id
"""

_SQL_INSTITUTION_EDGES = """
    WITH inst_pub AS (
        SELECT DISTINCT pi.institution_id, a.publication_id
        FROM authorship a
        JOIN profile_institutions pi ON a.profile_id = pi.profile_id
    )
    SELECT
        ip1.institution_id AS inst_a,
        ip2.institution_id AS inst_b,
        COUNT(*) AS shared_pubs
    FROM inst_pub ip1
    JOIN inst_pub ip2
      ON ip1.publication_id = ip2.publication_id
     AND ip1.institution_id < ip2.institution_id
    GROUP BY inst_a, inst_b
    HAVING shared_pubs >= ?
"""
# params: (min_shared_pubs,)

_SQL_SPECIALTY_NODES = """
    SELECT s.id,
           COALESCE(s.label_pl, s.label_en, s.id) AS label,
           COUNT(DISTINCT a.publication_id) AS total_pubs,
           COUNT(DISTINCT ps.profile_id) AS researcher_count
    FROM specialties s
    JOIN profile_specialties ps ON s.id = ps.specialty_id
    LEFT JOIN authorship a ON ps.profile_id = a.profile_id
    GROUP BY s.id
"""

_SQL_SPECIALTY_EDGES = """
    WITH counts AS (
        SELECT specialty_id, COUNT(DISTINCT profile_id) AS n
        FROM profile_specialties
        GROUP BY specialty_id
    )
    SELECT
        ps1.specialty_id AS source,
        ps2.specialty_id AS target,
        COUNT(DISTINCT ps1.profile_id) AS shared,
        c.n AS source_total
    FROM profile_specialties ps1
    JOIN profile_specialties ps2
      ON ps1.profile_id = ps2.profile_id
     AND ps1.specialty_id != ps2.specialty_id
    JOIN counts c ON c.specialty_id = ps1.specialty_id
    GROUP BY ps1.specialty_id, ps2.specialty_id
    HAVING shared >= ?
"""
# params: (min_shared_researchers,)


# ── public loaders ────────────────────────────────────────────────────────────

def load_researcher_graph(
    conn: sqlite3.Connection,
    *,
    domain_code: str | None = None,
    institution_id: str | None = None,
    min_shared_pubs: int = 1,
) -> Graph:
    """
    Nodes  = researchers (weight = publication count, proxy for citations).
    Edges  = co-authorship; weight = number of shared publications.

    Filtering by domain_code or institution_id is strongly recommended —
    the full dataset has 150k+ profiles and 2.4M authorship rows.
    """
    min_shared_pubs = max(1, min_shared_pubs)
    _ensure_indexes(conn)

    nodes = {
        str(r["id"]): _make_researcher_node(r)
        for r in _query(conn, _SQL_RESEARCHER_NODES, (
            domain_code, domain_code,
            institution_id, institution_id,
        ))
    }

    if not nodes:
        return Graph(nodes={}, edges=[])

    conn.execute("CREATE TEMP TABLE IF NOT EXISTS _rg_auth (profile_id INTEGER, publication_id INTEGER)")
    conn.execute("DELETE FROM _rg_auth")
    conn.execute(_SQL_RESEARCHER_EDGES_FILL_TEMP, (
        domain_code, domain_code,
        institution_id, institution_id,
    ))
    conn.execute("CREATE INDEX IF NOT EXISTS _rg_auth_pub ON _rg_auth (publication_id, profile_id)")

    edges = [
        GraphEdge(
            source=str(row["source"]),
            target=str(row["target"]),
            kind=EDGE_CO_AUTHORSHIP,
            weight=float(row["shared_pubs"]),
            data={"shared_pubs": int(row["shared_pubs"])},
        )
        for row in _query(conn, _SQL_RESEARCHER_EDGES_QUERY, (min_shared_pubs,))
    ]

    conn.execute("DROP TABLE IF EXISTS _rg_auth")
    return Graph(nodes=nodes, edges=edges)


def load_institution_graph(
    conn: sqlite3.Connection,
    *,
    min_shared_pubs: int = 1,
) -> Graph:
    """
    Nodes  = institutions (weight = total distinct publications by affiliated researchers).
    Edges  = institutions appearing together on at least one publication.
             weight = Jaccard similarity as percentage:
             shared / (pubs_a + pubs_b - shared) * 100
    """
    min_shared_pubs = max(1, min_shared_pubs)
    _ensure_indexes(conn)

    nodes = {
        str(r["id"]): _make_institution_node(r)
        for r in _query(conn, _SQL_INSTITUTION_NODES)
    }

    pub_totals: dict[str, int] = {nid: node.data["total_pubs"] for nid, node in nodes.items()}

    edges = [
        GraphEdge(
            source=str(row["inst_a"]),
            target=str(row["inst_b"]),
            kind=EDGE_INSTITUTION_COLLAB,
            weight=_jaccard_pct(
                int(row["shared_pubs"]),
                pub_totals.get(str(row["inst_a"]), 0),
                pub_totals.get(str(row["inst_b"]), 0),
            ),
            data={
                "shared_pubs": int(row["shared_pubs"]),
                "pubs_a": pub_totals.get(str(row["inst_a"]), 0),
                "pubs_b": pub_totals.get(str(row["inst_b"]), 0),
            },
        )
        for row in _query(conn, _SQL_INSTITUTION_EDGES, (min_shared_pubs,))
    ]

    return Graph(nodes=nodes, edges=edges)


def load_specialty_graph(
    conn: sqlite3.Connection,
    *,
    min_shared_researchers: int = 2,
    min_pct: float = 0.0,
) -> Graph:
    """
    Nodes  = specialties (weight = total publications of researchers with that specialty).
    Edges  = directed: source → target means X% of researchers with source specialty
             also have target specialty.  weight = that percentage (0–100).

    Tune min_shared_researchers and min_pct to prune low-support edges.
    Example: min_shared_researchers=5, min_pct=10.0 gives a much cleaner graph.
    """
    min_shared_researchers = max(1, min_shared_researchers)
    _ensure_indexes(conn)

    nodes = {
        str(r["id"]): _make_specialty_node(r)
        for r in _query(conn, _SQL_SPECIALTY_NODES)
    }

    edges: list[GraphEdge] = []
    for row in _query(conn, _SQL_SPECIALTY_EDGES, (min_shared_researchers,)):
        pct = int(row["shared"]) / int(row["source_total"] or 1) * 100
        if pct < min_pct:
            continue
        edges.append(GraphEdge(
            source=str(row["source"]),
            target=str(row["target"]),
            kind=EDGE_SPECIALTY_CO_OCC,
            weight=round(pct, 4),
            data={
                "shared_researchers": int(row["shared"]),
                "source_researcher_count": int(row["source_total"]),
                "pct": round(pct, 4),
            },
        ))

    return Graph(nodes=nodes, edges=edges)
