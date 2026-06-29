# PHASE3_KICKOFF.md

The Phase 3 task. Builds on the Phase 2 skeleton — smarter routing, enforced fallbacks, context/session tracking, and handoff-driven restarts. Paste the prompt below into Claude Code on the Fedora KDE dev workstation.

---

## Paste this into Claude Code

> **Task: enforce routing rules, fallback behavior, and handoff-driven restarts (Phase 3).**
>
> Build on the Phase 2 `agent-hub/` skeleton. Phase 3 has one focused goal: make the routing layer fully live — routing rules enforced from `config/ROUTING_RULES.yaml`, usage-limit fallbacks active, context/session thresholds respected, and `HANDOFF.md` driving clean worker restarts. Everything outside routing and context tracking stays as-is unless a test breaks.
>
> Read `PROJECT_BRIEF.md`, `ARCHITECTURE.md`, `PHASE1_KICKOFF.md`, and `PHASE2_KICKOFF.md`. The interfaces, state schemas, tier rules, approval gate, checkpoint, and graph topology are already defined and tested. Add only what is listed below and change nothing else unless a test breaks.
>
> **Deliverables:**
>
> 1. **`src/orchestrator/nodes/workflow.py` — route node** — enforce `ROUTING_RULES.yaml` end-to-end:
>    - Apply `by_task_type[type].primary`; fall back to `fallbacks` list in order.
>    - Consult `LIMITS.json`: drop any worker whose `status ∈ {limited, failed}` or `avoid_until > now`.
>    - If the planner suggests a worker with `confidence ≥ 0.6` and that worker is capable and available, prefer it over the config primary.
>    - If no worker survives filtering: apply `on_all_unavailable` from the rules (`safe_stop` or `queue`); write a blocker to `STATUS.json` and surface it in `DAILY_REPORT.md`.
>    - Set `HubState.chosen_worker` and `HubState.fallbacks` (the surviving ordered list, primary excluded).
>    - Log the chosen worker, reason, fallback list, and `avoid_until` values to the run log.
>
> 2. **`src/orchestrator/nodes/workflow.py` — record node (fallback wiring)** — extend the existing record node:
>    - On `WorkerResult.status ∈ {failed, limited, timeout}` with retries remaining and a non-empty `HubState.fallbacks`: pop the next fallback as `chosen_worker`, decrement `retries`, loop back to `execute` (not `route`) via the existing retry edge.
>    - For Tier 2 tasks: if the fallback worker differs from the one named in the approval decision's `allowed_worker`, do **not** execute — pause the task (write `status: paused` to BACKLOG), write a new entry to `APPROVAL_QUEUE.yaml` naming the fallback worker, and route to `report` instead of `execute`. The original approval is not valid for a different worker.
>    - After exhausting all fallbacks: write `status: blocked` to the task in BACKLOG, write a blocker to `STATUS.json`, append to `DAILY_REPORT.md`, and route to `report → END`.
>
> 3. **`src/orchestrator/tracking/context.py`** — extend to actively trigger handoffs:
>    - After each `execute`, call `context.update(worker, worker_result)` to increment `turns` and `approx_input_bytes` (proxy: len of the task description string sent).
>    - After updating, call `context.check_thresholds(worker)` → returns `(should_handoff: bool, reason: str | None)`. Trigger when **any** of the following trips: `turns > max_turns`, `approx_input_bytes > max_input_bytes`, idle `> stale_minutes` (wall-clock since `last_activity`), or the same worker has failed ≥ 2 consecutive times in this session.
>    - Write the updated `CONTEXT_STATE.json` after each check.
>    - `check_thresholds` must never raise — return `(False, None)` on any read error.
>
> 4. **`src/orchestrator/nodes/workflow.py` — record node (handoff wiring)** — extend the record node to call `context.check_thresholds` after every execution:
>    - If `should_handoff` is true: write a scrubbed `HANDOFF.md` using the template from `ARCHITECTURE.md §3` (frontmatter + Goal / Done so far / Current state / Next concrete step / Relevant files). Populate `reason` from `check_thresholds`. Set `fresh_session_recommended: true` and `reason` in `CONTEXT_STATE.json`. Do **not** auto-restart the worker — surface the handoff in `DAILY_REPORT.md` and route to `report → END`. A human or the next cycle will pick it up.
>    - The handoff writer must scrub: no secrets, no credentials, no OAuth tokens, no unrelated files. Only include the task description, the git diff summary, the changed-file list, and the one next step.
>    - The `HANDOFF.md` must include the `git_sha` from `HubState.checkpoint` (if set).
>
> 5. **`src/orchestrator/io/state_files.py`** — add a `write_approval_queue_entry(request)` helper. Must append (not overwrite) to `APPROVAL_QUEUE.yaml`, validating against the schema. Existing entries must be preserved.
>
> 6. **`tests/`** — add the following test modules. All must pass without any network calls:
>    - **`test_routing.py`**: primary worker available → chosen; primary `avoid_until` in the future → fallback chosen; primary `status: failed` → fallback chosen; planner suggestion with confidence ≥ 0.6 and capable/available worker → planner suggestion wins; all workers unavailable → `safe_stop` outcome with blocker written to `STATUS.json`; worker order in `fallbacks` matches config after primary is excluded.
>    - **`test_fallback.py`**: Tier-0/1 task, primary fails, fallback available → fallback executes and produces success result; Tier-0/1 task, all workers fail → task marked `blocked` in BACKLOG; Tier-2 task, primary fails, fallback worker differs from `allowed_worker` in approval → task paused, new entry appended to `APPROVAL_QUEUE.yaml`, workspace not mutated; Tier-2 task, primary fails, fallback worker matches `allowed_worker` → fallback executes (mock) successfully.
>    - **`test_context_tracking.py`**: `turns` increments correctly per `update` call; `approx_input_bytes` accumulates; `check_thresholds` returns `(True, "turns")` when turns exceed `max_turns`; `check_thresholds` returns `(True, "stale")` when `last_activity` is beyond `stale_minutes`; `(True, "consecutive_failures")` after ≥ 2 consecutive failures from the same worker; `(False, None)` when no threshold is tripped; `CONTEXT_STATE.json` written after each update.
>    - **`test_handoff.py`**: after a threshold trip, `HANDOFF.md` is written with correct frontmatter fields (`handoff_id`, `reason`, `task_id`, `git_sha`); body contains Goal, Done so far, Current state, Next concrete step, Relevant files sections; no credential or token patterns present in the output; `fresh_session_recommended: true` is set in `CONTEXT_STATE.json`; task not re-executed after handoff written.
>    - **`test_phase3_cycle.py`**: end-to-end mock of a full Phase 3 cycle — primary worker `avoid_until` active, fallback picked, Tier-1 task executes successfully, HANDOFF not written (thresholds not tripped), DAILY_REPORT appended, STATUS updated. A second variant: turns threshold tripped mid-cycle, HANDOFF written, task not re-executed.
>
> 7. **`README.md`** — add a Phase 3 section after the Phase 2 section:
>    - Explain that routing rules are now enforced from `config/ROUTING_RULES.yaml`.
>    - Explain fallback behavior: workers are skipped if `status: failed/limited` or `avoid_until > now`; next available fallback is tried.
>    - Explain Tier-2 fallback constraint: a different fallback worker requires a new approval decision.
>    - Explain the handoff mechanism: when a context threshold trips (turns, bytes, staleness, consecutive failures), `HANDOFF.md` is written and the session stops cleanly; the next cycle or human picks up from the handoff.
>    - Note that `on_all_unavailable: safe_stop` is the default and means the engine will not block indefinitely — it writes a blocker and exits the cycle cleanly.
>
> **Constraints:**
> - Do not implement the Claude Code or Cursor adapters — stubs in `workers.yaml` only.
> - Do not add a dashboard, real network calls, or new dependencies beyond what Phase 2 already has.
> - Do not auto-restart worker sessions — handoffs surface in `DAILY_REPORT.md` for human or next-cycle pickup only.
> - Do not auto-approve or auto-execute any Tier-2 action that now targets a different worker than the original approval named.
> - Never store, log, or transmit OAuth tokens or credentials anywhere — including the handoff body.
> - `pytest` must be green after all changes.

---

## Definition of Done for Phase 3

- The route node reads `ROUTING_RULES.yaml` and `LIMITS.json` on every cycle. A worker with `avoid_until > now` or `status ∈ {failed, limited}` is never chosen as primary; the first available fallback is used instead.
- A planner suggestion with `confidence ≥ 0.6` for a capable, available worker overrides the config primary.
- When all workers are unavailable, the engine writes a blocker to `STATUS.json`, appends to `DAILY_REPORT.md`, and exits the cycle cleanly — it does not block or loop.
- For Tier 0/1 tasks: primary failure → fallback executes transparently. All fallbacks exhausted → task marked `blocked`.
- For Tier 2 tasks: primary failure where the fallback worker differs from `allowed_worker` → task paused, new entry appended to `APPROVAL_QUEUE.yaml`, workspace not mutated.
- `context.update` and `context.check_thresholds` run after every execution. `CONTEXT_STATE.json` is updated each cycle.
- Any of the four threshold conditions (turns, bytes, staleness, consecutive failures) produces a correctly populated `HANDOFF.md` with valid frontmatter, all required body sections, no credentials, and the correct `git_sha`.
- After a handoff is written, the cycle ends — no re-execution, no auto-restart.
- `pytest` is green.
- `README.md` explains routing enforcement, fallback behavior, Tier-2 fallback constraint, and the handoff mechanism.

When this is met, move to Phase 4 (real local planner on the 3090 box via `PlannerInterface`; Qwen-class model; plan/route/review quality tested against mock planner).
