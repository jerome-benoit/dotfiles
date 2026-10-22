# Process: Refresh Patches

## Context

The six local patches live directly under `patches/`. Their builders declare
the `patches` lists directly; source versions and hashes come from
`home-manager/modules/development/pins/{prime-agent,caveman}.json`.
The three flake inputs `hermes-agent`, `opencode` and `strata` do not set these
patch bases. Reassess each patch when its own source pin changes.

## Current Patches

None pending refresh. The tree carries six patches, each with a `# base:` and
`# intent:` header, and a comment at its use site explaining why it exists and
when it can go:

- `patches/prime-agent-nix-self-update.patch` — refuse Nix-managed self-update and fix `PI_OFFLINE` parsing.
- `patches/prime-agent-darwin-tests.patch` — skip the Darwin ps comparison when process ground truth is unavailable.
- `patches/prime-agent-nix-daemon-generation.patch` — reject different or unverifiable daemon executables without stopping existing sessions.
- `patches/prime-agent-bundled-docs.patch` — point login guidance to the bundled upstream README.
- `patches/caveman-nix-managed-install.patch` — refuse every executable install and self-update path.
- `patches/caveman-blocks-nix-hooks.patch` — keep the Nix wrapper as the installed hook.

## Local Patch Refresh

1. Read the patch's `# base:` / `# intent:` headers and its builder's use-site
   comment. Check every carried change, not only the patch's main purpose.
2. Resolve the exact source from `pins/default.nix` and the corresponding JSON
   pin. Use that hash-pinned source, not the current contents of a mutable tag.
3. Check whether upstream now supplies each fix. Remove only superseded hunks;
   retire the whole patch only when every carried change is covered upstream.
4. Regenerate remaining hunks against the pinned source, preserving the headers
   and updating `# base:` when its version changes.
5. Verify application without fuzz or offset warnings and inspect the resulting
   code. Exercise affected behavior when code or upstream assumptions change.
6. Update the use-site explanation, removal condition and inventory as needed.
   Commit or push only when requested.

## PR-Derived Patch Refresh

Use this procedure only for a patch associated with an upstream PR. Set the
actual patch path; no `patches/<project>/` layout is assumed. The commands below
use a flat `patches/<name>.patch` path.

Resolve the source revision from its actual pin. The `flake.lock` example in
step 1 applies only to flake inputs, not the current JSON-pinned packages.
When refreshing a Hermes fork patch, follow `hermes_agent_sync_main_patched`
before updating its input.

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
diff patches/<name>.patch /tmp/filtered.patch
```

- If identical → no change needed
- If different → replace the patch body, preserving its `# base:` / `# intent:` headers.

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
  in pkgs.applyPatches {
    src = flake.inputs.<input>.packages.${system}.default.src;
    patches = [ (patchDir + "/<name>.patch") ];
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
git add patches/<name>.patch
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
