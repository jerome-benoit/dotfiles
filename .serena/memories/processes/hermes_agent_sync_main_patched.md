# Historical Process: Sync `hermes-agent/main-patched`

## Status

The active flake follows `github:NousResearch/hermes-agent` directly.
Do not resynchronize or repin the historical fork during routine lock updates.
The procedure below applies only if the project explicitly switches back to a fork.

## Historical Repositories

- Fork: `github:jerome-benoit/hermes-agent`, branch `main-patched`.
- Upstream: `github:NousResearch/hermes-agent`, branch `main`.

## Rules

- Run git commands as `GIT_MASTER=1 git ...`.
- Work in a temporary clone under `/tmp/opencode`, not in `/home/fraggle/.nix`.
- Record the old remote fork SHA before rewriting; use it only as the exact push lease.
- Do not update `.nix/flake.lock` until the pushed fork remote has been fetched and verified.
- Do not commit or push dotfiles unless explicitly requested.
- Do not encode current SHAs, dates, narHashes, or a fixed ahead-count in this memory; derive them during each sync.

## Sync Procedure

1. Inspect `/home/fraggle/.nix` status and preserve any existing dirty work.
2. Clone the fork in `/tmp/opencode`, add/fetch upstream, and fetch `origin/main-patched`.
3. Record:
   - old fork remote SHA: `origin/main-patched`
   - new upstream SHA: `upstream/main`
   - current fork-only commits: `GIT_MASTER=1 git log --oneline --reverse upstream/main..origin/main-patched`
4. Decide which fork-only commits to keep:
   - keep temporary patches that are still not upstream
   - drop commits that became empty, upstreamed, or obsolete
   - if the set is ambiguous, stop and inspect before pushing
5. Rebuild from fresh `upstream/main` and cherry-pick kept commits in original order.
6. Verify before push:
   - clean status
   - `upstream/main` is an ancestor of the rebuilt branch
   - expected fork-only commits only
   - relevant lock/package invariants for any preserved npm/Nix patch
   - do not run a full/slow build by default; only run a targeted build when explicitly requested or when the patch itself changes build logic in a way git/lock checks cannot validate
7. Push with exact lease: `--force-with-lease=refs/heads/main-patched:<old_remote_sha>`.
8. Fetch `origin/main-patched` and verify it equals local `HEAD`.
9. Update `.nix/flake.lock` for `hermes-agent`, then verify the lock points to the verified remote SHA.
10. Clean up the temp clone. If a build was explicitly requested, run it before cleanup.

## If All Fork Patches Drop

Switch `.nix` back to upstream `github:NousResearch/hermes-agent` instead of keeping an empty fork branch.
