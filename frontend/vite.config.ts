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
      // 端口被占就直接报错，不静默换端口。容器里 5173 是 docker-compose.dev.yml
      // 中 5175->5173 映射的目标端口，一旦 vite 自己换了端口，映射就会失效。
      strictPort: true,
      // 后端每个路由前缀都要列在这里。漏掉的 GET 请求会被 Vite 的 SPA 回退
      // 返回 index.html（HTTP 200），前端只会得到一个解析失败，不会看到 404。
      proxy: {
        "/conversations": backendTarget,
        "/data/raw": backendTarget,
        "/data/parsed_docs": backendTarget,
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
