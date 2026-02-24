import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { api } from "../api";
import { useAppStore } from "../store";

export default function SettingsReviewPage() {
  const { settingId } = useParams();
  const navigate = useNavigate();
  const setSettingId = useAppStore((s) => s.setSettingId);

  const [setting, setSetting] = useState(null);
  const [status, setStatus] = useState("Loading setting...");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!settingId) return;
    setSettingId(settingId);
    api
      .getSetting(settingId)
      .then((payload) => {
        setSetting(payload);
        setStatus(`Viability: ${payload.viability}`);
      })
      .catch((err) => setStatus(String(err.message || err)));
  }, [settingId, setSettingId]);

  const runspecText = useMemo(() => JSON.stringify(setting?.runspec || {}, null, 2), [setting]);
  const workflowIntentText = useMemo(() => JSON.stringify(setting?.workflow_intent || {}, null, 2), [setting]);

  async function lockAndContinue() {
    if (!settingId || busy) return;
    setBusy(true);
    try {
      const payload = await api.lockSetting(settingId);
      setSetting(payload.setting);
      setStatus("Setting locked.");
      navigate("/app/workflows/new");
    } catch (err) {
      setStatus(String(err.message || err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel">
      <h2>Settings Review</h2>
      <p className="status">{status}</p>

      <h3>Viability Notes</h3>
      <ul>
        {(setting?.viability_notes || []).map((line, idx) => (
          <li key={idx}>{line}</li>
        ))}
      </ul>

      <h3>RunSpec</h3>
      <pre className="code-box">{runspecText}</pre>

      <h3>Workflow Intent (prefill for next step)</h3>
      <pre className="code-box">{workflowIntentText}</pre>

      <button onClick={lockAndContinue} disabled={busy || !settingId}>
        Lock Setting and Build Workflow
      </button>
    </section>
  );
}
