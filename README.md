# darktableAgent

darktableAgent is an AI-assisted editing workflow built on top of our fork of [darktable](https://github.com/darktable-org/darktable). It combines a darkroom chat interface, a local Python backend, and a structured edit protocol so edit requests can be translated into supported darktable operations.

darktable remains the source of truth for image state and rendering. The backend plans edits; darktable validates and applies them through supported controls.

## Features

- Integrated darkroom chat UI
- Single-turn planning and live iterative edit sessions
- Structured operation protocol between UI and backend
- Streaming progress during live runs
- Deterministic smoke-test path using mock responses

## Architecture

- `darktable/` contains our darktable fork and the darkroom UI integration
- `server/` contains the FastAPI backend and Codex bridge
- `shared/` contains the protocol models and schema

Request flow:

1. darktable captures the current image state, editable settings, preview, and session context.
2. The backend sends that context to the planner.
3. The planner returns structured edit operations.
4. darktable validates and applies those operations through supported controls.

In live mode, the backend can stage multiple edit batches, refresh state and preview, and continue refining within the same run.

## Setup

Prerequisites:

- macOS or Linux
- `python3` 3.14+
- `uv`
- `codex` CLI installed and authenticated
- macOS: Homebrew
- Linux: darktable build dependencies for your distribution
- local CLI tools used by the build and test scripts: `ninja`, `cmake`, `curl`
- optional: `xvfb-run` for headless smoke tests (Linux)
- macOS smoke runs require an active logged-in GUI session; they do not use `xvfb-run`

Install all dependencies (Homebrew packages on macOS, Python packages on all platforms):

```bash
npm run bootstrap
```

Build darktable:

```bash
npm run darktable:build
```

Start the backend:

```bash
npm run server:start
```

Start darktable:

```bash
npm run darktable:start
```

By default, the backend runs locally on `127.0.0.1:8001`.

## Testing

Run the Python test suite:

```bash
uv run pytest server/tests
```

Run Python type checking:

```bash
uvx pyright server shared
```

Run local pre-commit checks:

```bash
uvx pre-commit run --all-files
```

Run the evaluation harness against the built-in golden corpus:

```bash
npm run agent:eval
```

Run the deterministic smoke test:

```bash
npm run agent:smoke
```

Run the deterministic multi-turn smoke test:

```bash
npm run agent:smoke:multi-turn
```

On Linux, the smoke script can run headlessly with `xvfb-run`.
On macOS, run it from a logged-in desktop session so darktable can open normally.

## Protocol

Protocol details are documented in `docs/protocol-v1.md`.

## Evaluation Harness

Evaluation harness details are documented in `docs/evaluation-harness.md`.

## Upstream darktable tracking

Upstream tracking details are documented in `docs/upstream-darktable.md`.

Check the vendored darktable tree against the tracked upstream release with:

```bash
npm run darktable:upstream-status
```

The upstream metadata distinguishes between the original fork base and the current upstream release our vendored tree matches.
