from __future__ import annotations

from typing import Any


def evaluate_physics_viability(spec: dict[str, Any]) -> tuple[str, list[str]]:
    notes: list[str] = []

    processes = set(spec.get("processes", []))
    events = int(spec.get("events", 0) or 0)
    e_cm = float(((spec.get("beam") or {}).get("e_cm") or 0.0))

    viability = "good"

    if not processes:
        viability = "non_viable"
        notes.append("No process is enabled.")

    if events <= 0:
        viability = "non_viable"
        notes.append("Events must be > 0.")
    elif events < 1000:
        viability = "caution"
        notes.append("Low event count may produce unstable histogram tails.")

    if e_cm > 0 and e_cm < 100:
        viability = "caution"
        notes.append("Very low collision energy may not match intended LHC-like studies.")

    if "SoftQCD:inelastic" in processes:
        p_that_min = float(((spec.get("phase_space") or {}).get("p_that_min") or 0.0))
        if p_that_min > 5.0:
            viability = "caution"
            notes.append("SoftQCD inelastic usually uses low pTHatMin; high threshold can bias minimum-bias intent.")

    merging = bool(((spec.get("merging") or {}).get("enabled")))
    jet_matching = bool(((spec.get("jet_matching") or {}).get("enabled")))
    if merging and jet_matching:
        viability = "non_viable"
        notes.append("Merging and jet matching are both enabled; policy forbids this combination.")

    if not notes:
        notes.append("No obvious viability risks detected from static checks.")

    return viability, notes
