#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd -P)
ASSET_PATH="${ASSET_PATH:-$REPO_ROOT/assets/_DSC8809.ARW}"
HOST="${HOST:-127.0.0.1}"
PYTHON_BIN="${PYTHON_BIN:-$REPO_ROOT/.venv/bin/python}"
MOCK_RESPONSE_ID="${MOCK_RESPONSE_ID:-${DARKTABLE_AGENT_TEST_MOCK_RESPONSE_ID:-exposure-plus-0.7}}"
AUTORUN_PROMPT="${AUTORUN_PROMPT:-${DARKTABLE_AGENT_TEST_AUTORUN_PROMPT:-Please apply the mock exposure edit.}}"
AUTORUN_QUIT_AFTER_MS="${AUTORUN_QUIT_AFTER_MS:-${DARKTABLE_AGENT_TEST_AUTORUN_QUIT_AFTER_MS:-1000}}"
DARKTABLE_TIMEOUT_SECONDS="${DARKTABLE_TIMEOUT_SECONDS:-120}"
KEEP_ARTIFACTS="${KEEP_ARTIFACTS:-0}"
SKIP_BUILD="${SKIP_BUILD:-0}"
SKIP_SERVER_TESTS="${SKIP_SERVER_TESTS:-0}"
CLEAN_RUNTIME="${CLEAN_RUNTIME:-0}"
REQUIRE_IMAGE_STATE="${REQUIRE_IMAGE_STATE:-0}"
REQUIRE_CAPABILITIES="${REQUIRE_CAPABILITIES:-0}"

REPORT_FILE="${REPORT_FILE:-$(mktemp "${TMPDIR:-/tmp}/darktable-agent-report.XXXXXX.ini")}"
SERVER_LOG="${SERVER_LOG:-$(mktemp "${TMPDIR:-/tmp}/darktable-agent-server.XXXXXX.log")}"
RUNTIME_DIR="${RUNTIME_DIR:-$REPO_ROOT/.darktable-local}"

cleanup() {
  if [[ -n "${SERVER_PID:-}" ]]; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi

  if [[ "$KEEP_ARTIFACTS" != "1" ]]; then
    rm -f "$REPORT_FILE" "$SERVER_LOG"
  fi

  if [[ "$CLEAN_RUNTIME" == "1" ]]; then
    rm -rf "$RUNTIME_DIR"
  fi
}
trap cleanup EXIT

if [[ ! -f "$ASSET_PATH" ]]; then
  echo "Missing RAW asset: $ASSET_PATH" >&2
  exit 1
fi

if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="python3"
fi

if [[ -z "${PORT:-}" ]]; then
  PORT="$((20000 + RANDOM % 20000))"
fi

SERVER_URL="${DARKTABLE_AGENT_SERVER_URL:-http://$HOST:$PORT/v1/chat}"
HEALTH_URL="${HEALTH_URL:-http://$HOST:$PORT/health}"

cd "$REPO_ROOT"

if [[ "$SKIP_SERVER_TESTS" != "1" ]]; then
  "$PYTHON_BIN" -m pytest server/tests
fi

if [[ "$SKIP_BUILD" != "1" ]]; then
  "$SCRIPT_DIR/build_darktable_local.sh"
fi

HOST="$HOST" PORT="$PORT" "$SCRIPT_DIR/run_server.sh" >"$SERVER_LOG" 2>&1 &
SERVER_PID=$!

for _ in $(seq 1 40); do
  if curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done

if ! curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
  echo "Server did not become healthy. See $SERVER_LOG" >&2
  exit 1
fi

launcher=("$SCRIPT_DIR/run_darktable_local.sh" --disable-opencl "$ASSET_PATH")
if [[ -z "${DISPLAY:-}" ]]; then
  if command -v xvfb-run >/dev/null 2>&1; then
    launcher=(xvfb-run -a "${launcher[@]}")
  else
    echo "No DISPLAY set and xvfb-run is unavailable." >&2
    exit 1
  fi
fi

echo "Server: $SERVER_URL"
echo "Asset:  $ASSET_PATH"
echo "Report: $REPORT_FILE"

DARKTABLE_AGENT_SERVER_URL="$SERVER_URL" \
  DARKTABLE_AGENT_TEST_AUTORUN_PROMPT="$AUTORUN_PROMPT" \
  DARKTABLE_AGENT_TEST_MOCK_RESPONSE_ID="$MOCK_RESPONSE_ID" \
  DARKTABLE_AGENT_TEST_RESULT_FILE="$REPORT_FILE" \
  DARKTABLE_AGENT_TEST_AUTORUN_QUIT_AFTER_MS="$AUTORUN_QUIT_AFTER_MS" \
  RUNTIME_DIR="$RUNTIME_DIR" \
  timeout "${DARKTABLE_TIMEOUT_SECONDS}s" "${launcher[@]}"

"$PYTHON_BIN" - "$REPORT_FILE" "$MOCK_RESPONSE_ID" <<'PY'
import configparser
import math
import sys

report_path, mock_response_id = sys.argv[1], sys.argv[2]
config = configparser.ConfigParser()
if not config.read(report_path):
    raise SystemExit(f"Missing report file: {report_path}")

result = config["result"]
status = result.get("status", "")
expected_statuses = {
    "unsupported-action": "apply_failed",
}
expected_status = expected_statuses.get(mock_response_id, "ok")
if status != expected_status:
    raise SystemExit(
        f"Unexpected darktable status {status!r}, expected {expected_status!r}: "
        f"{result.get('error', '')}"
    )

operation_count = int(result.get("operation_count", "0"))
if operation_count < 1:
    raise SystemExit(f"Expected at least one operation, found {operation_count}")

exposure_after = float(result.get("current_exposure", "nan"))
if math.isnan(exposure_after):
    raise SystemExit("Missing current_exposure in smoke report")

exposure_before = float(result.get("exposure_before", "nan"))
if math.isnan(exposure_before):
    raise SystemExit("Missing exposure_before in smoke report")

expected_deltas = {
    "exposure-plus-0.7": 0.7,
    "exposure-minus-0.7": -0.7,
    "exposure-sequence-plus-0.7": 0.7,
}
if mock_response_id in expected_deltas:
    actual_delta = exposure_after - exposure_before
    expected_delta = expected_deltas[mock_response_id]
    if abs(actual_delta - expected_delta) > 0.05:
        raise SystemExit(
            f"Expected exposure delta {expected_delta}, got {actual_delta} "
            f"(before={exposure_before}, after={exposure_after})"
        )

expected_finals = {
    "exposure-set-1.25": 1.25,
    "exposure-clamp-max": 18.0,
    "exposure-clamp-min": -18.0,
}
if mock_response_id in expected_finals:
    expected_final = expected_finals[mock_response_id]
    if abs(exposure_after - expected_final) > 0.05:
        raise SystemExit(
            f"Expected final exposure {expected_final}, got {exposure_after} "
            f"(before={exposure_before}, after={exposure_after})"
        )

blocked_expectations = {
    "unsupported-action": 1,
}
if mock_response_id in blocked_expectations:
    blocked_count = int(result.get("execution_blocked_count", "0"))
    failed_count = int(result.get("execution_failed_count", "0"))
    if blocked_count != blocked_expectations[mock_response_id]:
        raise SystemExit(
            f"Expected blocked count {blocked_expectations[mock_response_id]}, "
            f"found {blocked_count}"
        )
    if failed_count != 0:
        raise SystemExit(f"Expected failed count 0, found {failed_count}")
    if abs(exposure_after - exposure_before) > 0.05:
        raise SystemExit(
            f"Unsupported action should not change exposure "
            f"(before={exposure_before}, after={exposure_after})"
        )

print(
    f"Smoke test passed: status={status} operations={operation_count} "
    f"before={exposure_before:.3f} after={exposure_after:.3f}"
)
PY

if [[ "$REQUIRE_IMAGE_STATE" == "1" || "$REQUIRE_CAPABILITIES" == "1" ]]; then
  "$PYTHON_BIN" - "$SERVER_LOG" "$REQUIRE_IMAGE_STATE" "$REQUIRE_CAPABILITIES" <<'PY'
import json
import sys

rows = []
with open(sys.argv[1], "r", encoding="utf-8") as handle:
    for line in handle:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if payload.get("event") == "accepted_request":
            rows.append(payload)

if not rows:
    raise SystemExit("Expected at least one accepted_request log entry")

accepted_request = rows[-1]
image_state = accepted_request.get("imageState")
capabilities = accepted_request.get("capabilities")

if image_state is not None:
    if not isinstance(image_state, dict):
        raise SystemExit("Missing imageState in accepted_request log entry")
    if "currentExposure" not in image_state:
        raise SystemExit("Missing currentExposure in imageState")
    if not isinstance(image_state.get("controls"), list) or not image_state["controls"]:
        raise SystemExit("Missing controls in imageState")
    if not isinstance(image_state.get("history"), list):
        raise SystemExit("Missing history in imageState")

if capabilities is not None:
    if not isinstance(capabilities, list) or not capabilities:
        raise SystemExit("Missing capabilities in accepted_request log entry")
    capability = capabilities[0]
    expected = {
        "capabilityId": "exposure.primary",
        "label": "Exposure",
        "kind": "set-float",
        "targetType": "darktable-action",
        "actionPath": "iop/exposure/exposure",
    }
    for key, value in expected.items():
        if capability.get(key) != value:
            raise SystemExit(f"Capability field {key} expected {value!r}, got {capability.get(key)!r}")
    if capability.get("supportedModes") != ["set", "delta"]:
        raise SystemExit(f"Unexpected supportedModes: {capability.get('supportedModes')!r}")

require_image_state = bool(int(sys.argv[2]))
require_capabilities = bool(int(sys.argv[3]))
if require_image_state and image_state is None:
    raise SystemExit("Expected imageState in accepted_request log entry")
if require_capabilities and capabilities is None:
    raise SystemExit("Expected capabilities in accepted_request log entry")

messages = []
if require_image_state:
    messages.append("image-state snapshot")
if require_capabilities:
    messages.append("capability manifest")
print(f"{' and '.join(messages).capitalize()} validated from server log")
PY
fi

if [[ "$KEEP_ARTIFACTS" == "1" ]]; then
  echo "Artifacts kept:"
  echo "  report: $REPORT_FILE"
  echo "  server log: $SERVER_LOG"
  echo "  runtime dir: $RUNTIME_DIR"
fi
