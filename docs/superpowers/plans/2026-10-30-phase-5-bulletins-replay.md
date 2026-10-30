# Phase 5: Bulletins and Replay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** the agent writes checked, bilingual (EN/ES) bulletins with evidence, and `vigia-replay --episode 55` runs the whole pipeline over Kīlauea's episode 55 on a simulated clock, producing six or more bulletins plus the comparison with the official USGS values.

**Architecture:**
- `vigia/agent/bulletin.py`: Muse Spark's final answer is a bulletin draft in a strict JSON format (`text.format` on every agent turn). The code then checks every quoted number against the stored measurements (bounded by the agent's clock), takes the wind check from the run's own `get_wind` result, draws each evidence frame with its masks, and adds the official agency, link and disclaimer from config. `vigia/agent/render.py` turns a bulletin into Markdown (one language) and HTML (both).
- `vigia/pipeline.py`: one step at time `now` runs the quality gate, then one SAM window per camera per closed hour with its measurements, then the agent's bulletin at each full hour. The live CLI `vigia-pipeline` and the replay use the same `Pipeline`.
- `vigia/replay.py`: the replay feeds the episode's frames into its own database as the simulated clock passes them, steps the pipeline, stores each step (so it can resume), and writes `timeline.json` and `report.md`.
- `vigia/episodes.py`: the official values, moved out of `scripts/validate_ep55.py`, so the replay can compare with them.
- `vigia/phases.py`: Muse Spark reads the episode's timelapse (video input) for its phases, set against the SAM-derived times and HVO's.

**Tech stack:** Python 3.12, OpenAI SDK against the Meta Model API (`muse-spark-1.3` with tools + `text.format`, video input through the Files API; `sam-3.1` video), Pydantic 2, SQLite, Pillow, numpy, ffmpeg.

---

## Facts this plan relies on (measured while planning, 2026-10-30)

**Probe A: tools plus a strict bulletin format on every turn** (`probe:bulletin`, $0.0102, scratch script)
- The schema had:
  - nested arrays of objects;
  - enums;
  - every property required, with `additionalProperties: false` at every level.
- It was sent as `text.format` on both turns of a chained run, together with a strict function tool.
- **Turn 1:** Muse Spark wrote plain-text commentary ("I'll measure the plume on kilauea-kp for your bulletin.") and called the tool. The format does not force commentary into JSON.
- **Turn 2:** valid JSON that parsed against the schema, with the keys in alphabetical order.
  - It copied the tool's numbers exactly (6951 ± 429, frame 29).
  - It wrote the Spanish **without accents** ("Se midio", "desgasificacion"). The instructions must ask for proper Spanish.
  - It read `drift_bearing` as "drifting toward bearing 224.4". The instructions must say that it is the side of the line of sight.
- Cached input tokens were reported (753 of 873) on the second probe run.
- **Meta API limits:** `tool_choice` accepts only `"auto"` (META_API_NOTES §2), so a turn cannot be forced to answer without tools. That is why the format goes on every turn.

**Probe B: Muse Spark video understanding** (`probe:phases`, two calls, $0.0997 in all)
- **Input:** the K2cam timelapse of episode 55:
  - 195 usable frames, 13:00–19:28Z;
  - assembled at 2 fps and 1280×720: 97.5 s, 24 MB;
  - uploaded with `purpose=user_data` and sent as `{"type": "input_video", "file_id": ...}`.
- **Cost per call:** 25,408 input tokens (about 130 per frame) and about 4,200 output tokens: $0.050, 27–32 s.
- **Answers** (HST; video second → frame index `round(second × fps)` → capture time):

  | Phase | HVO | SAM, K2cam | SAM, any camera | Muse Spark, plain prompt | Muse Spark, with lighting hint |
  |---|---|---|---|---|---|
  | onset | 03:19 | 04:28 | 03:25 (V1cam) | 04:20 | 04:18 |
  | peak | 04:50–05:10 | 04:52 | – | 07:33 | 06:42 |
  | decline | after 05:10 (650 ft at 06:02) | 05:16 | – | 09:02 | 08:56 |
  | end | 09:03 | 09:02 | 09:01 (V1cam) | 09:04 | 09:08 |

- **What the answers show:**
  - Muse Spark reads the printed time within about 2 minutes of the frame at the second it names.
  - It gets the end right.
  - It sees the onset only when the fountain rises above K2cam's foreground (04:20), as SAM does on K2cam (04:28).
  - It puts the peak after sunrise: the daylight fountain looks bigger. The lighting hint ("judge its height against fixed features, not by its brightness") moved it from 07:33 to 06:42, still wrong.
  - So the phases cross-check is qualitative, and the SAM times are the better reading. The plan keeps the hint and reports whatever comes out.
- **SAM-derived phases** (stored Phase 2 tracks, tallest fountain box in pixels per frame, 5-frame running median):
  - K2cam:
    - first detection 14:28:02Z, last 19:02:01Z;
    - running-median peak 522 px at 14:52:02Z;
    - the first frame under 90 % of the peak is about 15:16Z.
  - V1cam:
    - first 13:25:03Z, last 19:01:05Z.
    - Its PTZ zoom changes (9.4×, 1.4×, 1.0×) make its heights incomparable, so V1cam gives onset and end only.

**Stored data**
- **Episode 55 frames** in `data/vigia.sqlite`, 13:00–19:30Z: KPcam 78, K2cam 195, V1cam 195 (ids 6–474). All have a verdict, and all are usable.
  - Usable frames per hour: KP 12, K2 30, V1 30. The 19:00–19:30 half-hour has 6, 15 and 15.
  - Sizes: KP and K2 3840×2160, V1 1920×1080.
- **Tracking runs** 1–9 cover the whole episode in one window per camera and phrase. The replay does not use them: it tracks again in hourly windows in its own database.
- `drift_bearing` sigmas are 2.1–8.0°, and tools round degrees to one decimal.
- **Spend so far:** $0.912 + $0.110 (these probes) = **$1.02**.

**Cost and time of the acceptance replay (estimate)**
- **Tracking:** 3 cameras × 3 phrases × 7 windows = 63 SAM video requests. Each bills at least 50 frames: about $0.63.
- **Agent:** 7 runs (on the hours 14:00–19:00Z, plus the end at 19:30Z), $0.03–0.06 each, plus `assess_frame` calls: about $0.3–0.5.
- **Timelapse reading:** $0.05.
- **Total about $1.0–1.2**, under the daily cap of $5.
- **Wall time:** mask decoding is the slow part (Phase 2: 11 min for K2's 168 plume masks), so allow about an hour.

## File map

| File | Change | Responsibility |
|---|---|---|
| `vigia/meta/client.py` | modify | `respond(text_format=)`, `ask_json(videos=)` |
| `vigia/agent/loop.py` | modify | `REPORT`, `instructions(finish=)`, `run_agent(finish=, text_format=)`, `context_from_settings` |
| `vigia/agent/bulletin.py` | create | Draft format and models; checking, wind, evidence overlays; storage; `write_bulletin`; `vigia-bulletin` CLI |
| `vigia/agent/render.py` | create | Labels, local times, Markdown, HTML, `publish` |
| `vigia/db.py` | modify | Tables `bulletins` and `replay_ticks` |
| `vigia/episodes.py` | create | `Episode`, `EP55` and its official values, comparison rows (moved from the script) |
| `scripts/validate_ep55.py` | modify | Imports the episode and rows from `vigia.episodes`; its output does not change |
| `vigia/pipeline.py` | create | `Pipeline.step`: quality gate, hourly tracking and measuring, agent schedule; `vigia-pipeline` CLI |
| `vigia/replay.py` | create | Frame feed, ticks, resumable `run_replay`, comparison of bulletins, timeline and report; `vigia-replay` CLI |
| `vigia/phases.py` | create | `sam_phases`, `ask_phases` (Muse Spark video), `cross_check` |
| `pyproject.toml` | modify | Console scripts `vigia-bulletin`, `vigia-pipeline`, `vigia-replay` |
| `tests/test_meta_client.py`, `tests/test_agent_loop.py` | modify | Tests |
| `tests/test_bulletin.py`, `tests/test_render.py`, `tests/test_episodes.py`, `tests/test_pipeline.py`, `tests/test_replay.py`, `tests/test_phases.py` | create | Tests |
| `docs/research/replay_ep55.md` | create (orchestrator) | The acceptance replay: bulletins, comparison, phases, cost |

**Deviations from `docs/PLAN.md`, on purpose:**
- **What the model writes.** The official source and the disclaimer are in the bulletin schema of PLAN.md, but the model never writes them. They come from `sources.yaml` and a constant, so they can never be wrong or missing. The model writes only:
  - the activity level;
  - the headlines and bodies;
  - the measurements;
  - the evidence frame ids, each with its target and captions.
- **More fields per measurement.** Each one also names its camera and target. A `top_altitude` means nothing without them.
- **Wind.** The bulletin's wind check is the run's own `get_wind` result, so its numbers are the tool's.
- **Where the replay writes.** It uses its own database, `data/replay/ep55/vigia.sqlite`. It does not reuse the Phase 2 whole-episode tracks: it tracks hourly windows as live mode would. Its spend goes to that database's ledger, so the daily cap counts the two databases separately.
- **Where the pipeline lives.** The "pipeline runner that also serves live mode" is `vigia/pipeline.py` with its own CLI, `vigia-pipeline`, so it can run during episode 56.

**Conventions for every task:**
- English code and comments.
- Run the whole suite with `.venv\Scripts\python.exe -m pytest` before committing.
- Commit only the task's files.
- **No `Co-Authored-By` trailer.**
- Never push: the orchestrator pushes.

**Order:** Tasks 1–2 (client and loop) → 3–5 (bulletin and render) → 6–7 (`write_bulletin`, episodes) → 8 (pipeline) → 9–10 (replay and phases) → 11 (orchestrator). Later tests import helpers from earlier test files:
- `test_bulletin` imports `DRAFT` and `plume_frame`;
- `test_agent_loop` provides `Script` and `FAKE_TOOLS`.

---

### Task 1: Structured final answers and video input in the Meta client

**Files:**
- Modify: `vigia/meta/client.py`
- Test: `tests/test_meta_client.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_meta_client.py`:

```python
FORMAT = {"type": "json_schema", "name": "answer", "strict": True,
          "schema": {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"],
                     "additionalProperties": False}}


def test_respond_can_shape_the_final_answer_with_a_text_format(conn):
    api = FakeApi(lambda r: httpx.Response(200, json=turn_body([], text='{"n": 1}')))

    turn = make_client(api, conn).respond(input=[{"role": "user", "content": "n?"}], tools=[TOOL],
                                          instructions="Answer.", purpose="turn", text_format=FORMAT)

    assert api.json_body()["text"] == {"format": FORMAT}
    assert turn.text == '{"n": 1}'


def test_respond_without_a_text_format_leaves_the_answer_free(conn):
    api = FakeApi(lambda r: httpx.Response(200, json=turn_body([], text="Done.")))

    make_client(api, conn).respond(input=[{"role": "user", "content": "Go."}], tools=[TOOL], instructions="Go.",
                                   purpose="turn")

    assert "text" not in api.json_body()


def test_ask_json_sends_uploaded_videos_by_file_id(conn):
    api = FakeApi(lambda r: httpx.Response(200, json=response_body("muse-spark-1.3", '{"n": 3}', SPARK_USAGE)))

    answer = make_client(api, conn).ask_json(prompt="How many phases?", videos=["file-1"], schema_name="answer",
                                             schema=FORMAT["schema"], purpose="phases")

    assert answer == {"n": 3}
    assert api.json_body()["input"][0]["content"] == [{"type": "input_text", "text": "How many phases?"},
                                                     {"type": "input_video", "file_id": "file-1"}]


def test_a_video_counts_in_the_budget_estimate_before_the_call(conn):
    api = FakeApi(lambda r: httpx.Response(200, json=response_body("muse-spark-1.3", '{"n": 3}', SPARK_USAGE)))
    client = make_client(api, conn, budget=0.06)

    client.ask_json(prompt="n?", schema_name="answer", schema=FORMAT["schema"], purpose="text")  # estimated ~$0.017
    with pytest.raises(BudgetExceeded):  # 40,000 video tokens and 4,000 output tokens: ~$0.067
        client.ask_json(prompt="n?", videos=["file-1"], schema_name="answer", schema=FORMAT["schema"],
                        purpose="video")

    assert len(api.requests) == 1
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_meta_client.py -q`
Expected: 4 failures (`unexpected keyword argument 'text_format'` and `'videos'`).

- [ ] **Step 3: Implement**

In `vigia/meta/client.py`, next to `_IMAGE_TOKENS_ESTIMATE`:

```python
_VIDEO_TOKENS_ESTIMATE = 40_000  # a 195-frame 1280x720 timelapse took 25,408 input tokens (Phase 5 probe)
```

Replace `ask_json`'s signature, docstring, content and estimate:

```python
    def ask_json(
        self,
        *,
        prompt: str,
        schema_name: str,
        schema: dict[str, Any],
        purpose: str,
        images: Sequence[bytes] = (),
        videos: Sequence[str] = (),
        instructions: str | None = None,
        effort: str = "low",
        max_output_tokens: int = 4000,
    ) -> dict[str, Any]:
        """Ask Muse Spark a question about zero or more images and videos (Files API ids, from upload_video);
        the answer follows `schema`."""
        content = [{"type": "input_text", "text": prompt}]
        content += [{"type": "input_image", "image_url": _data_url(image)} for image in images]
        content += [{"type": "input_video", "file_id": file_id} for file_id in videos]
```

and, further down in the same method:

```python
        input_estimate = (len(images) * _IMAGE_TOKENS_ESTIMATE + len(videos) * _VIDEO_TOKENS_ESTIMATE
                          + _PROMPT_OVERHEAD_TOKENS + (len(prompt) + len(instructions or "")) // 3)
```

In `respond`, add the parameter after `context_tokens`, extend the docstring, set the format, and count it in the estimate:

```python
        context_tokens: int = 0,
        text_format: dict[str, Any] | None = None,
    ) -> Turn:
        """One agent turn of Muse Spark with function tools, chained to the previous turn.

        The server keeps the conversation of `previous_response_id` but not the request settings, so the
        tools, instructions and reasoning effort go with every turn. `context_tokens` (the previous turn's)
        feeds the pre-call budget estimate. `text_format` (a Responses `text.format`, e.g. a strict
        json_schema) shapes the final answer; a turn that calls tools still writes its commentary as plain text.
        """
```

```python
        if previous_response_id is not None:
            request["previous_response_id"] = previous_response_id
        if text_format is not None:
            request["text"] = {"format": text_format}
        sent = (len(json.dumps(input)) + len(json.dumps(tools)) + len(instructions)
                + len(json.dumps(text_format or {})))
```

- [ ] **Step 4: Run the tests**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: all pass (342 + 4).

- [ ] **Step 5: Commit**

```bash
git add vigia/meta/client.py tests/test_meta_client.py
git commit -m "Let Muse Spark turns take an answer format and questions take uploaded videos"
```

---

### Task 2: An answer format and a closing request for agent runs

**Files:**
- Modify: `vigia/agent/loop.py`
- Test: `tests/test_agent_loop.py`

- [ ] **Step 1: Write the failing tests**

In `tests/test_agent_loop.py`, extend the import from `vigia.agent.loop` to:

```python
from vigia.agent.loop import REPORT, WRAP_UP, context_from_settings, instructions, main, run_agent, trace
```

and append:

```python
FORMAT = {"type": "json_schema", "name": "answer", "strict": True,
          "schema": {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"],
                     "additionalProperties": False}}


def test_a_run_can_ask_for_its_final_answer_in_a_format(conn, tmp_path):
    api = Script(turn_body([("echo", '{"n": 1}')], text="Checking.", rid="resp_1"), turn_body([], text='{"n": 1}'))

    result = run(conn, tmp_path, api, finish="Answer with n as JSON.", text_format=FORMAT)

    assert (result.status, result.final_text) == ("done", '{"n": 1}')
    assert [request["text"] for request in api.requests] == [{"format": FORMAT}] * 2
    assert all(request["instructions"].endswith("\n\nAnswer with n as JSON.") for request in api.requests)


def test_by_default_a_run_asks_for_a_free_text_report(conn, tmp_path):
    api = Script(turn_body([], text="All quiet."))

    run(conn, tmp_path, api)

    assert "text" not in api.requests[0]
    assert api.requests[0]["instructions"].endswith("\n\n" + REPORT)


def test_context_from_settings_reads_the_config_files(cli_env, conn):
    from vigia.settings import Settings
    settings = Settings.from_env()

    ctx = context_from_settings(settings, conn, httpx.Client(), T0)

    assert (ctx.now, ctx.client, ctx.data_dir) == (T0, None, settings.data_dir)
    assert list(ctx.sources.volcanoes) == ["kilauea"]
```

The last test reuses the `cli_env` fixture defined further down in the same file. It points `SOURCES_PATH` at a small YAML file. The calibration and prompts paths keep their defaults, `config/calibration.yaml` and `config/prompts.yaml`, which exist because pytest runs from the repo root.

- [ ] **Step 2: Run them to see them fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_agent_loop.py -q`
Expected: ImportError (`REPORT`, `context_from_settings`).

- [ ] **Step 3: Implement**

In `vigia/agent/loop.py`, end `INSTRUCTIONS` with a `{finish}` placeholder instead of the report paragraph:

```python
- Call tools that do not depend on each other in the same turn.
- Quote only numbers the tools returned, with their uncertainty; never invent one.

{finish}"""
REPORT = ("Finish with a short report in English: what each camera shows now; the measurements with ± sigma, units, "
          "capture times and frame ids; the drift against the wind; and what you could not measure and why.")
```

(`REPORT` is exactly the paragraph it replaces, so the default instructions do not change.)

Change `instructions`:

```python
def instructions(volcano: Volcano, volcano_id: str, now: datetime, finish: str = REPORT) -> str:
    local = ""
    if volcano.utc_offset_hours is not None:
        offset = timedelta(hours=volcano.utc_offset_hours)
        local = f" ({(now + offset):%Y-%m-%d %H:%M} local time, UTC{volcano.utc_offset_hours:+g})"
    return INSTRUCTIONS.format(name=volcano.name, country=volcano.country, agency=volcano.official_agency,
                               url=volcano.official_url, now=f"{now.astimezone(timezone.utc):%Y-%m-%d %H:%M}",
                               local=local, example=to_iso(now), volcano_id=volcano_id, finish=finish)
```

Change `run_agent`'s signature and its first line, and pass the format on every turn:

```python
def run_agent(client: MetaClient, ctx: ToolContext, volcano_id: str, task: str, *, max_turns: int = MAX_TURNS,
              budget_usd: float = BUDGET_USD, effort: str = "medium", tools: Sequence[Tool] | None = None,
              finish: str = REPORT, text_format: dict[str, Any] | None = None,
              wall_clock: Callable[[], datetime] = utcnow) -> AgentRun:
    """Run the agent on one task at the context's clock and store its trace.

    `finish` is the instructions' closing request; with `text_format` (a Responses text.format) every turn asks
    for the final answer in that format.
    """
    conn = ctx.conn
    text = instructions(ctx.sources.volcanoes[volcano_id], volcano_id, ctx.now, finish)
```

```python
                reply = job.respond(input=pending, tools=definitions, instructions=text, purpose="turn",
                                    previous_response_id=previous, effort=effort, context_tokens=context_tokens,
                                    text_format=text_format)
```

Add the context builder after `trace`'s helpers (before `main`), and use it in `main`:

```python
def context_from_settings(settings: Settings, conn, http: httpx.Client, now: datetime,
                          client: MetaClient | None = None, sources: Sources | None = None) -> ToolContext:
    """The tools' context from the config files the settings name, at clock `now`."""
    sources = sources or load_sources(settings.sources_path)
    return ToolContext(conn=conn, data_dir=settings.data_dir, sources=sources,
                       calibration=load_calibration(settings.calibration_path),
                       prompts=load_prompts(settings.prompts_path), winds=WindService(conn, http, sources), now=now,
                       client=client)
```

Import `Sources` with `from vigia.config import Sources, Volcano, load_sources`. In `main`, replace the `ToolContext(...)` construction with:

```python
        ctx = context_from_settings(settings, conn, http, args.at or utcnow(), sources=sources)
```

- [ ] **Step 4: Run the tests**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add vigia/agent/loop.py tests/test_agent_loop.py
git commit -m "Let an agent run close with any request and an answer format, and build its context from the settings"
```

---
### Task 3: The bulletin draft: format and models

**Files:**
- Create: `vigia/agent/bulletin.py`
- Test: `tests/test_bulletin.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_bulletin.py`:

```python
import json
from typing import get_args

import pytest
from pydantic import ValidationError

from vigia.agent.bulletin import (DRAFT_FORMAT, DRAFT_SCHEMA, ActivityLevel, BulletinDraft, DraftEvidence,
                                  DraftMeasurement)

DRAFT = {  # the shape of Muse Spark's answer in the Phase 5 planning probe
    "activity_level": "fountaining",
    "headline_en": "Lava fountain and a tall plume at Kīlauea",
    "headline_es": "Fuente de lava y una columna alta en el Kīlauea",
    "body_en": "KPcam measured the plume top at 6,951 ± 429 m above sea level at 04:55.",
    "body_es": "KPcam midió el tope de la columna a 6.951 ± 429 m sobre el nivel del mar a las 04:55.",
    "measurements": [{"camera_id": "kilauea-kp", "target": "plume", "metric": "top_altitude", "value": 6951,
                      "sigma": 429, "unit": "m", "frame_ids": [29]}],
    "evidence": [{"frame_id": 29, "target": "plume", "caption_en": "The plume at its peak.",
                  "caption_es": "La columna en su máximo."}],
}


def objects(schema):
    """Every object schema in `schema`, itself included."""
    if schema.get("type") == "object":
        yield schema
        for prop in schema["properties"].values():
            yield from objects(prop)
    elif schema.get("type") == "array":
        yield from objects(schema["items"])


def test_the_draft_format_is_strict_at_every_level():
    assert DRAFT_FORMAT == {"type": "json_schema", "name": "bulletin", "schema": DRAFT_SCHEMA, "strict": True}
    found = list(objects(DRAFT_SCHEMA))
    assert len(found) == 3
    for schema in found:
        assert schema["required"] == list(schema["properties"]) and schema["additionalProperties"] is False


def test_the_draft_format_has_the_draft_models_fields():
    assert list(DRAFT_SCHEMA["properties"]) == list(BulletinDraft.model_fields)
    items = {name: DRAFT_SCHEMA["properties"][name]["items"]["properties"] for name in ("measurements", "evidence")}
    assert list(items["measurements"]) == list(DraftMeasurement.model_fields)
    assert list(items["evidence"]) == list(DraftEvidence.model_fields)
    assert DRAFT_SCHEMA["properties"]["activity_level"]["enum"] == list(get_args(ActivityLevel))
    assert items["measurements"]["metric"]["enum"] == ["top_height", "top_altitude", "area", "drift_offset",
                                                       "drift_bearing"]


def test_a_draft_parses_from_muse_sparks_json():
    draft = BulletinDraft.model_validate_json(json.dumps(DRAFT))

    assert draft.activity_level == "fountaining"
    assert (draft.measurements[0].frame_ids, draft.measurements[0].value) == ([29], 6951)
    assert draft.evidence[0].caption_es == "La columna en su máximo."


@pytest.mark.parametrize("change", [
    {"activity_level": "red_alert"},
    {"headline_en": ""},
    {"disclaimer": "Not official."},
    {"measurements": [{**DRAFT["measurements"][0], "frame_ids": []}]},
    {"measurements": [{**DRAFT["measurements"][0], "sigma": -1}]},
    {"measurements": [{**DRAFT["measurements"][0], "metric": "speed"}]},
])
def test_a_draft_outside_the_format_is_refused(change):
    with pytest.raises(ValidationError):
        BulletinDraft.model_validate({**DRAFT, **change})
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_bulletin.py -q`
Expected: ModuleNotFoundError (`vigia.agent.bulletin`).

- [ ] **Step 3: Implement**

Create `vigia/agent/bulletin.py`:

```python
"""Bulletins: what the agent tells the public about a volcano, in English and Spanish, with its evidence.

Muse Spark writes a draft as the final answer of an agent run, in the strict JSON format DRAFT_FORMAT: a
descriptive activity level (what the cameras show, never an alert level), a headline and a body in each
language, the measurements the body quotes and the frames that show them. The code adds what must never depend
on the model: the volcano's official agency and link, the disclaimer, the wind check as the get_wind tool
returned it, an overlay of each evidence frame with its masks, and a check of every quoted number against the
stored measurements up to the agent's clock (a number nothing stored supports is marked unverified). Bulletins
are stored in the `bulletins` table; vigia.agent.render turns them into Markdown and HTML.
"""

from __future__ import annotations

from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

from vigia.agent.tools import Metric
from vigia.prompts import Target

ActivityLevel = Literal["no_view", "quiet", "degassing", "incandescence", "fountaining"]
Unit = Literal["m", "m2", "deg"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DraftMeasurement(_Strict):
    camera_id: str
    target: Target
    metric: Metric
    value: float
    sigma: float = Field(ge=0)
    unit: Unit
    frame_ids: list[int] = Field(min_length=1)


class DraftEvidence(_Strict):
    frame_id: int
    target: Target
    caption_en: str
    caption_es: str


class BulletinDraft(_Strict):
    """What Muse Spark writes."""

    activity_level: ActivityLevel
    headline_en: str = Field(min_length=1)
    headline_es: str = Field(min_length=1)
    body_en: str = Field(min_length=1)
    body_es: str = Field(min_length=1)
    measurements: list[DraftMeasurement]
    evidence: list[DraftEvidence]


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def _enum(literal: Any) -> dict[str, Any]:
    return {"type": "string", "enum": list(get_args(literal))}


DRAFT_SCHEMA = _object({
    "activity_level": _enum(ActivityLevel),
    "headline_en": {"type": "string"},
    "headline_es": {"type": "string"},
    "body_en": {"type": "string"},
    "body_es": {"type": "string"},
    "measurements": {"type": "array", "items": _object({
        "camera_id": {"type": "string"}, "target": _enum(Target), "metric": _enum(Metric),
        "value": {"type": "number"}, "sigma": {"type": "number"}, "unit": _enum(Unit),
        "frame_ids": {"type": "array", "items": {"type": "integer"}}})},
    "evidence": {"type": "array", "items": _object({
        "frame_id": {"type": "integer"}, "target": _enum(Target),
        "caption_en": {"type": "string"}, "caption_es": {"type": "string"}})},
})
DRAFT_FORMAT = {"type": "json_schema", "name": "bulletin", "schema": DRAFT_SCHEMA, "strict": True}
```

- [ ] **Step 4: Run the tests**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add vigia/agent/bulletin.py tests/test_bulletin.py
git commit -m "Define the bulletin draft Muse Spark writes and its strict answer format"
```

---

### Task 4: Building a bulletin: checked numbers, the run's wind, evidence overlays, storage

**Files:**
- Modify: `vigia/agent/bulletin.py`, `vigia/db.py`
- Test: `tests/test_bulletin.py`

- [ ] **Step 1: Write the failing tests**

In `tests/test_bulletin.py`, replace the import block with:

```python
import json
from typing import get_args

import pytest
from PIL import Image
from pydantic import ValidationError

from conftest import NOW
from test_agent_tools import (SIZE, T0, add_frame, add_measurement, add_run, add_track, context, detection_ids,
                              store)  # store is a fixture
from vigia.agent.bulletin import (DRAFT_FORMAT, DRAFT_SCHEMA, ActivityLevel, BulletinDraft, DraftEvidence,
                                  DraftMeasurement, build_bulletin, draw_evidence, load_bulletin, run_wind,
                                  store_bulletin, verify)
from vigia.timeutil import to_iso
```

and append:

```python
def plume_frame(conn, store, minutes=-5, top_altitude=6950.9, sigma=429.4):
    """A KPcam frame `minutes` from the clock, with a tracked plume (box 60,60-120,150) and its measured top."""
    frame_id = add_frame(conn, store, "kilauea-kp", minutes)
    track_id = add_track(conn, add_run(conn, "kilauea-kp", "plume", [frame_id], phrase="steam"), [frame_id])
    add_measurement(conn, frame_id, "top_altitude", top_altitude, sigma, detection_id=detection_ids(conn, track_id)[0])
    return frame_id


def quoted(frame_id, **change):
    return DraftMeasurement.model_validate({**DRAFT["measurements"][0], "frame_ids": [frame_id], **change})


def shown(frame_id, **change):
    return DraftEvidence.model_validate({**DRAFT["evidence"][0], "frame_id": frame_id, **change})


def test_a_quoted_number_a_stored_measurement_supports_is_verified(conn, store, tmp_path):
    frame_id = plume_frame(conn, store)

    cited = verify(conn, quoted(frame_id), T0)

    assert cited.verified and cited.captured_at == "2026-10-17T14:55:00Z"


@pytest.mark.parametrize("change", [{"value": 7500}, {"sigma": 200}, {"metric": "top_height"},
                                    {"camera_id": "kilauea-k2"}, {"unit": "m2"}, {"frame_ids": [999]}])
def test_a_quoted_number_nothing_stored_supports_is_not_verified(conn, store, tmp_path, change):
    frame_id = plume_frame(conn, store)

    cited = verify(conn, quoted(frame_id, **change), T0)

    assert (cited.verified, cited.captured_at) == (False, None)


def test_a_measurement_captured_after_the_clock_supports_nothing(conn, store, tmp_path):
    frame_id = plume_frame(conn, store, minutes=5)

    assert not verify(conn, quoted(frame_id), T0).verified


def test_the_wind_check_is_the_runs_last_get_wind_result_with_a_drift(conn):
    checked = {"volcano": "kilauea", "model_hour": "2026-10-17T15:00:00Z", "layer_mean": {"toward_deg": 151},
               "drift_check": {"angle_deg": 73.3, "consistent": True}, "levels": [{"pressure_hpa": 850}]}
    steps = [("get_wind", checked, 1), ("get_wind", {"volcano": "kilauea", "levels": []}, 1),
             ("get_wind", {"error": "bad"}, 0), ("echo", {"drift_check": "not wind"}, 1)]
    with conn:
        for seq, (name, result, ok) in enumerate(steps, 1):
            conn.execute("INSERT INTO agent_steps (run_id, seq, turn, kind, created_at, tool_name, result, ok) "
                         "VALUES (7, ?, 1, 'tool', '2026-10-28T00:00:00Z', ?, ?, ?)", (seq, name, json.dumps(result), ok))

    assert run_wind(conn, 7) == {key: value for key, value in checked.items() if key != "levels"}
    assert run_wind(conn, 8) is None


def test_an_evidence_frame_is_drawn_with_its_targets_masks(conn, store, tmp_path):
    frame_id = plume_frame(conn, store)

    evidence = draw_evidence(conn, tmp_path, tmp_path / "bulletins" / "run1", shown(frame_id), T0)

    assert evidence.overlay == f"bulletins/run1/frame{frame_id}_plume.jpg"
    assert (evidence.camera_id, evidence.captured_at) == ("kilauea-kp", "2026-10-17T14:55:00Z")
    with Image.open(tmp_path / evidence.overlay) as drawn:
        rgb = drawn.convert("RGB")
    assert rgb.width == SIZE[0] and rgb.height > SIZE[1]  # the legend strip goes below the frame
    inside, outside = rgb.getpixel((90, 100)), rgb.getpixel((300, 100))
    assert inside[2] > outside[2] + 40  # the plume's colour is blue-cyan


def test_a_large_evidence_frame_is_drawn_1280_pixels_wide(conn, store, tmp_path):
    frame_id = add_frame(conn, store, "kilauea-kp", -5, size=(2560, 1440))
    add_track(conn, add_run(conn, "kilauea-kp", "plume", [frame_id]), [frame_id])

    evidence = draw_evidence(conn, tmp_path, tmp_path / "bulletins" / "run1", shown(frame_id), T0)

    with Image.open(tmp_path / evidence.overlay) as drawn:
        assert drawn.width == 1280


def test_build_bulletin_checks_the_draft_and_adds_the_official_source_and_disclaimer(conn, store, tmp_path):
    frame_id = plume_frame(conn, store)
    draft = BulletinDraft.model_validate({
        **DRAFT, "measurements": [quoted(frame_id).model_dump(), quoted(frame_id, value=9000).model_dump()],
        "evidence": [shown(frame_id).model_dump()]})

    bulletin = build_bulletin(context(conn, tmp_path), "kilauea", 3, draft, tmp_path / "bulletins",
                              wall_clock=lambda: NOW)

    assert (bulletin.run_id, bulletin.volcano, bulletin.clock, bulletin.created_at) == (
        3, "kilauea", "2026-10-17T15:00:00Z", to_iso(NOW))
    assert [m.verified for m in bulletin.measurements] == [True, False] and not bulletin.verified
    assert (bulletin.official_agency, bulletin.official_url) == ("USGS Hawaiian Volcano Observatory (HVO)",
                                                                 "https://www.usgs.gov/volcanoes/kilauea")
    assert "does not replace official alerts" in bulletin.disclaimer_en
    assert bulletin.disclaimer_en.endswith("https://www.usgs.gov/volcanoes/kilauea")
    assert "No reemplaza las alertas" in bulletin.disclaimer_es
    assert bulletin.evidence[0].overlay == f"bulletins/run3/frame{frame_id}_plume.jpg"
    assert bulletin.notes == ["1 of 2 quoted number(s) match no stored measurement"]
    assert bulletin.wind is None and bulletin.headline_es == DRAFT["headline_es"]


def test_evidence_after_the_clock_or_beyond_three_frames_is_left_out(conn, store, tmp_path):
    early, late = plume_frame(conn, store), add_frame(conn, store, "kilauea-kp", 5)
    draft = BulletinDraft.model_validate({**DRAFT, "measurements": [],
                                          "evidence": [shown(i).model_dump() for i in (late, early, early, early)]})

    bulletin = build_bulletin(context(conn, tmp_path), "kilauea", 3, draft, tmp_path / "bulletins")

    assert [e.frame_id for e in bulletin.evidence] == [early, early]
    assert bulletin.notes == [f"evidence frame {late} left out: no such frame captured by 2026-10-17T15:00:00Z",
                              "1 evidence frame(s) beyond 3 left out"]


def test_a_stored_bulletin_loads_back_with_its_id(conn, tmp_path):
    draft = BulletinDraft.model_validate({**DRAFT, "evidence": []})
    bulletin = build_bulletin(context(conn, tmp_path), "kilauea", 3, draft, tmp_path / "bulletins")

    stored = store_bulletin(conn, bulletin)

    assert stored.id == 1 and load_bulletin(conn, 1) == stored
    row = conn.execute("SELECT * FROM bulletins").fetchone()
    assert (row["run_id"], row["activity_level"], row["verified"], row["clock"]) == (
        3, "fountaining", 0, "2026-10-17T15:00:00Z")
    with pytest.raises(KeyError):
        load_bulletin(conn, 2)
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_bulletin.py -q`
Expected: ImportError (`build_bulletin`, ...).

- [ ] **Step 3: Implement**

In `vigia/db.py`, append to `SCHEMA` (before its closing `"""`):

```sql
CREATE TABLE IF NOT EXISTS bulletins (       -- one bulletin of an agent run (vigia.agent.bulletin)
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id         INTEGER NOT NULL REFERENCES agent_runs (id),
    volcano        TEXT    NOT NULL,
    clock          TEXT    NOT NULL,  -- UTC time it describes: the agent's clock
    created_at     TEXT    NOT NULL,  -- UTC wall clock
    activity_level TEXT    NOT NULL,  -- no_view | quiet | degassing | incandescence | fountaining (never an alert level)
    headline_en    TEXT    NOT NULL,
    headline_es    TEXT    NOT NULL,
    verified       INTEGER NOT NULL,  -- 1 if every quoted number matched a stored measurement
    body           TEXT    NOT NULL   -- the whole bulletin as JSON (vigia.agent.bulletin.Bulletin)
);
CREATE INDEX IF NOT EXISTS idx_bulletins_clock ON bulletins (volcano, clock);
```

In `vigia/agent/bulletin.py`, end the module docstring with the sentence "Evidence overlays are JPEGs at most 1,280 pixels wide, in the bulletin's folder.", replace the imports with:

```python
from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, get_args

import numpy as np
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

from vigia.agent.tools import Metric, ToolContext
from vigia.overlay import Layer, draw_layers
from vigia.prompts import Target
from vigia.timeutil import to_iso, utcnow
from vigia.tracking import detection_mask
```

add, after `Unit`:

```python
EVIDENCE_MAX = 3
OVERLAY_WIDTH = 1280  # evidence overlays are scaled down to this width
COLORS = {"plume": (80, 200, 255), "fountain": (255, 90, 30), "incandescence": (255, 210, 0)}
TOLERANCE = {"m": 1.0, "m2": 1.0, "deg": 0.1}  # what rounding can change in a quoted number, besides 1 %
DISCLAIMER_EN = ("Automated, experimental reading of public webcams by Vigía Andino. It does not replace official "
                 "alerts or warnings. For the official status of {name}, see {agency}: {url}")
DISCLAIMER_ES = ("Lectura automática y experimental de cámaras públicas hecha por Vigía Andino. No reemplaza las "
                 "alertas ni los avisos oficiales. Para el estado oficial de {name}, consulte a {agency}: {url}")
```

add, after `BulletinDraft`:

```python
class CitedMeasurement(DraftMeasurement):
    verified: bool                  # a stored measurement on one of its frames, captured by the clock, matches it
    captured_at: str | None = None  # UTC capture time of that frame


class Evidence(DraftEvidence):
    camera_id: str
    captured_at: str  # UTC
    overlay: str      # the frame with the target's masks drawn, relative to the data dir (POSIX)


class Bulletin(_Strict):
    """A published bulletin: the draft, checked, plus what never depends on the model."""

    id: int | None = None
    run_id: int
    volcano: str
    volcano_name: str
    utc_offset_hours: float | None
    clock: str       # UTC: the time it describes, the agent's clock
    created_at: str  # UTC wall clock
    activity_level: ActivityLevel
    headline_en: str
    headline_es: str
    body_en: str
    body_es: str
    measurements: list[CitedMeasurement]
    evidence: list[Evidence]
    wind: dict[str, Any] | None  # the run's last get_wind result that checked a drift, without its levels
    official_agency: str
    official_url: str
    disclaimer_en: str
    disclaimer_es: str
    notes: list[str] = []  # what the code left out or could not support

    @property
    def verified(self) -> bool:
        return all(m.verified for m in self.measurements)
```

and append, after `DRAFT_FORMAT`:

```python
def _close(quoted: float, stored: float, unit: str) -> bool:
    return abs(quoted - stored) <= max(TOLERANCE[unit], 0.01 * abs(stored))


def verify(conn: sqlite3.Connection, measurement: DraftMeasurement, clock: datetime) -> CitedMeasurement:
    """The quoted measurement, verified if a stored one of its camera, target, metric and unit, on one of its
    frames and captured by the clock, has its value and sigma."""
    marks = ",".join("?" * len(measurement.frame_ids))
    rows = conn.execute(
        f"""SELECT value, sigma, captured_at FROM measurements
            WHERE camera_id = ? AND target = ? AND metric = ? AND unit = ? AND frame_id IN ({marks})
            AND captured_at <= ? ORDER BY captured_at DESC""",
        (measurement.camera_id, measurement.target, measurement.metric, measurement.unit, *measurement.frame_ids,
         to_iso(clock))).fetchall()
    for row in rows:
        if (_close(measurement.value, row["value"], measurement.unit)
                and _close(measurement.sigma, row["sigma"], measurement.unit)):
            return CitedMeasurement(**measurement.model_dump(), verified=True, captured_at=row["captured_at"])
    return CitedMeasurement(**measurement.model_dump(), verified=False)


def run_wind(conn: sqlite3.Connection, run_id: int) -> dict[str, Any] | None:
    """The run's last successful get_wind result that checked a drift, without its level list."""
    for row in conn.execute(
            "SELECT result FROM agent_steps WHERE run_id = ? AND tool_name = 'get_wind' AND ok = 1 ORDER BY seq DESC",
            (run_id,)):
        result = json.loads(row["result"])
        if "drift_check" in result:
            return {key: value for key, value in result.items() if key != "levels"}
    return None


def draw_evidence(conn: sqlite3.Connection, data_dir: Path, folder: Path, item: DraftEvidence,
                  clock: datetime) -> Evidence | None:
    """Draw the target's masks on the evidence frame into `folder` (inside the data dir); None if no such frame
    was captured by the clock."""
    frame = conn.execute("SELECT * FROM frames WHERE id = ? AND captured_at <= ?",
                         (item.frame_id, to_iso(clock))).fetchone()
    if frame is None:
        return None
    detections = conn.execute(
        """SELECT d.*, r.phrase FROM detections d JOIN tracks t ON t.id = d.track_id
           JOIN tracking_runs r ON r.id = t.run_id WHERE d.frame_id = ? AND r.target = ? ORDER BY d.id""",
        (frame["id"], item.target)).fetchall()
    with Image.open(data_dir / frame["path"]) as source:
        image = source.convert("RGB")
    scale = min(1.0, OVERLAY_WIDTH / image.width)
    size = (round(image.width * scale), round(image.height * scale))
    if scale < 1:
        image = image.resize(size, Image.Resampling.LANCZOS)
    layers = []
    for detection in detections:
        mask = detection_mask(detection, frame["width"], frame["height"])
        if scale < 1:
            mask = np.asarray(Image.fromarray(mask).resize(size, Image.Resampling.NEAREST), dtype=bool)
        layers.append(Layer(mask, COLORS[item.target], f"{item.target}: {detection['phrase']}"))
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"frame{frame['id']}_{item.target}.jpg"
    draw_layers(image, layers).save(path, quality=85)
    return Evidence(**item.model_dump(), camera_id=frame["camera_id"], captured_at=frame["captured_at"],
                    overlay=path.relative_to(data_dir).as_posix())


def build_bulletin(ctx: ToolContext, volcano_id: str, run_id: int, draft: BulletinDraft, out_dir: Path, *,
                   wall_clock: Callable[[], datetime] = utcnow) -> Bulletin:
    """Check the draft against what was stored by the agent's clock and add what never depends on the model.
    Evidence overlays go to out_dir/run<run_id>, which must be inside the data dir."""
    volcano = ctx.sources.volcanoes[volcano_id]
    measurements = [verify(ctx.conn, m, ctx.now) for m in draft.measurements]
    evidence, notes = [], []
    for item in draft.evidence[:EVIDENCE_MAX]:
        drawn = draw_evidence(ctx.conn, ctx.data_dir, out_dir / f"run{run_id}", item, ctx.now)
        if drawn is None:
            notes.append(f"evidence frame {item.frame_id} left out: no such frame captured by {to_iso(ctx.now)}")
        else:
            evidence.append(drawn)
    if len(draft.evidence) > EVIDENCE_MAX:
        notes.append(f"{len(draft.evidence) - EVIDENCE_MAX} evidence frame(s) beyond {EVIDENCE_MAX} left out")
    unverified = sum(not m.verified for m in measurements)
    if unverified:
        notes.append(f"{unverified} of {len(measurements)} quoted number(s) match no stored measurement")
    names = {"name": volcano.name, "agency": volcano.official_agency, "url": volcano.official_url}
    return Bulletin(
        run_id=run_id, volcano=volcano_id, volcano_name=volcano.name, utc_offset_hours=volcano.utc_offset_hours,
        clock=to_iso(ctx.now), created_at=to_iso(wall_clock()),
        **draft.model_dump(exclude={"measurements", "evidence"}), measurements=measurements, evidence=evidence,
        wind=run_wind(ctx.conn, run_id), official_agency=volcano.official_agency, official_url=volcano.official_url,
        disclaimer_en=DISCLAIMER_EN.format(**names), disclaimer_es=DISCLAIMER_ES.format(**names), notes=notes)


def store_bulletin(conn: sqlite3.Connection, bulletin: Bulletin) -> Bulletin:
    """Insert the bulletin; returns it with its id."""
    with conn:
        bulletin_id = conn.execute(
            """INSERT INTO bulletins (run_id, volcano, clock, created_at, activity_level, headline_en, headline_es,
                                      verified, body) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '')""",
            (bulletin.run_id, bulletin.volcano, bulletin.clock, bulletin.created_at, bulletin.activity_level,
             bulletin.headline_en, bulletin.headline_es, int(bulletin.verified))).lastrowid
        stored = bulletin.model_copy(update={"id": bulletin_id})
        conn.execute("UPDATE bulletins SET body = ? WHERE id = ?", (stored.model_dump_json(), bulletin_id))
    return stored


def load_bulletin(conn: sqlite3.Connection, bulletin_id: int) -> Bulletin:
    row = conn.execute("SELECT body FROM bulletins WHERE id = ?", (bulletin_id,)).fetchone()
    if row is None:
        raise KeyError(f"no bulletin {bulletin_id}")
    return Bulletin.model_validate_json(row["body"])
```

- [ ] **Step 4: Run the tests**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add vigia/agent/bulletin.py vigia/db.py tests/test_bulletin.py
git commit -m "Check a bulletin's numbers against the stored measurements, draw its evidence and store it"
```

---

### Task 5: Rendering a bulletin as Markdown and HTML

**Files:**
- Create: `vigia/agent/render.py`
- Test: `tests/test_render.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_render.py`:

```python
from typing import get_args

from vigia.agent.bulletin import ActivityLevel, Bulletin, CitedMeasurement, Evidence
from vigia.agent.render import LEVELS, METRICS, TARGETS, local_time, number, publish, to_html, to_markdown
from vigia.agent.tools import Metric
from vigia.prompts import Target

WIND = {"volcano": "kilauea", "model_hour": "2026-10-17T15:00:00Z", "source": "Open-Meteo Historical Forecast API",
        "altitude_m": 6951, "layer_mean": {"bottom_m": 1080, "top_m": 6951, "from_deg": 331, "toward_deg": 151,
                                           "speed_ms": 3.3},
        "drift_check": {"measured_side_deg": 224.4, "wind_toward_deg": 151, "angle_deg": 73.3, "consistent": True}}


def bulletin(**change):
    measured = dict(camera_id="kilauea-kp", target="plume", frame_ids=[29])
    base = Bulletin(
        id=4, run_id=3, volcano="kilauea", volcano_name="Kīlauea", utc_offset_hours=-10,
        clock="2026-10-17T15:00:00Z", created_at="2026-10-28T18:00:00Z", activity_level="fountaining",
        headline_en="Lava fountain and a tall plume", headline_es="Fuente de lava y una columna alta",
        body_en="KPcam measured the plume top.\n\nThe wind pushes it southwest.",
        body_es="KPcam midió el tope de la columna.\n\nEl viento la empuja al suroeste.",
        measurements=[
            CitedMeasurement(**measured, metric="top_altitude", value=6951, sigma=429, unit="m", verified=True,
                             captured_at="2026-10-17T14:55:05Z"),
            CitedMeasurement(**measured, metric="drift_bearing", value=224.4, sigma=2.1, unit="deg",
                             verified=False)],
        evidence=[Evidence(frame_id=29, target="plume", caption_en="The plume at its peak.",
                           caption_es="La columna en su máximo.", camera_id="kilauea-kp",
                           captured_at="2026-10-17T14:55:05Z", overlay="bulletins/run3/frame29_plume.jpg")],
        wind=WIND, official_agency="USGS Hawaiian Volcano Observatory (HVO)",
        official_url="https://www.usgs.gov/volcanoes/kilauea",
        disclaimer_en="It does not replace official alerts or warnings.",
        disclaimer_es="No reemplaza las alertas ni los avisos oficiales.",
        notes=["1 of 2 quoted number(s) match no stored measurement"])
    return base.model_copy(update=change)


def test_every_level_target_and_metric_has_a_label_in_each_language():
    assert set(LEVELS) == set(get_args(ActivityLevel))
    assert set(TARGETS) == set(get_args(Target)) and set(METRICS) == set(get_args(Metric))


def test_times_are_shown_in_the_volcanos_local_time():
    assert local_time("2026-10-17T14:55:05Z", -10) == "2026-10-17 04:55 (UTC-10)"
    assert local_time("2026-10-17T14:55:05Z", None) == "2026-10-17 14:55 UTC"


def test_numbers_use_each_languages_separators():
    assert (number(6951, "en"), number(6951, "es")) == ("6,951", "6.951")
    assert (number(3.3, "en", 1), number(3.3, "es", 1)) == ("3.3", "3,3")


def test_the_english_markdown_has_the_headline_numbers_wind_evidence_and_source():
    text = to_markdown(bulletin(), "en", image_root="../../")

    assert text.startswith("# Lava fountain and a tall plume\n")
    assert "Kīlauea · 2026-10-17 05:00 (UTC-10) · Activity: Lava fountain" in text
    assert "> **It does not replace official alerts or warnings.**" in text
    assert "| plume: top above sea level | kilauea-kp | 6,951 ± 429 m | 2026-10-17 04:55 (UTC-10) | 29 | yes |" in text
    assert "| plume: side of the line of sight | kilauea-kp | 224° ± 2° | – | 29 | no |" in text
    assert "from 331° toward 151° at 3.3 m/s" in text and "73° from where the wind blows: consistent." in text
    assert "![The plume at its peak.](../../bulletins/run3/frame29_plume.jpg)" in text
    assert "- 1 of 2 quoted number(s) match no stored measurement" in text
    assert text.endswith("Official source: [USGS Hawaiian Volcano Observatory (HVO)]"
                         "(https://www.usgs.gov/volcanoes/kilauea)\n")


def test_the_spanish_markdown_speaks_spanish():
    text = to_markdown(bulletin(), "es")

    assert text.startswith("# Fuente de lava y una columna alta\n")
    assert "Actividad: Fuente de lava" in text and "> **No reemplaza las alertas ni los avisos oficiales.**" in text
    assert "| columna: tope sobre el nivel del mar | kilauea-kp | 6.951 ± 429 m |" in text and "| sí |" in text
    assert "a 3,3 m/s" in text and "coherente" in text
    assert "Fuente oficial: [USGS Hawaiian Volcano Observatory (HVO)]" in text


def test_a_calm_wind_is_not_judged():
    calm = {**WIND, "drift_check": {**WIND["drift_check"], "consistent": None}}

    assert "too calm to tell" in to_markdown(bulletin(wind=calm), "en")
    assert "demasiado calmo para juzgar" in to_markdown(bulletin(wind=calm), "es")


def test_the_html_page_has_both_languages_and_escapes_the_models_text():
    page = to_html(bulletin(headline_en="<script>alert(1)</script>"))

    assert "<script>alert" not in page and "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert '<article lang="en">' in page and '<article lang="es">' in page
    assert page.count('class="disclaimer"') == 2
    assert "<p>The wind pushes it southwest.</p>" in page
    assert '<a href="https://www.usgs.gov/volcanoes/kilauea">' in page
    assert '<img src="bulletins/run3/frame29_plume.jpg" alt="The plume at its peak.">' in page


def test_publish_writes_the_pages_where_the_overlays_resolve(tmp_path):
    folder = publish(bulletin(), tmp_path, tmp_path / "bulletins")

    assert folder == tmp_path / "bulletins" / "run3"
    assert sorted(path.name for path in folder.iterdir()) == ["bulletin.en.md", "bulletin.es.md", "bulletin.html"]
    assert "](../../bulletins/run3/frame29_plume.jpg)" in (folder / "bulletin.en.md").read_text(encoding="utf-8")
    assert 'src="../../bulletins/run3/frame29_plume.jpg"' in (folder / "bulletin.html").read_text(encoding="utf-8")
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_render.py -q`
Expected: ModuleNotFoundError (`vigia.agent.render`).

- [ ] **Step 3: Implement**

Create `vigia/agent/render.py`. It imports `Bulletin` only for type checking, so `vigia.agent.bulletin` can import it in Task 6 without a cycle.

```python
"""Bulletins as Markdown (one language) and HTML (both), and the files a bulletin is published as.

Times show in the volcano's local time with its UTC offset. In HTML every text the model wrote is escaped.
"""

from __future__ import annotations

import html
import os
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from vigia.timeutil import parse_utc

if TYPE_CHECKING:
    from vigia.agent.bulletin import Bulletin, CitedMeasurement

Lang = Literal["en", "es"]
LEVELS = {  # activity level: (English, Spanish); what the cameras show, never an alert level
    "no_view": ("No usable view", "Sin vista útil"),
    "quiet": ("No visible activity", "Sin actividad visible"),
    "degassing": ("Gas or steam plume", "Columna de gas o vapor"),
    "incandescence": ("Glowing lava, no fountain", "Lava incandescente, sin fuente"),
    "fountaining": ("Lava fountain", "Fuente de lava"),
}
TARGETS = {"plume": ("plume", "columna"), "fountain": ("lava fountain", "fuente de lava"),
           "incandescence": ("glow", "incandescencia")}
METRICS = {
    "top_height": ("top above the vent", "tope sobre la boca"),
    "top_altitude": ("top above sea level", "tope sobre el nivel del mar"),
    "area": ("area", "área"),
    "drift_offset": ("drift across the line of sight", "deriva transversal a la visual"),
    "drift_bearing": ("side of the line of sight", "lado de la visual"),
}
WORDS = {
    "activity": ("Activity", "Actividad"), "measurements": ("Measurements", "Mediciones"),
    "what": ("What", "Qué"), "camera": ("Camera", "Cámara"), "value": ("Value", "Valor"),
    "captured": ("Captured", "Captura"), "frames": ("Frames", "Cuadros"), "checked": ("Checked", "Verificado"),
    "yes": ("yes", "sí"), "no": ("no", "no"), "wind": ("Wind", "Viento"), "evidence": ("Evidence", "Evidencia"),
    "notes": ("Notes", "Notas"), "official": ("Official source", "Fuente oficial"),
}
STYLE = ("body{font-family:system-ui,sans-serif;max-width:860px;margin:2rem auto;padding:0 1rem;line-height:1.5}"
         ".disclaimer{background:#fff4d6;border-left:4px solid #e0a800;padding:.6rem .8rem}"
         "table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:.25rem .5rem;text-align:left}"
         "img{max-width:100%}article+article{border-top:2px solid #ddd;margin-top:2rem}")


def _pick(pair: tuple[str, str], lang: Lang) -> str:
    return pair[0] if lang == "en" else pair[1]


def local_time(utc: str, offset_hours: float | None) -> str:
    """'2026-10-17 04:55 (UTC-10)': a UTC time in the volcano's local time; in UTC when it has no offset."""
    when = parse_utc(utc)
    if offset_hours is None:
        return f"{when:%Y-%m-%d %H:%M} UTC"
    return f"{when + timedelta(hours=offset_hours):%Y-%m-%d %H:%M} (UTC{offset_hours:+g})"


def number(value: float, lang: Lang, decimals: int = 0) -> str:
    """6,951.5 in English, 6.951,5 in Spanish."""
    text = f"{value:,.{decimals}f}"
    return text if lang == "en" else text.replace(",", "\0").replace(".", ",").replace("\0", ".")


def quantity(m: CitedMeasurement, lang: Lang) -> str:
    if m.unit == "deg":
        return f"{number(m.value, lang)}° ± {number(m.sigma, lang)}°"
    return f"{number(m.value, lang)} ± {number(m.sigma, lang)} {'m²' if m.unit == 'm2' else 'm'}"


def wind_text(b: Bulletin, lang: Lang) -> str:
    """The run's wind check in one language."""
    layer, check = b.wind["layer_mean"], b.wind["drift_check"]
    hour = local_time(b.wind["model_hour"], b.utc_offset_hours)
    low, high = number(layer["bottom_m"], lang), number(layer["top_m"], lang)
    speed = number(layer["speed_ms"], lang, 1)
    side, angle = number(check["measured_side_deg"], lang), number(check["angle_deg"], lang)
    if lang == "en":
        verdict = {True: "consistent", False: "not consistent", None: "too calm to tell"}[check["consistent"]]
        return (f"Model wind ({b.wind['source']}, {hour}): between {low} and {high} m it blows from "
                f"{layer['from_deg']}° toward {layer['toward_deg']}° at {speed} m/s. The plume was seen on the "
                f"{side}° side of the camera's line of sight, {angle}° from where the wind blows: {verdict}.")
    verdict = {True: "coherente", False: "no coherente",
               None: "viento demasiado calmo para juzgar"}[check["consistent"]]
    return (f"Viento del modelo ({b.wind['source']}, {hour}): entre {low} y {high} m sopla desde "
            f"{layer['from_deg']}° hacia {layer['toward_deg']}° a {speed} m/s. La columna se vio del lado de {side}° "
            f"de la visual de la cámara, a {angle}° de hacia donde sopla el viento: {verdict}.")


def _texts(b: Bulletin, lang: Lang) -> tuple[str, str, str]:
    if lang == "en":
        return b.headline_en, b.body_en, b.disclaimer_en
    return b.headline_es, b.body_es, b.disclaimer_es


def _header(lang: Lang) -> list[str]:
    return [_pick(WORDS[key], lang) for key in ("what", "camera", "value", "captured", "frames", "checked")]


def _rows(b: Bulletin, lang: Lang) -> list[list[str]]:
    rows = []
    for m in b.measurements:
        captured = local_time(m.captured_at, b.utc_offset_hours) if m.captured_at else "–"
        rows.append([f"{_pick(TARGETS[m.target], lang)}: {_pick(METRICS[m.metric], lang)}", m.camera_id,
                     quantity(m, lang), captured, ", ".join(map(str, m.frame_ids)),
                     _pick(WORDS["yes" if m.verified else "no"], lang)])
    return rows


def to_markdown(b: Bulletin, lang: Lang, *, image_root: str = "") -> str:
    """The bulletin in one language; each evidence image links to image_root plus its data-dir path."""
    headline, body, disclaimer = _texts(b, lang)
    level = _pick(LEVELS[b.activity_level], lang)
    when = local_time(b.clock, b.utc_offset_hours)
    lines = [f"# {headline}", "", f"{b.volcano_name} · {when} · {_pick(WORDS['activity'], lang)}: {level}", "",
             f"> **{disclaimer}**", "", body, ""]
    if b.measurements:
        lines += [f"## {_pick(WORDS['measurements'], lang)}", "", "| " + " | ".join(_header(lang)) + " |",
                  "|---|---|---|---|---|---|"]
        lines += ["| " + " | ".join(row) + " |" for row in _rows(b, lang)] + [""]
    if b.wind:
        lines += [f"## {_pick(WORDS['wind'], lang)}", "", wind_text(b, lang), ""]
    if b.evidence:
        lines += [f"## {_pick(WORDS['evidence'], lang)}", ""]
        for e in b.evidence:
            caption = e.caption_en if lang == "en" else e.caption_es
            alt = caption.replace("[", "(").replace("]", ")")
            lines += [f"![{alt}]({image_root}{e.overlay})", "",
                      f"*{caption}* ({e.camera_id}, {local_time(e.captured_at, b.utc_offset_hours)})", ""]
    if b.notes:
        lines += [f"## {_pick(WORDS['notes'], lang)}", ""] + [f"- {note}" for note in b.notes] + [""]
    lines.append(f"{_pick(WORDS['official'], lang)}: [{b.official_agency}]({b.official_url})")
    return "\n".join(lines) + "\n"


def _article(b: Bulletin, lang: Lang, image_root: str) -> str:
    e = html.escape
    headline, body, disclaimer = _texts(b, lang)
    level = _pick(LEVELS[b.activity_level], lang)
    parts = [f'<article lang="{lang}">', f'<p class="disclaimer">{e(disclaimer)}</p>', f"<h1>{e(headline)}</h1>",
             f"<p>{e(b.volcano_name)} · {e(local_time(b.clock, b.utc_offset_hours))} · "
             f"{_pick(WORDS['activity'], lang)}: {e(level)}</p>"]
    parts += [f"<p>{e(paragraph.strip())}</p>" for paragraph in body.split("\n\n") if paragraph.strip()]
    if b.measurements:
        parts += [f"<h2>{_pick(WORDS['measurements'], lang)}</h2>", "<table>",
                  "<tr>" + "".join(f"<th>{e(cell)}</th>" for cell in _header(lang)) + "</tr>"]
        parts += ["<tr>" + "".join(f"<td>{e(cell)}</td>" for cell in row) + "</tr>" for row in _rows(b, lang)]
        parts.append("</table>")
    if b.wind:
        parts += [f"<h2>{_pick(WORDS['wind'], lang)}</h2>", f"<p>{e(wind_text(b, lang))}</p>"]
    if b.evidence:
        parts.append(f"<h2>{_pick(WORDS['evidence'], lang)}</h2>")
        for item in b.evidence:
            caption = item.caption_en if lang == "en" else item.caption_es
            when = local_time(item.captured_at, b.utc_offset_hours)
            parts.append(f'<figure><img src="{e(image_root + item.overlay)}" alt="{e(caption)}">'
                         f"<figcaption>{e(caption)} ({e(item.camera_id)}, {e(when)})</figcaption></figure>")
    if b.notes:
        parts += [f"<h2>{_pick(WORDS['notes'], lang)}</h2>", "<ul>"]
        parts += [f"<li>{e(note)}</li>" for note in b.notes] + ["</ul>"]
    parts += [f'<p>{_pick(WORDS["official"], lang)}: <a href="{e(b.official_url)}">{e(b.official_agency)}</a></p>',
              "</article>"]
    return "\n".join(parts)


def to_html(b: Bulletin, *, image_root: str = "") -> str:
    """The bulletin as one HTML page, English then Spanish."""
    articles = "\n".join(_article(b, lang, image_root) for lang in ("en", "es"))
    return (f'<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            f"<title>{html.escape(b.headline_en)}</title>\n<style>{STYLE}</style>\n</head>\n<body>\n{articles}\n"
            "</body>\n</html>\n")


def publish(b: Bulletin, data_dir: Path, out_dir: Path) -> Path:
    """Write bulletin.html, bulletin.en.md and bulletin.es.md into out_dir/run<run id>; returns that folder."""
    folder = out_dir / f"run{b.run_id}"
    folder.mkdir(parents=True, exist_ok=True)
    root = Path(os.path.relpath(data_dir, folder)).as_posix() + "/"
    (folder / "bulletin.html").write_text(to_html(b, image_root=root), encoding="utf-8")
    for lang in ("en", "es"):
        (folder / f"bulletin.{lang}.md").write_text(to_markdown(b, lang, image_root=root), encoding="utf-8")
    return folder
```

- [ ] **Step 4: Run the tests**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add vigia/agent/render.py tests/test_render.py
git commit -m "Render bulletins as Markdown in each language and as one escaped HTML page"
```

---

### Task 6: The agent writes the bulletin, and `vigia-bulletin`

**Files:**
- Modify: `vigia/agent/bulletin.py`, `pyproject.toml`
- Test: `tests/test_bulletin.py`

- [ ] **Step 1: Write the failing tests**

In `tests/test_bulletin.py`, add to the imports:

```python
import httpx
import openai

from test_agent_loop import FAKE_TOOLS, SOURCES_YAML, Script
from test_meta_client import make_client, turn_body
from vigia.agent.bulletin import BULLETIN_FINISH, main, write_bulletin
from vigia.meta.client import MetaClient
```

and append:

```python
QUIET = {**DRAFT, "activity_level": "no_view", "measurements": [], "evidence": []}


def write(conn, tmp_path, api):
    return write_bulletin(make_client(api, conn), context(conn, tmp_path), "kilauea", tmp_path / "bulletins",
                          tools=FAKE_TOOLS, wall_clock=lambda: NOW)


def test_the_agent_writes_the_bulletin_in_its_format_and_it_is_stored_and_published(conn, store, tmp_path):
    frame_id = plume_frame(conn, store)
    draft = {**DRAFT, "measurements": [quoted(frame_id).model_dump()], "evidence": [shown(frame_id).model_dump()]}
    api = Script(turn_body([("echo", '{"n": 1}')], text="Measuring.", rid="resp_1"),
                 turn_body([], text=json.dumps(draft)))

    written = write(conn, tmp_path, api)

    assert written.problem is None and written.bulletin.id == 1 and written.bulletin.verified
    assert [request["text"] for request in api.requests] == [{"format": DRAFT_FORMAT}] * 2
    assert all(request["instructions"].endswith(BULLETIN_FINISH) for request in api.requests)
    assert load_bulletin(conn, 1) == written.bulletin
    folder = tmp_path / "bulletins" / f"run{written.run.run_id}"
    assert (folder / "bulletin.html").exists() and (folder / f"frame{frame_id}_plume.jpg").exists()


def test_a_final_answer_that_is_not_a_bulletin_stores_nothing(conn, tmp_path):
    written = write(conn, tmp_path, Script(turn_body([], text="The plume is high.")))

    assert written.bulletin is None and written.problem.startswith("the final answer is not a bulletin")
    assert written.run.status == "done"
    assert conn.execute("SELECT COUNT(*) FROM bulletins").fetchone()[0] == 0


def test_a_failed_run_writes_no_bulletin(conn, tmp_path):
    failure = httpx.Response(500, json={"error": {"message": "boom", "type": "server_error", "param": None,
                                                  "code": None}})

    written = write(conn, tmp_path, Script(failure))

    assert written.bulletin is None and written.problem.startswith("the agent run ended with error")


def test_the_task_recalls_the_last_bulletin_before_the_clock_only(conn, tmp_path):
    draft = BulletinDraft.model_validate(QUIET)
    for clock, headline in (("2026-10-17T14:00:00Z", "Fountain rising"), ("2026-10-17T16:00:00Z", "From later")):
        bulletin = build_bulletin(context(conn, tmp_path), "kilauea", 1, draft, tmp_path / "bulletins")
        store_bulletin(conn, bulletin.model_copy(update={"clock": clock, "headline_en": headline,
                                                         "activity_level": "fountaining"}))
    api = Script(turn_body([], text=json.dumps(QUIET)))

    write(conn, tmp_path, api)

    task = api.requests[0]["input"][0]["content"]
    assert task.startswith("Check Kilauea now")
    assert task.endswith("\nYour previous bulletin, at 2026-10-17 14:00 UTC, reported fountaining: Fountain rising")
    assert "From later" not in task


@pytest.fixture
def cli_env(monkeypatch, tmp_path):
    sources = tmp_path / "sources.yaml"
    sources.write_text(SOURCES_YAML, encoding="utf-8")
    monkeypatch.setenv("SOURCES_PATH", str(sources))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "data" / "vigia.sqlite"))
    return tmp_path


def fake_meta(monkeypatch, api):
    def from_env(ledger):  # the CLI's own ledger, so its database connection is the only one
        sdk = openai.OpenAI(base_url="https://api.meta.ai/v1", api_key="test-key", max_retries=0,
                            http_client=httpx.Client(transport=httpx.MockTransport(api)))
        return MetaClient(sdk, ledger)

    monkeypatch.setattr("vigia.agent.bulletin.MetaClient.from_env", from_env)


def test_cli_prints_the_trace_and_the_bulletin_in_both_languages(cli_env, monkeypatch, capsys):
    fake_meta(monkeypatch, Script(turn_body([("list_cameras_status", "{}")], rid="resp_1"),
                                  turn_body([], text=json.dumps(QUIET))))

    main(["--volcano", "kilauea", "--at", "2026-10-17T05:00-10:00"])

    out = capsys.readouterr().out
    assert "at 2026-10-17T15:00:00Z (kilauea): done after 2 turns" in out
    assert "# Lava fountain and a tall plume at Kīlauea" in out and "# Fuente de lava y una columna alta" in out
    assert "Kilauea · 2026-10-17 05:00 (UTC-10) · Activity: No usable view" in out
    assert (cli_env / "data" / "bulletins" / "run1" / "bulletin.html").exists()


def test_cli_exits_with_an_error_when_no_bulletin_comes_back(cli_env, monkeypatch, capsys):
    fake_meta(monkeypatch, Script(turn_body([], text="No JSON here.")))

    with pytest.raises(SystemExit) as exit_info:
        main(["--volcano", "kilauea", "--at", "2026-10-17T05:00-10:00"])

    assert exit_info.value.code == 1
    assert "no bulletin: the final answer is not a bulletin" in capsys.readouterr().out
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_bulletin.py -q`
Expected: ImportError (`BULLETIN_FINISH`, `write_bulletin`, `main`).

- [ ] **Step 3: Implement**

In `vigia/agent/bulletin.py`, add these imports:

```python
import argparse
import logging
import sys
from contextlib import closing
from dataclasses import dataclass

import httpx
from pydantic import ValidationError

from vigia import db
from vigia.agent.loop import (BUDGET_USD, DEFAULT_TASK, MAX_TURNS, AgentRun, context_from_settings, run_agent,
                              trace)
from vigia.agent.render import local_time, publish, to_markdown
from vigia.meta.client import MetaClient
from vigia.meta.ledger import CostLedger
from vigia.settings import Settings
from vigia.timeutil import parse_utc
```

Add after the disclaimers:

```python
BULLETIN_FINISH = """\
Finish with a bulletin for the public, as the JSON your answer format describes, in English and in Spanish (natural \
Spanish with all its accents and ñ, not a word-for-word translation):
- activity_level: what the cameras show now. It describes, it never sets an alert level: no_view (no camera can see \
the vent: cloud, fog, darkness or no fresh frames), quiet (a clear view with no plume, glow or fountain), degassing \
(a gas or steam plume and no glowing lava), incandescence (glowing lava but no fountain), fountaining (a lava \
fountain).
- headline: one sentence. body: three to six sentences on what each useful camera shows, the measurements with \
± sigma, units and local times, the drift against the wind, and what could not be measured and why.
- measurements: every number the body quotes from measure_track or get_history, exactly as the tool returned it \
(value and sigma), with its camera, target, metric, unit and the frame ids it came from. Quote per-frame values \
(latest or max), not means.
- evidence: one to three frames that best show what you describe, each with the target whose mask to draw and a \
short caption in each language.
- drift_bearing is the side of the camera's line of sight the plume sits on, not the direction it travels.
Do not write a disclaimer or the official source: every bulletin gets them."""
```

Append after `load_bulletin`:

```python
@dataclass(frozen=True)
class Written:
    run: AgentRun
    bulletin: Bulletin | None
    problem: str | None = None  # why there is no bulletin


def write_bulletin(client: MetaClient, ctx: ToolContext, volcano_id: str, out_dir: Path, *, task: str | None = None,
                   wall_clock: Callable[[], datetime] = utcnow, **agent: Any) -> Written:
    """Run the agent at the context's clock with a bulletin as its final answer, then check, store and publish it
    in out_dir (inside the data dir). The task recalls the last bulletin before the clock, so the agent can say
    what changed. Other keyword arguments go to run_agent."""
    volcano = ctx.sources.volcanoes[volcano_id]
    task = task or DEFAULT_TASK.format(name=volcano.name)
    previous = ctx.conn.execute(
        "SELECT clock, activity_level, headline_en FROM bulletins WHERE volcano = ? AND clock < ? "
        "ORDER BY clock DESC, id DESC LIMIT 1", (volcano_id, to_iso(ctx.now))).fetchone()
    if previous is not None:
        task += (f"\nYour previous bulletin, at {local_time(previous['clock'], volcano.utc_offset_hours)}, reported "
                 f"{previous['activity_level']}: {previous['headline_en']}")
    run = run_agent(client, ctx, volcano_id, task, finish=BULLETIN_FINISH, text_format=DRAFT_FORMAT,
                    wall_clock=wall_clock, **agent)
    if run.status not in ("done", "max_turns"):
        return Written(run, None, f"the agent run ended with {run.status}: {run.error}")
    try:
        draft = BulletinDraft.model_validate_json(run.final_text)
    except ValidationError as exc:
        return Written(run, None, f"the final answer is not a bulletin: {exc.errors()[0]['msg']}")
    bulletin = store_bulletin(ctx.conn, build_bulletin(ctx, volcano_id, run.run_id, draft, out_dir,
                                                       wall_clock=wall_clock))
    publish(bulletin, ctx.data_dir, out_dir)
    return Written(run, bulletin)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Have the agent write a bulletin about a volcano at a time (now, "
                                                 "or a past time to replay it), check it and publish it.")
    parser.add_argument("--volcano", required=True, help="volcano id from the sources file, e.g. kilauea")
    parser.add_argument("--at", type=parse_utc, help="the agent's clock, e.g. 2026-10-17T05:00-10:00 (default: now)")
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
        sys.stdout.reconfigure(errors="replace")  # a Windows console may not show every character
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    out_dir = settings.data_dir / "bulletins"
    with closing(db.connect(settings.db_path)) as conn, \
            httpx.Client(headers={"User-Agent": settings.user_agent}, timeout=30) as http:
        ctx = context_from_settings(settings, conn, http, args.at or utcnow(), sources=sources)
        client = MetaClient.from_env(CostLedger(conn, settings.daily_budget_usd))
        written = write_bulletin(client, ctx, args.volcano, out_dir, max_turns=args.max_turns,
                                 budget_usd=args.budget, effort=args.effort)
        print(trace(conn, written.run.run_id))
    if written.bulletin is None:
        print(f"no bulletin: {written.problem}")
        raise SystemExit(1)
    for lang in ("en", "es"):
        print()
        print(to_markdown(written.bulletin, lang))
    print(f"published in {out_dir / f'run{written.run.run_id}'}")
```

`load_sources` needs `from vigia.config import load_sources`. In `pyproject.toml`, add under `[project.scripts]`:

```toml
vigia-bulletin = "vigia.agent.bulletin:main"
```

then reinstall: `.venv\Scripts\python.exe -m pip install -e ".[dev]" -q`.

- [ ] **Step 4: Run the tests**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add vigia/agent/bulletin.py pyproject.toml tests/test_bulletin.py
git commit -m "Have the agent write, check and publish a bulletin, and add vigia-bulletin"
```

---

### Task 7: Episodes and their official values, out of the validation script

**Files:**
- Create: `vigia/episodes.py`
- Modify: `scripts/validate_ep55.py`
- Test: `tests/test_episodes.py`

The replay must compare its own database with HVO's values, so the official values and the row functions move from `scripts/validate_ep55.py` into the package. **The script's output must not change.**

- [ ] **Step 1: Record the script's current output**

Run: `.venv\Scripts\python.exe scripts\validate_ep55.py` then `git diff --stat docs/VALIDATION.md`.
Expected: only the "Generated by ... on <date>" line differs. Winds come from the `wind_profiles` cache, so no network is needed. Then run `git checkout docs/VALIDATION.md`.

- [ ] **Step 2: Write the failing tests**

Create `tests/test_episodes.py`:

```python
import pytest

from test_agent_tools import add_frame, add_measurement, add_run, add_track, detection_ids, store  # store: fixture
from vigia.episodes import EP55, EPISODES, drift_rows, end_rows, height_row, local_time, table
from vigia.timeutil import parse_utc


def measured(conn, store, camera_id, minutes, target, metric, value, sigma, unit="m"):
    """A frame `minutes` from 15:00Z with one tracked detection and one measurement of it; returns the frame id."""
    frame_id = add_frame(conn, store, camera_id, minutes)
    track_id = add_track(conn, add_run(conn, camera_id, target, [frame_id]), [frame_id])
    add_measurement(conn, frame_id, metric, value, sigma, detection_id=detection_ids(conn, track_id)[0],
                    target=target, unit=unit)
    return frame_id


def test_episode_55_states_hvos_values_in_metres_and_utc():
    assert EPISODES["55"] is EP55
    assert (EP55.volcano, EP55.cameras, EP55.timelapse_camera) == (
        "kilauea", ("kilauea-kp", "kilauea-k2", "kilauea-v1"), "kilauea-k2")
    peak = EP55.checks[4]
    assert (peak.quantity, peak.camera_id, peak.metric, peak.aggregate) == (
        "plume top (peak)", "kilauea-kp", "top_altitude", "max")
    assert peak.official_m == pytest.approx(7620)
    assert EP55.phases["onset"] == (parse_utc("2026-10-17T13:19:00Z"),) * 2
    assert EP55.phases["peak"] == (parse_utc("2026-10-17T14:50:00Z"), parse_utc("2026-10-17T15:10:00Z"))
    assert EP55.phases["end"] == (parse_utc("2026-10-17T19:03:00Z"),) * 2
    assert local_time("2026-10-17T14:55:05Z", EP55.local, seconds=True) == "04:55:05"


def test_a_max_row_takes_the_highest_frame_in_hvos_window(conn, store):
    measured(conn, store, "kilauea-kp", -10, "plume", "top_altitude", 6500, 300)
    measured(conn, store, "kilauea-kp", -5, "plume", "top_altitude", 6951, 429)
    measured(conn, store, "kilauea-kp", 15, "plume", "top_altitude", 9000, 400)  # 05:15: outside the window

    row = height_row(conn, EP55.checks[4], EP55.local)

    assert row == ["plume top (peak)", "04:50-05:10", "kilauea-kp", "25,000 ft a.s.l., 04:50-05:10 (7,620 m)",
                   "6,951 ± 429 m (22,805 ft); max of 2 frames, at 04:55", "-669 m (-9 %)", "-1.6", "yes"]


def test_an_upper_bound_row_agrees_under_the_bound(conn, store):
    measured(conn, store, "kilauea-kp", 150, "plume", "top_altitude", 3800, 100)  # 07:30 HST

    row = height_row(conn, EP55.checks[6], EP55.local)

    assert row[4].startswith("3,800 ± 100 m") and row[5:] == ["within the bound", "-", "yes"]


def test_a_window_without_measurements_has_none(conn):
    assert height_row(conn, EP55.checks[0], EP55.local)[4:] == ["no measurement", "", "", ""]


def test_end_rows_set_the_last_fountain_detection_against_hvos_end(conn, store):
    frames = [add_frame(conn, store, "kilauea-k2", minutes) for minutes in (200, 242)]  # 18:20 and 19:02
    add_track(conn, add_run(conn, "kilauea-k2", "fountain", frames), frames)

    assert end_rows(conn, EP55) == [["kilauea-k2", "09:02:00", "09:03", "-1.0 min"]]


def test_drift_rows_count_the_frames_on_each_side(conn, store):
    for minutes, side in ((-10, 224.4), (-5, 224.4), (0, 230.2)):
        measured(conn, store, "kilauea-kp", minutes, "plume", "drift_bearing", side, 2.1, unit="deg")

    assert drift_rows(conn, EP55) == [["kilauea-kp", "3", "224°: 2, 230°: 1", "224° (-1° from SW)", "yes"]]


def test_table_writes_a_markdown_table():
    assert table(["A", "B"], [["1", "2"]]) == "| A | B |\n|---|---|\n| 1 | 2 |"
```

- [ ] **Step 3: Run them to see them fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_episodes.py -q`
Expected: ModuleNotFoundError (`vigia.episodes`).

- [ ] **Step 4: Implement**

Create `vigia/episodes.py`. The `Check` dataclass, the seven checks and the row functions come from `scripts/validate_ep55.py`. They are unchanged except that they take the episode and its time zone instead of module constants.

```python
"""Past eruptive episodes the replay can run, and the official values to compare its results with.

Episode 55 of Kīlauea's summit eruption, on 2026-10-17. The official values and their sources are in
docs/research/episode55.md; they are compared with, never fitted. scripts/validate_ep55.py writes
docs/VALIDATION.md from these rows, and vigia.replay compares a replay with them.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import numpy as np

from vigia.timeutil import parse_utc, to_iso

FT = 0.3048
HST = timezone(timedelta(hours=-10))
HEIGHT_HEADER = ["Quantity", "Window (HST)", "Camera", "Official", "Ours", "Error", "z", "Agrees"]
END_HEADER = ["Camera", "Last fountain detection (HST)", "Official end (HST)", "Difference"]
DRIFT_HEADER = ["Camera", "Frames", "Across-track side (frames)", "Most frames", "Consistent with SW"]


@dataclass(frozen=True)
class Check:
    quantity: str
    camera_id: str
    target: str
    metric: str          # top_height: above the vent; top_altitude: above sea level
    start: str           # UTC window of our frames, inclusive
    end: str
    aggregate: str       # max: our highest frame in the window; mean: the window's average
    official_m: float
    official: str        # as HVO stated it
    source: str
    upper_bound: bool = False  # HVO said "under" this value


@dataclass(frozen=True)
class Episode:
    key: str
    volcano: str
    cameras: tuple[str, ...]  # the cameras the replay feeds, in the order the rows list them
    start: datetime           # UTC span of the stored frames
    end: datetime
    local: timezone           # the volcano's local time, for the rows
    timelapse_camera: str     # a fixed camera that shows the whole episode, for Muse Spark's reading of it
    checks: tuple[Check, ...]
    phases: dict[str, tuple[datetime, datetime]]  # onset, peak, decline, end: earliest and latest official UTC time
    drift_deg: float          # the official drift direction (towards)
    drift_name: str           # how the official source names it


EP55 = Episode(
    key="55", volcano="kilauea", cameras=("kilauea-kp", "kilauea-k2", "kilauea-v1"),
    start=parse_utc("2026-10-17T13:00:00Z"), end=parse_utc("2026-10-17T19:30:00Z"), local=HST,
    timelapse_camera="kilauea-k2",
    checks=(
        Check("fountain height (peak)", "kilauea-k2", "fountain", "top_height", "2026-10-17T14:50:00Z",
              "2026-10-17T15:10:59Z", "max", 720 * FT, "720 ft, 04:50-05:10", "HVO Daily Update, Oct 17"),
        Check("fountain height", "kilauea-k2", "fountain", "top_height", "2026-10-17T15:57:00Z",
              "2026-10-17T16:07:59Z", "mean", 650 * FT, "about 650 ft at 06:02", "HVO message 06:02 HST"),
        Check("fountain height", "kilauea-k2", "fountain", "top_height", "2026-10-17T16:55:00Z",
              "2026-10-17T17:05:59Z", "mean", 500 * FT, "500 ft by 07:00", "HVO Daily Update, Oct 17"),
        Check("fountain height", "kilauea-k2", "fountain", "top_height", "2026-10-17T17:55:00Z",
              "2026-10-17T18:05:59Z", "mean", 300 * FT, "about 300 ft by 08:00", "HVO Daily Update, Oct 17"),
        Check("plume top (peak)", "kilauea-kp", "plume", "top_altitude", "2026-10-17T14:50:00Z",
              "2026-10-17T15:10:59Z", "max", 25000 * FT, "25,000 ft a.s.l., 04:50-05:10",
              "VONA 2026/67 (webcam); HVO Daily Update"),
        Check("plume top", "kilauea-kp", "plume", "top_altitude", "2026-10-17T15:57:00Z", "2026-10-17T16:07:59Z",
              "mean", 17000 * FT, "17,000 ft a.s.l. at 06:02", "HVO message 06:02 HST"),
        Check("plume top", "kilauea-kp", "plume", "top_altitude", "2026-10-17T17:25:00Z", "2026-10-17T17:35:59Z",
              "mean", 13000 * FT, "under 13,000 ft a.s.l. by 07:30", "HVO Daily Update, Oct 17", upper_bound=True),
    ),
    phases={
        "onset": (parse_utc("2026-10-17T13:19:00Z"),) * 2,     # 3:19 a.m. HST
        "peak": (parse_utc("2026-10-17T14:50:00Z"), parse_utc("2026-10-17T15:10:00Z")),  # 720 ft, 04:50-05:10
        "decline": (parse_utc("2026-10-17T15:10:00Z"), parse_utc("2026-10-17T16:02:00Z")),  # 650 ft by 06:02
        "end": (parse_utc("2026-10-17T19:03:00Z"),) * 2,       # 9:03 a.m. HST, VAN 2026/H489 (the table: 9:06)
    },
    drift_deg=225.0,  # "MOV: SW" (VONA 2026/67), winds from the NE below 20,000 ft
    drift_name="SW",
)
EPISODES = {EP55.key: EP55}


def local_time(utc: str, tz: timezone, seconds: bool = False) -> str:
    return parse_utc(utc).astimezone(tz).strftime("%H:%M:%S" if seconds else "%H:%M")


def table(header: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    return "\n".join(lines + ["| " + " | ".join(row) + " |" for row in rows])


def per_frame(conn: sqlite3.Connection, check: Check) -> list[tuple[str, float, float]]:
    """(capture time, value, sigma) per frame in the window: the highest detection on each frame."""
    found = conn.execute(
        """SELECT captured_at, value, sigma FROM measurements
           WHERE camera_id = ? AND target = ? AND metric = ? AND captured_at BETWEEN ? AND ?
           ORDER BY captured_at, value DESC""",
        (check.camera_id, check.target, check.metric, check.start, check.end)).fetchall()
    best = {}
    for captured_at, value, sigma in found:
        best.setdefault(captured_at, (captured_at, value, sigma))
    return list(best.values())


def height_row(conn: sqlite3.Connection, check: Check, tz: timezone) -> list[str]:
    frames = per_frame(conn, check)
    window = f"{local_time(check.start, tz)}-{local_time(check.end, tz)}"
    official = f"{check.official} ({check.official_m:,.0f} m)"
    if not frames:
        return [check.quantity, window, check.camera_id, official, "no measurement", "", "", ""]
    values = np.array([f[1] for f in frames])
    sigmas = np.array([f[2] for f in frames])
    if check.aggregate == "max":
        i = int(values.argmax())
        value, sigma, how = values[i], sigmas[i], f"max of {len(frames)} frames, at {local_time(frames[i][0], tz)}"
    else:
        value, sigma = values.mean(), float(np.sqrt((sigmas ** 2).mean()))
        how = f"mean of {len(frames)} frames (spread {values.std():.0f} m)"
    error = value - check.official_m
    if check.upper_bound:
        verdict = "yes" if value - 2 * sigma <= check.official_m else "no"
        error_text = "within the bound" if value <= check.official_m else f"{error:+,.0f} m above it"
        z_text = f"{error / sigma:+.1f}" if value > check.official_m else "-"
    else:
        verdict = "yes" if abs(error) <= 2 * sigma else "no"
        error_text = f"{error:+,.0f} m ({100 * error / check.official_m:+.0f} %)"
        z_text = f"{error / sigma:+.1f}"
    ours = f"{value:,.0f} ± {sigma:,.0f} m ({value / FT:,.0f} ft); {how}"
    return [check.quantity, window, check.camera_id, official, ours, error_text, z_text, verdict]


def end_rows(conn: sqlite3.Connection, episode: Episode) -> list[list[str]]:
    official = episode.phases["end"][0]
    rows = []
    for camera_id, last in conn.execute(
            """SELECT r.camera_id, MAX(t.last_seen) FROM tracks t JOIN tracking_runs r ON r.id = t.run_id
               WHERE r.target = 'fountain' AND r.window_start >= ? AND r.window_end <= ?
               GROUP BY r.camera_id ORDER BY r.camera_id""", (to_iso(episode.start), to_iso(episode.end))):
        if last is None:
            continue
        minutes = (parse_utc(last) - official).total_seconds() / 60
        rows.append([camera_id, local_time(last, episode.local, seconds=True),
                     local_time(to_iso(official), episode.local), f"{minutes:+.1f} min"])
    return rows


def drift_rows(conn: sqlite3.Connection, episode: Episode) -> list[list[str]]:
    rows = []
    for camera_id in episode.cameras:
        bearings = np.array([value for (value,) in conn.execute(
            """SELECT value FROM measurements WHERE camera_id = ? AND metric = 'drift_bearing'
               AND captured_at BETWEEN ? AND ?""", (camera_id, to_iso(episode.start), to_iso(episode.end)))])
        if not bearings.size:
            continue
        sides, counts = np.unique(np.round(bearings).astype(int), return_counts=True)
        main_side = int(sides[counts.argmax()])
        off = (main_side - episode.drift_deg + 180) % 360 - 180
        share = ", ".join(f"{side}°: {count}" for side, count in zip(sides, counts))
        rows.append([camera_id, str(bearings.size), share, f"{main_side}° ({off:+.0f}° from {episode.drift_name})",
                     "yes" if abs(off) <= 90 else "no"])
    return rows
```

In `scripts/validate_ep55.py`:
- delete `FT`, `HST`, `EPISODE`, `OFFICIAL_END`, `OFFICIAL_DRIFT_DEG`, `Check`, `CHECKS`, `per_frame`, `height_row`, `end_rows`, `drift_rows`, `hst` and `table`, and import them from the package:

```python
from vigia.episodes import (DRIFT_HEADER, END_HEADER, EP55, HEIGHT_HEADER, drift_rows, end_rows, height_row,
                            local_time, table)
```

- in `main`, build the rows with:

```python
    rows = [height_row(conn, check, EP55.local) for check in EP55.checks]
    ends = end_rows(conn, EP55)
    drifts = drift_rows(conn, EP55)
```

- in `wind_rows`, loop over `EP55.cameras` and pass `(camera_id, to_iso(EP55.start), to_iso(EP55.end))` to the query;
- in `report`, use the three headers: `table(HEIGHT_HEADER, rows)`, `table(END_HEADER, ends)`, `table(DRIFT_HEADER, drifts)`;
- import `to_iso` next to `parse_utc` and `utcnow`, and drop the imports nothing uses any more (`dataclass`, `timedelta`, `timezone`).

The docstring stays as it is.

- [ ] **Step 5: Run the tests and check the script's output**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: all pass.

Run: `.venv\Scripts\python.exe scripts\validate_ep55.py` then `git diff docs/VALIDATION.md`.
Expected: only the "Generated by ... on <date>" line differs. Run `git checkout docs/VALIDATION.md` and do not commit it.

- [ ] **Step 6: Commit**

```bash
git add vigia/episodes.py scripts/validate_ep55.py tests/test_episodes.py
git commit -m "Move episode 55's official values and comparison rows into the package for the replay"
```

---

### Task 8: The pipeline and `vigia-pipeline`

**Files:**
- Create: `vigia/pipeline.py`
- Modify: `pyproject.toml`
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pipeline.py`:

```python
from datetime import datetime, timedelta, timezone

import pytest

from test_agent_loop import SOURCES_YAML
from test_agent_tools import T0, add_frame, add_run, context, store  # store is a fixture
from vigia import tracking
from vigia.agent.bulletin import Written
from vigia.agent.loop import AgentRun
from vigia.meta.ledger import BudgetExceeded
from vigia.metrics import MeasureReport
from vigia.pipeline import Pipeline, PipelineConfig, floor_time, main
from vigia.timeutil import to_iso
from vigia.tracking import RunSummary, TrackingReport

START = T0 - timedelta(hours=2)  # 13:00Z: the pipeline starts here
H = timedelta(hours=1)
M = timedelta(minutes=1)


class Fakes:
    """Tracking, measuring and the agent, recording their calls and storing the rows the pipeline looks for."""

    def __init__(self):
        self.tracked, self.measured, self.agent_clocks = [], [], []
        self.budget_spent = False

    def track(self, client, conn, data_dir, camera, prompts, start, end):
        if self.budget_spent:
            raise BudgetExceeded("daily budget $5.00 would be exceeded")
        self.tracked.append((camera.id, start, end))
        frame_ids = [frame.id for frame in tracking.usable_frames(conn, data_dir, camera.id, start, end)]
        run_id = add_run(conn, camera.id, "plume", frame_ids)
        return TrackingReport(camera.id, len(frame_ids),
                              runs=[RunSummary(run_id, "plume", "steam", 1, len(frame_ids), start, end)])

    def measure(self, conn, calibration, camera_id, start, end):
        self.measured.append((camera_id, start, end))
        return MeasureReport(camera_id, measured=2)

    def write(self, client, ctx, volcano_id, out_dir, **agent):
        self.agent_clocks.append(ctx.now)
        with ctx.conn:
            run_id = ctx.conn.execute(
                "INSERT INTO agent_runs (started_at, clock, volcano, task, model, status) "
                "VALUES ('2026-10-28T00:00:00Z', ?, ?, 'task', 'muse-spark-1.3', 'done')",
                (to_iso(ctx.now), volcano_id)).lastrowid
        return Written(AgentRun(run_id, "done", 1, 0.0, "{}", None), None, "no bulletin in this test")


@pytest.fixture
def fakes():
    return Fakes()


def pipeline(conn, tmp_path, fakes, *, client="a Meta client", **config):
    base = context(conn, tmp_path, client=client, now=START)
    config = {"volcano": "kilauea", "cameras": ("kilauea-kp", "kilauea-k2"), "bulletin_dir": tmp_path / "bulletins",
              **config}
    return Pipeline(base, PipelineConfig(**config), track=fakes.track, measure=fakes.measure, write=fakes.write)


def frames(conn, store, camera_id, hour, count=6, every=10, usable=True):
    """`count` frames of the camera, `every` minutes apart from `hour` hours after the pipeline's start."""
    first = int((START - T0) / M) + 60 * hour
    return [add_frame(conn, store, camera_id, first + every * i, usable=usable) for i in range(count)]


def test_a_step_gives_every_recent_frame_without_a_verdict_one(conn, store, tmp_path, fakes):
    frames(conn, store, "kilauea-kp", 1, count=2, usable=None)

    report = pipeline(conn, tmp_path, fakes, client=None).step(START + 2 * H)

    assert report.assessed == 2
    assert conn.execute("SELECT COUNT(*) FROM frame_quality").fetchone()[0] == 2
    assert fakes.tracked == [] and fakes.agent_clocks == []  # without a client nothing calls SAM or Muse Spark


def test_each_closed_hour_is_tracked_once_per_camera(conn, store, tmp_path, fakes):
    frames(conn, store, "kilauea-kp", 0)
    frames(conn, store, "kilauea-k2", 0)
    runner = pipeline(conn, tmp_path, fakes)

    report = runner.step(START + H + 5 * M)
    runner.step(START + H + 10 * M)

    end = START + H - timedelta(seconds=1)
    assert fakes.tracked == [("kilauea-kp", START, end), ("kilauea-k2", START, end)]
    assert [(w["camera_id"], w["start"], w["end"]) for w in report.tracked] == [
        ("kilauea-kp", to_iso(START), to_iso(end)), ("kilauea-k2", to_iso(START), to_iso(end))]
    assert report.tracked[0]["runs"][0]["detections"] == 6


def test_a_window_waits_until_it_has_settled(conn, store, tmp_path, fakes):
    frames(conn, store, "kilauea-kp", 0)
    runner = pipeline(conn, tmp_path, fakes)

    runner.step(START + H + 4 * M)
    assert fakes.tracked == []
    runner.step(START + H + 5 * M)
    assert len(fakes.tracked) == 1


def test_flushing_tracks_the_open_window_up_to_the_clock_and_never_past_it(conn, store, tmp_path, fakes):
    frames(conn, store, "kilauea-kp", 0, count=6, every=10)  # 13:00 to 13:50

    pipeline(conn, tmp_path, fakes, settle=timedelta(0), min_frames=3).step(START + 30 * M, flush=True)

    assert fakes.tracked == [("kilauea-kp", START, START + 30 * M)]


def test_a_window_with_too_few_usable_frames_is_not_tracked(conn, store, tmp_path, fakes):
    frames(conn, store, "kilauea-kp", 0, count=4)
    frames(conn, store, "kilauea-k2", 0, count=6, usable=False)

    pipeline(conn, tmp_path, fakes).step(START + 2 * H)

    assert fakes.tracked == []


def test_only_calibrated_cameras_are_measured(conn, store, tmp_path, fakes):
    frames(conn, store, "kilauea-kp", 0)
    frames(conn, store, "kilauea-k2", 0)

    report = pipeline(conn, tmp_path, fakes).step(START + H + 5 * M)

    assert fakes.measured == [("kilauea-kp", START, START + H - timedelta(seconds=1))]  # only KPcam is calibrated
    assert report.measured == 2


def test_the_agent_writes_at_each_full_hour_after_the_start(conn, tmp_path, fakes):
    runner = pipeline(conn, tmp_path, fakes)

    reports = [runner.step(START + minutes * M) for minutes in (30, 60, 65, 120)]

    assert fakes.agent_clocks == [START + H, START + 2 * H]
    assert reports[1].agent_run_id == 1 and reports[1].bulletin_id is None
    assert reports[1].errors == ["agent run 1: no bulletin in this test"]


def test_a_forced_agent_runs_once_per_clock_and_can_be_held_back(conn, tmp_path, fakes):
    runner = pipeline(conn, tmp_path, fakes)

    runner.step(START + 30 * M, agent=True)
    runner.step(START + 30 * M, agent=True)
    runner.step(START + H, agent=False)

    assert fakes.agent_clocks == [START + 30 * M]


def test_without_an_agent_schedule_no_agent_runs(conn, tmp_path, fakes):
    pipeline(conn, tmp_path, fakes, agent_every=None).step(START + 2 * H)

    assert fakes.agent_clocks == []


def test_a_spent_budget_stops_tracking_and_is_reported(conn, store, tmp_path, fakes):
    frames(conn, store, "kilauea-kp", 0)
    fakes.budget_spent = True

    report = pipeline(conn, tmp_path, fakes).step(START + H + 5 * M)

    assert fakes.tracked == [] and any("daily budget" in error for error in report.errors)


def test_floor_time_counts_from_the_unix_epoch():
    assert floor_time(datetime(2026, 10, 17, 14, 37, tzinfo=timezone.utc), H) == datetime(
        2026, 10, 17, 14, tzinfo=timezone.utc)


def test_a_report_reads_as_one_line_per_step(conn, store, tmp_path, fakes):
    frames(conn, store, "kilauea-kp", 0)

    report = pipeline(conn, tmp_path, fakes).step(START + H + 5 * M)

    assert report.as_json()["clock"] == to_iso(START + H + 5 * M)
    assert report.summary().startswith("2026-10-17T14:05:00Z: 0 frames assessed (0 usable); tracked kilauea-kp "
                                       "13:00-13:59 (6 detections); 2 detections measured")


@pytest.fixture
def cli_env(monkeypatch, tmp_path):
    sources = tmp_path / "sources.yaml"
    sources.write_text(SOURCES_YAML, encoding="utf-8")
    monkeypatch.setenv("SOURCES_PATH", str(sources))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "data" / "vigia.sqlite"))


@pytest.mark.parametrize("argv, message", [(["--volcano", "etna"], "etna"),
                                           (["--volcano", "kilauea"], "no enabled camera"),
                                           (["--volcano", "kilauea", "--interval", "0"], "--interval")])
def test_cli_refuses_what_it_cannot_run(cli_env, capsys, argv, message):
    with pytest.raises(SystemExit):
        main(argv)

    assert message in capsys.readouterr().err
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_pipeline.py -q`
Expected: ModuleNotFoundError (`vigia.pipeline`).

- [ ] **Step 3: Implement**

Create `vigia/pipeline.py`:

```python
"""The pipeline a live deployment runs every few minutes, and the replay runs on its simulated clock.

One step at time `now`, for one volcano's cameras:
1. the quality gate gives a verdict to every frame of the last hours that has none (local checks, and Muse
   Spark for the uncertain ones when there is a client);
2. every closed window (one per camera per hour, the Phase 2 cost rule) with enough usable frames and no
   tracking run yet is tracked with SAM 3.1 video, and a calibrated camera's new detections are measured;
3. at each full `agent_every` after the pipeline started, the agent writes a bulletin.
A window counts as closed once `settle` has passed after its end, so that late frames are in; the replay, whose
frames are all on time, settles for nothing. Nothing in a step looks past `now`. Tracking and measuring take
minutes (mask decoding), so a server runs the steps in a background thread, never in a request.

    vigia-pipeline --volcano kilauea
"""

from __future__ import annotations

import argparse
import dataclasses
import logging
import sys
import time
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import openai

from vigia import db, tracking
from vigia.agent.bulletin import write_bulletin
from vigia.agent.loop import BUDGET_USD, context_from_settings
from vigia.agent.tools import ToolContext
from vigia.config import load_sources
from vigia.gate import QualityGate, SparkMode
from vigia.meta.client import MetaClient
from vigia.meta.ledger import BudgetExceeded, CostLedger
from vigia.metrics import measure_window
from vigia.settings import Settings
from vigia.timeutil import to_iso, utcnow

log = logging.getLogger(__name__)

TRACK_WINDOW = timedelta(hours=1)
LOOKBACK = timedelta(hours=3)
SETTLE = timedelta(minutes=5)
MIN_WINDOW_FRAMES = 5
AGENT_EVERY = timedelta(hours=1)
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


@dataclass(frozen=True)
class PipelineConfig:
    volcano: str
    cameras: tuple[str, ...]
    bulletin_dir: Path                   # inside the data dir
    window: timedelta = TRACK_WINDOW
    lookback: timedelta = LOOKBACK       # how far back frames are assessed and windows tracked
    settle: timedelta = SETTLE
    min_frames: int = MIN_WINDOW_FRAMES  # fewer usable frames in a window: not worth a SAM request
    spark: SparkMode = "uncertain"
    agent_every: timedelta | None = AGENT_EVERY
    agent_budget_usd: float = BUDGET_USD


@dataclass
class StepReport:
    clock: datetime
    assessed: int = 0
    usable: int = 0
    tracked: list[dict[str, Any]] = field(default_factory=list)  # per window: camera, start, end, frames, runs
    measured: int = 0
    agent_run_id: int | None = None
    bulletin_id: int | None = None
    errors: list[str] = field(default_factory=list)

    def as_json(self) -> dict[str, Any]:
        return {"clock": to_iso(self.clock), "assessed": self.assessed, "usable": self.usable,
                "tracked": self.tracked, "measured": self.measured, "agent_run_id": self.agent_run_id,
                "bulletin_id": self.bulletin_id, "errors": self.errors}

    def summary(self) -> str:
        parts = [f"{to_iso(self.clock)}: {self.assessed} frames assessed ({self.usable} usable)"]
        parts += [f"tracked {w['camera_id']} {w['start'][11:16]}-{w['end'][11:16]} "
                  f"({sum(run['detections'] for run in w['runs'])} detections)" for w in self.tracked]
        if self.measured:
            parts.append(f"{self.measured} detections measured")
        if self.bulletin_id is not None:
            parts.append(f"bulletin {self.bulletin_id} (agent run {self.agent_run_id})")
        elif self.agent_run_id is not None:
            parts.append(f"agent run {self.agent_run_id}, no bulletin")
        return "; ".join(parts) + "".join(f"\n  failed: {error}" for error in self.errors)


def floor_time(when: datetime, every: timedelta) -> datetime:
    """The latest whole multiple of `every` since the Unix epoch at or before `when`."""
    return _EPOCH + (when - _EPOCH) // every * every


class Pipeline:
    """Quality, tracking, measuring and bulletins for one volcano; `base.now` is when the pipeline started."""

    def __init__(self, base: ToolContext, config: PipelineConfig, *, track: Callable = tracking.track_window,
                 measure: Callable = measure_window, write: Callable = write_bulletin):
        self.base, self.config = base, config
        self.started_at = base.now
        self._cameras = [base.camera(camera_id) for camera_id in config.cameras]
        self._track, self._measure, self._write = track, measure, write

    def step(self, now: datetime, *, flush: bool = False, agent: bool | None = None) -> StepReport:
        """One step at `now`. `flush` also tracks the open window up to now (the end of a replay). `agent`: None
        runs the agent when a full `agent_every` has come; True runs it unless a run at this very clock exists;
        False holds it back."""
        ctx = dataclasses.replace(self.base, now=now)
        report = StepReport(now)
        self._assess(ctx, report)
        if ctx.client is None:
            return report
        self._track_windows(ctx, report, flush)
        due = self._agent_due(now) if agent is None else agent and not self._ran_at(now)
        if due:
            self._run_agent(ctx, report)
        return report

    def _assess(self, ctx: ToolContext, report: StepReport) -> None:
        gate = QualityGate(ctx.conn, ctx.data_dir, ctx.sources, ctx.client)
        spark = self.config.spark if ctx.client is not None else "never"
        try:
            for camera in self._cameras:
                result = gate.assess_range(camera.id, ctx.now - self.config.lookback, ctx.now, spark=spark)
                report.assessed += len(result.verdicts)
                report.usable += sum(verdict.usable for verdict in result.verdicts)
                report.errors += result.errors
        except BudgetExceeded as exc:
            report.errors.append(f"quality gate stopped: {exc}")

    def _windows(self, now: datetime, flush: bool) -> list[tuple[datetime, datetime]]:
        """[start, end] of the closed windows in the lookback, and of the open one up to now when flushing."""
        every = self.config.window
        start = floor_time(max(now - self.config.lookback, self.started_at), every)
        windows = []
        while start + every + self.config.settle <= now:
            windows.append((start, start + every - timedelta(seconds=1)))
            start += every
        if flush and start < now:
            windows.append((start, now))
        return windows

    def _tracked(self, camera_id: str, start: datetime) -> bool:
        return self.base.conn.execute(
            "SELECT 1 FROM tracking_runs WHERE camera_id = ? AND window_start >= ? AND window_end < ? LIMIT 1",
            (camera_id, to_iso(start), to_iso(start + self.config.window))).fetchone() is not None

    def _track_windows(self, ctx: ToolContext, report: StepReport, flush: bool) -> None:
        for camera in self._cameras:
            for start, end in self._windows(ctx.now, flush):
                if self._tracked(camera.id, start):
                    continue
                if len(tracking.usable_frames(ctx.conn, ctx.data_dir, camera.id, start, end)) < self.config.min_frames:
                    continue
                try:
                    result = self._track(ctx.client, ctx.conn, ctx.data_dir, camera, ctx.prompts, start, end)
                except BudgetExceeded as exc:
                    report.errors.append(f"tracking stopped: {exc}")
                    return
                except (ValueError, openai.APIError) as exc:  # e.g. the upload failed: the next step tries again
                    report.errors.append(f"{camera.id} {to_iso(start)}: {exc}")
                    continue
                report.errors += result.errors
                report.tracked.append({
                    "camera_id": camera.id, "start": to_iso(start), "end": to_iso(end), "frames": result.frames,
                    "runs": [{"run_id": run.run_id, "target": run.target, "phrase": run.phrase, "tracks": run.tracks,
                              "detections": run.detections} for run in result.runs]})
                if camera.id in ctx.calibration.cameras and result.runs:
                    measured = self._measure(ctx.conn, ctx.calibration, camera.id, start, end)
                    report.measured += measured.measured
                    report.errors += measured.errors

    def _agent_due(self, now: datetime) -> bool:
        every = self.config.agent_every
        if every is None:
            return False
        boundary = floor_time(now, every)
        if boundary <= self.started_at:
            return False
        return self.base.conn.execute(
            "SELECT 1 FROM agent_runs WHERE volcano = ? AND clock >= ? AND clock < ? LIMIT 1",
            (self.config.volcano, to_iso(boundary), to_iso(boundary + every))).fetchone() is None

    def _ran_at(self, now: datetime) -> bool:
        return self.base.conn.execute("SELECT 1 FROM agent_runs WHERE volcano = ? AND clock = ? LIMIT 1",
                                      (self.config.volcano, to_iso(now))).fetchone() is not None

    def _run_agent(self, ctx: ToolContext, report: StepReport) -> None:
        written = self._write(ctx.client, ctx, self.config.volcano, self.config.bulletin_dir,
                              budget_usd=self.config.agent_budget_usd)
        report.agent_run_id = written.run.run_id
        if written.bulletin is not None:
            report.bulletin_id = written.bulletin.id
        else:
            report.errors.append(f"agent run {written.run.run_id}: {written.problem}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the pipeline live for one volcano: quality verdicts, hourly "
                                                 "SAM tracking and measuring, and an hourly bulletin. Run "
                                                 "vigia-ingest alongside it.")
    parser.add_argument("--volcano", required=True, help="volcano id from the sources file, e.g. kilauea")
    parser.add_argument("--interval", type=float, default=5, help="minutes between steps (default 5)")
    parser.add_argument("--agent-every", type=float, default=60,
                        help="minutes between bulletins, 0 for none (default 60)")
    parser.add_argument("--once", action="store_true", help="run one step and exit")
    args = parser.parse_args(argv)
    if args.interval <= 0:
        parser.error("--interval must be positive")
    settings = Settings.from_env()
    sources = load_sources(settings.sources_path)
    if args.volcano not in sources.volcanoes:
        parser.error(f"unknown volcano {args.volcano!r} in {settings.sources_path}")
    cameras = tuple(camera.id for camera in sources.enabled_cameras() if camera.volcano == args.volcano)
    if not cameras:
        parser.error(f"{args.volcano} has no enabled camera in {settings.sources_path}")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    with closing(db.connect(settings.db_path)) as conn, \
            httpx.Client(headers={"User-Agent": settings.user_agent}, timeout=30) as http:
        client = MetaClient.from_env(CostLedger(conn, settings.daily_budget_usd))
        config = PipelineConfig(volcano=args.volcano, cameras=cameras, bulletin_dir=settings.data_dir / "bulletins",
                                agent_every=timedelta(minutes=args.agent_every) if args.agent_every > 0 else None)
        pipeline = Pipeline(context_from_settings(settings, conn, http, utcnow(), client, sources), config)
        while True:
            try:
                print(pipeline.step(utcnow()).summary(), flush=True)
            except Exception:
                if args.once:
                    raise
                log.exception("the step failed; the next one tries again")
            if args.once:
                return
            time.sleep(args.interval * 60)
```

In `pyproject.toml`, add under `[project.scripts]`:

```toml
vigia-pipeline = "vigia.pipeline:main"
```

then reinstall: `.venv\Scripts\python.exe -m pip install -e ".[dev]" -q`.

- [ ] **Step 4: Run the tests**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add vigia/pipeline.py pyproject.toml tests/test_pipeline.py
git commit -m "Add the pipeline: quality verdicts, one SAM window per camera per hour, measurements and hourly bulletins"
```

---

### Task 9: The replay and `vigia-replay`

**Files:**
- Create: `vigia/replay.py`
- Modify: `vigia/db.py`, `pyproject.toml`
- Test: `tests/test_replay.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_replay.py`:

```python
import json
from dataclasses import replace
from datetime import timedelta

import pytest

from test_agent_tools import T0, context, frame_jpeg
from test_bulletin import DRAFT
from vigia import db
from vigia.agent.bulletin import BulletinDraft, CitedMeasurement, build_bulletin, store_bulletin
from vigia.episodes import EP55
from vigia.ingest.store import FrameStore
from vigia.pipeline import StepReport
from vigia.replay import activity_rows, bulletin_rows, feed, main, run_replay, ticks
from vigia.timeutil import parse_utc, to_iso

M = timedelta(minutes=1)


@pytest.fixture
def source(tmp_path):
    """The database the episode's frames come from (live: data/vigia.sqlite)."""
    connection = db.connect(tmp_path / "source.sqlite")
    yield connection
    connection.close()


def add(source, tmp_path, camera_id, minutes):
    """A frame in the source database `minutes` from 15:00Z; returns its id."""
    captured_at = T0 + minutes * M
    return FrameStore(source, tmp_path).add(camera_id, frame_jpeg(minutes + 2000), captured_at=captured_at,
                                            timestamp_source="ashcam", fetched_at=captured_at)


class FakePipeline:
    """Records each step, and the newest frame the replay's database held when it ran."""

    def __init__(self, conn):
        self.conn, self.calls = conn, []

    def step(self, now, *, flush=False, agent=None):
        latest = self.conn.execute("SELECT MAX(captured_at) FROM frames").fetchone()[0]
        self.calls.append((now, flush, agent, latest))
        return StepReport(now, assessed=1)


def episode(start, end):
    return replace(EP55, start=start, end=end, cameras=("kilauea-kp",))


def test_ticks_step_to_the_end_and_stop_on_it():
    assert ticks(T0, T0 + 12 * M, 5 * M) == [T0 + 5 * M, T0 + 10 * M, T0 + 12 * M]


def test_feed_copies_the_frames_captured_by_the_clock_with_their_ids(source, conn, tmp_path):
    kp, k2, later, v1 = (add(source, tmp_path, camera, minutes) for camera, minutes in (
        ("kilauea-kp", -10), ("kilauea-k2", -5), ("kilauea-kp", 5), ("kilauea-v1", -5)))
    cameras, start = ("kilauea-kp", "kilauea-k2"), T0 - 60 * M

    assert feed(source, conn, cameras, start, T0) == {"kilauea-kp": 1, "kilauea-k2": 1}
    assert [row[0] for row in conn.execute("SELECT id FROM frames ORDER BY id")] == [kp, k2]
    assert feed(source, conn, cameras, start, T0) == {}
    assert feed(source, conn, cameras, start, T0 + 5 * M) == {"kilauea-kp": 1}


def test_the_replay_steps_the_pipeline_on_the_simulated_clock_and_nothing_after_it_exists(source, conn, tmp_path):
    for minutes in range(-28, 11, 4):  # 14:32 to 15:08
        add(source, tmp_path, "kilauea-kp", minutes)
    fake = FakePipeline(conn)

    timeline = run_replay(source, context(conn, tmp_path), episode(T0 - 30 * M, T0 + 12 * M), tmp_path / "replay",
                          step=10 * M, pipeline=fake)

    clocks = [T0 - 20 * M, T0 - 10 * M, T0, T0 + 10 * M, T0 + 12 * M]
    assert [call[0] for call in fake.calls] == clocks
    assert all(parse_utc(latest) <= now for now, _, _, latest in fake.calls)
    assert [call[1:3] for call in fake.calls] == [(False, None)] * 4 + [(True, True)]
    assert [tick["clock"] for tick in timeline["ticks"]] == [to_iso(clock) for clock in clocks]
    assert timeline["ticks"][0]["new_frames"] == {"kilauea-kp": 3}
    assert json.loads((tmp_path / "replay" / "timeline.json").read_text(encoding="utf-8")) == timeline
    assert (tmp_path / "replay" / "report.md").read_text(encoding="utf-8").startswith("# Replay of episode 55")


def test_an_interrupted_replay_resumes_after_its_last_stored_tick(source, conn, tmp_path):
    with conn:
        for clock in (T0 - 20 * M, T0 - 10 * M):
            conn.execute("INSERT INTO replay_ticks (clock, report) VALUES (?, ?)",
                         (to_iso(clock), json.dumps({"clock": to_iso(clock)})))
    fake = FakePipeline(conn)

    timeline = run_replay(source, context(conn, tmp_path), episode(T0 - 30 * M, T0 + 12 * M), tmp_path / "replay",
                          step=10 * M, pipeline=fake)

    assert [call[0] for call in fake.calls] == [T0, T0 + 10 * M, T0 + 12 * M]
    assert len(timeline["ticks"]) == 5


def test_speed_keeps_the_simulated_clock_at_most_that_many_times_faster_than_the_wall(source, conn, tmp_path):
    wall, slept = [0.0], []

    def sleep(seconds):
        slept.append(round(seconds, 6))
        wall[0] += seconds

    run_replay(source, context(conn, tmp_path), episode(T0, T0 + 30 * M), tmp_path / "replay", step=10 * M,
               speed=60, pipeline=FakePipeline(conn), sleep=sleep, monotonic=lambda: wall[0])

    assert slept == [10.0, 10.0]  # 10 simulated minutes at 60x: 10 s; the first step sets the origin


def bulletin_at(conn, tmp_path, clock, level="fountaining", measurements=()):
    draft = BulletinDraft.model_validate({**DRAFT, "activity_level": level, "measurements": [], "evidence": []})
    bulletin = build_bulletin(context(conn, tmp_path), "kilauea", 1, draft, tmp_path / "bulletins")
    return store_bulletin(conn, bulletin.model_copy(update={"clock": clock, "measurements": list(measurements)}))


def top(value, sigma, captured_at):
    return CitedMeasurement(camera_id="kilauea-kp", target="plume", metric="top_altitude", value=value, sigma=sigma,
                            unit="m", frame_ids=[29], verified=True, captured_at=captured_at)


def test_each_official_height_meets_the_first_bulletin_once_its_window_opens(conn, tmp_path):
    bulletin_at(conn, tmp_path, "2026-10-17T14:00:00Z", measurements=[top(5000, 300, "2026-10-17T13:55:05Z")])
    bulletin_at(conn, tmp_path, "2026-10-17T15:00:00Z", measurements=[top(6500, 350, "2026-10-17T14:45:05Z"),
                                                                     top(6951, 429, "2026-10-17T14:55:05Z")])
    bulletin_at(conn, tmp_path, "2026-10-17T16:00:00Z")

    rows = bulletin_rows(conn, EP55)

    assert rows[4] == ["plume top (peak)", "25,000 ft a.s.l., 04:50-05:10 (7,620 m)", "#2 at 05:00",
                       "6,951 ± 429 m at 04:55", "-669 m (-9 %)", "yes"]
    assert rows[0][2:4] == ["#2 at 05:00", "not quoted"]  # no bulletin quotes a fountain height
    assert rows[5][2:4] == ["#3 at 06:00", "not quoted"]
    assert rows[6][2:] == ["none", "", "", ""]  # no bulletin after 07:25


def test_activity_rows_say_when_fountaining_was_first_and_no_longer_reported(conn, tmp_path):
    for clock, level in (("2026-10-17T13:00:00Z", "degassing"), ("2026-10-17T14:00:00Z", "fountaining"),
                         ("2026-10-17T19:00:00Z", "fountaining"), ("2026-10-17T19:30:00Z", "degassing")):
        bulletin_at(conn, tmp_path, clock, level)

    assert activity_rows(conn, EP55) == [["fountaining first reported", "04:00", "03:19", "+41 min"],
                                         ["fountaining no longer reported", "09:30", "09:03", "+27 min"]]


def test_activity_rows_without_bulletins_say_never(conn):
    assert [row[1] for row in activity_rows(conn, EP55)] == ["never", "never"]


def test_cli_knows_only_the_stored_episodes(capsys):
    with pytest.raises(SystemExit):
        main(["--episode", "54"])

    assert "invalid choice" in capsys.readouterr().err
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_replay.py -q`
Expected: ModuleNotFoundError (`vigia.replay`).

- [ ] **Step 3: Implement**

In `vigia/db.py`, append to `SCHEMA`:

```sql
CREATE TABLE IF NOT EXISTS replay_ticks (    -- one step of a replay's simulated clock (vigia.replay)
    clock  TEXT PRIMARY KEY,  -- UTC simulated time
    report TEXT NOT NULL      -- JSON: the pipeline's step report plus the frames fed
);
```

Create `vigia/replay.py`:

```python
"""Replay a past episode through the live pipeline on a simulated clock, and set what it says against the record.

The replay has its own database, data/replay/ep<key>/vigia.sqlite. Every `step` of simulated time it copies
into it the episode's frames captured by then, as live ingest would have, and runs one pipeline step at that
time (vigia.pipeline): quality verdicts, one SAM window per camera per closed hour with its measurements, and
the agent's bulletin at every full hour and once more at the end. Nothing captured after the simulated clock
exists for any of them. Each step's report goes to replay_ticks, so an interrupted replay resumes where it
stopped. With --speed S the simulated clock runs at most S times faster than the wall clock (it cannot run
faster than tracking does).

At the end it writes timeline.json (the steps, the bulletins and the comparisons with the official values) and
report.md next to the database. Its Meta spend goes to that database's ledger.

    vigia-replay --episode 55 --speed 60
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import sqlite3
import sys
import time
from collections import Counter
from collections.abc import Callable
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from vigia import db
from vigia.agent.bulletin import Bulletin
from vigia.agent.loop import context_from_settings
from vigia.agent.tools import ToolContext
from vigia.episodes import (DRIFT_HEADER, END_HEADER, EPISODES, HEIGHT_HEADER, Episode, drift_rows, end_rows,
                            height_row, local_time, table)
from vigia.meta.client import MetaClient
from vigia.meta.ledger import CostLedger
from vigia.pipeline import AGENT_EVERY, Pipeline, PipelineConfig
from vigia.settings import Settings
from vigia.timeutil import parse_utc, to_iso

log = logging.getLogger(__name__)

STEP = timedelta(minutes=5)
FRAME_COLUMNS = ("id", "camera_id", "captured_at", "timestamp_source", "fetched_at", "sha256", "path", "bytes",
                 "width", "height")
BULLETIN_HEADER = ["Quantity", "Official", "Bulletin (local)", "It quoted", "Error", "Checked"]
ACTIVITY_HEADER = ["Event", "Bulletins (local)", "Official (local)", "Difference"]


def ticks(start: datetime, end: datetime, step: timedelta) -> list[datetime]:
    """The simulated clock's steps: every `step` after start, and the end itself."""
    out, tick = [], start + step
    while tick < end:
        out.append(tick)
        tick += step
    return out + [end]


def feed(source: sqlite3.Connection, conn: sqlite3.Connection, cameras: tuple[str, ...], start: datetime,
         clock: datetime) -> dict[str, int]:
    """Copy the cameras' frames captured from start to clock that the replay lacks, keeping their ids; returns the
    new frames per camera."""
    marks = ",".join("?" * len(cameras))
    rows = source.execute(
        f"""SELECT {', '.join(FRAME_COLUMNS)} FROM frames WHERE camera_id IN ({marks})
            AND captured_at BETWEEN ? AND ? ORDER BY captured_at, id""",
        (*cameras, to_iso(start), to_iso(clock))).fetchall()
    new: Counter[str] = Counter()
    with conn:
        for row in rows:
            inserted = conn.execute(
                f"INSERT OR IGNORE INTO frames ({', '.join(FRAME_COLUMNS)}) "
                f"VALUES ({', '.join('?' * len(FRAME_COLUMNS))})", tuple(row)).rowcount
            new[row["camera_id"]] += inserted
    return {camera: count for camera, count in new.items() if count}


def run_replay(source: sqlite3.Connection, base: ToolContext, episode: Episode, out_dir: Path, *,
               step: timedelta = STEP, agent_every: timedelta | None = AGENT_EVERY, speed: float = 0.0,
               pipeline: Pipeline | None = None, sleep: Callable[[float], None] = time.sleep,
               monotonic: Callable[[], float] = time.monotonic) -> dict[str, Any]:
    """Replay the episode into base.conn, the replay's own database, and write timeline.json and report.md to
    out_dir (inside the data dir); returns the timeline."""
    conn = base.conn
    if pipeline is None:
        config = PipelineConfig(volcano=episode.volcano, cameras=episode.cameras, bulletin_dir=out_dir / "bulletins",
                                settle=timedelta(0), agent_every=agent_every)
        pipeline = Pipeline(dataclasses.replace(base, now=episode.start), config)
    done = {row[0] for row in conn.execute("SELECT clock FROM replay_ticks")}
    origin: tuple[datetime, float] | None = None
    for tick in ticks(episode.start, episode.end, step):
        if to_iso(tick) in done:
            continue
        if speed > 0:
            if origin is None:
                origin = (tick, monotonic())
            wait = (tick - origin[0]).total_seconds() / speed - (monotonic() - origin[1])
            if wait > 0:
                sleep(wait)
        new = feed(source, conn, episode.cameras, episode.start, tick)
        last = tick == episode.end
        report = pipeline.step(tick, flush=last, agent=True if last and agent_every else None)
        with conn:
            conn.execute("INSERT INTO replay_ticks (clock, report) VALUES (?, ?)",
                         (to_iso(tick), json.dumps({**report.as_json(), "new_frames": new})))
        log.info("%s", report.summary())
    timeline = build_timeline(conn, episode, step, agent_every)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "timeline.json").write_text(json.dumps(timeline, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "report.md").write_text(report_markdown(timeline, episode), encoding="utf-8")
    return timeline


def bulletin_rows(conn: sqlite3.Connection, episode: Episode) -> list[list[str]]:
    """Each official height against the first bulletin written once its window opened: the value of that target
    and metric it quoted nearest the window's middle."""
    rows = []
    for check in episode.checks:
        official = f"{check.official} ({check.official_m:,.0f} m)"
        row = conn.execute("SELECT body FROM bulletins WHERE volcano = ? AND clock >= ? ORDER BY clock, id LIMIT 1",
                           (episode.volcano, check.start)).fetchone()
        if row is None:
            rows.append([check.quantity, official, "none", "", "", ""])
            continue
        bulletin = Bulletin.model_validate_json(row["body"])
        written = f"#{bulletin.id} at {local_time(bulletin.clock, episode.local)}"
        quoted = [m for m in bulletin.measurements if (m.target, m.metric) == (check.target, check.metric)]
        if not quoted:
            rows.append([check.quantity, official, written, "not quoted", "", ""])
            continue
        middle = parse_utc(check.start) + (parse_utc(check.end) - parse_utc(check.start)) / 2
        m = min(quoted, key=lambda q: abs(parse_utc(q.captured_at) - middle) if q.captured_at else timedelta.max)
        error = m.value - check.official_m
        if check.upper_bound:
            error_text = "within the bound" if m.value <= check.official_m else f"{error:+,.0f} m above it"
        else:
            error_text = f"{error:+,.0f} m ({100 * error / check.official_m:+.0f} %)"
        at = f" at {local_time(m.captured_at, episode.local)}" if m.captured_at else ""
        rows.append([check.quantity, official, written, f"{m.value:,.0f} ± {m.sigma:,.0f} m{at}", error_text,
                     "yes" if m.verified else "no"])
    return rows


def activity_rows(conn: sqlite3.Connection, episode: Episode) -> list[list[str]]:
    """When the bulletins first reported fountaining, and first stopped reporting it, against the official onset
    and end."""
    levels = conn.execute("SELECT clock, activity_level FROM bulletins WHERE volcano = ? ORDER BY clock, id",
                          (episode.volcano,)).fetchall()
    first = next((row["clock"] for row in levels if row["activity_level"] == "fountaining"), None)
    stopped = None if first is None else next(
        (row["clock"] for row in levels if row["clock"] > first and row["activity_level"] != "fountaining"), None)
    rows = []
    for event, clock, official in (("fountaining first reported", first, episode.phases["onset"][0]),
                                   ("fountaining no longer reported", stopped, episode.phases["end"][0])):
        when = local_time(to_iso(official), episode.local)
        if clock is None:
            rows.append([event, "never", when, ""])
        else:
            minutes = (parse_utc(clock) - official) / timedelta(minutes=1)
            rows.append([event, local_time(clock, episode.local), when, f"{minutes:+.0f} min"])
    return rows


def build_timeline(conn: sqlite3.Connection, episode: Episode, step: timedelta, agent_every: timedelta | None,
                   phases: dict[str, Any] | None = None) -> dict[str, Any]:
    """Everything the replay produced, as one JSON-ready dict (the dashboard's replay player reads it)."""
    return {
        "episode": episode.key, "volcano": episode.volcano, "cameras": list(episode.cameras),
        "start": to_iso(episode.start), "end": to_iso(episode.end), "step_minutes": step / timedelta(minutes=1),
        "agent_every_minutes": None if agent_every is None else agent_every / timedelta(minutes=1),
        "official_phases": {phase: [to_iso(low), to_iso(high)] for phase, (low, high) in episode.phases.items()},
        "ticks": [json.loads(row[0]) for row in conn.execute("SELECT report FROM replay_ticks ORDER BY clock")],
        "bulletins": [json.loads(row[0]) for row in conn.execute(
            "SELECT body FROM bulletins WHERE volcano = ? ORDER BY clock, id", (episode.volcano,))],
        "phases": phases,
        "comparison": {
            "heights": [height_row(conn, check, episode.local) for check in episode.checks],
            "ends": end_rows(conn, episode), "drift": drift_rows(conn, episode),
            "bulletins": bulletin_rows(conn, episode), "activity": activity_rows(conn, episode)},
        "cost_usd": round(conn.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM api_calls").fetchone()[0], 4),
    }


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def report_markdown(timeline: dict[str, Any], episode: Episode) -> str:
    comparison, every = timeline["comparison"], timeline["agent_every_minutes"]
    bulletins = [[local_time(b["clock"], episode.local), b["activity_level"], _cell(b["headline_en"]),
                  _cell(b["headline_es"]), "yes" if all(m["verified"] for m in b["measurements"]) else "no"]
                 for b in timeline["bulletins"]]
    agent = f"a bulletin every {every:g} min and at the end" if every else "no agent"
    return "\n".join([
        f"# Replay of episode {episode.key}: {episode.volcano}", "",
        f"From {local_time(timeline['start'], episode.local)} to {local_time(timeline['end'], episode.local)} local "
        f"time: {len(timeline['ticks'])} steps of {timeline['step_minutes']:g} min, {agent}. "
        f"Meta API cost: ${timeline['cost_usd']:.2f}.", "",
        "## Bulletins", "",
        table(["Time (local)", "Activity", "Headline", "Titular", "Numbers checked"], bulletins), "",
        "## What the bulletins quoted against the official values", "",
        table(BULLETIN_HEADER, comparison["bulletins"]), "",
        "## Activity against the official times", "", table(ACTIVITY_HEADER, comparison["activity"]), "",
        "## The replay's measurements against the official values", "",
        table(HEIGHT_HEADER, comparison["heights"]), "",
        "## End of fountaining", "", table(END_HEADER, comparison["ends"]), "",
        "## Drift", "", table(DRIFT_HEADER, comparison["drift"]), "",
    ])


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Replay a past episode through the pipeline on a simulated clock "
                                                 "(quality, hourly SAM tracking and measuring, the agent's "
                                                 "bulletins) and compare it with the official values.")
    parser.add_argument("--episode", required=True, choices=sorted(EPISODES), help="which episode")
    parser.add_argument("--speed", type=float, default=0,
                        help="at most this many simulated seconds per wall second, e.g. 60 (default 0: no limit)")
    parser.add_argument("--step", type=float, default=STEP / timedelta(minutes=1),
                        help="simulated minutes per step (default 5)")
    parser.add_argument("--agent-every", type=float, default=AGENT_EVERY / timedelta(minutes=1),
                        help="simulated minutes between bulletins (default 60)")
    parser.add_argument("--no-agent", action="store_true", help="no agent runs and no bulletins")
    args = parser.parse_args(argv)
    if args.step <= 0 or args.agent_every <= 0 or args.speed < 0:
        parser.error("--step and --agent-every must be positive and --speed not negative")
    episode = EPISODES[args.episode]
    settings = Settings.from_env()
    out_dir = settings.data_dir / "replay" / f"ep{episode.key}"
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    with closing(db.connect(settings.db_path)) as source, closing(db.connect(out_dir / "vigia.sqlite")) as conn, \
            httpx.Client(headers={"User-Agent": settings.user_agent}, timeout=30) as http:
        marks = ",".join("?" * len(episode.cameras))
        stored = source.execute(f"SELECT COUNT(*) FROM frames WHERE camera_id IN ({marks}) AND captured_at "
                                "BETWEEN ? AND ?", (*episode.cameras, to_iso(episode.start), to_iso(episode.end)))
        if not stored.fetchone()[0]:
            parser.error(f"{settings.db_path} has no frames of episode {episode.key}; backfill them with vigia-backfill")
        client = MetaClient.from_env(CostLedger(conn, settings.daily_budget_usd))
        run_replay(source, context_from_settings(settings, conn, http, episode.start, client), episode, out_dir,
                   step=timedelta(minutes=args.step), speed=args.speed,
                   agent_every=None if args.no_agent else timedelta(minutes=args.agent_every))
    print((out_dir / "report.md").read_text(encoding="utf-8"))
    print(f"timeline: {out_dir / 'timeline.json'}")
```

In `pyproject.toml`, add under `[project.scripts]`:

```toml
vigia-replay = "vigia.replay:main"
```

then reinstall: `.venv\Scripts\python.exe -m pip install -e ".[dev]" -q`.

- [ ] **Step 4: Run the tests**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add vigia/replay.py vigia/db.py pyproject.toml tests/test_replay.py
git commit -m "Replay an episode through the pipeline on a simulated clock and compare its bulletins with the record"
```

---

### Task 10: The episode's phases: Muse Spark's reading of the timelapse against SAM and HVO

**Files:**
- Create: `vigia/phases.py`
- Modify: `vigia/replay.py`
- Test: `tests/test_phases.py`, `tests/test_replay.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_phases.py`:

```python
import json
from dataclasses import replace
from datetime import timedelta

import httpx

from test_agent_tools import SOURCES, T0, add_frame, add_run, add_track, context, store  # store is a fixture
from test_meta_client import SPARK_USAGE, make_client, response_body
from test_tracking import UPLOADED, needs_ffmpeg
from vigia.episodes import EP55
from vigia.phases import PHASES, ask_phases, cross_check, sam_phases

M = timedelta(minutes=1)
HEIGHTS = [10, 20, 40, 60, 70, 72, 70, 66, 62, 58, 40, 20]  # running medians: 20 30 40 60 70 70 70 66 62 58 49 40


def fountain(conn, store, camera_id, minutes, height):
    """A frame `minutes` from 15:00Z on which a fountain `height` pixels tall was tracked."""
    frame_id = add_frame(conn, store, camera_id, minutes)
    add_track(conn, add_run(conn, camera_id, "fountain", [frame_id]), [frame_id], box=(60, 150 - height, 120, 150))
    return frame_id


def test_sam_phases_read_the_fountains_height_through_the_episode(conn, store):
    for i, height in enumerate(HEIGHTS):
        fountain(conn, store, "kilauea-k2", 2 * i, height)

    assert sam_phases(conn, "kilauea-k2", T0, T0 + 30 * M) == {
        "onset": "2026-10-17T15:00:00Z", "peak": "2026-10-17T15:08:00Z",  # the first highest running median
        "decline": "2026-10-17T15:16:00Z", "end": "2026-10-17T15:22:00Z"}  # first under 90 % of it; last


def test_sam_phases_without_a_fountain_are_empty(conn):
    assert sam_phases(conn, "kilauea-k2", T0, T0 + 30 * M) == dict.fromkeys(PHASES)


def test_cross_check_sets_each_reading_against_the_official_window(conn, store):
    fountain(conn, store, "kilauea-v1", -35, 10)  # 14:25: the first fountain on any camera
    for i, height in enumerate(HEIGHTS):
        fountain(conn, store, "kilauea-k2", 2 * i - 20, height)  # 14:40 to 15:02
    episode = replace(EP55, start=T0 - 60 * M, end=T0 + 60 * M, phases={
        "onset": (T0 - 30 * M,) * 2, "peak": (T0, T0 + 10 * M), "decline": (T0 + 10 * M, T0 + 30 * M),
        "end": (T0 + 40 * M,) * 2})
    spark = {"onset": {"seen": True, "time": "2026-10-17T14:20:00Z"},
             "peak": {"seen": True, "time": "2026-10-17T16:42:00Z"},
             "decline": {"seen": False, "time": None}, "end": {"seen": True, "time": "2026-10-17T15:45:00Z"}}

    result = cross_check(conn, episode, spark)

    assert result["rows"] == [
        ["onset", "04:30", "04:40 (+10 min)", "kilauea-v1: 04:25 (-5 min)", "04:20 (-10 min)"],
        ["peak", "05:00-05:10", "04:48 (-12 min)", "-", "06:42 (+92 min)"],
        ["decline", "05:10-05:30", "04:56 (-14 min)", "-", "-"],
        ["end", "05:40", "05:02 (-38 min)", "kilauea-k2: 05:02 (-38 min)", "05:45 (+5 min)"]]
    assert result["camera_id"] == "kilauea-k2" and result["muse_spark"] == spark
    assert result["sam"]["peak"] == "2026-10-17T14:48:00Z"
    assert result["sam_any_camera"]["onset"] == {"time": "2026-10-17T14:25:00Z", "camera_id": "kilauea-v1"}


def test_cross_check_without_muse_spark_says_it_was_not_asked(conn):
    assert [row[4] for row in cross_check(conn, EP55, None)["rows"]] == ["not asked"] * 4


def phase(second, seen=True, printed=""):
    return {"seen": seen, "video_second": second, "printed_time": printed, "description": "A fountain."}


ANSWER = {"onset": phase(0.5, printed="2026-10-17 05:02:00 HST"), "peak": phase(1.0), "decline": phase(2.4, seen=False),
          "end": phase(99), "summary": "A short fountain."}


class FakeVideoApi:
    """The Files API and one Muse Spark answer; records every request."""

    def __init__(self, answer):
        self.answer, self.requests = answer, []

    def __call__(self, request):
        self.requests.append(request)
        if request.url.path == "/v1/files":
            return httpx.Response(200, json=UPLOADED)
        if request.method == "DELETE":
            return httpx.Response(200, json={"id": "file-1", "object": "file", "deleted": True})
        return httpx.Response(200, json=response_body("muse-spark-1.3", json.dumps(self.answer), SPARK_USAGE))


@needs_ffmpeg
def test_ask_phases_maps_each_named_video_second_to_its_frames_capture_time(conn, store, tmp_path):
    for i in range(6):  # 15:00 to 15:10, every 2 minutes
        add_frame(conn, store, "kilauea-k2", 2 * i)
    api = FakeVideoApi(ANSWER)
    camera = context(conn, tmp_path).camera("kilauea-k2")

    result = ask_phases(make_client(api, conn), conn, tmp_path, camera, SOURCES.volcanoes["kilauea"], T0,
                        T0 + 10 * M)

    assert (result["camera_id"], result["frames"], result["fps"], result["summary"]) == (
        "kilauea-k2", 6, 2.0, "A short fountain.")
    assert result["onset"] == {**ANSWER["onset"], "time": "2026-10-17T15:02:00Z"}  # second 0.5 at 2 fps: frame 1
    assert result["peak"]["time"] == "2026-10-17T15:04:00Z"
    assert result["decline"]["time"] is None
    assert result["end"]["time"] == "2026-10-17T15:10:00Z"  # a second past the clip: its last frame
    sent = json.loads(api.requests[1].content)
    assert sent["input"][0]["content"][1] == {"type": "input_video", "file_id": "file-1"}
    prompt = sent["input"][0]["content"][0]["text"]
    assert "6 frames, captured about every 2 minutes from 15:00 to 15:10 (UTC)" in prompt
    assert "about 4 minutes x t after the first" in prompt
    assert api.requests[-1].method == "DELETE"
```

Append to `tests/test_replay.py`:

```python
from vigia.phases import PHASES


def test_the_replay_reuses_muse_sparks_stored_reading_of_the_timelapse(source, conn, tmp_path):
    stored = {phase: {"seen": False, "time": None} for phase in PHASES} | {"summary": "Nothing."}
    (tmp_path / "replay").mkdir()
    (tmp_path / "replay" / "spark_phases.json").write_text(json.dumps(stored), encoding="utf-8")

    timeline = run_replay(source, context(conn, tmp_path), episode(T0, T0 + 10 * M), tmp_path / "replay",
                          step=10 * M, pipeline=FakePipeline(conn))

    assert timeline["phases"]["muse_spark"] == stored
    assert [row[4] for row in timeline["phases"]["rows"]] == ["-"] * 4
    assert "## Episode phases" in (tmp_path / "replay" / "report.md").read_text(encoding="utf-8")


def test_without_a_client_or_a_stored_reading_muse_spark_is_not_asked(source, conn, tmp_path):
    timeline = run_replay(source, context(conn, tmp_path), episode(T0, T0 + 10 * M), tmp_path / "replay",
                          step=10 * M, pipeline=FakePipeline(conn))

    assert timeline["phases"]["muse_spark"] is None and timeline["phases"]["rows"][0][4] == "not asked"
```

- [ ] **Step 2: Run them to see them fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_phases.py tests/test_replay.py -q`
Expected: ModuleNotFoundError (`vigia.phases`).

- [ ] **Step 3: Implement**

Create `vigia/phases.py`:

```python
"""The phases of an eruptive episode, read two ways and set against the official times.

Muse Spark watches the timelapse of one fixed camera, uploaded through the Files API, and names the video second
at which the lava fountain starts, peaks, declines and ends; the frame shown at that second gives each phase's
capture time. SAM's fountain tracks give the same phases from numbers: the first and last detection, and the
peak and the start of the decline of the fountain's height in pixels (its tallest box on each frame as a running
median over 5 frames; on a fixed camera the box's bottom stays at the vent). In the planning probe on episode
55's K2cam timelapse, Muse Spark put the end 1-5 minutes after HVO's but the peak after sunrise, two hours late;
SAM put the peak at 04:52 HST, inside HVO's 04:50-05:10.
"""

from __future__ import annotations

import logging
import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import openai

from vigia import tracking
from vigia.config import Camera, Volcano
from vigia.episodes import Episode, local_time
from vigia.meta.client import MetaClient
from vigia.timeutil import parse_utc, to_iso
from vigia.video import assemble

log = logging.getLogger(__name__)

PHASES = ("onset", "peak", "decline", "end")
FPS = 2.0      # timelapse frames per second: about 130 input tokens per frame
HEIGHT = 720   # timelapse height in pixels: the printed time stays readable
RUNNING = 5    # frames in the running median of the fountain's height
DECLINE = 0.9  # the decline starts at the first frame after the peak under this share of it
HEADER = ["Phase", "Official (local)", "SAM, timelapse camera", "SAM, any camera", "Muse Spark, timelapse"]
PROMPT = (
    "This is a timelapse from the {camera} webcam at {volcano}. It has {frames} frames, captured about every "
    "{cadence} minutes from {first} to {last} ({zone}), played at {fps} frames per second, so video second t shows "
    "the frame captured about {per_second} minutes x t after the first. The capture time may be printed on the "
    "frames.\n"
    "The light may change during the clip, between night and day: at night a lava fountain glows yellow-white, by "
    "day it looks red-orange. Judge its height against fixed features such as trees and the crater rim, not by its "
    "brightness or colour.\n"
    "Find the phases of the eruptive episode: onset (the lava fountain starts), peak (the fountain is at its "
    "highest), decline (the fountain is clearly lower than at its peak and dropping), end (fountaining stops). For "
    "each, give the video second and the time printed on that frame exactly as printed (empty if none), and "
    "describe what you see. Set seen to false for a phase the clip does not show.")
_PHASE = {"type": "object", "properties": {
    "seen": {"type": "boolean"}, "video_second": {"type": "number"}, "printed_time": {"type": "string"},
    "description": {"type": "string"}}, "required": ["seen", "video_second", "printed_time", "description"],
    "additionalProperties": False}
SCHEMA = {"type": "object", "properties": {**{phase: _PHASE for phase in PHASES}, "summary": {"type": "string"}},
          "required": [*PHASES, "summary"], "additionalProperties": False}


def fountain_heights(conn: sqlite3.Connection, camera_ids: list[str], start: datetime,
                     end: datetime) -> list[tuple[str, str, int]]:
    """(capture time, camera, tallest fountain box in pixels) per frame with a fountain detection, oldest first."""
    marks = ",".join("?" * len(camera_ids))
    return [tuple(row) for row in conn.execute(
        f"""SELECT f.captured_at, r.camera_id, MAX(d.box_bottom - d.box_top) FROM detections d
            JOIN frames f ON f.id = d.frame_id JOIN tracks t ON t.id = d.track_id
            JOIN tracking_runs r ON r.id = t.run_id
            WHERE r.camera_id IN ({marks}) AND r.target = 'fountain' AND f.captured_at BETWEEN ? AND ?
            GROUP BY f.id ORDER BY f.captured_at, f.id""", (*camera_ids, to_iso(start), to_iso(end)))]


def sam_phases(conn: sqlite3.Connection, camera_id: str, start: datetime, end: datetime) -> dict[str, str | None]:
    """The camera's first and last fountain detection, the frame with the highest running median of the
    fountain's height, and the first frame after it under 90 % of that median."""
    rows = fountain_heights(conn, [camera_id], start, end)
    if not rows:
        return dict.fromkeys(PHASES)
    heights = np.array([row[2] for row in rows], dtype=float)
    half = RUNNING // 2
    running = np.array([np.median(heights[max(0, i - half):i + half + 1]) for i in range(len(heights))])
    peak = int(running.argmax())
    decline = next((i for i in range(peak + 1, len(running)) if running[i] < DECLINE * running[peak]), None)
    return {"onset": rows[0][0], "peak": rows[peak][0], "decline": None if decline is None else rows[decline][0],
            "end": rows[-1][0]}


def ask_phases(client: MetaClient, conn: sqlite3.Connection, data_dir: Path, camera: Camera, volcano: Volcano,
               start: datetime, end: datetime, *, fps: float = FPS, height: int = HEIGHT) -> dict[str, Any]:
    """Muse Spark's reading of the camera's timelapse: per phase whether it saw it, the video second, the capture
    time of the frame at that second, the printed time it read there, and what it saw."""
    frames = tracking.usable_frames(conn, data_dir, camera.id, start, end)
    if len(frames) < 2:
        raise ValueError(f"{camera.id} has {len(frames)} usable frames from {to_iso(start)} to {to_iso(end)}")
    cadence = float(np.median(np.diff([frame.captured_at.timestamp() for frame in frames]))) / 60
    offset = timedelta(hours=volcano.utc_offset_hours or 0)
    zone = "UTC" if volcano.utc_offset_hours is None else f"UTC{volcano.utc_offset_hours:+g}"
    prompt = PROMPT.format(camera=camera.name, volcano=volcano.name, frames=len(frames), cadence=f"{cadence:g}",
                           first=f"{frames[0].captured_at + offset:%H:%M}", last=f"{frames[-1].captured_at + offset:%H:%M}",
                           zone=zone, fps=f"{fps:g}", per_second=f"{cadence * fps:g}")
    with tempfile.TemporaryDirectory() as tmp:
        video = assemble([frame.path for frame in frames], Path(tmp) / "timelapse.mp4", fps=fps,
                         height=min(height, frames[0].height) // 2 * 2)
        file_id = client.upload_video(video)
    try:
        answer = client.ask_json(prompt=prompt, videos=[file_id], schema_name="phases", schema=SCHEMA,
                                 purpose="phases", effort="medium", max_output_tokens=8000)
    finally:
        try:
            client.delete_file(file_id)
        except openai.APIError as exc:
            log.warning("could not delete the uploaded timelapse %s: %s", file_id, exc)
    result: dict[str, Any] = {"camera_id": camera.id, "frames": len(frames), "fps": fps, "summary": answer["summary"]}
    for phase in PHASES:
        item = answer[phase]
        index = min(max(round(item["video_second"] * fps), 0), len(frames) - 1)
        result[phase] = {**item, "time": to_iso(frames[index].captured_at) if item["seen"] else None}
    return result


def _reading(time: str | None, low: datetime, high: datetime, episode: Episode) -> str:
    """'04:52 (+0 min)': a time in local time and its minutes outside the official window."""
    if time is None:
        return "-"
    when = parse_utc(time)
    outside = when - high if when > high else when - low if when < low else timedelta(0)
    return f"{local_time(time, episode.local)} ({outside / timedelta(minutes=1):+.0f} min)"


def cross_check(conn: sqlite3.Connection, episode: Episode, spark: dict[str, Any] | None) -> dict[str, Any]:
    """Each phase by SAM on the timelapse camera, by SAM on any camera (onset and end), by Muse Spark (None: not
    asked) and officially, with each reading's minutes outside the official window."""
    fixed = sam_phases(conn, episode.timelapse_camera, episode.start, episode.end)
    heights = fountain_heights(conn, list(episode.cameras), episode.start, episode.end)
    anywhere = {"onset": heights[0] if heights else None, "end": heights[-1] if heights else None}
    rows = []
    for phase in PHASES:
        low, high = episode.phases[phase]
        official = local_time(to_iso(low), episode.local)
        if high != low:
            official += f"-{local_time(to_iso(high), episode.local)}"
        found = anywhere.get(phase)
        if spark is None:
            asked = "not asked"
        else:
            asked = _reading(spark[phase]["time"] if spark[phase]["seen"] else None, low, high, episode)
        rows.append([phase, official, _reading(fixed[phase], low, high, episode),
                     f"{found[1]}: {_reading(found[0], low, high, episode)}" if found else "-", asked])
    return {"camera_id": episode.timelapse_camera, "sam": fixed,
            "sam_any_camera": {phase: found and {"time": found[0], "camera_id": found[1]}
                               for phase, found in anywhere.items()},
            "muse_spark": spark, "rows": rows}
```

In `vigia/replay.py`:
- import `openai`, `BudgetExceeded` (`from vigia.meta.ledger import BudgetExceeded, CostLedger`), `from vigia.agent.tools import ToolContext, ToolError` and `from vigia.phases import HEADER as PHASES_HEADER, ask_phases, cross_check`;
- add a `spark_video: bool = True` keyword to `run_replay`, after `speed`;
- replace the line that builds the timeline with:

```python
    spark = _spark_phases(base, episode, out_dir) if spark_video else None
    timeline = build_timeline(conn, episode, step, agent_every, cross_check(conn, episode, spark))
```

- add this function after `run_replay`:

```python
def _spark_phases(base: ToolContext, episode: Episode, out_dir: Path) -> dict[str, Any] | None:
    """Muse Spark's reading of the episode's timelapse: asked once, then read from spark_phases.json."""
    path = out_dir / "spark_phases.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    if base.client is None:
        return None
    try:
        answer = ask_phases(base.client, base.conn, base.data_dir, base.camera(episode.timelapse_camera),
                            base.sources.volcanoes[episode.volcano], episode.start, episode.end)
    except (openai.APIError, BudgetExceeded, ToolError, ValueError) as exc:
        log.warning("Muse Spark did not read the timelapse: %s", exc)
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(answer, ensure_ascii=False, indent=1), encoding="utf-8")
    return answer
```

- in `report_markdown`, build the list as `sections = [...]` and, before joining, add the phases:

```python
    if timeline["phases"]:
        sections += ["## Episode phases", "",
                     f"SAM's fountain tracks and Muse Spark's reading of the {timeline['phases']['camera_id']} "
                     "timelapse, in local time, each with its minutes outside the official window.", "",
                     table(PHASES_HEADER, timeline["phases"]["rows"]), ""]
    return "\n".join(sections)
```

- in `main`, add `parser.add_argument("--no-video", action="store_true", help="do not ask Muse Spark to read the timelapse")` and pass `spark_video=not args.no_video` to `run_replay`;
- in the module docstring, add "and the episode's phases as SAM's tracks and Muse Spark's reading of the timelapse give them (vigia.phases)" to the description of `timeline.json`.

- [ ] **Step 4: Run the tests**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add vigia/phases.py vigia/replay.py tests/test_phases.py tests/test_replay.py
git commit -m "Read the episode's phases from Muse Spark's view of the timelapse and set them against SAM and HVO"
```

---

### Task 11: Acceptance replay, notes and the roadmap (orchestrator)

- [ ] **Reinstall and run the suite:**
  - `.venv\Scripts\python.exe -m pip install -e ".[dev]" -q`
  - `.venv\Scripts\python.exe -m pytest -q`
- [ ] **One bulletin first, as a smoke test,** in the main database (about $0.05): `vigia-bulletin --volcano kilauea --at 2026-10-17T05:00-10:00`. Check:
  - the answer parses;
  - the Spanish has its accents;
  - the plume top is verified;
  - the evidence overlay shows the mask;
  - the wind check is there;
  - the HTML opens.
  - If the prompt needs a fix, fix it before the replay, which runs it seven times.
- [ ] **The replay:** `vigia-replay --episode 55`, in the background. Expect about an hour and $1.0–1.2. The log prints one line per step. It can be resumed if interrupted.
- [ ] **Acceptance:**
  - six or more bulletins: seven are expected, on the hours from 14:00 to 19:00Z, plus one at 19:30Z;
  - `report.md` has the comparison tables;
  - spot-check one run's trace (`trace()`): nothing captured after its clock.
- [ ] **Write `docs/research/replay_ep55.md`:**
  - the command, the cost and the time;
  - the bulletins (time, level, EN and ES headlines, whether their numbers were verified);
  - the comparison tables from `report.md`;
  - the phases cross-check;
  - findings and limits.
- [ ] **Update `docs/PLAN.md`:**
  - tick Phase 5;
  - add the facts the plan depends on (bulletins, replay, phases);
  - update the module map (`pipeline.py`, `episodes.py`, `phases.py`, `agent/render.py`), the test count and the budget.
- [ ] **Close the phase:**
  - append the execution notes to this plan;
  - commit, push, and update the project memory.

---

## Execution notes

- **Subagents:** one `implementer` per group: 1–2, 3–5, 6–7, 8 and 9–10, with one commit per task. One `reviewer` per group gets its BASE and HEAD. Findings go back to the same implementer by SendMessage. Task 11 is the orchestrator's.
- **Money:** Tasks 1–10 call no paid API, because every test uses fakes. Task 11 spends about $0.05 on the smoke bulletin and about $1.0–1.2 on the replay.
