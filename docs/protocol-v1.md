# Protocol Contract

This document describes the current live contract for `POST /v1/chat`.

darktable sends a structured editing snapshot to the local Python server. The
Python server forwards that snapshot into the Codex app server, receives a
structured plan, and returns a stable response envelope to darktable.

## Request

```json
{
  "schemaVersion": "3.0",
  "requestId": "req-123",
  "session": {
    "appSessionId": "app-001",
    "imageSessionId": "image-42",
    "conversationId": "conv-456",
    "turnId": "req-123"
  },
  "message": {
    "role": "user",
    "text": "Increase exposure by exactly 0.7 EV."
  },
  "uiContext": {
    "view": "darkroom",
    "imageId": 42,
    "imageName": "IMG_0042.CR3"
  },
  "capabilityManifest": {
    "manifestVersion": "1.0",
    "targets": [
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
    ]
  },
  "imageSnapshot": {
    "imageRevisionId": "img-42-hist-1",
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
    "historyPosition": 1,
    "historyCount": 1,
    "editableSettings": [
      {
        "settingId": "setting.exposure.primary",
        "capabilityId": "exposure.primary",
        "label": "Exposure",
        "actionPath": "iop/exposure/exposure",
        "currentNumber": 2.8,
        "supportedModes": ["set", "delta"],
        "minNumber": -18.0,
        "maxNumber": 18.0,
        "defaultNumber": 0.0,
        "stepNumber": 0.01
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
    ],
    "preview": null,
    "histogram": null
  }
}
```

- `schemaVersion`: required string, must be `"3.0"`
- `requestId`: required non-empty string
- `session`: required app/image/conversation/turn identity
- `message.role`: required string, must be `"user"`
- `message.text`: required non-empty string
- `uiContext`: required UI state for the active view/image
- `capabilityManifest.targets`: required writable controls declared by darktable
- `imageSnapshot`: required current image snapshot for the active darkroom image

## Response

```json
{
  "schemaVersion": "3.0",
  "requestId": "req-123",
  "session": {
    "appSessionId": "app-001",
    "imageSessionId": "image-42",
    "conversationId": "conv-456",
    "turnId": "req-123"
  },
  "status": "ok",
  "assistantMessage": {
    "role": "assistant",
    "text": "Increasing exposure by +0.7 EV."
  },
  "plan": {
    "planId": "plan-123",
    "baseImageRevisionId": "img-42-hist-1",
    "operations": [
      {
        "operationId": "op-exposure-plus-0.7",
        "sequence": 1,
        "kind": "set-float",
        "target": {
          "type": "darktable-action",
          "actionPath": "iop/exposure/exposure",
          "settingId": "setting.exposure.primary"
        },
        "value": {
          "mode": "delta",
          "number": 0.7
        },
        "reason": "The request asked for a precise +0.7 EV adjustment.",
        "constraints": {
          "onOutOfRange": "clamp",
          "onRevisionMismatch": "fail"
        }
      }
    ]
  },
  "operationResults": [
    {
      "operationId": "op-exposure-plus-0.7",
      "status": "planned",
      "error": null
    }
  ],
  "error": null
}
```

- `status`: `"ok"` or `"error"`
- `assistantMessage`: user-visible assistant text
- `plan`: ordered operations to apply against the current image revision
- `operationResults`: current server-side result state for each operation
- `error`: present only when `status == "error"`

## Operation model

- `kind: "set-float"` means write a numeric value
- `target.type: "darktable-action"` means the target is a darktable action path
- `target.settingId` ties the plan back to a specific editable setting in the image snapshot
- `value.mode: "delta"` means add `number` to the current value
- `value.mode: "set"` means assign `number` directly
- `constraints.onOutOfRange: "clamp"` means darktable should clamp to allowed bounds
- `constraints.onRevisionMismatch: "fail"` means darktable should reject stale plans

## Codex app server flow

The local Python server uses `codex app-server` over `stdio://` JSON-RPC.

For each darktable conversation:

1. The server initializes a local Codex app-server client.
2. The server starts or reuses a Codex thread mapped to `session.conversationId`.
3. The server submits the current request snapshot as turn input.
4. Codex returns structured JSON constrained by the local output schema.
5. The Python server wraps that plan into the stable darktable response envelope.

## Validation and errors

- The server validates the full request body and rejects unknown fields.
- The server rejects editable settings that do not match the capability manifest.
- The server rejects malformed operation plans from Codex before darktable sees them.
- Backend failures from the Codex app server return `status: "error"` with `plan: null`.
