from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

SCHEMA_VERSION = "1.0"
MAX_EVENTS = 1_000_000
MAX_TIMES_ALLOW_ERRORS = 100
MAX_EXPERT_OVERRIDES = 200
MAX_EXPERT_LINE_LEN = 300

PROCESS_KEYS = {
    "HardQCD:all",
    "SoftQCD:all",
    "SoftQCD:nonDiffractive",
    "SoftQCD:inelastic",
    "WeakSingleBoson:ffbar2gmZ",
    "WeakSingleBoson:ffbar2W",
    "Top:gg2ttbar",
    "Top:qqbar2ttbar",
    "HiggsSM:ffbar2HW",
}

PDG_OVERRIDE_KEYS = {
    "onMode",
    "onIfAny",
    "addChannel",
    "mayDecay",
    "m0",
    "mMin",
    "mMax",
    "mWidth",
}


class BeamSpec(BaseModel):
    frame_type: Literal[1, 2, 3, 4, 5] = 1
    id_a: int = 2212
    id_b: int = 2212
    e_cm: float | None = 13000.0
    e_a: float | None = 6500.0
    e_b: float | None = 6500.0
    lhef: str | None = None

    @model_validator(mode="after")
    def validate_frame_requirements(self) -> "BeamSpec":
        if self.frame_type == 4:
            if not self.lhef or not self.lhef.strip():
                raise ValueError("beam.lhef is required when frame_type=4")
        elif self.frame_type == 2:
            if self.e_a is None or self.e_b is None:
                raise ValueError("beam.e_a and beam.e_b are required when frame_type=2")
        else:
            if self.e_cm is None:
                raise ValueError("beam.e_cm is required when frame_type is not 2 or 4")
        return self


class PhaseSpaceSpec(BaseModel):
    p_that_min: float = Field(default=20.0, ge=0)
    p_that_max: float | None = Field(default=None, ge=0)
    m_hat_min: float | None = Field(default=None, ge=0)
    m_hat_max: float | None = Field(default=None, ge=0)


class EventStagesSpec(BaseModel):
    process_level_all: bool = True
    mpi: bool = True
    isr: bool = True
    fsr: bool = True
    hadron_all: bool = True
    hadronize: bool = True
    decay: bool = True


class ShowerMpiTuneSpec(BaseModel):
    space_ptmax_match: int = Field(default=1, ge=0, le=3)
    time_ptmax_match: int = Field(default=1, ge=0, le=3)
    mpi_pt0_ref: float = Field(default=2.3, ge=0)
    mpi_b_profile: int = Field(default=2, ge=0, le=5)
    tune_pp: int = Field(default=14, ge=0, le=30)
    tune_ee: int = Field(default=7, ge=0, le=30)


class PdfPhotonSpec(BaseModel):
    p_set: int = Field(default=14, ge=1)
    lepton: bool = False
    beam_a2gamma: bool = False
    beam_b2gamma: bool = False
    use_hard: bool = False
    photon_parton_all: bool = False


class PdgOverride(BaseModel):
    pdg: int
    key: str
    value: str

    @field_validator("key")
    @classmethod
    def validate_key(cls, value: str) -> str:
        if value not in PDG_OVERRIDE_KEYS:
            allowed = ", ".join(sorted(PDG_OVERRIDE_KEYS))
            raise ValueError(f"invalid PDG override key '{value}', allowed: {allowed}")
        return value

    @field_validator("value")
    @classmethod
    def validate_value(cls, value: str) -> str:
        v = value.strip()
        if not v:
            raise ValueError("PDG override value must be non-empty")
        return v


class MergingSpec(BaseModel):
    enabled: bool = False
    process: str = "pp>jj"
    tms: float = Field(default=30.0, ge=0)
    n_jet_max: int = Field(default=2, ge=0)


class JetMatchingSpec(BaseModel):
    enabled: bool = False
    q_cut: float = Field(default=30.0, ge=0)


class RunSpec(BaseModel):
    schema_version: Literal[SCHEMA_VERSION] = SCHEMA_VERSION
    name: str | None = None

    events: int = Field(default=10_000, ge=1, le=MAX_EVENTS)
    times_allow_errors: int = Field(default=10, ge=0, le=MAX_TIMES_ALLOW_ERRORS)

    seed_enabled: bool = True
    seed: int = Field(default=8310, ge=1, le=900_000_000)

    beam: BeamSpec = Field(default_factory=BeamSpec)
    processes: list[str] = Field(default_factory=lambda: ["SoftQCD:inelastic"])

    phase_space: PhaseSpaceSpec = Field(default_factory=PhaseSpaceSpec)
    event_stages: EventStagesSpec = Field(default_factory=EventStagesSpec)
    shower_mpi_tune: ShowerMpiTuneSpec = Field(default_factory=ShowerMpiTuneSpec)
    pdf_photon: PdfPhotonSpec = Field(default_factory=PdfPhotonSpec)

    pdg_overrides: list[PdgOverride] = Field(default_factory=list)
    expert_overrides: list[str] = Field(default_factory=list)

    merging: MergingSpec = Field(default_factory=MergingSpec)
    jet_matching: JetMatchingSpec = Field(default_factory=JetMatchingSpec)

    @field_validator("processes")
    @classmethod
    def validate_processes(cls, value: list[str]) -> list[str]:
        cleaned = sorted({v.strip() for v in value if v and v.strip()})
        if not cleaned:
            raise ValueError("at least one process key must be enabled")
        unknown = [v for v in cleaned if v not in PROCESS_KEYS]
        if unknown:
            raise ValueError(f"unknown process keys: {', '.join(unknown)}")
        return cleaned

    @field_validator("expert_overrides", mode="before")
    @classmethod
    def normalize_expert_overrides(cls, value: object) -> list[str]:
        if value is None:
            return []

        if isinstance(value, str):
            rows = [line.strip() for line in value.splitlines()]
            return [line for line in rows if line]

        if isinstance(value, list):
            normalized: list[str] = []
            for line in value:
                if line is None:
                    continue
                s = str(line).strip()
                if s:
                    normalized.append(s)
            return normalized

        raise TypeError("expert_overrides must be a string or list of strings")

    @field_validator("expert_overrides")
    @classmethod
    def validate_expert_overrides(cls, value: list[str]) -> list[str]:
        if len(value) > MAX_EXPERT_OVERRIDES:
            raise ValueError(f"too many expert overrides (max {MAX_EXPERT_OVERRIDES})")

        for line in value:
            if len(line) > MAX_EXPERT_LINE_LEN:
                raise ValueError(
                    f"expert override line exceeds max length {MAX_EXPERT_LINE_LEN}: {line[:40]}..."
                )
        return value


class RunSpecEnvelope(BaseModel):
    spec: RunSpec


class CreateRunRequest(BaseModel):
    spec: RunSpec
    auto_enqueue: bool = True


class CompileResponse(BaseModel):
    cmnd_text: str
    lines: list[str]


class StatusResponse(BaseModel):
    run_id: str
    state: str
    created_at: str
    updated_at: str
    message: str | None = None
    error: str | None = None


class ArtifactResponse(BaseModel):
    name: str
    size_bytes: int


class ChatCreateSessionRequest(BaseModel):
    initial_spec: RunSpec | None = None


class ChatMessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class ChatRunRequest(BaseModel):
    source: Literal["working", "proposed"] = "working"
