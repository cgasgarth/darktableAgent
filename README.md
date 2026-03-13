# darktableAgent

darktableAgent is an integrated AI workspace for darktable.

The goal is to bring conversational editing, agent-driven workflows, and structured automation directly into the darktable experience while keeping image processing inside darktable itself. The UI acts as the client, a Python service handles orchestration, and the backend model provider supplies reasoning and action planning.

## Overview

darktableAgent is built around three ideas:

- darktable remains the source of truth for image state and rendering
- the AI layer returns structured editing intent and action results, not raw UI automation
- the backend is designed for agent orchestration, auditability, and repeatable editing workflows

This repository is organized as a monorepo so the desktop integration, backend service, shared contracts, and supporting documentation can evolve together.

## Repository Layout

- `darktable/` - darktable application code and integrated in-UI agent experience
- `server/` - Python backend for orchestration, tool execution, conversation handling, and model/provider integration
- `shared/` - shared schemas, protocol definitions, and cross-boundary contracts
- `docs/` - architecture notes, design docs, and implementation plans
- `scripts/` - local development and bootstrap helpers

## Architecture Direction

The current intended flow is:

1. A user interacts with the agent inside darktable.
2. darktable sends structured chat and editing context to the Python server.
3. The Python server calls the model backend and decides what actions should be taken.
4. The server returns structured responses describing requested edits, execution status, and readback state.
5. darktable applies or displays those results inside the integrated UI.

## Project Status

This repository is in its initial setup stage.

- The monorepo structure is in place.
- Directory boundaries are defined.
- `darktable/` now contains the official darktable 5.4.1 stable source release as plain source files, not a nested git clone.
- The custom local build installs into `darktable/.install-5.4.1`.
- `server/` and `shared/` currently contain a mock chat/edit contract that is useful for wiring darktable to a real local server. The current mock applies exposure through darktable's action system, but it should not be treated as the final agent contract.

## Planned Priorities

- establish the shared client/server protocol
- build the Python orchestration service
- integrate an in-UI chat surface inside darktable
- add structured action execution and readback flows
- expand into richer editing, masking, and workflow automation features

## Local darktable workflow

- Rebuild the local custom darktable with `./scripts/build_darktable_local.sh`
- Run the local custom darktable with `./scripts/run_darktable_local.sh`
- Run the mock server-to-darktable exposure smoke check with `./scripts/mock_exposure_smoke.sh`
- Or use the root npm scripts: `npm run darktable:build`, `npm run darktable:start`, `npm run darktable:build-and-start`, and `npm run mock:smoke`
- The launcher keeps its config, cache, and library isolated under `.darktable-local/` so it does not reuse a system darktable profile
- The build uses `darktable/build-5.4.1` for build artifacts and `darktable/.install-5.4.1` for the runnable install tree

## License

TBD
