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

function loadYandexMaps(apiKey: string, lang = "ru_RU"): Promise<void> {
  if (window.ymaps3) return Promise.resolve();
  if (yandexScript) return yandexScript;

  yandexScript = new Promise<void>((resolve, reject) => {
    const existing = document.getElementById("yandex-maps-v3") as HTMLScriptElement | null;
    const script = existing ?? document.createElement("script");
    const onLoad = () => (window.ymaps3 ? resolve() : reject(new Error("Yandex Maps API не загрузился")));
    const onError = () => reject(new Error("Не удалось загрузить Yandex Maps API"));

    script.addEventListener("load", onLoad, { once: true });
    script.addEventListener("error", onError, { once: true });
    if (!existing) {
      script.id = "yandex-maps-v3";
      script.async = true;
      script.src = `https://api-maps.yandex.ru/v3/?${new URLSearchParams({ apikey: apiKey, lang })}`;
      document.head.appendChild(script);
    }
  }).catch((error: unknown) => {
    yandexScript = null;
    throw error;
  });

  return yandexScript;
}

function coordinatesOf(org: Organization): Coordinates | null {
  if (typeof org.lat !== "number" || typeof org.lon !== "number") return null;
  if (!Number.isFinite(org.lat) || !Number.isFinite(org.lon)) return null;
  if (org.lat < -90 || org.lat > 90 || org.lon < -180 || org.lon > 180) return null;
  return [org.lon, org.lat];
}

function MapFallback({ message }: { message: string }) {
  return (
    <div className="map-fallback" role="status">
      <span className="map-fallback-pin" aria-hidden="true">⌖</span>
      <span>{message}</span>
    </div>
  );
}

export interface OrganizationMapProps {
  organizations: Organization[];
  selectedId?: number | null;
  onSelect: (id: number) => void;
  className?: string;
}

/** Неблокирующая карта: при любом сбое список организаций продолжает работать. */
export default function OrganizationMap({ organizations, selectedId, onSelect, className = "" }: OrganizationMapProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const selectRef = useRef(onSelect);
  const [state, setState] = useState<"loading" | "ready" | "fallback">("loading");
  const [message, setMessage] = useState("Загружаем карту…");

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
    setMessage("Загружаем карту…");

    if (mapped.length === 0) {
      setState("fallback");
      setMessage("Для этих организаций пока нет координат карты");
      return () => { active = false; };
    }

    (async () => {
      try {
        const config = await api.get<MapConfig>("/api/v1/maps/config");
        if (!config.enabled || !config.api_key) throw new Error("Ключ карты не настроен");
        await loadYandexMaps(config.api_key, config.lang);
        const ymaps = window.ymaps3;
        if (!ymaps) throw new Error("Yandex Maps API недоступен");
        await ymaps.ready;
        if (!active || !containerRef.current) return;

        const average = mapped.reduce(
          (sum, item) => [sum[0] + item.coordinates[0], sum[1] + item.coordinates[1]] as Coordinates,
          [0, 0] as Coordinates,
        );
        const center: Coordinates = [average[0] / mapped.length, average[1] / mapped.length];
        map = new ymaps.YMap(containerRef.current, {
          location: { center, zoom: mapped.length === 1 ? 15 : 10 },
        }, [new ymaps.YMapDefaultSchemeLayer(), new ymaps.YMapDefaultFeaturesLayer()]);

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
      } catch (error: unknown) {
        if (!active) return;
        setState("fallback");
        setMessage(error instanceof Error && error.message === "Ключ карты не настроен"
          ? "Карта временно недоступна: ключ не настроен"
          : "Карту не удалось загрузить — используйте список или маршрут");
      }
    })();

    return () => {
      active = false;
      map?.destroy?.();
      map = null;
    };
  }, [organizations, selectedId]);

  return (
    <div className={`organization-map-wrap ${className}`}>
      {state === "fallback" && <MapFallback message={message} />}
      {state === "loading" && <MapFallback message={message} />}
      <div ref={containerRef} className={`organization-map${state === "ready" ? " is-ready" : ""}`} aria-label="Карта организаций" />
    </div>
  );
}
