/// <reference types="vite/client" />

declare global {
  interface Window {
    __TAURI__: {
      core: {
        invoke: (cmd: string, args?: Record<string, unknown>) => Promise<unknown>;
      };
      event: {
        listen: (event: string, handler: (event: { payload: unknown }) => void) => Promise<() => void>;
        emit: (event: string, payload?: unknown) => Promise<void>;
      };
      window: {
        getCurrentWindow: () => {
          startDragging: () => Promise<void>;
          outerPosition: () => Promise<{ x: number; y: number }>;
          show: () => Promise<void>;
          hide: () => Promise<void>;
          center: () => Promise<void>;
          setFocus: () => Promise<void>;
        };
      };
      app: {
        getVersion: () => Promise<string>;
      };
    };
  }
}

export {};
