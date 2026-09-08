import React, { useEffect, useState, useCallback } from "react";
import type { SessionInfo } from "../types";

interface Props {
  backendUrl: string;
  token: string;
  onSelectSession: (sessionId: string) => void;
  onNewSession: () => void;
  onSaveSession: (name?: string) => void;
  activeSessionId?: string;
}

export const SessionPicker: React.FC<Props> = ({
  backendUrl,
  token,
  onSelectSession,
  onNewSession,
  onSaveSession,
  activeSessionId,
}) => {
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [isOpen, setIsOpen] = useState(false);
  const [saveName, setSaveName] = useState("");
  const [showSaveInput, setShowSaveInput] = useState(false);

  const fetchSessions = useCallback(async () => {
    if (!backendUrl) return;
    setLoading(true);
    try {
      const headers: Record<string, string> = {};
      if (token) {
        headers["Authorization"] = `Bearer ${token}`;
      }
      const res = await fetch(`${backendUrl}/api/sessions`, { headers });
      if (res.ok) {
        const data = await res.json();
        setSessions(data.sessions || []);
      }
    } catch {
      // ignore network errors when offline
    } finally {
      setLoading(false);
    }
  }, [backendUrl, token]);

  useEffect(() => {
    fetchSessions();
  }, [fetchSessions]);

  const handleSave = () => {
    onSaveSession(saveName.trim() || undefined);
    setSaveName("");
    setShowSaveInput(false);
    setTimeout(fetchSessions, 600);
  };

  return (
    <div className="session-picker">
      <div className="session-bar">
        <button
          className="toolbar-btn session-toggle-btn"
          onClick={() => {
            setIsOpen(!isOpen);
            if (!isOpen) fetchSessions();
          }}
          title="Manage sessions"
        >
          🗂️ Sessions ({sessions.length})
        </button>
        <button
          className="toolbar-btn"
          onClick={onNewSession}
          title="Start fresh conversation"
        >
          ✨ New
        </button>
        <button
          className="toolbar-btn"
          onClick={() => setShowSaveInput(!showSaveInput)}
          title="Save conversation checkpoint"
        >
          💾 Save
        </button>
      </div>

      {showSaveInput && (
        <div className="session-save-row">
          <input
            type="text"
            className="session-save-input"
            placeholder="Session name (optional)..."
            value={saveName}
            onChange={(e) => setSaveName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleSave();
              if (e.key === "Escape") setShowSaveInput(false);
            }}
          />
          <button className="toolbar-btn primary-btn" onClick={handleSave}>
            Save
          </button>
          <button
            className="toolbar-btn"
            onClick={() => setShowSaveInput(false)}
          >
            Cancel
          </button>
        </div>
      )}

      {isOpen && (
        <div className="session-dropdown">
          <div className="session-dropdown-header">
            <span>Saved Sessions</span>
            <button
              className="icon-btn"
              onClick={fetchSessions}
              title="Refresh sessions"
              disabled={loading}
            >
              🔄
            </button>
          </div>
          <div className="session-list">
            {loading && <div className="session-loading">Loading sessions...</div>}
            {!loading && sessions.length === 0 && (
              <div className="session-empty">No saved sessions yet</div>
            )}
            {sessions.map((s) => (
              <div
                key={s.session_id}
                className={`session-item ${activeSessionId === s.session_id ? "active" : ""}`}
                onClick={() => {
                  onSelectSession(s.session_id);
                  setIsOpen(false);
                }}
              >
                <div className="session-item-title">
                  {s.title || s.session_id}
                </div>
                <div className="session-item-meta">
                  <span>{s.turn_count || 0} turns</span>
                  {s.updated_at && (
                    <span>• {new Date(s.updated_at).toLocaleDateString()}</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
