import React from "react";
import ReactDOM from "react-dom/client";
import { HelmetProvider } from "react-helmet-async";
import App from "./App";
import { initAnalytics } from "./lib/analytics";
import { initTelemetry } from "./lib/telemetry";
import "./styles.css";
import "./ui.css";

initTelemetry();
initAnalytics();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <HelmetProvider>
      <App />
    </HelmetProvider>
  </React.StrictMode>
);
