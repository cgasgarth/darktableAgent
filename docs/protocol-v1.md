# Protocol Contract

This document describes the current live contract for `POST /v1/chat`.

darktable sends structured editing context to the local Python server. The
Python server forwards that context into the Codex app server, receives a
structured plan, and returns a stable response envelope to darktable.

## Request

```json
{
  "schemaVersion": "2.0",
  "requestId": "req-123",
  "conversationId": "conv-456",
  "message": {
    "role": "user",
    "text": "Increase exposure by exactly 0.7 EV."
  },
  "uiContext": {
    "view": "darkroom",
    "imageId": 42,
    "imageName": "IMG_0042.CR3"
  },
  "capabilities": [
    {
      "capabilityId": "exposure.primary",
      "label": "Exposure",
      "kind": "set-float",
      "targetType": "darktable-action",
      "actionPath": "iop/exposure/exposure",
      "supportedModes": ["set", "delta"],
      "minNumber": -18.0,
      "maxNumber": 18.0,
      "defaultNumber": 0.0,
      "stepNumber": 0.01
    }
  ],
  "imageState": {
    "currentExposure": 2.8,
    "historyPosition": 1,
    "historyCount": 1,
    "metadata": {
      "imageId": 42,
      "imageName": "IMG_0042.CR3",
      "cameraMaker": "Sony",
      "cameraModel": "ILCE-7RM5",
      "width": 9504,
      "height": 6336,
      "exifExposureSeconds": 0.01,
      "exifAperture": 4.0,
      "exifIso": 100.0,
      "exifFocalLength": 35.0
    },
    "controls": [
      {
        "capabilityId": "exposure.primary",
        "label": "Exposure",
        "actionPath": "iop/exposure/exposure",
        "currentNumber": 2.8
      }
    ],
    "history": [
      {
        "num": 0,
        "module": "exposure",
        "enabled": true,
        "multiPriority": 0,
        "instanceName": "exposure",
        "iopOrder": 20
      }
    ]
  }
}
```

- `schemaVersion`: required string, must be `"2.0"`
- `requestId`: required non-empty string
- `conversationId`: required non-empty string
- `message.role`: required string, must be `"user"`
- `message.text`: required non-empty string
- `uiContext`: required UI state for the active view/image
- `capabilities`: required array of writable agent capabilities declared by darktable
- `imageState`: required object containing the current darkroom snapshot

## Response

```json
{
  "schemaVersion": "2.0",
  "requestId": "req-123",
  "conversationId": "conv-456",
  "status": "ok",
  "message": {
    "role": "assistant",
    "text": "Increasing exposure by +0.7 EV."
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

- `status`: `"ok"` or `"error"`
- `message`: user-visible assistant text
- `operations`: ordered list of planned darktable operations
- `error`: present only when `status == "error"`

## Operation model

- `kind: "set-float"` means write a numeric value
- `target.type: "darktable-action"` means the target is a darktable action path
- `value.mode: "delta"` means add `number` to the current value
- `value.mode: "set"` means assign `number` directly

## Codex app server flow

The local Python server uses `codex app-server` over `stdio://` JSON-RPC.

For each darktable conversation:

1. The server initializes a local Codex app-server client.
2. The server starts or reuses a Codex thread mapped to `conversationId`.
3. The server submits the current request snapshot as turn input.
4. Codex returns structured JSON constrained by the local output schema.
5. The Python server wraps that plan into the stable darktable response envelope.

## Validation and errors

- The server validates the full request body and rejects unknown fields.
- The server rejects image-state controls that do not match the capability manifest.
- Backend failures from the Codex app server return `status: "error"` with an empty `operations` array.
