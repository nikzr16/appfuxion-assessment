import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The dev server forwards /api to the FastAPI backend (the nginx container does the
// same in Docker), so the browser only ever talks to one origin.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.VITE_BACKEND_URL ?? "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    rollupOptions: {
      output: {
        // Libraries change less often than the app: their own chunk caches across releases
        // and keeps every chunk under the 500 kB warning.
        manualChunks: {
          react: ["react", "react-dom", "react-router"],
          query: ["@tanstack/react-query"],
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    testTimeout: 15_000, // room for setup.ts's 5 s findBy* waits on a slow machine
  },
});
