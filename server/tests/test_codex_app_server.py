import pytest

from server.codex_app_server import CodexAppServerBridge


def test_default_command_disables_configured_mcp_servers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DARKTABLE_AGENT_CODEX_APP_SERVER_CMD", raising=False)

    bridge = CodexAppServerBridge()

    assert bridge._command == [
        "codex",
        "app-server",
        "-c",
        "mcp_servers.chrome-devtools.enabled=false",
        "--listen",
        "stdio://",
    ]


def test_environment_command_override_replaces_default_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "DARKTABLE_AGENT_CODEX_APP_SERVER_CMD",
        "codex app-server --listen stdio://",
    )

    bridge = CodexAppServerBridge()

    assert bridge._command == ["codex", "app-server", "--listen", "stdio://"]


def test_extract_error_message_prefers_nested_json_message() -> None:
    message = '{"error":{"message":"The real error"}}'

    assert CodexAppServerBridge._extract_error_message(message) == "The real error"


def test_task_complete_marks_turn_complete() -> None:
    bridge = CodexAppServerBridge(command=["codex", "app-server", "--listen", "stdio://"])
    turn_state = {
        "thread_id": "thread-1",
        "turn_id": "turn-1",
        "chunks": [],
        "final_message": None,
        "turn_error": None,
        "completed": False,
    }

    bridge._handle_message_locked(  # type: ignore[attr-defined]
        {
            "method": "codex/event/task_complete",
            "params": {
                "id": "turn-1",
                "msg": {
                    "last_agent_message": '{"assistantText":"Done","operations":[]}',
                },
            },
        },
        turn_state,
    )

    assert turn_state["final_message"] == '{"assistantText":"Done","operations":[]}'
    assert turn_state["completed"] is True
