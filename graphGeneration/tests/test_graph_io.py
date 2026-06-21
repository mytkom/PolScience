from __future__ import annotations

import matplotlib
matplotlib.use("Agg")  # must be set before any other matplotlib import

from pathlib import Path

import matplotlib.pyplot as plt
import networkx as nx
import pytest

from data_loader import (
    EDGE_CO_AUTHORSHIP,
    KIND_INSTITUTION,
    KIND_RESEARCHER,
    KIND_SPECIALTY,
    Graph,
    GraphEdge,
    GraphNode,
)
from graph_io import (
    _PlotData,
    _compute_layout,
    _prepare_plot_data,
    _rescale,
    _truncate,
    plot_matplotlib,
    to_gephi,
    to_networkx,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def small_graph() -> Graph:
    return Graph(
        nodes={
            "a": GraphNode("a", KIND_RESEARCHER, "Alice", 5.0,
                           {"pub_count": 5, "domain_code": "DZ01", "degree_code": None}),
            "b": GraphNode("b", KIND_RESEARCHER, "Bob", 3.0,
                           {"pub_count": 3, "domain_code": "DZ01", "degree_code": None}),
        },
        edges=[GraphEdge("a", "b", EDGE_CO_AUTHORSHIP, 2.0, {"shared_pubs": 2})],
    )


@pytest.fixture()
def small_nx(small_graph) -> nx.Graph:
    return to_networkx(small_graph)


@pytest.fixture()
def small_digraph() -> nx.DiGraph:
    G = nx.DiGraph()
    G.add_node("s1", label="Spec 1", kind=KIND_SPECIALTY, weight=10.0)
    G.add_node("s2", label="Spec 2", kind=KIND_SPECIALTY, weight=5.0)
    G.add_edge("s1", "s2", weight=50.0, kind="specialty_co_occurrence")
    return G


# ── _rescale ──────────────────────────────────────────────────────────────────

class TestRescale:
    def test_maps_min_to_lo_and_max_to_hi(self):
        assert _rescale([0.0, 5.0, 10.0], 100.0, 200.0) == pytest.approx([100.0, 150.0, 200.0])

    def test_single_value_gets_lo(self):
        assert _rescale([7.0], 100.0, 200.0) == pytest.approx([100.0])

    def test_all_equal_values_get_lo(self):
        assert _rescale([3.0, 3.0, 3.0], 100.0, 200.0) == pytest.approx([100.0, 100.0, 100.0])

    def test_preserves_relative_order(self):
        result = _rescale([1.0, 2.0, 3.0], 0.0, 1.0)
        assert result[0] < result[1] < result[2]


# ── _truncate ─────────────────────────────────────────────────────────────────

class TestTruncate:
    def test_short_string_unchanged(self):
        assert _truncate("hello", 10) == "hello"

    def test_exact_length_unchanged(self):
        assert _truncate("hello", 5) == "hello"

    def test_long_string_truncated_with_ellipsis(self):
        result = _truncate("hello world", 5)
        assert result == "hello…"
        assert len(result) == 6  # 5 chars + ellipsis character


# ── to_networkx ───────────────────────────────────────────────────────────────

class TestToNetworkx:
    def test_returns_undirected_graph_by_default(self, small_graph):
        G = to_networkx(small_graph)
        assert isinstance(G, nx.Graph)
        assert not isinstance(G, nx.DiGraph)

    def test_returns_digraph_when_directed(self, small_graph):
        G = to_networkx(small_graph, directed=True)
        assert isinstance(G, nx.DiGraph)

    def test_node_ids_preserved(self, small_graph):
        G = to_networkx(small_graph)
        assert set(G.nodes()) == {"a", "b"}

    def test_node_label_attribute(self, small_graph):
        G = to_networkx(small_graph)
        assert G.nodes["a"]["label"] == "Alice"
        assert G.nodes["b"]["label"] == "Bob"

    def test_node_weight_attribute(self, small_graph):
        G = to_networkx(small_graph)
        assert G.nodes["a"]["weight"] == 5.0

    def test_node_kind_attribute(self, small_graph):
        G = to_networkx(small_graph)
        assert G.nodes["a"]["kind"] == KIND_RESEARCHER

    def test_edge_exists(self, small_graph):
        G = to_networkx(small_graph)
        assert G.has_edge("a", "b")

    def test_edge_weight_attribute(self, small_graph):
        G = to_networkx(small_graph)
        assert G["a"]["b"]["weight"] == 2.0

    def test_none_data_values_excluded(self):
        g = Graph(
            nodes={"x": GraphNode("x", KIND_RESEARCHER, "X", 1.0,
                                  {"degree_code": None, "domain_code": "DZ01"})},
            edges=[],
        )
        G = to_networkx(g)
        assert "degree_code" not in G.nodes["x"]
        assert G.nodes["x"]["domain_code"] == "DZ01"

    def test_empty_graph(self):
        G = to_networkx(Graph(nodes={}, edges=[]))
        assert len(G) == 0


# ── _compute_layout ───────────────────────────────────────────────────────────

class TestComputeLayout:
    def test_spring_returns_position_for_every_node(self, small_nx):
        pos = _compute_layout(small_nx, "spring", seed=42)
        assert set(pos.keys()) == set(small_nx.nodes())

    def test_circular_returns_position_for_every_node(self, small_nx):
        pos = _compute_layout(small_nx, "circular", seed=42)
        assert set(pos.keys()) == set(small_nx.nodes())

    def test_spectral_returns_position_for_every_node(self, small_nx):
        pos = _compute_layout(small_nx, "spectral", seed=42)
        assert set(pos.keys()) == set(small_nx.nodes())

    def test_unknown_layout_defaults_to_spring(self, small_nx):
        pos = _compute_layout(small_nx, "nonexistent", seed=42)
        assert set(pos.keys()) == set(small_nx.nodes())

    def test_positions_are_2d(self, small_nx):
        pos = _compute_layout(small_nx, "spring", seed=42)
        assert all(len(coords) == 2 for coords in pos.values())


# ── _prepare_plot_data ────────────────────────────────────────────────────────

_PREP_DEFAULTS = dict(
    layout="circular",
    node_size_range=(100.0, 200.0),
    edge_width_range=(1.0, 3.0),
    label_nodes=True,
    max_label_len=20,
    seed=42,
)


class TestPreparePlotData:
    def test_returns_plotdata(self, small_nx):
        d = _prepare_plot_data(small_nx, **_PREP_DEFAULTS)
        assert isinstance(d, _PlotData)

    def test_node_count(self, small_nx):
        d = _prepare_plot_data(small_nx, **_PREP_DEFAULTS)
        assert len(d.node_ids) == 2
        assert len(d.node_sizes) == 2
        assert len(d.node_colors) == 2

    def test_node_sizes_in_range(self, small_nx):
        d = _prepare_plot_data(small_nx, **_PREP_DEFAULTS)
        assert all(100.0 <= s <= 200.0 for s in d.node_sizes)

    def test_heavier_node_gets_larger_size(self, small_nx):
        # "a" weight=5.0 > "b" weight=3.0
        d = _prepare_plot_data(small_nx, **_PREP_DEFAULTS)
        idx_a = d.node_ids.index("a")
        idx_b = d.node_ids.index("b")
        assert d.node_sizes[idx_a] > d.node_sizes[idx_b]

    def test_node_colors_use_kind(self, small_nx):
        d = _prepare_plot_data(small_nx, **_PREP_DEFAULTS)
        assert all(c == "#4C72B0" for c in d.node_colors)  # KIND_RESEARCHER color

    def test_unknown_kind_uses_fallback_color(self):
        G = nx.Graph()
        G.add_node("x", label="X", kind="unknown_kind", weight=1.0)
        d = _prepare_plot_data(G, **_PREP_DEFAULTS)
        assert d.node_colors[0] == "#8C8C8C"

    def test_edge_count(self, small_nx):
        d = _prepare_plot_data(small_nx, **_PREP_DEFAULTS)
        assert len(d.edges) == 1
        assert len(d.edge_widths) == 1

    def test_no_edges_gives_empty_lists(self):
        G = nx.Graph()
        G.add_node("a", label="A", kind=KIND_RESEARCHER, weight=1.0)
        d = _prepare_plot_data(G, **_PREP_DEFAULTS)
        assert d.edges == []
        assert d.edge_widths == []

    def test_labels_present_when_enabled(self, small_nx):
        d = _prepare_plot_data(small_nx, **_PREP_DEFAULTS)
        assert "a" in d.labels
        assert d.labels["a"] == "Alice"

    def test_labels_empty_when_disabled(self, small_nx):
        d = _prepare_plot_data(small_nx, **{**_PREP_DEFAULTS, "label_nodes": False})
        assert d.labels == {}

    def test_long_labels_truncated(self, small_nx):
        d = _prepare_plot_data(small_nx, **{**_PREP_DEFAULTS, "max_label_len": 3})
        assert all(len(lbl) <= 4 for lbl in d.labels.values())  # 3 chars + ellipsis


# ── plot_matplotlib ───────────────────────────────────────────────────────────

class TestPlotMatplotlib:
    def test_returns_figure(self, small_nx):
        fig = plot_matplotlib(small_nx)
        assert isinstance(fig, plt.Figure)
        plt.close(fig)

    def test_empty_graph_returns_figure(self):
        fig = plot_matplotlib(nx.Graph())
        assert isinstance(fig, plt.Figure)
        plt.close(fig)

    def test_directed_graph_accepted(self, small_digraph):
        fig = plot_matplotlib(small_digraph)
        assert isinstance(fig, plt.Figure)
        plt.close(fig)

    def test_title_set(self, small_nx):
        fig = plot_matplotlib(small_nx, title="My Graph")
        assert fig.axes[0].get_title() == "My Graph"
        plt.close(fig)


# ── to_gephi ──────────────────────────────────────────────────────────────────

class TestToGephi:
    def test_writes_file(self, small_nx, tmp_path):
        path = tmp_path / "out.gexf"
        to_gephi(small_nx, path)
        assert path.exists()
        assert path.stat().st_size > 0

    def test_file_contains_node_labels(self, small_nx, tmp_path):
        path = tmp_path / "out.gexf"
        to_gephi(small_nx, path)
        content = path.read_text()
        assert "Alice" in content
        assert "Bob" in content

    def test_accepts_string_path(self, small_nx, tmp_path):
        path = str(tmp_path / "out.gexf")
        to_gephi(small_nx, path)
        assert Path(path).exists()

    def test_directed_graph_written(self, small_digraph, tmp_path):
        path = tmp_path / "directed.gexf"
        to_gephi(small_digraph, path)
        assert path.exists()
