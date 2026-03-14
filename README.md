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
3. The Python server calls the Codex app server and decides what actions should be taken.
4. The server returns structured responses describing requested edits, execution status, and readback state.
5. darktable applies or displays those results inside the integrated UI.

## Project Status

This repository is in its initial agent-integration stage.

- The monorepo structure is in place.
- Directory boundaries are defined.
- `darktable/` now contains the official darktable 5.4.1 stable source release as plain source files, not a nested git clone.
- The custom local build installs into `darktable/.install-5.4.1`.
- `server/` now bridges darktable requests into the Codex app server and returns structured operation plans back to darktable.
- `shared/` defines the live chat/edit contract used between darktable and the local Python server.
- darktable now sends a 1k rendered preview, histogram, metadata, history, and dynamically discovered editable controls with each request.
- chat sessions are now image-scoped in darkroom, with one conversation surface per image plus a `new chat` reset action.

## Planned Priorities

- keep expanding the editable control surface beyond the first working operations
- improve the persistent chat UI and make it easier to keep open while editing
- add richer multi-step plans, previews, and safer apply/revert flows
- expand into masking, local adjustments, and broader workflow automation

## Current Request Payload

Each live `POST /v1/chat` request now includes:

- app, image, conversation, and turn session IDs
- the active image metadata and history state
- a 1k rendered JPEG preview of the current darkroom output when available
- a histogram derived from the same rendered output
- a capability manifest of writable darktable controls
- a matching list of current editable settings, including float, choice, and bool controls

The current protocol details live in [docs/protocol-v1.md](docs/protocol-v1.md).

## Local darktable workflow

- Rebuild the local custom darktable with `./scripts/build_darktable_local.sh`
- Run the local custom darktable with `./scripts/run_darktable_local.sh`
- Run the live Codex server-to-darktable exposure smoke check with `./scripts/agent_exposure_smoke.sh`
- Or use the root npm scripts: `npm run darktable:build`, `npm run darktable:start`, `npm run darktable:build-and-start`, `npm run server:start`, and `npm run agent:smoke`
- The launcher keeps its config, cache, and library isolated under `.darktable-local/` so it does not reuse a system darktable profile
- The build uses `darktable/build-5.4.1` for build artifacts and `darktable/.install-5.4.1` for the runnable install tree
- The server expects a working local `codex` CLI login because it uses `codex app-server` as the planning backend
- The smoke script now validates preview, histogram, capability coverage, and darktable session identifiers in the generated report

## License

TBD
