# Protocol v1

This document describes the current temporary scaffold for `POST /v1/chat`.

It is not the final darktable agent contract.

The `mockActionId` field and the brighten/darken mock behavior are only placeholders from the initial backend slice. As the real Python agent harness and darktable edit execution path are implemented, this document should be replaced by a protocol that reflects actual planning, execution, and state readback.

## Request

```json
{
  "schemaVersion": "1.0",
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
  "mockActionId": "brighten-exposure"
}
```

- `schemaVersion`: required string, must be `"1.0"`
- `requestId`: required non-empty string
- `conversationId`: required non-empty string
- `message.role`: required string, must be `"user"`
- `message.text`: required non-empty string
- `uiContext.view`: required non-empty string
- `uiContext.imageId`: integer or `null`
- `uiContext.imageName`: string or `null`
- `mockActionId`: `"brighten-exposure"`, `"darken-exposure"`, or `null`

## Response

```json
{
  "schemaVersion": "1.0",
  "requestId": "req-123",
  "conversationId": "conv-456",
  "status": "ok",
  "message": {
    "role": "assistant",
    "text": "Planned a +0.7 EV exposure adjustment."
  },
  "actions": [
    {
      "actionId": "adjust-exposure-brighten",
      "type": "adjust-exposure",
      "status": "planned",
      "parameters": {
        "deltaEv": 0.7
      }
    }
  ],
  "error": null
}
```

- `schemaVersion`: required string, always `"1.0"`
- `requestId`: required string; echoed from the request when present
- `conversationId`: required string; echoed from the request when present
- `status`: required string, `"ok"` or `"error"`
- `message.role`: required string, always `"assistant"`
- `message.text`: required string
- `actions`: required array of planned actions
- `error`: object or `null`

## Mock behavior

- `mockActionId == "brighten-exposure"`: one `adjust-exposure` action with `deltaEv: 0.7`
- `mockActionId == "darken-exposure"`: one `adjust-exposure` action with `deltaEv: -0.7`
- `mockActionId == null`: echo-style assistant message and empty `actions`

## Validation and errors

- The server validates the full request body and rejects unknown fields.
- Malformed payloads return `4xx` with `status: "error"`, an empty `actions` array, and an `error` object.
- If `requestId` or `conversationId` cannot be read from an invalid payload, the server returns empty strings for those fields so the response envelope stays structurally stable.
