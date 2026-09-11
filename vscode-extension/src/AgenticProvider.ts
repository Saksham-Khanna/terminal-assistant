/**
 * AgenticProvider — WebviewViewProvider for the sidebar panel.
 *
 * Manages the webview lifecycle, CSP headers, asset URIs, and the
 * postMessage bridge between the extension host and the React webview.
 */

import * as vscode from "vscode";
import type { WebviewToExtMessage } from "./messaging";

export class AgenticProvider implements vscode.WebviewViewProvider {
  public static readonly viewType = "agentic-chat";

  private _view?: vscode.WebviewView;
  private _extensionUri: vscode.Uri;

  constructor(private readonly context: vscode.ExtensionContext) {
    this._extensionUri = context.extensionUri;
  }

  resolveWebviewView(
    webviewView: vscode.WebviewView,
    _context: vscode.WebviewViewResolveContext,
    _token: vscode.CancellationToken
  ): void {
    this._view = webviewView;

    webviewView.webview.options = {
      enableScripts: true,
      localResourceRoots: [
        vscode.Uri.joinPath(this._extensionUri, "dist", "webview"),
      ],
    };

    webviewView.webview.html = this._getHtml(webviewView.webview);

    // Send backend config to webview on load
    this._sendBackendConfig();

    // Handle messages from webview
    webviewView.webview.onDidReceiveMessage(
      (message: WebviewToExtMessage) => this._handleMessage(message),
      undefined,
      this.context.subscriptions
    );
  }

  /**
   * Post a message to the webview (if it's alive).
   */
  postMessage(message: any): void {
    this._view?.webview.postMessage(message);
  }

  private _sendBackendConfig(): void {
    const config = vscode.workspace.getConfiguration("agentic");
    const backendUrl = config.get<string>("backendUrl", "http://localhost:8000");
    // Token ladder: VS Code setting → env var → workspace .env → empty
    let token = config.get<string>("backendToken", "");
    if (!token) token = process.env.AGENTIC_WEB_TOKEN || "";
    if (!token) token = this._readDotEnvToken() || "";
    this.postMessage({
      type: "setBackendUrl",
      url: backendUrl,
      token,
    });
  }

  /**
   * Fallback: read AGENTIC_WEB_TOKEN from the workspace's .env file. This keeps
   * auth working when the backend is auto-started by BackendManager (which loads
   * .env itself) without the user having to duplicate the token in VS Code settings.
   */
  private _readDotEnvToken(): string {
    const folders = vscode.workspace.workspaceFolders;
    if (!folders || folders.length === 0) return "";
    try {
      const envPath = vscode.Uri.joinPath(folders[0].uri, ".env").fsPath;
      const content = require("fs").readFileSync(envPath, "utf8");
      const match = content.match(/^\s*AGENTIC_WEB_TOKEN\s*=\s*["']?([^"'\r\n]+)["']?\s*$/m);
      return match ? match[1].trim() : "";
    } catch {
      return "";
    }
  }

  private async _handleMessage(message: WebviewToExtMessage): Promise<void> {
    switch (message.type) {
      case "requestOpenFile":
        // Open a workspace file in VS Code's native editor
        try {
          const config = vscode.workspace.getConfiguration("agentic");
          const backendUrl = config.get<string>("backendUrl", "http://localhost:8000");
          // We need the workspace root — fetch from /api/health or use workspace folder
          const folders = vscode.workspace.workspaceFolders;
          if (folders) {
            const fileUri = vscode.Uri.joinPath(folders[0].uri, message.path);
            await vscode.window.showTextDocument(fileUri);
          }
        } catch (e: any) {
          vscode.window.showErrorMessage(`Failed to open file: ${e.message}`);
        }
        break;

      case "requestDiff":
        // Show a diff editor with old vs new content
        try {
          const oldUri = vscode.Uri.parse(`untitled:${message.path}.old`);
          const newUri = vscode.Uri.parse(`untitled:${message.path}.new`);
          // For diff, we use a virtual document approach
          await vscode.commands.executeCommand(
            "vscode.diff",
            oldUri,
            newUri,
            `Diff: ${message.path}`
          );
        } catch (e: any) {
          vscode.window.showErrorMessage(`Failed to show diff: ${e.message}`);
        }
        break;

      case "showInfo":
        vscode.window.showInformationMessage(message.message);
        break;

      case "showError":
        vscode.window.showErrorMessage(message.message);
        break;

      case "startBackend":
        await vscode.commands.executeCommand("agentic.startBackend");
        break;

      case "stopBackend":
        await vscode.commands.executeCommand("agentic.stopBackend");
        break;

      case "webviewReady":
        this._sendBackendConfig();
        break;
    }
  }

  private _getHtml(webview: vscode.Webview): string {
    const distUri = vscode.Uri.joinPath(this._extensionUri, "dist", "webview");

    const scriptUri = webview.asWebviewUri(
      vscode.Uri.joinPath(distUri, "assets", "index.js")
    );
    const styleUri = webview.asWebviewUri(
      vscode.Uri.joinPath(distUri, "assets", "style.css")
    );

    const nonce = getNonce();

    // Strict CSP with:
    // - worker-src blob: (Monaco workers)
    // - style-src 'unsafe-inline' (Monaco injects styles)
    // - font-src for codicon/Monaco fonts
    return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="Content-Security-Policy" content="
    default-src 'none';
    script-src 'nonce-${nonce}' ${webview.cspSource};
    style-src ${webview.cspSource} 'unsafe-inline';
    font-src ${webview.cspSource};
    img-src ${webview.cspSource} data:;
    connect-src ws://localhost:* http://localhost:* ws://127.0.0.1:* http://127.0.0.1:*;
    worker-src blob: ${webview.cspSource};
  ">
  <link rel="stylesheet" href="${styleUri}">
  <title>Agentic IDE</title>
</head>
<body>
  <div id="root"></div>
  <script type="module" nonce="${nonce}" src="${scriptUri}"></script>
</body>
</html>`;
  }
}

function getNonce(): string {
  let text = "";
  const possible = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
  for (let i = 0; i < 32; i++) {
    text += possible.charAt(Math.floor(Math.random() * possible.length));
  }
  return text;
}
