# agent-hub

A **local AI agent orchestration hub** — a file-based control plane that coordinates planners and workers through a deterministic LangGraph workflow.

**Phase 1:** mocked planner and worker skeleton. No real LLM, no real coding workers, no network calls. Tier 2+ workspace mutations are **approval-gated**, not automatic.

**Phase 2 (current):** adds the Codex CLI worker for one bounded Tier-2 docs task. Codex authenticates through its own OAuth login; the hub does not store, read, inject, or log API keys, OAuth tokens, session cookies, or credentials.

## Current state

| Item | Value |
|------|-------|
| Mode | `dry_run` |
| T-0001 | `done` — Tier 1 planning mock cycle completed |
| T-0002 | Tier 2 docs task with a bounded Codex approval record |
| Tests | `pytest` |

Check live status anytime:

```bash
python cli.py status
python cli.py backlog
```

## Install

Development and testing currently happen on a **Fedora KDE** Linux workstation (the eventual deployment target is the Pop!_OS box). On a fresh Fedora install, make sure the prerequisites are present:

```bash
# Fedora prerequisites (python venv is bundled with python3; git is needed for Phase 2 checkpoints)
sudo dnf install -y python3 python3-pip git
```

Then set up the project:

```bash
cd /path/to/agent-hub
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run one cycle

```bash
python cli.py run
```

This picks the highest-priority `ready` task from `project/BACKLOG.yaml` and runs it through the graph:

`intake → plan → route → safety_check → [approval_gate] → checkpoint → execute → validate → record → report`

When no tasks are `ready`, the cycle reports `outcome: no_task`.

### Example tasks in the starter backlog

| ID | Type | Tier | Behavior |
|---|---|---|---|
| T-0001 | planning | 1 | Completes a full mock cycle automatically |
| T-0002 | docs | 2 | Queued for approval; does **not** mutate `workspace/` in `dry_run` |

## Other commands

```bash
python cli.py status    # hub status summary
python cli.py backlog   # list backlog tasks
```

## Approvals (Tier 2+)

Tier 2+ tasks pause at `approval_gate` until a human adds a matching record to `approvals/APPROVAL_DECISIONS.yaml`.

**Pending:** request `A-0001` for task `T-0002` (see `approvals/APPROVAL_QUEUE.yaml` and `approvals/RISK_REVIEW.md`).

### How to approve or deny

1. Open `approvals/APPROVAL_QUEUE.yaml` and find the `request_id` (e.g. `A-0001`).
2. Append a decision to `approvals/APPROVAL_DECISIONS.yaml`:

```yaml
schema_version: 1
decisions:
  - request_id: A-0001
    decision: approved          # approved | denied
    decided_by: human
    decided_at: '2026-06-26T16:00:00Z'
    approved_scope:           # required when approved
      task_id: T-0002
      tier: 2
      target_folder: workspace/example
      allowed_files: ['workspace/example/utils.py']
      allowed_worker: codex
      expires_at: '2026-06-26T18:00:00Z'
    note: 'ok, limited to utils.py docstring only'
```

3. Remove the matching entry from `pending` in `APPROVAL_QUEUE.yaml`.
4. Set the task back to `ready` in `project/BACKLOG.yaml`.
5. Run `python cli.py run` again.

To **deny**, set `decision: denied`, omit `approved_scope`, and add a `note` explaining why.

Required scope fields match `config/SAFETY_RULES.yaml` → `approval_scope_required_fields`.

## Folder map

```
agent-hub/
├── config/           # ROUTING_RULES, SAFETY_RULES, workers registry
├── project/          # control-plane state (STATUS, BACKLOG, LIMITS, logs)
├── approvals/        # approval queue and decisions
├── runs/
│   ├── AGENT_RUNS/   # per-run worker logs
│   └── VALIDATION_RESULTS/
├── src/orchestrator/ # engine, graph, nodes, planners, workers, safety
├── tests/
├── workspace/        # git repo the hub operates on (separate git)
├── cli.py
└── requirements.txt
```

## What is mocked (Phase 1)

- **Planner:** `mock_planner` — deterministic plans from BACKLOG fields
- **Worker:** `mock_worker` — writes run logs; Tier 1 planning updates `DECISION_LOG`; Tier 2 without approval returns `blocked`
- **Limits/context:** heuristic tracking with conservative cooldown defaults
- **Mode:** `dry_run` — no `workspace/` mutations for docs/code tasks

## Phase 2: Codex OAuth worker

Codex is invoked through the command template in `config/workers.yaml`, currently `codex exec --sandbox workspace-write {task}` for a non-interactive workspace-write run. The exact syntax may need to be updated to match the installed Codex CLI version; update `command_template` in `workers.yaml`, not the adapter code.

Before running a real Codex-backed Tier-2 cycle, authenticate outside the hub:

```bash
codex login
```

or the equivalent login command for the installed Codex CLI. The OAuth session is owned by the CLI/keychain. The hub only starts the subprocess and captures redacted stdout/stderr in `runs/AGENT_RUNS/`.

If Codex reports `auth_expired` signals such as "not authenticated", "please log in", "session expired", "unauthorized", or `401`, the engine records the worker in `project/LIMITS.json` as:

```json
{
  "status": "failed",
  "failure_type": "auth_expired",
  "retry_after": null,
  "avoid_until": null,
  "notes": "re-authentication required"
}
```

The task is not retried on a timer. A human must re-authenticate with the Codex CLI and manually reset the Codex entry in `LIMITS.json` before the worker is used again.

## Phase 3: live routing, fallbacks, and handoffs

Routing is now enforced from `config/ROUTING_RULES.yaml` on every cycle. For the task type, the engine tries `primary` first and then each configured fallback in order. A planner suggestion can override the config primary only when its confidence is at least `0.6` and the suggested worker is both capable and available.

Workers are skipped when `project/LIMITS.json` marks them as `status: failed` or `status: limited`, or when `avoid_until` is in the future. When a primary worker fails, is limited, or times out, the next available fallback is tried directly through the existing retry path. If all fallbacks are exhausted, the task is marked `blocked`, a blocker is written to `STATUS.json`, and the cycle exits cleanly.

Tier-2 fallback execution is constrained by the original approval. If the fallback worker differs from `approved_scope.allowed_worker`, the engine pauses the task, appends a new request to `approvals/APPROVAL_QUEUE.yaml`, and does not execute the fallback. A new human approval is required for that worker.

Context/session tracking runs after every execution. If turns, approximate input bytes, staleness, or consecutive failures cross the configured thresholds in `project/CONTEXT_STATE.json`, the engine writes `project/HANDOFF.md`, sets `fresh_session_recommended: true`, appends the handoff to `DAILY_REPORT.md`, and stops the cycle. It does not auto-restart worker sessions; a human or a later cycle picks up from the handoff.

`on_all_unavailable: safe_stop` is the default routing behavior. It means the engine will not block indefinitely when no worker is usable: it writes a blocker and exits the cycle cleanly.

## Safety

- **Tier 0–1:** may run automatically (logs, reports, planning docs)
- **Tier 2+:** requires an explicit matching record in `approvals/APPROVAL_DECISIONS.yaml` before any workspace mutation
- **Kill switch:** create a `STOP` file at the repo root to halt at the next checkpoint
- **Write guard:** all state writes must land inside `workspace/`, `project/`, `runs/`, or `approvals/`

## Tests

```bash
pytest
```

Phase 1 coverage includes: Tier 1 auto-run, Tier 2 approval gating, approved-folder write guard, `dry_run` workspace protection, and no-ready-tasks behavior.

## Next phase

Phase 2 adds a real Codex worker adapter, explicit Tier-2 approval, git checkpoint + rollback.
