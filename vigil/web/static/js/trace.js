// The agent's trace: the runs by the clock and the steps of one. Model text, tool arguments and tool results are
// shown through el()/fill() (text) and JSON.stringify, never as markup.

import { el, fill } from "./dom.js";
import * as lib from "./lib.js";

const dollars = (cost) => `$${(cost ?? 0).toFixed(4)}`;
const pretty = (value) => (typeof value === "string" ? value : JSON.stringify(value, null, 2));

export function renderTrace(root, data, ctx) {
  const { config, scene, actions } = ctx;
  const select = root.querySelector("#run-select"), head = root.querySelector("#trace-head");
  const steps = root.querySelector("#steps");
  if (data.error) {
    fill(select);
    fill(head, el("p", { class: "error-note" }, `The agent trace could not be loaded (${data.error.message}).`));
    fill(steps);
    return;
  }
  const { runs, run, steps: rows } = data.trace;
  const offset = config.volcano.utc_offset_hours, zone = lib.zone(offset);
  const local = (when) => lib.localTime(when, offset);

  fill(select, runs.map((r) => el("option", {
    value: r.run_id, selected: run?.run_id === r.run_id,
  }, `${local(r.clock)} · run ${r.run_id} · ${r.status}`)));
  if (run) select.value = String(run.run_id);
  select.disabled = runs.length === 0;
  select.onchange = () => actions.traceRun(Number(select.value));

  if (!run) {
    fill(head, el("p", { class: "error-note" }, `No agent run by ${local(scene.clock)} ${zone}.`));
    fill(steps);
    return;
  }
  fill(head,
    el("div", {}, `Run ${run.run_id} at ${local(run.clock)} ${zone} · ${run.status} · ${run.turns} turns · ` +
      `${dollars(run.cost_usd)} · ${run.model}`),
    el("div", { class: "task" }, run.task),
    run.error ? el("div", {}, `Error: ${run.error}`) : null,
    run.bulletin_id ? el("div", {}, el("button", {
      type: "button", class: "link-button", onClick: () => actions.openBulletin(run.bulletin_id),
    }, `Open bulletin #${run.bulletin_id}`)) : null);

  // the run's last model step whose text is a JSON object is the bulletin draft
  let draft = null;
  for (const step of rows) {
    if (step.kind !== "model" || !step.text) continue;
    try {
      const parsed = JSON.parse(step.text);
      if (parsed && typeof parsed === "object") draft = { step, parsed };
    } catch { /* ordinary text */ }
  }
  fill(steps, rows.map((step) => {
    const content = step.kind === "tool" ? toolStep(step) : modelStep(step, draft?.step === step ? draft.parsed : null);
    return content && el("li", { class: "step" }, el("span", { class: "step-turn" }, `T${step.turn}`), content);
  }));
}

function modelStep(step, parsed) {
  if (!step.text && !step.reasoning) return null;
  return el("div", {},
    step.text ? el("p", { class: "step-say" }, parsed ? "Final answer: the bulletin draft" : step.text) : null,
    parsed ? el("details", {}, el("summary", {}, "Draft JSON"), el("pre", {}, JSON.stringify(parsed, null, 2))) : null,
    step.reasoning ? el("details", {}, el("summary", {}, "Reasoning summary"), el("p", {}, step.reasoning)) : null);
}

function toolStep(step) {
  const args = step.arguments;
  const shown = args && typeof args === "object" && !Array.isArray(args)
    ? Object.entries(args).map(([key, value]) => `${key}=${JSON.stringify(value)}`).join(", ")
    : (args === null || args === undefined ? "" : pretty(args));
  const meta = [step.ok === false ? el("span", { class: "failed" }, "✕ error") : "ok"];
  if (step.latency_ms !== null && step.latency_ms !== undefined) meta.push(`${(step.latency_ms / 1000).toFixed(1)} s`);
  meta.push(dollars(step.cost_usd));
  return el("div", {},
    el("div", { class: "step-call" }, el("span", { class: "fn" }, step.tool_name), `(${shown})`),
    el("div", { class: "step-meta" }, meta.flatMap((part, i) => (i ? [" · ", part] : [part]))),
    step.result === null || step.result === undefined ? null
      : el("details", {}, el("summary", {}, "Result"), el("pre", {}, pretty(step.result))));
}
