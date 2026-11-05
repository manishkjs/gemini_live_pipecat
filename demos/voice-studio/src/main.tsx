import { createRoot } from "react-dom/client";
import "./globals.css";
import { StudioErrorBoundary } from "./components/studio/error-boundary";
import VoiceStudio from "./components/voice-studio";

const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("Missing #root mount element");
}
createRoot(rootElement).render(
  <StudioErrorBoundary>
    <VoiceStudio />
  </StudioErrorBoundary>,
);
