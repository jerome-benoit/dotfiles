# Process: Refresh Patches

## Context

Local patches live directly under `patches/`. Builders declare their `patches`
lists.
Prime Agent source pins come from
`home-manager/modules/development/pins/prime-agent.json`. Caveman CLI and
installer follow the `caveman` input in `flake.lock`; Blocks, release assets
and source dependency hashes use `pins/caveman.json`.
OpenCode Desktop patches follow the selected CLI source, which defaults to the
`opencode` input in `flake.lock`.
Agent of Empires patches follow the `agent-of-empires` input in `flake.lock`.
Colibri's CUDA and UI integration follows the `colibri` input in `flake.lock`.
Herdr Desktop patches follow the locked nixpkgs `herdr-desktop` source.
The `hermes-agent` input sets the base of the provider snapshot and terminal mise patches.
Reassess each patch when its own source changes.

## Naming

Use `<package>-<purpose>.patch`, in lowercase with hyphens. Start with the
name of the package being patched, not an executable or module alias
(e.g. `agent-of-empires-cursor-executable.patch`).

## Patch Metadata

Each patch records its base, intent and prerequisites. Keep relevant upstream
provenance and tracked issues; omit empty issue fields. Document a concrete
replacement condition when applicable, not a circular condition for local policy.
Proposals are not fixes in the pin, and partial coverage stays explicit.
OpenCode native V2 Stop routing is tracked by `JuliusBrussee/caveman#1539`.

### Partition and source equivalence

Caveman Hermes parser, membership, ownership and restore remain one unit.
OpenCode factories/cwd/Stop are separate. CLI and installer roots are physically
separate with one raw-absolute-root policy; trailing spaces were already preserved
in the pin. Preserving existing settings modes is a local permissions policy;
upstream deliberately applies 0600 instead.

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
   For another lock update in an open PR, compare against the branch's current
   lock, preserving its pin and patch corrections. Recheck external consumers
   even when the patch's own source is unchanged.
   Freeze pre-existing main edits without moving them; compose them with the PR
   only in an isolated validation tree. Keep those edits out of the PR commit.
   For Nixpkgs updates, trace effective package aliases, runtime closures and
   toolchain derivations, not version labels alone. Home Manager updates also
   require checking the activation, profile and shell-integration consumers.
3. Check whether upstream now supplies each fix. Remove only superseded hunks;
   retire the whole patch only when every carried change is covered upstream.
4. Apply prerequisite patches in the builder's declared order before regenerating
   remaining hunks. Preserve the headers and update `# base:` when its version or
   prerequisite changes. The CLI registration patch includes the managed-install
   guard in its base; neither patch corrects the other.
5. Verify application without fuzz or offset warnings and inspect the resulting
   code. Exercise affected behavior when code or upstream assumptions change.
   Provenance-only updates with unchanged code and consumers do not require
   aggregate runtime checks.
   Apply the package-specific checks below and record any outstanding validation.
6. Update the use-site explanation and patch headers as needed.
   Commit or push only when requested.
7. For confirmed upstream bugs, search open and closed issues and pull requests
   by affected symbol, symptom, and cause. Read the matches before reporting.
   Reuse an exact reference; otherwise report the affected revision, minimal
   proof, expected behavior, and verification limits. Do not report local policy
   as an upstream defect.

### Colibri

After updating the Colibri source, use `checks/gpu.nix` to verify the CPU,
CUDA, and Metal install plans. Check that `CUDA_GLIBC_MATH_COMPAT=0` keeps
the upstream compatibility header out of the CUDA commands.

Before retiring `colibri-openmp-cgroup-quota.patch`, run the unpatched
`test_omp_tune` with OpenMP enabled, `/sys/devices/system/cpu` masked, and more
than one logical CPU available. Verify that both cases run:

- A synthetic one-CPU quota reduces the OpenMP team to one thread. Check the
  `test_cg` diagnostic or inspect the team size before and after tuning.
- The default sizing case keeps its expected team size under a finite ambient
  quota below that size. Verify the test uses its own unlimited fixture or
  otherwise isolates this assertion from the ambient quota.

A passing exit alone does not prove either condition.

### Hermes local terminal

Keep the Hermes patches inside `nix/python.nix`'s workspace package overlay:
the outer package does not unpack the Python code, and pre-patching `pythonSrc`
would make workspace lock reads depend on a derivation. Preserve the Darwin
`fetchPnpmDeps` scope and upstream build authorization overlay.

Apply the mise patch when `programs.mise` is enabled and has a package. The
gateway marker enables shim restoration at runtime.
Keep declarative plugin directory links unchanged. Hermes issue #156560 tracks
cleanup failures; the local patch makes only owned copies writable before
publication and cleanup. Before retiring it, verify provider discovery from a
read-only source, cleanup after exit and failed partial copies, and no mutation
of source files, modes or external link targets. Use `checks/hermes-provider.py`
for discovery and cleanup and verify source preservation separately.
The regressions must exercise an unprivileged process.

For source deltas in provider cache ceilings, cwd recovery, secret routing or
offline TTS, copy only the selected upstream tests and run the installed wheel with
isolated Python imports. Keep pytest tooling outside the runtime environment.

Substitute the fixed Nix-store resolver with `--replace-fail`. The resolver uses
the configured mise package and returns PATH only; no path comes from the private
gateway boolean. Preserve the shared helper's default inert behavior and explicit
background `restore_login_path` opt-in.

Gateway mise mode must not turn a failed post-profile activation into a successful
non-login fallback. Preserve the local fallback-decision override only for the
gateway marker, and keep the regression where an explicit init file causes
activation to fail after a valid gateway launch. Unmarked fallback stays upstream.

Retire the mise patch and its resolver substitution together when the selected
source restores shim priority after profiles and inherited PATH repair, before
login snapshots and opted-in background commands. Bootstrap failure must not
fall back to non-login execution in gateway mise mode; unmarked sessions and
background commands without `restore_login_path` must keep upstream behavior.

When patched code or relevant upstream assumptions change, run
`checks/hermes-mise.py` through the public Hermes check.
It imports the actual installed wheel with its own interpreter and exercises
`LocalEnvironment` snapshots and persistent cwd, not extracted helper bodies.
Keep real mise/Node fixtures, account Bash/Zsh, all directory layouts, runtime
configuration reload, byte-identical `configFile`, and disabled/null/outside
gateway cases. A source-only import or a patched test copy is not a substitute.

### OpenCode dependency hashes

`pins/opencode.json` records hashes for the selected OpenCode source and local Bun.
Compare workspace manifests, root catalogs, native lockfile entries, the recipe,
normalizers and Bun after updating OpenCode or Nixpkgs. Recalculate all three
targets when dependency inputs change; update source and toolchain provenance together.
Keep `hashSourceRevision` and `hashNixpkgsRevision` at the revisions used to
measure the hashes. Record the selected source and toolchain separately when
reusing the hashes after validation.
Record dependency-output hash checks separately from CLI builds and ARM-targeted
`--cpu`/`--os` calculations separately from native builds. Do not carry forward
verification claims from an older source. Keep hash-only checks serial with
`--max-jobs 1 --cores 1`; they do not require a full CLI or Desktop build.

Use a disk-backed `TMPDIR` for standalone calculations when `/tmp` is tmpfs;
large dependency trees otherwise count against the memory limit. Replay the
selected dependency derivation's filters, frozen lock, normalizers and
`installPhase`. The default package override skips descending into `node_modules`
trees it has already copied recursively. The upstream `node_modules_updater`
keeps its original copy command. Calibrate the procedure against
the previous known native pin at its exact source and Bun version before
trusting new outputs. If calibration is performed afterwards, record it as
retrospective without rewriting the initial execution history. Limit Bun network
concurrency without changing dependency selection. Import only outputs whose
NAR hash and fixed-output store path match the selected derivation.

Copy-free NAR calculation requires an exact format check against Nix and calibration
against the previous per-target reference. Preserve output paths, symlinks and
executable bits; this byte proof does not establish fixed-output registration.

Use `inputs.opencode` from this repository's evaluated flake so its
`nixpkgs.follows` supplies the actual Bun toolchain. CLI `--override-input`
does not override inputs loaded by `builtins.getFlake` inside `--expr`.
Check the evaluated derivation's Bun input before calculating hashes.
Use a fake output hash or an explicit rebuild to force fresh output:
a successful build can otherwise reuse an existing fixed-output store path
without checking the current recipe.

If a calculation is interrupted, inspect completed phases and retained outputs
before retrying. Hash a completed dependency output directly instead of rebuilding it.
Restart only the unfinished phase, with a bounded deadline.

### OpenCode Desktop stages

Retire the stage patch and adjacent `postPatch` substitution together when the
selected source isolates distinct CLI builds with the same version, architecture,
and channel, and retains both bundled and adopted stages for the current
architecture. Test same-version Nix rebuilds; channel isolation alone is not
enough. Assess the separate `OPENCODE_CLI_DIST` fix against the Desktop build's
actual input directory.

### Caveman source pin

The Caveman CLI and installer use the `github:JuliusBrussee/caveman/main`
source input. Upstream has no flake, so `flake = false` supplies its source
to the local derivations, like other source-built packages in this repository.
`flake.lock` records the revision; do not duplicate it in the JSON asset pin.

Run `bash scripts/fix-nix-hashes.sh update <base-ref>` only in an isolated CI
checkout with a clean index and working tree. Commit the lock change before
running it: selection compares `HEAD` against the merge base. The updater sets
repository-local Git author config, stages all three pin paths and commits the
whole index if nonempty. It does not push.

There is no standalone, non-committing updater command. For local recalculation,
use the committed candidate lock in a clean temporary clone. Replay the
`caveman_pnpm_hash` and `blocks_vendor_hash` Nix commands from
`scripts/fix-nix-hashes.sh` with that clone and its locked Nixpkgs. Accept only
the expected fixed-output mismatch. Read `packages/cli/BINARY_RELEASE` and
`BLOCKS_RELEASE` from the evaluated `inputs.caveman.outPath`. Render the pinned
URL templates for the declared platforms and names. Use
`nix store prefetch-file --json` for each runtime asset and license, and add
`--unpack` for the Blocks source archive. Use that unpacked hash for the Blocks
vendor probe. Review and transfer only the intended JSON changes. All six
companions and license notices follow the binary release; Blocks has its own
source and vendor hash. Do not infer these versions from the CLI's `package.json`.

Keep the CLI's `supersede-stdin` capability check: older Cavemem binaries store
the literal flag as replacement text. Check real stdin replacement, history and
oversized-input refusal against temporary stores, never user data.

CLI patches target TypeScript before the offline pnpm build. The installer patch
targets the same source tree separately, without shipping build dependencies.
When refreshing, preserve upstream changes underneath local adapters: ordinary
model overrides keep upstream's atomic writer; prepared plugins collect writes
into their ownership-journal transaction. Preserve the host-shell renderer when
porting execution-time callbacks instead of restoring an older hook formatter.

Apply every patch in its declared order without offsets or fuzz. Drop only hunks
whose behavior the selected source now supplies. Run the installed-runtime check
with a real YAML parser for both the Hermes Native and Shrink writers. Run the
CI updater contract separately.

While the Hermes scope patch is active, verify that `caveman wrap --codemode
hermes` launches Hermes without a Code Mode overlay. With another supported
agent, verify that Code Mode discovers its MCP servers but excludes Hermes
servers. Check that `caveman-mcp codemode` accepts an explicit JSON config,
rejects a missing `--config`, and rejects automatic discovery even with a config.

Retire the CLI patch when the pinned CLI preserves Hermes MCP filters in launch
and discovery and refuses unsafe configuration writeback. Assess the wrapper
against the pinned `caveman-mcp` release independently: it must require explicit
JSON configuration and reject automatic discovery even with a config, or
discover Hermes safely without bypassing its filters or changing its configuration.

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

Blocks package checks run the CLI suite, `internal/hook` and the `hooks` e2e
scenario.

Before dropping the config-root patch, verify detection and install/status/uninstall
share `OPENCODE_CONFIG_DIR`, `XDG_CONFIG_HOME/opencode`, then `~/.config/opencode`
precedence. A relative effective root must fail without writes. Preserve foreign
files, alternate roots and stable launcher targets. Assert filesystem behavior,
not the printed representation of OpenCode paths.
The plugin e2e scenario requires Bun; the installed-runtime check exercises both
OpenCode APIs under Node.

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

Managed `caveman-install --hook-node` accepts only the selected profile's exact
lexical `lib/caveman/node` path; other overrides fail before preparation or writes.
Without Nix management, prepared plugins honor upstream's bare or absolute Node
override, while omission retains the normal interpreter discovery.

Prepared plugins emit host callbacks even with `--no-hooks` or `--minimal`.
Explicit absolute Node overrides must therefore run a supported interpreter
before preparation writes a payload or ownership journal. Outside Nix management,
disabled-hooks removal skips interpreter-version checks for unused overrides.
Nix-managed overrides still require a supported private Node at the selected
profile path. Bare `node` retains upstream's warning-only PATH lookup.

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

Prepared Claude statusline suggestions pass the profile's raw absolute Bash path
through the upstream host-shell renderer. Preparation-owned metadata stores
`bashPath`, not a prequoted shell word. Existing accepted statusline commands
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
Hermes tracks `NousResearch/hermes-agent` directly. Follow the historical
`hermes_agent_sync_main_patched` procedure only for an explicit migration back
to that fork, not for routine patch or lock refreshes.

### 1. Check PR status against locked rev

```bash
INPUT='<input-name>'
LOCKED_REV=$(jq -er --arg input "$INPUT" '
  .nodes[.nodes[.root].inputs[$input]].locked.rev
  | strings | select(test("^[0-9a-fA-F]{40}$"))
' flake.lock) &&
REPO='<OWNER>/<REPO>' &&
PR_NUMBER='<PR_NUMBER>' &&
PR_JSON=$(gh pr view "$PR_NUMBER" --repo "$REPO" \
  --json state,mergeCommit,baseRefOid,headRefOid) &&
printf '%s\n' "$PR_JSON"
```

If `state: "MERGED"`, verify merge is included in locked rev:

```bash
# "ahead" or "identical" → merge included; inspect coverage of each carried change
# "behind" or "diverged" → ancestry does not establish inclusion
MERGE_SHA=$(jq -er '
  .mergeCommit.oid | strings | select(test("^[0-9a-fA-F]{40}$"))
' <<<"$PR_JSON") &&
  gh api "repos/$REPO/compare/$MERGE_SHA...$LOCKED_REV" --jq '.status'
```

- If the merge is included, remove only changes covered by the pinned source.
  Keep local fixes not supplied upstream; retire the patch only when all carried
  changes are covered. For complete removal, use
  `chore: remove merged <project> PR #<N> patch`.
- If `state: "CLOSED"` without merge, decide whether to propose the change again,
  keep it locally or drop it.
- If `state: "OPEN"` or changes remain after a merge, continue below.

### 2. Generate a candidate from the observed commits

Use the base and head OIDs from step 1, not a second request for the live PR
diff. Fetch both commits in a temporary clone or repository. For a fork, the PR
head ref can be used to obtain the objects only if it resolves to the observed
head OID. Stop and re-observe the PR if the selected commits cannot be obtained.

```bash
PR_BASE=$(jq -er '.baseRefOid | strings | select(test("^[0-9a-fA-F]{40}$"))' <<<"$PR_JSON")
PR_HEAD=$(jq -er '.headRefOid | strings | select(test("^[0-9a-fA-F]{40}$"))' <<<"$PR_JSON")
PATCH_TMP=$(mktemp -d)
git -C "$PATCH_TMP" init -q
git -C "$PATCH_TMP" fetch "https://github.com/$REPO.git" "$PR_BASE" "$PR_HEAD"
DIFF_BASE=$(git -C "$PATCH_TMP" merge-base "$PR_BASE" "$PR_HEAD")
git -C "$PATCH_TMP" diff --no-color --no-ext-diff --no-textconv --binary \
  "$DIFF_BASE" "$PR_HEAD" > "$PATCH_TMP/fresh.patch"
```

Run the steps only if the preceding command succeeds. Record the PR URL,
observed base and head OIDs, and effective merge-base OID with the refresh.
These identify the candidate, not the pinned source to which the local patch
applies. Keep the selected upstream provenance in the local patch headers.

### 3. Filter by build and runtime use

The patch applies during `patchPhase` on the full fetched source. Keep hunks
needed by the builder, installed runtime or relevant checks. Judge each file by
its actual consumers, not its directory or extension.

- Keep source, scripts, tests and configuration used by the selected package.
- Keep documentation, manifests, lock files or Nix expressions when the builder
  consumes them or the installed runtime requires their changes.
- Strip unrelated prose, changelog entries, CI changes and unused metadata.

These examples require `filterdiff` from `patchutils` in `PATH`. If needed, enter `nix shell nixpkgs#patchutils` first.

```bash
# Note: filterdiff uses fnmatch(3) — '*' matches across '/' (unlike shell globs).
# So 'packages/opencode/*' matches 'packages/opencode/src/deep/file.ts'.

# Example for opencode:
filterdiff -p1 -i 'packages/opencode/*' "$PATCH_TMP/fresh.patch" > "$PATCH_TMP/filtered.patch"

# Example for qmd:
filterdiff -p1 -i 'src/llm.ts' "$PATCH_TMP/fresh.patch" > "$PATCH_TMP/filtered.patch"

# GUARD: empty output = wrong pattern or PR changed scope
if [ ! -s "$PATCH_TMP/filtered.patch" ]; then
  echo "ERROR: filterdiff produced empty output. Check -i pattern." >&2
  exit 1
fi
```

If `filterdiff` is unavailable, remove only sections unrelated to the selected
build, runtime and checks.

### 4. Compare and regenerate

Compare by file and hunk: compare added, removed and context lines, including
their whitespace, without provenance headers, diff metadata or hunk offsets.
Review path, mode, rename or binary changes separately. Header-only drift does
not establish a change to the hunks; identical hunks need no regeneration.

Regenerate required changes against the pinned source after applying its
prerequisites. Do not overwrite the local patch with the filtered candidate.
Preserve local hunks absent from the candidate unless the selected source
supplies their behavior. Preserve provenance headers, update the pinned base
when it changes, and distinguish newly imported upstream hunks from local fixes.

### 5. Verify patch application against the builder's source

Run from the repository worktree being changed. This example checks the Caveman CLI patch sequence, including its declared prerequisites:

```bash
nix build --impure --no-link --print-out-paths --expr '
  let
    root = builtins.getEnv "PWD";
    flake = builtins.getFlake ("git+file://" + root);
    system = builtins.currentSystem;
    pkgs = flake.inputs.nixpkgs.legacyPackages.${system};
    package = flake.packages.${system}.caveman.cliPackage;
  in pkgs.applyPatches {
    name = "caveman-patch-application";
    src = package.src;
    patches = package.patches;
  }'
```

`applyPatches` unpacks the selected source, applies the ordered patches and copies the resulting tree to its output. It does not build the application. Fetching sources and realizing the helper's build dependencies can still take time. `--dry-run` does not execute patch application.

Use the actual builder for each other target:

- Caveman installer: use `flake.packages.${system}.caveman.installerSource` and its `src` and `patches`, not the CLI derivation.
- Caveman Blocks: instantiate `caveman/blocks.nix` with `pins.caveman.blocks` from `development/pins/default.nix`, then use `nativePackage.src` and `nativePackage.patches` from the wrapper's passthrough. Blocks has its own JSON-pinned source.
- Prime Agent: use `pins.primeAgent.src` from `development/pins/default.nix` and the complete ordered patch list in `development/prime-agent.nix`.
- Herdr Desktop: use `pkgs.herdr-desktop.src`; preserve its existing `patches` before appending the local patch, as `development/herdr.nix` does for Darwin.

For other packages, resolve the source and ordered patch list from the selected builder. Preserve prerequisite order and any existing upstream patches. Include new patch files in the flake's Git source snapshot before checking application.

Inspect the applied files and patch log. Application alone does not verify syntax, compilation or runtime behavior. Run the affected syntax and package or behavior checks when patched code or upstream assumptions change; choose checks for the actual package rather than defaulting to the current user's full activation build.

### 6. Check for offset/fuzz warnings

Use the output path printed by step 5. Retrieve the log before checking warnings
so a failed retrieval cannot look like a clean patch application. If no log is
available, rebuild locally to obtain one before declaring this check complete.

```bash
(
  PATCH_LOG=$(mktemp) || exit 1
  trap 'rm -f "$PATCH_LOG"' EXIT
  if ! nix log '<output-store-path>' >"$PATCH_LOG" 2>&1; then
    cat "$PATCH_LOG" >&2
    echo "Could not retrieve the patch log; warning check incomplete." >&2
    exit 1
  fi
  if grep -Ei 'offset|fuzz|FAILED' "$PATCH_LOG"; then
    echo "Patch warnings or failures; inspect and regenerate against the selected base." >&2
    exit 1
  else
    case $? in
      1) echo "No offset, fuzz or failure messages found." ;;
      *) echo "Could not inspect the patch log." >&2; exit 1 ;;
    esac
  fi
)
```

### 7. Publish only when requested

Commit only when requested. If every change in the listed paths belongs in the
commit, review those paths against `HEAD` and use a path-limited commit.
Add any intended new files by path first so Git can include them.

```bash
PATCH_PATH='patches/<name>.patch'
git diff HEAD -- "$PATCH_PATH"
git commit --only -m "chore: refresh <project> PR #<N> patch" -- "$PATCH_PATH"
```

Include intended pin or builder paths in both commands. A path-limited commit
uses the working-tree contents of those paths; do not use it for partial changes
within a file. Use an isolated index or selective commit workflow in that case.
Never let the commit pick up unrelated staged changes. Confirm the commit
contains only intended changes; leave other staged and working-tree edits intact.

Push only when requested, and verify publication to the requested remote and branch. Authorization to commit does not itself authorize a push.

## Failure Modes

- **Patch conflict (not just offset drift)**: PR code overlaps with changes in locked rev. Manual resolution needed — inspect the diff, adjust hunks by hand.
- **PR force-pushed**: Re-observe the base and head OIDs before selecting a new candidate. Re-filter and compare the candidate hunks.
- **Patch applies but breaks build**: Diagnose with the affected package derivation or smallest relevant check. Inspect changed assumptions in `postFixup` or `installPhase`. Use full Home Manager activation only for an activation-specific issue that focused checks cannot resolve.
- **Empty filterdiff output**: Pattern wrong or PR no longer touches expected files. Investigate before proceeding.
