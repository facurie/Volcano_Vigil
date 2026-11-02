"""The agent loop: Muse Spark calls the tools of vigil.agent.tools until it can answer.

Every turn resends the whole conversation (the task, each reply's output items
but its reasoning, and the tool results) with store=false, instead of chaining
turns with previous_response_id: Meta's response store failed in 4 of the 39
turns of one replay (503 "persistence service error", and a 400 "referenced
response not found or expired" on a chained turn), and each failure ended a
run. The input tokens cost the same either way. The instructions, tools and
reasoning effort go with every turn. Muse Spark may call several tools in one
turn; they run one after another, in order. A run ends when Muse Spark
answers without calling a tool (done), when it still calls tools on its last
turn (max_turns; it is told to answer on that turn), when a model turn would
push the run's Meta spend (its own turns plus the SAM and Muse Spark calls its
tools make) past `budget_usd` or the day past the daily cap (budget), or when
the API fails (error). A tool call that would exceed the budget does not end
the run: the model gets it as a tool error, and the run ends at the next
turn's check. Every turn and tool call is a row of `agent_steps`
under one `agent_runs` row: the trace the dashboard shows.

    vigil-agent --volcano kilauea --at 2026-10-17T05:00-10:00
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import sys
import time
from collections.abc import Callable, Sequence
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import openai

from vigil import db
from vigil.agent.tools import Tool, Toolbox, ToolContext
from vigil.calibration import load_calibration
from vigil.config import Sources, Volcano, load_sources
from vigil.meta.client import MetaClient
from vigil.meta.ledger import BudgetExceeded, CostLedger
from vigil.prompts import load_prompts
from vigil.settings import Settings
from vigil.timeutil import parse_utc, to_iso, utcnow
from vigil.wind import WindService

log = logging.getLogger(__name__)

MAX_TURNS = 12
BUDGET_USD = 0.30
TURN_RETRY_PAUSES = (2.0, 8.0)  # seconds before sending again a turn the server failed (HTTP 5xx: nothing billed)
INSTRUCTIONS = """\
You are Volcano Vigil, an agent that watches the public webcams of {name} ({country}) and measures what they \
show. The official source for this volcano is {agency} ({url}). You never issue alerts or alert levels: you \
describe what the cameras show, with numbers and the frame ids that support them.

It is {now} UTC{local}. The tools only see frames captured up to this time. Give tool times in UTC with a Z, \
e.g. {example}. The volcano's id is {volcano_id}.

How to work:
- Start with list_cameras_status. Only calibrated cameras give heights.
- Prefer work already done: track_window returns stored tracks for free when the window was tracked before. \
Tracking a new window costs about $0.01 per phrase and takes minutes; segment_frame costs $0.0025 and \
assess_frame up to $0.008 per frame.
- measure_track gives top_altitude (metres above sea level) and top_height (metres above the vent) of the \
mask's highest pixel, each with a one-sigma uncertainty. drift_bearing is only the side of the camera's line of \
sight the plume sits on: one camera cannot see drift along its line of sight.
- To check a plume's drift against the wind, call get_wind with the plume top's altitude and the measured \
drift_bearing; it compares that side with the mean wind between the vent and the top.
- Call tools that do not depend on each other in the same turn.
- Quote only numbers the tools returned, with their uncertainty; never invent one.

{finish}"""
REPORT = ("Finish with a short report in English: what each camera shows now; the measurements with ± sigma, units, "
          "capture times and frame ids; the drift against the wind; and what you could not measure and why.")
WRAP_UP = "No turns left: write your final report now with what you have, without calling tools."
DEFAULT_TASK = ("Check {name} now: which cameras show activity? Measure the plume and any lava fountain you can, "
                "compare the plume's drift with the forecast wind, and report.")


@dataclass(frozen=True)
class AgentRun:
    run_id: int
    status: str  # done | max_turns | budget | error
    turns: int
    cost_usd: float
    final_text: str
    error: str | None


def instructions(volcano: Volcano, volcano_id: str, now: datetime, finish: str = REPORT) -> str:
    local = ""
    if volcano.utc_offset_hours is not None:
        offset = timedelta(hours=volcano.utc_offset_hours)
        local = f" ({(now + offset):%Y-%m-%d %H:%M} local time, UTC{volcano.utc_offset_hours:+g})"
    return INSTRUCTIONS.format(name=volcano.name, country=volcano.country, agency=volcano.official_agency,
                               url=volcano.official_url, now=f"{now.astimezone(timezone.utc):%Y-%m-%d %H:%M}",
                               local=local, example=to_iso(now), volcano_id=volcano_id, finish=finish)


def run_agent(client: MetaClient, ctx: ToolContext, volcano_id: str, task: str, *, max_turns: int = MAX_TURNS,
              budget_usd: float = BUDGET_USD, effort: str = "medium", tools: Sequence[Tool] | None = None,
              finish: str = REPORT, text_format: dict[str, Any] | None = None,
              wall_clock: Callable[[], datetime] = utcnow, sleep: Callable[[float], None] = time.sleep) -> AgentRun:
    """Run the agent on one task at the context's clock and store its trace.

    `finish` is the instructions' closing request; with `text_format` (a Responses text.format) every turn asks
    for the final answer in that format. A turn the server fails (HTTP 5xx, e.g. Meta's 503 "persistence service
    error") is sent again after each pause of TURN_RETRY_PAUSES before the run ends in error.
    """
    conn = ctx.conn
    text = instructions(ctx.sources.volcanoes[volcano_id], volcano_id, ctx.now, finish)
    with conn:
        run_id = conn.execute(
            "INSERT INTO agent_runs (started_at, clock, volcano, task, model, status) VALUES (?, ?, ?, ?, ?, 'running')",
            (to_iso(wall_clock()), to_iso(ctx.now), volcano_id, task, client.spark_model)).lastrowid
    job = client.tagged(f"agent:{run_id}", budget_usd)
    toolbox = Toolbox(dataclasses.replace(ctx, client=job), tools)
    definitions = toolbox.definitions()
    conversation: list[dict[str, Any]] = [{"role": "user", "content": task}]
    seq, turns = 0, 0
    status, final, error = "max_turns", "", None

    def step(kind: str, **columns: Any) -> None:
        nonlocal seq
        seq += 1
        columns = {"run_id": run_id, "seq": seq, "turn": turns, "kind": kind, "created_at": to_iso(wall_clock()),
                   **columns}
        with conn:
            conn.execute(f"INSERT INTO agent_steps ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})",
                         tuple(columns.values()))

    try:
        for turn in range(1, max_turns + 1):
            if turn == max_turns:
                conversation.append({"role": "user", "content": WRAP_UP})
            try:
                for pause in (*TURN_RETRY_PAUSES, None):
                    try:
                        started = time.perf_counter()
                        reply = job.respond(input=conversation, tools=definitions, instructions=text, purpose="turn",
                                            store=False, effort=effort, context_tokens=0, text_format=text_format)
                        break
                    except openai.InternalServerError as exc:
                        if pause is None:
                            raise
                        log.warning("run %d, turn %d: %s; sending it again in %g s", run_id, turn, exc, pause)
                        sleep(pause)
            except BudgetExceeded as exc:
                status, error = "budget", str(exc)
                break
            except openai.APIError as exc:
                status, error = "error", f"{type(exc).__name__}: {exc}"[:500]
                break
            turns = turn
            step("model", response_id=reply.response_id, text=reply.text, reasoning=reply.reasoning,
                 cost_usd=reply.cost_usd, latency_ms=_ms(started))
            if not reply.calls:
                final = reply.text
                if reply.status == "incomplete":
                    status, error = "error", "the answer was cut off at max_output_tokens"
                elif reply.status != "completed":
                    status, error = "error", f"the answer ended with status {reply.status!r}"
                else:
                    status = "done"
                break
            if turn == max_turns:
                final = reply.text
                break
            conversation.extend(reply.items)
            for call in reply.calls:
                spent, started = job.tag_spent(), time.perf_counter()
                result, ok = toolbox.call(call.name, call.arguments)
                output = json.dumps(result, ensure_ascii=False)
                step("tool", tool_name=call.name, call_id=call.call_id, arguments=call.arguments, result=output,
                     ok=int(ok), cost_usd=job.tag_spent() - spent, latency_ms=_ms(started))
                conversation.append({"type": "function_call_output", "call_id": call.call_id, "output": output})
    except BaseException as exc:  # Ctrl-C or a bug: the run must not stay 'running'
        status, error = "error", f"{type(exc).__name__}: {exc}"[:500]
        raise
    finally:
        cost = job.tag_spent()
        with conn:
            conn.execute(
                "UPDATE agent_runs SET finished_at = ?, status = ?, turns = ?, cost_usd = ?, final_text = ?, "
                "error = ? WHERE id = ?", (to_iso(wall_clock()), status, turns, cost, final, error, run_id))
    return AgentRun(run_id, status, turns, cost, final, error)


def _ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)


def trace(conn, run_id: int) -> str:
    """A stored run as text: one line per step, then the final report."""
    run = conn.execute("SELECT * FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
    lines = [f"run {run_id} at {run['clock']} ({run['volcano']}): {run['status']} after {run['turns']} turns, "
             f"${run['cost_usd']:.4f}"]
    for row in conn.execute("SELECT * FROM agent_steps WHERE run_id = ? ORDER BY seq", (run_id,)):
        if row["kind"] == "model":
            if row["text"]:
                lines.append(f"  {row['turn']} model: {_short(row['text'])}")
        else:
            outcome = "ok" if row["ok"] else "error"
            lines.append(f"  {row['turn']} tool {row['tool_name']} {row['arguments']} -> {outcome} "
                         f"({row['latency_ms'] / 1000:.1f} s, ${row['cost_usd']:.4f}): {_short(row['result'])}")
    if run["error"]:
        lines.append(f"error: {run['error']}")
    lines += ["final:", run["final_text"] or ""]
    return "\n".join(lines)


def _short(text: str, limit: int = 160) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 3] + "..."


def context_from_settings(settings: Settings, conn, http: httpx.Client, now: datetime,
                          client: MetaClient | None = None, sources: Sources | None = None) -> ToolContext:
    """The tools' context from the config files the settings name, at clock `now`."""
    sources = sources or load_sources(settings.sources_path)
    return ToolContext(conn=conn, data_dir=settings.data_dir, sources=sources,
                       calibration=load_calibration(settings.calibration_path),
                       prompts=load_prompts(settings.prompts_path), winds=WindService(conn, http, sources), now=now,
                       client=client)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the Muse Spark agent on a volcano at a time: now, or a past "
                                                 "time to replay it.")
    parser.add_argument("--volcano", required=True, help="volcano id from the sources file, e.g. kilauea")
    parser.add_argument("--at", type=parse_utc, help="the agent's clock, e.g. 2026-10-17T05:00-10:00 (default: now)")
    parser.add_argument("--task", help="what to ask (default: check the volcano, measure, compare with the wind)")
    parser.add_argument("--max-turns", type=int, default=MAX_TURNS, help=f"model turns (default {MAX_TURNS})")
    parser.add_argument("--budget", type=float, default=BUDGET_USD,
                        help=f"USD for the whole run, tool calls included (default {BUDGET_USD})")
    parser.add_argument("--effort", choices=["low", "medium", "high"], default="medium", help="reasoning effort")
    args = parser.parse_args(argv)
    if args.max_turns < 1:
        parser.error("--max-turns must be at least 1")

    settings = Settings.from_env()
    sources = load_sources(settings.sources_path)
    if args.volcano not in sources.volcanoes:
        parser.error(f"unknown volcano {args.volcano!r} in {settings.sources_path}")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")  # the report may hold characters a Windows console cannot show
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    task = args.task or DEFAULT_TASK.format(name=sources.volcanoes[args.volcano].name)
    with closing(db.connect(settings.db_path)) as conn, \
            httpx.Client(headers={"User-Agent": settings.user_agent}, timeout=30) as http:
        ctx = context_from_settings(settings, conn, http, args.at or utcnow(), sources=sources)
        client = MetaClient.from_env(CostLedger(conn, settings.daily_budget_usd))
        result = run_agent(client, ctx, args.volcano, task, max_turns=args.max_turns, budget_usd=args.budget,
                           effort=args.effort)
        print(trace(conn, result.run_id))


if __name__ == "__main__":
    main()
