# The agentic layer: Investigator + MCP

Nazar's Ask page answers one question. The agentic layer adds three things on top of the same tools and rules.

| | What | Where |
|---|---|---|
| **Investigator** | Give a goal. It writes a plan, runs tools step by step, follows leads, and returns a case file. | `backend/nazar/agentic/investigator.py`, web `/agent/`, Telegram `/investigate` |
| **MCP client (hub)** | The investigator can use any MCP server listed in `mcp.servers.json`. | `backend/nazar/agentic/hub.py` |
| **MCP server** | Any MCP client (Claude Desktop, Claude Code, Cursor) can query the cameras. | `backend/nazar/agentic/server.py` |

## 1. Investigator

```
goal -> PLAN (3-7 steps, structured output)
     -> EXECUTE: model rounds with Nazar's tools + update_plan + MCP tools
          - read-only tools run at once (in parallel within a round)
          - tools that change something are QUEUED for the owner
          - the model marks steps doing/done/failed/skipped and may add steps ("new lead")
     -> CASE FILE: summary, findings, recommendations, evidence panel, pending actions
```

Rules it keeps (enforced in server code, covered by `tests/test_investigator.py`):

- **Evidence levels are never the model's.** Each finding cites tool calls; the server derives the level from them,
  weakest link first: SQL facts are Confirmed, visual hits keep their own level, appearance matches and AI
  descriptions are Candidates, data from an outside tool is labelled "from a connected tool", and a finding with no
  citation is labelled "agent's reasoning, not evidence".
- **Nothing changes without the owner.** `activate_rule` and every MCP tool that is not read-only become a pending
  action with its exact arguments. Approve or reject it in the app. An action is claimed atomically, so it cannot run twice.
- **Bounded.** `AGENT_MAX_STEPS` model rounds (default 12), identical repeat calls are refused, every model call
  writes a `usage` row, and the run is stored in `agent_runs` / `agent_actions`.

Ways to start one:

- Web: **Investigate** in the navigation, or **Investigate** on any alert.
- Telegram: `/investigate Kal raat kuch ajeeb hua? Poori jaanch karo`
- API: `POST /api/agent/investigate` with `{goal, camera_id?}` or `{alert_id}` (server-sent events:
  `run`, `status`, `plan`, `tool`, `action`, `text`, `result`, `error`). Also `GET /api/agent/runs`,
  `GET /api/agent/runs/{id}`, `POST /api/agent/runs/{id}/actions/{action_id}` with `{approve}`, `GET /api/agent/tools`.
- Automatic: `AUTO_INVESTIGATE_ALERTS=true` makes the worker investigate each new alert (at most 6 per hour).

Measured on 24 Nov 2026 (demo data): three runs took 57-131 s and cost ₹5.49, ₹7.68 and ₹5.59 on the agent model.
The spoken summary is made on demand: it is synthesized the first time the owner presses play, not for every run.

## 2. Connecting MCP servers (Nazar as a client)

`mcp.servers.json` at the repo root uses the same `mcpServers` shape as Claude Desktop and Cursor, so a server's
published config can be pasted in. `${VAR}` is filled from `.env`. A server whose variable is empty is listed as
"needs a key" and not started.

| Server | Needs | State out of the box |
|---|---|---|
| `toolbox` (ships with Nazar) | nothing; Telegram / webhook URLs optional | on: weather, case notes, send to Telegram / Slack / Discord |
| `memory` | Node | on: long-term notes about the site |
| `thinking` | Node | on: reasoning scratchpad |
| `brave` | `BRAVE_API_KEY` | on once the key is set |
| `notion` | `NOTION_TOKEN` | on once the key is set |
| `github` (remote) | `GITHUB_PERSONAL_ACCESS_TOKEN` | on once the key is set |
| `files` | Node 24+ | off |
| `home-assistant` (remote) | `HOME_ASSISTANT_URL`, `HOME_ASSISTANT_TOKEN` | off; check the URL path for your version |
| `browser` | Node, ~300 MB RAM | off |

Per-server keys beyond the standard ones: `enabled`, `description`, `tools` (allow-list), `auto_approve`,
`require_approval`.

Safety model:

- A tool runs unattended only if the server marks it read-only (`readOnlyHint`) or you list it in `auto_approve`.
- A stdio server gets a basic environment plus only the variables its own config names. It never inherits Nazar's keys.
- The investigator sends text only. Footage never goes to an external tool.

## 3. Using Nazar from Claude Desktop, Claude Code or Cursor (Nazar as a server)

Add this to the client's MCP config (use the full path of this repo's Python):

```json
{
  "mcpServers": {
    "nazar": {
      "command": "C:/path/to/Nazar/.venv/Scripts/python.exe",
      "args": ["-m", "nazar.agentic.server"]
    }
  }
}
```

Claude Code: `claude mcp add nazar -- C:/path/to/Nazar/.venv/Scripts/python.exe -m nazar.agentic.server`.
HTTP instead of stdio: `python -m nazar.agentic.server --http` serves `http://127.0.0.1:8020/mcp`.

Postgres must be running. Tools: `list_cameras`, `count`, `peak_occupancy`, `search_footage`, `list_tracks`,
`security_events`, `camera_gaps`, `journey`, `analytics_views`, `analytics_sql`, `compare_periods`, `track_image`,
`camera_frame`, `describe_moment`, `ask_nazar`, `draft_watch_rule`, `incident_report`, `investigate`.
Counting, searching and events cost no AI call; `describe_moment`, `ask_nazar` and `investigate` call OpenAI.
Images are the stored face-blurred ones. Rules are drafted inactive; only the owner activates them in the app.

## Tests

`pytest tests/test_investigator.py tests/test_mcp.py` (no database or API key needed). `test_mcp.py` starts a real
stdio MCP server (`tests/toy_mcp_server.py`) and checks connect, list, call and the approval gate.
