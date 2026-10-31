// The line-of-sight map (Leaflet over USGS The National Map): the vent, each camera as a circle of its position
// uncertainty with its sightline to the vent, the plume's measured side across the measuring camera's sightline, and
// the model wind from the newest bulletin. Leaflet treats string tooltip content as HTML, so every tooltip is a DOM
// node built with el(). Colours come from the CSS tokens.

import { el, fill } from "./dom.js";
import * as lib from "./lib.js";

const TILES = "https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/tile/{z}/{y}/{x}";
const ATTRIBUTION = 'Imagery: <a href="https://www.usgs.gov/programs/national-geospatial-program/national-map">USGS The National Map</a>';
const ARROW_ROOM_M = 4000;  // how far around the vent the view keeps room for the arrows
const WIND_M_PER_MS = 600;  // length of the wind arrow per m/s of the layer-mean wind

let map = null, layers = null, fitted = false;

const token = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const tip = (text) => el("span", {}, text);

function ensureMap(root) {
  if (map) return;
  map = L.map(root, { scrollWheelZoom: false, attributionControl: true, zoomSnap: 0.25 });
  L.tileLayer(TILES, { maxZoom: 16, attribution: ATTRIBUTION }).addTo(map);
  layers = L.layerGroup().addTo(map);
}

// An arrow's head: a small triangle in screen pixels at `at`, pointing along the compass bearing.
function arrowhead(at, bearing, color) {
  const icon = el("svg:svg", { width: 14, height: 14, viewBox: "0 0 14 14", style: `transform: rotate(${bearing}deg)` },
    el("svg:polygon", { points: "7,1 12,12 7,9.5 2,12", fill: color }));
  return L.marker(at, { icon: L.divIcon({ html: icon, className: "arrowhead", iconSize: [14, 14], iconAnchor: [7, 7] }),
    interactive: false, keyboard: false });
}

function arrow(from, bearing, metres, { color, weight, label }) {
  const to = lib.destination(from.lat, from.lon, bearing, metres);
  const shaft = L.polyline([[from.lat, from.lon], to], { color, weight, opacity: 0.95 });
  shaft.bindTooltip(tip(label), { className: "map-label", sticky: true });
  layers.addLayer(shaft);
  layers.addLayer(arrowhead(to, bearing, color));
}

export function renderMap(root, data, ctx) {
  const legend = document.getElementById("map-legend");
  if (data.error) {
    fill(legend, el("p", { class: "error-note" }, `The map could not be loaded (${data.error.message}).`));
    return;
  }
  const mapRoot = document.getElementById("map");
  if (typeof L === "undefined") {
    fill(legend, el("p", { class: "error-note" }, "The map needs Leaflet from unpkg.com, which did not load."));
    return;
  }
  const { config, scene } = ctx;
  const offset = config.volcano.utc_offset_hours;
  const local = (when) => lib.localTime(when, offset);
  ensureMap(mapRoot);
  layers.clearLayers();
  const steam = token("--steam"), lava = token("--lava"), plume = token("--plume"), basalt = token("--basalt-1");
  const names = new Map(data.cameras.map((c) => [c.camera_id, lib.shortName(c.name)]));
  const vent = config.vent;
  const rows = [];
  const row = (swatch, text) => rows.push(el("div", { class: "row" }, el("i", { class: `swatch ${swatch.kind ?? ""}`, style: `--swatch: ${swatch.color}` }), text));

  if (vent) {
    layers.addLayer(L.circleMarker([vent.lat, vent.lon], { radius: 6, weight: 2, color: lava, fillColor: basalt, fillOpacity: 1 })
      .bindTooltip(tip("Vent"), { permanent: true, direction: "left", offset: [-8, 0], className: "map-label" }));
    row({ kind: "vent", color: "var(--basalt-1)" }, "Vent");
  }

  const drawn = data.cameras.filter((c) => c.position);
  for (const camera of drawn) {
    const { lat, lon, sigma_m: sigma } = camera.position;
    layers.addLayer(L.circle([lat, lon], { radius: sigma, color: steam, weight: 1, opacity: 0.45, fill: false }));
    layers.addLayer(L.circleMarker([lat, lon], { radius: 4, weight: 0, fillColor: steam, fillOpacity: 1 })
      .bindTooltip(el("span", {}, names.get(camera.camera_id), el("br"), `position ±${lib.number(sigma)} m`),
        { permanent: true, direction: "right", offset: [6, 0], className: "map-label" }));
    if (vent) layers.addLayer(L.polyline([[lat, lon], [vent.lat, vent.lon]], { color: steam, weight: 1, opacity: 0.45 }));
  }
  if (drawn.length) {
    row({ kind: "dot", color: "var(--steam)" }, "Camera, with a circle of its position uncertainty");
    if (vent) row({ color: "var(--steam)" }, "Line of sight from each camera to the vent");
  }

  // the plume's measured side: the measuring camera's newest visible plume detection
  const measuring = data.measuring;
  const detection = measuring?.tracked?.detections.find((d) =>
    d.target === "plume" && d.measurements.drift_bearing && d.measurements.drift_offset);
  if (vent && detection) {
    const { drift_bearing: side, drift_offset: across } = detection.measurements;
    const camera = names.get(measuring.camera_id) ?? measuring.camera_id;
    const seenAge = lib.age(measuring.tracked.captured_at, scene.clock);
    arrow(vent, side.value, across.value, { color: plume, weight: 3,
      label: `Plume side ${Math.round(side.value)}° · ${lib.plusMinus(across.value, across.sigma, "m")} across ` +
        `${camera}'s line of sight · ${local(measuring.tracked.captured_at)} (${seenAge})` });
    row({ color: "var(--plume)" }, `Plume's measured side: ${Math.round(side.value)}°, ${lib.number(across.value)} m across ${camera}'s line of sight (${seenAge})`);
  }

  // the wind of the newest bulletin that has one
  const withWind = (data.bulletins ?? []).find((b) => b.wind?.layer_mean);
  if (vent && withWind) {
    const w = withWind.wind, mean = w.layer_mean;
    const windAge = lib.age(w.model_hour, scene.clock);
    arrow(vent, mean.toward_deg, mean.speed_ms * WIND_M_PER_MS, { color: steam, weight: 2,
      label: `Model wind ${lib.number(mean.speed_ms, 1)} m/s toward ${Math.round(mean.toward_deg)}° · mean ` +
        `${lib.number(mean.bottom_m)}–${lib.number(mean.top_m)} m · model hour ${local(w.model_hour)} (${windAge})` });
    row({ color: "var(--steam)" }, `Model wind, ${lib.number(mean.speed_ms, 1)} m/s toward ${Math.round(mean.toward_deg)}° (arrow: ${WIND_M_PER_MS} m per m/s; ${windAge})`);
  }

  for (const camera of data.cameras.filter((c) => !c.position)) {
    rows.push(el("div", { class: "row" }, `${names.get(camera.camera_id)}: position not known well enough to draw`));
  }
  const check = withWind?.wind.drift_check;
  if (check) {
    const word = { true: "consistent", false: "not consistent" }[check.consistent] ?? "too calm to tell";
    rows.push(el("div", { class: "row" }, Number.isFinite(check.angle_deg)
      ? `The plume sits ${Math.round(check.angle_deg)}° from where the wind blows: ${word}.`
      : `The wind is too calm to tell whether the plume follows it.`));
  }
  rows.push(el("div", { class: "row" }, "One camera sees only the part of the drift across its line of sight."));
  fill(legend, rows);

  if (!fitted) {
    // the vent and the cameras, and a margin around the vent for the plume's side and the wind arrow
    const around = vent ? [0, 90, 180, 270].map((bearing) => lib.destination(vent.lat, vent.lon, bearing, ARROW_ROOM_M)) : [];
    const points = [...(vent ? [[vent.lat, vent.lon]] : []), ...around, ...drawn.map((c) => [c.position.lat, c.position.lon])];
    if (points.length) {
      map.fitBounds(L.latLngBounds(points), { padding: [24, 24] });
      fitted = true;
    } else {
      map.setView([config.volcano.lat, config.volcano.lon], 12);
    }
  }
}
