import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // react-force-graph-3d's sub-packages otherwise resolve to two different
  // three.js copies; a single instance is required or the scene renders blank.
  resolve: {
    dedupe: ["three"],
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
