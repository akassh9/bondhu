from app.v2.workflow_validation import validate_workflow_graph


def test_valid_graph_passes() -> None:
    graph = {
        "nodes": [
            {"id": "n1", "type": "settings_source", "config": {}},
            {"id": "n2", "type": "particle_filter", "config": {"pdg": [13, -13]}},
            {"id": "n3", "type": "histogram_1d", "config": {"field": "pt", "bins": 20, "min": 0.0, "max": 5.0}},
            {"id": "n4", "type": "export", "config": {"format": "json"}},
        ],
        "edges": [
            {"source": "n1", "target": "n2"},
            {"source": "n2", "target": "n3"},
            {"source": "n3", "target": "n4"},
        ],
    }
    errors = validate_workflow_graph(graph)
    assert errors == []


def test_cycle_rejected() -> None:
    graph = {
        "nodes": [
            {"id": "n1", "type": "settings_source", "config": {}},
            {"id": "n2", "type": "particle_filter", "config": {}},
        ],
        "edges": [
            {"source": "n1", "target": "n2"},
            {"source": "n2", "target": "n1"},
        ],
    }
    errors = validate_workflow_graph(graph)
    assert any("acyclic" in err for err in errors)


def test_type_mismatch_rejected() -> None:
    graph = {
        "nodes": [
            {"id": "n1", "type": "settings_source", "config": {}},
            {"id": "n2", "type": "export", "config": {"format": "json"}},
            {"id": "n3", "type": "histogram_1d", "config": {"field": "pt", "bins": 10, "min": 0, "max": 1}},
        ],
        "edges": [
            {"source": "n1", "target": "n2"},
            {"source": "n2", "target": "n3"},
        ],
    }
    errors = validate_workflow_graph(graph)
    assert any("invalid transition" in err for err in errors)
