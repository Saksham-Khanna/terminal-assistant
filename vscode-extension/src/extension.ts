/**
 * Extension entry point — registers commands, creates the webview provider,
 * and optionally auto-starts the backend.
 */

import * as vscode from "vscode";
import { AgenticProvider } from "./AgenticProvider";
import { BackendManager } from "./BackendManager";

let backendManager: BackendManager;
let provider: AgenticProvider;

export function activate(context: vscode.ExtensionContext) {
  backendManager = new BackendManager();
  provider = new AgenticProvider(context);

  // Register the webview provider for the sidebar panel
  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider(
      AgenticProvider.viewType,
      provider,
      { webviewOptions: { retainContextWhenHidden: true } }
    )
  );

  // Register commands
  context.subscriptions.push(
    vscode.commands.registerCommand("agentic.openChat", () => {
      // Focus the sidebar view
      vscode.commands.executeCommand("agentic-chat.focus");
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("agentic.startBackend", async () => {
      await backendManager.start();
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("agentic.stopBackend", async () => {
      await backendManager.stop();
      vscode.window.showInformationMessage("Agentic backend stopped.");
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("agentic.sendSelection", () => {
      const editor = vscode.window.activeTextEditor;
      if (!editor) { return; }
      const selection = editor.document.getText(editor.selection);
      if (!selection) { return; }
      const fileName = editor.document.fileName;
      const language = editor.document.languageId;
      provider.postMessage({
        type: "sendSelection",
        text: selection,
        fileName,
        language,
      });
    })
  );

  // Auto-start backend if configured
  const config = vscode.workspace.getConfiguration("agentic");
  if (config.get<boolean>("autoStartBackend", true)) {
    backendManager.start().catch(() => {
      // Silently fail — user can start manually
    });
  }
}

export function deactivate() {
  backendManager?.dispose();
}
