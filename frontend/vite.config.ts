import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const backendTarget = "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: {
      "/chat": backendTarget,
      "/upload": backendTarget,
      "/validate": backendTarget,
      "/transcribe": backendTarget,
      "/generate-speech": backendTarget,
      "/uploads": backendTarget,
      "/data": backendTarget,
      "/health": backendTarget
    }
  }
});
