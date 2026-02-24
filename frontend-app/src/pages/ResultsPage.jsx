import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Tooltip, XAxis, YAxis } from "recharts";

import { api } from "../api";

export default function ResultsPage() {
  const { workflowRunId } = useParams();
  const [run, setRun] = useState(null);
  const [status, setStatus] = useState("Loading...");

  useEffect(() => {
    if (!workflowRunId) return;
    let mounted = true;

    async function loadLoop() {
      while (mounted) {
        try {
          const payload = await api.getWorkflowRun(workflowRunId);
          if (!mounted) return;
          setRun(payload);
          setStatus(`State: ${payload.state}`);
          if (payload.state === "SUCCEEDED" || payload.state === "FAILED") return;
        } catch (err) {
          if (!mounted) return;
          setStatus(String(err.message || err));
          return;
        }
        await new Promise((resolve) => setTimeout(resolve, 1500));
      }
    }

    loadLoop();
    return () => {
      mounted = false;
    };
  }, [workflowRunId]);

  const barData = useMemo(() => {
    if (!run?.node_runs) return [];
    return run.node_runs.map((node) => ({
      node: node.node_id,
      rows: node.output?.count || 0,
    }));
  }, [run]);
  const resultsReview = run?.summary?.llm_results_review || null;

  return (
    <section className="panel">
      <h2>Workflow Results</h2>
      <p className="status">{status}</p>

      {run && (
        <>
          <div className="summary">
            <div>Workflow Run: {run.id}</div>
            <div>Simulation Run: {run.run_id || "-"}</div>
          </div>

          <h3>LLM Results Review</h3>
          {resultsReview ? (
            <div className="node-card">
              <div>{resultsReview.overview}</div>
              <div className="summary">
                <div>Model: {resultsReview.model || "-"}</div>
                <div>Messages used: {resultsReview.conversation_message_count ?? "-"}</div>
                {resultsReview.conversation_truncated ? <div>Conversation clipped for token safety.</div> : null}
              </div>

              <h4>Potentially Expected</h4>
              <ul>
                {(resultsReview.expected || []).map((item, idx) => (
                  <li key={`expected-${idx}`}>{item}</li>
                ))}
              </ul>

              <h4>Observed</h4>
              <ul>
                {(resultsReview.observed || []).map((item, idx) => (
                  <li key={`observed-${idx}`}>{item}</li>
                ))}
              </ul>

              <h4>What Likely Went Right</h4>
              <ul>
                {(resultsReview.went_right || []).map((item, idx) => (
                  <li key={`right-${idx}`}>{item}</li>
                ))}
              </ul>

              <h4>What Might Have Gone Wrong</h4>
              <ul>
                {(resultsReview.went_wrong_or_risky || []).map((item, idx) => (
                  <li key={`wrong-${idx}`}>{item}</li>
                ))}
              </ul>

              <h4>Next Steps</h4>
              <ul>
                {(resultsReview.next_steps || []).map((item, idx) => (
                  <li key={`next-${idx}`}>{item}</li>
                ))}
              </ul>
            </div>
          ) : (
            <p className="muted">
              {run.state === "SUCCEEDED" || run.state === "FAILED"
                ? "No LLM review available for this run."
                : "LLM review will appear once the run finishes."}
            </p>
          )}

          <h3>Node Outputs</h3>
          <div className="node-grid">
            {run.node_runs.map((node) => (
              <div key={node.node_id} className="node-card">
                <strong>
                  {node.node_id} ({node.node_type})
                </strong>
                <div>State: {node.state}</div>
                <pre className="code-box">{JSON.stringify(node.output, null, 2)}</pre>
                {(node.artifacts || []).map((artifact) => (
                  <div key={artifact}>
                    <a
                      href={`${api.base}/v2/workflow-runs/${encodeURIComponent(run.id)}/artifacts/${encodeURIComponent(artifact)}`}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      {artifact}
                    </a>
                  </div>
                ))}
              </div>
            ))}
          </div>

          <h3>Quick Chart (rows per node)</h3>
          <div className="chart-wrap">
            <BarChart width={760} height={280} data={barData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="node" />
              <YAxis />
              <Tooltip />
              <Bar dataKey="rows" fill="#0a7c70" />
            </BarChart>
          </div>
        </>
      )}
    </section>
  );
}
