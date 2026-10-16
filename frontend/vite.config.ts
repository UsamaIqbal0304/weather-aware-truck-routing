import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the Django server runs on :8000 and Vite on :5173. Proxying
// /api keeps the browser on one origin, so the app needs no CORS middleware
// in development and none in production either, where Vercel serves the
// static build and the Python function from the same host.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.VITE_API_TARGET ?? "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    rollupOptions: {
      output: {
        // MapLibre is ~800 kB on its own. Splitting it out means a change to
        // our own code does not invalidate the map bundle in a user's cache.
        manualChunks: { maplibre: ["maplibre-gl"] },
      },
    },
  },
});
