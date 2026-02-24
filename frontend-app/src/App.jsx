import { Link, Navigate, Route, Routes } from "react-router-dom";

import ChatPage from "./pages/ChatPage";
import ResultsPage from "./pages/ResultsPage";
import SettingsReviewPage from "./pages/SettingsReviewPage";
import WorkflowPage from "./pages/WorkflowPage";

export default function App() {
  return (
    <div className="app-shell">
      <header className="topbar">
        <div>
          <h1>Pythia Agentic Workflow</h1>
          <p>Chat planning to settings lock to workflow graph to results</p>
        </div>
        <nav className="nav">
          <Link to="/app/chat">Chat</Link>
          <Link to="/app/workflows/new">Workflow</Link>
        </nav>
      </header>

      <main>
        <Routes>
          <Route path="/" element={<Navigate to="/app/chat" replace />} />
          <Route path="/app/chat" element={<ChatPage />} />
          <Route path="/app/settings/:settingId/review" element={<SettingsReviewPage />} />
          <Route path="/app/workflows/new" element={<WorkflowPage />} />
          <Route path="/app/workflows/:workflowId" element={<WorkflowPage />} />
          <Route path="/app/results/:workflowRunId" element={<ResultsPage />} />
        </Routes>
      </main>
    </div>
  );
}
