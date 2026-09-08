import React from "react";
import type { ConnectionStatus } from "../hooks/useWebSocket";

interface Props {
  status: ConnectionStatus;
  usage?: string;
}

export const StatusBar: React.FC<Props> = ({ status, usage }) => {
  const statusColors: Record<ConnectionStatus, string> = {
    connected: "var(--vscode-testing-iconPassed, #4ec9b0)",
    connecting: "var(--vscode-editorWarning-foreground, #cca700)",
    disconnected: "var(--vscode-errorForeground, #f14c4c)",
  };

  const statusLabels: Record<ConnectionStatus, string> = {
    connected: "Connected",
    connecting: "Connecting…",
    disconnected: "Disconnected",
  };

  return (
    <div className="status-bar-container">
      <div className="status-indicator">
        <span
          className="status-dot"
          style={{ backgroundColor: statusColors[status] }}
        />
        <span className="status-label">{statusLabels[status]}</span>
      </div>
      {usage && (
        <div className="status-usage" title="Session token usage">
          <span className="status-usage-icon">⚡</span>
          <span>{usage}</span>
        </div>
      )}
    </div>
  );
};
