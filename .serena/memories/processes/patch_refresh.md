# Process: Refresh Patches

## Context

Local patches live directly under `patches/`. Their builders declare
the `patches` lists directly. Prime Agent source pins come from
`home-manager/modules/development/pins/prime-agent.json`. Caveman CLI and
installer patches follow the `caveman` input in `flake.lock`; its separate
Blocks source and companion assets use `pins/caveman.json`.
OpenCode Desktop patches follow the selected CLI source, which defaults to the
`opencode` input in `flake.lock`.
The `hermes-agent` and `strata` inputs do not set these patch bases.
Reassess each patch when its own source changes.

## Naming

Use `<package>-<purpose>.patch`, in lowercase with hyphens. Start with the
name of the package being patched, not an executable or module alias
(e.g. `agent-of-empires-cursor-executable.patch`).

## Current Patches

Each patch has `# base:` and `# intent:` headers, plus a comment at its use site
explaining why it exists and when it can go:

- `patches/prime-agent-nix-self-update.patch` — refuse Nix-managed self-update and fix `PI_OFFLINE` parsing.
- `patches/prime-agent-darwin-tests.patch` — skip the Darwin ps comparison when process ground truth is unavailable.
- `patches/prime-agent-daemon-discovery.patch` — remove mission-local exclusions while preserving state-root ownership.
- `patches/prime-agent-nix-daemon-generation.patch` — reject different or unverifiable daemon executables without stopping existing sessions.
- `patches/prime-agent-bundled-docs.patch` — point login guidance to the bundled upstream README.
- `patches/prime-agent-python-skill-source.patch` — import selected skill sources without installing dependencies.
- `patches/caveman-nix-managed-install.patch` — refuse every executable install and self-update path.
- `patches/caveman-nix-registration-paths.patch` — serialize profile references separately from runtime closure paths; apply after `caveman-nix-managed-install.patch`.
- `patches/caveman-nix-installer-paths.patch` — preserve private interpreters and ownership in standalone installers and prepared local plugins.
- `patches/caveman-blocks-nix-hooks.patch` — keep the profile-selected Nix wrapper as the installed hook.
- `patches/caveman-blocks-opencode2.patch` — adapt Blocks PR #17 for OpenCode 1/2, with local fixes for issues #18/#19.
- `patches/caveman-hermes-native-yaml.patch` — carry upstream PR #1395's writer fixes, recognize normalized Hermes ownership semantically, and restore only owned values.
- `patches/caveman-opencode-hermes.patch` — adapt OpenCode roots, V2 plugin scopes and Hermes YAML membership/deny-list checks; apply after managed-install, registration-paths and hermes-native-yaml.
- `patches/caveman-installer-config-root.patch` — honor the effective OpenCode root in the installer and copied plugin; apply after nix-installer-paths.
- `patches/caveman-blocks-config-root.patch` — resolve the OpenCode hook profile against the effective root; apply after blocks-nix-hooks and blocks-opencode2.
- `patches/agent-of-empires-cursor-executable.patch` — detect and launch the packaged `cursor-agent` executable; no prerequisite patches.
- `patches/opencode-nvim-execution-lifecycle.patch` — map native execution lifecycle events to editor status; no prerequisite patches.
- `patches/opencode-nix-cli-stages.patch` — isolate staged CLI builds by Nix output identity and retain all copies of the bundled and adopted service versions for the current architecture; no prerequisite patches.

## Local Patch Refresh

1. Read the patch's `# base:` / `# intent:` headers and its builder's use-site
   comment. Check every carried change, not only the patch's main purpose.
   For composite patches, preserve proposal provenance in `# upstream:` and
   identify separately tracked local defects in `# issues:`.
2. Resolve the exact source from the builder's declaration. Caveman CLI and
   installer use `inputs.caveman`, locked in `flake.lock`; JSON-pinned sources
   use `pins/default.nix` and the corresponding JSON pin. Use that locked or
   hash-pinned source, not the current contents of a mutable branch or tag.
   The installer patch records its archive URL and unpacked `fetchzip` hash;
   keep both aligned with the locked source when changing its base.
3. Check whether upstream now supplies each fix. Remove only superseded hunks;
   retire the whole patch only when every carried change is covered upstream.
4. Apply prerequisite patches in the builder's declared order before regenerating
   remaining hunks. Preserve the headers and update `# base:` when its version or
   prerequisite changes. The CLI registration patch includes the managed-install
   guard in its base; neither patch corrects the other.
5. Verify application without fuzz or offset warnings and inspect the resulting
   code. Exercise affected behavior when code or upstream assumptions change.
6. Update the use-site explanation, removal condition and inventory as needed.
   Commit or push only when requested.

### Caveman source pin

The Caveman CLI and installer use the `github:JuliusBrussee/caveman/main`
source input. Upstream has no flake, so `flake = false` supplies its source
to the local derivation, like other source-built packages in this repository.
`flake.lock` records the revision; do not duplicate it in the JSON asset pin.

After updating the input, `scripts/fix-nix-hashes.sh update <base-ref>` refreshes
the filtered CLI pnpm dependency hash, then reads `packages/cli/BINARY_RELEASE`
and `BLOCKS_RELEASE` from the locked source. Runtime assets and license notices
follow the binary release; Blocks keeps its own source and vendor hash.
Do not infer either companion version from the CLI's `package.json`.

CLI patches target TypeScript before the offline pnpm build. The installer patch
targets the same source tree separately, without shipping build dependencies.
When refreshing, preserve upstream changes underneath local adapters: ordinary
model overrides keep upstream's atomic writer; prepared plugins collect writes
into their ownership-journal transaction. Preserve the host-shell renderer when
porting execution-time callbacks instead of restoring an older hook formatter.

Apply every patch in its declared order without offsets or fuzz. Drop only hunks
whose behavior the selected source now supplies. Run the installed-runtime check,
including both Hermes writers with a real YAML parser, and the CI updater contract.

### Caveman native integrations

#### Hermes YAML

Enable, repair and disable share YAML spans and scalar decoding. Preserve
indentation, quoted keys, wrapped scalar values and plugin names, foreign
values and original nullable routes. Remove owned plugin items completely,
including their continuation lines.
Treat `#` lines inside quoted scalars as data; preserve standalone comments.

YAML separation uses ASCII space and tab. Preserve other Unicode whitespace
in scalar values, keys and continuations.
Fold physical line separation before decoding escapes. Preserve escaped
spaces and tabs; an escaped line break adds no space.

Decode quoted scalar content with YAML's literal and escaped tab rules.
Preserve tab content in block scalars. Reject tabs used for structural
indentation, including foreign descendants.

Accept supported plain string keys and plugin names, including spaces, Unicode
and `-`, `?`, `:` prefixes without separation. Match complete finite numeric and
timestamp scalars, not name prefixes. Reject duplicate keys, aliases, merge keys
and unsupported containers before writes.

Remove only standalone integration-marker comments. Preserve marker-looking
scalar content, including deferred plain scalars, quoted flow values and keys.
Fresh enable rejects unjournaled marker comments.

A null `plugin_block` or `mcp_block` marks a pre-existing foreign entry.
Restoration tolerates its removal; integration health requires its presence.
Repair owns recreated entries. Disable preserves prior user deletions.

Exercise normalization, payload-removal repair, repeated repair and disable
through the installed CLI. Verify original routes, foreign values, regenerated
payloads, ownership and MCP recovery. Retain write-free refusal coverage for
owned drift and unsupported input.

#### Blocks migration

Use the evaluated `home.profileDirectory`. Unset `CDPATH` inside the migration
subshell before walking checked directories. Preserve the caller's environment
and dry-run behavior. Exercise the evaluated Home Manager activation with
intended and alternate owned trees; only the intended hook may change.
Quote profile paths and complete diagnostic messages as shell arguments.

### OpenCode adapter

After changing the OpenCode plugin, run
`caveman-blocks hooks install --harness opencode` to refresh an existing install.
Updating the Nix package alone does not rewrite user-level agent configuration.

Both OpenCode APIs resolve shell workdirs against the active project. Pending
hints use session/call identity in V1 and session/message/call identity in V2;
recomputing an invocation clears its previous hint. Keep both API paths covered
in the installed-plugin check and the patch's e2e driver.

### Caveman registrations

The enabled Home Manager module defaults `home.sessionVariables.CAVEMAN_MODE`
to `compress` with `lib.mkDefault`. This sets the proxy mode in user sessions,
not a service: activation does not start or restart a proxy. Existing processes
keep their environment and mode. Override the session variable declaratively or
use `CAVEMAN_MODE=record caveman start` for an explicit pass-through launch.

#### Profile paths and runtime dependencies

Home Manager supplies `home.profileDirectory` to the Caveman package. Standalone,
XDG and `useUserPackages` installations therefore select their effective profile
without a second agent-root table. Package-only callers invoke a profile's
`bin/caveman` or `bin/caveman-install`, or explicitly set
`CAVEMAN_REGISTRATION_ROOT` to an absolute lexical profile prefix. Do not resolve
that executable/profile link into the store.

After package installation, activation migrates existing user-owned Blocks
hook symlinks from recognized store paths to the selected profile. This also
repairs collected targets. It neither installs absent hooks nor rewrites agent
configuration. Foreign files/links and symlinked or foreign-owned parents are
left untouched; dry-run performs no mutation.

Execution-time companion paths stay in the package closure. Generated
registrations use the selected profile's public commands and private
`lib/caveman/node`, `lib/caveman/bash` and `lib/caveman/dist` payloads.
The source-shaped installer lives at `lib/caveman/source`, with its own
`package.json`; the CLI's `package.json` stays beside `dist`. This single private
namespace survives both NixOS's default profile and Home Manager's filtered
`useUserPackages` outer profile. Neither interpreter becomes a public command.
Do not restore a `share/caveman` alias: profile filters need the actual `/lib` tree.

Temporary `wrap` packs and runtime shell-command rewrites use the executing
closure instead; they do not require a persistent registration profile.

`--with-mcp-shrink` registers the shipped JavaScript middleware through private
profile Node. It is distinct from the native `caveman-shrink` companion; preserve
the upstream command and arguments when refreshing this serializer.

#### Installation and registration

The package does not activate, repair, download or register integrations on
installation. Skills-only and delegated-manager channels keep their existing
upstream destinations and do not acquire an MCP requirement.

Agent registration remains manual. Reinstall existing generation-specific
registrations with their owning command (`caveman enable`, `caveman tools mcp
install`, `caveman tools hooks install`, or `caveman-install`); do not rewrite
stored paths or ownership journals. Agent roots, credentials and foreign entries
remain managed by the upstream serializers.

The standalone installer ships the pinned source-shaped payload. Its Claude
channel prepares an owned mutable local marketplace and delegates registration
to Claude. `--prepare-plugin claude` and `--prepare-plugin cursor` expose the same
explicit mutable layer without changing host caches or writing into the store.
Existing upstream Claude installations must be removed through their host before
choosing the local channel. Reinstall does not re-enable disabled plugins.
Uninstall retains changed payloads and foreign-scope registrations; Cursor payload
removal requires host detachment and the explicit `--plugin-detached` acknowledgment.

#### Automatic Claude profile ownership

Automatic Claude installation owns a separate payload and journal for each
ambient Claude profile. It uses the existing `claudeConfigDir()` resolver,
normalizes that root with `path.resolve` and hashes the full lexical path with
SHA256. Payloads live at
`$CAVEMAN_HOME/claude-profiles/<digest>/claude-plugin` (default
`CAVEMAN_HOME=~/.caveman`). Uninstall selects the same profile without discovering
or detaching other profiles. An absent selected-profile journal is a no-op.
Profile identity is not realpath-resolved; physical payload ancestry checks
remain mandatory. `--config-dir` changes hook files and settings only, not the
ambient profile used by `claude plugin` or its automatic payload.

Prepare-only destinations do not acquire this automatic profile identity.
`--prepare-plugin claude` keeps `$CAVEMAN_HOME/claude-plugin` by default;
`--plugin-dir` selects the explicit payload for preparation and removal.
Cursor's default and explicit prepared paths remain unchanged.

#### Legacy Claude migration

Legacy shared payloads and journals are never adopted, migrated or deleted by
the automatic channel, including with `--force`. A selected-profile marketplace
that still names another path stops installation and reports actual and expected
paths. Detach `caveman-nix` through Claude in **every** profile that refers to the
old payload (`claude plugin marketplace remove caveman-nix --scope user` in each
profile; remove any other referring scopes through their host as well).
Only after all host references are detached, remove an unchanged owned payload
with `caveman-install --prepare-plugin claude --plugin-dir <old-absolute-path>
--uninstall --plugin-detached`. Reinstall each desired automatic profile.
Foreign edits and user backups retain the existing ownership protections.
Automatic uninstall reports existing unscoped payload/journal paths as retained
state only; this advisory neither infers host references nor fails cleanup.

#### Prepared hooks and model overrides

Prepared Claude statusline suggestions use the profile's private Bash command
from preparation-owned interpreter metadata. Existing accepted statusline commands
remain user-owned; reinstall alone does not rewrite their interpreter.

Claude's prepared agent files permit the upstream SessionStart model overrides.
Only exact expected changes to an unchanged owned payload advance its digest.
Updates preflight write permissions, stage files outside the payload and commit
the journal last. Synchronous failures restore displaced originals; unsafe rollback
retains foreign edits and recovery files at the reported path. This is not
power-loss recovery or concurrent transaction isolation. Cursor remains unchanged.

#### Mutable payload constraints

Prepared plugin destinations require physical directory ancestors. Stable
executable profile symlinks remain allowed, but mutable payload ancestors may
not be symlinks, even outside the store. If `HOME` or `CAVEMAN_HOME` is aliased,
set `CAVEMAN_HOME` to a physical mutable path before installation. Alternatively,
use `--prepare-plugin` with a physical absolute `--plugin-dir`, then load that
prepared payload through the host. Never point these mutable paths into the store.

An uninstall without a prepared-plugin journal is a no-op for that channel;
an existing journal still requires the full physical-ancestor validation.

#### Runtime verification

The runtime check runs the installer's behavioral Node suite and
`checks/caveman-profiles.py` / `checks/caveman-installer.py`. The profile check
requires the package, absolute Git and Node commands, TypeBox, and two real
`buildEnv` outputs: a package profile filtered to `/bin` and `/lib`, and the same
filter around a default inner profile. Both profiles register Gemini's Delegate
server through automatic public-launcher inference, an explicit lexical root,
and private-Node launcher inference. Each generated argv must initialize and
list `caveman_delegate` with an empty external `PATH`.

The lifetime cases exercise generated callbacks, protocols and ownership across
independent same-version generations, with A removed after selecting B. Pi
recovery uses the real TypeBox dependency, not an SDK substitute. Real host
sessions and native platform execution remain separate smoke tests.

Run manual generation-copy checks with a disk-backed `TMPDIR` and a memory
limit when the host's `/tmp` is tmpfs. Large fixture copies stay under inherited
`TMPDIR`. Each scenario allocates one physically resolved native state leaf
directly under that temporary parent, falling back to `/tmp` only if needed.
The allocator bounds `run/native.sock` to 103 filesystem bytes for Darwin/Linux.
Long-`TMPDIR` smoke runs must retain that invariant without weakening Pi's real
output-replacement assertion. Stop processes before deleting state or copies;
a failed stop retains both paths and fails the check. A custom Darwin daemon
`TMPDIR` that is too long, combined with sandbox denial of `/tmp`, remains
unverified; no sandbox grants are added. Shell fixtures do not load host startup
profiles.

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
# "ahead" or "identical" → merge included; inspect coverage of each carried change
# "behind" or "diverged" → ancestry does not establish inclusion
gh api repos/<OWNER>/<REPO>/compare/<mergeCommitSha>...$LOCKED_REV --jq '.status'
```

- If the merge is included, remove only changes covered by the pinned source.
  Keep local fixes not supplied upstream; retire the patch only when all carried
  changes are covered. For complete removal, use
  `chore: remove merged <project> PR #<N> patch`.
- If `state: "CLOSED"` without merge, decide whether to propose the change again,
  keep it locally or drop it.
- If `state: "OPEN"` or changes remain after a merge, continue below.

### 2. Download fresh PR diff

```bash
gh pr diff <PR_NUMBER> --repo <OWNER>/<REPO> > /tmp/fresh.patch
```

### 3. Filter by build and runtime use

The patch applies during `patchPhase` on the full fetched source. Keep hunks
needed by the builder, installed runtime or relevant checks. Judge each file by
its actual consumers, not its directory or extension.

- Keep source, scripts, tests and configuration used by the selected package.
- Keep documentation, manifests, lock files or Nix expressions when the builder
  consumes them or the installed runtime requires their changes.
- Strip unrelated prose, changelog entries, CI changes and unused metadata.

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

If `filterdiff` is unavailable, remove only sections unrelated to the selected
build, runtime and checks.

### 4. Compare & replace

```bash
diff patches/<name>.patch /tmp/filtered.patch
```

- If identical → no change needed
- If different, regenerate the required changes against the pinned source after
  its prerequisite patches. Preserve local fixes absent from the PR diff and
  retain the provenance headers; update the base when it changes.

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

- Keep only hunks required by the selected build, installed runtime or checks.
- Verify against the selected pinned source, not upstream HEAD.
- A fresh PR diff may target a different base. Regenerate against the existing
  pinned source and its prerequisites, or update the relevant pin when the
  dependency change is intended. For flake inputs, that can mean
  `nix flake update <input>`; for JSON-pinned sources, update their source pin.
  Verify the resulting patch against the chosen base in either case.
- Treat fuzz/offset warnings as errors — a patch drifting today breaks tomorrow
- ALWAYS `git status` after commit to confirm it landed (truncated output can hide failures)
- Commit message format: `chore: refresh <project> PR #<N> patch`
