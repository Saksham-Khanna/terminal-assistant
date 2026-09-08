import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

// Monaco editor bundled locally — NO CDN, NO vite-plugin-monaco-editor.
// Workers are imported via ?worker in the webview code and MonacoEnvironment
// is set manually at runtime.

export default defineConfig({
  plugins: [react()],
  root: path.resolve(__dirname, "webview"),
  build: {
    outDir: path.resolve(__dirname, "dist/webview"),
    emptyOutDir: true,
    rollupOptions: {
      input: path.resolve(__dirname, "webview/index.html"),
      output: {
        entryFileNames: "assets/[name].js",
        chunkFileNames: "assets/[name].js",
        assetFileNames: "assets/[name].[ext]",
      },
    },
    sourcemap: true,
    // Keep chunk names predictable for CSP/asWebviewUri
    cssCodeSplit: false,
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "webview"),
    },
  },
  define: {
    "process.env.NODE_ENV": JSON.stringify("production"),
  },
  worker: {
    format: "es",
  },
});
