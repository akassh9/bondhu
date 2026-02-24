import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import ReactFlow, { Background, Controls } from "reactflow";
import "reactflow/dist/style.css";

import { api } from "../api";
import { useAppStore } from "../store";

function toNumber(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function normalizeWorkflowIntent(intent) {
  if (!intent || typeof intent !== "object") return null;

  const pdg = Array.isArray(intent.particle_filter?.pdg)
    ? intent.particle_filter.pdg
        .map((value) => Number(value))
        .filter((value) => Number.isInteger(value))
        .slice(0, 16)
    : [];

  const cut = {};
  ["pt_min", "pt_max", "eta_min", "eta_max", "phi_min", "phi_max", "mass_min", "mass_max"].forEach((key) => {
    const parsed = toNumber(intent.kinematic_cut?.[key]);
    if (parsed !== null) cut[key] = parsed;
  });

  const histRaw = intent.histogram_1d;
  const histogram =
    histRaw && typeof histRaw === "object"
      ? {
          field: ["pt", "eta", "phi", "mass", "energy"].includes(String(histRaw.field || "").toLowerCase())
            ? String(histRaw.field).toLowerCase()
            : "pt",
          bins: Math.min(200, Math.max(1, Math.trunc(Number(histRaw.bins || 20)))),
          min: toNumber(histRaw.min) ?? 0,
          max: toNumber(histRaw.max) ?? 10,
        }
      : null;

  if (histogram && histogram.max <= histogram.min) {
    histogram.max = histogram.min + 1;
  }

  const exportFormats = Array.isArray(intent.export_formats)
    ? intent.export_formats
        .map((fmt) => String(fmt).toLowerCase())
        .filter((fmt, idx, arr) => ["json", "csv", "png"].includes(fmt) && arr.indexOf(fmt) === idx)
    : [];

  const unavailableRequests = Array.isArray(intent.unavailable_requests)
    ? intent.unavailable_requests.map((line) => String(line).trim()).filter(Boolean)
    : [];

  const hasPrefill =
    pdg.length > 0 ||
    Object.keys(cut).length > 0 ||
    Boolean(histogram) ||
    Boolean(intent.include_cutflow) ||
    exportFormats.length > 0;

  if (!hasPrefill) return null;

  return {
    summary: String(intent.summary || "").trim(),
    pdg,
    finalOnly: intent.particle_filter?.final_only !== false,
    cut,
    histogram,
    includeCutflow: Boolean(intent.include_cutflow),
    exportFormats,
    unavailableRequests,
  };
}

function buildGraphFromIntent(intent) {
  const nodes = [{ id: "settings", type: "settings_source", config: {} }];
  const edges = [];
  let previousNodeId = "settings";
  let exportSourceNodeId = "settings";

  if (intent.pdg.length > 0) {
    const nodeId = "filter_particles";
    nodes.push({
      id: nodeId,
      type: "particle_filter",
      config: { pdg: intent.pdg, final_only: intent.finalOnly },
    });
    edges.push({ source: previousNodeId, target: nodeId });
    previousNodeId = nodeId;
  }

  if (Object.keys(intent.cut).length > 0) {
    const nodeId = "cut_kinematics";
    nodes.push({
      id: nodeId,
      type: "kinematic_cut",
      config: intent.cut,
    });
    edges.push({ source: previousNodeId, target: nodeId });
    previousNodeId = nodeId;
    exportSourceNodeId = nodeId;
  }

  if (intent.includeCutflow) {
    const nodeId = "cutflow";
    const cuts = [];
    if (intent.cut.pt_min !== undefined) cuts.push({ name: "pt_min", field: "pt", op: ">", value: intent.cut.pt_min });
    if (intent.cut.pt_max !== undefined) cuts.push({ name: "pt_max", field: "pt", op: "<", value: intent.cut.pt_max });
    if (intent.cut.eta_min !== undefined) cuts.push({ name: "eta_min", field: "eta", op: ">", value: intent.cut.eta_min });
    if (intent.cut.eta_max !== undefined) cuts.push({ name: "eta_max", field: "eta", op: "<", value: intent.cut.eta_max });
    if (intent.cut.phi_min !== undefined) cuts.push({ name: "phi_min", field: "phi", op: ">", value: intent.cut.phi_min });
    if (intent.cut.phi_max !== undefined) cuts.push({ name: "phi_max", field: "phi", op: "<", value: intent.cut.phi_max });
    if (intent.cut.mass_min !== undefined) cuts.push({ name: "mass_min", field: "mass", op: ">", value: intent.cut.mass_min });
    if (intent.cut.mass_max !== undefined) cuts.push({ name: "mass_max", field: "mass", op: "<", value: intent.cut.mass_max });

    nodes.push({
      id: nodeId,
      type: "cutflow",
      config: { cuts },
    });
    edges.push({ source: previousNodeId, target: nodeId });
    if (!intent.histogram) {
      exportSourceNodeId = nodeId;
    }
  }

  if (intent.histogram) {
    const nodeId = "hist_1d";
    nodes.push({
      id: nodeId,
      type: "histogram_1d",
      config: intent.histogram,
    });
    edges.push({ source: previousNodeId, target: nodeId });
    exportSourceNodeId = nodeId;
  }

  const hasJson = intent.exportFormats.includes("json");
  const hasCsv = intent.exportFormats.includes("csv");
  let format = "json";
  if (hasJson && hasCsv) format = "all";
  else if (hasCsv) format = "csv";

  const exportNodeId = "export_results";
  nodes.push({
    id: exportNodeId,
    type: "export",
    config: { format },
  });
  edges.push({ source: exportSourceNodeId, target: exportNodeId });

  return { nodes, edges };
}

function defaultGraph() {
  return {
    nodes: [
      { id: "settings", type: "settings_source", config: {} },
      { id: "filter_mu", type: "particle_filter", config: { pdg: [13, -13], final_only: true } },
      { id: "hist_pt", type: "histogram_1d", config: { field: "pt", bins: 20, min: 0, max: 10 } },
      { id: "export_json", type: "export", config: { format: "json" } },
    ],
    edges: [
      { source: "settings", target: "filter_mu" },
      { source: "filter_mu", target: "hist_pt" },
      { source: "hist_pt", target: "export_json" },
    ],
  };
}

export default function WorkflowPage() {
  const { workflowId } = useParams();
  const navigate = useNavigate();

  const settingIdFromStore = useAppStore((s) => s.settingId);
  const setWorkflowId = useAppStore((s) => s.setWorkflowId);
  const setWorkflowRunId = useAppStore((s) => s.setWorkflowRunId);

  const [workflowName, setWorkflowName] = useState("Muon Tracking Workflow");
  const [graph, setGraph] = useState(defaultGraph());
  const [status, setStatus] = useState("Ready");
  const [activeWorkflowId, setActiveWorkflowId] = useState(workflowId || null);
  const [busy, setBusy] = useState(false);
  const [intentWarnings, setIntentWarnings] = useState([]);

  useEffect(() => {
    if (!workflowId) return;
    api
      .getWorkflow(workflowId)
      .then((wf) => {
        setActiveWorkflowId(wf.id);
        setWorkflowId(wf.id);
        setWorkflowName(wf.name);
        setGraph(wf.graph);
        setStatus(`Loaded workflow ${wf.id}`);
      })
      .catch((err) => setStatus(String(err.message || err)));
  }, [workflowId, setWorkflowId]);

  useEffect(() => {
    if (workflowId || !settingIdFromStore) return;
    let mounted = true;
    api
      .getSetting(settingIdFromStore)
      .then((setting) => {
        if (!mounted) return;
        const intent = normalizeWorkflowIntent(setting.workflow_intent);
        if (!intent) return;

        setGraph(buildGraphFromIntent(intent));
        if (intent.summary) setWorkflowName("Intent Prefill Workflow");
        setIntentWarnings(intent.unavailableRequests || []);
        if ((intent.unavailableRequests || []).length > 0) {
          setStatus(`Prefilled from chat intent. Note: ${intent.unavailableRequests.join(" | ")}`);
        } else {
          setStatus("Prefilled workflow graph from chat intent.");
        }
      })
      .catch((err) => setStatus(String(err.message || err)));

    return () => {
      mounted = false;
    };
  }, [workflowId, settingIdFromStore]);

  const flowNodes = useMemo(
    () =>
      graph.nodes.map((node, idx) => ({
        id: node.id,
        data: { label: `${node.type}\n${node.id}` },
        position: { x: 120 + idx * 220, y: 120 + (idx % 2) * 120 },
      })),
    [graph.nodes]
  );

  const flowEdges = useMemo(
    () =>
      graph.edges.map((edge, idx) => ({
        id: `e-${idx}-${edge.source}-${edge.target}`,
        source: edge.source,
        target: edge.target,
      })),
    [graph.edges]
  );

  async function saveWorkflow() {
    if (!settingIdFromStore && !activeWorkflowId) {
      setStatus("Missing locked setting. Complete chat/settings flow first.");
      return;
    }

    setBusy(true);
    try {
      if (!activeWorkflowId) {
        const wf = await api.createWorkflow({
          settingId: settingIdFromStore,
          name: workflowName,
          graph,
        });
        setActiveWorkflowId(wf.id);
        setWorkflowId(wf.id);
        setStatus(`Created workflow ${wf.id}`);
      } else {
        // v1 API has create/get/validate/run. Update is intentionally omitted in this first cut.
        setStatus(`Workflow ${activeWorkflowId} already exists.`);
      }
    } catch (err) {
      setStatus(String(err.message || err));
    } finally {
      setBusy(false);
    }
  }

  async function validateWorkflow() {
    if (!activeWorkflowId) {
      setStatus("Save workflow first.");
      return;
    }
    setBusy(true);
    try {
      const result = await api.validateWorkflow(activeWorkflowId);
      if (result.valid) {
        setStatus("Workflow graph valid.");
      } else {
        setStatus(`Workflow invalid: ${result.errors.join(" | ")}`);
      }
    } catch (err) {
      setStatus(String(err.message || err));
    } finally {
      setBusy(false);
    }
  }

  async function runWorkflow() {
    if (!activeWorkflowId) {
      setStatus("Save workflow first.");
      return;
    }
    setBusy(true);
    try {
      const run = await api.startWorkflowRun(activeWorkflowId, 3600);
      setWorkflowRunId(run.id);
      setStatus(`Workflow run started: ${run.id}`);
      navigate(`/app/results/${encodeURIComponent(run.id)}`);
    } catch (err) {
      setStatus(String(err.message || err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel">
      <h2>Workflow Builder</h2>
      <p className="status">{status}</p>
      {intentWarnings.length > 0 && (
        <ul>
          {intentWarnings.map((line, idx) => (
            <li key={`${idx}-${line}`} className="muted">
              {line}
            </li>
          ))}
        </ul>
      )}

      <label>
        Workflow Name
        <input value={workflowName} onChange={(e) => setWorkflowName(e.target.value)} />
      </label>

      <div className="flow-wrap">
        <ReactFlow nodes={flowNodes} edges={flowEdges} fitView>
          <Background />
          <Controls />
        </ReactFlow>
      </div>

      <h3>Graph JSON (editable)</h3>
      <textarea
        rows={14}
        value={JSON.stringify(graph, null, 2)}
        onChange={(e) => {
          try {
            const parsed = JSON.parse(e.target.value);
            setGraph(parsed);
          } catch (_err) {
            // keep editable text forgiving
          }
        }}
      />

      <div className="row">
        <button onClick={saveWorkflow} disabled={busy}>
          Save Workflow
        </button>
        <button onClick={validateWorkflow} disabled={busy || !activeWorkflowId}>
          Validate
        </button>
        <button onClick={runWorkflow} disabled={busy || !activeWorkflowId}>
          Run Workflow
        </button>
      </div>
    </section>
  );
}
