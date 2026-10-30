import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The build goes into the Python package, where FastAPI serves it at /app (see app.py).
// In development, `npm run dev` serves the page on its own port and sends the API and the
// existing server-rendered pages to the Python app, so the browser still sees one origin.
const python = "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  base: "/app/",
  build: { outDir: "../northstar/web/spa", emptyOutDir: true },
  server: {
    proxy: Object.fromEntries(
      ["/api", "/accounts", "/balances", "/types", "/static"].map((path) => [path, python]),
    ),
  },
  // A US timezone, where new Date("2026-10-30") would show as Oct 29: the tests prove we never rely on it.
  test: { environment: "node", env: { TZ: "America/Los_Angeles" } },
});
