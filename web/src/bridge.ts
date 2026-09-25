/** Типизированная обёртка MAX Bridge (window.WebApp, подключается через CDN в index.html). */

declare global {
  interface Window {
    WebApp?: {
      initData?: string;
      initDataUnsafe?: {
        user?: { id: number; first_name?: string; last_name?: string };
        chat?: { id: number; type?: string };
        start_param?: string;
        [k: string]: unknown;
      };
      platform?: string;
      version?: string;
      getLaunchContext?: () => unknown;
      requestContact?: () => unknown;
      getViewportSize?: () => unknown;
    };
  }
}

export function getInitData(): string | null {
  return window.WebApp?.initData ?? null;
}

export function isInsideMax(): boolean {
  return Boolean(window.WebApp?.initData);
}

export function maxPlatform(): string {
  return window.WebApp?.platform ?? "web";
}

/** start_param из диплинка `?startapp=<payload>` → экран, на который надо открыть приложен��е. */
export function startParam(): string | null {
  return window.WebApp?.initDataUnsafe?.start_param ?? null;
}
