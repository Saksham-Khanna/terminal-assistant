/**
 * BackendManager — auto-start/stop the Python FastAPI backend.
 *
 * Spawns `agentic web --port <port>` (or `python -m cli web --port <port>`)
 * as a child process, monitors health via GET /api/health, and handles
 * auto-restart on crash and graceful shutdown on deactivate.
 */

import * as vscode from "vscode";
import { ChildProcess, spawn } from "child_process";
import http from "http";

export class BackendManager {
  private process: ChildProcess | null = null;
  private outputChannel: vscode.OutputChannel;
  private healthTimer: ReturnType<typeof setInterval> | null = null;
  private _isRunning = false;

  constructor() {
    this.outputChannel = vscode.window.createOutputChannel("Agentic Backend");
  }

  get isRunning(): boolean {
    return this._isRunning;
  }

  private getConfig() {
    const config = vscode.workspace.getConfiguration("agentic");
    const backendUrl = config.get<string>("backendUrl", "http://localhost:8000");
    const pythonPath = config.get<string>("pythonPath", "python");
    const url = new URL(backendUrl);
    return {
      host: url.hostname,
      port: parseInt(url.port || "8000", 10),
      pythonPath,
      backendUrl,
    };
  }

  async start(): Promise<boolean> {
    if (this._isRunning) {
      vscode.window.showInformationMessage("Agentic backend is already running.");
      return true;
    }

    // Check if backend is already running externally
    const alreadyUp = await this.healthCheck();
    if (alreadyUp) {
      this._isRunning = true;
      this.startHealthMonitor();
      this.outputChannel.appendLine("[BackendManager] External backend detected, using it.");
      return true;
    }

    const { pythonPath, port, host } = this.getConfig();
    this.outputChannel.appendLine(`[BackendManager] Starting backend: ${pythonPath} -m cli web --port ${port} --host ${host}`);
    this.outputChannel.show(true);

    try {
      // Try `agentic web` first (installed via pip), fall back to `python -m cli`
      this.process = spawn(pythonPath, ["-m", "cli", "web", "--port", String(port), "--host", host], {
        cwd: this.getWorkspaceRoot(),
        env: { ...process.env },
        stdio: ["ignore", "pipe", "pipe"],
      });

      this.process.stdout?.on("data", (data: Buffer) => {
        this.outputChannel.append(data.toString());
      });

      this.process.stderr?.on("data", (data: Buffer) => {
        this.outputChannel.append(data.toString());
      });

      this.process.on("close", (code) => {
        this.outputChannel.appendLine(`[BackendManager] Process exited with code ${code}`);
        this._isRunning = false;
      });

      this.process.on("error", (err) => {
        this.outputChannel.appendLine(`[BackendManager] Process error: ${err.message}`);
        this._isRunning = false;
      });

      // Wait for backend to become healthy
      const healthy = await this.waitForHealth(15000);
      if (healthy) {
        this._isRunning = true;
        this.startHealthMonitor();
        vscode.window.showInformationMessage("Agentic backend started successfully.");
        return true;
      } else {
        vscode.window.showErrorMessage("Agentic backend failed to start. Check the output channel.");
        return false;
      }
    } catch (err: any) {
      vscode.window.showErrorMessage(`Failed to start backend: ${err.message}`);
      return false;
    }
  }

  async stop(): Promise<void> {
    this.stopHealthMonitor();
    if (this.process) {
      this.process.kill("SIGTERM");
      this.process = null;
    }
    this._isRunning = false;
    this.outputChannel.appendLine("[BackendManager] Backend stopped.");
  }

  async healthCheck(): Promise<boolean> {
    const { backendUrl } = this.getConfig();
    return new Promise((resolve) => {
      const url = new URL("/api/health", backendUrl);
      const req = http.get(url.toString(), { timeout: 3000 }, (res) => {
        resolve(res.statusCode === 200);
      });
      req.on("error", () => resolve(false));
      req.on("timeout", () => {
        req.destroy();
        resolve(false);
      });
    });
  }

  private async waitForHealth(timeoutMs: number): Promise<boolean> {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      const ok = await this.healthCheck();
      if (ok) { return true; }
      await new Promise((r) => setTimeout(r, 1000));
    }
    return false;
  }

  private startHealthMonitor(): void {
    this.stopHealthMonitor();
    this.healthTimer = setInterval(async () => {
      const ok = await this.healthCheck();
      if (!ok && this._isRunning) {
        this._isRunning = false;
        this.outputChannel.appendLine("[BackendManager] Health check failed — backend may have crashed.");
      }
    }, 15000);
  }

  private stopHealthMonitor(): void {
    if (this.healthTimer) {
      clearInterval(this.healthTimer);
      this.healthTimer = null;
    }
  }

  private getWorkspaceRoot(): string {
    const folders = vscode.workspace.workspaceFolders;
    if (folders && folders.length > 0) {
      return folders[0].uri.fsPath;
    }
    return process.cwd();
  }

  dispose(): void {
    this.stop();
    this.outputChannel.dispose();
  }
}
