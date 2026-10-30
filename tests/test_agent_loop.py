import json

import httpx
import openai
import pytest

from conftest import NOW, make_jpeg
from test_agent_tools import SOURCES, T0, context
from test_meta_client import make_client, response_body, turn_body
from test_sam import IMAGE_OUTPUT
from vigia.agent.loop import (REPORT, TURN_RETRY_PAUSES, WRAP_UP, context_from_settings, instructions, main, run_agent,
                              trace)
from vigia.agent.tools import Args, NoArgs, Tool
from vigia.config import Volcano
from vigia.meta.client import MetaClient
from vigia.timeutil import to_iso


class Script:
    """Answers each Meta request with the next scripted answer: a JSON body (HTTP 200) or an httpx.Response."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.requests = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(json.loads(request.content))
        answer = self.answers.pop(0)
        return answer if isinstance(answer, httpx.Response) else httpx.Response(200, json=answer)


class EchoArgs(Args):
    n: int


def echo(ctx, args):
    return {"n": args.n, "now": to_iso(ctx.now)}


def segment(ctx, args):
    return {"objects": len(ctx.meta().segment_image(make_jpeg(), "steam", purpose="segment"))}


FAKE_TOOLS = [Tool("echo", "Echo n.", EchoArgs, echo), Tool("segment", "Segment steam.", NoArgs, segment)]
TURN = 1800 * 1.25e-6 + 300 * 4.25e-6  # the cost of one scripted turn


def run(conn, tmp_path, api, **kwargs):
    kwargs.setdefault("sleep", lambda seconds: None)  # a retried turn does not wait in tests
    return run_agent(make_client(api, conn), context(conn, tmp_path), "kilauea", "Echo twice.", tools=FAKE_TOOLS,
                     wall_clock=lambda: NOW, **kwargs)


def steps(conn, run_id):
    return conn.execute("SELECT * FROM agent_steps WHERE run_id = ? ORDER BY seq", (run_id,)).fetchall()


def test_a_run_calls_tools_until_muse_spark_answers_and_stores_the_trace(conn, tmp_path):
    api = Script(turn_body([("echo", '{"n": 1}'), ("echo", '{"n": 2}')], text="Checking.", reasoning="Two calls.",
                           rid="resp_1"),
                 turn_body([], text="n was 1 and 2.", rid="resp_2"))

    result = run(conn, tmp_path, api)

    assert (result.status, result.turns, result.final_text, result.error) == ("done", 2, "n was 1 and 2.", None)
    first, second = api.requests
    assert first["input"] == [{"role": "user", "content": "Echo twice."}] and "previous_response_id" not in first
    assert second["previous_response_id"] == "resp_1"
    assert [item["call_id"] for item in second["input"]] == ["call_0", "call_1"]
    assert json.loads(second["input"][1]["output"]) == {"n": 2, "now": "2026-10-17T15:00:00Z"}
    assert (second["tools"], second["instructions"]) == (first["tools"], first["instructions"])
    trace_rows = steps(conn, result.run_id)
    assert [(s["kind"], s["turn"], s["tool_name"]) for s in trace_rows] == [
        ("model", 1, None), ("tool", 1, "echo"), ("tool", 1, "echo"), ("model", 2, None)]
    assert (trace_rows[0]["text"], trace_rows[0]["reasoning"], trace_rows[0]["response_id"]) == (
        "Checking.", "Two calls.", "resp_1")
    assert (trace_rows[1]["ok"], trace_rows[1]["arguments"], trace_rows[1]["call_id"]) == (1, '{"n": 1}', "call_0")
    row = conn.execute("SELECT * FROM agent_runs WHERE id = ?", (result.run_id,)).fetchone()
    assert (row["status"], row["clock"], row["volcano"], row["turns"], row["task"]) == (
        "done", "2026-10-17T15:00:00Z", "kilauea", 2, "Echo twice.")
    assert row["cost_usd"] == pytest.approx(2 * TURN) == result.cost_usd


def test_a_bad_tool_call_goes_back_to_muse_spark_as_an_error(conn, tmp_path):
    api = Script(turn_body([("echo", '{"n": "x"}'), ("nope", "{}")], rid="resp_1"), turn_body([], text="Sorry."))

    result = run(conn, tmp_path, api)

    assert result.status == "done"
    outputs = [json.loads(item["output"]) for item in api.requests[1]["input"]]
    assert "invalid arguments" in outputs[0]["error"] and "unknown tool" in outputs[1]["error"]
    assert [s["ok"] for s in steps(conn, result.run_id) if s["kind"] == "tool"] == [0, 0]


def test_tool_steps_record_what_their_meta_calls_cost(conn, tmp_path):
    api = Script(turn_body([("segment", "{}")], rid="resp_1"),
                 response_body("sam-3.1", IMAGE_OUTPUT, {"images_processed": 1}),
                 turn_body([], text="Two objects."))

    result = run(conn, tmp_path, api)

    tool_step = [s for s in steps(conn, result.run_id) if s["kind"] == "tool"][0]
    assert tool_step["cost_usd"] == pytest.approx(0.0025)
    assert json.loads(tool_step["result"]) == {"objects": 2}
    purposes = [row[0] for row in conn.execute("SELECT purpose FROM api_calls ORDER BY id")]
    assert purposes == [f"agent:{result.run_id}/turn", f"agent:{result.run_id}/segment", f"agent:{result.run_id}/turn"]
    assert result.cost_usd == pytest.approx(2 * TURN + 0.0025)


def test_the_last_turn_tells_muse_spark_to_answer_and_its_tool_calls_are_not_run(conn, tmp_path):
    api = Script(turn_body([("echo", '{"n": 1}')], rid="resp_1"), turn_body([("echo", '{"n": 2}')], rid="resp_2"))

    result = run(conn, tmp_path, api, max_turns=2)

    assert (result.status, result.turns) == ("max_turns", 2)
    assert api.requests[1]["input"][-1] == {"role": "user", "content": WRAP_UP}
    assert len([s for s in steps(conn, result.run_id) if s["kind"] == "tool"]) == 1


def test_a_run_stops_before_a_turn_that_would_exceed_its_budget(conn, tmp_path):
    api = Script()

    result = run(conn, tmp_path, api, budget_usd=0.02)  # one turn is estimated at about $0.026

    assert (result.status, result.turns, api.requests) == ("budget", 0, [])
    assert f"agent:{result.run_id}" in result.error


def test_an_api_failure_ends_the_run_with_an_error(conn, tmp_path):
    failure = httpx.Response(500, json={"error": {"message": "boom", "type": "server_error", "param": None,
                                                  "code": None}})

    result = run(conn, tmp_path, Script(*[failure] * (len(TURN_RETRY_PAUSES) + 1)))

    assert result.status == "error" and "boom" in result.error
    assert conn.execute("SELECT status FROM agent_runs WHERE id = ?", (result.run_id,)).fetchone()[0] == "error"


SERVER_DOWN = httpx.Response(503, json={"error": {"message": "persistence service error", "type": "server_error",
                                                  "param": None, "code": None}})


def test_a_turn_the_server_failed_is_sent_again_after_a_pause(conn, tmp_path):
    api = Script(turn_body([("echo", '{"n": 1}')], rid="resp_1"), SERVER_DOWN, SERVER_DOWN, turn_body([], text="Done."))
    pauses = []

    result = run(conn, tmp_path, api, sleep=pauses.append)

    assert (result.status, result.turns, result.final_text) == ("done", 2, "Done.")
    assert pauses == list(TURN_RETRY_PAUSES)
    assert api.requests[1] == api.requests[2] == api.requests[3]  # the same turn, chained to resp_1


def test_a_turn_the_server_keeps_failing_ends_the_run(conn, tmp_path):
    api = Script(*[SERVER_DOWN] * (len(TURN_RETRY_PAUSES) + 1))

    result = run(conn, tmp_path, api, sleep=lambda seconds: None)

    assert result.status == "error" and "persistence service error" in result.error
    assert len(api.requests) == len(TURN_RETRY_PAUSES) + 1


def test_a_refused_request_is_not_sent_again(conn, tmp_path):
    refused = httpx.Response(400, json={"error": {"message": "bad request", "type": "invalid_request_error",
                                                  "param": None, "code": None}})
    api = Script(refused)

    result = run(conn, tmp_path, api, sleep=lambda seconds: pytest.fail("a 400 must not be retried"))

    assert result.status == "error" and len(api.requests) == 1


def test_an_answer_cut_off_by_the_token_limit_is_an_error(conn, tmp_path):
    result = run(conn, tmp_path, Script(turn_body([], text="The plume is", status="incomplete")))

    assert result.status == "error" and "max_output_tokens" in result.error


def test_the_instructions_give_the_clock_the_agency_and_the_rules():
    volcano = Volcano(**{**SOURCES.volcanoes["kilauea"].model_dump(), "utc_offset_hours": -10})

    text = instructions(volcano, "kilauea", T0)

    assert "It is 2026-10-17 15:00 UTC (2026-10-17 05:00 local time, UTC-10)." in text
    assert "USGS Hawaiian Volcano Observatory (HVO)" in text and "https://www.usgs.gov/volcanoes/kilauea" in text
    assert "never issue alerts" in text
    assert "The volcano's id is kilauea." in text


def test_trace_prints_each_step_and_the_final_report(conn, tmp_path):
    api = Script(turn_body([("echo", '{"n": 1}')], text="Checking.", rid="resp_1"), turn_body([], text="n was 1."))
    result = run(conn, tmp_path, api)

    text = trace(conn, result.run_id)

    assert text.splitlines()[0].startswith(f"run {result.run_id} at 2026-10-17T15:00:00Z (kilauea): done after 2 turns, $0.00")
    assert "  1 model: Checking." in text
    assert '  1 tool echo {"n": 1} -> ok' in text
    assert text.endswith("n was 1.")


SOURCES_YAML = """
volcanoes:
  kilauea: {name: Kilauea, country: United States, official_agency: USGS HVO,
            official_url: "https://www.usgs.gov/volcanoes/kilauea", lat: 19.405, lon: -155.29, utc_offset_hours: -10}
cameras: []
"""


@pytest.fixture
def cli_env(monkeypatch, tmp_path):
    sources = tmp_path / "sources.yaml"
    sources.write_text(SOURCES_YAML, encoding="utf-8")
    monkeypatch.setenv("SOURCES_PATH", str(sources))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "data" / "vigia.sqlite"))
    return tmp_path


def test_cli_refuses_an_unknown_volcano(cli_env, capsys):
    with pytest.raises(SystemExit):
        main(["--volcano", "etna"])

    assert "etna" in capsys.readouterr().err


def test_cli_runs_the_agent_at_the_given_clock_and_prints_its_trace(cli_env, monkeypatch, capsys):
    api = Script(turn_body([("list_cameras_status", "{}")], rid="resp_1"), turn_body([], text="No cameras."))

    def fake_from_env(ledger):  # the CLI's own ledger, so its database connection is the only one
        sdk = openai.OpenAI(base_url="https://api.meta.ai/v1", api_key="test-key", max_retries=0,
                            http_client=httpx.Client(transport=httpx.MockTransport(api)))
        return MetaClient(sdk, ledger)

    monkeypatch.setattr("vigia.agent.loop.MetaClient.from_env", fake_from_env)

    main(["--volcano", "kilauea", "--at", "2026-10-17T05:00-10:00"])

    out = capsys.readouterr().out
    assert "at 2026-10-17T15:00:00Z (kilauea): done after 2 turns" in out
    assert "tool list_cameras_status {} -> ok" in out
    assert out.rstrip().endswith("No cameras.")
    assert "Check Kilauea now" in api.requests[0]["input"][0]["content"]


def test_an_answer_that_did_not_complete_is_an_error(conn, tmp_path):
    result = run(conn, tmp_path, Script(turn_body([], status="failed")))

    assert result.status == "error" and "failed" in result.error


def test_an_unexpected_failure_still_closes_the_run(conn, tmp_path):
    def broken(ctx, args):
        return {"not json": {1, 2}}  # a set: json.dumps fails outside the toolbox

    api = Script(turn_body([("broken", "{}")], rid="resp_1"))
    with pytest.raises(TypeError):
        run_agent(make_client(api, conn), context(conn, tmp_path), "kilauea", "Go.",
                  tools=[Tool("broken", "Broken.", NoArgs, broken)], wall_clock=lambda: NOW)

    row = conn.execute("SELECT status, error, finished_at FROM agent_runs").fetchone()
    assert (row["status"], row["finished_at"]) == ("error", to_iso(NOW))
    assert "TypeError" in row["error"]


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
