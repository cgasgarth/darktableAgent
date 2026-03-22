# Evaluation Harness

Issue `#30` adds a stable evaluation harness so planner and binder changes can be checked against the same corpus instead of relying only on demos.

## What it covers

- A small built-in corpus spanning portrait, landscape, product, mixed-lighting, and high-ISO night workflows.
- Golden submissions expressed as canonical plans plus reference preview targets.
- Deterministic scoring for:
  - unknown or invalid targets
  - canonical binding failures
  - resolved operation count
  - tool-call and pass-count efficiency
  - preview clipping ratios
  - look-match distance versus a reference preview

## Run locally

```bash
npm run agent:eval
```

That runs the harness against the built-in golden corpus and exits non-zero if any case regresses.

## Evaluate external submissions

Provide a JSON file with a `submissions` array:

```json
{
  "submissions": [
    {
      "caseId": "portrait-natural-baseline",
      "plan": {
        "assistantText": "...",
        "continueRefining": false,
        "operations": [],
        "canonicalActions": []
      },
      "previewBase64": "<base64 image bytes>",
      "toolCallsUsed": 2,
      "passCount": 1
    }
  ]
}
```

Then run:

```bash
python3 -m server.evals.harness --submissions path/to/submissions.json
```

## Extending the corpus

- Add a new case in `server/evals/corpus.py`.
- Define the request, reference preview, expectations, thresholds, and golden submission.
- Add or adjust tests in `server/tests/test_evaluation_harness.py` if the new case introduces a new metric or rule.

The current corpus uses synthetic preview fixtures so it stays lightweight and reproducible in CI. It is designed to grow into real RAW-sidecar or rendered-preview corpora as more golden workflows are captured.
