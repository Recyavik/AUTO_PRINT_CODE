import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App.tsx";
import { applyTheme, savedTheme } from "./theme.ts";
import "./styles.css";

applyTheme(savedTheme());   // до первой отрисовки — без мелькания другой темы

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);

// офлайн-заглушка для окна приложения, когда помощник выключен (только в собранной версии)
if ("serviceWorker" in navigator && import.meta.env.PROD) void navigator.serviceWorker.register("/sw.js");
