import json

import httpx
import openai
import pytest

from conftest import NOW, make_jpeg
from test_sam import IMAGE_OUTPUT, OBJ_0
from vigia.meta.client import MetaClient
from vigia.meta.ledger import BudgetExceeded, CostLedger

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
