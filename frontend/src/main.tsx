import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { initTelemetry } from "./lib/telemetry";
import "./styles.css";
import "./ui.css";

initTelemetry();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
