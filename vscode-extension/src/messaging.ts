/**
 * Typed postMessage bridge between extension host and webview.
 *
 * Both sides import these types so the protocol is compile-time checked.
 */

// ---- Extension → Webview messages ----

export interface ExtSetBackendUrl {
  type: "setBackendUrl";
  url: string;
  token: string;
}

export interface ExtSendSelection {
  type: "sendSelection";
  text: string;
  fileName: string;
  language: string;
}

export interface ExtOpenFile {
  type: "openFile";
  path: string;
  content: string;
}

export type ExtToWebviewMessage =
  | ExtSetBackendUrl
  | ExtSendSelection
  | ExtOpenFile;

// ---- Webview → Extension messages ----

export interface WebRequestOpenFile {
  type: "requestOpenFile";
  path: string;
}

export interface WebRequestDiff {
  type: "requestDiff";
  path: string;
  oldContent: string;
  newContent: string;
}

export interface WebShowInfo {
  type: "showInfo";
  message: string;
}

export interface WebShowError {
  type: "showError";
  message: string;
}

export interface WebStartBackend {
  type: "startBackend";
}

export interface WebStopBackend {
  type: "stopBackend";
}

export interface WebWebviewReady {
  type: "webviewReady";
}

export type WebviewToExtMessage =
  | WebRequestOpenFile
  | WebRequestDiff
  | WebShowInfo
  | WebShowError
  | WebStartBackend
  | WebStopBackend
  | WebWebviewReady;
