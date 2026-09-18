import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// base must match the path this app is served under, or every asset URL in
// index.html points at the main app's root and 404s. Same origin as
// schoolz-web is the whole point: localStorage (and so the auth session,
// in both auth modes) is origin-scoped, so serving this from a path on the
// same host means the session is shared with no token passing at all.
export default defineConfig({
  base: "/focus/",
  plugins: [react()],
  server: {
    host: true,
    port: 3001,
  },
  preview: {
    host: true,
    port: 3001,
  },
});
