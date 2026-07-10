import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "");
  const backendTarget = env.VITE_BACKEND_TARGET || "http://127.0.0.1:8000";

  return {
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
  };
});
