import { useEffect, useMemo, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { useDashboardStore } from "../store/dashboardStore";

function markerSize(score) {
  return 14 + Math.round((Number(score) || 0) * 14);
}

function bandClass(score) {
  return `soc-threat-${getRiskBand(score).toLowerCase()}`;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => `&#${ch.charCodeAt(0)};`);
}

function buildMarkerIcon(cluster, delay) {
  const size = markerSize(cluster.score);
  const count = cluster.events.length;

  return L.divIcon({
    className: "soc-threat-icon",
    html: `
      <div class="soc-threat-marker ${bandClass(cluster.score)}" style="--size:${size}px;--delay:${delay}s">
        <span class="soc-threat-halo"></span>
        <span class="soc-threat-ring"></span>
        <span class="soc-threat-ring soc-threat-ring-late"></span>
        <span class="soc-threat-core"></span>
        ${count > 1 ? `<span class="soc-threat-count">${count}</span>` : ""}
      </div>
    `,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  });
}

function buildTooltip(cluster) {
  const names = [...new Set(cluster.events.map((event) => event.userName).filter(Boolean))];
  const shown = names.slice(0, 3).map(escapeHtml).join(", ");
  const more = names.length > 3 ? ` +${names.length - 3}` : "";

  return `
    <div class="soc-threat-tip">
      <p class="soc-threat-tip-place">${escapeHtml(cluster.label)}</p>
      <p class="soc-threat-tip-meta">${getRiskBand(cluster.score)} · peak ${formatPercent(cluster.score)} · ${cluster.events.length} event${cluster.events.length === 1 ? "" : "s"}</p>
      ${shown ? `<p class="soc-threat-tip-users">${shown}${more}</p>` : ""}
    </div>
  `;
}

// Greedy on-screen clustering: nearby origins merge into one marker at the current zoom.
function clusterByScreenDistance(events, map, radius = 26) {
  const clusters = [];
  [...events]
    .sort((a, b) => (Number(b.score) || 0) - (Number(a.score) || 0))
    .forEach((event) => {
      const point = map.latLngToLayerPoint([event.lat, event.lng]);
      const cluster = clusters.find((item) => item.point.distanceTo(point) < radius);
      if (cluster) {
        cluster.events.push(event);
        if (!cluster.labels.includes(event.label)) cluster.labels.push(event.label);
        return;
      }
      clusters.push({
        lat: event.lat,
        lng: event.lng,
        point,
        score: Number(event.score) || 0,
        labels: [event.label],
        events: [event],
      });
    });

  return clusters.map((cluster) => ({
    ...cluster,
    label: cluster.labels.length > 1 ? `${cluster.labels[0]} +${cluster.labels.length - 1} nearby` : cluster.labels[0],
  }));
}

function getRiskBand(score) {
  const value = Number(score) || 0;
  if (value >= 0.8) return "Critical";
  if (value >= 0.5) return "Elevated";
  return "Watch";
}

function formatPercent(score) {
  const value = Number(score);
  if (!Number.isFinite(value)) {
    return "0%";
  }

  return `${Math.round(value * 100)}%`;
}

async function geocodeIp(sourceIp) {
  const response = await fetch(
    `http://ip-api.com/json/${sourceIp}?fields=status,message,query,country,city,lat,lon`
  );
  const data = await response.json();

  if (data.status !== "success") {
    throw new Error(data.message || "Geocoding failed");
  }

  return {
    lat: data.lat,
    lng: data.lon,
    label: [data.city, data.country].filter(Boolean).join(", ") || sourceIp,
  };
}

export default function ThreatMap({ compact = true }) {
  const threatEvents = useDashboardStore((state) => state.threatMap.items);
  const mapRef = useRef(null);
  const mapNodeRef = useRef(null);
  const markerLayerRef = useRef(null);
  const mapInitializedRef = useRef(false);
  const fittedRef = useRef(false);
  const geoCacheRef = useRef(new Map());
  const [resolvedEvents, setResolvedEvents] = useState([]);
  const [isResolving, setIsResolving] = useState(false);

  const threatSummary = useMemo(() => {
    if (!threatEvents.length) {
      return "No confirmed threats in the last 24 hours.";
    }

    return `${threatEvents.length} confirmed threat${threatEvents.length === 1 ? "" : "s"} located by source IP.`;
  }, [threatEvents]);

  const mapSettings = useMemo(
    () => [
      { label: "Basemap", value: "Esri Dark Gray" },
      { label: "Geolocation", value: "ip-api.com" },
      { label: "Window", value: "Last 24 hours" },
    ],
    []
  );

  const legend = useMemo(
    () => [
      { label: "Watch", detail: "Score below 50%", score: 0.3 },
      { label: "Elevated", detail: "Score 50% to 79%", score: 0.65 },
      { label: "Critical", detail: "Score 80% and above", score: 0.92 },
    ],
    []
  );

  useEffect(() => {
    if (!mapNodeRef.current || mapInitializedRef.current) {
      return;
    }

    const map = L.map(mapNodeRef.current, {
      zoomControl: false,
      attributionControl: true,
      scrollWheelZoom: false,
      worldCopyJump: true,
      preferCanvas: true,
      minZoom: 2,
    }).setView([20, 10], 2);

    L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}", {
      attribution: "Tiles &copy; Esri &mdash; Esri, DeLorme, NAVTEQ",
      className: "soc-map-tiles",
      maxZoom: 16,
    }).addTo(map);

    markerLayerRef.current = L.layerGroup().addTo(map);
    mapRef.current = map;
    mapInitializedRef.current = true;

    const timeoutId = window.setTimeout(() => {
      map.invalidateSize();
    }, 0);

    return () => {
      window.clearTimeout(timeoutId);
      map.remove();
      mapRef.current = null;
      markerLayerRef.current = null;
      mapInitializedRef.current = false;
      fittedRef.current = false;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function resolveThreats() {
      if (!threatEvents.length) {
        setResolvedEvents([]);
        setIsResolving(false);
        return;
      }

      setIsResolving(true);

      const nextEvents = await Promise.all(
        threatEvents.map(async (event) => {
          if (!event.sourceIp) {
            return null;
          }

          if (!geoCacheRef.current.has(event.sourceIp)) {
            try {
              geoCacheRef.current.set(event.sourceIp, await geocodeIp(event.sourceIp));
            } catch {
              geoCacheRef.current.set(event.sourceIp, null);
            }
          }

          const geo = geoCacheRef.current.get(event.sourceIp);
          if (!geo) {
            return null;
          }

          return {
            ...event,
            ...geo,
          };
        })
      );

      if (!cancelled) {
        setResolvedEvents(nextEvents.filter(Boolean));
        setIsResolving(false);
      }
    }

    resolveThreats();

    return () => {
      cancelled = true;
    };
  }, [threatEvents]);

  useEffect(() => {
    const map = mapRef.current;
    const layer = markerLayerRef.current;
    if (!map || !layer) {
      return undefined;
    }

    function drawMarkers() {
      layer.clearLayers();
      clusterByScreenDistance(resolvedEvents, map)
        .sort((a, b) => a.score - b.score)
        .forEach((cluster, index) => {
          L.marker([cluster.lat, cluster.lng], {
            icon: buildMarkerIcon(cluster, -((index * 0.7) % 2.8).toFixed(2)),
            keyboard: false,
            zIndexOffset: Math.round(cluster.score * 1000),
          })
            .bindTooltip(buildTooltip(cluster), {
              direction: "top",
              offset: [0, -markerSize(cluster.score) / 2],
              opacity: 1,
              className: "soc-tooltip",
            })
            .addTo(layer);
        });
    }

    if (resolvedEvents.length && !fittedRef.current) {
      fittedRef.current = true;
      const bounds = L.latLngBounds(resolvedEvents.map((event) => [event.lat, event.lng]));
      map.fitBounds(bounds.pad(0.35), { maxZoom: 4, animate: false });
    }

    drawMarkers();
    map.on("zoomend", drawMarkers);

    return () => {
      map.off("zoomend", drawMarkers);
    };
  }, [resolvedEvents]);

  return (
    <section
      className={`soc-glass pointer-events-auto overflow-hidden p-5 ${
        compact ? "h-[390px] w-full" : ""
      }`}
    >
      {compact ? (
        <>
          <div className="mb-3 flex items-start justify-between gap-3">
            <div>
              <p className="soc-kicker">Threat Map</p>
              <p className="mt-2 text-xs text-soc-muted">{threatSummary}</p>
            </div>
            {isResolving ? <span className="text-xs text-soc-muted">Geocoding...</span> : null}
          </div>

          <div className="relative h-[228px] overflow-hidden rounded-xl border border-soc-border/80">
            <div ref={mapNodeRef} className="h-full w-full" />
            {isResolving && resolvedEvents.length === 0 ? (
              <div className="absolute inset-0 flex items-center justify-center bg-soc-panel/60 text-sm text-soc-muted">
                Resolving threat origins...
              </div>
            ) : null}
          </div>
        </>
      ) : (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1.7fr)_minmax(280px,0.9fr)]">
          <div className="space-y-4">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <p className="soc-kicker">Threat Map</p>
                <h2 className="mt-1 text-lg font-medium tracking-tight text-soc-text">Threat origins</h2>
                <p className="mt-2 max-w-2xl text-sm text-soc-muted">{threatSummary}</p>
              </div>
              <div className="rounded-xl border border-soc-border/80 bg-soc-panelSoft/40 px-4 py-3">
                <p className="text-[10px] font-medium uppercase tracking-[0.2em] text-soc-muted">Live markers</p>
                <p className="mt-1 text-lg font-medium text-soc-text">{resolvedEvents.length}</p>
                <p className="mt-1 text-xs text-soc-muted">{isResolving ? "Updating geocodes..." : "Ready"}</p>
              </div>
            </div>

            <div className="relative h-[560px] overflow-hidden rounded-2xl border border-soc-border/80">
              <div ref={mapNodeRef} className="h-full w-full" />
              {isResolving && resolvedEvents.length === 0 ? (
                <div className="absolute inset-0 flex items-center justify-center bg-soc-panel/60 text-sm text-soc-muted">
                  Resolving threat origins...
                </div>
              ) : null}
            </div>
          </div>

          <div className="space-y-4">
            <div className="rounded-2xl border border-soc-border/80 bg-soc-panelSoft/40 p-4">
              <p className="soc-kicker">Legend</p>
              <div className="mt-4 space-y-3">
                {legend.map((item) => (
                  <div key={item.label} className="flex items-center gap-3">
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center">
                      <div className={`soc-threat-marker ${bandClass(item.score)}`} style={{ "--size": `${markerSize(item.score)}px` }}>
                        <span className="soc-threat-halo" />
                        <span className="soc-threat-ring" />
                        <span className="soc-threat-ring soc-threat-ring-late" />
                        <span className="soc-threat-core" />
                      </div>
                    </div>
                    <div>
                      <p className="text-sm font-medium text-soc-text">{item.label}</p>
                      <p className="text-xs text-soc-muted">{item.detail}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="rounded-2xl border border-soc-border/80 bg-soc-panelSoft/40 p-4">
              <p className="soc-kicker">Map Settings</p>
              <div className="mt-4 space-y-3">
                {mapSettings.map((item) => (
                  <div key={item.label} className="flex items-center justify-between gap-3 border-b border-soc-border/40 pb-2 last:border-none last:pb-0">
                    <span className="text-sm text-soc-muted">{item.label}</span>
                    <span className="text-sm font-medium text-soc-text">{item.value}</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="rounded-2xl border border-soc-border/80 bg-soc-panelSoft/40 p-4">
              <p className="soc-kicker">Recent Signals</p>
              <div className="mt-4 space-y-3">
                {resolvedEvents.length === 0 ? (
                  <p className="text-sm text-soc-muted">No geolocated markers yet.</p>
                ) : (
                  resolvedEvents.slice(0, 5).map((event) => (
                    <div key={`${event.id}-${event.timestamp}`} className="rounded-xl border border-soc-border/70 bg-soc-panel/55 p-3">
                      <div className="flex items-center justify-between gap-3 text-xs text-soc-muted">
                        <span>{event.userName}</span>
                        <span>{formatPercent(event.score)}</span>
                      </div>
                      <p className="mt-2 text-sm text-soc-text">{event.label}</p>
                      <p className="mt-1 text-xs text-soc-muted">{getRiskBand(event.score)} risk band</p>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
