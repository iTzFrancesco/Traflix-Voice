import { lazy, Suspense } from "react";

const IS_ANDROID =
  typeof navigator !== "undefined" && /Android/i.test(navigator.userAgent);

// Keep the Android Hub out of the desktop startup chunk and vice versa. The
// platform is stable for the lifetime of a WebView, so only one lazy branch is
// ever requested at runtime.
async function loadMobileApp() {
  await import("./mobile/mobile.css");
  return import("./mobile/MobileApp");
}

const PlatformApp = lazy(() =>
  IS_ANDROID ? loadMobileApp() : import("./desktop/DesktopApp"),
);

function PlatformLoading() {
  return (
    <div
      className="app-loading-shell"
      role="status"
      aria-live="polite"
      aria-busy="true"
    >
      <span className="app-loading-mark" aria-hidden="true" />
      <span>Avvio di Traflix Voice…</span>
    </div>
  );
}

/**
 * Keep the desktop console and Android Hub as separate application shells.
 * Shared hooks and types remain available to both shells, but platform UI and
 * lifecycle code cannot run in the other product by accident.
 */
export default function App() {
  return (
    <Suspense fallback={<PlatformLoading />}>
      <PlatformApp />
    </Suspense>
  );
}
