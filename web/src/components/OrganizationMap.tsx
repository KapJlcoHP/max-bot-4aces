import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { MapConfig, Organization } from "../types";

type Coordinates = [number, number];

interface YMapLocation {
  center: Coordinates;
  zoom: number;
}

interface YMapOptions {
  location: YMapLocation;
}

interface YMapMarkerOptions {
  coordinates: Coordinates;
}

interface YMapChild {
  readonly __yandexMapChild?: true;
}

interface YMapInstance {
  addChild(child: YMapChild): void;
  removeChild?(child: YMapChild): void;
  destroy?(): void;
}

interface YandexMapsApi {
  ready: Promise<void>;
  YMap: new (container: HTMLElement, options: YMapOptions, children?: YMapChild[]) => YMapInstance;
  YMapDefaultSchemeLayer: new () => YMapChild;
  YMapDefaultFeaturesLayer: new () => YMapChild;
  YMapMarker: new (options: YMapMarkerOptions, element: HTMLElement) => YMapChild;
}

declare global {
  interface Window {
    ymaps3?: YandexMapsApi;
  }
}

let yandexScript: Promise<void> | null = null;
const MAP_LOAD_ATTEMPTS = 3;
const MAP_LOAD_TIMEOUT_MS = 15_000;
const MAP_RETRY_DELAY_MS = 750;

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function loadYandexMapsAttempt(apiKey: string, lang: string): Promise<void> {
  if (window.ymaps3) return Promise.resolve();

  // После неудачной попытки старый script может остаться в DOM уже в
  // завершённом состоянии. Повторно подписаться на его load нельзя — удаляем
  // его и создаём новый элемент.
  document.getElementById("yandex-maps-v3")?.remove();

  return new Promise<void>((resolve, reject) => {
    const script = document.createElement("script");
    let timer = 0;
    let settled = false;

    const cleanup = () => {
      window.clearTimeout(timer);
      script.removeEventListener("load", onLoad);
      script.removeEventListener("error", onError);
    };
    const fail = (error: Error) => {
      if (settled) return;
      settled = true;
      cleanup();
      script.remove();
      reject(error);
    };
    const onLoad = () => {
      if (window.ymaps3) {
        settled = true;
        cleanup();
        resolve();
      } else {
        fail(new Error("Yandex Maps API не загрузился"));
      }
    };
    const onError = () => fail(new Error("Не удалось загрузить Yandex Maps API"));

    script.id = "yandex-maps-v3";
    script.async = true;
    // MAX WebView может выбрать слишком строгую политику referrer.
    // Яндекс проверяет доменное ограничение JS API по HTTP Referer.
    script.referrerPolicy = "origin";
    script.src = `https://api-maps.yandex.ru/v3/?${new URLSearchParams({ apikey: apiKey, lang })}`;
    script.addEventListener("load", onLoad, { once: true });
    script.addEventListener("error", onError, { once: true });
    timer = window.setTimeout(
      () => fail(new Error("Превышено время загрузки Yandex Maps API")),
      MAP_LOAD_TIMEOUT_MS,
    );
    document.head.appendChild(script);
  });
}

function loadYandexMaps(apiKey: string, lang = "ru_RU"): Promise<void> {
  if (window.ymaps3) return Promise.resolve();
  if (yandexScript) return yandexScript;

  yandexScript = (async () => {
    let lastError: unknown = new Error("Yandex Maps API недоступен");
    for (let attempt = 1; attempt <= MAP_LOAD_ATTEMPTS; attempt += 1) {
      try {
        await loadYandexMapsAttempt(apiKey, lang);
        return;
      } catch (error: unknown) {
        lastError = error;
        if (attempt < MAP_LOAD_ATTEMPTS) await wait(MAP_RETRY_DELAY_MS);
      }
    }
    throw lastError;
  })().finally(() => {
    yandexScript = null;
  });

  return yandexScript;
}

function waitForYandexReady(ymaps: YandexMapsApi): Promise<void> {
  return new Promise<void>((resolve, reject) => {
    const timer = window.setTimeout(
      () => reject(new Error("Yandex Maps API долго не готовится")),
      MAP_LOAD_TIMEOUT_MS,
    );
    ymaps.ready.then(() => {
      window.clearTimeout(timer);
      resolve();
    }).catch((error: unknown) => {
      window.clearTimeout(timer);
      reject(error);
    });
  });
}

function coordinatesOf(org: Organization): Coordinates | null {
  if (typeof org.lat !== "number" || typeof org.lon !== "number") return null;
  if (!Number.isFinite(org.lat) || !Number.isFinite(org.lon)) return null;
  if (org.lat < -90 || org.lat > 90 || org.lon < -180 || org.lon > 180) return null;
  return [org.lon, org.lat];
}

export interface OrganizationMapProps {
  organizations: Organization[];
  selectedId?: number | null;
  onSelect: (id: number) => void;
  onAvailabilityChange?: (available: boolean) => void;
  className?: string;
}

/** Карта — прогрессивное улучшение: при сбое она полностью исчезает, список продолжает работать. */
export default function OrganizationMap({
  organizations,
  selectedId,
  onSelect,
  onAvailabilityChange,
  className = "",
}: OrganizationMapProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const selectRef = useRef(onSelect);
  const [state, setState] = useState<"loading" | "ready" | "unavailable">("loading");

  useEffect(() => {
    selectRef.current = onSelect;
  }, [onSelect]);

  useEffect(() => {
    let active = true;
    let map: YMapInstance | null = null;
    const mapped = organizations
      .map((organization) => ({ organization, coordinates: coordinatesOf(organization) }))
      .filter((item): item is { organization: Organization; coordinates: Coordinates } => item.coordinates !== null);

    setState("loading");
    onAvailabilityChange?.(false);

    if (mapped.length === 0) {
      setState("unavailable");
      return () => { active = false; };
    }

    (async () => {
      try {
        const config = await api.get<MapConfig>("/api/v1/maps/config");
        if (!config.enabled || !config.api_key) throw new Error("Ключ карты не настроен");
        await loadYandexMaps(config.api_key, config.lang);
        const ymaps = window.ymaps3;
        if (!ymaps) throw new Error("Yandex Maps API недоступен");
        await waitForYandexReady(ymaps);
        if (!active || !containerRef.current) return;

        const selected = selectedId == null
          ? null
          : mapped.find((item) => item.organization.id === selectedId) ?? null;
        const average = mapped.reduce(
          (sum, item) => [sum[0] + item.coordinates[0], sum[1] + item.coordinates[1]] as Coordinates,
          [0, 0] as Coordinates,
        );
        const center: Coordinates = selected
          ? selected.coordinates
          : [average[0] / mapped.length, average[1] / mapped.length];
        // В JS API v3 слои добавляются после создания карты. Передача их
        // третьим аргументом конструктора игнорируется браузером и даёт
        // пустой контейнер без тайлов.
        map = new ymaps.YMap(containerRef.current, {
          location: { center, zoom: selected || mapped.length === 1 ? 15 : 10 },
        });
        map.addChild(new ymaps.YMapDefaultSchemeLayer());
        map.addChild(new ymaps.YMapDefaultFeaturesLayer());

        mapped.forEach(({ organization, coordinates }) => {
          const marker = document.createElement("button");
          marker.type = "button";
          marker.className = `organization-marker${organization.id === selectedId ? " selected" : ""}`;
          marker.title = organization.title;
          marker.setAttribute("aria-label", organization.title);
          marker.addEventListener("click", () => selectRef.current(organization.id));
          map?.addChild(new ymaps.YMapMarker({ coordinates }, marker));
        });
        setState("ready");
        onAvailabilityChange?.(true);
      } catch (error: unknown) {
        if (!active) return;
        setState("unavailable");
        onAvailabilityChange?.(false);
      }
    })();

    return () => {
      active = false;
      map?.destroy?.();
      map = null;
    };
  }, [organizations, selectedId, onAvailabilityChange]);

  if (state !== "ready") return null;
  return <div className={`organization-map-wrap ${className}`}><div ref={containerRef} className="organization-map is-ready" aria-label="Карта организаций" /></div>;
}
