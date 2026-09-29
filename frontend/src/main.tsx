import React from "react";
import ReactDOM from "react-dom/client";
import { HelmetProvider } from "react-helmet-async";
import App from "./App";
import { initAnalytics } from "./lib/analytics";
import { initI18n, redirectToStoredLang } from "./lib/i18n";
import { initTelemetry } from "./lib/telemetry";
import "./styles.css";
import "./ui.css";

initTelemetry();
initAnalytics();

if (!redirectToStoredLang()) {
  // The non-English strings are one small JSON fetched before first paint,
  // so a Spanish visitor never sees English flash first.
  void initI18n().then(() => {
    ReactDOM.createRoot(document.getElementById("root")!).render(
      <React.StrictMode>
        <HelmetProvider>
          <App />
        </HelmetProvider>
      </React.StrictMode>
    );
  });
}
