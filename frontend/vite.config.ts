import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        // Not Vite's index-*.js. Tabs still running the reverted
        // lib/freshBuild.ts (#517) reload when index.html names an
        // /assets/index-*.js other than their own, and on an iPhone that
        // reload left a blank page. They don't look for any other name.
        entryFileNames: "assets/app-[hash].js",
        // The libraries (React, the router, i18next, Supabase, Faro) in a
        // file of their own: it changes only when a dependency does, so a
        // returning visitor keeps it cached across our deploys and fetches
        // just the app's own code again (nginx marks /assets/ immutable).
        manualChunks(id) {
          if (id.includes("/node_modules/")) return "vendor";
        },
      },
    },
  },
  server: {
    host: true,
    port: 3000,
  },
  preview: {
    host: true,
    port: 3000,
  },
});
