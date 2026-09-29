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
  isBusy: boolean;
  showToast: (message: string, type: ToastType) => void;
}

export function useDesktopUpdater({
  enabled,
  isBusy,
  showToast,
}: UseDesktopUpdaterOptions) {
  const [update, setUpdate] = useState<DesktopUpdateNotice | null>(null);
  const updateRef = useRef<Update | null>(null);
  const isBusyRef = useRef(isBusy);
  const downloadCompleteRef = useRef(false);
  const installInFlightRef = useRef(false);
  const checkInFlightRef = useRef<Promise<void> | null>(null);
  const lastCheckAtRef = useRef(0);
  isBusyRef.current = isBusy;

  const downloadAndInstall = useCallback(async () => {
    const pendingUpdate = updateRef.current;
    if (!pendingUpdate || isBusyRef.current || installInFlightRef.current) return;

    installInFlightRef.current = true;
    try {
      if (!downloadCompleteRef.current) {
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
      }

      if (isBusyRef.current) {
        setUpdate((previous) =>
          previous ? { ...previous, state: "ready" } : previous,
        );
        return;
      }

      setUpdate((previous) =>
        previous ? { ...previous, state: "installing" } : previous,
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
    } finally {
      installInFlightRef.current = false;
    }
  }, []);

  const checkForDesktopUpdate = useCallback(
    async (force = false) => {
      if (!enabled || !window.__TAURI__?.core?.invoke || updateRef.current) return;
      if (checkInFlightRef.current) return checkInFlightRef.current;

      const now = Date.now();
      if (!force && now - lastCheckAtRef.current < UPDATE_CHECK_INTERVAL_MS) return;
      lastCheckAtRef.current = now;

      let checkPromise: Promise<void>;
      checkPromise = (async () => {
        try {
          const latest = await checkForUpdate({ timeout: 20_000 });
          if (!latest) {
            setUpdate(null);
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
            `È disponibile Traflix Voice ${latest.version}: aggiornamento automatico avviato.`,
            "info",
          );
        } catch (error) {
          console.warn("[desktop-update] check failed:", error);
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
    if (isBusy || (update?.state !== "available" && update?.state !== "ready")) return;
    void downloadAndInstall();
  }, [downloadAndInstall, isBusy, update?.state]);

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
      void downloadAndInstall();
      return;
    }
    await checkForDesktopUpdate(true);
  }, [checkForDesktopUpdate, downloadAndInstall]);

  return { update, retryUpdate };
}
