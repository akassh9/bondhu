from __future__ import annotations

import re

from .models import RunSpec

_OVERRIDE_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9]+:[A-Za-z0-9]+|-?\d+:[A-Za-z0-9]+)\s*=\s*(.+?)\s*$")

_ALLOWED_EXPERT_FAMILIES = {
    "Beams",
    "PhaseSpace",
    "ProcessLevel",
    "PartonLevel",
    "HadronLevel",
    "SpaceShower",
    "TimeShower",
    "MultipartonInteractions",
    "Tune",
    "PDF",
    "PhotonParton",
    "Merging",
    "JetMatching",
    "HardQCD",
    "SoftQCD",
    "WeakSingleBoson",
    "Top",
    "HiggsSM",
}

_PROTECTED_KEYS = {
    "Main:numberOfEvents",
    "Main:timesAllowErrors",
    "Random:setSeed",
    "Random:seed",
    "Beams:frameType",
    "Beams:idA",
    "Beams:idB",
    "Beams:eCM",
    "Beams:eA",
    "Beams:eB",
    "Beams:LHEF",
}


class PolicyViolation(ValueError):
    pass


def validate_policy(spec: RunSpec) -> None:
    if spec.seed_enabled and spec.seed <= 0:
        raise PolicyViolation("seed must be > 0 when seed_enabled=true")

    if spec.merging.enabled and spec.jet_matching.enabled:
        # Not universally invalid in PYTHIA, but too risky for this first guarded API.
        raise PolicyViolation("enable either merging or jet matching, not both in one run")

    if spec.events > 250_000 and spec.merging.enabled:
        raise PolicyViolation("events too high for merging-enabled run (max 250000)")

    for line in spec.expert_overrides:
        if line.startswith("!"):
            continue

        match = _OVERRIDE_RE.match(line)
        if not match:
            raise PolicyViolation(f"invalid expert override format: '{line}'")

        key = match.group(1)
        if key in _PROTECTED_KEYS:
            raise PolicyViolation(f"expert override modifies protected key '{key}'")

        if ":" in key and not key[0].isdigit() and not key.startswith("-"):
            family = key.split(":", 1)[0]
            if family not in _ALLOWED_EXPERT_FAMILIES:
                raise PolicyViolation(f"expert override family '{family}' is not allowed")

        value = match.group(2).strip()
        if len(value) > 240:
            raise PolicyViolation(f"expert override value too long for key '{key}'")
