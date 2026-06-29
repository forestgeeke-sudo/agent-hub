# PROJECT_BRIEF.md

> Stable description of the project. Change this rarely. Everything else (status, backlog, logs) is generated and changes often.

## What this is

A **local AI agent orchestration hub**: a desktop system that coordinates a local LLM, cloud coding workers (Claude Code, Codex), OpenClaw, and local scripts to plan, execute, document, validate, and follow up on complex tasks.

## Architecture in one sentence

A deterministic **Python + LangGraph workflow engine** is the control plane; an **LLM planner** is advisory only (plan / route / review / summarize); **workers are swappable hands**; **state lives in files**.

## Non-negotiable design principles

1. **Decision vs. execution are separate.** The LLM proposes; the engine disposes.
2. **State lives in files**, not in chat memory.
3. **Model-agnostic and upgradeable.** The planner is behind an interface.
4. **Workers are swappable adapters** behind one interface.
5. **Two separate filesystems:** control plane vs. workspace.
6. **Safety is deterministic, not LLM-judged.**
7. **Tier-2 work is approval-gated.**
8. **Build the smallest working skeleton first.**
