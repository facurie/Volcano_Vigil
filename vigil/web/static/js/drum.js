// The plume-height drum: a helicorder-style chart on the scene's time axis. It inks only up to the clock; the future
// is blank paper. HVO's values, phases and the bulletins appear only once the API sends them. The chart is an SVG
// built with el(); every colour comes from a CSS class (tokens in app.css). Model text never reaches here: only
// numbers, times and short fixed labels.

import { el, fill } from "./dom.js";
import * as lib from "./lib.js";

const M = { left: 48, right: 16, top: 20, bottom: 24 };
const STRIP_H = 16, MIN_TOP_M = 9000, Y_STEP_M = 2000;
const GAP_MS = 30 * 60_000;     // a longer pause between measurements breaks the line
const HOUR_MS = 3_600_000;
const CHAR_PX = 6.7;            // a label's width in 11 px IBM Plex Mono, to place labels without measuring
const TARGET_LABELS = { plume: "plume", fountain: "lava fountain", incandescence: "glow" };
const TARGET_ORDER = Object.keys(TARGET_LABELS);

const instances = new WeakMap();  // root -> {width, args}: the drum redraws when its width changes

const svg = (tag, props = {}, ...children) => el(`svg:${tag}`, props, ...children);
const line = (x1, y1, x2, y2, cls) => svg("line", { x1, y1, x2, y2, class: cls });
const label = (x, y, text, props = {}) => svg("text", { x, y, ...props }, text);
const shortOf = (cameras, id) => {
  const camera = (cameras ?? []).find((c) => c.camera_id === id);
  return camera ? lib.shortName(camera.name) : id;
};

export function renderDrum(panel, data, ctx) {
  const root = panel.querySelector("#drum");  // the figure: the panel also holds the head, the table and the results
  const legend = document.getElementById("drum-legend"), table = document.getElementById("drum-table");
  if (data.error) {
    fill(legend);
    fill(table);
    fill(root, el("p", { class: "error-note" }, `The plume record could not be loaded (${data.error.message}).`));
    instances.get(root)?.observer.disconnect();
    instances.delete(root);
    return;
  }
  renderLegend(legend, data, ctx);
  renderTable(table, data, ctx);
  let instance = instances.get(root);
  if (!instance) {
    instance = { width: 0, args: null };
    instance.observer = new ResizeObserver(() => { if (root.clientWidth !== instance.width) draw(root, instance); });
    instance.observer.observe(root);
    instances.set(root, instance);
  }
  instance.args = { data, ctx };
  draw(root, instance);
}

function renderLegend(root, data, ctx) {
  const name = shortOf(data.cameras, data.series?.camera_id);
  fill(root,
    el("span", {}, el("i", { class: "lg lg-line" }), `${name} plume top ± σ`),
    ctx.state.mode === "replay" ? el("span", {}, el("i", { class: "lg lg-diamond" }), "HVO (official)") : null,
    el("span", {}, el("i", { class: "lg lg-triangle" }), "Bulletin"));
}

function renderTable(root, data, ctx) {
  const offset = ctx.config.volcano.utc_offset_hours;
  const points = data.series?.points ?? [];
  fill(root, points.length ? el("table", { class: "b-table" },
    el("thead", {}, el("tr", {}, ["Time (local)", "Plume top above sea level", "Frame"].map((h) => el("th", { scope: "col" }, h)))),
    el("tbody", {}, points.map((p) => el("tr", {},
      el("td", { class: "mono" }, `${lib.stamp(p.captured_at, ctx.scene.clock, offset, true)} ${lib.zone(offset)}`),
      el("td", { class: "mono" }, lib.plusMinus(p.value, p.sigma, "m")),
      el("td", { class: "mono" }, p.frame_id))))) : null);
}

function draw(root, instance) {
  const style = getComputedStyle(root);
  const width = root.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
  instance.width = root.clientWidth;
  if (width <= 0) return;
  const { data, ctx } = instance.args;
  const { state, config, scene, actions } = ctx;
  const offset = config.volcano.utc_offset_hours, zone = lib.zone(offset);
  const local = (when, seconds = false) => lib.stamp(when, scene.clock, offset, seconds);
  const replay = state.mode === "replay";
  const clock = Date.parse(scene.clock);
  const episode = replay ? config.replays.find((r) => r.episode === state.episode) : null;
  const t0 = replay ? Date.parse(episode.start) : clock - 24 * HOUR_MS;
  const t1 = replay ? Date.parse(episode.end) : clock;

  const points = (data.series?.points ?? []).map((p) => ({ ...p, t: Date.parse(p.captured_at) }));
  const official = replay ? (data.series?.official ?? []) : [];
  const phases = replay ? (data.replay?.official_phases ?? {}) : {};
  const strips = Object.entries(data.strips ?? {});
  const bulletins = (data.bulletins ?? []).map((b) => ({ ...b, t: Date.parse(b.clock) }))
    .filter((b) => b.t >= t0 && b.t <= t1);

  const topM = Math.max(MIN_TOP_M, Math.ceil(Math.max(0, ...points.map((p) => p.value + p.sigma)) / 1000) * 1000);
  const plotW = width - M.left - M.right;
  const plotH = width >= 700 ? 300 : 200;  // taller where the panel is wide, so it fills the row beside the map
  const stepMs = (replay ? 1 : 3) * HOUR_MS;
  const offsetMs = offset * HOUR_MS;
  const tickTimes = [];
  for (let t = Math.ceil((t0 + offsetMs) / stepMs) * stepMs - offsetMs; t <= t1; t += stepMs) tickTimes.push(t);
  const isMidnight = (t) => lib.localTime(new Date(t).toISOString(), offset) === "00:00";
  const axisH = tickTimes.some(isMidnight) ? M.bottom + 12 : M.bottom;  // room for the date under a midnight label
  const height = M.top + plotH + axisH + strips.length * STRIP_H + 4;
  const x = (t) => M.left + ((t - t0) / (t1 - t0)) * plotW;
  const y = (metres) => M.top + plotH - (metres / topM) * plotH;
  const right = M.left + plotW, bottom = M.top + plotH;
  const nameOf = (id) => shortOf(data.cameras, id);

  // ---- paper: the future, the grid, the vent's elevation
  const paper = svg("g", { class: "drum-grid" });
  const future = replay && clock < t1
    ? svg("rect", { class: "drum-future", x: x(clock), y: M.top, width: right - x(clock), height: plotH }) : null;
  for (let metres = 0; metres <= topM; metres += Y_STEP_M) {
    paper.append(line(M.left, y(metres), right, y(metres)),
      label(M.left - 8, y(metres) + 4, metres === 0 ? "0" : `${metres / 1000} km`, { "text-anchor": "end" }));
  }
  const every = Math.max(1, Math.ceil(36 / ((stepMs / (t1 - t0)) * plotW)));  // label every n-th tick when narrow
  tickTimes.forEach((t, n) => {
    paper.append(line(x(t), M.top, x(t), bottom));
    const midnight = isMidnight(t);
    if (n % every === 0 || midnight) {
      const when = new Date(t).toISOString();
      paper.append(label(x(t), bottom + 16, lib.localTime(when, offset), { "text-anchor": "middle" }));
      if (midnight) paper.append(label(x(t), bottom + 28, lib.localDate(when, offset), { "text-anchor": "middle" }));
    }
  });
  const vent = config.vent
    ? [line(M.left, y(config.vent.elev_m), right, y(config.vent.elev_m), "drum-vent"),
      label(right - 4, y(config.vent.elev_m) - 4, `vent ${lib.number(config.vent.elev_m)} m`, { "text-anchor": "end" })]
    : [];

  // ---- HVO's phases: onset and end as lines, the peak as a band
  const phaseMarks = [];
  for (const [phase, [from, to]] of Object.entries(phases)) {
    if (phase !== "onset" && phase !== "peak" && phase !== "end") continue;
    const a = Date.parse(from), b = Date.parse(to);
    const text = `${phase} (HVO)`, edge = x(b), fits = edge + 4 + text.length * CHAR_PX < right;
    phaseMarks.push(
      phase === "peak" ? svg("rect", { class: "drum-peak", x: x(a), y: M.top, width: x(b) - x(a), height: plotH })
        : line(x(a), M.top, x(a), bottom, "drum-phase"),
      label(fits ? edge + 4 : x(a) - 4, M.top + 12, text, { "text-anchor": fits ? "start" : "end" }));
  }

  // ---- HVO's official values
  const marks = official.map((o) => {
    const a = Date.parse(o.start), b = Date.parse(o.end), mid = (a + b) / 2, cy = y(o.value_m), cx = x(mid);
    const text = `HVO ${o.upper_bound ? "< " : ""}${lib.number(o.value_m)} m`;
    const half = (text.length * CHAR_PX) / 2;
    const anchorX = Math.min(Math.max(cx, M.left + half), width - half);
    return svg("g", {},
      line(x(a), cy, x(b), cy, "drum-official"),
      svg("polygon", { class: "drum-diamond", points: `${cx},${cy - 6} ${cx + 6},${cy} ${cx},${cy + 6} ${cx - 6},${cy}` },
        svg("title", {}, `${o.official} · ${o.source}`)),
      o.upper_bound ? line(cx, cy + 6, cx, cy + 12, "drum-official") : null,
      label(anchorX, cy - 10, text, { class: "value halo", "text-anchor": "middle" }));
  });

  // ---- the series: a σ band and a line, broken where the camera was silent for long
  const runs = [];
  for (const p of points) {
    const current = runs.at(-1);
    if (current && p.t - current.at(-1).t <= GAP_MS) current.push(p);
    else runs.push([p]);
  }
  const lone = runs.filter((r) => r.length === 1).flatMap(([p]) => [  // a measurement with no neighbour within 30 min
    line(x(p.t), y(p.value + p.sigma), x(p.t), y(p.value - p.sigma), "drum-sigma"),
    svg("circle", { class: "drum-dot", cx: x(p.t), cy: y(p.value), r: 3 }),
  ]);
  const ink = runs.filter((r) => r.length > 1).flatMap((r) => [
    svg("polygon", { class: "drum-band", points: [
      ...r.map((p) => `${x(p.t)},${y(p.value + p.sigma)}`), ...[...r].reverse().map((p) => `${x(p.t)},${y(p.value - p.sigma)}`),
    ].join(" ") }),
    svg("polyline", { class: "drum-line", points: r.map((p) => `${x(p.t)},${y(p.value)}`).join(" ") }),
  ]);
  const end = points.at(-1);
  const endText = end ? `${lib.number(end.value)} m` : "";
  const endMarks = end ? [
    svg("circle", { class: "drum-dot", cx: x(end.t), cy: y(end.value), r: 4 }),
    // below the dot: HVO's diamond and label can sit right beside the last point
    x(end.t) + 8 + endText.length * CHAR_PX < width ? label(x(end.t) + 8, y(end.value) + 20, endText, { class: "value halo" }) : null,
  ] : [];

  // ---- the cameras' strips: what each frame showed
  const rows = strips.map(([id, frames], i) => {
    const top = bottom + axisH + i * STRIP_H;
    return svg("g", {}, label(M.left - 8, top + 12, nameOf(id), { "text-anchor": "end" }),
      frames.map((f) => {
        const seen = TARGET_ORDER.filter((t) => f.targets.includes(t));
        const kind = f.targets.includes("fountain") ? "fountain" : f.targets.includes("plume") ? "plume"
          : f.usable ? "clear" : "rejected";
        const verdict = f.usable === null ? "unchecked" : f.usable ? "usable" : "not usable";
        return svg("rect", { class: `strip strip-${kind}`, x: x(Date.parse(f.captured_at)) - 1, y: top + 3, width: 2, height: 10 },
          svg("title", {}, [local(f.captured_at, true), verdict, ...(seen.length ? [seen.map((t) => TARGET_LABELS[t]).join(", ")] : [])].join(" · ")));
      }));
  });

  // ---- the clock and the bulletins
  const clockMarks = replay ? [
    line(x(clock), M.top - 4, x(clock), bottom, "drum-clock"),
    label(x(clock), M.top - 8, local(scene.clock), { class: "clock-label", "text-anchor": "middle" })] : [];
  const bulletinMarks = bulletins.map((b) => {
    const open = () => actions.openBulletin(b.id);
    return svg("polygon", {
      class: "drum-bulletin", role: "button", tabindex: "0", points: `${x(b.t) - 4},${M.top} ${x(b.t) + 4},${M.top} ${x(b.t)},${M.top + 7}`,
      onClick: open, onKeydown: (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); open(); } },
    }, svg("title", {}, `Bulletin ${local(b.clock)} · ${b[state.lang].level}`));
  });

  // ---- hover and keyboard: a crosshair that snaps to the nearest measurement
  const cursor = line(0, M.top, 0, bottom, "drum-cursor");
  cursor.setAttribute("visibility", "hidden");
  const empty = points.length ? null : label(M.left + plotW / 2, M.top + plotH / 2, replay
    ? `No plume measurements by ${local(scene.clock)}.` : "No plume measurements in the last 24 hours.",
  { "text-anchor": "middle", class: "drum-empty" });
  const overlay = svg("rect", { x: M.left, y: M.top, width: plotW, height: plotH, fill: "transparent", class: "drum-hit" });
  const chart = svg("svg", {
    width, height, viewBox: `0 0 ${width} ${height}`, role: "group", tabindex: points.length ? "0" : null,
    "aria-label": "Plume top above sea level over time. Use the arrow keys to move between measurements, Enter to show the frame.",
  }, future, paper, vent, phaseMarks, marks, ink, lone, clockMarks, endMarks, rows, empty, cursor, overlay, bulletinMarks);
  fill(root, chart);

  let tooltip = null, selected = null;
  const hide = () => {
    selected = null;
    cursor.setAttribute("visibility", "hidden");
    tooltip?.remove();
    tooltip = null;
  };
  const show = (index) => {
    selected = index;
    const p = points[index];
    cursor.setAttribute("x1", x(p.t));
    cursor.setAttribute("x2", x(p.t));
    cursor.setAttribute("visibility", "visible");
    tooltip?.remove();
    tooltip = el("div", { class: "tooltip", role: "status" },
      el("strong", {}, lib.plusMinus(p.value, p.sigma, "m")),
      el("span", {}, `${lib.number(lib.feet(p.value))} ft above sea level`),
      el("span", {}, `${local(p.captured_at, true)} ${zone} · frame ${p.frame_id}`));
    root.append(tooltip);
    const wide = tooltip.offsetWidth, tall = tooltip.offsetHeight;
    const left = chart.offsetLeft + x(p.t) + 12;
    tooltip.style.left = `${left + wide > root.clientWidth ? chart.offsetLeft + x(p.t) - 12 - wide : left}px`;
    tooltip.style.top = `${Math.max(0, chart.offsetTop + y(p.value) - tall - 10)}px`;
  };
  const nearest = (t) => points.reduce((best, p, i) => (Math.abs(p.t - t) < Math.abs(points[best].t - t) ? i : best), 0);
  overlay.addEventListener("pointermove", (event) => {
    if (!points.length) return;
    const px = event.clientX - chart.getBoundingClientRect().left;
    show(nearest(t0 + ((px - M.left) / plotW) * (t1 - t0)));
  });
  overlay.addEventListener("pointerleave", () => { if (document.activeElement !== chart) hide(); });
  overlay.addEventListener("click", () => { if (selected !== null) actions.pinFrame(points[selected].frame_id); });
  chart.addEventListener("focus", () => { if (points.length && selected === null) show(points.length - 1); });
  chart.addEventListener("blur", hide);
  chart.addEventListener("keydown", (event) => {
    if (!points.length || event.target !== chart) return;
    const step = { ArrowLeft: -1, ArrowRight: 1 }[event.key];
    if (step) show(Math.min(Math.max((selected ?? points.length - 1) + step, 0), points.length - 1));
    else if ((event.key === "Enter" || event.key === " ") && selected !== null) actions.pinFrame(points[selected].frame_id);
    else return;
    event.preventDefault();
  });
}
