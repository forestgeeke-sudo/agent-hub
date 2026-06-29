# PHASE2_KICKOFF.md

The Phase 2 task. Builds on the Phase 1 skeleton — one real worker, one real Tier-2 cycle, OAuth auth throughout. Paste the prompt below into Claude Code on the Fedora KDE dev workstation.

---

## Paste this into Claude Code

> **Task: add the Codex OAuth worker and complete one real Tier-2 cycle (Phase 2).**
>
> Build on the Phase 1 `agent-hub/` skeleton. Phase 2 has one focused goal: run a single real Tier-2 task end-to-end using the Codex CLI (authenticated via OAuth — never via an API key), backed by a real approval record, a git checkpoint, and a verified rollback path. Everything else stays mocked.
>
> Read `PROJECT_BRIEF.md`, `ARCHITECTURE.md`, and `PHASE1_KICKOFF.md`. The folder structure, interfaces, state schemas, tier rules, and graph topology are already defined. Add only what is listed below and change nothing else unless a test breaks.
>
> **Deliverables:**
>
> 1. **`config/workers.yaml`** — update with the following entries. Add an `auth_method` field (`oauth | api_key | none`) and a `command_template` field (the CLI invocation pattern, with `{task}` as the placeholder for the task description string). Example shape:
>    ```yaml
>    schema_version: 1
>    workers:
>      mock_worker:
>        auth_method: none
>        capabilities: [code_edit, docs, planning, routing]
>        status: available
>        command_template: null
>      codex:
>        auth_method: oauth
>        capabilities: [code_edit, docs, refactor]
>        status: available
>        command_template: "codex {task}"   # adjust if actual CLI syntax differs
>      claude:
>        auth_method: oauth
>        capabilities: [code_edit, docs, refactor, planning]
>        status: future
>        command_template: "claude {task}"
>      cursor:
>        auth_method: oauth
>        capabilities: [code_edit, refactor]
>        status: future
>        command_template: null             # TBD
>    ```
>    `future` workers are never routed to; they are placeholders only.
>
> 2. **`src/orchestrator/workers/codex_worker.py`** — a concrete `WorkerAdapter` subclass. Requirements:
>    - **No API key injection.** The OAuth session is managed entirely by the Codex CLI itself (via its own login/keychain). The adapter only invokes the subprocess; it never reads, writes, or passes tokens.
>    - Invokes `command_template` (from `workers.yaml`) as a subprocess inside `workspace/`, capturing stdout and stderr line-by-line, streaming both to the run log folder (`runs/AGENT_RUNS/<ts>_codex_<task_id>/`).
>    - After execution, runs `git diff HEAD` inside `workspace/` and populates `WorkerResult.diff` and `WorkerResult.files_changed`.
>    - **Parses stderr for three distinct signal classes:**
>      - `failure_type: usage_limit` — matches phrases such as: `"rate limit"`, `"quota"`, `"too many requests"`, `"429"`. Sets `avoid_until = now + 60 min`, `retry_after_is_guess: true`, `retry_confidence: low`.
>      - `failure_type: auth_expired` — matches phrases such as: `"not authenticated"`, `"please log in"`, `"login required"`, `"session expired"`, `"unauthorized"`, `"401"`. Sets `status: failed`, `notes: "re-authentication required before retrying"`. **Never sets `retry_after` or `avoid_until`** — an auth failure requires human action, not a timed wait.
>      - `failure_type: error` — any other non-zero exit code.
>    - Respects `dry_run=True`: if the flag is set, the adapter **must not** invoke the subprocess or mutate `workspace/`. Return a `WorkerResult` with `status="blocked"`, `notes="dry_run active"`.
>    - Populates `WorkerResult.usage_signal` (parsed limit/auth hints) and `WorkerResult.context_signal` (turn count proxy: increment a turns counter per call; bytes-sent: length of the task string sent).
>    - Note in a module-level docstring: *"The exact `command_template` format may need adjustment once the installed Codex CLI version is confirmed. Update `workers.yaml` rather than this file."*
>
> 3. **`tests/fixtures/codex_stderr/`** — add at least four plain-text fixture files representing realistic Codex CLI stderr output:
>    - `normal_completion.txt` — a normal successful run (exit 0, some progress lines)
>    - `usage_limit.txt` — a usage/rate-limit error (non-zero exit, limit phrase in stderr)
>    - `auth_expired.txt` — a session/auth error (non-zero exit, auth phrase in stderr)
>    - `generic_error.txt` — an unrelated error (non-zero exit, no limit or auth phrase)
>    Write realistic-looking content; these do not need to be real captures. The `codex_worker` tests must use these fixtures and must not make any network calls.
>
> 4. **`src/orchestrator/tracking/limits.py`** — extend to handle `auth_expired` as a distinct case:
>    - On `auth_expired`: set `status: failed`, `failure_type: auth_expired`, leave `retry_after: null`, leave `avoid_until: null`, write `notes: "re-authentication required"`. Log a warning that the engine will not retry this worker until a human clears the flag.
>    - On `usage_limit` without a machine-readable `retry_after`: apply the conservative default: `avoid_until = now + 60min`, `retry_after_is_guess: true`, `retry_confidence: low`.
>    - Clearing a `failed`/`auth_expired` worker back to `available` requires an explicit human action (or a future CLI command) — never auto-clear.
>    - Add a `notes` field to the LIMITS.json schema (nullable string). Update the Pydantic model in `state_files.py` accordingly.
>
> 5. **`approvals/APPROVAL_DECISIONS.yaml`** — populate one real approval decision for the Tier-2 `docs` task in the backlog (T-0001 or whatever ID Phase 1 used). All required scope fields must be present: `task_id`, `tier: 2`, `target_folder: workspace/example`, `allowed_files: ["workspace/example/utils.py"]`, `allowed_worker: codex`, `expires_at` set at least 2 hours ahead of a reference timestamp. This is the record the engine reads in the approval gate.
>
> 6. **`src/orchestrator/nodes/approval_gate.py`** (or equivalent) — verify and patch as needed:
>    - Reads `APPROVAL_DECISIONS.yaml`; finds the decision matching `request_id` / `task_id`.
>    - Validates **all** scope fields: task ID, tier, target folder, allowed files, allowed worker, and expiration. Any single mismatch → pause task, write `status: paused` to BACKLOG, skip to `record` then `report`, do not execute.
>    - Specific mismatch cases that must each pause independently: (a) `expires_at` is in the past, (b) `allowed_worker` does not match the `chosen_worker` in `HubState`, (c) the task's target file is not in `allowed_files`, (d) no decision record exists at all.
>
> 7. **`src/orchestrator/nodes/checkpoint.py`** (or equivalent) — verify and patch as needed:
>    - Runs `git add -A && git commit -m "checkpoint: {task_id} pre-execution"` inside `workspace/` before any Tier-2 execution.
>    - Records the resulting `git_sha` in `HubState.checkpoint`.
>    - The test (see below) must confirm that after checkpoint + execution + `git reset --hard <sha>`, the workspace file is back to its pre-execution content.
>
> 8. **`tests/`** — add or extend the following test modules. All must pass without any network calls:
>    - **`test_codex_worker.py`**: loads each stderr fixture; asserts correct `WorkerResult.status`, `failure_type`, and signal fields for each case; asserts `dry_run=True` returns `status="blocked"` and makes no subprocess call; asserts `WorkerResult.files_changed` and `diff` are populated on a successful mock run (use `subprocess` mock / `monkeypatch`).
>    - **`test_approval_gate.py`**: valid approval → proceeds to checkpoint; expired `expires_at` → pauses; wrong `allowed_worker` → pauses; file not in `allowed_files` → pauses; no decision record → pauses.
>    - **`test_checkpoint.py`**: write a dummy file to `workspace/`; run checkpoint node; mutate the file; call `git reset --hard <sha>`; assert file content is restored.
>    - **`test_limits_oauth.py`**: `auth_expired` result → `status: failed`, `retry_after` is null, `avoid_until` is null, `notes` contains "re-auth"; `usage_limit` result → `avoid_until` is ~60 min from now, `retry_after_is_guess: true`, `retry_confidence: low`; `available` worker with prior `auth_expired` flag is not auto-cleared by a successful run of a different worker.
>    - **`test_phase2_cycle.py`**: end-to-end mock of a full Tier-2 cycle using `codex_worker` with a `success` fixture and a valid approval decision: assert `runs/AGENT_RUNS/` folder created, `DAILY_REPORT.md` appended, `STATUS.json` updated, `BACKLOG.yaml` task marked `done`, `LIMITS.json` updated.
>
> 9. **`README.md`** — add a Phase 2 section after the Phase 1 section:
>    - Note that Codex authenticates via OAuth; no API key is stored in the repo or environment.
>    - Explain how to authenticate externally before running (`codex login` or equivalent).
>    - Explain `auth_expired` behavior: the engine flags the worker as `status: failed`, pauses the task, and will not retry until a human re-authenticates and manually resets `LIMITS.json`.
>    - Note that `command_template` in `workers.yaml` may need to be updated to match the installed Codex CLI version.
>
> **Constraints:**
> - Do not implement the Claude Code or Cursor adapters — stubs in `workers.yaml` only.
> - Do not store, log, or transmit any OAuth token, session cookie, or credential anywhere in the codebase, state files, or logs. If the worker CLI prints a token to stdout/stderr, redact it before writing to the run log (match common token patterns and replace with `[REDACTED]`).
> - Do not auto-approve or auto-execute any Tier-2 action without a valid matching decision record.
> - Do not add a dashboard, network calls, or any new dependencies beyond what Phase 1 already has.
> - `pytest` must be green after all changes.

---

## Definition of Done for Phase 2

- `codex_worker` invokes the Codex CLI subprocess with the `command_template` from `workers.yaml`. No API key is touched anywhere.
- All four stderr fixture tests pass without network calls: correct `failure_type` and signal fields for `success`, `usage_limit`, `auth_expired`, and `generic_error`.
- A Tier-2 task with a valid matching approval decision completes a full cycle: approval validated → git checkpoint committed → codex executed → diff captured → validation run → `STATUS.json` + `BACKLOG.yaml` + `LIMITS.json` updated → `DAILY_REPORT.md` appended.
- `git reset --hard <sha>` in `workspace/` cleanly undoes the Tier-2 mutation (verified by `test_checkpoint.py`).
- An `auth_expired` failure writes `status: failed`, `failure_type: auth_expired`, `retry_after: null`, `avoid_until: null`, `notes: "re-authentication required"` to `LIMITS.json`. It is not auto-cleared.
- A `usage_limit` failure writes `avoid_until ≈ now + 60min`, `retry_after_is_guess: true`, `retry_confidence: low`.
- All four approval scope mismatch cases (expired, wrong worker, wrong file, no record) each pause the task rather than executing.
- `pytest` is green.
- `README.md` explains OAuth requirement, `auth_expired` behavior, and `command_template` adjustment note.

When this is met, move to Phase 3 (worker registry live, routing rules enforced, usage-limit fallback, context/session tracking + handoff-driven restarts).
