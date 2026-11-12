# Modules Reference

## Core Modules (`modules/core/`)

### constants.nix

Defines user-level constants accessible via `config.modules.core.constants`.
Private configuration is loaded through the `privateConfig` argument (SOPS-encrypted); non-secret constants are inline.

- `systems` - System architectures (readonly, from root constants.nix)
- `profiles` - Profile names: desktop, server (readonly)
- `distros` - Supported distros: almalinux, debian, fedora, ubuntu (readonly)
- `identity.fullName` - Full name (from privateConfig)
- `identity.username` - Default personal machine username (from privateConfig)
- `identity.gpg.keyId` - GPG key ID (from privateConfig)
- `identity.gpg.fingerprint` - GPG fingerprint (from privateConfig)
- `identity.telegram.userId` - Telegram user ID (from privateConfig)
- `personal.email` - Personal email (from privateConfig)
- `personal.domain` - Personal domain (from privateConfig)
- `work.email` - Work email (from privateConfig)
- `work.employer` - Employer name (from privateConfig)
- `work.jobTitle` - Job title (from privateConfig)
- `work.gheHostname` - GitHub Enterprise hostname (from privateConfig)
- `work.username` - Work machine username override (from privateConfig)
- `hosts` - Host aliases defined in `core/constants.nix`; the server address comes from `privateConfig.hosts.server`
- `historySize` - 50000 (configurable)
- `timezone` - "Europe/Paris" (configurable)
- `fontFamily` - "JetBrainsMono Nerd Font" (readonly)
- `deltaConfig` - Shared delta pager configuration submodule (readonly)

### email.nix

Canonical multi-account email configuration:

- Private account metadata comes from `privateConfig.email.accounts`
- Runtime credentials use `email/accounts/<account>/password` in `credentials.enc.yaml`
- Projects selected account definitions into Home Manager's canonical `accounts.email.accounts`
- `modules.core.email.defaultAccount` selects the primary account
- `modules.core.email.selectedAccounts` selects account definitions materialized per profile
- `modules.core.email.activeAccounts` keeps only canonical accounts whose Home Manager `enable` flag is true
- Credentials and Himalaya tables are generated only for active accounts
- Validates account names, selection, transports, nullable optional aliases, and TLS-required password-backed SASL LOGIN
- Consumer modules must read `accounts.email.accounts`; client-specific settings stay in the client module

### sops.nix

SOPS secrets management via `sops-nix` home-manager module:

- **Decryption**: configured SOPS age identity (0600, outside repo)
- **Default sops file**: `secrets/credentials.enc.yaml`
- **Activation ordering (Linux)**: reload user units before materializing secrets; consumers require `sops-nix.service`
- **Activation ordering (macOS)**: decrypt synchronously before `setupLaunchAgents`; `RunAtLoad` refreshes secrets at login
- **App credentials**: hermes-env, shell-secrets (from credentials.enc.yaml)
- **Email credentials**: declared per active account by `core/email.nix`
- **SSH key**: `secrets/ssh/id_rsa` (format=binary, deployed to `~/.ssh/id_rsa`)
- **SSH pubkey**: `secrets/ssh/id_rsa.pub` (via home.file, plaintext)
- **Interactive edits**: `scripts/secrets.py` stages ciphertext beside its destination, preserves the final YAML suffix for editor detection and passes the original filename to SOPS for creation rules.
- **Publication**: interactive edits publish by rename after successful encryption; `scripts/encrypt-gpg-bundle.sh` also verifies its staged export before replacing the previous bundle.
- **Editor cleanup**: plaintext stays in a private manager-owned workspace until supervised descendants stop. Handled HUP, QUIT, INT and TERM trigger cleanup; SIGKILL or machine failure can leave plaintext.

### distro.nix

Auto-detects Linux distribution via `/etc/os-release`:

- `config.modules.core.distro.id` - Detected distro ID or "darwin" or null
- `config.modules.core.distro.ids` - Attribute set of supported distros
- Emits warning for unsupported distributions

### gpu.nix

- `vendor` selects automatic host detection or an explicit vendor; `acceleration` is read-only (`cuda`, `rocm`, `vulkan`, or native package defaults).
- `scripts/gpu-env.sh` snapshots the NVIDIA driver and AMD KFD targets using native file reads, and validates the NVIDIA compute-capability query. Mutable sysfs values are not fetched through Nix's URL cache.
- CUDA requires a complete successful probe and selects the newest driver-compatible scope whose final targets cover all detected and explicitly configured targets and satisfy combined platform constraints. Stock scopes are preserved when suitable; legacy targets customize a coherent scope. Unusable scopes are skipped before falling back.
- ROCm requires a host platform supported by the pinned HIP compiler, KFD and a detected target in the pinned CLR target list. Unsupported compiler platforms retain Vulkan or native package defaults; the CLR list is not a hardware certification matrix.
- `cudaCapabilities` and `rocmTargets` expose the validated snapshot/selected targets; `cudaPackages` provides the selected scope to consumers. `nvidiaDriverVersion` is the explicit fallback when the native version probe is unavailable.
- Generic Linux uses Home Manager's `/run/opengl-driver` integration with an exact NVIDIA version; NixOS is excluded from that provisioning. Darwin consumers retain native Metal/CoreML defaults.
- The `gpu` check covers snapshot freshness/disappearance, probe failures, toolkit boundaries, legacy targets, captured overlay scopes including invalid metadata, Orin/Thor SBSA transitions and legacy Jetson fallback, ROCm host-platform fallbacks, nested CUDA consumers and NixOS activation isolation.

### lib.nix

Shared library functions:

- `config.modules.core.lib.mkSystemPackage` - Placeholder package for system-managed binaries
- `config.modules.core.lib.mkPlatformPackage` - Nix package on Darwin, system stub on Linux
- `config.modules.core.lib.mkUnstableVersion` - Version string from a flake input (0-unstable-YYYY-MM-DD+shortRev)
- `config.modules.core.lib.mkUnstableVersionWithBase` - mkUnstableVersion with an explicit base version
- `config.modules.core.lib.deltaConfigToCli` - Converts `modules.core.constants.deltaConfig` to delta CLI flags string (readonly)
- `config.modules.core.lib.mkOptionalPackageOption` - Creates a `nullOr package` option (default/defaultText/description/example) (readonly)
- `config.modules.core.lib.mkOptionalPackages` - Entry list `{ package, enabled ? true, warning ? null }` to `{ packages, warnings }` (readonly)

### home-manager.nix

Base home-manager configuration:

- Enables `programs.home-manager`
- Configures Nix settings (flakes, nix-command, warn-dirty=false)
- Sets up weekly garbage collection (30 days retention)

### packages.nix

Common packages for all platforms:

- **All**: litellm, mergiraf, nerd-fonts.jetbrains-mono, nh, nixfmt, volta
- **GGML inference tools**: llama.cpp, stable-diffusion.cpp (`sd-cli`, `sd-server`) and whisper.cpp on desktop and server profiles. Linux uses the shared CUDA/ROCm/Vulkan selection; Apple Silicon retains native Metal defaults. Only `/bin` and `/share` are exposed in the profile, keeping each package's private libraries isolated.
- **Linux server**: delta, grc (only on server profile)
- **Desktop exclusions**: Antigravity is disabled on `rigel`; Crush is disabled on `faust` and `rigel`.
- **macOS**: Extensive list (bat, bruno, delta, firefox, go, google-chrome, grc, jetbrains IDEs, python3, rustup, vscode, zed-editor, etc.)
- **OpenClaw tools** (via `nix-openclaw-tools` flake input): camsnap, discrawl, gogcli, goplaces, sag, sonoscli, summarize and wacrawl (all platforms); imsg, peekaboo and poltergeist (macOS desktop only). These standalone tools do not install the OpenClaw application or gateway.
- **Homebrew**: .Brewfile with taps (hAIperspace/hai, moltenbits) and packages (docker-desktop, ferdium, ghostty, gpg-suite@nightly, jordanbaird-ice, shuttle, growlrrr, hai, mole)

### profile.nix

Profile system defining which modules are enabled per profile:

| Category    | Module     | Desktop | Server |
| ----------- | ---------- | ------- | ------ |
| shell       | direnv     | ✓       | ✗      |
| shell       | eza        | ✓       | ✗      |
| shell       | fd         | ✓       | ✓      |
| shell       | fzf        | ✓       | ✓      |
| shell       | ripgrep    | ✓       | ✓      |
| shell       | zoxide     | ✓       | ✗      |
| shell       | zsh        | ✓       | ✓      |
| development | bun        | ✓       | ✗      |
| development | gh         | ✓       | ✗      |
| development | git        | ✓       | ✓      |
| development | lazygit    | ✓       | ✓      |
| development | opencode   | ✓       | ✗      |
| development | herdr      | ✓       | ✗      |
| development | claudeCode | ✓       | ✗      |
| programs    | alacritty  | ✓       | ✗      |
| programs    | btop       | ✓       | ✓      |
| programs    | ghostty    | ✓       | ✗      |
| programs    | glow       | ✓       | ✓      |
| programs    | lazydocker | ✓       | ✓      |
| programs    | ssh        | ✓       | ✓      |
| programs    | tmux       | ✓       | ✓      |
| editors     | neovim     | ✓       | ✗      |
| editors     | vim        | ✓       | ✓      |

### specialisations.nix

Creates work/personal contexts with distinct Git identities, signatures, shell aliases (`hm`/`hmw`/`hmp`), email account selection, SSH settings and SOPS overrides. Both contexts currently select `tokyoNightStorm`.

Requires: `modules.development.git.enable = true`, `modules.shell.zsh.enable = true`

---

## Shell Modules (`modules/shell/`)

### zsh.nix

Shell configuration with oh-my-zsh:

- Theme: fino
- Session variables: NH_FLAKE, WORKSPACE, EDITOR
- Base plugins: colorize, screen, docker, python, poetry, rust, deno, volta, node, npm, etc.
- Dynamic plugins based on: profile modules, distro, platform
- Custom init: `oc()` preserves literal OpenCode arguments across its project-scoped tmux launch, EDITOR setup (code --wait), DVM support, .secrets loading with permission check
- envExtra: cargo env, gh auth token for NIX_CONFIG access-tokens and HOMEBREW_GITHUB_API_TOKEN
- Profile: Volta setup, PATH configuration, .zprofile.d scripts sourcing

### fzf.nix

Fuzzy finder configuration:

- Uses `mkPlatformPackage` (Nix on Darwin, system stub on Linux)
- Commands use fd for file discovery
- **Requires**: fd module enabled

### direnv.nix

Directory environment management:

- nix-direnv enabled
- Zsh integration disabled (using oh-my-zsh plugin)

### eza.nix

Modern ls replacement:

- Git integration enabled
- Icons: auto
- Options: group-directories-first, header

### fd.nix, ripgrep.nix, zoxide.nix

Simple wrappers using `mkPlatformPackage` (Nix on Darwin, system stub on Linux).

---

## Development Modules (`modules/development/`)

### git.nix

Comprehensive Git configuration:

- **Core**: delta pager, commitGraph, untrackedCache, fsmonitor
- **User**: name, email, signingKey from constants (defaults, overridable)
- **Commit**: GPG signing, sign-off, verbose
- **Push**: current, autoSetupRemote, followTags, useForceIfIncludes
- **Merge**: mergiraf driver, diff3 conflict style
- **Delta**: line-numbers, hyperlinks, VS Dark+ theme
- **macOS**: opendiff mergetool, osxkeychain credential helper

### gh.nix

GitHub CLI:

- Extensions: gh-dash

### lazygit.nix

Git TUI with dynamic theme colors from `themes.current`:

- Custom conventional commit command (key: C); subject, body and breaking-change trailer are shell-quoted separately.
- Delta pager integration
- Auto-fetch, auto-refresh enabled
- **Requires**: git module enabled

### hermes-agent.nix

Hermes Agent configuration:

- `plugins`: source directories linked under their canonical names by Home Manager.
- Non-empty `plugins` requires normalized absolute `home.homeDirectory` and
  `services.hermes-agent.hermesHome` paths; `hermesHome` must equal or descend from HOME.
- Set `plugins = lib.mkForce { };` when using a Hermes home outside HOME.
- State setup shell-quotes the Hermes home and working directory, including paths with spaces.
- Linux creates the stable `.env` link before service reload; `After`/`Requires=sops-nix` gates its secret target. Darwin also gates each gateway/backend launch on secret readability, failing after 60 seconds rather than starting without credentials.
- Linux/systemd and macOS/launchd gateways share a non-interactive account-login launcher using Nixpkgs `getent` and `getconf`.
- Login PATH precedes the Home Manager profile and original service PATH fallbacks. On macOS, secret readiness precedes login initialization. Backend launch policy is unchanged.
- When `programs.mise.enable` is true and `programs.mise.package` is non-null, the gateway runs that package's `mise activate bash --shims` after login. One private Bash resolver serves both the launcher and the packaged local terminal; mise resolves `shims_dir`, `MISE_DATA_DIR` and XDG settings without interactive activation hooks.
- Mise's shim paths precede the combined login/profile/service PATH while preserving those entries' relative order. A gateway-only boolean opts the packaged local terminal into restoring shim priority after its login profiles and configured init files, before its snapshot. Background commands opt in only through upstream `restore_login_path=true`; other background calls retain upstream behavior.
- Each shim selects the tool version from the command's current directory, including persistent terminal `cd` changes and same-name tools exposed by login. Default profiles, explicit `terminal.shell_init_files`, `auto_source_bashrc` and runtime edits remain upstream-owned. Neither runtime YAML nor `services.hermes-agent.configFile` receives injected settings or migrations.
- Disabling mise or setting its package to null removes activation and its gateway marker in the next generation. Restart the gateway to replace existing snapshots; existing sessions are not repaired in place. CLI processes outside the gateway, backends, containers and remote environments do not opt in. No tools are provisioned; normal mise trust, fallback and auto-install policies still apply.
- The local terminal fix patches the module-provided package's actual workspace wheel before building `hermesVenv`. Arbitrary `services.hermes-agent.package` replacements remain supported but do not automatically acquire that source patch. Remove it when Hermes offers an additive post-login PATH hook.
- Gateway mise mode requires successful login/profile initialization. If snapshot activation fails, terminal commands retry that same login path and report its failure instead of bypassing it with Hermes's non-login fallback. Unmarked processes retain the upstream fallback.
- Declare extra service tools with `services.hermes-agent.extraPackages`. Put user-specific PATH exports in non-interactive login files, not interactive-only shell setup.
- Unsupported shells fail explicitly; login startup must not require a TTY. No PATH entry is added to credentials or the global service-manager environment.
- Extra dependency groups use upstream package/module merging; runtime wrappers retain PortAudio and applicable CUDA libraries. Linux wrappers include `ld` and `objdump` for Python's PortAudio discovery without a compiler.
- Linux PM artifacts use the build-platform `patchelfUnstable`, whose pinned source includes the executable-header overlap fix. This replaces only their patchelf build input; other PM inputs and Darwin remain unchanged.
- Icon generation uses the unpatched minimal interpreter, so terminal PATH fixes do not invalidate web or Desktop renderer builds.

### prime-agent.nix

- Uses a private recursive Python 3.12 package set for the pinned runtime and its build dependencies. The rest of the configuration retains the unmodified nixpkgs Python package sets.
- Rust compilation is separate from Python, catalog and launcher assembly. Python or catalog updates retain the native build; final executable copies preserve daemon-generation identity.
- Backports [httpx2#1231](https://github.com/pydantic/httpx2/pull/1231) only to that package set's `httpcore2`. Its Trio virtual-clock fixture prevents the cancellation tests' real 10 ms deadline from expiring during HTTP/2 initialization on loaded builders. Assertions, asyncio/Trio coverage and the existing RISC-V exclusions remain unchanged. Remove the patch when the pinned nixpkgs includes that fix or a release containing it.
- The patched `httpcore2` 2.13.1 is required through Starlette's build checks; the runtime retains its separately pinned 2.12.0 wheel. This test fix does not close the separate initialization-cancellation cleanup gap.
- OpenAI and LiteLLM use the unmodified nixpkgs recipes. OpenAI's upstream 15-second mTLS test budget remains a cold-build limitation; using the stock recipe does not fix that upstream test.

### aoe.nix

Agent of Empires session manager:

- Options: `enable`, `enableWeb`, `package`, `theme`, `defaultTool`
- Package from `inputs.agent-of-empires.packages.${system}`; `enableWeb` selects `aoe-with-web` instead of `default`
- Default tool: `opencode`; default theme: `tokyo-night-storm`
- Shell completions: bash, fish, zsh
- Seed `config.toml` only when no file or symlink exists; dry runs leave files and directories unchanged.
- Prefer the declared future XDG session environment during activation. Without a declared export, follow the native environment and existing-directory precedence, including Darwin's legacy fallback.

- The selected packaged AoE registry detects and launches Nixpkgs' `cursor-agent`; no generic `agent` alias is installed.

### pi.nix

- Options: `enable`, `package`
- Uses `inputs.pi.packages.${system}.default` from upstream `main`, pinned by `flake.lock`.

### strata.nix

- Options: `enable`, `package`, `workspaceDirectory`, `dataDirectory`, `modelsDirectory`.
- The default package launches the pinned upstream `x86_64-linux` CUDA development environment; a custom `package` replaces it.
- `workspaceDirectory` defaults to `${config.xdg.dataHome}/strata` and holds the writable source checkout, virtual environment, engines, build caches and interpreter GC root.
- Directory values are absolute strings outside `/nix/store`, not Nix paths. Changing paths does not migrate existing files.
- `dataDirectory` supplies `--data-dir` for new models, packs and drafts; null preserves upstream folder selection.
- Non-null `modelsDirectory` supplies `--models-dir` and separates GGUF destinations: ready dense/PLE/embedding and QAD dense/PLE use this directory; NVFP4 packs, QAD checkpoints/drafts and image VAE files use the data directory. Null preserves upstream layout, even with an explicit CLI `--models-dir`.
- On `nemesis`, `home.nix` sets `dataDirectory` to `/data00/strata`.
- Both directory defaults apply only during initial or explicit setup (`--setup`, `--model`, `--family`, `--no-start`).
- Explicit CLI values take priority independently, including equals syntax and unambiguous upstream abbreviations (`--models` is accepted; `--model` selects a model; `--mod` is ambiguous).
- Launcher classification reads only literal option names, actions and arities from the pinned upstream parser. It uses argparse without importing setup or running acquisition; unknown or ambiguous argument forms reach upstream unchanged.
- Installed launches do not receive directory defaults, collect existing files or rewrite folder settings. Updates, checks, calibration and standalone commands retain upstream behavior.
- Upstream owns model selection, tuning, profiles and explicit data-move confirmation. Existing XDG config/state settings remain unchanged; no Terminal package or service is added.
- The launcher applies `strata-setup-directory-roles.patch` to the pinned checkout under the workspace lock. The diff stays visible; `.git/strata-source.patch` records the patch text for revision changes and offline rollback. Conflicting edits are refused.
- Complete NVFP4 installations are reused in place before selecting a QAD checkpoint, including under the current `dataDirectory`.
- Fully verified QAD checkpoints take priority over partial downloads; other candidates retain the existing byte-length heuristic. Checkpoints resume in their original directory. Verified files in the selected checkpoint root are reused; files from different roots are not combined.
- Incomplete QAD preparations write to the selected GGUF and data destinations; completion marks stay with their outputs.
- Split ready downloads use pinned remaining sizes and resume parts grouped by destination filesystem. QAD preparation retains its aggregate estimate once on a shared filesystem; separate filesystems retain the data-side expert-arena lower bound while setup warns that the remaining output split is unknown.

- The runtime revision records validated local prerequisites; incomplete updates invalidate it and retry on the next launch.
- Validation uses upstream component inventory and engine metadata; component manifests do not require `BUILD.json`.
- Source refs, the workspace lock and Nix interpreter roots support offline rollback and serialized updates.
- Component references use upstream compatibility and explicit pins; raw executable paths use the legacy engine-version floor.
- Successful engine rollbacks remain approved while the source revision, payload and local source fingerprints are unchanged.
- Python/config repair and calibration preserve approved engines; explicit update/setup or source/payload changes invalidate the corresponding approval.
- Rollback approval does not bypass runtime prerequisites or unknown-version rejection.
- Runtime validation does not establish GPU compatibility, model integrity or successful inference.

### opencode.nix

OpenCode AI assistant:

- Options: `enable`, `enableDesktop`, `opencodePackage`, `desktopPackage`
- Packages from flake input: TUI/CLI and Desktop variants (`opencode2` is a symlink to the same v2 binary)
- CLI, Desktop and Neovim use the shared background service by default
- Custom CLI packages must be upstream-compatible source-built derivations; service and Linux runtime adjustments also apply to overrides
- Existing build environment and post-fixup hooks are preserved
- The Linux C++ runtime wrapper is assembled separately from CLI compilation; channel selection remains compile-time. Darwin retains the compiled package directly.
- Generated Desktop bundles the selected CLI
- Staged CLI paths include the version, architecture and Nix output identity
- Cleanup retains all stages of the bundled and adopted versions for the current architecture
- Build-time CLI staging uses upstream's `packages/cli/dist` layout
- `checks.opencode-desktop` builds Desktop and verifies the bundled CLI, version manifest and copied executable
- Generated Desktop requires a non-null CLI package selection
- Generated Desktop is a fallback: a normal `desktopPackage` override replaces it; `null` omits Desktop even when enabled
- Desktop uses upstream's pinned Electron package
- Workaround: upstream dependency hashes are incompatible with the selected Bun. `pins/opencode.json` records hashes, source/toolchain revisions and verification provenance.
- Hash updates require matching dependency inputs and Bun. Verify the bot's source and toolchain in its job logs; an unchanged `bun.lock` alone is insufficient.
- Recalculate with the locked source and local Bun when inputs differ; update provenance and verify dependency and CLI builds.
- ARM-targeted calculations must reproduce native bot hashes with the reference Bun before reuse. They do not replace native build verification.
- CLI and generated Desktop share the corrected dependency derivation; custom package selections remain unchanged.
- Remove this override when upstream ships hashes compatible with the selected source and Bun. The local hash fixer does not maintain these hashes.
- Warnings if packages unavailable for system

### ollama.nix

- Options: `enable`, `enableService`. Linux profiles install the CLI; only the desktop profile on `morphee` enables the user service. Other Linux hosts and server profiles remain CLI-only. Disabling the module removes its CLI and service contributions.
- Owns GPU-selected package configuration and installation. Linux uses the shared CUDA/ROCm/Vulkan policy; `services.ollama.package` remains overrideable. CLI-only mode installs the same package without creating a unit.
- Reuses Home Manager's `services.ollama` for the Linux daemon. Defaults to 131072 context tokens, Flash Attention and `q8_0` KV cache; override through `services.ollama.environmentVariables`. Server context is not a minimum or an OMP client budget.
- Uses `Type=exec`, restarts on failure and logs to the user journal. Model storage and idle-unload behavior remain unchanged.
- Darwin desktop profiles contribute the Ollama formula to the shared Brewfile, retaining Homebrew service ownership. `core/packages.nix` provides the generic Brewfile activation.
- See `suggested_commands` for first-activation handover and user-service lifetime.

### omp.nix

- Linux preloads the C++ runtime through `DT_NEEDED`; `OMP_NATIVE_LIBRARY_PATH` supplies worker search paths without changing user subprocess `LD_LIBRARY_PATH`.
- Build-platform Python repairs Bun's `DT_VERDEF` after autoPatchelf and before native completion generation. ELF repair and pyelftools are build-time only.
- Native install checks verify version and completions; Linux checks also verify runtime resolution by soname and absolute path.

### caveman.nix

- All six native companions, including Cavemem, use the `BINARY_RELEASE` asset pins. Blocks retains its separate source and vendor hash.
- CLI compilation is separate from installer, companion and profile registration assembly. Artifact/hash or profile changes retain the compiled CLI at unchanged release versions.
- Blocks assembles its wrapper separately from Go compilation. Git and Python remain native check inputs, so their updates can still invalidate the native build.
- The CLI preserves Cavemem's `supersede-stdin` capability guard. Runtime checks verify byte-exact replacement above the argv limit, history preservation and refusal above 256 KiB without changing current memory.
- Managed `caveman-install --hook-node` must name the selected profile's private `lib/caveman/node`; bare or foreign interpreters are refused before writes. Unmanaged prepared plugins honor the upstream interpreter override.
- Caveman CLI, installer, copied OpenCode plugin and Blocks use nonempty `OPENCODE_CONFIG_DIR`, then nonempty `XDG_CONFIG_HOME/opencode`, then `HOME/.config/opencode`. An empty override is unset; a nonempty relative `OPENCODE_CONFIG_DIR` is refused. The installer and copied plugin retain upstream `XDG_CONFIG_HOME` handling, including relative values. Changing roots does not move or delete old files.
- Generated OpenCode plugins support both API majors. Each factory owns its project/session state; native and shrink children use the served project cwd, including locationless session-deletion cleanup routed by the host.
- Hermes deny lists take precedence over enable lists. Caveman refuses inactive native/shrink installs before rewriting configuration or plugin payloads; use `hermes plugins enable caveman_native` or `hermes plugins enable caveman_shrink` to change that preference.
- Hermes membership checks accept scalar-string block and flow sequences, including flow nodes on the next line, quoted names, token-adjacent comments and supported multiline scalars. A `#` inside a plain name remains data. Unrelated disabled names and duplicate deny entries are preserved; malformed or unsupported YAML fails closed before rewriting configuration or plugin payloads.
- Already-enabled shrink flow lists remain byte-identical on reinstall. Writers still refuse nonempty flow lists that need an added membership; native-owned flow rewrites remain unsupported. A refused shrink install may invalidate its stale installation marker, but does not rewrite config or plugin files.

### colibri.nix

- Colibri includes Pillow for shipped image preprocessing. CUDA toolkits below 12.8 build DeepSeek without tensor cores; driver/toolkit selection remains unchanged.
- Native compilation excludes the Python environment and dashboard. PythonMinimal remains a native check input. Assembly preserves Python resource paths.
- CUDA compilation passes the selected scope's `flags.gencodeString` through upstream's `CUDA_GENCODE` and DeepSeek V4's separate `V4_CUDA_GENCODE`, retaining configured SASS/PTX targets without probing a build-time GPU. Do not use `all-major`: CUDA 12.x includes SM 5.0, which cannot compile upstream's unguarded `__hfma2` calls.
- Linux CUDA builds remove upstream's forced `__THROW` shim: the selected Nixpkgs/NVIDIA math headers already match glibc exception specifications. CPU and Metal sources remain unpatched.
- `checks.gpu` dry-runs Colibri's Linux CUDA/CPU and Darwin Metal install plans against the upstream Makefiles. It checks selected CUDA targets, the pre-12.8 tensor-core fallback and portable CPU flags; Metal selection must not evaluate CUDA policy. No GPU or toolkit is needed; native build/runtime coverage is separate.

### bun.nix

Simple Bun JavaScript runtime enablement.

### claude-code.nix

Claude Code AI assistant:

- Simple wrapper installing `pkgs.claude-code`

### herdr.nix

Herdr terminal UI, persistent terminal engine and native Desktop:

- Options: `enable`, `enableDesktop`, `package` (nullOr), `corePackage` (nullOr), `desktopPackage` (nullOr), `theme` (nullOr)
- Packages come from the locked nixpkgs: `herdr` (`herdr`), `herdr-core` (`hc`, `herdr-core`) and `herdr-desktop` (`herdr-app`); no separate Herdr flake input or local builder
- Enabling the module installs the TUI and core. Desktop is opt-in at module level; desktop profiles enable it, server profiles disable the module
- Defaults omit unavailable or unsupported packages with warnings. Core/Desktop currently support Linux x86-64/ARM64 and macOS ARM64; explicit package overrides remain the caller's responsibility
- Generated Desktop uses `corePackage` as its packaged fallback dependency. An explicit `desktopPackage` override replaces it; `null` omits Desktop. Enabled, non-null Desktop requires non-null `corePackage`
- Existing app `core` settings, earlier PATH/install candidates and running session daemons retain upstream precedence. Custom Desktop packages must supply a compatible engine; app/core versions need not be equal
- Theme: `null` follows the shared theme system (`modules.themes.current`), mapped
  onto herdr built-ins (tokyonight→tokyo-night/-day, catppuccin→catppuccin/-latte);
  override with any built-in name (tokyo-night, catppuccin, dracula, nord, gruvbox, ...)
- Config: `~/.config/herdr/config.toml` on Linux and macOS (seeds `onboarding=false` + `[theme]` on first activation; editable in-app via prefix+s / `herdr server reload-config`)
- Activation preserves existing regular files, including empty files; dry runs never create config files or directories
- Desktop settings/mods live under `$XDG_CONFIG_HOME/herdr-app` (`HERDR_APP_HOME` overrides it); core config/state live under `$XDG_CONFIG_HOME/herdr-core` and `$XDG_STATE_HOME/herdr-core`. These remain application-owned and separate from the TUI theme/config
- Nixpkgs supplies backend discovery, Linux desktop entries/icons and graphics RUNPATH, plus the macOS app bundle. No global loader environment or extra Home Manager service is added; the core starts on demand
- Generated macOS Desktop disables automatic CLI-link installation, including bundles copied by Home Manager. It does not create or rewrite `~/.local/bin/herdr-app`; explicit `desktopPackage` overrides retain their own behavior. Existing launchers remain untouched; an older self-link can still shadow the profile and needs manual removal after checking its target
- Update the local packages through nixpkgs. Normal source-built Desktop does not auto-update; its explicit upstream setup actions remain available. Remote machine setup retains upstream release installation behavior

### openspec.nix

OpenSpec CLI:

- Options: `enable`, `package`
- Package from flake input
- Warnings if package unavailable for system

---

## Programs Modules (`modules/programs/`)

### alacritty.nix

Terminal emulator:

- Theme: dynamic from `themes.current.fileName` (via alacritty-theme package)
- Font: constants.fontFamily, 14pt
- Window: maximized, 0.95 opacity, blur
- Scrollback: uses constants.historySize
- URL hints: Cmd/Ctrl+click to open (cross-platform)
- Bell: grrr on macOS (auto-detected path), notify-send on Linux
- Keybindings: cross-platform (Command on macOS, Control on Linux)

### ghostty.nix

Terminal emulator:

- Font: constants.fontFamily, 12pt
- Theme: dynamic from `themes.current.altName` (macOS only)
- Quick terminal: Ctrl+grave toggle, centered, no animation
- macOS: option-as-alt enabled

### tmux.nix

Terminal multiplexer:

- vi mode, mouse enabled
- Theme: dynamic plugin selection via `theme.family` (supports tokyonight and catppuccin)
- Plugins: sensible, yank, pain-control, vim-tmux-navigator, resurrect, continuum
- Catppuccin: battery plugin loads before final status composition; Continuum loads last so its periodic-save hook remains installed.
- Session persistence: 15-minute autosave, restore on start
- Assertion validates theme family exists in `tmuxThemePlugins`

### zellij.nix

Terminal multiplexer:

- Theme: dynamic from `themes.current.name`
- zjstatus plugin for status bar with dynamic theme colors
- Session serialization enabled (60s interval)
- Custom keybindings: Alt+hjkl navigation, Alt+[] tabs, Alt+n/t new pane/tab, Alt+f/z float/fullscreen
- `Ctrl-o` enters Session mode; `w` and `p` launch session/plugin managers there, never intercepting ordinary Normal-mode typing.

### lazydocker.nix

Docker TUI:

- Theme: dynamic colors from `themes.current`
- Rounded borders
- Custom commands: bash, sh shell access

### ssh.nix

SSH configuration:

- Forward agent and X11 enabled
- macOS: UseKeychain
- SSH settings are defined in `core/specialisations.nix`; work sets `programs.ssh.settings."*.local".User` to `constants.identity.username`.

### ortie.nix

- Installs the nixpkgs package; a shared overlay supplies `aws-lc` and `libgit2` required by Cargo's system-library hook until the pin includes [the upstream fix](https://github.com/NixOS/nixpkgs/pull/586834).
- The email check uses the same corrected Ortie package; its other package dependencies remain stock.

### himalaya.nix

Himalaya v2 CLI email client:

- Enables selected canonical `accounts.email.accounts` in Home Manager
- Uses upstream `programs.himalaya` to render native v2 configuration and install the CLI
- Global client settings live in `programs.himalaya.settings`
- Password commands reference account-owned SOPS credentials; plaintext never enters the Nix store
- Preserves credential argv and per-account command overrides
- SMTP-only accounts acquire no implicit Maildir; explicit Maildir settings remain supported

### btop.nix

Simple wrapper using `mkPlatformPackage`.

### glow.nix

Markdown viewer:

- Package via `mkPlatformPackage`
- YAML config generated (style: auto, mouse: true, pager: true, width: 100)
- Platform-aware config path: `~/Library/Preferences/glow/` on macOS, XDG on Linux

---

## Editors Modules (`modules/editors/`)

### vim.nix

Vim configuration:

- Linux: Generates .vimrc for system vim with plugin runtimepath
- macOS: Uses home-manager vim module
- Plugins: airline, airline-themes, vim-nix, commentary, surround, gitgutter
- Settings: numbers, cursor line, 2-space indent, search highlighting

### neovim.nix

Full IDE configuration (~500 lines):

**Plugins**:

- UI: snacks-nvim, lualine-nvim, nvim-web-devicons
- Theme: dynamic plugin selection via `theme.family` (tokyonight-nvim or catppuccin-nvim)
- Files: neo-tree-nvim, oil-nvim
- Editor: nvim-surround, nvim-autopairs, comment-nvim, which-key-nvim, gitsigns-nvim
- Treesitter: all grammars; FileType enables highlighting and indentation. `gnn` selects a named node, `grn` grows an ancestor, `grc` grows a local scope, and `grm` restores the previous selection.
- Whole-line incremental selections at EOF use linewise Visual mode to retain the final newline. Partial-line EOF selections remain charwise; Neovim cannot include that final newline without adding unwanted prefix bytes.
- Fuzzy: telescope-nvim with fzf-native
- Formatting: conform-nvim
- Completion: blink-cmp, lazydev-nvim
- AI (optional): opencode-nvim

**LSP Servers**: bashls, pyright, ts_ls, gopls, rust_analyzer, nixd, lua_ls; named definitions come from nvim-lspconfig before native `vim.lsp.enable`.

**Formatters**: stylua, prettier, nixfmt, ruff

**OpenCode Integration** (when enabled):

- Keymaps: `<leader>o*` prefix
- Terminal toggle, context prompts and command mappings
- Session, navigation and prompt actions dispatch to the visible TUI through an opt-in local plugin and private OSC input, without changing user keybinds.
- The bridge package exposes a stable profile path; terminal preflight registers it in OpenCode's effective config root without replacing user files or overriding `OPENCODE_CONFIG_DIR`.
- Session sharing is unavailable in OpenCode V2.
- Notifications and statusline consume native `session.execution.started/succeeded/interrupted/failed` events; completed/interrupted runs restore idle status, and failures retain error notifications.
- Event-driven file reloads and permission handling
- HTTP requests and SSE events use `curl`

**Requires**: opencode module enabled if opencode plugin enabled

---

## Themes Module (`modules/themes/default.nix`)

### Architecture

All themes defined in a single file via `mkTheme` factory function. The theme system uses:

- **Registry**: `config.modules.themes.registry` — attrsOf typed submodule
- **Active key**: `config.modules.themes.active` — string key (default: "tokyoNightStorm")
- **Current**: `config.modules.themes.current` — resolved theme from registry (readOnly)

### Available Themes (7)

| Key                   | Family     | Style     | bg      |
| --------------------- | ---------- | --------- | ------- |
| `tokyoNight`          | tokyonight | night     | #1a1b26 |
| `tokyoNightStorm`     | tokyonight | storm     | #24283b |
| `tokyoNightLight`     | tokyonight | day       | #e6e7ed |
| `catppuccinMocha`     | catppuccin | mocha     | #1e1e2e |
| `catppuccinMacchiato` | catppuccin | macchiato | #24273a |
| `catppuccinFrappe`    | catppuccin | frappe    | #303446 |
| `catppuccinLatte`     | catppuccin | latte     | #eff1f5 |

### Theme Submodule Type

Each theme provides `family`, `name`, `altName`, `fileName`, `neovimName`, `style`, and `colors`. `colors` is a typed submodule: `bg`, `fg`, and eight base ANSI colors are required; eight `bright*` colors default to their corresponding base colors. All colors must match `#RRGGBB`. A new family also needs support in the consuming applications; see `task_completion_checklist`, **Adding New Themes**.

### Access Pattern

```nix
theme = config.modules.themes.current;
theme.name       # "tokyo-night-storm"
theme.colors.bg  # "#24283b"
theme.colors.blue # "#7aa2f7"
```

Used by: alacritty, ghostty, lazygit, lazydocker, tmux, zellij, neovim
