# Process: Refresh Patches

## Context

Local patches live directly under `patches/`. Builders declare their `patches`
lists; the Strata launcher declares its runtime source patch.
Prime Agent source pins come from
`home-manager/modules/development/pins/prime-agent.json`. Caveman CLI and
installer follow the `caveman` input in `flake.lock`; Blocks, release assets
and source dependency hashes use `pins/caveman.json`.
OpenCode Desktop patches follow the selected CLI source, which defaults to the
`opencode` input in `flake.lock`.
Agent of Empires patches follow the `agent-of-empires` input in `flake.lock`.
Colibri patches follow the `colibri` input in `flake.lock`.
Herdr Desktop patches follow the locked nixpkgs `herdr-desktop` source.
The `strata` input sets the base of its runtime setup patch. The `hermes-agent`
input sets the base of its local terminal shim-priority patch.
Reassess each patch when its own source changes.

## Naming

Use `<package>-<purpose>.patch`, in lowercase with hyphens. Start with the
name of the package being patched, not an executable or module alias
(e.g. `agent-of-empires-cursor-executable.patch`).

## Current Patches

Each patch records its base, intent and prerequisites. Keep relevant upstream
provenance and tracked issues; omit empty issue fields. Document a concrete
replacement condition when applicable, not a circular condition for local policy.
Proposals are not fixes in the pin, and partial coverage stays explicit.
Hermes provider causes are tracked by #156556 (identity), #156557 (hosted RPC),
#156558 (activation), #156559 (namespaces) and #156560 (readonly POSIX cleanup)
in `NousResearch/hermes-agent`. PR156224 is proposed partial rollback/concurrency
coverage. The selected source supplies persistent owner-locked roots and reclamation
(#156493); local read-only cleanup composes with that protocol. PR156209 is a
historical persistence proposal, closed without merge; it does not supply reclamation.
OpenCode native V2 Stop routing is tracked by `JuliusBrussee/caveman#1539`.

- `patches/agent-of-empires-cursor-executable.patch` — detect and launch the packaged cursor-agent executable instead of agent.
- `patches/caveman-blocks-config-root.patch` — resolve the OpenCode hook profile against the absolute effective config root. Prerequisites: caveman-blocks-nix-hooks.patch, caveman-blocks-opencode2.patch (in order).
- `patches/caveman-blocks-nix-hooks.patch` — link the selected profile wrapper as the installed hook without copying the executable.
- `patches/caveman-blocks-opencode2.patch` — support OpenCode 1/2 with invocation-scoped hints and location-relative workdirs.
- `patches/caveman-cli-config-root.patch` — require raw absolute OpenCode override with existing root precedence. Prerequisites: caveman-opencode-lifecycle.patch.
- `patches/caveman-hermes-native-yaml.patch` — use one strict Hermes span/scalar/list parser for native and shrink membership, ownership and restoration. Prerequisites: caveman-nix-managed-install.patch, caveman-nix-registration-paths.patch.
- `patches/caveman-installer-config-root.patch` — require raw absolute override in installer and copied plugin; preserve XDG fallback. Prerequisites: caveman-nix-installer-paths.patch.
- `patches/caveman-installer-settings-permissions.patch` — local policy: preserve existing settings modes during atomic replacement; new files remain 0600.
- `patches/caveman-nix-installer-paths.patch` — use profile-local interpreters and isolate mutable Claude payload ownership. Prerequisites: caveman-installer-settings-permissions.patch (integration tests; bridge production independent).
- `patches/caveman-nix-managed-install.patch` — refuse executable installation and self-update in the CLI, durable npm installer and module downloader.
- `patches/caveman-nix-registration-paths.patch` — separate closure-local execution from durable profile registrations and migrate active journal paths. Prerequisites: caveman-nix-managed-install.patch.
- `patches/caveman-opencode-lifecycle.patch` — keep factory-local native state, explicit workdirs and model-idle Stop; retain both APIs. Prerequisites: caveman-nix-managed-install.patch, caveman-nix-registration-paths.patch, caveman-hermes-native-yaml.patch.
- `patches/colibri-cuda-glibc.patch` — preserve the CUDA/glibc math exception specifications supplied by Nixpkgs.
- `patches/herdr-desktop-nix-cli-link.patch` — keep Nix-managed macOS apps from installing user CLI links.
- `patches/hermes-agent-provider-activation-ui.patch` — do not classify pending provider activation as next-chat tools or prompts.
- `patches/hermes-agent-provider-reload.patch` — preserve frozen provider versions, coherent published readers, context-local home discovery and owned-copy cleanup.
- `patches/hermes-agent-provider-update-tests.patch` — verify provider publication, structured errors and retained clients without pinning display wording. Check-only.
- `patches/hermes-agent-terminal-mise-shims.patch` — restore gateway mise shim priority after local login profiles, before snapshots and opted-in background commands.
- `patches/opencode-nix-cli-stages.patch` — isolate Nix CLI builds and retain bundled and adopted stages for the current architecture.
- `patches/opencode-nvim-execution-lifecycle.patch` — register native OpenCode execution lifecycle events and map completion or interruption to idle status.
- `patches/prime-agent-bundled-docs.patch` — point provider login guidance at the bundled, version-matched upstream README.
- `patches/prime-agent-darwin-tests.patch` — skip the Darwin ps comparison when /bin/ps cannot read the live process.
- `patches/prime-agent-nix-daemon-generation.patch` — verify Nix executable identity on probes, session handshakes and reconnects.
- `patches/prime-agent-nix-self-update.patch` — refuse managed CLI/core/TUI self-update before effects; preserve read-only --check.
- `patches/prime-agent-python-skill-source.patch` — bind Nix kernel imports to selected non-project skill sources without installing dependencies.
- `patches/prime-agent-release-offline.patch` — use the catalog boolean parser for release-check PI_OFFLINE.
- `patches/strata-cli-validation.patch` — validate serve and monitor arguments before optional dependencies. Prerequisites: strata-workspace-source-lifecycle.patch (shared parse_args/preflight contract).
- `patches/strata-destination-budgets.patch` — account remaining downloads and preparation by destination filesystem. Prerequisites: strata-setup-directory-roles.patch.
- `patches/strata-engine-inspection.patch` — inspect SYCL launcher and mapped host engine/argument paths without importing server.
- `patches/strata-selected-executable.patch` — verify the selected manifest executable, hash and execute permission.
- `patches/strata-setup-directory-roles.patch` — share artifact roles and selected destinations across setup, forecast and progress, including native macOS Control --models-dir. Prerequisites: strata-workspace-source-lifecycle.patch (source bootstrap and shared setup dispatch).
- `patches/strata-windows-cmake-metadata.patch` — refresh Windows vision metadata with native CRLF contexts. Prerequisites: strata-workspace-source-lifecycle.patch.
- `patches/strata-workspace-source-lifecycle.patch` — keep source CLI/bootstrap and complete workspace/source lease handoff protocol together.

### Partition and source equivalence

Caveman Hermes parser, membership, ownership and restore remain one unit.
OpenCode factories/cwd/Stop are separate. CLI and installer roots are physically
separate with one raw-absolute-root policy; trailing spaces were already preserved
in the pin. Preserving existing settings modes is a local permissions policy;
upstream deliberately applies 0600 instead.

Strata workspace/source publication stays indivisible. Roles, forecasts and
progress use one layout; budgets depend on roles. Validation uses the shared
source parser; SYCL inspection and selected-executable verification are distinct.
`home-manager/modules/development/strata-source-patch.nix` defines the same ordered
atomic composite for launcher and checks, without changing the helper API.

Compare the complete applied stack with its previous composition, then reverse
the composite to the pinned base. This proves application and source equivalence,
not runtime behavior. In Strata's initial a00be3c8 → f96717e87c partition, the only
behavioral change was Control --models-dir parity on Darwin. Keep its complete
consumer regression; later provider corrections are outside that comparison.
At Strata c77572806996349b49995e4f98d41b5294d36a21, DeepSeek is deliberately
retired by the parser, installer, catalog, runtime, server and updater. Remove
only local hunks and test slices whose consumers disappeared; do not recreate
its tables, helpers or dispatch branches. Keep supported Qwen and Qwen36 source
reuse, moves, ready/QAD outputs, vision and image VAE role destinations.

Cache retirement checks before a monitor releases its source read lease: its
updater and runtime import `strata_control.retired` later, after a source rollback
can remove the file. Exercise the real monitor worker and `cfg_paths.repair`
after independently publishing that rollback. Preserve the workspace/source FD
handoffs and `runtime._read_state(..., pending_ok=True)` startup behavior.

Darwin Control forecasts, progress and setup share requested destinations and
native completed-file selection. Keep --models-dir and --separate-model-artifacts
through the Darwin filter. Complete requested sets precede retained sets; partial
sets are never combined across roots. Preserve explicit personal-file selection
and keep missing readers and preparation outputs at their requested destinations.

Preserve upstream Auto drafting/card/slot signals and image noise/VAE options
when rebasing role changes. Progress keeps completed parts through steps 6/7 and
reaches 100 only when every part is complete; incomplete parts remain below 100.
Managed ordinary shards need native finish evidence when the helper is available,
not merely a final filename. Preserve explicit personal acceptance and legacy
helper-free progress; do not impose this predicate on ready SHA or reader selection.
The native GGUF tools use tools/_paths.py, strata_gguf.py and strata_quants.py by
default, and the vendored third_party/strata-gguf-py converter where required.
Keep gguf_py_env(): llama overrides can now be None. Validate compiled source
identity with the actual CMake project version, source hashes and binary marker,
not a release label or BUILD.json alone.

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
   This does not waive package-specific checks below. Source imports do not
   satisfy required installed-wheel checks; record any outstanding validation.
6. Update the use-site explanation, removal condition and inventory as needed.
   Commit or push only when requested.

### Hermes local terminal

Keep the `hermes-agent` patch inside `nix/python.nix`'s workspace package overlay:
the outer package does not unpack the Python code, and pre-patching `pythonSrc`
would make workspace lock reads depend on a derivation. Preserve the Darwin
`fetchPnpmDeps` scope and upstream build authorization overlay.

Provider discovery identifies the copied tree by names, modes and file contents,
not source timestamps. Publish its writable staging parent, preserving the copied
permissions. Cache only completed registrations, retain old versions for rollback
and late calls, and never wait for an active import from a public lookup.
Published registries are copied once per publication, not per lookup. Readers
capture registry/alias state under the publication lock, then inspect profiles
outside it. Never hold that lock across imports, callbacks or waits.
Home scans use the registration ContextVar and restore its token in `finally`.
Reserve the global discovery flag for process-wide initialization; it must not
be saved/restored by concurrent home scans. Resolver and auth guards combine
that global state with the current registration context.
The per-home publication status is independent of scan completion: loading is
reported as deferred, failed carries the current error, and only ready is active.
Read status without rescanning, using the manager home; gateway status wins over
backend status. Keep provider deferrals out of next-chat tools/prompt notices.
Extraction and RPC must use the same frozen code; the host shares the complete
version loader instead of replacing the process-wide registration function.
Cleanup restores owner access only in owned copies, including before the host
exits without atexit. Apply the wheel patch with or without mise.
Interrupted imports discard only the failed module family before waking waiters.
Home/plugin namespaces use complete, framed SHA-256 identities so long admitted
names do not expand internal storage components or collide after normalization.
`checks/hermes-provider.py` exercises canonical Copilot discovery;
`checks/hermes-provider-reload.py` covers generations, RPC, concurrency and exit
cleanup against the installed interpreter. Copying then hashing guarantees the
identity of the consumed copy, not an atomic multi-file update of a mutable source.
Exercise both concurrent completion orders, subsequent resolver/auth discovery,
import callbacks versus independent observers, failure/cancellation and the
global pending-auth guard. Advance only the provider clock; do not sleep or
mutate stamp caches to make those checks due.

For source deltas in provider cache ceilings, cwd recovery, secret routing or
offline TTS, copy only the selected upstream tests and run the installed wheel with
isolated Python imports. Keep pytest tooling outside the runtime environment.
Apply the check-only provider-update patch after copying its upstream test.
Keep publication status, structured failures and v2/v4 client coverage; do not
pin user-facing wording. The concurrent-list regression delays a real identity
lookup while a newer generation publishes and verifies both coherent views.

Substitute the fixed Nix-store resolver with `--replace-fail`. The resolver uses
the configured mise package and returns PATH only; no path comes from the private
gateway boolean. Preserve the shared helper's default inert behavior and explicit
background `restore_login_path` opt-in.

Gateway mise mode must not turn a failed post-profile activation into a successful
non-login fallback. Preserve the local fallback-decision override only for the
gateway marker, and keep the regression where an explicit init file causes
activation to fail after a valid gateway launch. Unmarked fallback stays upstream.

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
Record dependency-output hash checks separately from CLI builds and ARM-targeted
`--cpu`/`--os` calculations separately from native builds. Do not carry forward
verification claims from an older source. Keep hash-only checks serial with
`--max-jobs 1 --cores 1`; they do not require a full CLI or Desktop build.

Use a disk-backed `TMPDIR` for standalone calculations when `/tmp` is tmpfs;
large dependency trees otherwise count against the memory limit. Replay the
upstream filters, frozen lock and both normalizers. Calibrate the procedure
against the previous known native pin at its exact source and Bun version before
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

### Caveman source pin

The Caveman CLI and installer use the `github:JuliusBrussee/caveman/main`
source input. Upstream has no flake, so `flake = false` supplies its source
to the local derivations, like other source-built packages in this repository.
`flake.lock` records the revision; do not duplicate it in the JSON asset pin.

After updating the input, `scripts/fix-nix-hashes.sh update <base-ref>` refreshes
the filtered CLI pnpm hash, then reads `packages/cli/BINARY_RELEASE` and
`BLOCKS_RELEASE` from the locked source. All six prebuilt companions and license
notices follow the binary release; Blocks keeps its own source and vendor hash.
Do not infer companion versions from the CLI's `package.json`.

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

Blocks package checks run the CLI suite, `internal/hook` and the `hooks` e2e
scenario. Verify effective-root precedence, detection, install/status/uninstall
and relative-root refusal without changing hook configs or launcher targets.
Preserve foreign files and stable launcher targets; do not assert the printed
representation of OpenCode paths.
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

These examples require `filterdiff` from `patchutils` in `PATH`. If needed, enter `nix shell nixpkgs#patchutils` first.

```bash
# Note: filterdiff uses fnmatch(3) — '*' matches across '/' (unlike shell globs).
# So 'packages/opencode/*' matches 'packages/opencode/src/deep/file.ts'.

# Example for opencode:
filterdiff -p1 -i 'packages/opencode/*' /tmp/fresh.patch > /tmp/filtered.patch

# Example for qmd:
filterdiff -p1 -i 'src/llm.ts' /tmp/fresh.patch > /tmp/filtered.patch

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

### 5. Verify patch application against the builder's source

Run from the repository worktree being changed. This example checks the Caveman CLI patch sequence, including its declared prerequisites:

```bash
nix build --impure --no-link --print-out-paths --expr '
  let
    root = builtins.getEnv "PWD";
    flake = builtins.getFlake ("git+file://" + root);
    system = builtins.currentSystem;
    pkgs = flake.inputs.nixpkgs.legacyPackages.${system};
    package = flake.packages.${system}.caveman;
  in pkgs.applyPatches {
    name = "caveman-patch-application";
    src = package.src;
    patches = package.patches;
  }'
```

`applyPatches` unpacks the selected source, applies the ordered patches and copies the resulting tree to its output. It does not build the application. Fetching sources and realizing the helper's build dependencies can still take time. `--dry-run` does not execute patch application.

Use the actual builder for each other target:

- Caveman installer: use the CLI package's `installerSource.src` and `installerSource.patches`, not the CLI patch list.
- Caveman Blocks: instantiate `caveman/blocks.nix` with `pins.caveman.blocks` from `development/pins/default.nix`, then use that derivation's `src` and `patches`. Blocks has its own JSON-pinned source.
- Prime Agent: use `pins.primeAgent.src` from `development/pins/default.nix` and the complete ordered patch list in `development/prime-agent.nix`.
- Herdr Desktop: use `pkgs.herdr-desktop.src`; preserve its existing `patches` before appending the local patch, as `development/herdr.nix` does for Darwin.

For other packages, resolve the source and ordered patch list from the selected builder. Preserve prerequisite order and any existing upstream patches. Include new patch files in the flake's Git source snapshot before checking application.

Inspect the applied files and patch log. Application alone does not verify syntax, compilation or runtime behavior. Run the affected syntax and package or behavior checks when patched code or upstream assumptions change; choose checks for the actual package rather than defaulting to the current user's full activation build.

### 6. Check for offset/fuzz warnings

```bash
# Treat fuzz or offset warnings as review failures; inspect the result and regenerate against the selected base.
nix log <output-store-path> 2>&1 | grep -E "(offset|fuzz|FAILED)"
# If any output → patch line numbers are drifting. Investigate and re-generate patch.
# Use the output store path printed by step 5 with nix log; inspect the applied tree too.
```

### 7. Publish only when requested

Commit only when requested. Stage only the intended changes and inspect the staged diff, preserving unrelated working-tree changes:

```bash
git add -- patches/<name>.patch
git diff --cached
git commit -m "chore: refresh <project> PR #<N> patch"
git log --oneline -1
git show --stat --oneline HEAD
git status --short
```

Include any intended pin or builder updates in the staged review. Confirm the commit contains the intended changes; a globally clean worktree is not required. Do not discard unrelated changes to satisfy this procedure.

Push only when requested, and verify publication to the requested remote and branch. Authorization to commit does not itself authorize a push.

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
- Treat fuzz or offset warnings as review failures: inspect the applied code and regenerate against the selected base.
- Commit or push only when requested. Verify the intended commit and any authorized publication; preserve unrelated working-tree changes.
- Commit message format: `chore: refresh <project> PR #<N> patch`
