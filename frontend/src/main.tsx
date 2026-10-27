import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { forgetTokenInUrl } from "./api";
import { App } from "./App";
import "./styles.css";

forgetTokenInUrl();
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
