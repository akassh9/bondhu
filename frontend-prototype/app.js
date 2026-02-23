const byId = (id) => document.getElementById(id);

const API_BASE = window.localStorage.getItem("PYTHIA_API_BASE") || "http://127.0.0.1:8000";
const POLL_INTERVAL_MS = 1500;
const POLL_TIMEOUT_MS = 10 * 60 * 1000;
const MAX_DIFF_LINES = 80;

let approvedSpec = null;
let approvedAt = null;
let runInProgress = false;

const dom = {
  events: byId("events"),
  timesAllowErrors: byId("timesAllowErrors"),
  seedEnabled: byId("seedEnabled"),
  seed: byId("seed"),
  frameType: byId("frameType"),
  eCM: byId("eCM"),
  eCMOut: byId("eCMOut"),
  idA: byId("idA"),
  idB: byId("idB"),
  eA: byId("eA"),
  eB: byId("eB"),
  lhef: byId("lhef"),
  pTHatMin: byId("pTHatMin"),
  pTHatMax: byId("pTHatMax"),
  mHatMin: byId("mHatMin"),
  mHatMax: byId("mHatMax"),
  processLevelAll: byId("processLevelAll"),
  mpi: byId("mpi"),
  isr: byId("isr"),
  fsr: byId("fsr"),
  hadronAll: byId("hadronAll"),
  hadronize: byId("hadronize"),
  decay: byId("decay"),
  spacePTMaxMatch: byId("spacePTMaxMatch"),
  timePTMaxMatch: byId("timePTMaxMatch"),
  pT0Ref: byId("pT0Ref"),
  bProfile: byId("bProfile"),
  tunepp: byId("tunepp"),
  tuneee: byId("tuneee"),
  pSet: byId("pSet"),
  pdfLepton: byId("pdfLepton"),
  beamA2gamma: byId("beamA2gamma"),
  beamB2gamma: byId("beamB2gamma"),
  useHardPdf: byId("useHardPdf"),
  photonPartonAll: byId("photonPartonAll"),
  mergingOn: byId("mergingOn"),
  jetMatchingOn: byId("jetMatchingOn"),
  mergingProcess: byId("mergingProcess"),
  mergingTMS: byId("mergingTMS"),
  mergingNJetMax: byId("mergingNJetMax"),
  jetQCut: byId("jetQCut"),
  rawOverrides: byId("rawOverrides"),
  commandPreview: byId("commandPreview"),
  copyPreview: byId("copyPreview"),
  simulateRun: byId("simulateRun"),
  runSummary: byId("runSummary"),
  paperUpload: byId("paperUpload"),
  paperList: byId("paperList"),
  chatFeed: byId("chatFeed"),
  chatInput: byId("chatInput"),
  sendChat: byId("sendChat"),
  overrideRows: byId("overrideRows"),
  addOverride: byId("addOverride"),
  overrideRowTemplate: byId("overrideRowTemplate"),
  backendStatusChip: byId("backendStatusChip"),
  approvalStatus: byId("approvalStatus"),
  specDiff: byId("specDiff"),
  approveSpec: byId("approveSpec"),
  refreshHistory: byId("refreshHistory"),
  runHistory: byId("runHistory")
};

const processDefaults = ["SoftQCD:inelastic"];

function toNumber(value, fallback = 0) {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

function toOptionalNumber(value) {
  if (value === null || value === undefined) return null;
  const s = String(value).trim();
  if (!s) return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

function stableSerialize(value) {
  if (value === null || value === undefined) return "null";
  if (Array.isArray(value)) {
    return `[${value.map((v) => stableSerialize(v)).join(",")}]`;
  }
  if (typeof value === "object") {
    const keys = Object.keys(value).sort();
    return `{${keys.map((k) => `${JSON.stringify(k)}:${stableSerialize(value[k])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

function flattenSpec(value, prefix = "", out = {}) {
  if (value === null || value === undefined) {
    out[prefix || "<root>"] = null;
    return out;
  }

  if (Array.isArray(value)) {
    out[prefix || "<root>"] = value.map((item) => stableSerialize(item)).join(",");
    return out;
  }

  if (typeof value !== "object") {
    out[prefix || "<root>"] = value;
    return out;
  }

  const keys = Object.keys(value).sort();
  if (!keys.length) {
    out[prefix || "<root>"] = "{}";
    return out;
  }

  keys.forEach((key) => {
    const next = prefix ? `${prefix}.${key}` : key;
    flattenSpec(value[key], next, out);
  });

  return out;
}

function buildSpecDiff(oldSpec, newSpec) {
  if (!oldSpec) {
    return ["No approved spec yet."];
  }

  const oldFlat = flattenSpec(oldSpec);
  const newFlat = flattenSpec(newSpec);
  const keys = [...new Set([...Object.keys(oldFlat), ...Object.keys(newFlat)])].sort();

  const lines = [];
  keys.forEach((key) => {
    const oldVal = oldFlat[key];
    const newVal = newFlat[key];

    if (oldVal === undefined && newVal !== undefined) {
      lines.push(`+ ${key}: ${newVal}`);
      return;
    }

    if (oldVal !== undefined && newVal === undefined) {
      lines.push(`- ${key}: ${oldVal}`);
      return;
    }

    if (stableSerialize(oldVal) !== stableSerialize(newVal)) {
      lines.push(`~ ${key}: ${oldVal} -> ${newVal}`);
    }
  });

  if (!lines.length) {
    return ["No differences from approved spec."];
  }

  if (lines.length > MAX_DIFF_LINES) {
    const clipped = lines.slice(0, MAX_DIFF_LINES);
    clipped.push(`... ${lines.length - MAX_DIFF_LINES} more changes`);
    return clipped;
  }

  return lines;
}

function setRunButtonState(currentSpec) {
  const approvedMatches = approvedSpec && stableSerialize(currentSpec) === stableSerialize(approvedSpec);
  dom.simulateRun.disabled = runInProgress || !approvedMatches;

  if (runInProgress) {
    return;
  }

  dom.simulateRun.textContent = "Run on Backend";
}

function renderApproval(currentSpec) {
  if (!approvedSpec) {
    dom.approvalStatus.textContent = "No approved spec yet. Click \"Approve Current Spec\" before running.";
    dom.specDiff.textContent = "No approved spec yet.";
    setRunButtonState(currentSpec);
    return;
  }

  const approvedMatches = stableSerialize(currentSpec) === stableSerialize(approvedSpec);
  const when = approvedAt ? new Date(approvedAt).toLocaleString() : "unknown";

  if (approvedMatches) {
    dom.approvalStatus.textContent = `Approved at ${when}. Spec is unchanged and ready to run.`;
  } else {
    dom.approvalStatus.textContent = `Approved at ${when}. Current form has pending changes.`;
  }

  dom.specDiff.textContent = buildSpecDiff(approvedSpec, currentSpec).join("\n");
  setRunButtonState(currentSpec);
}

function setProcessDefaults() {
  const cards = document.querySelectorAll(".process-card input[data-key]");
  cards.forEach((input) => {
    if (processDefaults.includes(input.dataset.key)) input.checked = true;
  });
}

function addOverrideRow(seed) {
  const node = dom.overrideRowTemplate.content.firstElementChild.cloneNode(true);
  if (seed) {
    node.querySelector(".ov-pdg").value = seed.pdg || "";
    node.querySelector(".ov-key").value = seed.key || "onMode";
    node.querySelector(".ov-value").value = seed.value || "";
  }

  node.querySelectorAll("input,select").forEach((el) => {
    el.addEventListener("input", render);
  });

  node.querySelector(".remove-ov").addEventListener("click", () => {
    node.remove();
    render();
  });

  dom.overrideRows.appendChild(node);
}

function selectedProcessKeys() {
  return [...document.querySelectorAll(".process-card input[data-key]:checked")]
    .map((el) => el.dataset.key)
    .filter(Boolean)
    .sort();
}

function pdgOverrides() {
  const rows = [...dom.overrideRows.querySelectorAll(".override-row")];
  const out = [];

  rows.forEach((row) => {
    const pdg = row.querySelector(".ov-pdg").value.trim();
    const key = row.querySelector(".ov-key").value.trim();
    const value = row.querySelector(".ov-value").value.trim();
    if (!pdg || !key || !value) return;

    const pdgNum = Number(pdg);
    if (!Number.isFinite(pdgNum)) return;

    out.push({ pdg: pdgNum, key, value });
  });

  return out;
}

function expertOverridesList() {
  const raw = dom.rawOverrides.value.trim();
  if (!raw) return [];
  return raw
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
}

function buildRunSpec() {
  const frameType = toNumber(dom.frameType.value, 1);

  return {
    schema_version: "1.0",
    events: toNumber(dom.events.value, 10000),
    times_allow_errors: toNumber(dom.timesAllowErrors.value, 10),
    seed_enabled: dom.seedEnabled.checked,
    seed: toNumber(dom.seed.value, 8310),
    beam: {
      frame_type: frameType,
      id_a: toNumber(dom.idA.value, 2212),
      id_b: toNumber(dom.idB.value, 2212),
      e_cm: toOptionalNumber(dom.eCM.value),
      e_a: toOptionalNumber(dom.eA.value),
      e_b: toOptionalNumber(dom.eB.value),
      lhef: dom.lhef.value.trim() || null
    },
    processes: selectedProcessKeys(),
    phase_space: {
      p_that_min: toNumber(dom.pTHatMin.value, 20),
      p_that_max: toOptionalNumber(dom.pTHatMax.value),
      m_hat_min: toOptionalNumber(dom.mHatMin.value),
      m_hat_max: toOptionalNumber(dom.mHatMax.value)
    },
    event_stages: {
      process_level_all: dom.processLevelAll.checked,
      mpi: dom.mpi.checked,
      isr: dom.isr.checked,
      fsr: dom.fsr.checked,
      hadron_all: dom.hadronAll.checked,
      hadronize: dom.hadronize.checked,
      decay: dom.decay.checked
    },
    shower_mpi_tune: {
      space_ptmax_match: toNumber(dom.spacePTMaxMatch.value, 1),
      time_ptmax_match: toNumber(dom.timePTMaxMatch.value, 1),
      mpi_pt0_ref: toNumber(dom.pT0Ref.value, 2.3),
      mpi_b_profile: toNumber(dom.bProfile.value, 2),
      tune_pp: toNumber(dom.tunepp.value, 14),
      tune_ee: toNumber(dom.tuneee.value, 7)
    },
    pdf_photon: {
      p_set: toNumber(dom.pSet.value, 14),
      lepton: dom.pdfLepton.checked,
      beam_a2gamma: dom.beamA2gamma.checked,
      beam_b2gamma: dom.beamB2gamma.checked,
      use_hard: dom.useHardPdf.checked,
      photon_parton_all: dom.photonPartonAll.checked
    },
    pdg_overrides: pdgOverrides(),
    expert_overrides: expertOverridesList(),
    merging: {
      enabled: dom.mergingOn.checked,
      process: dom.mergingProcess.value.trim() || "pp>jj",
      tms: toNumber(dom.mergingTMS.value, 30),
      n_jet_max: toNumber(dom.mergingNJetMax.value, 2)
    },
    jet_matching: {
      enabled: dom.jetMatchingOn.checked,
      q_cut: toNumber(dom.jetQCut.value, 30)
    }
  };
}

function compileLocalPreview(spec) {
  const onOff = (value) => (value ? "on" : "off");
  const lines = [];

  lines.push("! Auto-generated run spec (frontend)");
  lines.push(`Main:numberOfEvents = ${spec.events}`);
  lines.push(`Main:timesAllowErrors = ${spec.times_allow_errors}`);
  lines.push(`Random:setSeed = ${onOff(spec.seed_enabled)}`);
  if (spec.seed_enabled) lines.push(`Random:seed = ${spec.seed}`);

  lines.push(`Beams:frameType = ${spec.beam.frame_type}`);
  lines.push(`Beams:idA = ${spec.beam.id_a}`);
  lines.push(`Beams:idB = ${spec.beam.id_b}`);

  if (spec.beam.frame_type === 4) {
    lines.push(`Beams:LHEF = ${spec.beam.lhef || "<path/to/file.lhe>"}`);
  } else if (spec.beam.frame_type === 2) {
    lines.push(`Beams:eA = ${spec.beam.e_a}`);
    lines.push(`Beams:eB = ${spec.beam.e_b}`);
  } else {
    lines.push(`Beams:eCM = ${spec.beam.e_cm}`);
  }

  spec.processes.forEach((key) => lines.push(`${key} = on`));

  lines.push(`PhaseSpace:pTHatMin = ${spec.phase_space.p_that_min}`);
  if (spec.phase_space.p_that_max !== null) lines.push(`PhaseSpace:pTHatMax = ${spec.phase_space.p_that_max}`);
  if (spec.phase_space.m_hat_min !== null) lines.push(`PhaseSpace:mHatMin = ${spec.phase_space.m_hat_min}`);
  if (spec.phase_space.m_hat_max !== null) lines.push(`PhaseSpace:mHatMax = ${spec.phase_space.m_hat_max}`);

  lines.push(`ProcessLevel:all = ${onOff(spec.event_stages.process_level_all)}`);
  lines.push(`PartonLevel:MPI = ${onOff(spec.event_stages.mpi)}`);
  lines.push(`PartonLevel:ISR = ${onOff(spec.event_stages.isr)}`);
  lines.push(`PartonLevel:FSR = ${onOff(spec.event_stages.fsr)}`);
  lines.push(`HadronLevel:all = ${onOff(spec.event_stages.hadron_all)}`);
  lines.push(`HadronLevel:Hadronize = ${onOff(spec.event_stages.hadronize)}`);
  lines.push(`HadronLevel:Decay = ${onOff(spec.event_stages.decay)}`);

  lines.push(`SpaceShower:pTmaxMatch = ${spec.shower_mpi_tune.space_ptmax_match}`);
  lines.push(`TimeShower:pTmaxMatch = ${spec.shower_mpi_tune.time_ptmax_match}`);
  lines.push(`MultipartonInteractions:pT0Ref = ${spec.shower_mpi_tune.mpi_pt0_ref}`);
  lines.push(`MultipartonInteractions:bProfile = ${spec.shower_mpi_tune.mpi_b_profile}`);
  lines.push(`Tune:pp = ${spec.shower_mpi_tune.tune_pp}`);
  lines.push(`Tune:ee = ${spec.shower_mpi_tune.tune_ee}`);

  lines.push(`PDF:pSet = ${spec.pdf_photon.p_set}`);
  lines.push(`PDF:lepton = ${onOff(spec.pdf_photon.lepton)}`);
  lines.push(`PDF:beamA2gamma = ${onOff(spec.pdf_photon.beam_a2gamma)}`);
  lines.push(`PDF:beamB2gamma = ${onOff(spec.pdf_photon.beam_b2gamma)}`);
  lines.push(`PDF:useHard = ${onOff(spec.pdf_photon.use_hard)}`);
  lines.push(`PhotonParton:all = ${onOff(spec.pdf_photon.photon_parton_all)}`);

  if (spec.merging.enabled) {
    lines.push("Merging:doKTMerging = on");
    lines.push(`Merging:Process = ${spec.merging.process}`);
    lines.push(`Merging:TMS = ${spec.merging.tms}`);
    lines.push(`Merging:nJetMax = ${spec.merging.n_jet_max}`);
  }

  if (spec.jet_matching.enabled) {
    lines.push("JetMatching:merge = on");
    lines.push(`JetMatching:qCut = ${spec.jet_matching.q_cut}`);
  }

  if (spec.pdg_overrides.length) {
    lines.push("");
    lines.push("! PDG-level overrides");
    spec.pdg_overrides.forEach((ov) => {
      lines.push(`${ov.pdg}:${ov.key} = ${ov.value}`);
    });
  }

  if (spec.expert_overrides.length) {
    lines.push("");
    lines.push("! Expert overrides");
    lines.push(...spec.expert_overrides);
  }

  return lines.join("\n");
}

function renderPreview() {
  const spec = buildRunSpec();
  dom.commandPreview.textContent = compileLocalPreview(spec);
}

function renderRunSummaryText(lines) {
  dom.runSummary.textContent = lines.join("\n");
}

function renderRunSummaryWithArtifacts(runId, status, artifacts) {
  dom.runSummary.innerHTML = "";

  const summaryLines = [
    `Run ID: ${runId}`,
    `State: ${status.state}`,
    status.message ? `Message: ${status.message}` : null,
    status.exit_code !== undefined ? `Exit code: ${status.exit_code}` : null,
    status.event_summary ? `Attempted events: ${status.event_summary.attempted_events}` : null,
    status.event_summary ? `Accepted events: ${status.event_summary.accepted_events}` : null,
    status.event_summary ? `Failed events: ${status.event_summary.failed_events}` : null,
    status.analysis ? `Analysis plugin: ${status.analysis.plugin}` : null,
    status.analysis ? `Acceptance: ${status.analysis.acceptance_vs_attempted}` : null
  ].filter(Boolean);

  summaryLines.forEach((line) => {
    const row = document.createElement("div");
    row.textContent = line;
    dom.runSummary.appendChild(row);
  });

  if (!artifacts.length) return;

  const title = document.createElement("div");
  title.style.marginTop = "10px";
  title.style.fontWeight = "600";
  title.textContent = "Artifacts:";
  dom.runSummary.appendChild(title);

  artifacts.forEach((artifact) => {
    const row = document.createElement("div");
    const link = document.createElement("a");
    link.href = `${API_BASE}/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(artifact.name)}`;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = `${artifact.name} (${artifact.size_bytes} bytes)`;
    row.appendChild(link);
    dom.runSummary.appendChild(row);
  });
}

function sleep(ms) {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

async function apiRequest(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, options);
  const contentType = response.headers.get("content-type") || "";
  const body = contentType.includes("application/json") ? await response.json() : await response.text();

  if (!response.ok) {
    if (typeof body === "string") {
      throw new Error(`HTTP ${response.status}: ${body}`);
    }

    const details = body.details
      ? (typeof body.details === "string" ? body.details : JSON.stringify(body.details))
      : "No details";
    throw new Error(`HTTP ${response.status}: ${body.error || response.statusText} (${details})`);
  }

  return body;
}

async function checkBackendHealth() {
  try {
    await apiRequest("/health");
    dom.backendStatusChip.textContent = "Backend: Connected";
    return true;
  } catch (_err) {
    dom.backendStatusChip.textContent = "Backend: Offline";
    return false;
  }
}

async function pollRunUntilDone(runId) {
  const started = Date.now();

  while (true) {
    const status = await apiRequest(`/runs/${encodeURIComponent(runId)}/status`);

    renderRunSummaryText([
      `Run ID: ${runId}`,
      `State: ${status.state}`,
      status.message ? `Message: ${status.message}` : ""
    ]);

    if (status.state === "SUCCEEDED" || status.state === "FAILED") {
      return status;
    }

    if (Date.now() - started > POLL_TIMEOUT_MS) {
      throw new Error("Run polling timed out");
    }

    await sleep(POLL_INTERVAL_MS);
  }
}

async function loadRunDetails(runId) {
  renderRunSummaryText([`Loading run ${runId}...`]);
  const status = await apiRequest(`/runs/${encodeURIComponent(runId)}/status`);
  const artifactPayload = await apiRequest(`/runs/${encodeURIComponent(runId)}/artifacts`);
  renderRunSummaryWithArtifacts(runId, status, artifactPayload.artifacts || []);
}

function renderRunHistory(runs) {
  dom.runHistory.innerHTML = "";

  if (!runs.length) {
    dom.runHistory.textContent = "No runs found.";
    return;
  }

  runs.forEach((run) => {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "run-history-row";

    const title = document.createElement("div");
    title.className = "run-history-title";
    title.textContent = `${run.run_id}  [${run.state}]`;

    const meta = document.createElement("div");
    meta.className = "run-history-meta";
    meta.textContent = `${run.updated_at || run.created_at || ""} ${run.message ? `- ${run.message}` : ""}`;

    row.appendChild(title);
    row.appendChild(meta);
    row.addEventListener("click", () => {
      loadRunDetails(run.run_id).catch((err) => {
        renderRunSummaryText(["Failed to load run details.", String(err.message || err)]);
      });
    });

    dom.runHistory.appendChild(row);
  });
}

async function loadRunHistory() {
  try {
    const payload = await apiRequest("/runs?limit=20");
    renderRunHistory(payload.runs || []);
  } catch (err) {
    dom.runHistory.textContent = `Failed to load history: ${String(err.message || err)}`;
  }
}

async function simulateRun() {
  const spec = buildRunSpec();
  const approvedMatches = approvedSpec && stableSerialize(spec) === stableSerialize(approvedSpec);
  if (!approvedMatches) {
    renderRunSummaryText([
      "Run blocked by approval gate.",
      "Approve current spec first, then run."
    ]);
    return;
  }

  runInProgress = true;
  dom.simulateRun.disabled = true;
  dom.simulateRun.textContent = "Submitting...";
  renderRunSummaryText(["Submitting run to backend..."]);

  try {
    await apiRequest("/runspec/validate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ spec })
    });

    const created = await apiRequest("/runs/create", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ spec, auto_enqueue: true })
    });

    const runId = created.run_id;
    dom.simulateRun.textContent = "Running...";

    const finalStatus = await pollRunUntilDone(runId);
    const artifactPayload = await apiRequest(`/runs/${encodeURIComponent(runId)}/artifacts`);
    const artifacts = artifactPayload.artifacts || [];

    renderRunSummaryWithArtifacts(runId, finalStatus, artifacts);
    await checkBackendHealth();
    await loadRunHistory();
  } catch (err) {
    renderRunSummaryText(["Run request failed.", String(err.message || err)]);
    dom.backendStatusChip.textContent = "Backend: Error";
  } finally {
    runInProgress = false;
    render();
  }
}

function respondToChat(message) {
  const m = message.toLowerCase();
  if (m.includes("next") || m.includes("plan")) {
    return "Suggested next step: freeze a baseline seed + run 10k/100k/1M event sweeps and compare acceptance stability before changing physics knobs.";
  }
  if (m.includes("paper") || m.includes("replication")) {
    return "Replication workflow: extract explicit cuts, map each to settings, then log unknown assumptions separately before running.";
  }
  if (m.includes("uncertainty") || m.includes("systematic")) {
    return "Add uncertainty bands and tune/PDF variations as separate subruns; keep the nominal run untouched for comparability.";
  }
  return "Acknowledged. I can compile that into settings, stage subruns, and output a reproducible run sheet.";
}

function appendMsg(role, text) {
  const el = document.createElement("div");
  el.className = `msg ${role}`;
  el.textContent = text;
  dom.chatFeed.appendChild(el);
  dom.chatFeed.scrollTop = dom.chatFeed.scrollHeight;
}

function sendChat() {
  const text = dom.chatInput.value.trim();
  if (!text) return;
  appendMsg("user", text);
  appendMsg("ai", respondToChat(text));
  dom.chatInput.value = "";
}

function updatePaperList(files) {
  dom.paperList.innerHTML = "";
  if (!files.length) return;

  [...files].forEach((file) => {
    const li = document.createElement("li");
    li.textContent = `${file.name} (${Math.max(1, Math.round(file.size / 1024))} KB)`;
    dom.paperList.appendChild(li);
  });
}

function render() {
  dom.eCMOut.textContent = dom.eCM.value;
  dom.seed.disabled = !dom.seedEnabled.checked;

  const usingLHEF = dom.frameType.value === "4";
  const usingEAEB = dom.frameType.value === "2";
  dom.lhef.disabled = !usingLHEF;
  dom.eCM.disabled = usingLHEF || usingEAEB;
  dom.eA.disabled = !usingEAEB;
  dom.eB.disabled = !usingEAEB;

  const currentSpec = buildRunSpec();
  dom.commandPreview.textContent = compileLocalPreview(currentSpec);
  renderApproval(currentSpec);
}

function setupListeners() {
  const inputs = document.querySelectorAll("input, select, textarea");
  inputs.forEach((el) => el.addEventListener("input", render));

  dom.addOverride.addEventListener("click", () => {
    addOverrideRow();
    render();
  });

  dom.copyPreview.addEventListener("click", async () => {
    const text = dom.commandPreview.textContent;
    try {
      await navigator.clipboard.writeText(text);
      dom.copyPreview.textContent = "Copied";
      window.setTimeout(() => {
        dom.copyPreview.textContent = "Copy Preview";
      }, 900);
    } catch (_err) {
      dom.copyPreview.textContent = "Copy Failed";
      window.setTimeout(() => {
        dom.copyPreview.textContent = "Copy Preview";
      }, 900);
    }
  });

  dom.approveSpec.addEventListener("click", () => {
    approvedSpec = buildRunSpec();
    approvedAt = new Date().toISOString();
    render();
  });

  dom.refreshHistory.addEventListener("click", () => {
    loadRunHistory();
  });

  dom.simulateRun.addEventListener("click", () => {
    simulateRun();
  });

  dom.sendChat.addEventListener("click", sendChat);
  dom.chatInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") sendChat();
  });

  dom.paperUpload.addEventListener("change", () => {
    updatePaperList(dom.paperUpload.files || []);
  });
}

async function initialize() {
  setProcessDefaults();
  addOverrideRow({ pdg: "221", key: "onMode", value: "off" });
  addOverrideRow({ pdg: "221", key: "addChannel", value: "1 1.0 0 13 -13 13 -13" });
  setupListeners();
  render();

  const healthy = await checkBackendHealth();
  if (healthy) {
    await loadRunHistory();
  }
}

initialize();
