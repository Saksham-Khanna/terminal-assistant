/**
 * useTheme — syncs with VS Code's current color theme via CSS variables.
 *
 * VS Code injects CSS custom properties (--vscode-editor-background, etc.)
 * into the webview. This hook reads a few key ones for use in JS.
 */

import { useEffect, useState } from "react";

interface ThemeColors {
  background: string;
  foreground: string;
  editorBackground: string;
  inputBackground: string;
  inputBorder: string;
  buttonBackground: string;
  buttonForeground: string;
  isDark: boolean;
}

function readTheme(): ThemeColors {
  const style = getComputedStyle(document.documentElement);
  const bg = style.getPropertyValue("--vscode-editor-background").trim() || "#1e1e1e";
  const fg = style.getPropertyValue("--vscode-editor-foreground").trim() || "#d4d4d4";

  // Simple heuristic: if bg luminance is low, it's a dark theme
  const r = parseInt(bg.replace("#", "").substring(0, 2), 16) || 0;
  const g = parseInt(bg.replace("#", "").substring(2, 4), 16) || 0;
  const b = parseInt(bg.replace("#", "").substring(4, 6), 16) || 0;
  const luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255;

  return {
    background: style.getPropertyValue("--vscode-sideBar-background").trim() || bg,
    foreground: fg,
    editorBackground: bg,
    inputBackground: style.getPropertyValue("--vscode-input-background").trim() || "#3c3c3c",
    inputBorder: style.getPropertyValue("--vscode-input-border").trim() || "#3c3c3c",
    buttonBackground: style.getPropertyValue("--vscode-button-background").trim() || "#0e639c",
    buttonForeground: style.getPropertyValue("--vscode-button-foreground").trim() || "#ffffff",
    isDark: luminance < 0.5,
  };
}

export function useTheme(): ThemeColors {
  const [theme, setTheme] = useState<ThemeColors>(readTheme());

  useEffect(() => {
    // Re-read on theme change (VS Code fires a class change on body)
    const observer = new MutationObserver(() => setTheme(readTheme()));
    observer.observe(document.body, { attributes: true, attributeFilter: ["class"] });
    return () => observer.disconnect();
  }, []);

  return theme;
}
