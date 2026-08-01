import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "@copilotkit/react-core/v2/styles.css";
import "./styles/global.css";

const rootElement = document.getElementById("root");

if (!rootElement) {
  throw new Error("Missing root element.");
}

createRoot(rootElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
