# Modules Reference

## Core Modules (`modules/core/`)

### constants.nix

Defines user-level constants accessible via `config.modules.core.constants`:

- `systems` - System architectures (readonly, from root constants.nix)
- `profiles` - Profile names: desktop, server (readonly)
- `distros` - Supported distros: almalinux, debian, fedora, ubuntu (readonly)
- `username` - "Jérôme Benoit" (readonly)
- `primaryEmail` - Personal email (readonly)
- `secondaryEmail` - Secondary email (readonly)
- `workEmail` - Work email (readonly)
- `gpg.keyId` - GPG key ID (readonly)
- `gpg.fingerprint` - GPG fingerprint (readonly)
- `historySize` - 50000 (configurable)
- `timezone` - "Europe/Paris" (configurable)
- `hosts` - Known hostnames: rigel, ns3108029 (readonly)
- `telegramUserId` - Telegram user ID for bot integrations (readonly)
- `fontFamily` - "JetBrainsMono Nerd Font" (readonly)
- `deltaConfig` - Shared delta pager configuration submodule (readonly)
- `deltaConfigToCli` - Function to convert deltaConfig to CLI flags string (readonly)

### distro.nix

Auto-detects Linux distribution via `/etc/os-release`:

- `config.modules.core.distro.id` - Detected distro ID or "darwin" or null
- `config.modules.core.distro.ids` - Attribute set of supported distros
- Emits warning for unsupported distributions

### lib.nix

Shared library functions:

- `config.modules.core.lib.mkSystemPackage` - Placeholder package for system-managed binaries
- `config.modules.core.lib.mkPlatformPackage` - Nix package on Darwin, system stub on Linux

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
- **steipete tools** (via `nix-steipete-tools` flake input): peekaboo, poltergeist, imsg, camsnap, sag (macOS) + summarize, gogcli, goplaces, sonoscli (all platforms)
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
| development | agentDeck  | ✓       | ✗      |
| development | aoe        | ✓       | ✗      |
| development | claudeCode | ✓       | ✗      |
| development | openclaw   | ✗       | ✗      |
| development | openspec   | ✓       | ✗      |
| programs    | alacritty  | ✓       | ✗      |
| programs    | btop       | ✓       | ✓      |
| programs    | ghostty    | ✓       | ✗      |
| programs    | glow       | ✓       | ✓      |
| programs    | himalaya   | ✓       | ✗      |
| programs    | lazydocker | ✓       | ✓      |
| programs    | ssh        | ✓       | ✓      |
| programs    | tmux       | ✓       | ✓      |
| programs    | zellij     | ✓       | ✗      |
| editors     | neovim     | ✓       | ✗      |
| editors     | vim        | ✓       | ✓      |

### specialisations.nix

Creates work/personal contexts with different:

- Git user email and signing key
- Email signature file (.signature)
- Shell aliases (hm, hmw, hmp)
- Active theme (via `modules.themes.active`)
- SSH matchBlocks (work specialisation has \*.local -> fraggle user)

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

### agent-deck.nix

AI agent command center TUI:

- Options: `enable`, `package`, `defaultTool`, `theme`
- Default tool: opencode (supports claude, gemini, opencode, codex)
- Theme: system (supports dark, light, system)
- Config: `~/.agent-deck/config.toml` (created on first activation)
- Built from flake input with `buildGoModule`

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
- Bundled plugins: summarize, sag, camsnap, gogcli, goplaces, sonoscli + macOS-only: peekaboo, poltergeist, imsg (bird disabled — upstream repo deleted, nix-steipete-tools#6)
- Service: launchd on macOS, systemd on Linux
- Config: gateway (local/loopback), Telegram channel, agent defaults (model fallbacks, auth profiles, secrets defaults), exec security allowlist
- Activation: injects `$include` for local overrides, seeds `openclaw.local.json`

### openspec.nix

OpenSpec CLI:

- Options: `enable`, `openspecPackage`
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

CLI email client:

- Platform-aware password command (macOS keychain / Linux pass)
- Common settings: signature, datetime-local-tz, auto format
- Account: piment-noir (OVH IMAP/SMTP)
- GPG signing enabled by default

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
