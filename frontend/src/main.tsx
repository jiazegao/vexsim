import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { forgetTokenInUrl, stayPresent } from "./api";
import { App } from "./App";
import "./styles.css";

forgetTokenInUrl();
stayPresent();
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
