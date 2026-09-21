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
      // 端口被占就直接报错，不再自动退到 5174/5175：
      // 静默换端口会留下多个 dev server，页面连的还是已经停掉的那个。
      strictPort: true,
      proxy: {
        "/chat": backendTarget,
        "/upload": backendTarget,
        "/validate": backendTarget,
        "/validations": backendTarget,
        "/traces": backendTarget,
        "/auth": backendTarget,
        "/transcribe": backendTarget,
        "/generate-speech": backendTarget,
        "/health": backendTarget
      }
    }
  };
});
