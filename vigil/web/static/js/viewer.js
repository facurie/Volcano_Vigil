// The camera tabs, the frame with its masks and the readout. Everything is built with el()/fill(): the frame, the
// verdicts and the numbers reach the DOM as text. Times through lib.localTime with the volcano's offset.

import { imageUrl } from "./api.js";
import { el, fill } from "./dom.js";
import * as lib from "./lib.js";

const CONDITIONS = { no_frames: "no frames", clock_mismatch: "clock mismatch" };
const TARGET_LABELS = { plume: "plume", fountain: "lava fountain", incandescence: "glow" };
const TARGET_ORDER = Object.keys(TARGET_LABELS);

let imageToken = 0;      // the newest image request; an older one that finishes late is dropped
let refocusTab = false;  // an arrow key moved the selection: put the focus back on the selected tab after the redraw

const conditionWord = (condition) => CONDITIONS[condition] ?? condition;

export function renderViewer(root, data, ctx) {
  const $ = (id) => root.querySelector(`#${id}`);
  if (data.error) {
    fill($("camera-tabs"));
    fill($("frame-bar"));
    showEmpty(root, null);
    fill($("readout"), el("p", { class: "error-note" }, `Cameras could not be loaded (${data.error.message}).`));
    return;
  }
  const { cameras, latest, pinnedFrame } = data;
  const { state, config, scene, actions } = ctx;
  const offset = config.volcano.utc_offset_hours;
  const zone = lib.zone(offset);
  const local = (when, seconds = false) => lib.localTime(when, offset, seconds);
  const byId = new Map(cameras.map((camera) => [camera.camera_id, camera]));
  const short = (id) => (byId.has(id) ? lib.shortName(byId.get(id).name) : id);

  renderTabs($("camera-tabs"), cameras, state, scene, actions);

  const shown = pinnedFrame ?? (state.frameChoice === "tracked" && latest.tracked ? latest.tracked : latest.latest);
  if (!shown) {
    showEmpty(root, `No frame from ${short(state.camera)} by ${local(scene.clock)}.`);
    fill($("frame-bar"));
    fill($("readout"));
    return;
  }
  showFrame(root, shown, `${short(shown.camera_id)} frame ${shown.frame_id}, ${local(shown.captured_at)} ${zone}`, scene);

  renderBar($("frame-bar"), { shown, latest, pinned: pinnedFrame !== null, local, zone, scene, actions });
  renderReadout($("readout"), { shown, camera: byId.get(shown.camera_id), cameras, local, zone, short });
}

function renderTabs(root, cameras, state, scene, actions) {
  const tabs = cameras.map((camera) => {
    const selected = camera.camera_id === state.camera;
    const when = camera.latest ? `last frame ${lib.age(camera.latest.captured_at, scene.clock)}` : "no frames";
    return el("button", {
      type: "button", role: "tab", class: "tab", "aria-selected": String(selected), tabindex: selected ? "0" : "-1",
      title: `${camera.name} · ${when}`, onClick: () => actions.selectCamera(camera.camera_id),
    }, el("span", { class: "cond-dot", dataset: { condition: camera.condition } }),
    el("span", { class: "tab-name" }, lib.shortName(camera.name)),
    el("span", { class: "tab-cond" }, conditionWord(camera.condition)));
  });
  tabs.forEach((tab, i) => tab.addEventListener("keydown", (event) => {
    const step = { ArrowRight: 1, ArrowLeft: -1 }[event.key];
    if (!step) return;
    event.preventDefault();
    refocusTab = true;
    actions.selectCamera(cameras[(i + step + cameras.length) % cameras.length].camera_id);
  }));
  fill(root, tabs);
  if (refocusTab) {
    refocusTab = false;
    root.querySelector('[aria-selected="true"]')?.focus();
  }
}

function showEmpty(root, message) {
  const img = root.querySelector("#frame-img"), empty = root.querySelector("#frame-empty");
  imageToken++;
  img.hidden = true;
  root.querySelector("#frame-well").removeAttribute("aria-busy");
  empty.hidden = message === null;
  empty.textContent = message ?? "";
}

// Keep the old image while the new one loads, then swap.
function showFrame(root, frame, alt, scene) {
  const well = root.querySelector("#frame-well"), img = root.querySelector("#frame-img");
  root.querySelector("#frame-empty").hidden = true;
  const wide = well.clientWidth * (window.devicePixelRatio || 1) > 1280;
  const url = imageUrl(frame.frame_id, scene, { width: wide ? 1920 : 1280 });
  const token = ++imageToken;
  img.alt = alt;
  if (img.getAttribute("src") === url) {
    img.hidden = false;
    well.removeAttribute("aria-busy");
    return;
  }
  well.setAttribute("aria-busy", "true");
  const probe = new Image();
  probe.onload = () => {
    if (token !== imageToken) return;
    img.src = url;
    img.hidden = false;
    well.removeAttribute("aria-busy");
  };
  probe.onerror = () => {
    if (token === imageToken) well.removeAttribute("aria-busy");
  };
  probe.src = url;
}

function renderBar(root, { shown, latest, pinned, local, zone, scene, actions }) {
  const verdict = shown.usable === null ? "unchecked"
    : shown.usable ? "usable" : (shown.reasons.join(", ") || "not usable");
  const targets = TARGET_ORDER.filter((t) => shown.detections.some((d) => d.target === t));
  const choose = (key, label, frame, current) => el("button", {
    type: "button", "aria-pressed": String(current === key), disabled: !frame,
    onClick: () => actions.setFrameChoice(key),
  }, `${label} ${frame ? local(frame.captured_at) : ""}`.trim());
  const which = shown === latest.tracked ? "tracked" : "latest";
  const unsettled = shown === latest.latest && shown.detections.length === 0 && latest.tracked;
  fill(root,
    pinned
      ? el("button", { type: "button", class: "link-button", onClick: () => actions.pinFrame(null) },
        "Picked on the chart · back to latest")
      : el("div", { class: "seg", role: "group", "aria-label": "Frame" },
        choose("tracked", "Last tracked", latest.tracked, which), choose("latest", "Latest", latest.latest, which)),
    el("span", { class: "mono" }, `${local(shown.captured_at, true)} ${zone}`),
    el("span", { class: "mono" }, `${lib.localTime(shown.captured_at, 0)} UTC`),
    el("span", {}, lib.age(shown.captured_at, scene.clock)),
    el("span", {}, verdict),
    unsettled ? el("span", {}, "SAM tracks each hour once it closes.") : null,
    el("div", { class: "keys" }, targets.map((t) => el("span", { class: "key", dataset: { target: t } }, TARGET_LABELS[t]))));
}

function renderReadout(root, { shown, camera, cameras, local, zone, short }) {
  const plume = shown.detections.find((d) => d.target === "plume");
  const seen = [...new Set(shown.detections.map((d) => TARGET_LABELS[d.target] ?? d.target))].sort();
  const sees = seen.length ? el("p", { class: "readout-note" }, `SAM sees: ${seen.join(", ")}`) : null;
  const name = short(shown.camera_id);

  if (camera && !camera.calibrated) {
    const measuring = cameras.find((c) => c.calibrated);
    fill(root, el("p", { class: "readout-note" },
      `Heights are not measured on ${name}: its view is not calibrated yet.`,
      measuring ? ` ${lib.shortName(measuring.name)} measures the plume.` : ""), sees);
    return;
  }
  const m = plume?.measurements ?? {};
  if (!m.top_altitude) {
    fill(root, el("p", { class: "readout-note" }, "No plume measured on this frame."), sees);
    return;
  }
  const top = m.top_altitude;
  const facts = [
    ["Above the vent", m.top_height && lib.plusMinus(m.top_height.value, m.top_height.sigma, m.top_height.unit)],
    ["Plume side", m.drift_bearing
      && `${lib.plusMinus(m.drift_bearing.value, m.drift_bearing.sigma, m.drift_bearing.unit)} of the sightline`],
    ["Across the sightline", m.drift_offset && lib.plusMinus(m.drift_offset.value, m.drift_offset.sigma, m.drift_offset.unit)],
    ["Area", m.area && lib.plusMinus(m.area.value, m.area.sigma, m.area.unit)],
  ].filter(([, value]) => value);
  fill(root,
    el("div", { class: "hero" },
      el("span", { class: "label" }, "Plume top above sea level"),
      el("div", { class: "hero-figure" },
        el("span", { class: "hero-value" }, lib.number(top.value)), el("span", { class: "hero-unit" }, "m")),
      el("div", { class: "hero-sigma" }, `± ${lib.number(top.sigma)} m · ${lib.number(lib.feet(top.value))} ft`)),
    el("dl", { class: "facts" }, facts.map(([label, value]) =>
      el("div", {}, el("dt", { class: "label" }, label), el("dd", {}, value)))),
    el("p", { class: "readout-meta" },
      `${name} · frame ${shown.frame_id} · ${local(shown.captured_at, true)} ${zone} · SAM 3.1 mask, calibrated camera`));
}
