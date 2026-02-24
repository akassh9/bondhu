from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from ..models import RunSpec


ThreadStatus = Literal["DISCOVERY", "SETTING_DRAFT", "SETTING_READY", "SETTING_LOCKED"]
Viability = Literal["good", "caution", "non_viable", "unknown"]


class ThreadCreateRequest(BaseModel):
    initial_spec: RunSpec | None = None


class MessageCreateRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class MessageResponse(BaseModel):
    role: str
    content: str
    agent_name: str | None = None
    trace_id: str | None = None
    created_at: str


class SettingResponse(BaseModel):
    id: str
    thread_id: str
    runspec: dict[str, Any]
    workflow_intent: dict[str, Any] = Field(default_factory=dict)
    viability: str
    viability_notes: list[str]
    locked_at: str | None
    created_at: str


class ThreadResponse(BaseModel):
    id: str
    status: str
    active_setting_id: str | None
    created_at: str
    updated_at: str
    messages: list[MessageResponse]
    setting: SettingResponse | None = None


class ThreadMessageResponse(BaseModel):
    thread: ThreadResponse
    assistant_message: str
    proposal_summary: str
    setting_state: str
    run_recommended: bool
    trace_id: str | None = None


class SettingLockResponse(BaseModel):
    setting: SettingResponse


class EdgeModel(BaseModel):
    source: str
    target: str


class NodeModel(BaseModel):
    id: str
    type: str
    config: dict[str, Any] = Field(default_factory=dict)


class WorkflowGraphModel(BaseModel):
    nodes: list[NodeModel]
    edges: list[EdgeModel]


class WorkflowCreateRequest(BaseModel):
    setting_id: str
    name: str
    schema_version: str = "1.0"
    graph: WorkflowGraphModel


class WorkflowResponse(BaseModel):
    id: str
    setting_id: str
    name: str
    schema_version: str
    graph: WorkflowGraphModel
    created_at: str
    updated_at: str


class WorkflowValidationResponse(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)


class WorkflowRunCreateRequest(BaseModel):
    timeout_seconds: int = Field(default=3600, ge=60, le=7200)


class NodeRunResponse(BaseModel):
    node_id: str
    node_type: str
    state: str
    output: dict[str, Any]
    artifacts: list[str]


class WorkflowRunResponse(BaseModel):
    id: str
    workflow_id: str
    run_id: str | None
    state: str
    summary: dict[str, Any]
    node_runs: list[NodeRunResponse]
    created_at: str
    updated_at: str
