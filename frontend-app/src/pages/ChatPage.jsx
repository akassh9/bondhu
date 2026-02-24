import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../api";
import { useAppStore } from "../store";

export default function ChatPage() {
  const navigate = useNavigate();
  const threadId = useAppStore((s) => s.threadId);
  const setThreadId = useAppStore((s) => s.setThreadId);
  const setSettingId = useAppStore((s) => s.setSettingId);

  const [messages, setMessages] = useState([]);
  const [status, setStatus] = useState("Idle");
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (threadId) return;
    setBusy(true);
    api
      .createThread()
      .then((thread) => {
        setThreadId(thread.id);
        setMessages(thread.messages || []);
        if (thread.setting?.id) setSettingId(thread.setting.id);
        setStatus(`Thread ${thread.id} created`);
      })
      .catch((err) => setStatus(String(err.message || err)))
      .finally(() => setBusy(false));
  }, [threadId, setThreadId, setSettingId]);

  async function send() {
    const text = input.trim();
    if (!text || !threadId || busy) return;

    setBusy(true);
    setInput("");
    try {
      const payload = await api.postThreadMessage(threadId, text);
      setMessages(payload.thread.messages || []);
      if (payload.thread.setting?.id) setSettingId(payload.thread.setting.id);
      setStatus(`State: ${payload.setting_state}`);

      if (payload.setting_state === "SETTING_READY" && payload.thread.setting?.id) {
        navigate(`/app/settings/${encodeURIComponent(payload.thread.setting.id)}/review`);
      }
    } catch (err) {
      setStatus(String(err.message || err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel">
      <h2>Chat Planning</h2>
      <p className="status">{status}</p>

      <div className="chat-feed">
        {messages.map((msg, idx) => (
          <div key={`${idx}-${msg.created_at || ""}`} className={`msg ${msg.role}`}>
            <strong>{msg.role}</strong>: {msg.content}
          </div>
        ))}
      </div>

      <div className="chat-row">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Describe beams, energy, process goals, observables, and constraints"
          rows={4}
        />
        <button onClick={send} disabled={busy || !threadId}>
          Send
        </button>
      </div>
    </section>
  );
}
