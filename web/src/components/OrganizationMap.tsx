import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { MapConfig, Organization } from "../types";
import { acquireYandexMaps, bounded, type Coordinates, type MapChild, type MapInstance, type MapLocation, type YandexMapsApi } from "./organizationMapSdk";

export function coordinatesOf(org: Organization): Coordinates | null {
  if (typeof org.lat !== "number" || typeof org.lon !== "number") return null;
  if (!Number.isFinite(org.lat) || !Number.isFinite(org.lon)) return null;
  if (org.lat < -90 || org.lat > 90 || org.lon < -180 || org.lon > 180) return null;
  return [org.lon, org.lat];
}

function cameraFor(organizations: Organization[], selectedId?: number | null): MapLocation {
  const selected = organizations.find((org) => org.id === selectedId);
  const selectedCoordinates = selected && coordinatesOf(selected);
  if (selectedCoordinates) return { center: selectedCoordinates, zoom: 15 };
  const points = organizations.map(coordinatesOf).filter((point): point is Coordinates => point !== null);
  if (points.length === 1) return { center: points[0], zoom: 15 };
  if (!points.length) return { bounds: [[-180, -85], [180, 85]] };
  const longitudes = points.map(([lon]) => lon);
  const latitudes = points.map(([, lat]) => lat);
  // Bounds let the SDK choose zoom for the actual viewport and visible results.
  return { bounds: [[Math.min(...longitudes), Math.min(...latitudes)], [Math.max(...longitudes), Math.max(...latitudes)]] };
}

interface Marker {
  child: MapChild;
  element: HTMLButtonElement;
  coordinates: Coordinates;
  click: () => void;
}

function MapFallback({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="map-fallback" role="status">
      <span className="map-fallback-pin" aria-hidden="true">⌖</span>
      <span>{message}</span>
      {onRetry && <button type="button" className="map-retry" onClick={onRetry}>Повторить загрузку карты</button>}
    </div>
  );
}

export interface OrganizationMapProps {
  organizations: Organization[];
  selectedId?: number | null;
  onSelect: (id: number) => void;
  className?: string;
}

/** SDK/map lifetime is independent from catalog, selection and callback updates. */
export default function OrganizationMap({ organizations, selectedId, onSelect, className = "" }: OrganizationMapProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const selectRef = useRef(onSelect);
  const latestRef = useRef({ organizations, selectedId });
  const mapRef = useRef<MapInstance | null>(null);
  const sdkRef = useRef<YandexMapsApi | null>(null);
  const markersRef = useRef(new Map<number, Marker>());
  const cameraRef = useRef("");
  const previousViewRef = useRef<{ points: string; selectedId?: number | null }>({ points: "" });
  const [started, setStarted] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<"loading" | "ready" | "fallback">("loading");
  const [message, setMessage] = useState("Загружаем карту…");
  const hasCoordinates = organizations.some((org) => coordinatesOf(org) !== null);

  useEffect(() => {
    selectRef.current = onSelect;
    latestRef.current = { organizations, selectedId };
  }, [organizations, selectedId, onSelect]);

  useEffect(() => {
    if (hasCoordinates) setStarted(true);
  }, [hasCoordinates]);

  useEffect(() => {
    if (!started) return;
    let active = true;
    const controller = new AbortController();
    let lease: ReturnType<typeof acquireYandexMaps> | undefined;
    const destroy = () => {
      for (const marker of markersRef.current.values()) marker.element.removeEventListener("click", marker.click);
      markersRef.current.clear();
      mapRef.current?.destroy();
      mapRef.current = null;
      sdkRef.current = null;
      cameraRef.current = "";
      previousViewRef.current = { points: "" };
    };
    setState("loading");
    setMessage("Загружаем карту…");
    void (async () => {
      try {
        const config = await bounded(api.get<MapConfig>("/api/v1/maps/config"), controller.signal);
        if (!active) return;
        if (!config.enabled || !config.api_key) throw new Error("Ключ карты не настроен");
        lease = acquireYandexMaps(config.api_key, config.lang);
        const sdk = await lease.promise;
        if (!active || !containerRef.current) return;
        const latest = latestRef.current;
        const location = cameraFor(latest.organizations, latest.selectedId);
        const map = new sdk.YMap(containerRef.current, { location });
        mapRef.current = map;
        sdkRef.current = sdk;
        cameraRef.current = JSON.stringify(location);
        map.addChild(new sdk.YMapDefaultSchemeLayer());
        map.addChild(new sdk.YMapDefaultFeaturesLayer());
        setState("ready");
      } catch (error: unknown) {
        if (!active) return;
        destroy();
        setState("fallback");
        setMessage(error instanceof Error && error.message === "Ключ карты не настроен"
          ? "Карта временно недоступна: ключ не настроен"
          : "Карту не удалось загрузить — используйте список или маршрут");
      }
    })();
    return () => {
      active = false;
      controller.abort();
      lease?.release();
      destroy();
    };
  }, [started, attempt]);

  useEffect(() => {
    const map = mapRef.current;
    const sdk = sdkRef.current;
    if (!map || !sdk || state !== "ready") return;
    const visible = new Map<number, { organization: Organization; coordinates: Coordinates }>();
    for (const organization of organizations) {
      const coordinates = coordinatesOf(organization);
      if (coordinates) visible.set(organization.id, { organization, coordinates });
    }
    for (const [id, marker] of markersRef.current) {
      const point = visible.get(id)?.coordinates;
      if (!point || point[0] !== marker.coordinates[0] || point[1] !== marker.coordinates[1]) {
        map.removeChild(marker.child);
        marker.element.removeEventListener("click", marker.click);
        markersRef.current.delete(id);
      }
    }
    for (const [id, { organization, coordinates }] of visible) {
      let marker = markersRef.current.get(id);
      if (!marker) {
        const element = document.createElement("button");
        element.type = "button";
        const click = () => selectRef.current(id);
        element.addEventListener("click", click);
        const child = new sdk.YMapMarker({ coordinates }, element);
        marker = { child, element, coordinates, click };
        markersRef.current.set(id, marker);
        map.addChild(child);
      }
      marker.element.className = `organization-marker${id === selectedId ? " selected" : ""}`;
      marker.element.title = organization.title;
      marker.element.setAttribute("aria-label", organization.title);
      marker.element.setAttribute("aria-pressed", String(id === selectedId));
    }
    // Empty/loading/error catalog updates remove markers without moving to a fake location.
    if (visible.size) {
      const points = JSON.stringify([...visible].map(([id, item]) => [id, ...item.coordinates]).sort((a, b) => a[0] - b[0]));
      const previous = previousViewRef.current;
      if (previous.points !== points || previous.selectedId !== selectedId) {
        const filtered = previous.points !== "" && previous.points !== points && previous.selectedId === selectedId;
        // A new result set should be visible as a whole even when it still contains
        // the selected card. A new selection, in contrast, focuses that marker.
        const location = cameraFor(organizations, filtered ? null : selectedId);
        const signature = JSON.stringify(location);
        if (signature !== cameraRef.current) {
          map.setLocation(location);
          cameraRef.current = signature;
        }
      }
      previousViewRef.current = { points, selectedId };
    }
  }, [organizations, selectedId, state]);

  const ready = state === "ready" && hasCoordinates;
  return (
    <div className={`organization-map-wrap ${className}`}>
      {!hasCoordinates
        ? <MapFallback message="Для этих организаций пока нет координат карты" />
        : state !== "ready" && <MapFallback message={message} onRetry={state === "fallback" ? () => setAttempt((value) => value + 1) : undefined} />}
      <div ref={containerRef} className={`organization-map${ready ? " is-ready" : ""}`} aria-label="Карта организаций" />
    </div>
  );
}
