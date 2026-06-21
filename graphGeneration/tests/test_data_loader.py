from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from data_loader import (
    Graph,
    GraphEdge,
    GraphNode,
    KIND_INSTITUTION,
    KIND_RESEARCHER,
    KIND_SPECIALTY,
    _ensure_indexes,
    _jaccard_pct,
    _make_institution_node,
    _make_researcher_node,
    _make_specialty_node,
    _query,
    load_institution_graph,
    load_researcher_graph,
    load_specialty_graph,
)

_SCHEMA = (Path(__file__).parent.parent / "LudzieNaukiScraper" / "schema.sql").read_text()


# ── fixture ───────────────────────────────────────────────────────────────────

@pytest.fixture()
def conn() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(_SCHEMA)
    _seed(db)
    yield db
    db.close()


def _seed(db: sqlite3.Connection) -> None:
    db.executemany(
        "INSERT INTO scientific_domains (code, label_en) VALUES (?, ?)",
        [("DZ01", "Domain 1"), ("DZ02", "Domain 2")],
    )
    db.executemany(
        "INSERT INTO profiles (id, given_name, surname, domain_code, is_stub) VALUES (?,?,?,?,?)",
        [
            ("p1", "Alice", "Smith", "DZ01", 0),
            ("p2", "Bob",   "Jones", "DZ01", 0),
            ("p3", "Carol", "Brown", "DZ02", 0),
            ("p4", "Dan",   "Stub",  None,   1),  # stub — must be excluded from graphs
        ],
    )
    db.executemany(
        "INSERT INTO publications (id, title, year) VALUES (?,?,?)",
        [("pub1", "Paper 1", 2020), ("pub2", "Paper 2", 2021),
         ("pub3", "Paper 3", 2022), ("pub4", "Paper 4", 2023)],
    )
    # p1: pub1, pub2 (2 pubs)
    # p2: pub1, pub2, pub3 (3 pubs)  — shares pub1+pub2 with p1, pub2 with p3
    # p3: pub2, pub4 (2 pubs)        — shares pub2 with p1 and p2
    # p4: pub4 (stub)
    db.executemany(
        "INSERT INTO authorship (profile_id, publication_id) VALUES (?,?)",
        [
            ("p1", "pub1"), ("p1", "pub2"),
            ("p2", "pub1"), ("p2", "pub2"), ("p2", "pub3"),
            ("p3", "pub2"), ("p3", "pub4"),
            ("p4", "pub4"),
        ],
    )
    db.executemany(
        "INSERT INTO institutions (id, name, city, voivodeship) VALUES (?,?,?,?)",
        [("inst1", "Warsaw Univ",  "Warszawa", "mazowieckie"),
         ("inst2", "Wrocław Univ", "Wrocław",  "dolnośląskie")],
    )
    # inst1: p1 + p2  → pubs {pub1, pub2, pub3}  total=3
    # inst2: p3       → pubs {pub2, pub4}         total=2
    # shared between inst1 and inst2: {pub2}       shared=1
    # Jaccard = 1 / (3 + 2 - 1) * 100 = 25.0
    db.executemany(
        "INSERT INTO profile_institutions (employment_id, profile_id, institution_id) VALUES (?,?,?)",
        [("e1", "p1", "inst1"), ("e2", "p2", "inst1"), ("e3", "p3", "inst2")],
    )
    db.executemany(
        "INSERT INTO specialties (id, label_pl, label_en) VALUES (?,?,?)",
        [("spec1", "Spec 1 PL", "Spec 1"), ("spec2", "Spec 2 PL", "Spec 2"), ("spec3", "Spec 3 PL", "Spec 3")],
    )
    # spec1: {p1, p2}  spec2: {p1, p3}  spec3: {p2}
    # Directed co-occurrence edges (source→target = % of source researchers also in target):
    #   spec1→spec2: p1 shared / 2 total = 50%
    #   spec1→spec3: p2 shared / 2 total = 50%
    #   spec2→spec1: p1 shared / 2 total = 50%
    #   spec3→spec1: p2 shared / 1 total = 100%
    db.executemany(
        "INSERT INTO profile_specialties (profile_id, specialty_id) VALUES (?,?)",
        [("p1", "spec1"), ("p1", "spec2"),
         ("p2", "spec1"), ("p2", "spec3"),
         ("p3", "spec2")],
    )
    db.commit()


# ── helper unit tests ─────────────────────────────────────────────────────────

class TestJaccardPct:
    def test_typical(self):
        assert _jaccard_pct(1, 3, 2) == pytest.approx(25.0)

    def test_zero_union(self):
        assert _jaccard_pct(0, 0, 0) == 0.0

    def test_full_overlap(self):
        # shared=5, both sets size 5 → union=5 → 100%
        assert _jaccard_pct(5, 5, 5) == pytest.approx(100.0)

    def test_no_shared(self):
        assert _jaccard_pct(0, 3, 4) == pytest.approx(0.0)


class TestQuery:
    def test_returns_row_objects(self, conn):
        rows = _query(conn, "SELECT id FROM profiles WHERE id = ?", ("p1",))
        assert len(rows) == 1
        assert rows[0]["id"] == "p1"

    def test_preserves_row_factory(self, conn):
        original = conn.row_factory
        _query(conn, "SELECT 1")
        assert conn.row_factory is original

    def test_preserves_non_default_row_factory(self, conn):
        conn.row_factory = lambda c, r: dict(zip([d[0] for d in c.description], r))
        _query(conn, "SELECT 1")
        assert conn.row_factory is not sqlite3.Row


# ── researcher graph ──────────────────────────────────────────────────────────

class TestResearcherGraph:
    def test_returns_graph(self, conn):
        g = load_researcher_graph(conn)
        assert isinstance(g, Graph)

    def test_node_count_excludes_stubs(self, conn):
        g = load_researcher_graph(conn)
        assert "p4" not in g.nodes
        assert len(g.nodes) == 3

    def test_node_kind(self, conn):
        g = load_researcher_graph(conn)
        assert all(n.kind == "researcher" for n in g.nodes.values())

    def test_node_labels(self, conn):
        g = load_researcher_graph(conn)
        assert g.nodes["p1"].label == "Alice Smith"
        assert g.nodes["p2"].label == "Bob Jones"

    def test_node_weights_are_pub_counts(self, conn):
        g = load_researcher_graph(conn)
        assert g.nodes["p1"].weight == 2.0
        assert g.nodes["p2"].weight == 3.0
        assert g.nodes["p3"].weight == 2.0

    def test_edges_co_authorship(self, conn):
        g = load_researcher_graph(conn)
        pairs = {(e.source, e.target) for e in g.edges}
        assert ("p1", "p2") in pairs
        assert ("p1", "p3") in pairs
        assert ("p2", "p3") in pairs

    def test_edge_weight_is_shared_pub_count(self, conn):
        g = load_researcher_graph(conn)
        p1_p2 = next(e for e in g.edges if {e.source, e.target} == {"p1", "p2"})
        assert p1_p2.weight == 2.0  # pub1 + pub2

    def test_edge_kind(self, conn):
        g = load_researcher_graph(conn)
        assert all(e.kind == "co_authorship" for e in g.edges)

    def test_min_shared_pubs_filters_edges(self, conn):
        g = load_researcher_graph(conn, min_shared_pubs=2)
        pairs = {(e.source, e.target) for e in g.edges}
        assert ("p1", "p2") in pairs       # share 2 pubs — kept
        assert ("p1", "p3") not in pairs   # share 1 pub  — dropped
        assert ("p2", "p3") not in pairs   # share 1 pub  — dropped

    def test_domain_filter_nodes(self, conn):
        g = load_researcher_graph(conn, domain_code="DZ01")
        assert set(g.nodes) == {"p1", "p2"}

    def test_domain_filter_edges(self, conn):
        g = load_researcher_graph(conn, domain_code="DZ01")
        assert len(g.edges) == 1
        assert {g.edges[0].source, g.edges[0].target} == {"p1", "p2"}

    def test_institution_filter_nodes(self, conn):
        g = load_researcher_graph(conn, institution_id="inst1")
        assert set(g.nodes) == {"p1", "p2"}

    def test_institution_filter_edges(self, conn):
        g = load_researcher_graph(conn, institution_id="inst1")
        assert len(g.edges) == 1

    def test_no_match_returns_empty_graph(self, conn):
        g = load_researcher_graph(conn, domain_code="DZ99")
        assert g.nodes == {}
        assert g.edges == []


# ── institution graph ─────────────────────────────────────────────────────────

class TestInstitutionGraph:
    def test_returns_graph(self, conn):
        g = load_institution_graph(conn)
        assert isinstance(g, Graph)

    def test_node_ids(self, conn):
        g = load_institution_graph(conn)
        assert set(g.nodes) == {"inst1", "inst2"}

    def test_node_kind(self, conn):
        g = load_institution_graph(conn)
        assert all(n.kind == "institution" for n in g.nodes.values())

    def test_node_labels(self, conn):
        g = load_institution_graph(conn)
        assert g.nodes["inst1"].label == "Warsaw Univ"

    def test_node_weight_is_total_distinct_pubs(self, conn):
        g = load_institution_graph(conn)
        assert g.nodes["inst1"].weight == 3.0  # pub1, pub2, pub3
        assert g.nodes["inst2"].weight == 2.0  # pub2, pub4

    def test_edge_exists(self, conn):
        g = load_institution_graph(conn)
        assert len(g.edges) == 1

    def test_edge_endpoints(self, conn):
        g = load_institution_graph(conn)
        assert {g.edges[0].source, g.edges[0].target} == {"inst1", "inst2"}

    def test_edge_weight_is_jaccard_pct(self, conn):
        g = load_institution_graph(conn)
        # shared=1, total_inst1=3, total_inst2=2 → 1/(3+2-1)*100 = 25.0
        assert g.edges[0].weight == pytest.approx(25.0)

    def test_edge_kind(self, conn):
        g = load_institution_graph(conn)
        assert g.edges[0].kind == "institution_collaboration"

    def test_min_shared_pubs_removes_edge(self, conn):
        g = load_institution_graph(conn, min_shared_pubs=2)
        assert g.edges == []


# ── specialty graph ───────────────────────────────────────────────────────────

class TestSpecialtyGraph:
    def test_returns_graph(self, conn):
        g = load_specialty_graph(conn)
        assert isinstance(g, Graph)

    def test_node_ids(self, conn):
        g = load_specialty_graph(conn)
        assert set(g.nodes) == {"spec1", "spec2", "spec3"}

    def test_node_kind(self, conn):
        g = load_specialty_graph(conn)
        assert all(n.kind == "specialty" for n in g.nodes.values())

    def test_node_label_prefers_polish(self, conn):
        g = load_specialty_graph(conn)
        assert g.nodes["spec1"].label == "Spec 1 PL"

    def test_node_weight_is_total_pubs(self, conn):
        g = load_specialty_graph(conn)
        assert g.nodes["spec1"].weight == 3.0   # pub1, pub2, pub3 (from p1+p2)
        assert g.nodes["spec3"].weight == 3.0   # pub1, pub2, pub3 (from p2 only)

    def test_directed_edges_present(self, conn):
        g = load_specialty_graph(conn, min_shared_researchers=1)
        pairs = {(e.source, e.target) for e in g.edges}
        assert ("spec1", "spec2") in pairs
        assert ("spec1", "spec3") in pairs
        assert ("spec2", "spec1") in pairs
        assert ("spec3", "spec1") in pairs

    def test_edges_are_directed_not_symmetric(self, conn):
        # spec3 has only 1 researcher (p2); spec2 has p1,p3 — p2 not in spec2
        g = load_specialty_graph(conn, min_shared_researchers=1)
        pairs = {(e.source, e.target) for e in g.edges}
        assert ("spec3", "spec2") not in pairs

    def test_edge_weight_is_percentage(self, conn):
        g = load_specialty_graph(conn, min_shared_researchers=1)
        spec3_to_spec1 = next(e for e in g.edges if e.source == "spec3" and e.target == "spec1")
        assert spec3_to_spec1.weight == pytest.approx(100.0)  # 1/1 = 100%

        spec1_to_spec2 = next(e for e in g.edges if e.source == "spec1" and e.target == "spec2")
        assert spec1_to_spec2.weight == pytest.approx(50.0)   # 1/2 = 50%

    def test_edge_kind(self, conn):
        g = load_specialty_graph(conn, min_shared_researchers=1)
        assert all(e.kind == "specialty_co_occurrence" for e in g.edges)

    def test_min_shared_researchers_filter(self, conn):
        g = load_specialty_graph(conn, min_shared_researchers=2)
        assert g.edges == []  # no specialty pair shares 2+ researchers in seed data

    def test_min_pct_filter(self, conn):
        g = load_specialty_graph(conn, min_shared_researchers=1, min_pct=60.0)
        # only spec3→spec1 survives (100%); all others are 50%
        assert len(g.edges) == 1
        assert g.edges[0].source == "spec3"
        assert g.edges[0].target == "spec1"


# ── _ensure_indexes ───────────────────────────────────────────────────────────

class TestEnsureIndexes:
    def test_creates_authorship_profile_index(self, conn):
        _ensure_indexes(conn)
        names = {r[1] for r in conn.execute("PRAGMA index_list(authorship)").fetchall()}
        assert "idx_authorship_profile" in names

    def test_creates_specialty_indexes(self, conn):
        _ensure_indexes(conn)
        names = {r[1] for r in conn.execute("PRAGMA index_list(profile_specialties)").fetchall()}
        assert "idx_ps_specialty" in names
        assert "idx_ps_profile" in names

    def test_idempotent(self, conn):
        _ensure_indexes(conn)
        _ensure_indexes(conn)  # must not raise


# ── node factories ────────────────────────────────────────────────────────────

def _row(**kwargs):
    """Minimal sqlite3.Row-like stub: supports row[key] access."""
    class _R:
        def __getitem__(self, k):
            return kwargs[k]
    return _R()


class TestMakeResearcherNode:
    def test_id(self):
        node = _make_researcher_node(_row(id="p1", given_name="Alice", surname="Smith",
                                          degree_code="dr", domain_code="DZ01", pub_count=3))
        assert node.id == "p1"

    def test_kind(self):
        node = _make_researcher_node(_row(id="p1", given_name="A", surname="B",
                                          degree_code=None, domain_code="DZ01", pub_count=0))
        assert node.kind == KIND_RESEARCHER

    def test_label_full_name(self):
        node = _make_researcher_node(_row(id="p1", given_name="Alice", surname="Smith",
                                          degree_code=None, domain_code="DZ01", pub_count=0))
        assert node.label == "Alice Smith"

    def test_label_given_name_only(self):
        node = _make_researcher_node(_row(id="p1", given_name="Alice", surname=None,
                                          degree_code=None, domain_code=None, pub_count=0))
        assert node.label == "Alice"

    def test_label_falls_back_to_id(self):
        node = _make_researcher_node(_row(id="p1", given_name=None, surname=None,
                                          degree_code=None, domain_code=None, pub_count=0))
        assert node.label == "p1"

    def test_weight_equals_pub_count(self):
        node = _make_researcher_node(_row(id="p1", given_name="A", surname="B",
                                          degree_code=None, domain_code="DZ01", pub_count=7))
        assert node.weight == 7.0

    def test_null_pub_count_defaults_to_zero(self):
        node = _make_researcher_node(_row(id="p1", given_name="A", surname="B",
                                          degree_code=None, domain_code=None, pub_count=None))
        assert node.weight == 0.0
        assert node.data["pub_count"] == 0


class TestMakeInstitutionNode:
    def test_id_and_kind(self):
        node = _make_institution_node(_row(id="inst1", name="Warsaw Univ",
                                           city="Warszawa", voivodeship="maz", total_pubs=10))
        assert node.id == "inst1"
        assert node.kind == KIND_INSTITUTION

    def test_label_is_name(self):
        node = _make_institution_node(_row(id="inst1", name="Warsaw Univ",
                                           city="Warszawa", voivodeship="maz", total_pubs=10))
        assert node.label == "Warsaw Univ"

    def test_weight_is_total_pubs(self):
        node = _make_institution_node(_row(id="inst1", name="X",
                                           city=None, voivodeship=None, total_pubs=42))
        assert node.weight == 42.0

    def test_null_total_pubs_defaults_to_zero(self):
        node = _make_institution_node(_row(id="i1", name="X",
                                           city=None, voivodeship=None, total_pubs=None))
        assert node.weight == 0.0

    def test_data_contains_city_and_voivodeship(self):
        node = _make_institution_node(_row(id="i1", name="X",
                                           city="Kraków", voivodeship="małopolskie", total_pubs=5))
        assert node.data["city"] == "Kraków"
        assert node.data["voivodeship"] == "małopolskie"


class TestMakeSpecialtyNode:
    def test_id_and_kind(self):
        node = _make_specialty_node(_row(id="s1", label="Archeologia",
                                          total_pubs=20, researcher_count=5))
        assert node.id == "s1"
        assert node.kind == KIND_SPECIALTY

    def test_label(self):
        node = _make_specialty_node(_row(id="s1", label="Archeologia",
                                          total_pubs=0, researcher_count=0))
        assert node.label == "Archeologia"

    def test_weight_is_total_pubs(self):
        node = _make_specialty_node(_row(id="s1", label="X",
                                          total_pubs=15, researcher_count=3))
        assert node.weight == 15.0

    def test_data_contains_researcher_count(self):
        node = _make_specialty_node(_row(id="s1", label="X",
                                          total_pubs=0, researcher_count=8))
        assert node.data["researcher_count"] == 8
