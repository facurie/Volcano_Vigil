# Deployment

Volcano Vigil runs as one Hugging Face Docker Space, `facurie/volcano-vigil`, on the free `cpu-basic` hardware
(2 vCPU, 16 GB). The address is in the README.

## Why this server

- Oracle Cloud's Always Free VM needs a credit card at signup, and the owner has none. Hugging Face Docker Spaces
  need a PRO subscription ($9/month), which the owner has.
- The Space's visibility is "protected": the code stays private and the app is public.
- A Space's disk is lost whenever it restarts. The live state is saved to a private bucket, `facurie/vigil-state`
  (`vigil/persist.py`), so the database, and with it the Meta API cost ledger and `DAILY_BUDGET_USD`, survive.

## What runs in the container (`deploy/start.sh`)

| Step | Command | Role |
|---|---|---|
| 1 | `vigil-persist restore` | Puts the saved database, frames and bulletins back. A failure stops the start (the Hub restarts the Space) |
| 2 | `vigil-mirror pull --episode 55 …` | Puts the episode 55 replay from its [Hugging Face dataset](https://huggingface.co/datasets/facurie/volcano-vigil-ep55) into the data dir, downloading only what changed |
| 3 | `vigil-web --host 0.0.0.0 --port 7860` | The dashboard, live and replay; it opens the databases read-only |
| 4 | `vigil-ingest --once --lookback-hours 24` | Catches up on the last 24 h of KPcam and K2cam from AshCam |
| 5 | `vigil-ingest --lookback-hours 24` | Polls KPcam and K2cam (AshCam) and F1cam (`M.jpg`); restarted if it exits |
| 6 | `vigil-pipeline --volcano kilauea` | Every 5 min: quality gate, one SAM window per camera per hour, measurements, an hourly bulletin. The only service that spends money; restarted if it exits |
| 7 | `vigil-alerts --volcano kilauea` | Every minute: looks for lava fountaining and posts each new alert to Telegram; restarted if it exits (see "Fountaining alerts and Telegram") |
| 8 | `vigil-persist run --interval 300` | Saves the state every 5 min and once more when the Space stops |

All of them run one image as uid 1000 with `DAILY_BUDGET_USD=8`, on the data dir `/app/data`. SQLite in WAL mode
lets them write and read at once. Secrets (`MODEL_API_KEY`, `HF_TOKEN`) are Space secrets, which reach the
processes as environment variables; they are never in git or in the image.

## First-time setup

1. **The bucket:** `.venv/Scripts/hf.exe buckets create vigil-state --private`.
2. **A token for the Space:** huggingface.co/settings/tokens → New token → type Write → name `vigil-space`. The
   Space uses it to read and write the bucket. Revoke it when the project is over.
3. **The Space:** `vigil-space deploy` (step 5) creates it as "protected" if it does not exist yet. To have it before
   the first code arrives (so the secrets can be set first), create it once with
   `HfApi().create_repo("facurie/volcano-vigil", repo_type="space", space_sdk="docker", visibility="protected", exist_ok=True)`.
4. **The secrets:** Space → Settings → Variables and secrets → New secret, twice:
   - `MODEL_API_KEY`: the value of that line in the local `.env`;
   - `HF_TOKEN`: the token of step 2.

   The Telegram bot token is added the same way (see "Fountaining alerts and Telegram").
5. **Deploy:** commit, then `.venv/Scripts/vigil-space.exe deploy --repo facurie/volcano-vigil`. The Hub builds the
   image (a few minutes) and starts it. Watch it with the commands under "Operate".

## Deploy a change

Commit, then run `vigil-space deploy --repo facurie/volcano-vigil`. It uploads `git archive HEAD`, never the working
tree, `.env` or `data/`, and deletes from the Space the files the tree no longer has. Each deploy rebuilds the image
and restarts the Space; the state comes back from the bucket (at most the last 5 minutes of work are lost).

## Operate

- **Visit the URL at least once every 24 hours.** Free hardware goes to sleep after 48 hours without visitors, which
  stops ingest and the pipeline. A visit wakes it, the state is restored and ingest catches up on up to 24 h; a gap
  longer than that is not filled by itself.
- Stage: `HfApi().get_space_runtime("facurie/volcano-vigil").stage` (`BUILDING`, `RUNNING`, `RUNTIME_ERROR`, …).
- Logs, `build` or `run` (the run log streams, so the command stops after 20 s without news):

  ```bash
  .venv/Scripts/python.exe -I - run <<'EOF'
  import sys
  import httpx
  from huggingface_hub import get_token

  url = f"https://huggingface.co/api/spaces/facurie/volcano-vigil/logs/{sys.argv[1]}"
  try:
      with httpx.stream("GET", url, params={"tail": 100}, headers={"Authorization": f"Bearer {get_token()}"},
                        timeout=20) as response:
          for line in response.iter_lines():
              print(line)
  except httpx.ReadTimeout:
      pass
  EOF
  ```
- Today's Meta API spend (UTC day) and the frames per camera, from the bucket's copy of the database (at most
  5 minutes old):

  `.venv/Scripts/hf.exe buckets cp hf://buckets/facurie/vigil-state/db/vigil.sqlite <scratch>/ledger.sqlite`

  `.venv/Scripts/python.exe -I -c "import sqlite3, sys; c = sqlite3.connect(sys.argv[1]); print(c.execute(\"SELECT ROUND(COALESCE(SUM(cost_usd), 0), 3) FROM api_calls WHERE substr(called_at, 1, 10) = date('now')\").fetchone()[0], c.execute('SELECT camera_id, COUNT(*), MAX(captured_at) FROM frames GROUP BY camera_id').fetchall())" <scratch>/ledger.sqlite`
- Stop everything at once (nothing spends while it is paused): `HfApi().pause_space("facurie/volcano-vigil")`.
  Resume with `HfApi().restart_space("facurie/volcano-vigil")`.
- After a new replay of episode 55: run `vigil-mirror push --episode 55 --repo facurie/volcano-vigil-ep55` locally,
  then redeploy. `vigil-mirror pull` fetches what changed.

## Fountaining alerts and Telegram

- **What runs:** `vigil-alerts --volcano kilauea`, every minute, supervised like ingest and the pipeline. It watches
  the alert cameras for a lava fountain, stores each onset and end in the `alerts` table (with their frames under
  `data/alerts/`, which `vigil-persist` saves) and posts it to the public Telegram channel
  [Volcano Vigil · Kīlauea](https://t.me/volcano_vigil_kilauea), through the bot `@volcano_vigil_bot`.
- **Its spend:** the Meta API calls it makes carry the tag `alerts:<date>` (one per UTC day) and may cost at most
  $0.75 a day (`ALERT_RESERVE_USD`, set in the image). They count inside the $8 cap: the pipeline stops at $7.25, so
  the alerts always have their share.
- **The secrets:** `TELEGRAM_BOT_TOKEN` is a Space secret (the value BotFather gave; never in git or the image) and
  `TELEGRAM_CHAT_ID` a public Space variable: the channel's numeric id, `-1004340718752`, which is not a secret.
  Check them locally with `vigil-telegram check`, and post a test message that is not an alert with
  `vigil-telegram test`.
- **The relay:** Hugging Face blocks `api.telegram.org` from Spaces on purpose (the first start on 2026-11-01 logged
  `Telegram check failed … getMe: ConnectTimeout`), so the Space posts through a Cloudflare Worker on the owner's
  free account, `https://vigil-telegram.facundorn3.workers.dev`, set in the public Space variable
  `TELEGRAM_API_URL`. Without it (or if the relay is down), the Space still stores the alerts and shows them on the
  dashboard, but every post fails (`not posted` in the log). Locally, leave `TELEGRAM_API_URL` empty to talk to
  Telegram itself, or check the relay with
  `TELEGRAM_API_URL=https://vigil-telegram.facundorn3.workers.dev .venv/Scripts/vigil-telegram.exe check`.
  - It was made in the dashboard: Workers & Pages → Create → "Start with Hello World!" → name `vigil-telegram` →
    Deploy → Edit code, paste the code below, Deploy. A new `workers.dev` subdomain answered with a TLS handshake
    failure ("unsupported protocol" in a browser) for about 20 minutes, until Cloudflare issued its certificate.
  - It forwards only this bot's five calls and answers 404 to anything else (checked: `GET /` and another bot's
    `getMe` get 404):

  ```js
  // Volcano Vigil: forwards only this bot's calls to the Telegram Bot API, which Hugging Face Spaces cannot reach.
  const BOT = "/bot9289168776:";
  const METHODS = new Set(["getMe", "getChat", "getChatMember", "sendMessage", "sendPhoto"]);

  export default {
    async fetch(request) {
      const url = new URL(request.url);
      const method = url.pathname.split("/").pop();
      if (request.method !== "POST" || !url.pathname.startsWith(BOT) || !METHODS.has(method)) {
        return new Response("Not found", { status: 404 });
      }
      url.protocol = "https:";
      url.hostname = "api.telegram.org";
      url.port = "";
      return fetch(new Request(url, request));
    },
  };
  ```

  The token passes through the Worker in the URL, as it does to Telegram. The code logs nothing, but Cloudflare's
  Workers Logs, when enabled, record each request's URL in the owner's account: keep them off (the Worker's
  Settings → Observability).
- **Its log lines:** read the run log as under "Operate" (the code block there), and grep it for `Telegram` (the
  check at start: `may post: yes`, `Telegram check failed`, or the warning that the token or chat id is not set),
  `ALERT` (each alert raised, as `ALERT onset #…` or `ALERT end #…`) and `not posted` (a post to Telegram that
  failed).
- **The alerts, read from the bucket's copy of the database** (copy it as under "Operate"):

  `.venv/Scripts/python.exe -I -c "import sqlite3, sys; c = sqlite3.connect(sys.argv[1]); print(*c.execute('SELECT id, kind, clock, captured_at, sent_at, send_error FROM alerts').fetchall(), sep=chr(10))" <scratch>/ledger.sqlite`

  `sent_at` is empty and `send_error` says why when a post to Telegram failed.
- **A longer catch-up at start:** the V1 camera, which only the alerts use, adds about 720 frames per 24 h to the
  catch-up, so the start takes about 5 minutes more (about 0.4 s per frame).

## Costs

- Space and bucket: $0 beyond the PRO subscription ($9/month; PRO includes 1 TB of private storage).
- Meta Model API: the pipeline costs about $6 a day (about $0.25 an hour on 2026-11-02, most of it the hourly agent
  run) and the alerts about $0.45, capped at $8 a UTC day. The cap was raised from $3 to $5 on 2026-11-01 and to $8 on
  2026-11-02 with the owner's OK, after $5 stopped the bulletins from 07:12 to 14:00 HST. Hitting the cap stops SAM,
  Muse Spark and bulletins until 00:00 UTC (14:00 HST); ingest and the dashboard go on.
- If the daily visit is ever missed or the 2 vCPU fall behind: `CPU Upgrade` costs $0.03/hour (about $0.72/day) and
  never sleeps. Switch to it only with the owner's OK.

## Risks

- **The Space sleeps** after 48 hours without visitors (see "Operate"), and the Hub may restart it at any time.
  Either way the state is restored; the work since the last save (5 minutes) is lost.
- **The restore fails** (for example, `HF_TOKEN` was revoked): the Space shows a runtime error and restarts instead
  of running on an empty database. Fix the secret.
- **AshCam** can change without notice, or may not answer from the Hub's network. Live ingest falls back to
  `M.jpg`, and the replay no longer needs AshCam.
- **A write token** sits in the Space's secrets. Revoke it after the judging.
- **The Telegram relay is blocked too:** the Hub could extend its block to `workers.dev`. The alerts are still
  stored and shown on the dashboard; their posts fail with `not posted` in the log (see "Fountaining alerts and
  Telegram"). Then move the Worker to a custom domain, or post from outside the Space.
