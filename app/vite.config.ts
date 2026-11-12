import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  clearScreen: false,
  define: {
    "import.meta.env.VITE_APP_RUNTIME": JSON.stringify(mode === "web" ? "web" : "desktop"),
  },
  server: {
    port: 1420,
    strictPort: true,
    proxy: {
      "^/(api|auth|login|register|forgot-password|reset-password)(/|\\?|$)": {
        target: "http://127.0.0.1:8765",
        changeOrigin: true,
      },
    },
  },
}));
