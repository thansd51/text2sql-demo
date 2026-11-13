import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// 로컬 개발: 화면은 5173, API는 Vite 프록시로 백엔드(8085)에 전달한다.
// 배포: FastAPI가 빌드 결과(dist)를 같은 출처로 제공하므로 API 주소는 상대 경로(/api/v1)다.
const backend = "http://localhost:8085";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": backend,
      "/health": backend,
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.js",
  },
});
