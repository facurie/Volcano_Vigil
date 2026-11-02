# Live fixes: a fountaining level only with a confirmed fountain, and a readable V1cam overlay

**Why.** On 2026-11-02 the live Space published bulletins 21, 22 and 23 (03:06, 04:06 and 05:06 HST) at level
`fountaining` ("V1cam shows active lava fountaining"). HVO's notice that day says the eruption is paused, with
strong glow and occasional spatter at the vents; episode 56 is forecast for Nov 4-7. SAM found no fountain
(the agent's V1cam and K2cam `fountain` tracks were empty) and the fountaining alerts stayed quiet, as they
should. Muse Spark picked the level from what it saw on frames such as 3212 (V1cam, 04:01 HST: spatter on the
rim, glowing gas). Nothing in the code checks the level. Separately, the dashboard's V1cam view showed the
plume mask as a 45 % sky-blue fill over an orange, glow-lit plume, which reads as noise.

Base: `6ad22ce`. Work happens in the worktree `../MetaHack-fixes`, branch `fix/live-v1-fountain`.

## Task 1: the `fountaining` level needs a fountain that something stored confirms

A fountain counts as confirmed at the clock `now` when one of these holds, using only rows that exist by `now`:

1. The volcano's latest alert with `clock <= now` is an `onset` (the alert watcher says fountaining).
2. An alert look (`alert_checks`) with `episode = 1`, `clock <= now` and `captured_at` in `(now - 1 h, now]`.
3. A SAM detection from a tracking run with `target = 'fountain'` and `window_end <= now`, on a frame captured in
   `(now - 1 h, now]` by a camera listed in `config/alerts.yaml`, whose `area_px / (width * height)` is at least
   that camera's `fountain_area`. Replays run the agent before the alerts, so this keeps a replayed fountain
   confirmed.

Steps:

- Move `CameraRule`, `AlertConfig` and `load_alert_config` from `vigil/alerts.py` to `vigil/config.py` (which has
  `ConfigError` and `load_sources`) and import them back into `vigil/alerts.py`, so `vigil.agent.bulletin` can
  use them without an import cycle (`vigil.alerts` imports `vigil.agent.bulletin`). Existing imports keep working.
- `fountain_evidence(conn, volcano_id, rules, now) -> str | None` in `vigil/agent/bulletin.py`: a short English
  phrase naming what confirms the fountain (which of the three, the camera, the capture time), or None. A
  database without the alerts tables (a replay mirrored before Phase 8) counts as no alerts.
- The task tells Muse Spark the watcher's state, next to the previous-bulletin line in `write_bulletin`: either
  that a fountain is confirmed (the phrase) or that nothing confirms one in the last hour, so spatter, bursts at the
  vent and glowing gas are `incandescence`. `BULLETIN_FINISH` defines `fountaining` as a sustained lava fountain
  that the task says is confirmed.
- `run_agent` takes `check: Callable[[str], str | None] | None`. When the model answers without tool calls and the
  answer is complete, `check(text)` may return a problem. Once per run, if a turn is left, the code records a step of
  kind `check` with the problem as its text, appends the reply's items and the problem as a user message, and the
  loop goes on. The dashboard's trace shows a `check` step as a short code note, not as model text.
- `write_bulletin(..., alert_rules: Mapping[str, CameraRule] | None = None)` passes a check that returns a problem
  when the draft parses, says `fountaining`, and `fountain_evidence` is None.
- `build_bulletin` is the last guard: a draft still at `fountaining` with no evidence is stored at `incandescence`,
  with the note `Muse Spark called this fountaining, but nothing stored by <clock> confirms a lava fountain: the
  level shows glowing lava` and a new `level_checked: bool = True` field set to False, which `verified` includes.
  Stored bulletins without the field load with True.
- The pipeline (`PipelineConfig`, `vigil-pipeline`), the replay and `vigil-bulletin` load `settings.alerts_path` and
  pass its cameras as `alert_rules`.

Tests first, with the fixtures in `tests/conftest.py`; each of the three confirmations and their clock bounds
(a row after `now`, a look older than 1 h, a small tracked fountain, a camera with no rule) gets a test, and so do
the retry (one retry only, none on the last turn) and the demotion.

## Task 2: the plume mask stops hiding a glow-lit plume

`draw_layers` gets a per-layer fill: the plume is drawn with a light fill and its outline, while the fountain and
incandescence keep the 0.45 fill. The value is picked by rendering V1cam frame 2746 (night, glow-lit plume) and a
daytime K2cam plume frame side by side, before the test is written.

## Task 3: V1cam's SAM tracks went empty after 2026-11-02 09:00Z

From agent run 17 (09:09Z) on, every `track_window` on kilauea-v1 (plume, glow and fountain, 24 calls) returned
no objects. Run 16 had found `steam` on 36 of 36 frames from 05:05 to 08:05Z. The scene and PTZ did not change,
no deploy happened in between, and K2cam kept returning tracks. Re-run SAM on one window that worked and one that
did not, in a scratch database (about $0.02), before deciding anything.
