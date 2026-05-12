# Process: Refresh Patches from PRs

## Context

Patches in `patches/<project>/*.patch` come from unmerged upstream PRs.
Applied via `overrideAttrs` adding to `patches` list (see `opencode.nix`, `qmd.nix`).
When the locked input advances, patch line offsets drift → must refresh.

**Prerequisites**: Flake lock must be current (`nix flake update <input>` already done). If running both processes, run `hermes_agent_sync_main_patched` FIRST (it affects the lock).

## Current Patches

- `patches/opencode/proxy-env-to-process-env.patch` — PR #12822 (anomalyco/opencode)
- `patches/opencode/relax-bun-version-check.patch` — local, NOT from a PR (exempt from this process)
- `patches/qmd/fix-nixos-llama-build.patch` — PR #574 (tobi/qmd), only `src/llm.ts`

## Process

### 1. Check PR status against locked rev

```bash
LOCKED_REV=$(jq -r '.nodes["<input-name>"].locked.rev' flake.lock)
gh pr view <PR_NUMBER> --repo <OWNER>/<REPO> --json state,mergeCommit,headRefOid
```

If `state: "MERGED"`, verify merge is included in locked rev:

```bash
# "ahead" or "identical" → merge included → DELETE patch
# "behind" or "diverged" → locked rev predates merge → keep patch until lock update
gh api repos/<OWNER>/<REPO>/compare/<mergeCommitSha>...$LOCKED_REV --jq '.status'
```

- If merge included → DELETE patch, commit `chore: remove merged <project> PR #<N> patch`
- If `state: "CLOSED"` without merge → decide: re-open as new PR, carry patch indefinitely, or drop feature
- If `state: "OPEN"` → refresh (continue below)

### 2. Download fresh PR diff

```bash
gh pr diff <PR_NUMBER> --repo <OWNER>/<REPO> > /tmp/fresh.patch
```

### 3. Filter: strip hunks irrelevant to build

The patch applies during `patchPhase` on the full `$src` fetched by nix. Keep hunks for files **relevant to the build output**. Strip docs, changelogs, lock files, and CI configs — even though they exist in `$src` — because they add conflict surface without affecting builds.

**What to KEEP**: source, test, scripts, config files that affect compilation/bundling
**What to STRIP**: docs/, CHANGELOG.md, flake.lock, flake.nix, .github/, README.md, metadata-only files

Per-project specifics:

- **opencode** (monorepo, `fetchFromGitHub` of full repo): keep `packages/opencode/**` hunks (src/, test/, scripts/, etc.). Strip root-level docs, CI, other workspace packages.
- **qmd** (single package): keep `src/` hunks. Strip docs, CHANGELOG, flake.lock, flake.nix.

```bash
# Note: filterdiff uses fnmatch(3) — '*' matches across '/' (unlike shell globs).
# So 'packages/opencode/*' matches 'packages/opencode/src/deep/file.ts'.

# Example for opencode:
/tmp/patchutils/bin/filterdiff -p1 -i 'packages/opencode/*' /tmp/fresh.patch > /tmp/filtered.patch

# Example for qmd:
/tmp/patchutils/bin/filterdiff -p1 -i 'src/llm.ts' /tmp/fresh.patch > /tmp/filtered.patch

# GUARD: empty output = wrong pattern or PR changed scope
if [ ! -s /tmp/filtered.patch ]; then
  echo "ERROR: filterdiff produced empty output. Check -i pattern." >&2
  exit 1
fi
```

If `filterdiff` unavailable: manually delete diff sections for build-irrelevant files.

### 4. Compare & replace

```bash
diff patches/<project>/<name>.patch /tmp/filtered.patch
```

- If identical → no change needed
- If different → `cp /tmp/filtered.patch patches/<project>/<name>.patch`

### 5. Verify patch applies

```bash
# `applyPatches` unpacks src and runs `patch -p1` for each patch — nothing else.
# Unlike `srcOnly` (which inherits nativeBuildInputs and may trigger npm/cargo fetches),
# `applyPatches` only needs the source tarball + patch files → near-instant.
# Unlike --dry-run (evaluation-only, never invokes a builder), this actually executes patches.
nix build --impure --expr '
  let home = builtins.getEnv "HOME";
      flake = builtins.getFlake "git+file://${home}/.nix";
      system = builtins.currentSystem;
      pkgs = flake.inputs.nixpkgs.legacyPackages.${system};
      patchDir = /. + "${home}/.nix/patches";
  in {
    # Validates ALL patches apply together (including local/exempt ones).
    # Only PR-sourced patches need refreshing; the full set is tested for coherence.
    opencode = pkgs.applyPatches {
      src = flake.inputs.opencode.packages.${system}.default.src;
      patches = [
        (patchDir + "/opencode/proxy-env-to-process-env.patch")
        (patchDir + "/opencode/relax-bun-version-check.patch")
      ];
    };
    qmd = pkgs.applyPatches {
      src = flake.inputs.qmd.packages.${system}.default.src;
      patches = [
        (patchDir + "/qmd/fix-nixos-llama-build.patch")
      ];
    };
  }'
# Full build is only needed when:
# - Conflict resolution changed patched code semantically (not just offsets)
# - Upstream altered assumptions affecting postFixup/installPhase
# In that case: nix build --impure ".#homeConfigurations.$(whoami).activationPackage"
```

### 6. Check for offset/fuzz warnings

```bash
# A patch that applies with fuzz/offset today will FAIL tomorrow. Treat warnings as errors.
nix log <drv-path> 2>&1 | grep -E "(offset|fuzz|FAILED)"
# If any output → patch line numbers are drifting. Investigate and re-generate patch.
# The .drv path is printed by step 5's `nix build` output.
```

### 7. Commit, push, and verify

```bash
git add patches/<project>/<name>.patch
git commit -m "chore: refresh <project> PR #<N> patch"
git push
# MANDATORY: verify
git status  # must show "nothing to commit, working tree clean"
git log --oneline -1  # must show the commit just made
```

## Failure Modes

- **Patch conflict (not just offset drift)**: PR code overlaps with changes in locked rev. Manual resolution needed — inspect the diff, adjust hunks by hand.
- **PR force-pushed**: `gh pr diff` gives latest head. Patch may change semantically. Always re-filter and compare.
- **Patch applies but breaks build**: Upstream changed assumptions affecting postFixup/installPhase. Run full build to diagnose: `nix build --impure ".#homeConfigurations.$(whoami).activationPackage"`.
- **Empty filterdiff output**: Pattern wrong or PR no longer touches expected files. Investigate before proceeding.

## Key Rules

- NEVER include doc/changelog/lock/CI hunks — they cause needless offset drift without affecting builds
- ALWAYS verify against the LOCKED rev, not upstream HEAD
- `gh pr diff` gives diff against the PR's TARGET branch HEAD — if our locked rev lags behind, line numbers diverge and patches fail. When this happens: update the lock first (`nix flake update <input>`), re-download the diff, then retry.
- Treat fuzz/offset warnings as errors — a patch drifting today breaks tomorrow
- ALWAYS `git status` after commit to confirm it landed (truncated output can hide failures)
- Commit message format: `chore: refresh <project> PR #<N> patch`
