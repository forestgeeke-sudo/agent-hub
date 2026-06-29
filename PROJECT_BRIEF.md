# PROJECT_BRIEF.md

> Stable description of the project. Change this rarely. Everything else (status, backlog, logs) is generated and changes often.

## What this is

A **local AI agent orchestration hub**: a desktop system that coordinates a local LLM, cloud coding workers (Claude Code, Codex, Cursor), and local scripts to plan, execute, document, validate, and follow up on complex tasks.

## Architecture in one sentence

A deterministic **Python + LangGraph workflow engine** is the control plane; an **LLM planner** is advisory only (plan / route / review / summarize); **workers are swappable hands**; **state lives in files**.

## Non-negotiable design principles

1. **Decision vs. execution are separate.** The LLM proposes; the engine disposes. The LLM never launches workers, enforces safety, or writes final state. The engine does all of that deterministically.
2. **State lives in files, not in chat memory or any one tool's internal state.** Any session can be reconstructed from the files on disk.
3. **Model-agnostic and upgradeable.** The planner is behind an interface so the backend (mock → cloud → local Qwen) can be swapped without touching the engine.
4. **Workers are swappable adapters** behind one interface. Adding a worker never changes the engine.
5. **Two separate filesystems:** the hub's **control plane** (its own state) and the **workspace** (the project the hub operates *on*). The hub may only write inside an explicit allowlist of approved folders.
6. **Safety is deterministic, not LLM-judged.** Permission tiers, the approved-folder allowlist, the approval gate, and the kill switch are enforced by code, never by model opinion.
7. **Tier-2 work is approval-gated.** Only Tier 0–1 work may run automatically. Tier 2+ actions require an explicit approval record before any mutation, even when the system is otherwise running in supervised or scheduled mode.
8. **Cloud workers authenticate via OAuth managed externally.** The hub never stores, injects, logs, or transmits OAuth tokens, session cookies, or API keys. Auth is handled entirely by each worker's own CLI (e.g. `codex login`, `claude login`). An `auth_expired` failure requires human re-authentication; the engine flags it and will not auto-retry.
9. **Build the smallest working skeleton first.** No dashboard first, no agent swarm first, no real autonomous model launching in the prototype.

## Hardware staging

- **Prototype / dev (now):** Fedora KDE Linux workstation — the active development and testing machine. No local GPU model in use here → develop with the **mock planner + cloud workers**. The eventual deployment target is the Pop!_OS box below.
- **Stage 1 box (deploy target):** Legion T5, Ryzen 9 5900X, **RTX 4070 Super 12 GB**, 32 GB RAM, Pop!_OS 22.04. 12 GB VRAM is **too small for a 30B planner at good quant** → run small local models (7–14B) here, or keep planning in the cloud.
- **Upgraded box:** same tower with **RTX 3090 24 GB**, 64 GB RAM. **This is the home of the real local 30B planner.**

## Worker roles (target)

- **Default planner / reviewer / router:** local Qwen-class coding model (later, on the 3090).
- **Main coding worker:** Codex CLI — authenticates via OAuth (no API key).
- **Higher-reasoning review / fallback:** Claude Code — authenticates via OAuth (no API key).
- **Cursor Auto:** future worker candidate — authenticates via OAuth (no API key). Status: placeholder only until Phase 5.
- **Local scripts:** validation, tests, scraping, git checks, file checks, scheduled reports.

> All cloud workers (Codex, Claude Code, Cursor) use OAuth subscription accounts. Usage-limit signals come from stderr text rather than HTTP headers and must be treated as heuristic guesses. Auth failures (`auth_expired`) are distinct from usage limits and require human re-authentication before the worker can be used again.

## Out of scope for the prototype

Dashboard, multi-agent swarms, real autonomous model launching, automatic Tier-2 execution/approval, package installs, anything outside approved folders, anything touching secrets or system settings, storing or injecting OAuth tokens.
