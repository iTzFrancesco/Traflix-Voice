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
          setSize: (size: { width: number; height: number }) => Promise<void>;
          startDragging: () => Promise<void>;
          show: () => Promise<void>;
          hide: () => Promise<void>;
          center: () => Promise<void>;
          setFocus: () => Promise<void>;
        };
        LogicalSize: new (width: number, height: number) => { width: number; height: number };
      };
      app: {
        getVersion: () => Promise<string>;
      };
    };
  }
}

export {};
