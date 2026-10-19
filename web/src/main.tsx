import { createRoot } from "react-dom/client";
import App from "./App";
import DramaWorkbench from "./DramaWorkbench";
import "./styles.css";
import { applyTheme, resolveTheme, THEME_STORAGE_KEY } from "./theme";

const isDramaWorkspace = window.location.pathname.startsWith("/drama");
document.documentElement.dataset.workspace = isDramaWorkspace ? "drama" : "vimax";

let storedTheme: string | null = null;
try {
  storedTheme = window.localStorage.getItem(THEME_STORAGE_KEY);
} catch {
  // Local storage can be unavailable in hardened browser contexts.
}
applyTheme(
  isDramaWorkspace
    ? "light"
    : resolveTheme(
        storedTheme,
        window.matchMedia("(prefers-color-scheme: dark)").matches,
      ),
);

createRoot(document.getElementById("root")!).render(
  isDramaWorkspace ? <DramaWorkbench /> : <App />,
);
