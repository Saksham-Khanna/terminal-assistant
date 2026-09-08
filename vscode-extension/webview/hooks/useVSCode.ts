/**
 * useVSCode — singleton wrapper around acquireVsCodeApi().
 *
 * acquireVsCodeApi() can only be called once per webview session.
 * This hook provides a stable reference and typed helpers.
 */

import { useCallback, useEffect, useRef } from "react";

interface VsCodeApi {
  postMessage(message: any): void;
  getState(): any;
  setState(state: any): void;
}

// Singleton — survives React re-renders
let vscodeApi: VsCodeApi | null = null;

function getApi(): VsCodeApi {
  if (!vscodeApi) {
    // @ts-ignore — acquireVsCodeApi is injected by VS Code
    vscodeApi = acquireVsCodeApi();
  }
  return vscodeApi!;
}

export function useVSCode() {
  const api = getApi();

  const postMessage = useCallback(
    (message: any) => api.postMessage(message),
    [api]
  );

  const onMessage = useCallback(
    (handler: (message: any) => void) => {
      const listener = (event: MessageEvent) => handler(event.data);
      window.addEventListener("message", listener);
      return () => window.removeEventListener("message", listener);
    },
    []
  );

  return { postMessage, onMessage, getState: api.getState.bind(api), setState: api.setState.bind(api) };
}
