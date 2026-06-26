# Process: Sync `hermes-agent/main-patched`

## Current state
- Fork input: `github:jerome-benoit/hermes-agent/main-patched`.
- Upstream: `github:NousResearch/hermes-agent/main`.
- Last verified sync: 2026-06-26.
- Upstream synced to: `8ab7246c45383cfcda4944d3872efa56f515f87f`.
- Fork `main-patched` verified at: `fd7243e9af4447fd987be91466c776ff4665678a`.
- Local `.nix/flake.lock` Hermes lock: `fd7243e9af4447fd987be91466c776ff4665678a`, `narHash = sha256-g66O9+vSbAUrsUWkfe2Pz3mNKorbWzJOLMM8H3n7oXQ=`.

## Preserved fork patches
`main-patched` should be `0 behind / 3 ahead` of upstream while these temporary fixes are active:
1. `fix(nix): skip av/faster-whisper build checks on aarch64-darwin`
2. `fix(nix): prebuilt python-olm on aarch64-darwin (no macOS wheels)`
3. `fix(npm): restore esbuild linux optional dependency`

## Sync rules
- Run all git commands as `GIT_MASTER=1 git ...`.
- Work in a temporary clone under `/tmp/opencode`, never in `/home/fraggle/.nix`.
- Record the old remote fork SHA before rewriting.
- Rebuild the branch from fresh `upstream/main`, then cherry-pick the preserved patches in order.
- Push only with exact lease: `--force-with-lease=refs/heads/main-patched:<old_remote_sha>`.
- Fetch and verify `origin/main-patched == local HEAD` before updating `.nix/flake.lock`.
- Do not commit or push dotfiles unless explicitly requested.

## Verification
- Check fork shape: `GIT_MASTER=1 git rev-list --left-right --count upstream/main...origin/main-patched` should be `0 3`.
- Check esbuild lock: `apps/desktop/package.json` and `package-lock.json` must pin `esbuild` to `0.28.1`, and `package-lock.json` must include `node_modules/@esbuild/linux-x64`.
- Build check used for the latest sync: `nix build --no-link --print-build-logs .#desktop` in the Hermes clone, then the same desktop build through the local `.nix` flake input.

## Drop conditions
- Drop the av/faster-whisper patch when NixOS/nix#15638 no longer requires the aarch64-darwin check workaround.
- Drop the python-olm patch when usable aarch64-darwin wheels exist upstream.
- Drop the esbuild patch when upstream restores npm optional native package lock entries or removes the Nix build path entirely.
- If all patches drop, point `.nix` back to `github:NousResearch/hermes-agent` instead of the fork.
