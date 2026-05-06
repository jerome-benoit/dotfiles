# Process: Refresh Patches from PRs

## Context
Patches in `patches/<project>/*.patch` come from unmerged upstream PRs.
Applied via `overrideAttrs` adding to `patches` list (see `opencode.nix`, `qmd.nix`).
When the locked input advances, patch line offsets drift → must refresh.

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

### 5. Verify patch applies (MUST actually build)
```bash
# --dry-run only checks evaluation, NOT patch application.
# Must do a real build to verify patches apply cleanly:
nix build .#homeConfigurations.I339261.activationPackage
```

### 6. Commit
```bash
git add patches/<project>/<name>.patch
git commit -m "chore: refresh <project> PR #<N> patch"
```

## Failure Modes
- **Patch conflict (not just offset drift)**: PR code overlaps with changes in locked rev. Manual resolution needed — inspect the diff, adjust hunks by hand.
- **PR force-pushed**: `gh pr diff` gives latest head. Patch may change semantically. Always re-filter and compare.
- **Patch applies but breaks build**: Upstream changed assumptions. May need to update patch logic, not just offsets.
- **Empty filterdiff output**: Pattern wrong or PR no longer touches expected files. Investigate before proceeding.

## Key Rules
- NEVER include doc/changelog/lock/CI hunks — they cause needless offset drift without affecting builds
- ALWAYS verify against the LOCKED rev, not upstream HEAD
- Commit message format: `chore: refresh <project> PR #<N> patch`
