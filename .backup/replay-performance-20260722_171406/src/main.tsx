import { createRoot } from "react-dom/client";
import App from "./App";
import { DashboardErrorBoundary } from "./components/DashboardErrorBoundary";
import "./styles/app.css";

const root = document.getElementById("root");
if (!root) throw new Error("Root element not found");

window.addEventListener("unhandledrejection", event => {
  console.error("Unhandled dashboard promise rejection", event.reason);
});

window.addEventListener("error", event => {
  console.error("Unhandled dashboard runtime error", event.error ?? event.message);
});

createRoot(root, {
  onUncaughtError: (error, info) => {
    console.error("Uncaught VEX dashboard error", error, info.componentStack);
    showFatalOverlay(error);
  },
  onCaughtError: (error, info) => {
    console.error("Caught VEX dashboard error", error, info.componentStack);
  },
  onRecoverableError: (error, info) => {
    console.warn("Recoverable VEX dashboard error", error, info.componentStack);
  }
}).render(
  <DashboardErrorBoundary>
    <App />
  </DashboardErrorBoundary>
);

function showFatalOverlay(error: unknown): void {
  if (document.getElementById("vex-fatal-overlay")) return;
  const overlay = document.createElement("div");
  overlay.id = "vex-fatal-overlay";
  overlay.className = "dashboard-fatal-overlay";

  const card = document.createElement("section");
  card.className = "dashboard-fatal-card";

  const title = document.createElement("h1");
  title.textContent = "Dashboard renderer stopped safely";

  const description = document.createElement("p");
  description.textContent = "The backtest engine continues in the background. Reload the browser view to reconnect.";

  const detail = document.createElement("pre");
  detail.textContent = error instanceof Error ? error.message : String(error);

  const reload = document.createElement("button");
  reload.type = "button";
  reload.textContent = "Reload dashboard";
  reload.addEventListener("click", () => window.location.reload());

  card.append(title, description, detail, reload);
  overlay.append(card);
  document.body.append(overlay);
}
