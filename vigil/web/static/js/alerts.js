// The fountaining banner under the notice. Alert texts are the code's, not a model's, but they still reach the DOM
// only as text (el/fill).

import { el, fill } from "./dom.js";
import * as lib from "./lib.js";

export function renderAlert(root, data, ctx) {
  const { config } = ctx;
  const shown = data.error ? null : lib.bannerAlert(data.alerts ?? [], data.state, ctx.scene.clock);
  root.hidden = shown === null;
  if (shown === null) {
    fill(root);
    return;
  }
  const offset = config.volcano.utc_offset_hours;
  const safeUrl = /^https?:\/\//.test(shown.official_url);
  fill(root,
    el("span", { class: "alert-tag", dataset: { kind: shown.kind } },
      shown.kind === "onset" ? "Fountaining seen" : "Fountaining stopped"),
    el("span", { class: "alert-time mono" }, `${lib.localTime(shown.seen_at, offset)} ${lib.zone(offset)}`),
    el("span", { class: "alert-text" }, shown.headline),
    el("a", { href: `/media/${shown.overlay.split("/").map(encodeURIComponent).join("/")}`, target: "_blank",
      rel: "noopener" }, "Frame"),
    safeUrl ? el("a", { href: shown.official_url, target: "_blank", rel: "noopener" },
      `Official status: ${shown.official_agency}`) : null);
}
