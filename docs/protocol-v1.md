# Protocol Mock Contract

This document describes the current temporary mock contract for `POST /v1/chat`.

It is still scaffolding, but it now matches the first real desktop integration:
darktable sends a chat request, the Python server returns a user-visible message
plus a list of structured operations, and darktable applies those operations
through its action system.

## Request

```json
{
  "schemaVersion": "2.0",
  "requestId": "req-123",
  "conversationId": "conv-456",
  "message": {
    "role": "user",
    "text": "Please brighten this image"
  },
  "uiContext": {
    "view": "darkroom",
    "imageId": 42,
    "imageName": "IMG_0042.CR3"
  },
  "mockResponseId": "exposure-plus-0.7"
}
```

- `schemaVersion`: required string, must be `"2.0"`
- `requestId`: required non-empty string
- `conversationId`: required non-empty string
- `message.role`: required string, must be `"user"`
- `message.text`: required non-empty string
- `uiContext.view`: required non-empty string
- `uiContext.imageId`: integer or `null`
- `uiContext.imageName`: string or `null`
- `mockResponseId`: `"chat-echo"`, `"exposure-plus-0.7"`, `"exposure-minus-0.7"`, `"status-summary"`, or `null`

`null` currently defaults to the exposure-increase mock so every darktable chat
submission exercises the same edit path.

## Response

```json
{
  "schemaVersion": "2.0",
  "requestId": "req-123",
  "conversationId": "conv-456",
  "status": "ok",
  "message": {
    "role": "assistant",
    "text": "Mock agent: increasing the current image exposure by +0.7 EV through the exposure slider."
  },
  "operations": [
    {
      "operationId": "op-exposure-plus-0.7",
      "kind": "set-float",
      "status": "planned",
        "target": {
          "type": "darktable-action",
          "actionPath": "iop/exposure/exposure"
        },
      "value": {
        "mode": "delta",
        "number": 0.7
      }
    }
  ],
  "error": null
}
```

- `schemaVersion`: required string, always `"2.0"`
- `requestId`: required string, echoed from the request when present
- `conversationId`: required string, echoed from the request when present
- `status`: required string, `"ok"` or `"error"`
- `message.role`: required string, always `"assistant"`
- `message.text`: required string
- `operations`: required array of planned darktable operations
- `error`: object or `null`

## Operation model

The current operation model is intentionally generic enough to scale:

- `kind: "set-float"` means the desktop should write a numeric value
- `target.type: "darktable-action"` means the target is a darktable action path
- `target.actionPath` identifies the control to read/write
- `value.mode: "delta"` means read the current value and add `number`
- `value.mode: "set"` means assign `number` directly

The first concrete target is exposure via `iop/exposure/exposure`.

## Mock behavior

- `mockResponseId == "chat-echo"`: assistant text only, no operations
- `mockResponseId == "exposure-plus-0.7"`: one planned `set-float` delta operation for `+0.7`
- `mockResponseId == "exposure-minus-0.7"`: one planned `set-float` delta operation for `-0.7`
- `mockResponseId == "status-summary"`: assistant status text only, no operations
- `mockResponseId == null`: defaults to `exposure-plus-0.7`

## Validation and errors

- The server validates the full request body and rejects unknown fields.
- Malformed payloads return `4xx` with `status: "error"`, an empty `operations` array, and an `error` object.
- If `requestId` or `conversationId` cannot be read from an invalid payload, the server returns empty strings for those fields so the response envelope stays structurally stable.
