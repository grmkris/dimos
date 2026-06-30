import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import topLevelAwait from "vite-plugin-top-level-await";
import wasm from "vite-plugin-wasm";

const r = (p: string) => fileURLToPath(new URL(p, import.meta.url));

// The library lives in ../packages and is consumed by alias (so the example app
// demonstrates the real @dimos/topics + @dimos/react surface). dedupe keeps a
// single React copy across the app + the aliased packages.
export default defineConfig({
  // wasm + topLevelAwait: @eclipse-zenoh/zenoh-ts ships a WASM module via the ESM
  // integration import, which Vite can't handle without these plugins.
  plugins: [wasm(), topLevelAwait(), react()],
  // Exclude WASM-shipping deps from esbuild pre-bundling so Vite serves their files
  // directly: the Rerun viewer (.wasm MIME) and zenoh-ts (vite-plugin-wasm handles it).
  // But DO pre-bundle zenoh-ts's CommonJS deps (e.g. channel-ts) so their named exports
  // resolve when the raw-served zenoh-ts imports them.
  optimizeDeps: {
    exclude: [
      "@rerun-io/web-viewer",
      "@rerun-io/web-viewer-react",
      "@eclipse-zenoh/zenoh-ts",
    ],
    include: [
      "channel-ts",
      "base64-arraybuffer",
      "uuid",
      "tslog",
      "typed-duration",
      "@thi.ng/leb128",
    ],
  },
  resolve: {
    alias: {
      "@dimos/react": r("../../packages/react/src/index.tsx"),
      "@dimos/topics": r("../../packages/topics/src/index.ts"),
    },
    dedupe: ["react", "react-dom"],
  },
  // Multi-page: the app (index.html) + the in-browser benchmark (bench.html). Dev serves
  // any .html directly; build needs both entries listed here.
  build: {
    rollupOptions: {
      input: { main: r("./index.html"), bench: r("./bench.html") },
    },
  },
  server: { host: true, port: 5173 },
});
