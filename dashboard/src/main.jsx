import React from "react";
import ReactDOM from "react-dom/client";
import { RouterProvider } from "react-router-dom";
import router from "./router";
import "./index.css";

async function bootstrap() {
  const mockEnabled =
    import.meta.env.DEV &&
    String(import.meta.env.VITE_ENABLE_MSW || "false").toLowerCase() === "true";

  if (mockEnabled) {
    try {
      const { worker } = await import("./mocks/browser");
      await worker.start({ onUnhandledRequest: "bypass" });
    } catch (error) {
      console.warn("MSW failed to start, continuing without request mocking.", error);
    }
  }

  ReactDOM.createRoot(document.getElementById("root")).render(
    <React.StrictMode>
      {import.meta.env.VITE_USE_MOCKS === "true" ||
      (import.meta.env.DEV && import.meta.env.VITE_DEV_MOCK_FALLBACK === "true") ? (
        <div
          role="status"
          className="fixed bottom-3 right-3 z-[100] rounded border border-amber-400/50 bg-amber-950/95 px-3 py-2 text-xs font-semibold text-amber-100 shadow-lg"
        >
          MOCK DATA MODE · not live inference
        </div>
      ) : null}
      <RouterProvider router={router} />
    </React.StrictMode>
  );
}

bootstrap();
