import json

import httpx
import openai
import pytest

from conftest import NOW, make_jpeg
from test_sam import IMAGE_OUTPUT, OBJ_0
from vigil.meta.client import MetaClient
from vigil.meta.ledger import BudgetExceeded, CostLedger

SPARK_USAGE = {"input_tokens": 1800, "input_tokens_details": {"cached_tokens": 0},
               "output_tokens": 300, "output_tokens_details": {"reasoning_tokens": 120}, "total_tokens": 2100}


def response_body(model, text, usage):
    return {
        "id": "resp_1", "object": "response", "created_at": 1793000000, "status": "completed", "model": model,
        "output": [{"type": "message", "id": "msg_1", "role": "assistant", "status": "completed",
                    "content": [{"type": "output_text", "text": text, "annotations": []}]}],
        "usage": usage,
    }


class FakeApi:
    """Records requests and answers them with a handler chosen per test."""

    def __init__(self, respond):
        self.requests: list[httpx.Request] = []
        self._respond = respond

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._respond(request)

    def json_body(self, i=0):
        return json.loads(self.requests[i].content)


def make_client(api, conn, budget=1.0):
    sdk = openai.OpenAI(base_url="https://api.meta.ai/v1", api_key="test-key", max_retries=0,
                        http_client=httpx.Client(transport=httpx.MockTransport(api)))
    return MetaClient(sdk, CostLedger(conn, daily_budget_usd=budget, now=lambda: NOW))


def calls(conn):
    return conn.execute("SELECT * FROM api_calls ORDER BY id").fetchall()


def test_segment_image_sends_one_phrase_and_the_image_as_a_data_url(conn):
    api = FakeApi(lambda r: httpx.Response(200, json=response_body("sam-3.1", IMAGE_OUTPUT, {"images_processed": 1})))

    make_client(api, conn).segment_image(make_jpeg(), "volcanic plume", purpose="smoke")

    body = api.json_body()
    assert api.requests[0].url.path == "/v1/responses"
    assert body["model"] == "sam-3.1"
    text_part, image_part = body["input"][0]["content"]
    assert text_part == {"type": "input_text", "text": "volcanic plume"}
    assert image_part["type"] == "input_image"
    assert image_part["image_url"].startswith("data:image/jpeg;base64,")
    assert body["metadata"]["include_confidence"] == "true"


def test_segment_image_returns_objects_and_records_the_cost(conn):
    api = FakeApi(lambda r: httpx.Response(200, json=response_body("sam-3.1", IMAGE_OUTPUT, {"images_processed": 1})))

    objects = make_client(api, conn).segment_image(make_jpeg(), "volcanic plume", purpose="smoke")

    assert [o.object_id for o in objects] == ["0", "1"]
    [row] = calls(conn)
    assert (row["model"], row["purpose"], row["ok"]) == ("sam-3.1", "smoke", 1)
    assert row["cost_usd"] == pytest.approx(0.0025)


def test_api_errors_are_recorded_and_raised(conn):
    error = {"error": {"message": "invalid prompt", "type": "invalid_request_error", "param": None, "code": None}}
    api = FakeApi(lambda r: httpx.Response(400, json=error))

    with pytest.raises(openai.BadRequestError):
        make_client(api, conn).segment_image(make_jpeg(), "lava", purpose="smoke")

    [row] = calls(conn)
    assert row["ok"] == 0
    assert "400" in row["error"]


def test_calls_over_the_daily_budget_never_reach_the_api(conn):
    api = FakeApi(lambda r: httpx.Response(200, json=response_body("sam-3.1", "", {"images_processed": 1})))

    with pytest.raises(BudgetExceeded):
        make_client(api, conn, budget=0.001).segment_image(make_jpeg(), "lava", purpose="smoke")

    assert api.requests == []


def test_ask_json_requests_strict_schema_output_and_parses_it(conn):
    answer = {"usable": True}
    api = FakeApi(lambda r: httpx.Response(200, json=response_body("muse-spark-1.3", json.dumps(answer), SPARK_USAGE)))
    schema = {"type": "object", "properties": {"usable": {"type": "boolean"}},
              "required": ["usable"], "additionalProperties": False}

    result = make_client(api, conn).ask_json(
        prompt="Is this frame usable?", images=[make_jpeg()], schema_name="frame_check", schema=schema,
        instructions="You inspect volcano webcam frames.", purpose="smoke",
    )

    body = api.json_body()
    assert body["model"] == "muse-spark-1.3"
    assert body["text"]["format"] == {"type": "json_schema", "name": "frame_check", "schema": schema, "strict": True}
    assert body["instructions"] == "You inspect volcano webcam frames."
    assert [p["type"] for p in body["input"][0]["content"]] == ["input_text", "input_image"]
    assert result == answer
    [row] = calls(conn)
    assert (row["input_tokens"], row["output_tokens"]) == (1800, 300)
    assert row["cost_usd"] == pytest.approx(1800 * 1.25e-6 + 300 * 4.25e-6)


def sse(events):
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()


def test_segment_video_streams_frames_and_records_billed_frames(conn):
    final = response_body("sam-3.1", "", {"video_frames_processed": 60})
    events = [
        {"type": "response.created", "sequence_number": 0, "response": {**final, "status": "in_progress", "output": []}},
        {"type": "response.output_text.delta", "sequence_number": 1, "item_id": "msg_1", "output_index": 0,
         "content_index": 0, "delta": f"<0f>{OBJ_0}\n", "logprobs": []},
        {"type": "response.output_text.delta", "sequence_number": 2, "item_id": "msg_1", "output_index": 0,
         "content_index": 0, "delta": f"<5f>{OBJ_0}\n", "logprobs": []},
        {"type": "response.completed", "sequence_number": 3, "response": final},
    ]
    api = FakeApi(lambda r: httpx.Response(200, content=sse(events), headers={"content-type": "text/event-stream"}))

    objects = make_client(api, conn).segment_video("file-123", "lava fountain", purpose="smoke", expected_frames=60)

    body = api.json_body()
    assert body["stream"] is True
    assert body["input"][0]["content"][1] == {"type": "input_video", "file_id": "file-123"}
    assert [(o.frame_index, o.object_id) for o in objects] == [(0, "0"), (5, "0")]
    [row] = calls(conn)
    assert row["cost_usd"] == pytest.approx(60 * 0.20e-3)


def test_upload_video_uses_the_user_data_purpose_with_an_expiry(conn, tmp_path):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    uploaded = {"id": "file-123", "object": "file", "bytes": 12, "created_at": 1793000000,
                "filename": "clip.mp4", "purpose": "user_data"}
    api = FakeApi(lambda r: httpx.Response(200, json=uploaded))

    file_id = make_client(api, conn).upload_video(clip)

    assert file_id == "file-123"
    request = api.requests[0]
    assert request.url.path == "/v1/files"
    assert b'name="purpose"\r\n\r\nuser_data' in request.content
    assert b'name="expires_after[seconds]"' in request.content


TOOL = {"type": "function", "name": "list_cameras_status", "description": "Status of every camera.",
        "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        "strict": True}


def turn_body(calls, text="", reasoning="", rid="resp_2", status="completed"):
    """A Muse Spark Responses answer: optional reasoning summary and commentary, then function calls."""
    output = []
    if reasoning:
        output.append({"type": "reasoning", "id": "rs_1", "summary": [{"type": "summary_text", "text": reasoning}]})
    if text:
        output.append({"type": "message", "id": "msg_1", "role": "assistant", "status": "completed",
                       "content": [{"type": "output_text", "text": text, "annotations": []}]})
    output += [{"type": "function_call", "id": f"fc_{i}", "call_id": f"call_{i}", "name": name,
                "arguments": arguments, "status": "completed"} for i, (name, arguments) in enumerate(calls)]
    return {"id": rid, "object": "response", "created_at": 1793000000, "status": status,
            "model": "muse-spark-1.3", "output": output, "usage": SPARK_USAGE}


def test_respond_sends_tools_and_instructions_every_turn_and_chains_the_previous_one(conn):
    api = FakeApi(lambda r: httpx.Response(200, json=turn_body([("list_cameras_status", "{}")])))
    client = make_client(api, conn)

    client.respond(input=[{"role": "user", "content": "Check the cameras."}], tools=[TOOL],
                   instructions="Be brief.", purpose="agent")
    client.respond(input=[{"type": "function_call_output", "call_id": "call_0", "output": "{}"}], tools=[TOOL],
                   instructions="Be brief.", purpose="agent", previous_response_id="resp_2")

    first, second = api.json_body(0), api.json_body(1)
    assert "previous_response_id" not in first
    assert second["previous_response_id"] == "resp_2"
    assert second["input"] == [{"type": "function_call_output", "call_id": "call_0", "output": "{}"}]
    for body in (first, second):
        assert body["model"] == "muse-spark-1.3"
        assert (body["tools"], body["instructions"]) == ([TOOL], "Be brief.")
        assert body["reasoning"] == {"effort": "medium", "summary": "auto"}
        assert body["parallel_tool_calls"] is True


def test_respond_asks_the_server_not_to_store_the_response_when_told_to(conn):
    api = FakeApi(lambda r: httpx.Response(200, json=turn_body([])))
    client = make_client(api, conn)

    client.respond(input=[], tools=[TOOL], instructions="x", purpose="agent")
    client.respond(input=[], tools=[TOOL], instructions="x", purpose="agent", store=False)

    assert "store" not in api.json_body(0)
    assert api.json_body(1)["store"] is False


def test_a_turn_keeps_its_output_items_but_not_the_reasoning_to_resend_them(conn):
    body = turn_body([("get_wind", '{"volcano": "kilauea"}')], text="First the wind.", reasoning="One check.")
    api = FakeApi(lambda r: httpx.Response(200, json=body))

    turn = make_client(api, conn).respond(input=[], tools=[TOOL], instructions="x", purpose="agent")

    assert [item["type"] for item in turn.items] == ["message", "function_call"]
    assert turn.items[0]["content"][0]["text"] == "First the wind."
    assert (turn.items[1]["call_id"], turn.items[1]["name"], turn.items[1]["arguments"]) == (
        "call_0", "get_wind", '{"volcano": "kilauea"}')
    assert all(None not in item.values() for item in turn.items)


def test_respond_returns_the_tool_calls_the_commentary_and_the_reasoning(conn):
    body = turn_body([("get_wind", '{"volcano": "kilauea"}'), ("list_cameras_status", "{}")],
                     text="First the cameras.", reasoning="Two independent checks.")
    api = FakeApi(lambda r: httpx.Response(200, json=body))

    turn = make_client(api, conn).respond(input=[], tools=[TOOL], instructions="x", purpose="agent")

    assert [(c.call_id, c.name, c.arguments) for c in turn.calls] == [
        ("call_0", "get_wind", '{"volcano": "kilauea"}'), ("call_1", "list_cameras_status", "{}")]
    assert (turn.response_id, turn.status, turn.text, turn.reasoning) == (
        "resp_2", "completed", "First the cameras.", "Two independent checks.")
    assert turn.cost_usd == pytest.approx(1800 * 1.25e-6 + 300 * 4.25e-6)
    assert turn.context_tokens == 2100
    assert calls(conn)[0]["purpose"] == "agent"


def test_a_tagged_client_logs_its_calls_under_the_tag(conn):
    api = FakeApi(lambda r: httpx.Response(200, json=turn_body([])))
    client = make_client(api, conn)
    job = client.tagged("agent:7")

    job.respond(input=[], tools=[TOOL], instructions="x", purpose="turn")
    client.respond(input=[], tools=[TOOL], instructions="x", purpose="turn")

    assert [row["purpose"] for row in calls(conn)] == ["agent:7/turn", "turn"]
    assert job.tag_spent() == pytest.approx(0.003525)


def test_a_tagged_budget_refuses_a_call_before_sending_it(conn):
    api = FakeApi(lambda r: httpx.Response(200, json=turn_body([])))
    job = make_client(api, conn, budget=10.0).tagged("agent:7", budget_usd=0.02)

    job.respond(input=[], tools=[TOOL], instructions="x", purpose="turn", max_output_tokens=2000)
    with pytest.raises(BudgetExceeded, match="agent:7"):
        job.respond(input=[], tools=[TOOL], instructions="x", purpose="turn")  # 6000 output tokens: ~$0.026

    assert len(api.requests) == 1


def test_an_untagged_client_has_no_job_spend(conn):
    with pytest.raises(RuntimeError, match="tagged"):
        make_client(FakeApi(lambda r: httpx.Response(500)), conn).tag_spent()


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
