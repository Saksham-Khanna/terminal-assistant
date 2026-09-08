import React from "react";
import type { ToolCall } from "../types";

interface Props {
  toolCall: ToolCall;
}

const TOOL_COLORS: Record<string, string> = {
  read_file: "var(--vscode-charts-blue)",
  read_file_range: "var(--vscode-charts-blue)",
  write_file: "var(--vscode-charts-green)",
  edit_file: "var(--vscode-charts-green)",
  list_dir: "var(--vscode-charts-blue)",
  run_shell_command: "var(--vscode-charts-orange)",
  search_codebase: "var(--vscode-charts-purple)",
  grep_search: "var(--vscode-charts-purple)",
  find_files_by_glob: "var(--vscode-charts-purple)",
  undo_last_change: "var(--vscode-charts-red)",
};

export const ToolCallCard: React.FC<Props> = ({ toolCall }) => {
  const [expanded, setExpanded] = React.useState(false);
  const color = TOOL_COLORS[toolCall.name] || "var(--vscode-foreground)";

  const argsStr = Object.entries(toolCall.args || {})
    .map(([k, v]) => {
      const val = typeof v === "string" ? (v.length > 60 ? v.slice(0, 60) + "…" : v) : JSON.stringify(v);
      return `${k}: ${val}`;
    })
    .join(", ");

  return (
    <div className="tool-call-card" onClick={() => setExpanded(!expanded)}>
      <div className="tool-call-header">
        <span className="tool-call-badge" style={{ backgroundColor: color }}>
          {toolCall.name}
        </span>
        <span className="tool-call-args-preview">{argsStr}</span>
        <span className="tool-call-chevron">{expanded ? "▾" : "▸"}</span>
      </div>
      {expanded && (
        <div className="tool-call-details">
          <div className="tool-call-section">
            <strong>Arguments:</strong>
            <pre>{JSON.stringify(toolCall.args, null, 2)}</pre>
          </div>
          {toolCall.result && (
            <div className="tool-call-section">
              <strong>Result:</strong>
              <pre>{toolCall.result}</pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
