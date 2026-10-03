import { useCallback, useEffect, useRef, useState } from "react";
import { check as checkForUpdate, type Update } from "@tauri-apps/plugin-updater";
import type { ToastType } from "../types";

const UPDATE_CHECK_INTERVAL_MS = 6 * 60 * 60 * 1000;

export type DesktopUpdateState =
  | "available"
  | "downloading"
  | "ready"
  | "installing"
  | "error";

export interface DesktopUpdateNotice {
  currentVersion: string;
  version: string;
  notes: string;
  state: DesktopUpdateState;
  downloadedBytes: number;
  contentLength: number | null;
  error: string;
}

interface UseDesktopUpdaterOptions {
  enabled: boolean;
  isBusyNow: () => boolean;
  showToast: (message: string, type: ToastType) => void;
}

export function useDesktopUpdater({
  enabled,
  isBusyNow,
  showToast,
}: UseDesktopUpdaterOptions) {
  const [update, setUpdate] = useState<DesktopUpdateNotice | null>(null);
  const [isCheckingForUpdate, setIsCheckingForUpdate] = useState(false);
  const updateRef = useRef<Update | null>(null);
  const isBusyNowRef = useRef(isBusyNow);
  const downloadCompleteRef = useRef(false);
  const installInFlightRef = useRef(false);
  const isInstallingRef = useRef(false);
  const checkInFlightRef = useRef<Promise<void> | null>(null);
  const lastCheckAtRef = useRef(0);
  isBusyNowRef.current = isBusyNow;

  const downloadUpdate = useCallback(async () => {
    const pendingUpdate = updateRef.current;
    if (!pendingUpdate || downloadCompleteRef.current || installInFlightRef.current) return;

    installInFlightRef.current = true;
    try {
      let downloadedBytes = 0;
      let contentLength: number | null = null;
      setUpdate((previous) =>
        previous ? { ...previous, state: "downloading", error: "" } : previous,
      );

      await pendingUpdate.download((event) => {
        if (event.event === "Started") {
          contentLength = event.data.contentLength ?? null;
        } else if (event.event === "Progress") {
          downloadedBytes += event.data.chunkLength;
        }
        setUpdate((previous) =>
          previous
            ? { ...previous, downloadedBytes, contentLength }
            : previous,
        );
      });
      downloadCompleteRef.current = true;
      setUpdate((previous) =>
        previous ? { ...previous, state: "ready" } : previous,
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      console.warn("[desktop-update] download failed:", error);
      updateRef.current = null;
      downloadCompleteRef.current = false;
      await pendingUpdate.close().catch(() => {});
      setUpdate((previous) =>
        previous ? { ...previous, state: "error", error: message } : previous,
      );
    } finally {
      installInFlightRef.current = false;
    }
  }, []);

  const installUpdate = useCallback(async () => {
    const pendingUpdate = updateRef.current;
    if (
      !pendingUpdate ||
      !downloadCompleteRef.current ||
      isBusyNowRef.current() ||
      installInFlightRef.current
    ) return;

    installInFlightRef.current = true;
    isInstallingRef.current = true;
    try {
      setUpdate((previous) =>
        previous ? { ...previous, state: "installing", error: "" } : previous,
      );
      await window.__TAURI__.core.invoke("shutdown_python");
      await pendingUpdate.install({ restartAfterInstall: true });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      console.warn("[desktop-update] install failed:", error);
      updateRef.current = null;
      downloadCompleteRef.current = false;
      await pendingUpdate.close().catch(() => {});
      setUpdate((previous) =>
        previous ? { ...previous, state: "error", error: message } : previous,
      );
      await new Promise((resolve) => window.setTimeout(resolve, 1800));
      await window.__TAURI__.core.invoke("restart_app");
    } finally {
      isInstallingRef.current = false;
      installInFlightRef.current = false;
    }
  }, []);

  const dismissUpdate = useCallback(async () => {
    if (installInFlightRef.current) return;
    const pendingUpdate = updateRef.current;
    updateRef.current = null;
    downloadCompleteRef.current = false;
    setUpdate(null);
    await pendingUpdate?.close().catch(() => {});
  }, []);

  const checkForDesktopUpdate = useCallback(
    async (force = false) => {
      if (!enabled || !window.__TAURI__?.core?.invoke) return;
      if (updateRef.current) {
        if (force) {
          showToast(`È già disponibile Traflix Voice ${updateRef.current.version}.`, "info");
        }
        return;
      }
      if (checkInFlightRef.current) return checkInFlightRef.current;

      const now = Date.now();
      if (!force && now - lastCheckAtRef.current < UPDATE_CHECK_INTERVAL_MS) return;
      lastCheckAtRef.current = now;
      setIsCheckingForUpdate(true);

      let checkPromise: Promise<void>;
      checkPromise = (async () => {
        try {
          const latest = await checkForUpdate({ timeout: 20_000 });
          if (!latest) {
            setUpdate(null);
            if (force) showToast("Traflix Voice è già aggiornato.", "success");
            return;
          }

          updateRef.current = latest;
          downloadCompleteRef.current = false;
          setUpdate({
            currentVersion: latest.currentVersion,
            version: latest.version,
            notes: latest.body ?? "",
            state: "available",
            downloadedBytes: 0,
            contentLength: null,
            error: "",
          });
          showToast(
            `È disponibile Traflix Voice ${latest.version}. Puoi scegliere quando scaricarlo e installarlo.`,
            "info",
          );
        } catch (error) {
          console.warn("[desktop-update] check failed:", error);
          if (force) {
            showToast("Impossibile controllare gli aggiornamenti. Verifica la connessione e riprova.", "error");
          }
        } finally {
          setIsCheckingForUpdate(false);
        }
      })().finally(() => {
        if (checkInFlightRef.current === checkPromise) {
          checkInFlightRef.current = null;
        }
      });
      checkInFlightRef.current = checkPromise;
      return checkPromise;
    },
    [enabled, showToast],
  );

  useEffect(() => {
    if (!enabled) return;

    const startupTimer = window.setTimeout(() => {
      void checkForDesktopUpdate();
    }, 1800);
    const checkWhenResumed = () => {
      if (document.visibilityState === "visible") void checkForDesktopUpdate();
    };
    window.addEventListener("focus", checkWhenResumed);
    window.addEventListener("pageshow", checkWhenResumed);
    document.addEventListener("visibilitychange", checkWhenResumed);

    return () => {
      window.clearTimeout(startupTimer);
      window.removeEventListener("focus", checkWhenResumed);
      window.removeEventListener("pageshow", checkWhenResumed);
      document.removeEventListener("visibilitychange", checkWhenResumed);
    };
  }, [checkForDesktopUpdate, enabled]);

  const retryUpdate = useCallback(async () => {
    if (updateRef.current) {
      if (downloadCompleteRef.current) void installUpdate();
      else void downloadUpdate();
      return;
    }
    await checkForDesktopUpdate(true);
  }, [checkForDesktopUpdate, downloadUpdate, installUpdate]);

  const checkForUpdateNow = useCallback(
    () => checkForDesktopUpdate(true),
    [checkForDesktopUpdate],
  );

  return {
    update,
    isCheckingForUpdate,
    checkForUpdateNow,
    isInstallingRef,
    retryUpdate,
    downloadUpdate,
    installUpdate,
    dismissUpdate,
  };
}
