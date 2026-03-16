# darktableAgent

`darktableAgent` adds an AI-assisted editing workflow to darktable.

This repository contains:
- a custom darktable build with an integrated chat UI in darkroom
- a local Python backend that plans edits as structured operations
- a shared protocol layer between the UI and backend

darktable remains the source of truth for image state and final rendering. The backend does not edit images directly; it returns structured operations, and darktable applies them through supported controls.

## Project Status

- Active prototype / experimental integration
- Linux-first development workflow
- Designed for local use: darktable talks to a backend running on your machine

## What It Does

- Adds a darkroom chat panel for edit requests
- Supports single-turn planning and live iterative edit sessions
- Streams progress during live runs
- Applies edits through a constrained capability catalog instead of free-form UI scripting
- Supports deterministic smoke tests with mock backend responses

## Repository Layout

- `darktable/` custom darktable source tree and UI integration
- `server/` FastAPI backend and Codex bridge
- `shared/` protocol models and schema
- `scripts/` local build, run, lint, and smoke-test helpers
- `docs/` protocol and design notes
- `assets/` sample test assets

## Architecture

1. darktable captures the current image state, editable settings, preview, and session metadata.
2. The backend sends that context to a planning model.
3. The model returns structured edit operations.
4. darktable validates and applies those operations through supported controls.

For live runs, the backend can stage iterative edits, refresh preview/state, and continue refining within the same turn.

## Current Scope And Limits

Today the agent mainly supports parameter-backed darkroom module controls:
- numeric settings
- enum/choice settings
- boolean settings
- module enable/disable toggles

It does not yet cover every darktable action type. Complex UI actions such as graph editors, picker tools, command buttons, and some non-darkroom controls are still being tracked as follow-up work.

## Prerequisites

- Linux
- `python3` 3.10+
- `uv`
- darktable build dependencies for your distro
- Linux CLI tools used by local scripts: `ninja`, `curl`, GNU `timeout`
- `codex` CLI installed and authenticated for live model-backed runs
- optional: `xvfb-run` for headless smoke tests

Use upstream darktable build docs for the system packages needed to build darktable itself.

## Setup

Before building or running the project, make sure the required local tools are available:
- `codex` CLI
- `ninja`
- `curl`
- GNU `timeout`
- optional: `xvfb-run` for headless smoke runs

Install Python dependencies:

```bash
uv sync --extra dev
```

Build the bundled darktable tree:

```bash
./scripts/build_darktable_local.sh
```

## Running Locally

Start the backend:

```bash
./scripts/run_server.sh
```

Start darktable:

```bash
./scripts/run_darktable_local.sh
```

`./scripts/run_darktable_local.sh` detaches by default and logs to `.darktable-local/darktable.log`. Use `--foreground` to keep it attached.

There are also npm convenience commands:

```bash
npm run darktable:build
npm run darktable:start
npm run server:start
npm run build:serve
```

## Configuration

The default local topology assumes:
- backend host: `127.0.0.1`
- backend port: `8001`
- chat endpoint: `http://127.0.0.1:8001/v1/chat`

Useful server environment variables:
- `DARKTABLE_AGENT_CODEX_APP_SERVER_CMD`
- `DARKTABLE_AGENT_CODEX_MODEL`
- `DARKTABLE_AGENT_CODEX_REASONING_EFFORT`
- `DARKTABLE_AGENT_CODEX_FAST_MODE_MODEL`
- `DARKTABLE_AGENT_CODEX_FAST_MODE_REASONING_EFFORT`
- `DARKTABLE_AGENT_CODEX_TIMEOUT_SECONDS`
- `DARKTABLE_AGENT_SERVER_TIMEOUT_SECONDS`
- `DARKTABLE_AGENT_SERVER_URL`
- `DARKTABLE_AGENT_SERVER_HOST`
- `DARKTABLE_AGENT_SERVER_PORT`
- `HOST`
- `PORT`

Useful local build/run overrides:
- `BUILD_DIR`
- `INSTALL_PREFIX`
- `RUNTIME_DIR`
- `PYTHON_BIN`

darktable-side backend routing can also be configured through the darktable setting `plugins/ai/agent/server_url` or the corresponding environment/config path used by the local scripts.

Live model-backed runs require a working `codex` CLI install and auth state, not just the package on disk.

## Testing

Run Python tests:

```bash
uv run pytest server/tests
```

Run Python type checking:

```bash
uvx pyright server shared
```

Run all local pre-commit checks:

```bash
uvx pre-commit run --all-files
```

Run the deterministic smoke test (mock responses by default):

```bash
./scripts/agent_exposure_smoke.sh
```

Or:

```bash
npm run agent:smoke
```

Example multi-turn smoke run:

```bash
MULTI_TURN_ENABLED=1 \
MULTI_TURN_MAX_TURNS=15 \
EXPECTED_MIN_REFINEMENT_PASSES=1 \
EXPECTED_MAX_REFINEMENT_PASSES=15 \
./scripts/agent_exposure_smoke.sh
```

## Protocol

Protocol details are documented in `docs/protocol-v1.md`.

## Related Notes

- The repo includes a custom darktable source tree under `darktable/`.
- Some test hooks and local-run defaults are intentionally development-oriented.
- Public-facing follow-up work for unsupported action classes is tracked in the GitHub issue tracker.

## License

Top-level project licensing is still being finalized. The bundled `darktable/` subtree retains upstream darktable licensing and notices.
