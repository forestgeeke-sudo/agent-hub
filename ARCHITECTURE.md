# ARCHITECTURE.md

Reference design for the local AI agent orchestration hub. Read `PROJECT_BRIEF.md` first.

---

## 1. Component map

```
                 ┌─────────────────────────────────────────────┐
                 │        WORKFLOW ENGINE (deterministic)        │
                 │        Python + LangGraph — the control plane │
                 │  launches workers · enforces tiers · tracks   │
                 │  state · retries · checkpoints · logs         │
                 └───────┬───────────────────────┬───────────────┘
        advisory only    │                       │  executes
            ┌────────────▼─────────┐   ┌──────────▼───────────────┐
            │   PLANNER (LLM)      │   │   WORKERS (adapters)     │
            │  plan/route/review/  │   │  mock · codex · claude · │
            │  summarize           │   │  cursor · scripts        │
            └──────────────────────┘   └──────────────────────────┘
                         ▲                          ▲
                         │      reads/writes        │
                 ┌───────┴──────────────────────────┴────────────┐
                 │   STATE FILES (control plane) + WORKSPACE      │
                 └────────────────────────────────────────────────┘
```

The planner can *recommend* a worker, a fresh session, or a stop. Only the engine *acts*.

---

## 2. Folder / file structure

Separate the **control plane** (`project/`, the hub's own state) from the **workspace** (`workspace/`, the code the hub edits). The hub may only write inside the approved-folder allowlist (default: `workspace/` plus its own `project/`, `runs/`, `approvals/`).

```
agent-hub/
├── README.md
├── pyproject.toml              # or requirements.txt
├── .gitignore
├── STOP                        # kill switch (presence = halt). Absent by default.
│
├── config/
│   ├── ROUTING_RULES.yaml
│   ├── SAFETY_RULES.yaml
│   └── workers.yaml            # worker registry / adapter config
│
├── project/                    # CONTROL PLANE — the active project's state
│   ├── PROJECT_BRIEF.md        # stable (copy of north-star)
│   ├── STATUS.json
│   ├── BACKLOG.yaml
│   ├── LIMITS.json
│   ├── CONTEXT_STATE.json
│   ├── DECISION_LOG.md
│   ├── DAILY_REPORT.md
│   └── HANDOFF.md
│
├── approvals/
│   ├── APPROVAL_QUEUE.yaml
│   ├── APPROVAL_DECISIONS.yaml
│   └── RISK_REVIEW.md
│
├── runs/
│   ├── AGENT_RUNS/             # runs/AGENT_RUNS/2026-06-26T1430_codex_T-0001/
│   └── VALIDATION_RESULTS/
│
├── src/orchestrator/
│   ├── graph.py                # LangGraph definition (nodes + edges)
│   ├── state.py                # typed HubState
│   ├── nodes/                  # intake, plan, route, safety, approval,
│   │                           #   checkpoint, execute, validate, record, report
│   ├── planners/               # base.py (interface), mock_planner.py, (qwen_planner.py later)
│   ├── workers/                # base.py (interface), mock_worker.py, codex_worker.py,
│   │                           #   (claude_worker.py, cursor_worker.py later)
│   ├── safety/                 # tiers.py, permissions.py
│   ├── tracking/               # limits.py, context.py
│   └── io/                     # state_files.py (read/write + schema validation), logging.py
│
├── cli.py                      # entrypoint: run one cycle, show status, list backlog
├── tests/
│   └── fixtures/
│       └── codex_stderr/       # realistic stderr fixture files for worker tests
└── workspace/                  # the project(s) the hub operates ON (a git repo)
    └── .gitkeep
```

**Refinements vs. your original list:** moved `ROUTING_RULES`/`SAFETY_RULES` into `config/` (they're config, not generated state); added `workers.yaml`; added `STOP`; made `AGENT_RUNS/` and `VALIDATION_RESULTS/` per-run folders rather than loose files; added an explicit `workspace/` that must be a git repo (this is what makes approved Tier-2 edits reversible); added `tests/fixtures/codex_stderr/` for worker signal-parsing tests.

---

## 3. State file schemas

All structured files carry `schema_version` so future migrations are detectable. Keep them small and hand-editable.

### STATUS.json
```json
{
  "schema_version": 1,
  "updated_at": "2026-06-26T14:30:00Z",
  "mode": "dry_run",
  "active_task_id": null,
  "last_cycle": { "id": "C-0007", "outcome": "success", "ended_at": "2026-06-26T14:29:00Z" },
  "blockers": [],
  "workers": { "mock_worker": "available", "codex": "unknown", "claude": "unknown" },
  "stop_requested": false
}
```

### BACKLOG.yaml
```yaml
schema_version: 1
tasks:
  - id: T-0001
    title: Add a docstring to utils.format_date
    description: >
      Add a one-line docstring; do not change behavior.
    type: docs           # code_edit | refactor | docs | scrape | maint | planning | routing | test
    risk_tier: 2
    priority: 2          # 1 = highest ... 5 = lowest
    target_folder: workspace/example
    suggested_worker: codex
    depends_on: []
    status: ready        # candidate | ready | in_progress | blocked | paused | done | abandoned
    created_at: 2026-06-26T14:00:00Z
```

### LIMITS.json
```json
{
  "schema_version": 1,
  "workers": {
    "codex": {
      "auth_method": "oauth",
      "status": "available",          // available | limited | failed | unknown
      "last_success": null,
      "last_failure": null,
      "failure_type": null,           // usage_limit | auth_expired | timeout | error
      "retry_after": null,            // ISO time if the tool told us; null for auth_expired
      "retry_after_is_guess": true,   // true when we estimated it (always true for OAuth workers)
      "retry_confidence": "low",      // high | medium | low
      "daily_uses": 0,
      "avoid_until": null,            // engine skips this worker before this time; null for auth_expired
      "notes": null                   // human-readable status note, e.g. "re-authentication required"
    }
  }
}
```

> **OAuth workers:** `retry_after` and `avoid_until` are **never set** for `auth_expired` failures — an auth failure requires human re-authentication, not a timed wait. Only `usage_limit` failures get a conservative `avoid_until`. Because OAuth usage-limit signals come from stderr text (not HTTP headers), `retry_after_is_guess` is `true` by default for all OAuth workers.

### CONTEXT_STATE.json
```json
{
  "schema_version": 1,
  "sessions": {
    "codex": {
      "turns": 0,
      "approx_input_bytes": 0,
      "started_at": null,
      "last_activity": null,
      "fresh_session_recommended": false,
      "reason": null
    }
  },
  "thresholds": { "max_turns": 25, "max_input_bytes": 400000, "stale_minutes": 120 }
}
```
> Note: for CLI workers you usually **cannot read real token counts**. These are proxies (turns, bytes of I/O sent, wall-clock staleness). Treat them as heuristics, not truth.

### config/workers.yaml
```yaml
schema_version: 1
workers:
  mock_worker:
    auth_method: none
    capabilities: [code_edit, docs, planning, routing]
    status: available
    command_template: null
  codex:
    auth_method: oauth          # session managed externally by codex CLI (e.g. `codex login`)
    capabilities: [code_edit, docs, refactor]
    status: available
    command_template: "codex {task}"   # adjust to match installed CLI version
  claude:
    auth_method: oauth          # session managed externally by claude CLI
    capabilities: [code_edit, docs, refactor, planning]
    status: future
    command_template: "claude {task}"
  cursor:
    auth_method: oauth          # session managed externally by cursor
    capabilities: [code_edit, refactor]
    status: future
    command_template: null      # TBD
```

> Workers with `status: future` are never routed to. They are placeholders for future phases.
> The hub **never reads, writes, stores, or logs** the OAuth token or session cookie for any worker. If a worker CLI prints a token to stdout/stderr, the run-log writer must redact it before persisting.

### config/ROUTING_RULES.yaml
```yaml
schema_version: 1
defaults:
  planner: mock_planner
  max_retries: 1
by_task_type:
  code_edit: { primary: codex,        fallbacks: [claude] }
  refactor:  { primary: codex,        fallbacks: [claude] }
  docs:      { primary: codex,        fallbacks: [claude] }
  planning:  { primary: planner,      fallbacks: [] }
  scrape:    { primary: local_script, fallbacks: [] }
  test:      { primary: local_script, fallbacks: [] }
worker_selection:
  prefer_available: true
  avoid_limited: true
  on_all_unavailable: safe_stop   # safe_stop | queue
```

### config/SAFETY_RULES.yaml
```yaml
schema_version: 1
mode: dry_run                    # dry_run | supervised | scheduled
approved_folders: [workspace, project, runs, approvals]
auto_execute_max_tier: 1         # only tiers 0/1 may run automatically
approval_required_tiers: [2, 3, 4]
tier2_preconditions:
  require_explicit_approval: true
  require_git_checkpoint: true
  require_validation: true
  require_bounded_scope: true
  forbid_path_substrings: [".env", "secrets", "id_rsa", ".ssh", ".git/config"]
approval_scope_required_fields: [task_id, tier, target_folder, allowed_files, allowed_worker, expires_at]
approval_timeout_minutes: 30     # on timeout in non-interactive runs: pause task, pick Tier 0/1 task or safe-stop
stop_file: STOP                  # if present, engine halts at next checkpoint
never_send_to_cloud_workers: [".env", "secrets", "credentials", "*.key", "*.token", "*.oauth"]
```

### approvals/APPROVAL_QUEUE.yaml  /  APPROVAL_DECISIONS.yaml
```yaml
# APPROVAL_QUEUE.yaml
schema_version: 1
pending:
  - request_id: A-0001
    task_id: T-0001
    tier: 3
    action_summary: "pip install requests in workspace venv"
    target_folder: workspace/example
    risk_notes: "modifies environment; not reversible by git"
    requested_at: 2026-06-26T14:31:00Z
```
```yaml
# APPROVAL_DECISIONS.yaml
schema_version: 1
decisions:
  - request_id: A-0001
    decision: approved          # approved | denied
    decided_by: human
    decided_at: 2026-06-26T14:40:00Z
    approved_scope:
      task_id: T-0001
      tier: 2
      target_folder: workspace/example
      allowed_files: ["workspace/example/utils.py"]
      allowed_worker: codex
      expires_at: 2026-06-26T16:40:00Z
    note: "ok, limited to the listed file"
```

### project/HANDOFF.md (frontmatter + body)
```markdown
---
handoff_id: H-0001
created_at: 2026-06-26T14:45:00Z
from_worker: codex
reason: usage_limit          # usage_limit | auth_expired | context_bloat | failure | manual
task_id: T-0001
git_sha: a1b2c3d
---
## Goal
<one paragraph: what we are trying to accomplish>
## Done so far
<bullet list>
## Current state / diff summary
<files changed + short diff summary, NOT full file dumps>
## Next concrete step
<the single next action a fresh worker should take>
## Relevant files
- workspace/example/utils.py
```
> The handoff packet is **scrubbed**: never include secrets, credentials, OAuth tokens, or unrelated proprietary content, because it may go to a cloud worker.

`DECISION_LOG.md`, `DAILY_REPORT.md`, `RISK_REVIEW.md` are free-form Markdown (append-only for the first two).

---

## 4. LangGraph workflow

### HubState (carried through the graph)
`cycle_id · mode · task · plan · chosen_worker · fallbacks · tier · approval_status · checkpoint · worker_result · validation · retries · max_retries · outcome · log_refs`

### Nodes
1. **intake** — load state files; check `STOP`; select next `ready` task from BACKLOG (respecting `depends_on`) or accept an injected task.
2. **plan** — `PlannerInterface.plan(state)` → steps, task_type, risk_tier, suggested_worker, fallbacks, confidence.
3. **route** — apply `ROUTING_RULES` + `LIMITS` + planner suggestion → `chosen_worker`, `fallbacks`; resolve final `tier`.
4. **safety_check** — resolve tier against `SAFETY_RULES` + `mode`; verify `target_folder` ∈ allowlist and not in forbidden substrings; decide Tier 0/1 safe-auto vs. Tier 2+ approval-required.
5. **approval_gate** *(conditional)* — required for Tier 2+. Write `APPROVAL_QUEUE` + `RISK_REVIEW`; read `APPROVAL_DECISIONS`; verify the approval scope matches the active task, tier, worker, target folder, allowed files, and expiration. Interactive → terminal prompt. Non-interactive + no valid decision within timeout → pause task, pick a Tier 0/1 task or safe-stop.
6. **checkpoint** — for any approved mutating action (tier ≥ 2): `git add -A && git commit` (or tag) in the workspace; record `git_sha`. Enables `git reset --hard` rollback.
7. **execute** — `WorkerAdapter.run(task, context)` → `WorkerResult`; stream logs into `runs/AGENT_RUNS/<ts>_<worker>_<task>/`. Run-log writer must redact tokens/credentials before persisting.
8. **validate** — run the validation matrix for the task type; write `runs/VALIDATION_RESULTS/...`; set pass/fail.
9. **record** — update `STATUS`, `BACKLOG` (status), `LIMITS`, `CONTEXT_STATE`, `DECISION_LOG`. On worker-limited/auth_expired/context-bloat, write `HANDOFF.md`.
10. **report** — append/update `DAILY_REPORT.md`.

### Edges
```
intake ──task?──> plan ──> route ──> safety_check
intake ──none──> report ──> END

safety_check ──Tier 0/1 safe-auto────> execute
safety_check ──Tier 2+ needs approval─> approval_gate
approval_gate ──approved──────────────> checkpoint
approval_gate ──denied/timeout────────> record(paused) ──> report ──> END

checkpoint ──> execute ──> validate ──> record
execute ─────> validate ──> record

record ──validation failed & retries left & fallback exists──> route   (retry on fallback worker)
record ──worker limited/auth_expired/bloated──> (HANDOFF written) ──> route or safe-stop
record ──otherwise──> report ──> END  (single-cycle)  | ──> intake (loop mode)
```

Keep the graph this small at first. LangGraph's checkpointing and conditional edges are the parts you actually want; don't add subgraphs/swarms until the linear loop is solid.

---

## 5. Interfaces

### Worker adapter
```python
@dataclass
class WorkerResult:
    status: Literal["success","failed","limited","blocked","timeout"]
    exit_code: int | None
    stdout: str
    stderr: str
    files_changed: list[str]
    diff: str | None
    usage_signal: dict | None     # any observable limit hints (headers, error text)
    context_signal: dict | None   # turns, approx bytes, freshness
    notes: str | None

class WorkerAdapter(ABC):
    name: str
    auth_method: Literal["oauth", "api_key", "none"]
    capabilities: set[str]                 # {"code_edit","docs","shell","scrape",...}
    def availability(self) -> Literal["available","limited","unknown","failed"]: ...
    def run(self, task, context, *, dry_run: bool = False) -> WorkerResult: ...
```
`mock_worker` creates a sentinel file or echoes a diff and returns `success`. Real adapters (e.g. `codex_worker`) wrap a CLI subprocess, parse exit codes / stderr for limit and auth signals, and compute the git diff. OAuth workers never receive credentials from the engine — they rely on the CLI's own session management.

### Planner interface
```python
@dataclass
class Plan:
    steps: list[str]
    task_type: str
    risk_tier: int
    suggested_worker: str | None
    fallbacks: list[str]
    confidence: float            # 0..1
    rationale: str

class PlannerInterface(ABC):
    def plan(self, state) -> Plan: ...
    def review(self, state, result: WorkerResult) -> "ReviewResult": ...
    def summarize(self, runs: list[dict]) -> str: ...
```
`mock_planner` builds a `Plan` deterministically from BACKLOG fields. Later, `qwen_planner` (on the 3090) and a `cloud_planner` (Claude/Codex-assisted) implement the same interface — the engine never changes.

---

## 6. Permission tiers & approval flow

| Tier | Scope | Default |
|---|---|---|
| 0 | read-only: inspect, diagnostics, reports, list files, read state, git status, summarize logs | **auto** |
| 1 | safe creation inside approved folders: logs, reports, handoffs, validation results, backups, planning docs | **auto** |
| 2 | bounded reversible edits inside approved folders: small code/doc/config edits, git-diffable, validated after | **approval required** |
| 3 | package installs, dependency changes, large refactors, changing automation/routing/safety, new integrations | **approval required** |
| 4 | destructive/system-level: deletes, broad permission changes, secrets, services, deploys, credentials, moves outside approved folders | **explicit approval; usually avoid** |

**Tier-2 execution preconditions (ALL must hold):**
explicit human approval for the specific task/scope · inside an approved folder · bounded and specific · expected files are known/discoverable · touches no secrets/credentials/system settings/global configs/package managers/services · git checkpoint captured first · validation runs after · a clear change log is written.

**Global mode switch (in SAFETY_RULES):** `dry_run` (plan + propose only, never execute workspace mutations) → `supervised` (Tier 0–1 auto; Tier 2+ approval-gated) → `scheduled` (Tier 0–1 unattended; Tier 2+ queued/paused). Autonomous Tier-2 mutation is intentionally not part of the current plan.

**Approval channel:** file queue + terminal prompt when interactive. Scheduled/non-interactive runs **never block forever**: write the request, pause that task, then pick a Tier 0/1 task or safe-stop, and surface it in `DAILY_REPORT.md`.

**Approval scope rule:** a Tier-2 approval is not a blanket permission. It must match task ID, tier, target folder, allowed files, chosen worker, and expiration. If the worker, target, file scope, or task intent changes, the engine must request approval again.

**Kill switch:** presence of `STOP` halts the engine at the next checkpoint.

---

## 7. Validation matrix

LLM review **supplements** tests; it never replaces them.

| Task type | Required checks | Gate |
|---|---|---|
| code_edit | git diff + changed-files summary; project test/build command if configured; lint/typecheck if available | fail → retry/fallback |
| refactor | all of code_edit, **plus** scope check (diff size/file count within plan) + LLM review of intent preservation | fail or out-of-scope → stop & flag |
| docs | spelling/format check; link & file-reference check; LLM review of accuracy | warn only (non-blocking) |
| scrape | schema validation of output; sample-row inspection; source-URL log; rate-limit/respectful-access note; duplicate check | schema fail → discard run |
| maint | read-only report first; **approval** before any change; backup before edits | approval-gated |
| planning | confirm output actually updated BACKLOG / STATUS / DECISION_LOG | missing update → fail |
| routing | log worker chosen + reason + fallback + usage/context state + confidence | record-only |
| test | exit code 0; capture pass/fail counts | non-zero → fail |

Every validation writes a small JSON/MD record to `runs/VALIDATION_RESULTS/`.

---

## 8. Routing, usage, and context rules

### Routing
1. Start from `ROUTING_RULES.by_task_type[type].primary`.
2. If the planner suggests a worker with confidence ≥ 0.6 and that worker is capable, prefer it.
3. Drop any worker whose `LIMITS.status ∈ {limited, failed}` or `avoid_until > now`.
4. If none available → `on_all_unavailable` (safe_stop or queue).

### Usage-limit tracking (OAuth/subscription workers are unreliable by nature)
Track per worker: `auth_method`, status, last_success, last_failure, failure_type, retry_after (if the tool told us), retry_after_is_guess, retry_confidence, daily_uses, avoid_until, notes.

On a mid-task limit hit: save logs → save git diff → update `LIMITS.json` → write `HANDOFF.md` → decide (switch worker / continue locally / safe-stop).

**Never invent reset times.** If unknown, apply a conservative default cooldown (e.g. `avoid_until = now + 60 min`, `retry_after_is_guess: true`, `retry_confidence: low`) and log that the timing is a guess.

### OAuth workers — auth vs. limit failures
All current cloud workers (Codex, Claude Code, Cursor) authenticate via OAuth managed entirely by the worker's own CLI. The engine never stores, injects, reads, or transmits OAuth tokens.

This creates two distinct failure classes that must be handled differently:

- **`failure_type: usage_limit`** — the worker's quota or rate limit was hit. Signals come from stderr text (not HTTP headers), so timing is always a guess. Set `avoid_until = now + 60 min`, `retry_after_is_guess: true`, `retry_confidence: low`. The engine will automatically retry after `avoid_until` passes.

- **`failure_type: auth_expired`** — the OAuth session has expired or the user is not logged in. Signals include phrases like "not authenticated", "please log in", "session expired", "unauthorized". **Do not set `retry_after` or `avoid_until`** — a timed retry will not help. Set `status: failed`, write `notes: "re-authentication required"`, surface in `DAILY_REPORT.md`, and do not attempt this worker again until a human re-authenticates and manually resets the flag in `LIMITS.json`.

A worker with `failure_type: auth_expired` is **never auto-cleared** by a successful run of any other worker or by the passage of time.

### Context / session tracking (heuristics only)
Recommend a fresh session when **any** threshold trips: `turns > max_turns`, `approx_input_bytes > max_input_bytes`, idle `> stale_minutes`, or repeated failures/looping detected. The planner may recommend it; the **engine** executes it: stop the bloated session → save logs → write a scrubbed `HANDOFF.md` (goal, done-so-far, diff summary, next step, files) → start a fresh worker session seeded only from the handoff.

---

## 9. Phased roadmap (refined)

Each phase has a **Definition of Done (DoD)**. Don't advance until DoD is met.

**Phase 0 — Design doc.** This file + `PROJECT_BRIEF.md`. *DoD: terms, state files, tiers, validation matrix, interfaces, routing, roadmap all written.* ✅ (this document)

**Phase 1 — local dev-box skeleton (mock everything).** Repo + folder structure; LangGraph linear loop; mock planner; mock worker; mock limits; all state files; daily report; handoff; basic validation; tests; README. Default `mode: dry_run`; Tier 0–1 can run in `supervised` only after tests pass. **No real worker, no real model.** *DoD: `python cli.py run` completes one Tier 0/1 mock cycle, writes all state/log files, queues any Tier-2 task for approval instead of executing it, and `pytest` is green.* ✅

**Phase 2 — First real worker (Codex, OAuth).** Add `codex_worker` adapter; run **one bounded** code/docs task end-to-end only after an explicit Tier-2 approval record exists; capture logs; run validation; update state; with git checkpoint + rollback. Codex authenticates via OAuth — no API key. `auth_expired` is handled as a distinct failure from `usage_limit`. *DoD: one real Tier-2 task requests approval, receives a matching approval decision, completes, validates, produces a usable diff, and has a clean rollback path. An `auth_expired` failure writes the correct LIMITS fields and is not auto-retried.*

**Phase 3 — Smarter routing.** Worker registry (`workers.yaml`) fully live; routing rules enforced; usage-limit tracking with OAuth-aware signal parsing; fallback behavior; context/session tracking + handoff-driven restarts. *DoD: forced limit/failure on the primary worker falls back safely for Tier 0/1 work; for Tier 2 work it either stays inside the approved scope or re-queues approval, and writes a correct HANDOFF.*

**Phase 4 — Real local planner (3090 box).** Install local runtime (llama.cpp/Ollama/vLLM); integrate Qwen-class planner behind `PlannerInterface`; test plan/route/review; keep cloud workers as bounded workers. *DoD: local planner drives a full cycle; quality compared against the cloud-assisted planner.* (Note: 4070 Super 12 GB can host only a smaller local model; the 30B planner belongs on the 24 GB 3090.)

**Phase 5 — More workers + automation.** Claude Code adapter (OAuth); Cursor Auto adapter (OAuth, if viable); local scraping scripts; scheduled runs; full approval-queue flow; (later) multi-project. *DoD: a scheduled unattended run does useful Tier 0/1 work and safely queues/defers Tier 2+ work.*

**Phase 6 — Dashboard (only after backend works).** Read-only first: run history, approvals, worker status, project state. *DoD: dashboard renders from the state files without the engine needing it.*

---

## 10. Glossary

- **Control plane** — the hub's own state files (`project/`, `approvals/`, `runs/`).
- **Workspace** — the project the hub edits; must be a git repo.
- **Worker** — a swappable adapter that does work (mock/codex/claude/cursor/script).
- **OAuth worker** — a cloud worker that authenticates via its own CLI OAuth session; the hub never handles its credentials.
- **Planner** — LLM behind an interface; advisory only.
- **Cycle** — one pass through the graph (intake → … → report).
- **Handoff** — a scrubbed packet that lets a fresh session resume cleanly.
- **Tier** — permission level 0–4 governing whether an action can run automatically or must be approval-gated.
- **auth_expired** — a failure type distinct from `usage_limit`; requires human re-authentication, not a timed retry.
