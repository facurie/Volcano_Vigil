// The bulletin feed, newest first, one expanded. Bulletin text (headline, body, notes, captions) is model text: it
// goes into the DOM only through el()/fill(), as text.

import { el, fill } from "./dom.js";
import * as lib from "./lib.js";

const CHECKED = "✓ Every number checked against the stored measurements";
const UNCHECKED = "Some numbers could not be checked against the stored measurements";

export function renderFeed(root, data, ctx) {
  const { state, config, scene, actions } = ctx;
  const list = root.querySelector("#bulletins");
  if (data.error) {
    fill(list, el("li", { class: "error-note" }, `Bulletins could not be loaded (${data.error.message}).`));
    return;
  }
  const { bulletins, cameras } = data;
  const offset = config.volcano.utc_offset_hours;
  const local = (when) => lib.stamp(when, scene.clock, offset);
  // a bulletin's time, and its local date when that is not the clock's day (the column is too narrow for both)
  const timeOf = (when) => [lib.localTime(when, offset),
    lib.localDate(when, offset) === lib.localDate(scene.clock, offset) ? null : lib.localDate(when, offset)];
  if (!bulletins.length) {
    fill(list, el("li", { class: "error-note" }, state.mode === "replay"
      ? `No bulletin yet by ${local(scene.clock)} ${lib.zone(offset)}. The agent writes one every hour.`
      : "No bulletin in the database yet."));
    return;
  }
  // an id that is not visible at this clock (the clock moved back) falls back to the newest
  const openId = bulletins.some((b) => b.id === state.openBulletin) ? state.openBulletin : bulletins[0].id;
  const names = new Map((cameras ?? []).map((c) => [c.camera_id, lib.shortName(c.name)]));
  fill(list, bulletins.map((b) => bulletin(b, b.id === openId, { local, timeOf, names, actions })));
}

function bulletin(b, open, { local, timeOf, names, actions }) {
  const [time, date] = timeOf(b.clock);
  return el("li", { class: "bulletin", "aria-current": open ? "true" : null },
    el("button", { type: "button", class: "b-summary", "aria-expanded": String(open),
      onClick: () => actions.openBulletin(b.id) },
    el("span", { class: "b-time" }, time, date ? el("span", { class: "b-date" }, date) : null),
    el("span", { class: "level", dataset: { level: b.activity_level } }, b.level),
    el("span", { class: "b-headline" }, b.headline)),
    open ? body(b, { local, names, actions }) : null);
}

function body(b, { local, names, actions }) {
  const safeUrl = /^https?:\/\//.test(b.official_url);
  return el("div", { class: "b-body" },
    el("p", { class: "b-disclaimer" }, b.disclaimer),
    b.body.split(/\n\s*\n/).map((paragraph) => el("p", {}, paragraph)),
    b.rows.length ? el("ul", { class: "b-rows" }, b.rows.map((row) => el("li", { class: "b-row" },
      el("div", { class: "b-row-main" }, el("span", {}, row[0]), el("span", { class: "b-row-value" }, row[2])),
      el("div", { class: "b-row-meta" }, [1, 4, 3, 5].map((i) => `${b.header[i]} ${row[i]}`).join(" · "))))) : null,
    b.wind_text ? el("p", { class: "b-wind" }, b.wind_text) : null,
    b.evidence.length ? el("div", { class: "b-evidence" }, b.evidence.map((e) => el("figure", {},
      el("img", { src: `/media/${e.overlay.split("/").map(encodeURIComponent).join("/")}`, loading: "lazy",
        alt: e.caption }),
      el("figcaption", {}, e.caption, el("br"),
        el("span", { class: "mono" }, `${names.get(e.camera_id) ?? e.camera_id}, ${local(e.captured_at)}`))))) : null,
    el("p", { class: "b-check" }, b.verified ? CHECKED : UNCHECKED,
      b.notes.length ? el("ul", {}, b.notes.map((note) => el("li", {}, note))) : null),
    el("p", { class: "b-source" }, "Official source: ",
      safeUrl ? el("a", { href: b.official_url, target: "_blank", rel: "noopener" }, b.official_agency)
        : b.official_agency),
    el("button", { type: "button", class: "link-button", onClick: () => actions.traceRun(b.run_id) },
      "Agent trace of this bulletin"));
}
