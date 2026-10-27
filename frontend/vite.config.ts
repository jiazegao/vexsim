import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// `npm run build` writes the app into the Python package, where `vexsim ui` serves it.
// `npm run dev` serves it from here instead, passing /api to a `vexsim ui --dev` started
// on the default port (open the link it prints once, for its cookie, then this server).
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../vexsim/ui/static",
    emptyOutDir: true,
    assetsDir: "assets",
  },
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8642", ws: true, changeOrigin: true },
    },
  },
  test: {
    include: ["tests/**/*.test.ts"],
    environment: "node",
  },
});
