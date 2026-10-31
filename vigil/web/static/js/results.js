// The replay's results against the official values: shown only when the API sends them (the clock at the episode's
// end). Tables are the same rows the replay's report.md prints; every cell is text.

import { el, fill } from "./dom.js";

export function renderResults(root, data) {
  const results = data.replay?.results;
  if (!results) {
    fill(root);
    return;
  }
  fill(root,
    el("h3", {}, "Against the official values"),
    results.tables.map((table) => [
      el("h4", {}, table.title),
      el("table", { class: "b-table" },
        el("thead", {}, el("tr", {}, table.header.map((h) => el("th", { scope: "col" }, h)))),
        el("tbody", {}, table.rows.map((row) => el("tr", {}, row.map((cell) => el("td", {}, cell)))))),
    ]),
    el("p", { class: "results-cost" }, `Meta API cost of the replay: $${results.cost_usd.toFixed(2)}`));
}
