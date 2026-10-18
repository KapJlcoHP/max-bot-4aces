export type Coordinates = [number, number];
export type MapLocation = { center: Coordinates; zoom: number } | { bounds: [Coordinates, Coordinates] };
export interface MapChild { readonly __yandexMapChild?: true }
export interface MapInstance {
  addChild(child: MapChild): void;
  removeChild(child: MapChild): void;
  setLocation(location: MapLocation): void;
  destroy(): void;
}
export interface YandexMapsApi {
  ready: Promise<void>;
  YMap: new (container: HTMLElement, options: { location: MapLocation }) => MapInstance;
  YMapDefaultSchemeLayer: new () => MapChild;
  YMapDefaultFeaturesLayer: new () => MapChild;
  YMapMarker: new (options: { coordinates: Coordinates }, element: HTMLElement) => MapChild;
}

declare global {
  interface Window { ymaps3?: YandexMapsApi }
}

// Both stages are bounded, including an SDK that loads but never becomes ready.
export const MAP_LOAD_TIMEOUT_MS = 12_000;

export function bounded<T>(promise: Promise<T>, signal: AbortSignal): Promise<T> {
  return new Promise((resolve, reject) => {
    const finish = (callback: () => void) => {
      clearTimeout(timer);
      signal.removeEventListener("abort", abort);
      callback();
    };
    const abort = () => finish(() => reject(new Error("Загрузка карты отменена")));
    const timer = setTimeout(() => finish(() => reject(new Error("Время загрузки карты истекло"))), MAP_LOAD_TIMEOUT_MS);
    signal.addEventListener("abort", abort, { once: true });
    // Attach both handlers even when already aborted: a late rejection is consumed.
    promise.then((value) => finish(() => resolve(value)), (error) => finish(() => reject(error)));
    if (signal.aborted) abort();
  });
}

interface LoadAttempt {
  promise: Promise<YandexMapsApi>;
  users: number;
  settled: boolean;
  cancel: () => void;
}
let current: LoadAttempt | null = null;

/** Shared while loading; the last departing consumer cancels a pending script. */
export function acquireYandexMaps(apiKey: string, lang = "ru_RU") {
  if (!current) {
    let resolve!: (api: YandexMapsApi) => void;
    let reject!: (error: Error) => void;
    const promise = new Promise<YandexMapsApi>((yes, no) => { resolve = yes; reject = no; });
    const attempt: LoadAttempt = { promise, users: 0, settled: false, cancel: () => fail(new Error("Загрузка карты отменена")) };
    current = attempt;
    let script: HTMLScriptElement | null = null;
    let api: YandexMapsApi | undefined;
    const cleanListeners = () => {
      clearTimeout(timer);
      script?.removeEventListener("load", onLoad);
      script?.removeEventListener("error", onError);
    };
    const fail = (error: Error) => {
      if (attempt.settled) return;
      attempt.settled = true;
      cleanListeners();
      script?.remove();
      // Never let an old attempt reset a newer attempt's SDK or promise.
      if (current === attempt) {
        current = null;
        if (api && window.ymaps3 === api) delete window.ymaps3;
      }
      reject(error);
    };
    const ready = () => {
      if (attempt.settled) return;
      api = window.ymaps3;
      if (!api) { fail(new Error("Yandex Maps API недоступен")); return; }
      const loaded = api;
      Promise.resolve(loaded.ready).then(() => {
        if (attempt.settled) return;
        attempt.settled = true;
        cleanListeners();
        resolve(loaded);
      }, () => fail(new Error("Yandex Maps API не готов")));
    };
    const onLoad = () => ready();
    const onError = () => fail(new Error("Не удалось загрузить Yandex Maps API"));
    const timer = setTimeout(() => fail(new Error("Время загрузки карты истекло")), MAP_LOAD_TIMEOUT_MS);
    if (window.ymaps3) {
      // Also own an earlier SDK script so failed readiness permits a fresh retry.
      script = document.getElementById("yandex-maps-v3") as HTMLScriptElement | null;
      ready();
    } else {
      // A failed/cancelled attempt must never leave a dead script to be reused.
      document.getElementById("yandex-maps-v3")?.remove();
      script = document.createElement("script");
      script.id = "yandex-maps-v3";
      script.async = true;
      script.src = `https://api-maps.yandex.ru/v3/?${new URLSearchParams({ apikey: apiKey, lang })}`;
      script.addEventListener("load", onLoad);
      script.addEventListener("error", onError);
      document.head.appendChild(script);
    }
  }
  const attempt = current;
  attempt.users += 1;
  let released = false;
  return {
    promise: attempt.promise,
    release() {
      if (released) return;
      released = true;
      attempt.users -= 1;
      if (attempt.users === 0 && !attempt.settled) attempt.cancel();
    },
  };
}
