import React, { useState, useEffect, useCallback } from "react";
import { DiffEditor, Editor } from "@monaco-editor/react";
import { useTheme } from "../hooks/useTheme";

interface Props {
  backendUrl: string;
  token: string;
  filePath?: string;
  originalContent?: string;
  modifiedContent?: string;
}

export const DiffViewer: React.FC<Props> = ({
  backendUrl,
  token,
  filePath,
  originalContent,
  modifiedContent,
}) => {
  const [workspaceDiff, setWorkspaceDiff] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [sideBySide, setSideBySide] = useState(true);
  const theme = useTheme();

  const hasDirectDiff =
    originalContent !== undefined && modifiedContent !== undefined;

  const fetchWorkspaceDiff = useCallback(async () => {
    if (!backendUrl) return;
    setLoading(true);
    try {
      const headers: Record<string, string> = {};
      if (token) {
        headers["Authorization"] = `Bearer ${token}`;
      }
      const res = await fetch(`${backendUrl}/api/diff`, { headers });
      if (res.ok) {
        const data = await res.json();
        setWorkspaceDiff(data.diff || "");
      }
    } catch {
      // ignore offline errors
    } finally {
      setLoading(false);
    }
  }, [backendUrl, token]);

  useEffect(() => {
    if (!hasDirectDiff) {
      fetchWorkspaceDiff();
    }
  }, [hasDirectDiff, fetchWorkspaceDiff]);

  const monacoTheme = theme.isDark ? "vs-dark" : "light";

  // Determine language for file diff
  const ext = filePath?.split(".").pop()?.toLowerCase();
  const langMap: Record<string, string> = {
    py: "python",
    ts: "typescript",
    tsx: "typescript",
    js: "javascript",
    jsx: "javascript",
    json: "json",
    html: "html",
    css: "css",
    md: "markdown",
  };
  const language = (ext && langMap[ext]) || "plaintext";

  return (
    <div className="diff-viewer-container">
      <div className="diff-viewer-bar">
        <div className="diff-viewer-info">
          <span className="diff-viewer-title">
            {hasDirectDiff
              ? `Diff: ${filePath || "Current Changes"}`
              : "Workspace Changes"}
          </span>
        </div>
        <div className="diff-viewer-actions">
          {hasDirectDiff && (
            <button
              className="toolbar-btn"
              onClick={() => setSideBySide(!sideBySide)}
              title="Toggle side-by-side or inline view"
            >
              {sideBySide ? "Inline View" : "Side-by-Side"}
            </button>
          )}
          {!hasDirectDiff && (
            <button
              className="icon-btn"
              onClick={fetchWorkspaceDiff}
              title="Refresh workspace diff"
              disabled={loading}
            >
              🔄
            </button>
          )}
        </div>
      </div>

      <div className="diff-viewer-content">
        {loading ? (
          <div className="diff-loading">Loading diff...</div>
        ) : hasDirectDiff ? (
          <DiffEditor
            height="100%"
            language={language}
            original={originalContent}
            modified={modifiedContent}
            theme={monacoTheme}
            options={{
              readOnly: true,
              renderSideBySide: sideBySide,
              automaticLayout: true,
              minimap: { enabled: false },
              fontSize: 13,
              fontFamily: "var(--vscode-editor-font-family, Consolas, monospace)",
              scrollBeyondLastLine: false,
            }}
          />
        ) : workspaceDiff.trim() ? (
          <Editor
            height="100%"
            language="diff"
            theme={monacoTheme}
            value={workspaceDiff}
            options={{
              readOnly: true,
              automaticLayout: true,
              minimap: { enabled: false },
              fontSize: 13,
              fontFamily: "var(--vscode-editor-font-family, Consolas, monospace)",
              scrollBeyondLastLine: false,
              wordWrap: "on",
            }}
          />
        ) : (
          <div className="diff-empty">
            <div className="diff-empty-icon">✓</div>
            <p>No changes detected.</p>
            <p className="diff-empty-hint">
              Workspace matches the latest saved state.
            </p>
          </div>
        )}
      </div>
    </div>
  );
};
