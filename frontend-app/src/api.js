const API_BASE = window.localStorage.getItem("PYTHIA_API_BASE") || "http://127.0.0.1:8000";

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, options);
  const contentType = response.headers.get("content-type") || "";
  const body = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const message = typeof body === "string" ? body : body.detail || body.error || JSON.stringify(body);
    throw new Error(`HTTP ${response.status}: ${message}`);
  }
  return body;
}

export const api = {
  base: API_BASE,
  health: () => request("/health"),

  createThread: (initialSpec = null) =>
    request("/v2/threads", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ initial_spec: initialSpec }),
    }),

  getThread: (threadId) => request(`/v2/threads/${encodeURIComponent(threadId)}`),

  postThreadMessage: (threadId, message) =>
    request(`/v2/threads/${encodeURIComponent(threadId)}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    }),

  getSetting: (settingId) => request(`/v2/settings/${encodeURIComponent(settingId)}`),

  lockSetting: (settingId) =>
    request(`/v2/settings/${encodeURIComponent(settingId)}/lock`, {
      method: "POST",
    }),

  createWorkflow: ({ settingId, name, graph, schemaVersion = "1.0" }) =>
    request("/v2/workflows", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        setting_id: settingId,
        name,
        schema_version: schemaVersion,
        graph,
      }),
    }),

  getWorkflow: (workflowId) => request(`/v2/workflows/${encodeURIComponent(workflowId)}`),

  validateWorkflow: (workflowId) =>
    request(`/v2/workflows/${encodeURIComponent(workflowId)}/validate`, {
      method: "POST",
    }),

  startWorkflowRun: (workflowId, timeoutSeconds = 3600) =>
    request(`/v2/workflows/${encodeURIComponent(workflowId)}/runs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ timeout_seconds: timeoutSeconds }),
    }),

  getWorkflowRun: (workflowRunId) => request(`/v2/workflow-runs/${encodeURIComponent(workflowRunId)}`),
};
