const byId = (id) => document.getElementById(id);

const API_BASE = window.localStorage.getItem("PYTHIA_API_BASE") || "http://127.0.0.1:8000";
const POLL_INTERVAL_MS = 1500;
const POLL_TIMEOUT_MS = 10 * 60 * 1000;

let sessionId = null;
let proposedSpec = null;
let runInFlight = false;

const dom = {
  backendChip: byId("backendChip"),
  sessionChip: byId("sessionChip"),
  chatFeed: byId("chatFeed"),
  chatInput: byId("chatInput"),
  sendChat: byId("sendChat"),
  newSession: byId("newSession"),
  proposalSummary: byId("proposalSummary"),
  proposalDiff: byId("proposalDiff"),
  applyProposal: byId("applyProposal"),
  runProposed: byId("runProposed"),
  runWorking: byId("runWorking"),
  refreshState: byId("refreshState"),
  workingPreview: byId("workingPreview"),
  runResult: byId("runResult"),
  recentRuns: byId("recentRuns")
};

function setButtons() {
  const hasProposed = !!proposedSpec;
  dom.applyProposal.disabled = !hasProposed || runInFlight;
  dom.runProposed.disabled = !hasProposed || runInFlight;
  dom.runWorking.disabled = runInFlight;
  dom.sendChat.disabled = runInFlight;
}

function appendMessage(role, text) {
  const el = document.createElement("div");
  el.className = `msg ${role}`;
  el.textContent = text;
  dom.chatFeed.appendChild(el);
  dom.chatFeed.scrollTop = dom.chatFeed.scrollHeight;
}

async function apiRequest(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, options);
  const contentType = response.headers.get("content-type") || "";
  const body = contentType.includes("application/json") ? await response.json() : await response.text();

  if (!response.ok) {
    if (typeof body === "string") {
      throw new Error(`HTTP ${response.status}: ${body}`);
    }
    const detail = body.detail || body.error || JSON.stringify(body);
    throw new Error(`HTTP ${response.status}: ${detail}`);
  }

  return body;
}

async function compileSpecToPreview(spec) {
  const payload = await apiRequest("/runspec/compile", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ spec })
  });
  return payload.cmnd_text || "";
}

function renderRunResultText(lines) {
  dom.runResult.textContent = lines.join("\n");
}

function renderRunResultWithArtifacts(runId, status, artifacts) {
  dom.runResult.innerHTML = "";
  const teammate = status.teammate_summary || null;
  const llm = status.llm_run_summary || null;

  const lines = [
    `Run ID: ${runId}`,
    `State: ${status.state}`,
    status.message ? `Message: ${status.message}` : null,
    status.event_summary ? `Attempted: ${status.event_summary.attempted_events}` : null,
    status.event_summary ? `Accepted: ${status.event_summary.accepted_events}` : null,
    status.analysis ? `Analysis: ${status.analysis.plugin}` : null,
  ].filter(Boolean);

  lines.forEach((line) => {
    const row = document.createElement("div");
    row.textContent = line;
    dom.runResult.appendChild(row);
  });

  if (teammate) {
    const head = document.createElement("div");
    head.style.marginTop = "8px";
    head.style.fontWeight = "600";
    head.textContent = `Teammate TLDR (${teammate.viability || "unknown"}):`;
    dom.runResult.appendChild(head);

    const tldr = document.createElement("div");
    tldr.textContent = teammate.tldr || "No summary.";
    dom.runResult.appendChild(tldr);

    const flags = teammate.flags || [];
    flags.forEach((flag) => {
      const row = document.createElement("div");
      row.textContent = `- ${flag}`;
      dom.runResult.appendChild(row);
    });

    const suggestions = teammate.suggestions || [];
    suggestions.forEach((step) => {
      const row = document.createElement("div");
      row.textContent = `- ${step}`;
      dom.runResult.appendChild(row);
    });
  }

  if (llm) {
    const head = document.createElement("div");
    head.style.marginTop = "8px";
    head.style.fontWeight = "600";
    head.textContent = "LLM TLDR:";
    dom.runResult.appendChild(head);

    const line = document.createElement("div");
    line.textContent = llm.tldr || "No LLM summary.";
    dom.runResult.appendChild(line);
  }

  if (!artifacts.length) return;

  const header = document.createElement("div");
  header.style.marginTop = "8px";
  header.style.fontWeight = "600";
  header.textContent = "Artifacts:";
  dom.runResult.appendChild(header);

  artifacts.forEach((artifact) => {
    const row = document.createElement("div");
    const link = document.createElement("a");
    link.href = `${API_BASE}/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(artifact.name)}`;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = `${artifact.name} (${artifact.size_bytes} bytes)`;
    row.appendChild(link);
    dom.runResult.appendChild(row);
  });
}

async function pollRunUntilDone(runId) {
  const start = Date.now();

  while (true) {
    const status = await apiRequest(`/runs/${encodeURIComponent(runId)}/status`);
    renderRunResultText([
      `Run ID: ${runId}`,
      `State: ${status.state}`,
      status.message ? `Message: ${status.message}` : "",
    ]);

    if (status.state === "SUCCEEDED" || status.state === "FAILED") {
      return status;
    }

    if (Date.now() - start > POLL_TIMEOUT_MS) {
      throw new Error("Run polling timed out");
    }

    await new Promise((resolve) => window.setTimeout(resolve, POLL_INTERVAL_MS));
  }
}

async function loadRecentRuns() {
  try {
    const payload = await apiRequest("/runs?limit=10");
    const runs = payload.runs || [];
    dom.recentRuns.innerHTML = "";

    if (!runs.length) {
      dom.recentRuns.textContent = "No runs found.";
      return;
    }

    runs.forEach((run) => {
      const row = document.createElement("div");
      row.className = "history-row";
      row.innerHTML = `<div>${run.run_id} [${run.state}]</div><div class="meta">${run.updated_at || run.created_at || ""}</div>`;
      row.addEventListener("click", async () => {
        const status = await apiRequest(`/runs/${encodeURIComponent(run.run_id)}/status`);
        const arts = await apiRequest(`/runs/${encodeURIComponent(run.run_id)}/artifacts`);
        renderRunResultWithArtifacts(run.run_id, status, arts.artifacts || []);
      });
      dom.recentRuns.appendChild(row);
    });
  } catch (err) {
    dom.recentRuns.textContent = `Failed to load runs: ${String(err.message || err)}`;
  }
}

async function renderSession(state, transient = null) {
  sessionId = state.session_id;
  dom.sessionChip.textContent = `Session: ${sessionId}`;

  const messages = state.messages || [];
  dom.chatFeed.innerHTML = "";
  if (!messages.length) {
    appendMessage("system", "Session started. Ask what run to build.");
  } else {
    messages.forEach((msg) => {
      const role = msg.role === "assistant" ? "assistant" : msg.role === "user" ? "user" : "system";
      appendMessage(role, msg.content || "");
    });
  }

  proposedSpec = state.proposed_spec || null;

  if (proposedSpec) {
    dom.proposalSummary.textContent = "Model proposed changes. Review diff then Apply or Run Proposed.";
    dom.proposalDiff.textContent = (state.proposed_diff || ["No diff available"]).join("\n");
  } else {
    if (transient && transient.proposalSummary) {
      dom.proposalSummary.textContent = transient.proposalSummary;
      dom.proposalDiff.textContent = transient.validationError
        ? `No proposal generated.\n${transient.validationError}`
        : "No proposal generated for this message.";
    } else {
      dom.proposalSummary.textContent = "No active proposal.";
      dom.proposalDiff.textContent = "No proposal yet.";
    }
  }

  try {
    dom.workingPreview.textContent = await compileSpecToPreview(state.working_spec);
  } catch (err) {
    dom.workingPreview.textContent = `Failed to compile working spec preview: ${String(err.message || err)}`;
  }

  setButtons();
}

async function createSession() {
  const state = await apiRequest("/chat/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({})
  });
  await renderSession(state);
}

async function refreshSession() {
  if (!sessionId) return;
  const state = await apiRequest(`/chat/sessions/${encodeURIComponent(sessionId)}`);
  await renderSession(state);
}

async function sendMessage() {
  const text = dom.chatInput.value.trim();
  if (!text || !sessionId || runInFlight) return;

  runInFlight = true;
  setButtons();
  dom.chatInput.value = "";

  try {
    appendMessage("user", text);

    const payload = await apiRequest(`/chat/sessions/${encodeURIComponent(sessionId)}/message`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text })
    });

    appendMessage("assistant", payload.assistant_message || "");

    if (payload.validation_error) {
      appendMessage("system", `Proposal validation failed: ${payload.validation_error}`);
    }

    await renderSession(payload.session, {
      proposalSummary: payload.proposal_summary || "",
      validationError: payload.validation_error || "",
    });
    await loadRecentRuns();
  } catch (err) {
    appendMessage("system", `Chat error: ${String(err.message || err)}`);
  } finally {
    runInFlight = false;
    setButtons();
  }
}

async function applyProposal() {
  if (!sessionId || runInFlight) return;
  runInFlight = true;
  setButtons();

  try {
    const payload = await apiRequest(`/chat/sessions/${encodeURIComponent(sessionId)}/apply`, {
      method: "POST"
    });
    await renderSession(payload.session);
    appendMessage("system", "Applied proposed spec to working spec.");
  } catch (err) {
    appendMessage("system", `Apply failed: ${String(err.message || err)}`);
  } finally {
    runInFlight = false;
    setButtons();
  }
}

async function runFromSession(source) {
  if (!sessionId || runInFlight) return;
  runInFlight = true;
  setButtons();
  renderRunResultText([`Starting run from ${source} spec...`]);

  try {
    const payload = await apiRequest(`/chat/sessions/${encodeURIComponent(sessionId)}/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source })
    });

    const runId = payload.run_id;
    const finalStatus = await pollRunUntilDone(runId);
    const arts = await apiRequest(`/runs/${encodeURIComponent(runId)}/artifacts`);
    renderRunResultWithArtifacts(runId, finalStatus, arts.artifacts || []);

    await renderSession(payload.session);
    await loadRecentRuns();
  } catch (err) {
    renderRunResultText(["Run failed to start.", String(err.message || err)]);
  } finally {
    runInFlight = false;
    setButtons();
  }
}

async function checkBackend() {
  try {
    await apiRequest("/health");
    dom.backendChip.textContent = "Backend: Connected";
    return true;
  } catch (_err) {
    dom.backendChip.textContent = "Backend: Offline";
    return false;
  }
}

function bindEvents() {
  dom.sendChat.addEventListener("click", () => {
    sendMessage();
  });

  dom.chatInput.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      sendMessage();
    }
  });

  dom.newSession.addEventListener("click", () => {
    createSession().catch((err) => {
      appendMessage("system", `Failed to create new session: ${String(err.message || err)}`);
    });
  });

  dom.applyProposal.addEventListener("click", () => {
    applyProposal();
  });

  dom.runProposed.addEventListener("click", () => {
    runFromSession("proposed");
  });

  dom.runWorking.addEventListener("click", () => {
    runFromSession("working");
  });

  dom.refreshState.addEventListener("click", () => {
    refreshSession().catch((err) => {
      appendMessage("system", `Refresh failed: ${String(err.message || err)}`);
    });
  });
}

async function init() {
  bindEvents();
  const ok = await checkBackend();
  if (!ok) {
    appendMessage("system", "Backend is offline. Start API server and refresh.");
    return;
  }

  await createSession();
  await loadRecentRuns();
}

init();
