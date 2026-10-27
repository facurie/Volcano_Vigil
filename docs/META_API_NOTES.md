# Meta Model API: research notes for Vigía Andino

Researched 2026-10-26 from the live docs at dev.meta.ai (the authoritative source), cross-checked with Context7 (`/websites/dev_meta_ai`, which agreed on every point checked) and with the official Meta repos and packages that the docs link to. The API was not called. Citations use short tags such as [models]; the [Source index](#source-index) at the end maps each tag to its URL. **(inferred)** marks anything the docs do not state outright.

---

## 0. Belief check (what the team assumed vs. what the docs say)

| # | Belief | Verdict | Details |
|---|---|---|---|
| 1 | The API is OpenAI-SDK compatible | **Confirmed** | It is "drop-in compatible with the OpenAI SDK, the Anthropic SDK, and OpenAI-compatible agent CLIs" [overview][quickstart]. Compatible surfaces: Responses, Chat Completions, Files and Models (OpenAI SDK), plus Messages (Anthropic SDK) [sdks][apiref]. |
| 2 | `base_url = https://api.meta.ai/v1` | **Confirmed** | [apiref][quickstart]. The Anthropic SDK takes the bare host `https://api.meta.ai` instead [sdks]. |
| 3 | The key lives in env var `MODEL_API_KEY` | **Confirmed, with a caveat** | `MODEL_API_KEY` is the documented convention, sent as `Authorization: Bearer $MODEL_API_KEY` [apiref][auth]. The OpenAI SDK does **not** read it automatically, so pass `api_key=os.environ["MODEL_API_KEY"]` (or set `OPENAI_API_KEY`) [sdks][quickstart]. Keys look like `LLM_<numeric_id>_<secret>` [auth][errors]. |
| 4 | SAM 3.1 uses `POST /v1/responses` with `input_text` plus `input_image` or `input_video` (MP4/MOV) | **Confirmed** | Video must be an MP4 or MOV container with H.264, H.265 or MPEG-4 video. VP9 and WebM are rejected [sam-overview][sam-seg]. Send one noun phrase per request [sam-seg]. |
| 5 | SAM returns one box and one mask per object | **Confirmed, with a correction to the shape** | You get one box and one mask per object **per frame**, but as special-token **text** in `output_text`, not JSON. Boxes are source pixels in xyxy format with inclusive x2/y2. Masks are base85-encoded box-sized rasters. Details in section 4 [sam-read]. |
| 6 | Model ID `sam-3-1` or `sam-3.1`? | **`sam-3.1`** | Every docs page, code sample, the rate-limit table and Context7 use `sam-3.1` [models][pricing][sam-overview][c7]. `sam-3-1` appears only in the marketing price tables on [card-sam] and [product] (and in the URL slug). Check with `GET /v1/models` at startup. |
| 7 | For video, Muse Spark takes an MP4 uploaded through the Files API (`purpose="user_data"`) or a URL | **Confirmed** | Upload with `purpose="user_data"`, then reference the file through `input_file`/`input_video` with `file_id`. Alternatively, send `input_video.video_url` as a public URL or a base64 data URL [video][files]. Muse Spark accepts only `video/mp4`; SAM also takes MOV [files][sam-seg]. |
| 8 | "Muse Spark 1.3" | **Confirmed; exact ID `muse-spark-1.3`** | Other IDs: `muse-spark-1.3-contributor`, `muse-spark-1.2`, `muse-spark-1.2-contributor`, `muse-spark-1.1` [models][pricing]. 1.3 is the latest and is "Recommended for new work" [models]. |
| 9 | Open weights: use `meta-models/muse-spark-open-1026` instead of `meta-models/muse-spark-open` | **Not found** | `-1026` does not appear in the docs, on the Hugging Face org [hf], on the official hackathon page [hackathon], on the organizer page [cv-hackathon] or in web search. The docs give `meta-models/muse-spark-open` as the model string on Together AI, Baseten, Groq and Nebius, and `accounts/fireworks/models/muse-spark-open` on Fireworks [spark-open-deploy]. Follow the hackathon instruction if it came through an official channel. Either way it is **not** a Model API ID. |

---

## 1. Summary table

| Model | Exact model ID | Endpoint(s) | Input → output | Context / limits | Price (pay-as-you-go) |
|---|---|---|---|---|---|
| Muse Spark 1.3 (Standard) | `muse-spark-1.3` | `POST /v1/responses` (recommended), `POST /v1/chat/completions`, `POST /v1/messages` (Anthropic format) [protocols][models] | Text, image, video (MP4), audio, PDF → text. Audio on 1.3 is "not fully supported"; use 1.2 for audio [models] | 1,048,576-token context [models]. Up to 50 images per request [img]. 50 MB per inline file, 1 GiB per uploaded file [files]. Rate limit 3,000 RPM and 4,000,000 TPM per team [pricing]. All reasoning levels including `max` [reasoning] | $1.25/M input, $0.15/M cached input, $4.25/M output [pricing] |
| Muse Spark 1.3 Contributor | `muse-spark-1.3-contributor` | Same as above | Same as above | Same context. 150 RPM and 3,000,000 TPM. No `max` reasoning [pricing][reasoning] | $0.10/M input, $0.002/M cached, $0.20/M output. Your content may be used for training [pricing] |
| Muse Spark 1.2 / 1.2 Contributor | `muse-spark-1.2` / `muse-spark-1.2-contributor` | Same as above | Same as above (1.2 is the recommended version for audio) | 1M context. 3,000 RPM / 4M TPM (Contributor: 150 RPM / 3M TPM) [pricing] | Same rates as 1.3 [pricing] |
| Muse Spark 1.1 | `muse-spark-1.1` | Same as above | Same as above | 1M context. 3,000 RPM / 4M TPM. Standard mode only [pricing] | Same rates as 1.3 Standard [pricing] |
| SAM 3.1 | `sam-3.1` | `POST /v1/responses` only, plus `POST /v1/files` for clips [models][overview] | A short noun phrase (or box/point prompt tokens) plus **one** image or **one** video → boxes and masks as special-token text [sam-overview] | Up to 15,000 frames (about 10 minutes) per video request. Up to 16 tracked objects per frame in video; images return every match. Up to 16 prompted objects [sam-seg]. 3,000 RPM, no TPM limit [pricing] | $2.50 per 1,000 images; $0.20 per 1,000 video frames, with a minimum of 50 frames per video request [pricing] |
| (FYI) Muse Wonder | `muse-wonder-1.0` | Same endpoints as Spark | Same modalities as Spark | 1M context. 3,000 RPM / 4M TPM. Preview [models][pricing] | $4.00/M input, $0.20/M cached, $20.00/M output [pricing] |

The maximum output for `muse-spark-1.3` is not given on the Models page. The quickstart's OpenCode config sets `"limit": {"context": 1048576, "output": 131072}` [quickstart], and asking for more than the configured maximum returns HTTP 400 [chat]. `GET /v1/models` lists the models enabled for your team, newest first by `created` [models][models-schemas].

---

## 2. Authentication, base URL, SDKs

- **Base URL:** `https://api.meta.ai/v1`. **Auth header:** `Authorization: Bearer $MODEL_API_KEY` [apiref].
- **Getting a key:** Dashboard → **API keys** → **Create API key**. The key is shown only once. It has the form `LLM_1607358788850350_nx9.....LJY` [auth].
- **Scope:** keys belong to a team, and all keys in a team share the same rate limits [auth][pricing]. A leaked key can also read the team's uploaded files [auth].
- **Health check:** `GET /v1/status` is unauthenticated and reports overall status and per-model availability [status].

**OpenAI SDK compatibility** (`pip install openai`) [sdks]:

| Endpoint | OpenAI SDK call | Notes |
|---|---|---|
| `POST /v1/responses` | `client.responses.create(...)`, `client.responses.stream(...)` | Recommended for agents. Carries reasoning across turns [protocols][responses] |
| `GET /v1/responses/{id}`, `POST .../cancel`, `DELETE .../{id}` | `client.responses.retrieve(id)`, `client.responses.cancel(id)` | Responses are stored by default (`store: true`) [responses] |
| `POST /v1/responses/input_tokens` | `client.post("/responses/input_tokens", body={...}, cast_to=object)` | Pre-flight token count; this raw-post pattern is from the cookbook [cb-vision][tokens] |
| `POST /v1/chat/completions` | `client.chat.completions.create(...)`, `client.beta.chat.completions.parse(...)` | Does **not** carry reasoning across turns [chat][so] |
| `POST/GET/DELETE /v1/files...` | `client.files.create/list/retrieve/delete` | Also `GET /v1/files/{id}/content` [files][apiref] |
| `GET /v1/models` | `client.models.list()` | [models] |
| `POST /v1/messages` | Anthropic SDK: `Anthropic(base_url="https://api.meta.ai", auth_token=...)` | `content` starts with a `redacted_thinking` block [sdks] |

- **Official Meta SDK:** there is none for the LLM API. The docs say "Meta Model API doesn't need a client of its own" [sdks]. Meta does publish **SAM output parsers**:
  - **Python:** `pip install meta-sam-parser`, imported as `meta_sam_parser`. Requires Python ≥ 3.10, has no dependencies, and is typed. The latest release on PyPI is 0.1.0 (2026-10-06) [pypi-parser].
  - **npm:** `@meta-sam/parser`, `@meta-sam/graphics`, `@meta-sam/video`, `@meta-sam/react` [sam-libs].
- **Other clients:** LangChain, LlamaIndex, the Vercel AI SDK and LiteLLM all work. With LiteLLM, prefix the model as `openai/muse-spark-1.3` [sdks].
- **Endpoints that do not exist:** the API reference has no embeddings or batch endpoints. Its resources are Responses, Chat Completions, Messages, Files, Models, Status, Images and Voice [apiref][llms]. `purpose=batch` exists for file uploads, but no batch endpoint is documented [files].
- **OpenAI features that do not work:**
  - `tool_choice` accepts only `"auto"`; anything else returns 400 [tools].
  - Only `n=1` is supported. `stop`, `logit_bias`, `verbosity`, `prediction`, `modalities`, `audio` and `logprobs` are rejected [chat][reasoning].
  - `truncation: "auto"` is rejected [responses].
  - Muse Spark is tuned for `temperature=1.0` and `top_p=1.0`, so leave sampling at the defaults [responses][chat].
- **SDK version:** the cookbook pins only `openai>=1.0` [gh-sam-api]. Use a recent release: `responses.stream`, `responses.parse` and `files.create(expires_after=...)` need newer SDKs **(inferred)**.

```python
import os
from openai import OpenAI

client = OpenAI(
    base_url="https://api.meta.ai/v1",
    api_key=os.environ["MODEL_API_KEY"],  # the SDK does not read MODEL_API_KEY by itself [sdks]
    max_retries=0,  # (inferred advice) the SDK retries 429 and >=500 twice by default [openai-readme];
                    # Meta says not to blindly retry 504 [errors], so own the retry policy (section 8)
)
```

---

## 3. Muse Spark (`muse-spark-1.3`)

### 3a. Image input

- **Responses API.** Add an `{"type": "input_image", "image_url": "<https URL or data:image/...;base64,...>"}` block to a **user** message, or use `{"type": "input_image", "file_id": "file-..."}`. Alternatively use `input_file` with `file_id` or `file_url` [img].
  - The optional `detail` field takes `low`, `high`, `auto` or `original` and defaults to `auto` [resp-schemas]. Its effect on Muse Spark is not documented.
- **Chat Completions.** Use `{"type": "image_url", "image_url": {"url": "..."}}`. The value is an object here, not a plain string [img].
- **Formats:** `image/png`, `image/jpeg` (alias `image/jpg`), `image/gif`, `image/webp`, `image/x-icon` [img][files].
- **Size and count limits:**
  - 50 MB per inline image, or 1 GiB through the Files API [img].
  - At most **50 images per request**. More returns HTTP 400 [img]. The cookbook calls 50 "about … a model guideline" [cb-vision].
  - **The maximum resolution is not documented.** "The model may resize images" [img].
- **Roles:** only include images in `user` messages [img]. The cookbook says putting one in a `developer` or `system` message returns 400 [cb-vision].
- **Token cost:** it scales with resolution. A ~1280 px image costs roughly **1,300–1,500 tokens**, and every request carries about 110 tokens of fixed overhead. Use `POST /v1/responses/input_tokens` for exact counts [img].
- **Errors:** an undecodable image returns 400 [img]. **A URL the server cannot fetch** (blocked by `robots.txt`, unreachable, denied by fetch policy) also returns 400 [errors]. Download webcam frames yourself and send data URLs **(inferred advice)**.
- **Coordinates:** if you ask Muse Spark for coordinates, it uses a normalized 0–1000 grid with the origin at the top left. Values can slightly exceed the range, so clamp them [img].

```python
import base64, json

def jpg_data_url(path: str) -> str:
    with open(path, "rb") as f:
        return "data:image/jpeg;base64," + base64.b64encode(f.read()).decode()

OBS_SCHEMA = {  # strict subset: additionalProperties false + every key required [so]
    "type": "object",
    "properties": {
        "activity": {"type": "string",
                     "enum": ["none", "steam", "ash_plume", "incandescence", "lava_fountain", "unclear"]},
        "confidence": {"type": "number"},
        "sam_prompts": {"type": "array", "items": {"type": "string"}},
        "summary_es": {"type": "string"},
        "summary_en": {"type": "string"},
    },
    "required": ["activity", "confidence", "sam_prompts", "summary_es", "summary_en"],
    "additionalProperties": False,
}

resp = client.responses.create(
    model="muse-spark-1.3",
    reasoning={"effort": "low"},  # [reasoning]
    max_output_tokens=4000,       # covers reasoning + visible output [reasoning]
    instructions="You analyse volcano webcam frames. Report only what is visible.",  # [responses]
    input=[{
        "role": "user",
        "content": [
            {"type": "input_text", "text": "Classify the visible volcanic activity."},
            {"type": "input_image", "image_url": jpg_data_url("cam.jpg")},
        ],
    }],
    text={"format": {"type": "json_schema", "name": "webcam_observation",
                     "schema": OBS_SCHEMA, "strict": True}},  # shape from [resp-schemas]
)
obs = json.loads(resp.output_text)
usage = resp.usage.model_dump()  # log it: see section 7
```

### 3b. Video input

- **Recommended path** [video]:
  1. Upload the clip with `POST /v1/files` and `purpose="user_data"`.
  2. Reference it from a Responses request as `{"type": "input_file", "file_id": ...}`. `{"type": "input_video", "file_id": ...}` also works.
- **By URL:** `{"type": "input_video", "video_url": "https://.../clip.mp4"}` with a public URL, or a base64 data URL up to the 50 MB inline limit [video][files].
- **Chat Completions:** use a `video_url` content part, `{"type": "video_url", "video_url": {"url": ..., "fps": <optional>}}` [video][chat-schemas].
- **Format:** `video/mp4` only. Muse Spark reads frames **and** transcribes embedded audio. Videos without audio are fine [video][files].
- **Undocumented limits:** maximum duration, frame sampling, resolution and tokens per second. The `fps` field on `input_video` (Responses) and `video_url` (Chat) is in the schema but has no description [resp-schemas][chat-schemas]. Measure token cost with `POST /v1/responses/input_tokens`, which accounts for media [tokens].
  - Rough data point from a **different deployment** (Muse Spark Open on Baseten): "samples at most 96 frames per clip: a 720p clip costs about 144 tokens per second, capped at ~6.9K tokens" [spark-open-deploy]. Treat this as an order of magnitude only **(inferred)**.
  - The open-weight prompting guide recommends clips longer than a few seconds and at least 448 px on the short side [spark-open-prompting]. It probably applies to the hosted model too **(inferred)**.
- **Retention:** uploaded files **never expire** unless you set `expires_after` (3600–2,592,000 s, anchored on `created_at`). They count toward a 100 GiB team storage cap [files]. See section 5.

```python
with open("timelapse.mp4", "rb") as f:
    up = client.files.create(file=f, purpose="user_data",
                             expires_after={"anchor": "created_at", "seconds": 86400})  # [files]
resp = client.responses.create(
    model="muse-spark-1.3",
    max_output_tokens=4000,
    input=[{"role": "user", "content": [
        {"type": "input_text", "text": "Describe how the plume evolves in this timelapse."},
        {"type": "input_file", "file_id": up.id},  # or {"type": "input_video", "file_id": up.id}
    ]}],
)
print(resp.output_text)
client.files.delete(up.id)  # frees team storage [files]
```

### 3c. Tool / function calling

**Responses tool format.** Tools are flat objects: `{"type": "function", "name", "description", "parameters", "strict"?}` [tools].

- When the model calls a tool, `output` contains `function_call` items with `name`, `arguments` (a JSON string), `call_id` and `status`.
- Reply with `{"type": "function_call_output", "call_id", "output"}` items and chain with `previous_response_id` [tools].
- The server reconstructs history from `previous_response_id`, but **not** request-level settings. Resend `instructions`, `tools` and `reasoning` on every turn [responses].
- The alternative is stateless replay: send `store: false` with `include: ["reasoning.encrypted_content"]` and replay `reasoning` items yourself. This cannot be combined with `previous_response_id`, which returns 400 [responses].

**Parallel calls.** Supported. `parallel_tool_calls` defaults to `true`; set it to `false` for one call per turn. With `previous_response_id`, the order of `function_call_output` items is not enforced [tools].

**Constraints:**
- `tool_choice` accepts only `"auto"`, so the model can always answer with plain text [tools].
- Function names must match `^[a-zA-Z0-9_.-]+$` with at most one dot.
- `call_id` must be 1–64 characters.
- Arguments are **not guaranteed** to validate against your schema, so validate them yourself.
- `max_tool_calls` limits only built-in tools.
- `custom` (freeform-text) tools exist only on the Responses API [tools].

**Built-in tools:** `web_search` costs $2.50 per 1,000 queries [pricing]. `tool_search` cannot be combined with a JSON-schema `text.format` [toolsearch].

**Streaming:** tool arguments arrive as `response.function_call_arguments.delta` and finish with `.done` events [tools].

**Manual replay:** if you build history yourself, intermediate assistant text before a `function_call` must carry `phase: "commentary"` [responses].

```python
import json

TOOLS = [{
    "type": "function",
    "name": "segment_latest_frame",
    "description": "Run SAM 3.1 on a camera's latest frame for ONE noun phrase; returns objects and mask areas.",
    "parameters": {"type": "object",
                   "properties": {"camera_id": {"type": "string"}, "phrase": {"type": "string"}},
                   "required": ["camera_id", "phrase"], "additionalProperties": False},
}]
IMPLS = {"segment_latest_frame": lambda camera_id, phrase: {"objects": []}}  # your code

def run_agent(task: str, max_turns: int = 8):
    common = dict(model="muse-spark-1.3", tools=TOOLS, reasoning={"effort": "medium"},
                  instructions="You are Vigía Andino, a volcano-watch agent.")
    resp = client.responses.create(input=task, **common)
    for _ in range(max_turns):
        calls = [it for it in resp.output if it.type == "function_call"]
        if not calls:
            return resp                            # final answer: resp.output_text
        outputs = []
        for c in calls:                            # can be several per turn (parallel)
            args = json.loads(c.arguments)         # validate before use [tools]
            outputs.append({"type": "function_call_output", "call_id": c.call_id,
                            "output": json.dumps(IMPLS[c.name](**args))})
        resp = client.responses.create(input=outputs, previous_response_id=resp.id, **common)
    raise RuntimeError("agent exceeded max_turns")
```

### 3d. Structured outputs (JSON schema)

**Where the parameter goes:**
- **Responses:** `text={"format": {"type": "json_schema", "name": <a-zA-Z0-9_- up to 64 chars>, "schema": {...}, "strict": bool, "description"?}}` [resp-schemas][so].
- **Chat Completions:** `response_format={"type": "json_schema", "json_schema": {"name", "schema", "strict"}}` [so].
- `{"type": "json_object"}` is the older JSON mode [resp-schemas].
- The docs disagree on what `response_format` does on Responses. One page says it is ignored, another says it returns 400. Either way, don't use it there. `text.format` sent to Chat Completions returns 400 [chat][cb-so].
- The guides only show Chat Completions examples. The Responses shape above comes from the schema reference.

**Guarantee:** decoding is constrained, so output always conforms to the schema. `strict: false` behaves like `true` for output conformance. `strict: true` additionally validates your schema against the strict subset: plain object root, `additionalProperties: false` everywhere, every property listed in `required`, no `allOf`/`oneOf` [so].

**Schema limits:**
- 10 nesting levels.
- 5,000 properties.
- 120,000 characters of names and enum values.
- 1,000 enum values.
- 200,000 nodes after `$ref` expansion.
- Recursive schemas return 400 [so].

**Pydantic helpers:**
- `client.beta.chat.completions.parse(response_format=Model)` is documented by Meta [so].
- `client.responses.parse(text_format=Model)`, read via `.output_parsed`, is an OpenAI SDK helper [openai-helpers]. Not shown in Meta docs; expected to work because it emits `text.format` **(inferred)**.

**Combining with tools:** combining `tools` and `text.format` in one request is not explicitly documented. Only `tool_search` with `json_schema` is forbidden [toolsearch], so it is probably allowed **(inferred)**.

### 3e. Reasoning controls

- **Levels:** `minimal`, `low`, `medium`, `high`, `xhigh`, `max`.
  - `max` works only on `muse-spark-1.3` and `muse-wonder-1.0`, not on `-contributor` models.
  - `none` returns 400 on Muse Spark.
  - If you omit the parameter, the model chooses a level [reasoning].
- **Where to set it:** `reasoning={"effort": ...}` on Responses, top-level `reasoning_effort` on Chat [reasoning].
- **Token budget and billing:** reasoning tokens count toward `max_output_tokens` (minimum 16) and are billed as output. They are reported in `usage.output_tokens_details.reasoning_tokens` [reasoning][responses]. Give the budget room: at least 4,000 is recommended for transcription-like tasks [video].
- **Summaries:** `reasoning.summary` = `auto`, `concise` or `detailed` (Responses only). Not guaranteed to appear [reasoning].
- **Not exposed:** raw reasoning text is never returned, and logprobs are unsupported [reasoning].

### 3f. Streaming

- **Event sequence:** with `stream=True`, Responses emits `response.created`, `response.in_progress`, `response.output_item.added/done`, `response.content_part.added/done`, `response.output_text.delta` and `response.completed`.
- **Failure events:** a failure ends the stream with `response.failed` or an `error` event, and an early stop ends it with `response.incomplete` [responses][errors].
- **Usage:**
  - Responses: the final streamed response always includes `usage`.
  - Chat: pass `stream_options={"include_usage": True}` [responses][cb-stream].
- **Timeouts:** non-streaming requests have a server-side time limit and return **504 `gateway_timeout`** when they exceed it. Streaming requests are exempt once the first event arrives. For long jobs use `background: true`, which:
  - can't be combined with `stream`,
  - caps the request body at 1 MiB,
  - is limited to 600 starts per minute [responses][pricing].
- **Python SDK pattern:** `with client.responses.stream(...) as s: for ev in s: ...; final = s.get_final_response()` [responses][openai-helpers].

---

## 4. SAM 3.1 (`sam-3.1`)

### Request schema

There is one `POST /v1/responses` call per **(concept, media item)** pair [sam-seg][sam-overview]:

```json
{
  "model": "sam-3.1",
  "input": [
    {"type": "message", "role": "user", "content": [
      {"type": "input_text", "text": "volcanic plume"},
      {"type": "input_image", "image_url": "https://... or data:image/jpeg;base64,..."}
    ]}
  ],
  "stream": true,
  "metadata": {"include_confidence": "true", "mask_encoding": "one_bit"}
}
```

**Video variant.** Replace the media part with `{"type": "input_video", "video_url": "https://.../clip.mp4"}` (a public URL or base64 data URL) or `{"type": "input_video", "file_id": "file-..."}` [sam-seg]. Image input is documented only through `image_url`; `file_id` for SAM images is not documented [sam-seg].

**Text prompts.** One concept per request, and there is **no multi-concept syntax**:
- `"a, b"`, `"a; b"` and `"a + b"` return zero matches.
- `"and"`, a newline, or a second `input_text` segments only one of the concepts [sam-seg].
- To segment N concepts, send N requests [sam-seg][cb-sam-basics].

**Prompt rules** [sam-seg]:
- Use a short, concrete noun phrase. Commands and questions often return nothing.
- Attributes narrow the match.
- Plural, case and punctuation are ignored.
- Avoid negation, OR and spatial phrases. Filter by box position in your own code instead.

**Our concept list.** "incandescence" names a phenomenon, not an object, and may match poorly. Try variants such as "glowing lava" or "lava" in the SAM Playground before committing **(inferred)**. Meta suggests this pairing: let Muse Spark decide what to segment and SAM produce the geometry [mediaseg]. The Playground is linked from [card-sam].

**Box and point prompts (alternative to a phrase).**
- Format: `<Nf>id<|box;x1=..;y1=..;x2=..;y2=..;w=W;h=H|>` or `<|point;x=..;y=..;w=W;h=H|>`. A `-` before a point makes it negative.
- Use up to 16 objects, with media-pixel coordinates.
- Never mix them with a phrase [sam-seg].
- `meta_sam_parser.build_object_prompt` builds the text [sam-libs].

### Parameters

All parameters go in `metadata`, and the **values must be strings** [sam-seg]:

| Key | Values | Effect |
|---|---|---|
| `include_confidence` | `"true"` / `"false"` | Adds `c` (0–1) to each box and mask, per frame. Requires parser ≥ 0.0.6 (Python) or ≥ 0.0.13 (TS) [sam-seg] |
| `mask_encoding` | `"lossless"` (default, marker `~`) / `"one_bit"` (marker `!`, several times smaller) | Box/point prompts always return `one_bit` [sam-seg] |
| `propagation_direction` | `"both"` (default) / `"forward"` / `"backward"` | Video with box/point prompts only. Measured from the earliest prompted frame. Tracking fewer frames costs less [sam-seg] |

**Parameters that do not exist:** there are **no** detection threshold, max-objects or frame-sampling parameters. Filter on `c` yourself. The schema's `input_video.fps` is undocumented [resp-schemas].

**Streaming:** streaming is recommended for video, but not required. A non-streaming call returns the same text in one response [sam-seg].

**Determinism:** results can vary slightly between runs [sam-seg].

### Response schema

Output arrives in the `output_text` lane as **special-token text, one line per frame**. For video, each frame is one `response.output_text.delta`, and the stream ends with `response.completed`. **Zero matches is not an error**: the response is an empty `output_text` [sam-read][sam-overview].

```text
line   ::= "<" N "f>" record ("," record)*
record ::= OBJECT_ID "<|box;x1=..;y1=..;x2=..;y2=..;w=<frameW>;h=<frameH>[;c=<conf>]|>"
                     "<|mask;x=0;y=0[;c=<conf>];data=<H>,<W>,<enc><payload>|>"
```

[sam-read]

**Boxes:**
- Coordinates are **source pixels**, x/y corners (`x1,y1` top-left, `x2,y2` bottom-right), **inclusive**.
- `w`/`h` give the source frame size, repeated on every record. The size is as displayed, after EXIF or rotation flags are applied [sam-read][sam-seg].
- The parser converts boxes to half-open coordinates: `right = x2+1`, `bottom = y2+1` [gh-protocol].

**Masks:**
- `data=H,W,…` gives the raster's **height, width**. `x=0;y=0` is a literal [sam-read].
- The mask raster covers the object's **box**: the normalized mask "carries the same half-open box as its bounds" [gh-protocol][pypi-parser]. So H = y2−y1+1 and W = x2−x1+1, which every docs example confirms. To build a full-frame mask, paste the raster at (x1, y1). dev.meta.ai itself says only "smaller than the frame".
  - **Correction, measured 2026-10-27:** that holds only for small boxes. Large masks come at reduced resolution: a 1081×680 box on a 2048×1152 image came with a 1024×644 raster (long side 1024, aspect kept). The parser keeps the raster's own size, so scale it to the box before pasting; `vigia/meta/sam.py` does (nearest neighbour). Mask edges of large objects are therefore only accurate to about box/raster pixels.
- The payload is **base85, not base64**, with a custom 85-character alphabet and an arithmetic-coded body. It is not COCO RLE, PNG or polygons [sam-read][gh-protocol].
- Decode it with `decode_mask_to_raster` (row-major 0/1), `decode_mask_to_rle` (COCO compressed RLE, `size=[h,w]`, column-major) or `decode_mask_to_svg_path` [sam-libs][pypi-parser].

**Scores:** `c` appears only with `include_confidence`. Box and mask carry the same value, which can differ per frame [sam-seg].

**Object IDs:**
- A bare integer, **stable across frames within one response**.
- Not dense or 0-based: a line can carry `0, 2`.
- Don't rely on an ID across an object's exit and re-entry, full occlusion, or very long clips [sam-read].

**Video ordering** [sam-read]:
- Frames with no objects emit **no line**, so frame indices can skip.
- Concept prompts arrive in ascending frame order.
- Box/point prompts with `both` arrive forward first, then backward. Always key results by `<Nf>`.

**Usage fields:** `usage.images_processed` (image) or `usage.video_frames_processed` (video, already reflecting the 50-frame minimum) [resp-schemas][pricing].

**Documented examples:**

```text
# image, prompt "button", 537x561 source (payloads elided) [sam-read]
<0f>0<|box;x1=353;y1=382;x2=453;y2=427;w=537;h=561|><|mask;x=0;y=0;data=46,101,~...|>,1<|box;x1=260;y1=382;x2=340;y2=427;w=537;h=561|><|mask;x=0;y=0;data=46,81,~...|>,2<|box;x1=516;y1=117;x2=536;y2=150;w=537;h=561|><|mask;x=0;y=0;data=34,21,~...|>
# video frame 0, 320x334 source, full lossless payloads [sam-read]
<0f>0<|box;x1=211;y1=228;x2=270;y2=254;w=320;h=334|><|mask;x=0;y=0;data=27,60,~!!!!M!0c[0o91w?q1!pIH4pPRVp2B3'7`e.ioeAf6-k/#Xd8%dX9x(|>,1<|box;x1=155;y1=228;x2=202;y2=254;w=320;h=334|><|mask;x=0;y=0;data=27,48,~!!!!J!0c[q=Pj_zs=*4C4(/./x#:/`S_GnD`=o3?X{emCgO$y@|>
# with include_confidence [sam-seg]
<0f>1<|box;x1=444;y1=625;x2=679;y2=850;w=1800;h=1200;c=0.9609375|><|mask;x=0;y=0;c=0.9609375;data=226,236,!...|>
```

Parsed summary from a real `sam-3.1` run, as produced by the cookbook [cb-sam-basics]:
`{"object_id": "0", "frame": null, "left": 751, "top": 290, "right": 925, "bottom": 493}` and the mask `{"encoding": "lossless", "width": 174, "height": 203, "foreground_pixels": 10063}`.

The docs publish **no full JSON response envelope** for SAM. Assembled from the Responses schema **(inferred)**:
`{"id": "resp_…", "object": "response", "status": "completed", "model": "sam-3.1", "output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "<0f>0<|box;…|><|mask;…|>"}]}], "usage": {"input_tokens": …, "output_tokens": …, "total_tokens": …, "images_processed": 1}}`.

### Limits

[sam-seg]:
- **Video formats:** MP4/MOV with H.264, H.265 or MPEG-4. VP9 and WebM are rejected.
- **Video length:** up to **15,000 frames (about 10 minutes)** per request.
- **Objects:** images return every match. Video tracks **up to 16 objects per frame**. Box/point prompts allow up to 16 objects.
- **Not documented for SAM:** image resolution, video resolution and fps caps. The generic file limits (50 MB inline, 1 GiB upload) presumably apply **(inferred)**.

**Upload behaviour:** uploads are synchronous. An MP4 whose `moov` atom sits at the end is remuxed losslessly; avoid that by exporting with `ffmpeg -i in.mp4 -c copy -movflags +faststart out.mp4` [sam-seg].

**Frame sampling:** the cookbooks show every source frame being segmented (240 frames for a 10 s clip). Pre-downsample with ffmpeg if you want fewer billed frames [cb-sticker][cb-sam-basics] **(inferred)**.

**Errors:** prompt and metadata errors return 400 with a descriptive message (for example `invalid prompt: object prompts cannot be combined with a phrase`) and are permanent. An unknown model returns 404 `model_not_found` [sam-seg].

### Python examples

Both examples use the OpenAI SDK plus `meta_sam_parser`'s documented direct parser (`create_parser` / `push` / `finish`) [pypi-parser].

```python
from meta_sam_parser import (CompletedOutcome, decode_mask_to_raster,
                             image_segmentation_format, video_segmentation_format)

def sam_image(image_url: str, phrase: str):
    resp = client.responses.create(
        model="sam-3.1",
        input=[{"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": phrase},              # ONE noun phrase
            {"type": "input_image", "image_url": image_url}]}],  # https URL or data: URL
        metadata={"include_confidence": "true", "mask_encoding": "one_bit"},
    )
    parser = image_segmentation_format().create_parser()
    list(parser.push(resp.output_text or ""))   # "" == zero matches (valid)
    result = parser.finish(CompletedOutcome()).result
    objs = {}
    for rec in result.records:                  # box record, then its mask record
        o = objs.setdefault(rec.object_id, {})
        if rec.kind == "box":
            o.update(box=(rec.left, rec.top, rec.right, rec.bottom), conf=rec.confidence)
        elif rec.kind == "mask":
            o["area_px"] = sum(decode_mask_to_raster(rec.mask))  # raster is box-sized
    return objs, resp.usage.model_dump()       # usage["images_processed"]

def sam_video(file_id: str, phrase: str):
    parser = video_segmentation_format().create_parser()
    with client.responses.stream(
        model="sam-3.1",
        input=[{"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": phrase},
            {"type": "input_video", "file_id": file_id}]}],
        metadata={"mask_encoding": "one_bit"},
    ) as stream:
        for ev in stream:
            if ev.type == "response.output_text.delta":  # one frame line per delta
                list(parser.push(ev.delta))
        final = stream.get_final_response()               # raises if not completed
    result = parser.finish(CompletedOutcome()).result
    tracks = {}
    for rec in result.records:
        if rec.kind == "box":
            tracks.setdefault(rec.object_id, []).append(
                (rec.frame.frame_index, rec.left, rec.top, rec.right, rec.bottom))
    return tracks, final.usage.model_dump()               # usage["video_frames_processed"]
```

The official async alternative (in the cookbook's `sam_api.py`) is `parse_responses_stream(events, video_segmentation_format()).final_result()` with `AsyncOpenAI` [gh-sam-api].

The live SAM stream does **not** emit `response.output_text.done`; it finalizes the lane with `response.content_part.done`. The parser handles this, but hand-written parsers must too [pypi-parser][gh-sam-api].

Whether the SDK's `usage.model_dump()` keeps the non-OpenAI fields (`images_processed`, `video_frames_processed`) is **(inferred)**: the OpenAI SDK models allow extra fields. Verify on the first real call.

---

## 5. Files API

- **Endpoints** [apiref][files]:
  - `POST /v1/files` (multipart; synchronous, so `200` means the file is usable) [sam-seg]
  - `GET /v1/files` (`purpose`, `limit` 1–10,000 with default 10,000, `order` asc/desc, `after` cursor) [files-list]
  - `GET /v1/files/{id}`
  - `GET /v1/files/{id}/content`
  - `DELETE /v1/files/{id}`
- **Purposes:** the upload endpoint accepts only `user_data` (for inference) and `batch` (JSONL). The file object's enum also lists `fine-tune` and `evals` [files-schemas].
- **IDs:** `file-<numeric>`, for example `file-842549258569145` [files-schemas][files].
- **Upload tip:** send `purpose` and `expires_after` before the `file` part for lower latency [files].
- **Size limits:**
  - 1 GiB (1,073,741,824 bytes) per uploaded file.
  - 50 MB (50,000,000 bytes) per inline file (`file_data`, `file_url`, data URLs).
  - **100 GiB team storage**. When it is full, uploads fail with 400 [files].
- **Retention:**
  - Files **do not expire** by default.
  - Optional `expires_after={"anchor": "created_at", "seconds": 3600..2592000}` (1 hour to 30 days). Then `expires_at = created_at + seconds` [files][files-schemas].
  - Delete files to free space [files].
- **Referencing a file:**
  - **Muse Spark:** `{"type": "input_file", "file_id": ...}` for images, videos and PDFs, or the typed `input_image`/`input_video` with `file_id` [files][img][video].
  - **SAM:** `{"type": "input_video", "file_id": ...}` for clips you segment more than once [sam-seg].
- **Accepted MIME types:**
  - Images: png, jpeg, gif, webp, x-icon.
  - Video: `video/mp4`.
  - Audio: mp3, wav.
  - Documents and text: `application/pdf` (first 100 pages of text, first 50 page images), `text/plain`, `application/json`, `application/jsonl` [files].
  - SAM additionally takes MOV [sam-seg].
- **Error quirk:** a bad `order` on `GET /v1/files` returns a **plain-text** 400, not JSON [errors].

---

## 6. Pricing

Prices come from [pricing] (https://dev.meta.ai/docs/pricing-rate-limits), cross-checked on [product], [card-spark] and [card-sam].

| Model | Unit | Standard | Contributor |
|---|---|---|---|
| `muse-spark-1.3` / `1.2` / `1.1` | input / cached input / output, per 1M tokens | $1.25 / $0.15 / $4.25 | $0.10 / $0.002 / $0.20 (1.3 and 1.2 only) |
| `sam-3.1` | image segmentation | $2.50 per 1,000 images | n/a |
| `sam-3.1` | video segmentation | $0.20 per 1,000 frames; **minimum 50 frames per video request** | n/a |
| `muse-wonder-1.0` | per 1M tokens | $4.00 / $0.20 / $20.00 | not available |
| `web_search` tool | per 1,000 queries | $2.50, on top of tokens | |
| `muse-image-1.0` | per image | $0.01 | |
| `muse-voice-transcribe-1.0` | per hour of audio | $0.18 | |

Billing rules [pricing][caching]:
- No long-context premium.
- Reasoning tokens are billed at the output rate [reasoning].
- `cached_tokens` is a **subset** of `input_tokens`, billed at the cached rate.
- SAM costs the same streaming and non-streaming.
- Meta's injected system scaffolding is not billed and is excluded from `usage`.

### Worked estimates

These are **(inferred)** arithmetic on the documented prices.

**(a) One Muse Spark 1.3 call with one 1280×720 image and ~500 output tokens.**
- Input ≈ 2,000 tokens: up to ~1,500 for the image (documented as "~1280 px ≈ 1,300–1,500"), ~110 fixed overhead, and an assumed ~400 tokens of instructions and question.
- Cost: 2,000 × $1.25/M = $0.0025, plus 500 × $4.25/M = $0.0021, so **≈ $0.0046 per call** (≈ $4.60 per 1,000 calls).
- Caveat: those 500 output tokens **include reasoning tokens**. With 1,500 reasoning plus 500 visible tokens (2,000 output), the call costs ≈ **$0.011**.
- Contributor variant: ≈ **$0.0003** (500 output) to $0.0006 (2,000 output).
- Measure real image tokens with `POST /v1/responses/input_tokens`.

**(b) One SAM 3.1 image call.**
- $2.50 / 1,000 = **$0.0025 per request** (one image, one concept).
- Our 5 concepts on one frame make 5 requests, so **$0.0125 per frame**.

**(c) One SAM 3.1 call on a 20 s 720p video.**
- Billing is per frame and the docs list no resolution factor, so 720p does not matter for price.
- At 30 fps: 600 frames × $0.0002 = **$0.12 per concept** ($0.60 for 5 concepts).
- At 25 fps: $0.10. At 10 fps (ffmpeg-downsampled): $0.04. At ≤2.5 fps (≤50 frames): billed as 50 frames, **$0.01**.
- **Missing from the docs:** whether the server samples frames (the undocumented `input_video.fps`). Log `usage.video_frames_processed` to see the real count.
- **Cost insight:** per frame, video ($0.0002) is 12.5× cheaper than image calls ($0.0025). Stitching ≥50 webcam snapshots into one MP4 costs $0.01 per concept instead of $0.125, and yields track IDs. Tracking quality across sparse snapshots is unknown, so test it.

**Muse Spark on a video:** the token cost is undocumented for Model API. Measure it with `input_tokens`. The Baseten open-weights data point (~144 tokens/s at 720p) would put a 20 s clip at ≈ 2,900 tokens ≈ $0.0036 input **(inferred, different deployment)**.

---

## 7. Rate limits, quotas, usage reporting

**Limits are per team, not per key, and separate for each model** [pricing]:

| Model | RPM | TPM | Other |
|---|---|---|---|
| `muse-spark-1.3` / `1.2` / `1.1` | 3,000 | 4,000,000 | |
| `muse-spark-1.3-contributor` / `1.2-contributor` | 150 | 3,000,000 | |
| `sam-3.1` | 3,000 | none | |
| `muse-wonder-1.0` | 3,000 | 4,000,000 | |
| Background responses | 600 starts per minute | | in addition to the limits above |

- **Viewing limits:** the dashboard's **Limits** page shows your team's limits, and the **Usage** page shows tokens and requests per day by model, with Playground usage included [help-ratelimits][help-usage].
- **Tiers:** no tiers or limit-increase process are described in the pages read.
- **No hard spend cap.** You can set a monthly **spend-limit email alert**, and charges apply at a payment threshold or on the 1st of the month [help-spend][help-bill]. Build your own budget guard **(inferred advice)**.
- **Rate-limit headers:** every successful **token-based** response carries `x-ratelimit-limit-tokens`, `x-ratelimit-remaining-tokens`, `x-ratelimit-limit-requests` and `x-ratelimit-remaining-requests` [pricing]. Whether SAM responses carry them is unclear. Read them with `raw = client.responses.with_raw_response.create(...); raw.headers.get(...); resp = raw.parse()` [openai-readme].
- **`usage` fields** [tokens][resp-schemas][chat-schemas]:
  - **Responses:** `input_tokens`, `input_tokens_details.cached_tokens`, `output_tokens`, `output_tokens_details.reasoning_tokens` and `total_tokens`, plus `images_processed` / `video_frames_processed` for SAM. With hosted tools, `input_tokens` sums all model iterations.
  - **Chat:** `prompt_tokens`, `prompt_tokens_details.cached_tokens`, `completion_tokens`, `completion_tokens_details.reasoning_tokens` and `total_tokens`.

Per-call cost logger **(inferred formula from the documented prices and fields)**:

```python
PRICE = {  # USD per unit, from https://dev.meta.ai/docs/pricing-rate-limits (2026-10-26)
    "muse-spark-1.3":             {"in": 1.25e-6, "cached": 0.15e-6,  "out": 4.25e-6},
    "muse-spark-1.3-contributor": {"in": 0.10e-6, "cached": 0.002e-6, "out": 0.20e-6},
    "sam-3.1":                    {"image": 2.50e-3, "frame": 0.20e-3},
}

def call_cost_usd(model: str, usage: dict, web_search_queries: int = 0) -> float:
    p = PRICE[model]
    if model == "sam-3.1":
        return ((usage.get("images_processed") or 0) * p["image"]
                + (usage.get("video_frames_processed") or 0) * p["frame"])
    cached = (usage.get("input_tokens_details") or {}).get("cached_tokens") or 0
    return ((usage["input_tokens"] - cached) * p["in"] + cached * p["cached"]
            + usage["output_tokens"] * p["out"] + web_search_queries * 2.50e-3)
```

---

## 8. Errors and retries

**Error envelope** [errors]: `{"error": {"message", "type", "param", "code"}}`.
- `type` is one of `invalid_request_error`, `authentication_error`, `rate_limit_error`, `server_error` or `billing_error`.
- `code` is often null on validation errors.
- An unknown **path** returns 404 with an **empty body**.

| Status | Meaning / code | Retry? |
|---|---|---|
| 400 | Validation: bad params, context overflow (`input + max_output_tokens > 1,048,576`), file too big, unfetchable media URL, undecodable media, `content_policy_violation`, bad conversation structure, SAM prompt errors | No. Fix the request [errors][sam-seg] |
| 401 | `invalid_api_key`: missing or malformed key | No [errors] |
| 402 | `billing_error` / `billing_not_configured` | No [errors] |
| 403 | No access to the model or feature | No [errors] |
| 404 | `model_not_found`, `file_not_found`. A just-completed response can briefly 404 on GET; retry once or twice | Only in that case [errors][responses] |
| 413 | `payload_too_large`: background body over 1 MiB, or a `store=true` request with huge inline media. Use the Files API or `store=false` | No [errors] |
| 429 | `rate_limit_exceeded`, with a `Retry-After` header | Yes [errors][pricing] |
| 500 | Server error, including malformed model output | Yes, with backoff [errors] |
| 503 | `server_shutting_down` (Retry-After of a few seconds), `service_overloaded` (Retry-After: 60), `backend_unavailable` (60 s) | Always [errors] |
| 504 | `gateway_timeout` on a non-streaming request | **Do not retry unchanged.** Stream, use `background: true`, or reduce the work [errors] |

**Retry recipe.** Use exponential backoff with jitter [pricing][errors]:
- Start at about 0.5 s and double on each attempt, adding 0–1 s of random jitter.
- Stop after 3–5 attempts.
- Honor `Retry-After`.
- Never retry 400, 401, 402, 403, 404 or 413.

The OpenAI SDK retries connection errors, 408, 409, 429 and ≥500 (including 504) twice by default [openai-readme]. Either set `max_retries=0` and use your own policy, or account for the hidden retries when you log costs **(inferred advice)**.

**Mid-stream failures** arrive as `response.failed` or an `error` SSE event (for example `server_shutting_down`). Retry the full request [errors].

---

## 9. Hackathon notes

**The event** [hackathon]:
- Meta Global AI Developer Hackathon. Kickoff Oct 26, 2026. Workshops and Discord office hours Oct 27–Nov 4.
- **Submissions due Nov 4, 9:00 PM ET.** Judging Nov 4–8. Finals on Nov 9.
- Two tracks: Indie and Startup. Two themes: "Build for Your World" and "Push the Frontier". $1M in prizes.
- Suggested stack: "Use the Muse Spark series, Muse Image and SAM 3.1 through Meta Model API, run Meta open weights models, and code faster with Muse Code."
- "Official Rules will be published before the Hackathon begins on October 26, 2026". They were not linked on the page when fetched.

**Credits:**
- Neither the official event page [hackathon] nor the organizer page [cv-hackathon] states a **Meta Model API** credit amount.
- The organizer page lists partner credits for open-weights inference "to select participants": Baseten **$100 + 2M TPM**, Modal **$100**, Fireworks **$25** [cv-hackathon].
- A third-party newsletter (Techpresso) claims "$150 in free Meta Model API credits". This is **unverified** [techpresso].
- Check the dashboard's Billing page for the real balance.

**`meta-models/muse-spark-open-1026`:** not found anywhere (see belief 9).
- Documented model strings: `meta-models/muse-spark-open` on Together, Baseten, Groq and Nebius; `accounts/fireworks/models/muse-spark-open` on Fireworks [spark-open-deploy].
- Hugging Face repos: `meta-models/Muse-Spark-Open-816B-A42B` (BF16, ~1.65 TB) and `-NVFP4` (~537 GB) [spark-open-get][hf].
- The model: 816B total / 42B active MoE, 1,048,576-token context, text/image/audio/video input [spark-open].
- The `-1026` suffix is probably a dated snapshot alias on a partner provider **(inferred)**. It is irrelevant if we stay on Model API.

**Contributor mode:**
- 12.5× cheaper input and ~21× cheaper output, but only 150 RPM [pricing].
- Content may be used for training.
- **Do not send personal or confidential information**, and it is not available to ZDR teams [help-contrib]. Public volcano webcams are probably fine, but frames can contain people **(inferred)**.

**Geography:** Argentina, Chile, Peru, Bolivia, Ecuador and Colombia are **not** restricted. Venezuela **is** a restricted territory [geo].

**Prompt tuning:** use the **Playground** to try SAM 3.1 prompts on our own webcam media before coding [card-sam].

---

## 10. Open questions, contradictions, undocumented behaviour

1. **SAM model ID.** The docs and code use `sam-3.1`; the marketing pricing tables show `sam-3-1` [card-sam][product]. Confirm with `GET /v1/models`.
2. **`fps` on video inputs.** `input_video.fps` (Responses) and `video_url.fps` (Chat) exist without any description [resp-schemas][chat-schemas]. Unknown: the default sampling rate, whether SAM honours the field (which would affect billed frames), and its limits.
3. **Muse Spark video limits.** Maximum duration, resolution, frames sampled and tokens per second are all undocumented. Only "MP4" plus the 50 MB / 1 GiB file limits are stated [video][files].
4. **Image resolution.** The maximum image resolution and resize policy are undocumented ("may resize"), and so is the effect of `detail` (`low|high|auto|original`) on Muse Spark [img][resp-schemas].
5. **SAM input limits.** Image and video resolution caps, the per-request file size beyond the generic limits, and image `file_id` support are all undocumented [sam-seg].
6. **SAM tuning parameters.** There is no threshold, max-objects or sampling parameter. Filter on `c` client-side [sam-seg].
7. **SAM zero-match billing.** Whether a zero-match image request still bills one image is not stated **(inferred: yes)**. Check `usage.images_processed`.
8. **SAM token fields.** Whether SAM responses populate `input_tokens`/`output_tokens`, and whether they carry `x-ratelimit-*` headers (described only for "token-based" responses), is unknown [pricing].
9. **Mask placement.** dev.meta.ai says only "smaller than the frame". The box-sized raster and its placement are stated in the parser README and protocol spec on GitHub/PyPI [gh-protocol][pypi-parser], not on dev.meta.ai.
10. **SAM stream finalizer.** The live SAM stream emits `response.content_part.done` but **not** `response.output_text.done` [pypi-parser]. It is also not stated whether each delta ends with `\n`. The parser buffers either way.
11. **Contradiction: injected tokens.** [pricing] says injected scaffolding is "excluded from the token counts reported … by the token-counting endpoints", but [tokens] says "The count endpoint includes these tokens".
12. **Contradiction: `response_format` on Responses.** "Accepted but ignored" according to [so] and [responses]; "returns HTTP 400" according to [cb-so].
13. **Contradiction: images in non-user roles.** "Not processed" according to [img]; "rejected with HTTP 400" according to [cb-vision].
14. **Contradiction: `expires_at`.** "The response omits `expires_at`" according to [files]; "always present … null rather than omitted" according to [files-schemas].
15. **Inconsistency: reasoning levels.** The Responses and Chat parameter lists name `none`…`xhigh` only [responses][chat], while [reasoning] and the schema include `max` for `muse-spark-1.3`.
16. **Maximum output tokens.** The model docs never state the limit for `muse-spark-1.3`. 131,072 appears only in the quickstart's OpenCode config [quickstart].
17. **Non-streaming timeout.** The time limit before a non-streaming request gets a 504 is not given [errors].
18. **Stored responses.** The retention period for stored Responses (`store: true`, needed for `previous_response_id`) was not found in the pages read.
19. **`metadata` limits.** The maximum number of keys and the value length for `metadata` are undocumented. SAM requires string values [sam-seg].
20. **Tools with structured output.** Combining `tools` with `text.format` is not explicitly documented; only `tool_search` with `json_schema` is forbidden [toolsearch].
21. **Languages and knowledge cutoff.** Neither is listed for `muse-spark-1.3` on [models]. The help pages say the models are multilingual [help-languages][help-cutoff].
22. **Hackathon specifics.** The `muse-spark-open-1026` ID, the Model API credit amount and the Official Rules link are all missing (section 9).

---

## Source index

- **llms** — https://dev.meta.ai/llms.txt
- **overview** — https://dev.meta.ai/docs/overview
- **quickstart** — https://dev.meta.ai/docs/quickstart
- **auth** — https://dev.meta.ai/docs/authentication
- **models** — https://dev.meta.ai/docs/models
- **sdks** — https://dev.meta.ai/docs/sdks
- **pricing** — https://dev.meta.ai/docs/pricing-rate-limits
- **errors** — https://dev.meta.ai/docs/error-handling
- **files** — https://dev.meta.ai/docs/file-handling
- **img** — https://dev.meta.ai/docs/image-understanding
- **video** — https://dev.meta.ai/docs/video-understanding
- **tools** — https://dev.meta.ai/docs/tool-calling
- **toolsearch** — https://dev.meta.ai/docs/tool-search
- **so** — https://dev.meta.ai/docs/structured-output
- **reasoning** — https://dev.meta.ai/docs/reasoning
- **caching** — https://dev.meta.ai/docs/prompt-caching
- **tokens** — https://dev.meta.ai/docs/token-counting
- **protocols** — https://dev.meta.ai/docs/protocols
- **responses** — https://dev.meta.ai/docs/protocols/responses
- **chat** — https://dev.meta.ai/docs/protocols/chat-completions
- **apiref** — https://dev.meta.ai/docs/api-reference
- **resp-schemas** — https://dev.meta.ai/docs/api-reference/responses/schemas
- **chat-schemas** — https://dev.meta.ai/docs/api-reference/chat-completions/schemas
- **files-schemas** — https://dev.meta.ai/docs/api-reference/files/schemas
- **files-list** — https://dev.meta.ai/docs/api-reference/files/list-files
- **models-schemas** — https://dev.meta.ai/docs/api-reference/models/schemas
- **status** — https://dev.meta.ai/docs/api-reference/status
- **mediaseg** — https://dev.meta.ai/docs/media-segmentation
- **sam-overview** — https://dev.meta.ai/docs/sam/overview
- **sam-seg** — https://dev.meta.ai/docs/sam/segmenting
- **sam-read** — https://dev.meta.ai/docs/sam/reading-segmentation
- **sam-libs** — https://dev.meta.ai/docs/sam/client-libraries
- **cb-sam-basics** — https://dev.meta.ai/docs/cookbook/sam-api-basics
- **cb-sticker** — https://dev.meta.ai/docs/cookbook/video-to-sticker-pack
- **cb-so** — https://dev.meta.ai/docs/cookbook/structured-output
- **cb-vision** — https://dev.meta.ai/docs/cookbook/vision-input
- **cb-stream** — https://dev.meta.ai/docs/cookbook/streaming-responses
- **card-spark** — https://dev.meta.ai/models/muse-spark
- **card-sam** — https://dev.meta.ai/models/sam-3-1
- **product** — https://dev.meta.ai/products/meta-model-api
- **hackathon** — https://dev.meta.ai/events/global-hackathon
- **cv-hackathon** — https://cerebralvalley.ai/e/meta-ai-developer-hackathon
- **spark-open** — https://dev.meta.ai/docs/muse-spark-open
- **spark-open-get** — https://dev.meta.ai/docs/muse-spark-open/get-the-model
- **spark-open-deploy** — https://dev.meta.ai/docs/muse-spark-open/deploy
- **spark-open-prompting** — https://dev.meta.ai/docs/muse-spark-open/prompting
- **help-ratelimits** — https://dev.meta.ai/help/usage-and-limits/rate-limits
- **help-usage** — https://dev.meta.ai/help/usage-and-limits/api-usage
- **help-bill** — https://dev.meta.ai/help/billing/api-bill
- **help-spend** — https://dev.meta.ai/help/billing/spend-limit-alert
- **help-contrib** — https://dev.meta.ai/help/policies-and-privacy/contributor-tier
- **help-languages** — https://dev.meta.ai/help/about-model-api/supported-languages
- **help-cutoff** — https://dev.meta.ai/help/about-model-api/knowledge-cutoff
- **geo** — https://dev.meta.ai/legal/geographic-use-policy
- **pypi-parser** — https://pypi.org/project/meta-sam-parser/ (README of v0.1.0)
- **gh-sam-api** — https://github.com/meta-models/meta-model-cookbook/blob/main/07_sam/01_api_basics/python/sam_api.py
- **gh-protocol** — https://github.com/meta-models/meta-sam/blob/main/protocol/sam3.md
- **hf** — https://huggingface.co/meta-models
- **c7** — Context7 library `/websites/dev_meta_ai` (mirror of dev.meta.ai docs)
- **openai-helpers** — https://github.com/openai/openai-python/blob/main/helpers.md
- **openai-readme** — https://github.com/openai/openai-python/blob/main/README.md
- **techpresso** — https://www.sequenzy.com/api/email-examples/j5iypr0umhagob6hpglchdwg/html (third-party newsletter copy)

[llms]: https://dev.meta.ai/llms.txt
[overview]: https://dev.meta.ai/docs/overview
[quickstart]: https://dev.meta.ai/docs/quickstart
[auth]: https://dev.meta.ai/docs/authentication
[models]: https://dev.meta.ai/docs/models
[sdks]: https://dev.meta.ai/docs/sdks
[pricing]: https://dev.meta.ai/docs/pricing-rate-limits
[errors]: https://dev.meta.ai/docs/error-handling
[files]: https://dev.meta.ai/docs/file-handling
[img]: https://dev.meta.ai/docs/image-understanding
[video]: https://dev.meta.ai/docs/video-understanding
[tools]: https://dev.meta.ai/docs/tool-calling
[toolsearch]: https://dev.meta.ai/docs/tool-search
[so]: https://dev.meta.ai/docs/structured-output
[reasoning]: https://dev.meta.ai/docs/reasoning
[caching]: https://dev.meta.ai/docs/prompt-caching
[tokens]: https://dev.meta.ai/docs/token-counting
[protocols]: https://dev.meta.ai/docs/protocols
[responses]: https://dev.meta.ai/docs/protocols/responses
[chat]: https://dev.meta.ai/docs/protocols/chat-completions
[apiref]: https://dev.meta.ai/docs/api-reference
[resp-schemas]: https://dev.meta.ai/docs/api-reference/responses/schemas
[chat-schemas]: https://dev.meta.ai/docs/api-reference/chat-completions/schemas
[files-schemas]: https://dev.meta.ai/docs/api-reference/files/schemas
[files-list]: https://dev.meta.ai/docs/api-reference/files/list-files
[models-schemas]: https://dev.meta.ai/docs/api-reference/models/schemas
[status]: https://dev.meta.ai/docs/api-reference/status
[mediaseg]: https://dev.meta.ai/docs/media-segmentation
[sam-overview]: https://dev.meta.ai/docs/sam/overview
[sam-seg]: https://dev.meta.ai/docs/sam/segmenting
[sam-read]: https://dev.meta.ai/docs/sam/reading-segmentation
[sam-libs]: https://dev.meta.ai/docs/sam/client-libraries
[cb-sam-basics]: https://dev.meta.ai/docs/cookbook/sam-api-basics
[cb-sticker]: https://dev.meta.ai/docs/cookbook/video-to-sticker-pack
[cb-so]: https://dev.meta.ai/docs/cookbook/structured-output
[cb-vision]: https://dev.meta.ai/docs/cookbook/vision-input
[cb-stream]: https://dev.meta.ai/docs/cookbook/streaming-responses
[card-spark]: https://dev.meta.ai/models/muse-spark
[card-sam]: https://dev.meta.ai/models/sam-3-1
[product]: https://dev.meta.ai/products/meta-model-api
[hackathon]: https://dev.meta.ai/events/global-hackathon
[cv-hackathon]: https://cerebralvalley.ai/e/meta-ai-developer-hackathon
[spark-open]: https://dev.meta.ai/docs/muse-spark-open
[spark-open-get]: https://dev.meta.ai/docs/muse-spark-open/get-the-model
[spark-open-deploy]: https://dev.meta.ai/docs/muse-spark-open/deploy
[spark-open-prompting]: https://dev.meta.ai/docs/muse-spark-open/prompting
[help-ratelimits]: https://dev.meta.ai/help/usage-and-limits/rate-limits
[help-usage]: https://dev.meta.ai/help/usage-and-limits/api-usage
[help-bill]: https://dev.meta.ai/help/billing/api-bill
[help-spend]: https://dev.meta.ai/help/billing/spend-limit-alert
[help-contrib]: https://dev.meta.ai/help/policies-and-privacy/contributor-tier
[help-languages]: https://dev.meta.ai/help/about-model-api/supported-languages
[help-cutoff]: https://dev.meta.ai/help/about-model-api/knowledge-cutoff
[geo]: https://dev.meta.ai/legal/geographic-use-policy
[pypi-parser]: https://pypi.org/project/meta-sam-parser/
[gh-sam-api]: https://github.com/meta-models/meta-model-cookbook/blob/main/07_sam/01_api_basics/python/sam_api.py
[gh-protocol]: https://github.com/meta-models/meta-sam/blob/main/protocol/sam3.md
[hf]: https://huggingface.co/meta-models
[c7]: https://context7.com/
[openai-helpers]: https://github.com/openai/openai-python/blob/main/helpers.md
[openai-readme]: https://github.com/openai/openai-python/blob/main/README.md
[techpresso]: https://www.sequenzy.com/api/email-examples/j5iypr0umhagob6hpglchdwg/html
