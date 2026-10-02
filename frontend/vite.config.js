import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Em desenvolvimento, /api vai para a API local (127.0.0.1, não localhost: no Windows localhost custa ~2 s).
const API = process.env.API_URL || "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: 5173, proxy: { "/api": { target: API, rewrite: (p) => p.replace(/^\/api/, "") } } },
  test: { environment: "jsdom", setupFiles: ["./src/teste_setup.js"] },
});
