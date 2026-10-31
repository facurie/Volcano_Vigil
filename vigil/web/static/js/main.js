// The dashboard's state, its clock and its loading. The panels are render functions in their own modules; main owns
// what they show (one scene: live, or a replay at its simulated time) and what they can do (the actions).
//
// Every renderer is called as render(root, data, ctx) with ctx = {state, config, scene, actions}, scene = {replay,
// clock} the clock the API answered with. When a panel's data could not be loaded, data is {error} (an Error).

import * as api from "./api.js";
import { el, fill } from "./dom.js";
import * as lib from "./lib.js";
import { renderDrum } from "./drum.js";
import { renderFeed } from "./feed.js";
import { renderMap } from "./map.js";
import { renderResults } from "./results.js";
import { renderTrace } from "./trace.js";
import { renderViewer } from "./viewer.js";

const LIVE_POLL_MS = 60_000;
const SCRUB_DEBOUNCE_MS = 120;
const $ = (id) => document.getElementById(id);

const state = {
  config: null,          // /api/config
  mode: "replay",        // "replay" | "live"
  episode: null,         // replay key, e.g. "55"
  clock: null,           // replay: the simulated time (ISO, Z). live: null, and the API answers at now
  ticks: [],             // the replay's grid: lib.ticks(start, end, step_minutes)
  camera: null,          // the selected camera id
  frameChoice: "tracked",// "tracked" | "latest"
  pinned: null,          // a frame id picked on the drum, until the clock or the camera changes
  lang: "en",            // bulletin language
  openBulletin: null,    // the bulletin id expanded in the feed (null: the newest)
  runId: null,           // the traced run (null: the newest by the clock)
  playing: false,
  speed: 5,              // simulated minutes per wall second
};

let last = null;         // the newest loaded scene, so a panel can be repainted without fetching
let generation = 0;
let controller = null;
let pollTimer = null;
let scrubTimer = null;
let playToken = 0;

const offset = () => state.config.volcano.utc_offset_hours;
const local = (when, seconds = false) => lib.localTime(when, offset(), seconds);

// ---- Actions the panels call ------------------------------------------------------------------------------------

const actions = {
  selectCamera(id) {
    if (id === state.camera) return;
    state.camera = id;
    state.pinned = null;
    return load();
  },
  setFrameChoice(choice) {
    state.frameChoice = choice;
    paint();
  },
  // A frame id pins that frame of the measuring camera in the viewer; null lets go of the pin.
  pinFrame(frameId) {
    if (frameId !== null && last?.measuringId) state.camera = last.measuringId;
    state.pinned = frameId;
    return load();
  },
  setLang(lang) {
    state.lang = lang;
    syncHash();
    paint();
  },
  openBulletin(id) {
    state.openBulletin = id;
    paint();
  },
  async traceRun(runId) {
    state.runId = runId;
    await load();
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    $("trace-title").scrollIntoView({ block: "start", behavior: reduced ? "auto" : "smooth" });
  },
};

// ---- Hash -------------------------------------------------------------------------------------------------------

function readHash() {
  return new URLSearchParams(location.hash.slice(1));
}

function syncHash() {
  const parts = [["mode", state.mode]];
  if (state.mode === "replay" && state.clock) parts.push(["at", state.clock]);
  if (state.camera) parts.push(["camera", state.camera]);
  if (state.lang !== "en") parts.push(["lang", state.lang]);
  if (state.runId !== null) parts.push(["run", state.runId]);
  const text = parts.map(([key, value]) => `${key}=${encodeURIComponent(value).replace(/%3A/g, ":")}`).join("&");
  history.replaceState(null, "", `#${text}`);
}

// ---- Clock and transport status ---------------------------------------------------------------------------------

function showClock(clock) {
  $("clock").dataset.mode = state.mode;
  $("clock-local").textContent = local(clock);
  let zone = lib.zone(offset());
  const date = lib.localDate(clock, offset());
  if (state.mode === "replay" || date !== lib.localDate(new Date().toISOString(), offset())) zone += ` · ${date}`;
  $("clock-zone").textContent = zone;
  $("clock-utc").textContent = `${lib.localTime(clock, 0)} UTC`;
}

const tickIndex = () => state.ticks.indexOf(state.clock);

function paintTransportControls() {
  const index = tickIndex(), lastIndex = state.ticks.length - 1;
  $("scrubber").max = Math.max(lastIndex, 0);
  $("scrubber").value = Math.max(index, 0);
  $("step-back").disabled = index <= 0;
  $("step-forward").disabled = index >= lastIndex;
  const play = $("play");
  play.textContent = state.playing ? "❚❚" : "▶";
  play.setAttribute("aria-label", state.playing ? "Pause" : "Play");
}

function paintTransportStatus() {
  const status = $("transport-status");
  const report = (last?.data.replay.value?.ticks ?? []).filter((tick) => tick.clock <= state.clock).at(-1);
  if (!report) {
    status.textContent = "";
    return;
  }
  const names = new Map((last.data.cameras.value?.cameras ?? []).map((c) => [c.camera_id, lib.shortName(c.name)]));
  const parts = [`Step ${local(report.clock)}`];
  if (report.assessed !== undefined) parts.push(`${report.assessed} frames checked`);
  if (report.tracked?.length) {
    parts.push(`SAM tracked ${report.tracked.map((t) => names.get(t.camera_id) ?? t.camera_id).join(", ")}`);
  }
  if (report.bulletin_id) parts.push(`bulletin #${report.bulletin_id}`);
  if (report.errors?.length) parts.push(`${report.errors.length} error${report.errors.length > 1 ? "s" : ""}`);
  status.textContent = parts.join(" · ");
}

// ---- Loading ----------------------------------------------------------------------------------------------------

const sceneCameras = () => (state.mode === "replay"
  ? state.config.replays.find((r) => r.episode === state.episode).cameras
  : state.config.live.cameras);

const settle = (result) => (result.status === "fulfilled" ? { value: result.value } : { error: result.reason });

function setBusy(busy) {
  for (const panel of document.querySelectorAll(".panel")) panel.setAttribute("aria-busy", String(busy));
}

async function load() {
  const mine = ++generation;
  controller?.abort();
  controller = new AbortController();
  const { signal } = controller;
  const scene = api.sceneParams(state);
  const call = (path, extra = {}) => api.get(path, { ...scene, ...extra }, signal);
  const cameraIds = sceneCameras();
  const wantedRun = state.runId;
  syncHash();
  setBusy(true);

  const cameras = call("/api/cameras");
  const measuringId = cameras.then((answer) => answer.cameras.find((c) => c.calibrated)?.camera_id ?? null);
  const latest = call("/api/frames/latest", { camera: state.camera });
  const measuring = measuringId.then((id) => {
    if (id === null) return null;
    return id === state.camera ? latest : call("/api/frames/latest", { camera: id });
  });
  const series = measuringId.then((id) => (id === null ? null
    : call("/api/series", { camera: id, target: "plume", metric: "top_altitude" })));
  const strips = Promise.allSettled(cameraIds.map((id) => call("/api/frames", { camera: id }))).then((results) =>
    Object.fromEntries(results.flatMap((r, i) => (r.status === "fulfilled" ? [[cameraIds[i], r.value.frames]] : []))));
  const bulletins = call("/api/bulletins");
  const trace = call("/api/agent/trace", { run_id: wantedRun }).catch((error) => {
    if (wantedRun === null || !error.message.startsWith("404")) throw error;
    if (mine === generation) state.runId = null;  // the traced run is after this clock
    return call("/api/agent/trace");
  });
  const replay = state.mode === "replay" ? call("/api/replay") : Promise.resolve(null);
  const pinned = state.pinned === null ? Promise.resolve(null)
    : call(`/api/frames/${state.pinned}`).then((answer) => answer.frame).catch(() => {
      if (mine === generation) state.pinned = null;  // not visible at this clock: show the camera's own frame
      return null;
    });

  const names = ["cameras", "measuringId", "latest", "measuring", "series", "strips", "bulletins", "trace", "replay",
    "pinned"];
  const settled = await Promise.allSettled([cameras, measuringId, latest, measuring, series, strips, bulletins, trace,
    replay, pinned]);
  if (mine !== generation) return;  // a newer load took over

  const data = Object.fromEntries(names.map((name, i) => [name, settle(settled[i])]));
  const answered = [data.cameras, data.latest, data.bulletins, data.trace, data.series, data.replay]
    .map((r) => r.value?.clock).find(Boolean);
  const clock = answered ?? state.clock ?? state.config.now;
  last = {
    data, measuringId: data.measuringId.value ?? null,
    scene: { replay: state.mode === "replay" ? state.episode : null, clock },
  };
  syncHash();
  paint();
  setBusy(false);
}

// ---- Painting ---------------------------------------------------------------------------------------------------

function paint() {
  if (!last) return;
  const { data, scene } = last;
  const ctx = { state, config: state.config, scene, actions };
  const value = (key) => data[key].value ?? null;
  const failure = (...keys) => keys.map((key) => data[key].error).find(Boolean);
  const draw = (root, render, keys, build) => {
    const error = failure(...keys);
    try {
      render(root, error ? { error } : build(), ctx);
    } catch (problem) {
      console.error(problem);  // one broken panel must not take the rest of the page down
    }
  };
  const panel = (name) => document.querySelector(`.panel.${name}`);

  draw(panel("viewer"), renderViewer, ["cameras", "latest"], () => ({
    cameras: value("cameras").cameras, latest: value("latest"), pinnedFrame: value("pinned") }));
  draw(panel("feed"), renderFeed, ["bulletins"], () => ({
    bulletins: value("bulletins").bulletins, cameras: value("cameras")?.cameras ?? null }));
  draw(panel("trace"), renderTrace, ["trace"], () => ({ trace: value("trace") }));
  draw(panel("drum"), renderDrum, ["series"], () => ({
    series: value("series"), strips: value("strips"), bulletins: value("bulletins")?.bulletins ?? null,
    replay: value("replay"), cameras: value("cameras")?.cameras ?? null }));
  draw(panel("map-panel"), renderMap, ["cameras"], () => ({
    cameras: value("cameras").cameras, measuring: value("measuring"),
    bulletins: value("bulletins")?.bulletins ?? null }));
  try {
    renderResults($("results"), { replay: value("replay") }, ctx);
  } catch (problem) {
    console.error(problem);
  }
  showClock(scene.clock);
  paintTransportControls();
  paintTransportStatus();
}

// ---- Mode and transport -----------------------------------------------------------------------------------------

async function chooseCamera(preferred) {
  const ids = sceneCameras();
  if (preferred && ids.includes(preferred)) return preferred;
  try {
    const { cameras } = await api.get("/api/cameras", api.sceneParams(state));
    return cameras.find((c) => c.calibrated)?.camera_id ?? ids[0] ?? null;
  } catch {
    return ids[0] ?? null;  // load() reports the failure
  }
}

function enterMode(mode, hashClock) {
  stopPlaying();
  clearInterval(pollTimer);
  generation++;  // a load the other mode started must not paint into this one
  controller?.abort();
  last = null;
  state.mode = mode;
  state.pinned = null;
  if (mode === "replay") {
    const replay = state.config.replays[0];
    state.episode = replay.episode;
    state.ticks = lib.ticks(replay.start, replay.end, replay.step_minutes);
    state.clock = snap(hashClock ?? state.clock);
  } else {
    state.episode = null;
    state.ticks = [];
    state.clock = null;
    pollTimer = setInterval(load, LIVE_POLL_MS);
  }
  for (const button of document.querySelectorAll(".mode")) {
    button.setAttribute("aria-pressed", String(button.dataset.mode === mode));
  }
  $("transport").hidden = mode !== "replay";
  paintTransportControls();
}

// The tick nearest to a time, or the first one when there is no usable time.
function snap(when) {
  const target = when ? Date.parse(when) : NaN;
  if (Number.isNaN(target)) return state.ticks[0];
  return state.ticks.reduce((best, tick) =>
    (Math.abs(Date.parse(tick) - target) < Math.abs(Date.parse(best) - target) ? tick : best));
}

async function switchMode(mode) {
  if (mode === state.mode) return;
  enterMode(mode, null);
  const camera = await chooseCamera(state.camera);
  if (state.mode !== mode) return;  // switched again while the cameras were loading
  state.camera = camera;
  state.runId = null;
  state.openBulletin = null;
  return load();
}

function goTo(index) {
  const clamped = Math.min(Math.max(index, 0), state.ticks.length - 1);
  if (state.ticks[clamped] === state.clock) return Promise.resolve();
  state.clock = state.ticks[clamped];
  state.pinned = null;
  paintTransportControls();
  return load();
}

function stopPlaying() {
  playToken++;
  state.playing = false;
  if (state.config) paintTransportControls();
}

async function startPlaying() {
  const token = ++playToken;
  state.playing = true;
  paintTransportControls();
  const stepMinutes = state.config.replays.find((r) => r.episode === state.episode).step_minutes;
  while (state.playing && token === playToken && tickIndex() < state.ticks.length - 1) {
    await new Promise((resolve) => setTimeout(resolve, (stepMinutes / state.speed) * 1000));
    if (!state.playing || token !== playToken) return;
    await goTo(tickIndex() + 1);
  }
  if (token === playToken) stopPlaying();
}

const togglePlaying = () => (state.playing ? stopPlaying() : startPlaying());

function wireControls() {
  for (const button of document.querySelectorAll(".mode")) {
    button.addEventListener("click", () => switchMode(button.dataset.mode));
  }
  const scrubber = $("scrubber");
  scrubber.addEventListener("input", () => {
    clearTimeout(scrubTimer);
    scrubTimer = setTimeout(() => goTo(Number(scrubber.value)), SCRUB_DEBOUNCE_MS);
  });
  scrubber.addEventListener("change", () => {
    clearTimeout(scrubTimer);
    goTo(Number(scrubber.value));
  });
  $("step-back").addEventListener("click", () => goTo(tickIndex() - 1));
  $("step-forward").addEventListener("click", () => goTo(tickIndex() + 1));
  $("play").addEventListener("click", togglePlaying);
  $("speed").addEventListener("change", (event) => { state.speed = Number(event.target.value); });
  document.addEventListener("keydown", (event) => {
    if (state.mode !== "replay" || event.altKey || event.ctrlKey || event.metaKey) return;
    // Not while the focus is on something that has its own use for these keys (fields, buttons, tabs, the drum).
    if (event.target.closest?.("input, select, textarea, button, [role='tab'], [tabindex]")) return;
    if (event.key === " ") togglePlaying();
    else if (event.key === "ArrowLeft") goTo(tickIndex() - 1);
    else if (event.key === "ArrowRight") goTo(tickIndex() + 1);
    else return;
    event.preventDefault();
  });
}

async function start() {
  try {
    state.config = await api.get("/api/config");
  } catch (error) {
    fill(document.querySelector(".console"), el("p", { class: "error-note" }, `Could not load the dashboard: ${error.message}`));
    return;
  }
  const hash = readHash();
  const replayWorks = state.config.replays.length > 0, liveWorks = state.config.live.available;
  document.querySelector('.mode[data-mode="replay"]').disabled = !replayWorks;
  document.querySelector('.mode[data-mode="live"]').disabled = !liveWorks;
  const wanted = hash.get("mode");
  const mode = (wanted === "replay" && replayWorks) || (wanted === "live" && liveWorks) ? wanted
    : replayWorks ? "replay" : "live";
  if (hash.get("lang") === "es") state.lang = "es";
  if (/^\d+$/.test(hash.get("run") ?? "")) state.runId = Number(hash.get("run"));
  enterMode(mode, hash.get("at"));
  state.camera = await chooseCamera(hash.get("camera"));
  wireControls();
  if (mode === "replay") showClock(state.clock);
  await load();
}

start();
