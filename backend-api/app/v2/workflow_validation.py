from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

ALLOWED_NODE_TYPES = {
    "settings_source",
    "particle_filter",
    "kinematic_cut",
    "event_selection",
    "histogram_1d",
    "histogram_2d",
    "cutflow",
    "yield_estimator",
    "export",
}

ALLOWED_TRANSITIONS = {
    "settings_source": {"particle_filter", "kinematic_cut", "event_selection", "histogram_1d", "histogram_2d", "cutflow", "yield_estimator", "export"},
    "particle_filter": {"kinematic_cut", "event_selection", "histogram_1d", "histogram_2d", "cutflow", "yield_estimator", "export"},
    "kinematic_cut": {"event_selection", "histogram_1d", "histogram_2d", "cutflow", "yield_estimator", "export"},
    "event_selection": {"histogram_1d", "histogram_2d", "cutflow", "yield_estimator", "export"},
    "histogram_1d": {"export"},
    "histogram_2d": {"export"},
    "cutflow": {"export"},
    "yield_estimator": {"export"},
    "export": set(),
}

REQUIRED_CONFIG_KEYS = {
    "particle_filter": set(),
    "kinematic_cut": set(),
    "event_selection": set(),
    "histogram_1d": {"field", "bins", "min", "max"},
    "histogram_2d": {"x_field", "y_field", "x_bins", "x_min", "x_max", "y_bins", "y_min", "y_max"},
    "cutflow": {"cuts"},
    "yield_estimator": {"sigma_mb", "lumi_fb", "branching_ratio"},
    "export": {"format"},
    "settings_source": set(),
}


def validate_workflow_graph(graph: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    nodes = graph.get("nodes")
    edges = graph.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return ["graph must contain list fields: nodes and edges"]

    node_by_id: dict[str, dict[str, Any]] = {}
    for node in nodes:
        if not isinstance(node, dict):
            errors.append("node entries must be objects")
            continue

        node_id = str(node.get("id", "")).strip()
        node_type = str(node.get("type", "")).strip()
        if not node_id:
            errors.append("node missing id")
            continue
        if node_id in node_by_id:
            errors.append(f"duplicate node id: {node_id}")
            continue
        if node_type not in ALLOWED_NODE_TYPES:
            errors.append(f"unsupported node type '{node_type}' for node '{node_id}'")
            continue

        config = node.get("config") or {}
        if not isinstance(config, dict):
            errors.append(f"node '{node_id}' config must be an object")
            continue

        required = REQUIRED_CONFIG_KEYS.get(node_type, set())
        missing = sorted(key for key in required if key not in config)
        if missing:
            errors.append(f"node '{node_id}' missing config keys: {', '.join(missing)}")

        node_by_id[node_id] = {"id": node_id, "type": node_type, "config": config}

    if not node_by_id:
        errors.append("at least one node is required")
        return errors

    settings_nodes = [n for n in node_by_id.values() if n["type"] == "settings_source"]
    if len(settings_nodes) != 1:
        errors.append("graph must contain exactly one settings_source node")

    outgoing: dict[str, list[str]] = defaultdict(list)
    indegree: dict[str, int] = {node_id: 0 for node_id in node_by_id}

    for edge in edges:
        if not isinstance(edge, dict):
            errors.append("edge entries must be objects")
            continue
        source = str(edge.get("source", "")).strip()
        target = str(edge.get("target", "")).strip()

        if source not in node_by_id:
            errors.append(f"edge source '{source}' does not exist")
            continue
        if target not in node_by_id:
            errors.append(f"edge target '{target}' does not exist")
            continue

        src_type = node_by_id[source]["type"]
        dst_type = node_by_id[target]["type"]
        if dst_type not in ALLOWED_TRANSITIONS.get(src_type, set()):
            errors.append(f"edge {source}->{target} invalid transition ({src_type} -> {dst_type})")

        outgoing[source].append(target)
        indegree[target] += 1

    if settings_nodes:
        settings_id = settings_nodes[0]["id"]
        if indegree.get(settings_id, 0) != 0:
            errors.append("settings_source node must not have inbound edges")

    queue = deque([node_id for node_id, deg in indegree.items() if deg == 0])
    visited = 0
    while queue:
        current = queue.popleft()
        visited += 1
        for nxt in outgoing.get(current, []):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)

    if visited != len(node_by_id):
        errors.append("graph must be acyclic (DAG required)")

    return errors


def topological_order(graph: dict[str, Any]) -> list[str]:
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    node_ids = [str(node["id"]) for node in nodes]

    outgoing: dict[str, list[str]] = defaultdict(list)
    indegree: dict[str, int] = {node_id: 0 for node_id in node_ids}

    for edge in edges:
        source = str(edge["source"])
        target = str(edge["target"])
        outgoing[source].append(target)
        indegree[target] += 1

    queue = deque([node_id for node_id, deg in indegree.items() if deg == 0])
    order: list[str] = []
    while queue:
        current = queue.popleft()
        order.append(current)
        for nxt in outgoing.get(current, []):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)

    return order
