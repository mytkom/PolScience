from __future__ import annotations

from dataclasses import dataclass, field
import sqlite3
from typing import Any, Iterable


@dataclass(frozen=True, slots=True)
class GraphNode:
    id: str
    kind: str
    label: str
    weight: float = 1.0
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GraphEdge:
    source: str
    target: str
    kind: str
    weight: float = 1.0
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PublicationGraph:
    nodes: dict[str, GraphNode]
    edges: list[GraphEdge]

    def node(self, node_id: str) -> GraphNode | None:
        return self.nodes.get(node_id)

    def neighbors(self, node_id: str) -> list[str]:
        adjacent: list[str] = []
        for edge in self.edges:
            if edge.source == node_id:
                adjacent.append(edge.target)
            elif edge.target == node_id:
                adjacent.append(edge.source)
        return adjacent


@dataclass(slots=True)
class PublicationNeighborhood:
    root_id: str
    root: GraphNode | None
    neighbors: dict[str, GraphNode]
    edges: list[GraphEdge]

    def as_graph(self) -> PublicationGraph:
        nodes = dict(self.neighbors)
        if self.root is not None:
            nodes[self.root.id] = self.root
        return PublicationGraph(nodes=nodes, edges=list(self.edges))


def ensure_graph_indexes(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE INDEX IF NOT EXISTS idx_authorship_profile ON authorship (profile_id)")


def _publication_label(row: sqlite3.Row) -> str:
    title = str(row["title"] or "").strip()
    if title:
        return title
    return str(row["id"])


def load_publication_node(conn: sqlite3.Connection, publication_id: str) -> GraphNode | None:
    pid = str(publication_id).strip()
    if not pid:
        return None
    row = conn.execute(
        """
        SELECT id, title, year, doi, journal_name, pages, publication_type, url
        FROM publications
        WHERE id = ?
        LIMIT 1
        """,
        (pid,),
    ).fetchone()
    if row is None:
        return None
    return GraphNode(
        id=str(row["id"]),
        kind="publication",
        label=_publication_label(row),
        weight=1.0,
        data={
            "year": row["year"],
            "doi": row["doi"],
            "journal_name": row["journal_name"],
            "pages": row["pages"],
            "publication_type": row["publication_type"],
            "url": row["url"],
        },
    )


def load_publication_nodes(
    conn: sqlite3.Connection,
    *,
    limit: int | None = None,
    publication_ids: Iterable[str] | None = None,
) -> list[GraphNode]:
    ids = [str(pid).strip() for pid in (publication_ids or []) if pid and str(pid).strip()]
    if ids:
        placeholders = ",".join(["?"] * len(ids))
        sql = f"""
            SELECT id, title, year, doi, journal_name, pages, publication_type, url
            FROM publications
            WHERE id IN ({placeholders})
        """
        params: tuple[Any, ...] = tuple(ids)
    else:
        sql = """
            SELECT id, title, year, doi, journal_name, pages, publication_type, url
            FROM publications
            ORDER BY COALESCE(year, 0) DESC, COALESCE(title, id) ASC, id ASC
        """
        params = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (int(limit),)

    nodes: list[GraphNode] = []
    for row in conn.execute(sql, params).fetchall():
        nodes.append(
            GraphNode(
                id=str(row["id"]),
                kind="publication",
                label=_publication_label(row),
                weight=1.0,
                data={
                    "year": row["year"],
                    "doi": row["doi"],
                    "journal_name": row["journal_name"],
                    "pages": row["pages"],
                    "publication_type": row["publication_type"],
                    "url": row["url"],
                },
            )
        )
    return nodes


def load_publication_edges_by_shared_authors(
    conn: sqlite3.Connection,
    *,
    publication_ids: Iterable[str] | None = None,
    min_shared_authors: int = 1,
) -> list[GraphEdge]:
    ids = [str(pid).strip() for pid in (publication_ids or []) if pid and str(pid).strip()]
    if not ids:
        return []

    ensure_graph_indexes(conn)
    placeholders = ",".join(["?"] * len(ids))
    sql = f"""
        SELECT
            a1.publication_id AS source_id,
            a2.publication_id AS target_id,
            COUNT(DISTINCT a1.profile_id) AS shared_authors
        FROM authorship a1
        JOIN authorship a2
          ON a1.profile_id = a2.profile_id
         AND a1.publication_id < a2.publication_id
        WHERE a1.publication_id IN ({placeholders})
          AND a2.publication_id IN ({placeholders})
        GROUP BY a1.publication_id, a2.publication_id
        HAVING COUNT(DISTINCT a1.profile_id) >= ?
        ORDER BY shared_authors DESC, source_id ASC, target_id ASC
    """

    params: tuple[Any, ...] = tuple(ids) + tuple(ids) + (max(1, int(min_shared_authors)),)
    edges: list[GraphEdge] = []
    for row in conn.execute(sql, params).fetchall():
        edges.append(
            GraphEdge(
                source=str(row["source_id"]),
                target=str(row["target_id"]),
                kind="shared_authors",
                weight=float(row["shared_authors"] or 0),
                data={"shared_authors": int(row["shared_authors"] or 0)},
            )
        )
    return edges


def load_publication_neighborhood_by_shared_authors(
    conn: sqlite3.Connection,
    *,
    publication_id: str,
    min_shared_authors: int = 1,
) -> PublicationNeighborhood:
    root = load_publication_node(conn, publication_id)
    root_id = str(publication_id).strip()
    if root is None:
        return PublicationNeighborhood(root_id=root_id, root=None, neighbors={}, edges=[])

    ensure_graph_indexes(conn)
    sql = """
        SELECT
            CASE WHEN a1.publication_id = ? THEN a2.publication_id ELSE a1.publication_id END AS neighbor_id,
            COUNT(DISTINCT a1.profile_id) AS shared_authors
        FROM authorship a1
        JOIN authorship a2
          ON a1.profile_id = a2.profile_id
         AND a1.publication_id < a2.publication_id
        WHERE a1.publication_id = ? OR a2.publication_id = ?
        GROUP BY neighbor_id
        HAVING COUNT(DISTINCT a1.profile_id) >= ?
        ORDER BY shared_authors DESC, neighbor_id ASC
    """

    edges: list[GraphEdge] = []
    neighbor_ids: list[str] = []
    params: tuple[Any, ...] = (root.id, root.id, root.id, max(1, int(min_shared_authors)))
    for row in conn.execute(sql, params).fetchall():
        neighbor_id = str(row["neighbor_id"])
        neighbor_ids.append(neighbor_id)
        edges.append(
            GraphEdge(
                source=root.id,
                target=neighbor_id,
                kind="shared_authors",
                weight=float(row["shared_authors"] or 0),
                data={"shared_authors": int(row["shared_authors"] or 0)},
            )
        )

    neighbor_nodes = load_publication_nodes(conn, publication_ids=neighbor_ids)
    return PublicationNeighborhood(
        root_id=root.id,
        root=root,
        neighbors={node.id: node for node in neighbor_nodes},
        edges=edges,
    )


def build_publication_graph(
    conn: sqlite3.Connection,
    *,
    publication_id: str,
    min_shared_authors: int = 1,
) -> PublicationGraph:
    return load_publication_neighborhood_by_shared_authors(
        conn,
        publication_id=publication_id,
        min_shared_authors=min_shared_authors,
    ).as_graph()