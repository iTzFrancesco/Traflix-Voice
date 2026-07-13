import { useEffect, useCallback, useRef } from "react";

type EventHandler = (payload: unknown) => void;

/**
 * Listen for a Tauri event. Returns a cleanup function.
 */
export function useTauriEvent(eventName: string, handler: EventHandler) {
  const handlerRef = useRef<EventHandler>(handler);
  handlerRef.current = handler;

  useEffect(() => {
    let unlisten: (() => void) | null = null;

    if (window.__TAURI__?.event?.listen) {
      window.__TAURI__.event
        .listen(eventName, (event: { payload: unknown }) => {
          handlerRef.current(event.payload);
        })
        .then((fn: () => void) => {
          unlisten = fn;
        })
        .catch((err: unknown) => {
          console.warn(`[tauri-event] Failed to listen to ${eventName}:`, err);
        });
    }

    return () => {
      if (unlisten) unlisten();
    };
  }, [eventName]);
}

/**
 * Emit a Tauri event.
 */
export function useTauriEmit() {
  const emit = useCallback((eventName: string, payload?: unknown) => {
    if (window.__TAURI__?.event?.emit) {
      window.__TAURI__.event.emit(eventName, payload).catch((err: unknown) => {
        console.warn(`[tauri-emit] Failed to emit ${eventName}:`, err);
      });
    }
  }, []);

  return emit;
}

/**
 * Invoke a Tauri command.
 */
export function useTauriInvoke() {
  const invoke = useCallback(
    (cmd: string, args?: Record<string, unknown>): Promise<unknown> => {
      if (window.__TAURI__?.core?.invoke) {
        return window.__TAURI__.core.invoke(cmd, args);
      }
      return Promise.reject(new Error("__TAURI__ not available"));
    },
    []
  );

  return invoke;
}
