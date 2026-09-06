import DesktopApp from "./desktop/DesktopApp";
import MobileApp from "./mobile/MobileApp";

const IS_ANDROID =
  typeof navigator !== "undefined" && /Android/i.test(navigator.userAgent);

/**
 * Keep the desktop console and Android Hub as separate application shells.
 * Shared hooks and types remain available to both shells, but platform UI and
 * lifecycle code cannot run in the other product by accident.
 */
export default function App() {
  return IS_ANDROID ? <MobileApp /> : <DesktopApp />;
}
