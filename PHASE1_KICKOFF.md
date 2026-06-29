# PHASE1_KICKOFF.md

The first safe Phase 1 task, written as a prompt you can paste into Claude Code on the Fedora KDE dev workstation. It scaffolds the skeleton only — mock everything, no real workers, no real model, and no Tier-2 automatic execution.

---

## Paste this into Claude Code

> **Task: scaffold the orchestration-hub skeleton (Phase 1, mocks only).**
>
> Build a Python project called `agent-hub` in the current empty directory. This is a file-based agent orchestrator. In this phase **everything is mocked** — no real LLM, no real coding workers, no network calls, no package installs beyond the listed dependencies, and no file writes outside this repo. Tier 2+ actions must be approval-gated, not auto-executed. Read the attached `PROJECT_BRIEF.md` and `ARCHITECTURE.md`; follow their folder structure, schemas, interfaces, tiers, validation matrix, and node/edge design exactly.
>
> **Deliverables:**
> 1. The folder tree from ARCHITECTURE.md §2 (`config/`, `project/`, `approvals/`, `runs/AGENT_RUNS/`, `runs/VALIDATION_RESULTS/`, `src/orchestrator/...`, `tests/`, `workspace/`), with `.gitkeep` where needed.
> 2. `requirements.txt` (or `pyproject.toml`) pinning `langgraph`, `pydantic`, `pyyaml`, `pytest`. Initialize a git repo and a separate git repo (or subfolder commit) for `workspace/`.
> 3. Starter state files populated from the schemas in ARCHITECTURE.md §3: `STATUS.json`, `BACKLOG.yaml` with two examples — one Tier-1 planning/report task that can complete a full safe mock cycle, and one Tier-2 `docs` task targeting `workspace/example` that must be queued for approval rather than auto-executed — `LIMITS.json`, `CONTEXT_STATE.json`, empty `DECISION_LOG.md`/`DAILY_REPORT.md`/`HANDOFF.md`, `config/ROUTING_RULES.yaml`, `config/SAFETY_RULES.yaml` (`mode: dry_run`, `auto_execute_max_tier: 1`, `approval_required_tiers: [2, 3, 4]`), `config/workers.yaml`, and empty approval files.
> 4. `src/orchestrator/io/state_files.py`: typed read/write helpers that load and **validate** each file against its schema (use pydantic), and refuse writes outside `approved_folders`.
> 5. `src/orchestrator/state.py`: the `HubState` model from §4.
> 6. Interfaces from §5: `planners/base.py` + `planners/mock_planner.py` (deterministic `Plan` from BACKLOG fields), `workers/base.py` + `workers/mock_worker.py` (for Tier 0/1 tasks, writes only inside the run log/control-plane output folders; for Tier 2 tasks without approval, returns `blocked`/`needs_approval` and does not mutate `workspace/`; returns a fake diff and `status="success"` only when execution is allowed).
> 7. `safety/tiers.py` + `safety/permissions.py`: resolve tier, enforce the §6 Tier-2 approval gate/preconditions and the approved-folder allowlist, honor the `STOP` file.
> 8. `tracking/limits.py` + `tracking/context.py`: update `LIMITS.json`/`CONTEXT_STATE.json` with the conservative-cooldown and threshold rules from §8.
> 9. `graph.py`: the LangGraph linear loop with the nodes/edges from §4 (intake → plan → route → safety_check → [approval_gate] → checkpoint → execute → validate → record → report). In `dry_run`, `execute` must not mutate `workspace/`. Tier 2+ must go through `approval_gate`; without a matching approval decision, it must pause/queue rather than execute.
> 10. Validation for the `planning`/Tier-1 example task and the `docs` task type per §7, writing records to `runs/VALIDATION_RESULTS/` where execution occurs, and writing an approval/blocked record when a Tier-2 task is queued.
> 11. `cli.py` with `run` (one cycle), `status`, and `backlog` subcommands.
> 12. `tests/`: cover state-file round-trip + schema validation, the approved-folder guard, tier resolution, approval gating for Tier 2, one full Tier-1 mock cycle (`run` produces a `runs/AGENT_RUNS/...` folder, a validation record, an updated `STATUS.json`, and an appended `DAILY_REPORT.md`), and one Tier-2 docs task that queues approval without mutating `workspace/`.
> 13. `README.md`: what this is, how to install, how to run a cycle, the folder map, and the current phase + what is intentionally mocked.
>
> **Constraints:** Do not implement real Codex/Claude/OpenClaw/Qwen adapters. Do not add a dashboard. Do not call any network or install anything beyond the four listed packages. Do not auto-approve or auto-execute Tier-2 workspace mutations. Keep modules small and readable. After scaffolding, run `pytest` and make it pass, then print the tree and the README.

---

## Definition of Done for Phase 1

- `pip install -r requirements.txt` then `python cli.py run` completes one full Tier-1 mock cycle with no errors.
- The Tier-1 cycle writes: a `runs/AGENT_RUNS/<ts>_mock_worker_T-0001/` log, a `runs/VALIDATION_RESULTS/` record, an updated `STATUS.json`, and an appended `DAILY_REPORT.md`.
- In default `dry_run`, no `workspace/` mutation occurs. In later explicitly approved Tier-2 runs, the only files mutated outside `project/`, `runs/`, `approvals/` may be inside `workspace/`. Any attempt to write elsewhere raises.
- `python cli.py status` and `python cli.py backlog` print readable summaries.
- `pytest` is green.
- `README.md` explains run steps, states clearly what is mocked, and states clearly that Tier 2+ is approval-gated, not automatic.

When this is met, move to Phase 2 (real Codex adapter, one bounded task, explicit Tier-2 approval, git checkpoint + rollback).
