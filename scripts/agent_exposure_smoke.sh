#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd -P)
ASSET_PATH="${ASSET_PATH:-$REPO_ROOT/assets/_DSC8809.ARW}"
HOST="${HOST:-${DARKTABLE_AGENT_SERVER_HOST:-127.0.0.1}}"
PYTHON_BIN="${PYTHON_BIN:-$REPO_ROOT/.venv/bin/python}"
AUTORUN_PROMPT="${AUTORUN_PROMPT:-${DARKTABLE_AGENT_TEST_AUTORUN_PROMPT:-Increase exposure by exactly 0.7 EV.}}"
AUTORUN_QUIT_AFTER_MS="${AUTORUN_QUIT_AFTER_MS:-${DARKTABLE_AGENT_TEST_AUTORUN_QUIT_AFTER_MS:-1000}}"
EXPECTED_STATUS="${EXPECTED_STATUS:-ok}"
EXPECTED_MIN_OPERATION_COUNT="${EXPECTED_MIN_OPERATION_COUNT:-1}"
EXPECTED_DELTA="${EXPECTED_DELTA:-0.7}"
EXPECTED_FINAL_EXPOSURE="${EXPECTED_FINAL_EXPOSURE:-}"
EXPECTED_BLOCKED_COUNT="${EXPECTED_BLOCKED_COUNT:-}"
MULTI_TURN_ENABLED="${MULTI_TURN_ENABLED:-0}"
MULTI_TURN_MAX_TURNS="${MULTI_TURN_MAX_TURNS:-15}"
EXPECTED_MIN_REFINEMENT_PASSES="${EXPECTED_MIN_REFINEMENT_PASSES:-}"
EXPECTED_MAX_REFINEMENT_PASSES="${EXPECTED_MAX_REFINEMENT_PASSES:-}"
EXPECTED_REFINEMENT_MODE="${EXPECTED_REFINEMENT_MODE:-}"
EXPECTED_REFINEMENT_STOP_REASON="${EXPECTED_REFINEMENT_STOP_REASON:-}"
KEEP_ARTIFACTS="${KEEP_ARTIFACTS:-0}"
SKIP_BUILD="${SKIP_BUILD:-0}"
SKIP_SERVER_TESTS="${SKIP_SERVER_TESTS:-0}"
CLEAN_RUNTIME="${CLEAN_RUNTIME:-0}"
REQUIRE_IMAGE_STATE="${REQUIRE_IMAGE_STATE:-0}"
REQUIRE_CAPABILITIES="${REQUIRE_CAPABILITIES:-0}"
EXPECTED_MIN_EDITABLE_SETTINGS="${EXPECTED_MIN_EDITABLE_SETTINGS:-20}"
REQUIRE_PREVIEW="${REQUIRE_PREVIEW:-0}"
REQUIRE_HISTOGRAM="${REQUIRE_HISTOGRAM:-0}"

if [[ -z "${DARKTABLE_TIMEOUT_SECONDS:-}" ]]; then
  DARKTABLE_TIMEOUT_SECONDS=600
fi

if [[ -z "${SERVER_TIMEOUT_SECONDS:-}" ]]; then
  SERVER_TIMEOUT_SECONDS=600
fi

if [[ -z "$EXPECTED_MIN_REFINEMENT_PASSES" ]]; then
  if [[ "$MULTI_TURN_ENABLED" == "1" ]]; then
    EXPECTED_MIN_REFINEMENT_PASSES=1
  else
    EXPECTED_MIN_REFINEMENT_PASSES=1
  fi
fi

if [[ -z "$EXPECTED_MAX_REFINEMENT_PASSES" ]]; then
  if [[ "$MULTI_TURN_ENABLED" == "1" ]]; then
    EXPECTED_MAX_REFINEMENT_PASSES="$MULTI_TURN_MAX_TURNS"
  else
    EXPECTED_MAX_REFINEMENT_PASSES=1
  fi
fi

if [[ -z "$EXPECTED_REFINEMENT_MODE" ]]; then
  if [[ "$MULTI_TURN_ENABLED" == "1" ]]; then
    EXPECTED_REFINEMENT_MODE="multi-turn"
  else
    EXPECTED_REFINEMENT_MODE="single-turn"
  fi
fi

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

if [[ -z "${PORT:-${DARKTABLE_AGENT_SERVER_PORT:-}}" ]]; then
  PORT="$((20000 + RANDOM % 20000))"
else
  PORT="${PORT:-${DARKTABLE_AGENT_SERVER_PORT}}"
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

HOST="$HOST" \
  PORT="$PORT" \
  DARKTABLE_AGENT_USE_MOCK_RESPONSES=1 \
  DARKTABLE_AGENT_CODEX_TIMEOUT_SECONDS="$SERVER_TIMEOUT_SECONDS" \
  "$SCRIPT_DIR/run_server.sh" >"$SERVER_LOG" 2>&1 &
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

launcher=("$SCRIPT_DIR/run_darktable_local.sh" --foreground --disable-opencl "$ASSET_PATH")
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
  DARKTABLE_AGENT_SERVER_TIMEOUT_SECONDS="$SERVER_TIMEOUT_SECONDS" \
  DARKTABLE_AGENT_TEST_AUTORUN_PROMPT="$AUTORUN_PROMPT" \
  DARKTABLE_AGENT_TEST_RESULT_FILE="$REPORT_FILE" \
  DARKTABLE_AGENT_TEST_AUTORUN_QUIT_AFTER_MS="$AUTORUN_QUIT_AFTER_MS" \
  DARKTABLE_AGENT_TEST_MULTI_TURN_ENABLED="$MULTI_TURN_ENABLED" \
  DARKTABLE_AGENT_TEST_MULTI_TURN_MAX_TURNS="$MULTI_TURN_MAX_TURNS" \
  RUNTIME_DIR="$RUNTIME_DIR" \
  timeout "${DARKTABLE_TIMEOUT_SECONDS}s" "${launcher[@]}"

"$PYTHON_BIN" - "$REPORT_FILE" "$SERVER_LOG" "$EXPECTED_STATUS" "$EXPECTED_MIN_OPERATION_COUNT" "$EXPECTED_DELTA" "$EXPECTED_FINAL_EXPOSURE" "$EXPECTED_BLOCKED_COUNT" "$EXPECTED_MIN_REFINEMENT_PASSES" "$EXPECTED_MAX_REFINEMENT_PASSES" "$EXPECTED_REFINEMENT_MODE" "$EXPECTED_REFINEMENT_STOP_REASON" <<'PY'
import configparser
import json
import math
import sys

(
    report_path,
    server_log_path,
    expected_status,
    expected_min_operation_count,
    expected_delta,
    expected_final_exposure,
    expected_blocked_count,
    expected_min_refinement_passes,
    expected_max_refinement_passes,
    expected_refinement_mode,
    expected_refinement_stop_reason,
) = sys.argv[1:12]
config = configparser.ConfigParser()
if not config.read(report_path):
    raise SystemExit(f"Missing report file: {report_path}")

result = config["result"]
status = result.get("status", "")
if status != expected_status:
    raise SystemExit(
        f"Unexpected darktable status {status!r}, expected {expected_status!r}: "
        f"{result.get('error', '')}"
    )

operation_count = int(result.get("operation_count", "0"))
if operation_count < int(expected_min_operation_count):
    raise SystemExit(
        f"Expected at least {expected_min_operation_count} operations, found {operation_count}"
    )

exposure_after = float(result.get("current_exposure", "nan"))
if math.isnan(exposure_after):
    raise SystemExit("Missing current_exposure in smoke report")

exposure_before = float(result.get("exposure_before", "nan"))
if math.isnan(exposure_before):
    raise SystemExit("Missing exposure_before in smoke report")

for key in ("app_session_id", "image_session_id", "active_conversation_id"):
    if not result.get(key, ""):
        raise SystemExit(f"Missing {key} in smoke report")

active_image_id = int(result.get("active_image_id", "0"))
if active_image_id <= 0:
    raise SystemExit(f"Expected active_image_id > 0 in smoke report, got {active_image_id}")

if expected_delta:
    actual_delta = exposure_after - exposure_before
    if abs(actual_delta - float(expected_delta)) > 0.05:
        raise SystemExit(
            f"Expected exposure delta {expected_delta}, got {actual_delta} "
            f"(before={exposure_before}, after={exposure_after})"
        )

if expected_final_exposure:
    expected_final = float(expected_final_exposure)
    if abs(exposure_after - expected_final) > 0.05:
        raise SystemExit(
            f"Expected final exposure {expected_final}, got {exposure_after} "
            f"(before={exposure_before}, after={exposure_after})"
        )

if expected_blocked_count:
    blocked_count = int(result.get("execution_blocked_count", "0"))
    failed_count = int(result.get("execution_failed_count", "0"))
    if blocked_count != int(expected_blocked_count):
        raise SystemExit(
            f"Expected blocked count {expected_blocked_count}, found {blocked_count}"
        )
    if failed_count != 0:
        raise SystemExit(f"Expected failed count 0, found {failed_count}")

accepted_requests = []
fulfilled_requests = []
with open(server_log_path, "r", encoding="utf-8") as handle:
    for line in handle:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if payload.get("event") == "accepted_request":
            accepted_requests.append(payload)
        elif payload.get("event") == "fulfilled_request":
            fulfilled_requests.append(payload)

if not accepted_requests:
    raise SystemExit("Expected at least one accepted_request log entry for refinement validation")

accepted_count = len(accepted_requests)
fulfilled_count = len(fulfilled_requests)
if accepted_count < int(expected_min_refinement_passes):
    raise SystemExit(
        f"Expected at least {expected_min_refinement_passes} accepted requests, found {accepted_count}"
    )
if accepted_count > int(expected_max_refinement_passes):
    raise SystemExit(
        f"Expected at most {expected_max_refinement_passes} accepted requests, found {accepted_count}"
    )
if fulfilled_count < accepted_count:
    raise SystemExit(
        f"Expected at least {accepted_count} fulfilled requests, found {fulfilled_count}"
    )

conversation_ids = {
    row.get("conversationId")
    for row in accepted_requests
    if isinstance(row.get("conversationId"), str) and row.get("conversationId")
}
image_session_ids = {
    row.get("imageSessionId")
    for row in accepted_requests
    if isinstance(row.get("imageSessionId"), str) and row.get("imageSessionId")
}
turn_ids = [
    row.get("turnId")
    for row in accepted_requests
    if isinstance(row.get("turnId"), str) and row.get("turnId")
]
if len(conversation_ids) != 1:
    raise SystemExit(
        f"Expected exactly one conversationId across refinement requests, found {sorted(conversation_ids)}"
    )
if len(image_session_ids) != 1:
    raise SystemExit(
        f"Expected exactly one imageSessionId across refinement requests, found {sorted(image_session_ids)}"
    )
if len(turn_ids) != accepted_count or len(set(turn_ids)) != accepted_count:
    raise SystemExit("Expected one unique turnId per refinement request")

refinement_modes = set()
refinement_enabled_values = set()
refinement_max_passes_values = set()
for row in accepted_requests:
    refinement = row.get("refinement")
    if not isinstance(refinement, dict):
        raise SystemExit("Missing refinement payload in accepted_request log entry")
    mode = refinement.get("mode")
    if isinstance(mode, str) and mode:
        refinement_modes.add(mode)
    enabled = refinement.get("enabled")
    if isinstance(enabled, bool):
        refinement_enabled_values.add(enabled)
    max_passes = refinement.get("maxPasses")
    if isinstance(max_passes, int):
        refinement_max_passes_values.add(max_passes)

if expected_refinement_mode:
    if refinement_modes != {expected_refinement_mode}:
        raise SystemExit(
            f"Expected refinement mode {expected_refinement_mode!r} in server logs, "
            f"found {sorted(refinement_modes)}"
        )
    expected_enabled = expected_refinement_mode == "multi-turn"
    if refinement_enabled_values != {expected_enabled}:
        raise SystemExit(
            f"Expected refinement enabled={expected_enabled} in server logs, "
            f"found {sorted(refinement_enabled_values)}"
        )

if refinement_max_passes_values and refinement_max_passes_values != {int(expected_max_refinement_passes)}:
    raise SystemExit(
        f"Expected refinement maxPasses {expected_max_refinement_passes} in server logs, "
        f"found {sorted(refinement_max_passes_values)}"
    )

refinement_mode = result.get("refinement_mode", "")
if expected_refinement_mode and refinement_mode and refinement_mode != expected_refinement_mode:
    raise SystemExit(
        f"Expected refinement mode {expected_refinement_mode!r}, got {refinement_mode!r}"
    )

refinement_enabled = result.get("refinement_enabled", "")
if refinement_enabled and expected_refinement_mode:
    expected_enabled = "1" if expected_refinement_mode == "multi-turn" else "0"
    if refinement_enabled != expected_enabled:
        raise SystemExit(
            f"Expected refinement_enabled={expected_enabled}, got {refinement_enabled}"
        )

reported_pass_count = result.get("refinement_pass_count", "")
if reported_pass_count:
    if int(reported_pass_count) != accepted_count:
        raise SystemExit(
            f"Expected refinement_pass_count {accepted_count}, got {reported_pass_count}"
        )

reported_turn_limit = result.get("refinement_max_turns", "")
if reported_turn_limit:
    if int(reported_turn_limit) != int(expected_max_refinement_passes):
        raise SystemExit(
            f"Expected refinement_max_turns {expected_max_refinement_passes}, got {reported_turn_limit}"
        )

if expected_refinement_stop_reason:
    stop_reason = result.get("refinement_stop_reason", "")
    if stop_reason != expected_refinement_stop_reason:
        raise SystemExit(
            f"Expected refinement_stop_reason {expected_refinement_stop_reason!r}, got {stop_reason!r}"
        )

print(
    f"Smoke test passed: status={status} operations={operation_count} "
    f"before={exposure_before:.3f} after={exposure_after:.3f} "
    f"requests={accepted_count}"
)
PY

if [[ "$REQUIRE_IMAGE_STATE" == "1" || "$REQUIRE_CAPABILITIES" == "1" || "$REQUIRE_PREVIEW" == "1" || "$REQUIRE_HISTOGRAM" == "1" ]]; then
  "$PYTHON_BIN" - "$SERVER_LOG" "$REQUIRE_IMAGE_STATE" "$REQUIRE_CAPABILITIES" "$REQUIRE_PREVIEW" "$REQUIRE_HISTOGRAM" "$EXPECTED_MIN_EDITABLE_SETTINGS" <<'PY'
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
image_snapshot = accepted_request.get("imageSnapshot")
capabilities = accepted_request.get("capabilities")

if image_snapshot is not None:
    if not isinstance(image_snapshot, dict):
        raise SystemExit("Missing imageSnapshot in accepted_request log entry")
    if "imageRevisionId" not in image_snapshot:
        raise SystemExit("Missing imageRevisionId in imageSnapshot")
    if not isinstance(image_snapshot.get("editableSettings"), list) or not image_snapshot["editableSettings"]:
        raise SystemExit("Missing editableSettings in imageSnapshot")
    if len(image_snapshot["editableSettings"]) < int(sys.argv[6]):
        raise SystemExit(
            f"Expected at least {sys.argv[6]} editableSettings, found {len(image_snapshot['editableSettings'])}"
        )
    if not isinstance(image_snapshot.get("history"), list):
        raise SystemExit("Missing history in imageSnapshot")
    metadata = image_snapshot.get("metadata")
    if not isinstance(metadata, dict):
        raise SystemExit("Missing metadata in imageSnapshot")
    preview = image_snapshot.get("preview")
    histogram = image_snapshot.get("histogram")
    if preview is not None:
        for key in ("previewId", "mimeType", "width", "height", "base64Data"):
            if key not in preview:
                raise SystemExit(f"Missing preview field {key}")
    if histogram is not None:
        if histogram.get("binCount", 0) <= 0:
            raise SystemExit("Histogram binCount must be positive")
        channels = histogram.get("channels")
        if not isinstance(channels, dict) or not channels:
            raise SystemExit("Histogram channels are missing")
        for channel_name in ("red", "green", "blue", "luma"):
            channel = channels.get(channel_name)
            if not isinstance(channel, dict) or "bins" not in channel:
                raise SystemExit(f"Missing histogram channel {channel_name}")
            if len(channel["bins"]) != histogram["binCount"]:
                raise SystemExit(
                    f"Histogram channel {channel_name} length mismatch: "
                    f"{len(channel['bins'])} != {histogram['binCount']}"
                )

if capabilities is not None:
    if not isinstance(capabilities, list) or not capabilities:
        raise SystemExit("Missing capabilities in accepted_request log entry")
    capability = capabilities[0]
    for key in (
        "capabilityId",
        "label",
        "kind",
        "targetType",
        "actionPath",
        "supportedModes",
        "minNumber",
        "maxNumber",
        "defaultNumber",
        "stepNumber",
    ):
        if key not in capability:
            raise SystemExit(f"Missing capability field {key}")

require_image_state = bool(int(sys.argv[2]))
require_capabilities = bool(int(sys.argv[3]))
require_preview = bool(int(sys.argv[4]))
require_histogram = bool(int(sys.argv[5]))
if require_image_state and image_snapshot is None:
    raise SystemExit("Expected imageSnapshot in accepted_request log entry")
if require_capabilities and capabilities is None:
    raise SystemExit("Expected capabilities in accepted_request log entry")
if require_preview and (image_snapshot is None or image_snapshot.get("preview") is None):
    raise SystemExit("Expected preview in accepted_request log entry")
if require_histogram and (image_snapshot is None or image_snapshot.get("histogram") is None):
    raise SystemExit("Expected histogram in accepted_request log entry")

print("Accepted request log includes expected image snapshot and capability manifest.")
PY
fi
