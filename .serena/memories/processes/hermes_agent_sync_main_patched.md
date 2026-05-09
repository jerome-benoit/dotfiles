# Process: Sync hermes-agent main-patched with upstream

## Context
- Fork: `github:jerome-benoit/hermes-agent` branch `main-patched`
- Upstream: `github:NousResearch/hermes-agent` branch `main`
- The fork carries 3 commits on top of upstream:
  1. `fix(tools/delegate): align direct endpoint transport heuristics` (PR #13567)
  2. `fix(tools/delegate): add kimi detection and docstring` (PR #13567)
  3. `fix(nix): skip av/faster-whisper build checks on aarch64-darwin` (NixOS/nix#15638 workaround)
- Flake input: `hermes-agent.url = "github:jerome-benoit/hermes-agent/main-patched"`

## Process

### 1. Clone, add upstream, rebase
```bash
_workdir=$(mktemp -d)
git clone --filter=blob:none https://github.com/jerome-benoit/hermes-agent.git "$_workdir/h" -b main-patched
cd "$_workdir/h"
git remote add upstream https://github.com/NousResearch/hermes-agent.git
git fetch upstream main --filter=blob:none
git rebase --empty=drop upstream/main
```

### 2. Validate rebase result
```bash
# Verify expected commit count (adjust as commits drop)
echo "Commits ahead: $(git rev-list --count upstream/main..HEAD)"
git log --oneline upstream/main..HEAD
```
- If a patch commit was merged upstream → it auto-drops during rebase (empty commit)
- If conflict → resolve keeping our changes in files we patched
- Expected: 3 commits (2 delegate + 1 darwin fix). If different, investigate.

### 3. Force push
```bash
git push --force-with-lease origin main-patched
```

### 4. Update flake lock
```bash
cd /  # avoid dangling CWD before cleanup
rm -rf "$_workdir"
nix flake update hermes-agent --flake /Users/I339261/.nix
# If fetch fails: GitHub CDN propagation delay after force-push. Retry after 30-60s.
```

### 5. Verify
```bash
# --dry-run is acceptable here (unlike patch refresh process, which uses srcOnly to
# execute patchPhase) because there are no nix patches to apply. The fixes live as
# commits in the fork source. --dry-run verifies evaluation (valid rev, no missing attrs).
# A full build is optional but recommended after conflict resolution.
nix build /Users/I339261/.nix#homeConfigurations.I339261.activationPackage --dry-run
```

### 6. Commit and push
```bash
git -C /Users/I339261/.nix add flake.lock
git -C /Users/I339261/.nix commit -m "chore: update hermes-agent lock"
git -C /Users/I339261/.nix push
```

## One-liner (when no conflicts expected)
```bash
_workdir=$(mktemp -d) && git clone --filter=blob:none https://github.com/jerome-benoit/hermes-agent.git "$_workdir/h" -b main-patched && cd "$_workdir/h" && git remote add upstream https://github.com/NousResearch/hermes-agent.git && git fetch upstream main --filter=blob:none && git rebase --empty=drop upstream/main && [[ $(git rev-list --count upstream/main..HEAD) -ge 1 ]] || { echo "ERROR: 0 commits ahead"; exit 1; } && git push --force-with-lease origin main-patched && cd / && rm -rf "$_workdir"
```
Then:
```bash
nix flake update hermes-agent --flake /Users/I339261/.nix && git -C /Users/I339261/.nix add flake.lock && git -C /Users/I339261/.nix commit -m "chore: update hermes-agent lock" && git -C /Users/I339261/.nix push
```

## When to sync
- When fork is behind upstream (check: `git rev-list --count HEAD..upstream/main` after fetch)
- After upstream merges one of our PRs (commit auto-drops)
- Before `nix flake update` to avoid stale fork

## Monitoring
- PR #13567 (delegate transport) — when merged, 2 commits auto-drop
- NixOS/nix#15638 (daemon code signing) — when fixed, remove `nix/python.nix` commit from fork
- hermes-agent tui npmDepsHash — goes stale frequently (issue #15272); fix: update hash in fork's `nix/tui.nix`

## Key Rules
- PREFER `--force-with-lease` (catches unexpected pushes from another machine). If rejected due to stale ref from same-session push, use `--force` after verifying commit count is correct.
- If commits drop to 0 → fork identical to upstream → switch input back to `github:NousResearch/hermes-agent`
- Commit message in dotfiles: `chore: update hermes-agent lock`
- If a commit drops, note in message: `chore: update hermes-agent lock (drop <desc>, now upstream)`
