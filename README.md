# darktableAgent

`darktableAgent` is a custom darktable workspace with an integrated chat UI and a local Python agent server.

darktable remains the source of truth for rendering and image state. The backend returns structured edit operations, and darktable applies them through supported controls.

## Features

- Local custom build of darktable 5.4.1 in this repo
- Integrated darkroom chat panel
- Image-scoped chat sessions with reset/new chat
- Single-turn mode and live iterative agent mode
- Configurable live tool-call budget (default `15`, no hard cap)
- Fast mode toggle in UI
- Structured protocol shared between UI and backend
- Deterministic smoke test path using mock server responses

## Repository Layout

- `darktable/` custom darktable source and UI integration
- `server/` FastAPI service and Codex app-server bridge
- `shared/` request/response schema and protocol models
- `scripts/` build, run, and smoke-test helpers
- `docs/` protocol and design docs
- `assets/` local test assets

## Prerequisites

- Linux
- `python3` (3.10+)
- `uv` (recommended) or `pip`
- darktable build dependencies installed on the machine (use upstream darktable build docs for distro packages)
- `codex` CLI installed and authenticated for live model runs

## Setup

1. Install Python dependencies:

```bash
uv sync --extra dev
```

2. Build darktable:

```bash
./scripts/build_darktable_local.sh
```

## Run Locally

Start the backend:

```bash
./scripts/run_server.sh
```

Start darktable:

```bash
./scripts/run_darktable_local.sh
```

`run_darktable_local.sh` detaches by default and logs to `.darktable-local/darktable.log`. Use `--foreground` to keep it attached.

You can also use npm shortcuts:

```bash
npm run darktable:build
npm run darktable:start
npm run server:start
npm run build:serve
```

## Configuration

Backend defaults:

- Model: `gpt-5.3-codex`
- Reasoning effort: `high`
- Fast mode reasoning effort: `low`
- Backend timeout: `600s`

Useful environment variables:

- `DARKTABLE_AGENT_CODEX_MODEL`
- `DARKTABLE_AGENT_CODEX_REASONING_EFFORT`
- `DARKTABLE_AGENT_CODEX_FAST_MODE_MODEL`
- `DARKTABLE_AGENT_CODEX_FAST_MODE_REASONING_EFFORT`
- `DARKTABLE_AGENT_CODEX_TIMEOUT_SECONDS` (server -> codex timeout, default `600`)
- `DARKTABLE_AGENT_SERVER_TIMEOUT_SECONDS` (darktable -> server timeout, default `600`)

## Testing

Run the deterministic smoke test (uses mock responses by default):

```bash
./scripts/agent_exposure_smoke.sh
```

Or via npm:

```bash
npm run agent:smoke
```

Multi-turn smoke example:

```bash
MULTI_TURN_ENABLED=1 \
MULTI_TURN_MAX_TURNS=15 \
EXPECTED_MIN_REFINEMENT_PASSES=1 \
EXPECTED_MAX_REFINEMENT_PASSES=15 \
./scripts/agent_exposure_smoke.sh
```

## Protocol

Protocol details are documented in [docs/protocol-v1.md](docs/protocol-v1.md).

## License

TBD
