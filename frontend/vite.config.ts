/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // react-force-graph-3d's sub-packages otherwise resolve to two different
  // three.js copies; a single instance is required or the scene renders blank.
  resolve: {
    dedupe: ["three"],
  },
  // The app is fully static (reads snapshot.json); no backend proxy needed.
  server: {
    port: 5173,
  },
  // jsdom lets component tests render; api.test.ts stubs fetch and is unaffected.
  test: {
    environment: "jsdom",
  },
});
