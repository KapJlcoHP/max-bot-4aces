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
      openLink?: (url: string) => void;
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

/** start_param из диплинка `?startapp=<payload>` → экран, на который надо открыть приложение.
 * Payload без двоеточий: имена экранов (route, meds, …) и шаги вида step_123. */
export function startParam(): string | null {
  return window.WebApp?.initDataUnsafe?.start_param ?? null;
}

/** start_param → путь внутри мини-апа. step_123 → /step/123. */
export function startParamPath(): string | null {
  const p = startParam();
  if (!p) return null;
  const stepMatch = /^step_(\d+)$/.exec(p);
  if (stepMatch) return `/step/${stepMatch[1]}`;
  const map: Record<string, string> = {
    home: "/",
    route: "/route",
    health: "/health",
    meds: "/meds",
    orgs: "/orgs",
    reminders: "/reminders",
    profile: "/profile",
    builder: "/builder",
    // легаси-пейлоады прежней версии
    catalog: "/builder",
    checklist: "/route",
    prep: "/route",
    family: "/family",
  };
  return map[p] ?? null;
}

export function openExternalLink(url: string): void {
  if (isInsideMax() && window.WebApp?.openLink) window.WebApp.openLink(url);
  else window.open(url, "_blank", "noopener,noreferrer");
}
