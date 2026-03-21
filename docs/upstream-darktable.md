# Tracking Upstream darktable

This repository does not need to be a GitHub fork of `darktable-org/darktable` to stay aligned with upstream. The source of truth for the vendored darktable base lives in `darktable-upstream.json`.

## Current baseline

- Upstream repository: `https://github.com/darktable-org/darktable.git`
- Tracked release tag: `release-5.4.1`
- Vendored source path in this repo: `darktable/`

## How to check our downstream patch surface

Run:

```bash
npm run darktable:upstream-status
```

That command clones the tracked upstream tag into a temporary directory, compares it to `darktable/`, ignores generated/build metadata, and reports whether the local tree matches upstream plus our expected downstream patch set.

You can also compare against a newer tag before attempting a sync:

```bash
python3 scripts/darktable_upstream.py status --tag release-5.4.1
```

Swap in a newer upstream tag when darktable ships a new release.

## How to track new upstream releases

- `darktable-upstream.json` records the currently tracked upstream tag and the expected downstream patch surface.
- `.github/workflows/darktable-upstream-watch.yml` checks the latest GitHub release from `darktable-org/darktable` on a schedule and opens or updates an issue when upstream advances.

## Recommended sync workflow

1. Create a branch like `sync-darktable-5.4.2`.
2. Run `python3 scripts/darktable_upstream.py status --tag release-5.4.2` to see the delta from the new upstream release.
3. Update the vendored `darktable/` tree to the new upstream release.
4. Reapply or adapt only the downstream patch surface recorded in `darktable-upstream.json`.
5. Update `darktable-upstream.json` to the new tracked tag.
6. Run the repo validation/build flow before opening the sync PR.

## Why this workflow

- No GitHub fork relationship is required.
- No persistent git remote is required for day-to-day tracking.
- The upstream baseline stays explicit and reviewable in the repo.
- Future sync PRs can focus on the small set of files where darktableAgent intentionally diverges from upstream.
