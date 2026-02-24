from app.v2.viability import evaluate_physics_viability


def test_viability_good_for_default_like_spec() -> None:
    spec = {
        "events": 10000,
        "processes": ["SoftQCD:inelastic"],
        "beam": {"e_cm": 13000},
        "phase_space": {"p_that_min": 0.0},
        "merging": {"enabled": False},
        "jet_matching": {"enabled": False},
    }
    viability, notes = evaluate_physics_viability(spec)
    assert viability in {"good", "caution"}
    assert notes


def test_viability_non_viable_for_conflicting_matching_modes() -> None:
    spec = {
        "events": 10000,
        "processes": ["HardQCD:all"],
        "beam": {"e_cm": 13000},
        "phase_space": {"p_that_min": 20.0},
        "merging": {"enabled": True},
        "jet_matching": {"enabled": True},
    }
    viability, notes = evaluate_physics_viability(spec)
    assert viability == "non_viable"
    assert any("Merging and jet matching" in note for note in notes)
