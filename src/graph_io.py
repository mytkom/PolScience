from __future__ import annotations

import math
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import networkx as nx

from data_loader import Graph, KIND_INSTITUTION, KIND_RESEARCHER, KIND_SPECIALTY

_KIND_COLORS: dict[str, str] = {
    KIND_RESEARCHER: "#4C72B0",
    KIND_INSTITUTION: "#DD8452",
    KIND_SPECIALTY:   "#55A868",
}
_FALLBACK_COLOR = "#8C8C8C"

# 20-color qualitative palette for community detection
_COMMUNITY_PALETTE = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
    "#aec7e8", "#ffbb78", "#98df8a", "#ff9896", "#c5b0d5",
    "#c49c94", "#f7b6d2", "#c7c7c7", "#dbdb8d", "#9edae5",
]


def _community_colors_for(G: nx.Graph, nodes: list[str]) -> list[str]:
    G_und = G.to_undirected() if isinstance(G, nx.DiGraph) else G
    try:
        communities = nx.community.greedy_modularity_communities(G_und)
    except Exception:
        return [_FALLBACK_COLOR] * len(nodes)
    node_to_comm = {n: i for i, comm in enumerate(communities) for n in comm}
    return [_COMMUNITY_PALETTE[node_to_comm.get(n, 0) % len(_COMMUNITY_PALETTE)] for n in nodes]


# ── graph conversion ──────────────────────────────────────────────────────────

def to_networkx(graph: Graph, *, directed: bool = False) -> nx.Graph:
    """
    Convert a Graph to networkx.  All node/edge attributes are preserved,
    so the result is ready for both matplotlib rendering and GEXF export.
    Pass directed=True for the specialty graph (directed co-occurrence edges).
    """
    G: nx.Graph = nx.DiGraph() if directed else nx.Graph()

    for node in graph.nodes.values():
        G.add_node(
            node.id,
            label=node.label,
            kind=node.kind,
            weight=node.weight,
            **{k: v for k, v in node.data.items() if v is not None},
        )

    for edge in graph.edges:
        G.add_edge(
            edge.source,
            edge.target,
            kind=edge.kind,
            weight=edge.weight,
            **{k: v for k, v in edge.data.items() if v is not None},
        )

    return G


# ── plot data preparation (testable without matplotlib) ───────────────────────

@dataclass(frozen=True, slots=True)
class _PlotData:
    pos: dict[str, Any]
    node_ids: list[str]
    node_sizes: list[float]
    node_colors: list[str]
    edges: list[tuple[str, str]]
    edge_widths: list[float]
    labels: dict[str, str]
    node_font_sizes: list[float]


def _compute_layout(G: nx.Graph, layout: str, seed: int) -> dict[str, Any]:
    if layout == "kamada_kawai":
        return nx.kamada_kawai_layout(G, weight="weight")
    if layout == "spectral":
        return nx.spectral_layout(G)
    if layout == "circular":
        return nx.circular_layout(G)
    return nx.spring_layout(G, seed=seed, weight="weight")


# typical ratios for a bold font: width/pt and line-height/pt
_CHAR_WIDTH_RATIO = 0.58
_LINE_HEIGHT_RATIO = 1.35


def _auto_node_size_range(
    pos: dict[str, Any],
    figsize: tuple[int, int],
    target_fill: float = 0.28,
) -> tuple[float, float]:
    """
    Derive (lo, hi) node sizes so nodes fill ~target_fill of the average
    inter-node spacing.  Works by measuring the actual layout bounding box and
    converting data units → display pts (72 pts/inch, ~85 % usable canvas).
    """
    pts = list(pos.values())
    n = len(pts)
    if n < 2:
        return (2000.0, 5000.0)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    dx = (max(xs) - min(xs)) or 1.0
    dy = (max(ys) - min(ys)) or 1.0
    # usable canvas in display pts
    canvas_w = figsize[0] * 72 * 0.85
    canvas_h = figsize[1] * 72 * 0.85
    scale = min(canvas_w / dx, canvas_h / dy)
    # average Voronoi cell side in display pts
    avg_spacing = math.sqrt(dx * dy / n) * scale
    r_base = avg_spacing * target_fill
    size_base = math.pi * r_base ** 2
    return (size_base * 0.65, size_base * 1.35)


def _remove_overlaps(
    pos: dict[str, Any],
    node_ids: list[str],
    node_sizes: list[float],
    display_scale: float,
    iterations: int = 50,
    pad: float = 1.15,
) -> dict[str, Any]:
    """
    Iteratively push overlapping nodes apart in data-coordinate space.

    node_sizes are matplotlib scatter areas (display pts²).
    display_scale is display pts per data unit — used to convert radii into
    data coordinates so the push distances are consistent with the axis.
    """
    radii = [math.sqrt(sz / math.pi) / display_scale * pad for sz in node_sizes]
    pos_m = [[*pos[n]] for n in node_ids]
    n = len(node_ids)
    for _ in range(iterations):
        moved = False
        for i in range(n):
            for j in range(i + 1, n):
                dx = pos_m[i][0] - pos_m[j][0]
                dy = pos_m[i][1] - pos_m[j][1]
                dist2 = dx * dx + dy * dy
                need = radii[i] + radii[j]
                if dist2 < need * need:
                    dist = math.sqrt(dist2) if dist2 > 1e-16 else 1e-8
                    if dist < 1e-8:
                        dx, dy, dist = 1.0, 0.0, 1.0
                    half = (need - dist) * 0.5
                    ux, uy = dx / dist, dy / dist
                    pos_m[i][0] += ux * half
                    pos_m[i][1] += uy * half
                    pos_m[j][0] -= ux * half
                    pos_m[j][1] -= uy * half
                    moved = True
        if not moved:
            break
    return {n: (p[0], p[1]) for n, p in zip(node_ids, pos_m)}


def _fit_font_size(node_size: float, label: str, max_font: float, pad: float = 0.82) -> float:
    """
    Largest font size (pts) so the label's text rectangle fits inside the
    scatter-node circle.  node_size is the matplotlib `s` parameter (area in
    display pts²); font sizes are also in pts, so they share the same unit.

    Derivation: circle radius r = sqrt(s/π).  The text block (W×H) must
    satisfy (W/2)²+(H/2)² ≤ (r·pad)².  With W = max_chars·CWR·fs and
    H = num_lines·LHR·fs, solve for fs.
    """
    r = math.sqrt(node_size / math.pi) * pad
    lines = label.split("\n")
    max_chars = max((len(l) for l in lines), default=1)
    num_lines = len(lines)
    half_diag = math.sqrt((max_chars * _CHAR_WIDTH_RATIO) ** 2 + (num_lines * _LINE_HEIGHT_RATIO) ** 2) / 2
    return min(r / half_diag, max_font)


def _prepare_plot_data(
    G: nx.Graph,
    *,
    layout: str,
    node_size_range: tuple[float, float],
    edge_width_range: tuple[float, float],
    font_size_range: tuple[float, float] = (3.5, 7.0),
    label_nodes: bool,
    max_label_len: int,
    seed: int,
    community_colors: bool = False,
    pos: dict[str, Any] | None = None,
) -> _PlotData:
    if pos is None:
        pos = _compute_layout(G, layout, seed)
    node_ids = list(G.nodes())
    raw_weights = [float(G.nodes[n].get("weight", 1.0)) for n in node_ids]
    node_sizes = _rescale(raw_weights, *node_size_range)
    node_colors = (
        _community_colors_for(G, node_ids)
        if community_colors
        else [_KIND_COLORS.get(G.nodes[n].get("kind", ""), _FALLBACK_COLOR) for n in node_ids]
    )
    edges = list(G.edges())
    edge_widths = (
        _rescale([float(G[u][v].get("weight", 1.0)) for u, v in edges], *edge_width_range)
        if edges else []
    )
    min_font, max_font = font_size_range
    labels: dict[str, str] = {}
    node_font_sizes: list[float] = []
    for n, sz in zip(node_ids, node_sizes):
        if label_nodes:
            wrapped = _wrap_label(str(G.nodes[n].get("label", n)), max_label_len)
            fit_fs = _fit_font_size(sz, wrapped, max_font)
            if fit_fs >= min_font:
                labels[n] = wrapped
            node_font_sizes.append(fit_fs)
        else:
            node_font_sizes.append(min_font)
    return _PlotData(
        pos=pos,
        node_ids=node_ids,
        node_sizes=node_sizes,
        node_colors=node_colors,
        edges=edges,
        edge_widths=edge_widths,
        labels=labels,
        node_font_sizes=node_font_sizes,
    )


# ── public rendering ──────────────────────────────────────────────────────────

def _largest_component(G: nx.Graph) -> nx.Graph:
    if isinstance(G, nx.DiGraph):
        comps = nx.weakly_connected_components(G)
    else:
        comps = nx.connected_components(G)
    largest = max(comps, key=len, default=set())
    return G.subgraph(largest).copy()


def _add_community_legend(
    ax,
    G: nx.Graph,
    node_ids: list[str],
    max_entries: int = 7,
) -> None:
    """Add a legend labelling each community by its highest-degree hub node."""
    G_und = G.to_undirected() if isinstance(G, nx.DiGraph) else G
    try:
        communities = list(nx.community.greedy_modularity_communities(G_und))
    except Exception:
        return
    communities.sort(key=len, reverse=True)
    node_set = set(node_ids)
    handles = []
    for i, comm in enumerate(communities[:max_entries]):
        visible = comm & node_set
        if not visible:
            continue
        hub = max(visible, key=lambda n: G.degree(n))
        hub_label = _truncate(str(G.nodes[hub].get("label", hub)), 22)
        color = _COMMUNITY_PALETTE[i % len(_COMMUNITY_PALETTE)]
        handles.append(mpatches.Patch(
            color=color,
            label=f"{hub_label}  ({len(visible)} nodes)",
        ))
    if handles:
        ax.legend(
            handles=handles, loc="lower left",
            framealpha=0.85, fontsize=8,
            title="Communities (hub node)", title_fontsize=8,
        )


def _label_color(hex_color: str) -> str:
    """White or near-black text for maximum contrast on this background."""
    if not (hex_color.startswith("#") and len(hex_color) == 7):
        return "white"
    r, g, b = int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16)
    return "#111111" if (0.299 * r + 0.587 * g + 0.114 * b) > 140 else "white"


def plot_matplotlib(
    G: nx.Graph,
    *,
    title: str = "",
    figsize: tuple[int, int] = (20, 15),
    layout: str = "kamada_kawai",
    node_size_range: tuple[float, float] | None = None,
    edge_width_range: tuple[float, float] = (0.5, 3.0),
    max_label_len: int = 40,
    font_size_range: tuple[float, float] = (4.0, 12.0),
    seed: int = 42,
    community_colors: bool = True,
    largest_component_only: bool = True,
    max_edges: int | None = None,
) -> plt.Figure:
    """
    Render a networkx graph with matplotlib.  Call to_networkx() first.

    layout: "kamada_kawai" | "spring" | "spectral" | "circular"
    node_size_range: (lo, hi) in display pts²; None = auto-scale to layout density
    max_edges: keep only the top N edges by weight (useful for dense graphs)
    largest_component_only: restrict to the main connected component
    Returns the Figure so the caller can save or show it.
    """
    G = G.copy()

    if max_edges is not None and G.number_of_edges() > max_edges:
        ranked = sorted(G.edges(data=True), key=lambda e: e[2].get("weight", 0.0), reverse=True)
        G.remove_edges_from([(u, v) for u, v, _ in ranked[max_edges:]])

    if largest_component_only and len(G) > 0:
        G = _largest_component(G)

    G.remove_nodes_from(list(nx.isolates(G)))

    fig, ax = plt.subplots(figsize=figsize)
    ax.set_facecolor("#F8F8F8")
    fig.patch.set_facecolor("#F8F8F8")
    ax.set_title(title, fontsize=14, pad=16, fontweight="bold")
    ax.axis("off")

    if len(G) == 0:
        ax.text(0.5, 0.5, "Empty graph", ha="center", va="center", transform=ax.transAxes)
        return fig

    # compute layout once so auto-sizing and overlap removal share it
    pos = _compute_layout(G, layout, seed)
    if node_size_range is None:
        node_size_range = _auto_node_size_range(pos, figsize)

    # push overlapping nodes apart using the node sizes we're about to draw
    _nids = list(G.nodes())
    _raw_w = [float(G.nodes[n].get("weight", 1.0)) for n in _nids]
    _sizes = _rescale(_raw_w, *node_size_range)
    _xs = [pos[n][0] for n in _nids]
    _ys = [pos[n][1] for n in _nids]
    _dx = (max(_xs) - min(_xs)) or 1.0
    _dy = (max(_ys) - min(_ys)) or 1.0
    _dscale = min(figsize[0] * 72 * 0.85 / _dx, figsize[1] * 72 * 0.85 / _dy)
    pos = _remove_overlaps(pos, _nids, _sizes, _dscale)

    d = _prepare_plot_data(
        G,
        layout=layout,
        node_size_range=node_size_range,
        edge_width_range=edge_width_range,
        font_size_range=font_size_range,
        label_nodes=True,
        max_label_len=max_label_len,
        seed=seed,
        community_colors=community_colors,
        pos=pos,
    )

    # axis limits with enough margin for labels that extend past node edges
    xs = [p[0] for p in d.pos.values()]
    ys = [p[1] for p in d.pos.values()]
    xpad = (max(xs) - min(xs)) * 0.14 or 0.8
    ypad = (max(ys) - min(ys)) * 0.14 or 0.8
    ax.set_xlim(min(xs) - xpad, max(xs) + xpad)
    ax.set_ylim(min(ys) - ypad, max(ys) + ypad)

    edge_alpha = max(0.08, min(0.75, 50.0 / max(len(d.edges), 1)))

    nx.draw_networkx_nodes(
        G, d.pos,
        nodelist=d.node_ids,
        node_size=d.node_sizes,
        node_color=d.node_colors,
        ax=ax, alpha=0.92,
        linewidths=0.8, edgecolors="white",
    )

    if d.edges:
        if isinstance(G, nx.DiGraph):
            nx.draw_networkx_edges(
                G, d.pos, edgelist=d.edges, width=d.edge_widths,
                ax=ax, alpha=edge_alpha, arrows=True, arrowstyle="-|>",
                edge_color="#555555",
            )
        else:
            nx.draw_networkx_edges(
                G, d.pos, edgelist=d.edges, width=d.edge_widths,
                ax=ax, alpha=edge_alpha, edge_color="#555555",
            )

    # labels drawn directly on nodes with auto-contrast color and size-scaled font
    color_by_id = dict(zip(d.node_ids, d.node_colors))
    font_by_id = dict(zip(d.node_ids, d.node_font_sizes))
    for node, label in d.labels.items():
        x, y = d.pos[node]
        ax.text(
            x, y, label,
            fontsize=font_by_id.get(node, font_size_range[0]),
            fontweight="bold",
            ha="center", va="center",
            multialignment="center",
            linespacing=1.1,
            color=_label_color(color_by_id.get(node, _FALLBACK_COLOR)),
        )

    if community_colors:
        _add_community_legend(ax, G, d.node_ids)

    fig.tight_layout()
    return fig


def assign_communities(G: nx.Graph) -> nx.Graph:
    """Add 'community' (int) and 'community_name' (hub node label) to every node."""
    G_und = G.to_undirected() if isinstance(G, nx.DiGraph) else G
    try:
        communities = nx.community.greedy_modularity_communities(G_und)
        for i, comm in enumerate(communities):
            hub = max(comm, key=lambda n: G_und.degree(n))
            hub_label = str(G_und.nodes[hub].get("label", hub))
            for node in comm:
                if node in G.nodes:
                    G.nodes[node]["community"] = i
                    G.nodes[node]["community_name"] = hub_label
    except Exception:
        pass
    return G


def to_gephi(G: nx.Graph, path: str | Path) -> None:
    """Export a networkx graph to GEXF format for Gephi.  Call to_networkx() first."""
    nx.write_gexf(G, str(path))


# ── helpers ───────────────────────────────────────────────────────────────────

def _rescale(values: list[float], lo: float, hi: float) -> list[float]:
    vmin = min(values, default=0.0)
    vmax = max(values, default=1.0)
    span = vmax - vmin or 1.0
    return [lo + (v - vmin) / span * (hi - lo) for v in values]


def _truncate(text: str, max_len: int) -> str:
    return text if len(text) <= max_len else text[:max_len] + "…"


def _wrap_label(text: str, max_len: int, wrap_width: int = 15) -> str:
    """Truncate if over max_len, then wrap at word boundaries into multiple lines."""
    if len(text) > max_len:
        text = text[:max_len] + "…"
    lines = textwrap.wrap(text, width=wrap_width)
    return "\n".join(lines) if lines else text
