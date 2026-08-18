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
- `hosts` - Known hostnames (from privateConfig)
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

- **Decryption**: age key file (`~/.config/sops/age/keys.txt`, 0600, outside repo)
- **Default sops file**: `secrets/credentials.enc.yaml`
- **Activation ordering fix (Linux)**: Mic92/sops-nix#581 (entryBetween reloadSystemd → sops-nix)
- **Activation ordering fix (macOS)**: Mic92/sops-nix#910 (entryAfter setupLaunchAgents, guarded plist existence)
- **App credentials**: hermes-env, shell-secrets (from credentials.enc.yaml)
- **Email credentials**: declared per active account by `core/email.nix`
- **SSH key**: `secrets/ssh/id_rsa` (format=binary, deployed to `~/.ssh/id_rsa`)
- **SSH pubkey**: `secrets/ssh/id_rsa.pub` (via home.file, plaintext)

### distro.nix

Auto-detects Linux distribution via `/etc/os-release`:

- `config.modules.core.distro.id` - Detected distro ID or "darwin" or null
- `config.modules.core.distro.ids` - Attribute set of supported distros
- Emits warning for unsupported distributions

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

- **All**: litellm, mergiraf, nerd-fonts.jetbrains-mono, nh, nixfmt, ollama, volta, whisper-cpp
- **Linux server**: delta, grc (only on server profile)
- **macOS**: Extensive list (bat, bruno, delta, firefox, go, google-chrome, grc, jetbrains IDEs, python3, rustup, vscode, zed-editor, etc.)
- **openclaw tools** (via `nix-openclaw-tools` flake input): peekaboo, poltergeist, imsg, camsnap, sag (macOS) + summarize, gogcli, goplaces, sonoscli, discrawl, wacrawl (all platforms)
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

Creates work/personal contexts with different git email, signature, shell aliases (hm/hmw/hmp), active theme, SSH matchBlocks, and sops overrides.

Requires: `modules.development.git.enable = true`, `modules.shell.zsh.enable = true`

---

## Shell Modules (`modules/shell/`)

### zsh.nix

Shell configuration with oh-my-zsh:

- Theme: fino
- Session variables: NH_FLAKE, WORKSPACE, EDITOR
- Base plugins: colorize, screen, docker, python, poetry, rust, deno, volta, node, npm, etc.
- Dynamic plugins based on: profile modules, distro, platform
- Custom init: `oc()` tmux+opencode wrapper, EDITOR setup (code --wait), DVM support, .secrets loading with permission check
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

- Custom conventional commit command (key: C)
- Delta pager integration
- Auto-fetch, auto-refresh enabled
- **Requires**: git module enabled

### opencode.nix

OpenCode AI assistant:

- Options: `enable`, `enableDesktop`
- Packages from flake input: TUI/CLI and Desktop variants
- Warnings if packages unavailable for system

### bun.nix

Simple Bun JavaScript runtime enablement.

### claude-code.nix

Claude Code AI assistant:

- Simple wrapper installing `pkgs.claude-code`

### herdr.nix

Terminal multiplexer for AI coding agents (tmux-style, pure-Rust binary):

- Options: `enable`, `package` (nullOr), `theme` (nullOr)
- Theme: `null` follows the shared theme system (`modules.themes.current`), mapped
  onto herdr built-ins (tokyonight→tokyo-night/-day, catppuccin→catppuccin/-latte);
  override with any built-in name (tokyo-night, catppuccin, dracula, nord, gruvbox, ...)
- Config: `~/.config/herdr/config.toml` on Linux and macOS (seeds `onboarding=false` + `[theme]` on first activation; editable in-app via prefix+s / `herdr server reload-config`)
- Package consumed from the `herdr` flake input (`inputs.herdr.packages.${system}.default`), no vendor/src hash to maintain
- No conductor/telegram/slack integration (unlike the former agent-deck)


### aoe.nix

Agent of Empires session manager:

- Options: `enable`, `package`, `theme`, `defaultTool`
- Default tool: opencode (supports claude, opencode, vibe, codex, gemini)
- Theme: tokyo-night-storm (supports phosphor, tokyo-night-storm, catppuccin-latte, dracula, empire)
- Config: XDG config or `~/.agent-of-empires/config.toml` on macOS
- Shell completions: bash, fish, zsh
- Built from flake input with `rustPlatform.buildRustPackage`

### openclaw.nix

OpenClaw AI gateway:

- Uses `programs.openclaw` HM module from `nix-openclaw` flake input
- Bundled plugins: summarize, sag, camsnap, gogcli, goplaces, sonoscli + macOS-only: peekaboo, poltergeist, imsg
- Service: launchd on macOS, systemd on Linux
- Config: gateway (local/loopback), Telegram channel, agent defaults (model fallbacks, auth profiles, secrets defaults), exec security allowlist
- Activation: injects `$include` for local overrides, seeds `openclaw.local.json`

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
- Catppuccin: includes battery plugin + custom status line
- Session persistence: 15-minute autosave, restore on start
- Assertion validates theme family exists in `tmuxThemePlugins`

### zellij.nix

Terminal multiplexer:

- Theme: dynamic from `themes.current.name`
- zjstatus plugin for status bar with dynamic theme colors
- Session serialization enabled (60s interval)
- Custom keybindings: Alt+hjkl navigation, Alt+[] tabs, Alt+n/t new pane/tab, Alt+f/z float/fullscreen

### lazydocker.nix

Docker TUI:

- Theme: dynamic colors from `themes.current`
- Rounded borders
- Custom commands: bash, sh shell access

### ssh.nix

SSH configuration:

- Forward agent and X11 enabled
- macOS: UseKeychain
- SSH matchBlocks defined in specialisations.nix (work: \*.local -> fraggle user)

### himalaya.nix

Himalaya v2 CLI email client:

- Consumes canonical accounts from `accounts.email.accounts`
- Generates native v2 `imap`, `smtp`, `mailbox.alias`, and SASL LOGIN tables
- Global client settings remain in `modules.programs.himalaya.settings`
- Temporary native renderer works around nix-community/home-manager#9794
- Password commands reference account-owned SOPS credentials; plaintext never enters the Nix store

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
- Treesitter: with all grammars
- Fuzzy: telescope-nvim with fzf-native
- Formatting: conform-nvim
- Completion: blink-cmp, lazydev-nvim
- AI (optional): opencode-nvim

**LSP Servers**: bashls, pyright, ts_ls, gopls, rust_analyzer, nixd, lua_ls

**Formatters**: stylua, prettier, nixfmt, ruff

**OpenCode Integration** (when enabled):

- Keymaps: `<leader>o*` prefix
- Session management, navigation, prompt commands
- Statusline integration
- Event handling (idle, error notifications)

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

Each theme provides: `family`, `name`, `altName`, `fileName`, `style`, `colors` (attrsOf str with 18 color keys)

### Access Pattern

```nix
theme = config.modules.themes.current;
theme.name       # "tokyo-night-storm"
theme.colors.bg  # "#24283b"
theme.colors.blue # "#7aa2f7"
```

Used by: alacritty, ghostty, lazygit, lazydocker, tmux, zellij, neovim
