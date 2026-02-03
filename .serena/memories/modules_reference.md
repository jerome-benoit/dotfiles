# Modules Reference

## Core Modules (`modules/core/`)

### constants.nix
Defines user-level constants accessible via `config.modules.core.constants`:
- `systems` - System architectures (readonly, from root constants.nix)
- `profiles` - Profile names: desktop, server (readonly)
- `distros` - Supported distros: almalinux, debian, fedora, ubuntu (readonly)
- `username` - "Jérôme Benoit" (readonly)
- `email` - Personal email (readonly)
- `workEmail` - Work email (readonly)
- `gpg.keyId` - GPG key ID (readonly)
- `gpg.fingerprint` - GPG fingerprint (readonly)
- `historySize` - 50000 (configurable)
- `timezone` - "Europe/Paris" (configurable)
- `hosts` - Known hostnames: rigel, ns3108029 (readonly)
- `fontFamily` - "JetBrainsMono Nerd Font" (readonly)

### distro.nix
Auto-detects Linux distribution via `/etc/os-release`:
- `config.modules.core.distro.id` - Detected distro ID or "darwin" or null
- `config.modules.core.distro.ids` - Attribute set of supported distros
- Emits warning for unsupported distributions

### home-manager.nix
Base home-manager configuration:
- Enables `programs.home-manager`
- Configures Nix settings (flakes, nix-command, warn-dirty=false)
- Sets up weekly garbage collection (30 days retention)

### packages.nix
Common packages for all platforms:
- **All**: nerd-fonts.jetbrains-mono, nh, mergiraf, nixfmt, volta
- **Linux server**: delta, grc (only on server profile)
- **macOS**: Extensive list including dev tools, IDEs, browsers, utilities
- **Homebrew**: .Brewfile for casks (docker-desktop, ferdium, ghostty, gpg-suite, ice, shuttle)

### profile.nix
Profile system defining which modules are enabled per profile:

| Category | Module | Desktop | Server |
|----------|--------|---------|--------|
| shell | direnv | ✓ | ✗ |
| shell | eza | ✓ | ✗ |
| shell | fd | ✓ | ✓ |
| shell | fzf | ✓ | ✓ |
| shell | ripgrep | ✓ | ✓ |
| shell | zoxide | ✓ | ✗ |
| shell | zsh | ✓ | ✓ |
| development | bun | ✓ | ✗ |
| development | gh | ✓ | ✗ |
| development | git | ✓ | ✓ |
| development | lazygit | ✓ | ✓ |
| development | opencode | ✓ | ✗ |
| programs | alacritty | ✓ | ✗ |
| programs | btop | ✓ | ✓ |
| programs | ghostty | ✓ | ✗ |
| programs | glow | ✓ | ✓ |
| programs | lazydocker | ✓ | ✓ |
| programs | ssh | ✓ | ✓ |
| programs | tmux | ✓ | ✓ |
| programs | zellij | ✓ | ✗ |
| editors | neovim | ✓ | ✗ |
| editors | vim | ✓ | ✓ |

### specialisations.nix
Creates work/personal contexts with different:
- Git user email and signing key
- Email signature file (.signature)
- Shell aliases (hm, hmw, hmp)
- SSH matchBlocks (work specialisation has *.local -> fraggle user)

Requires: `modules.development.git.enable = true`, `modules.shell.zsh.enable = true`

---

## Shell Modules (`modules/shell/`)

### zsh.nix
Shell configuration with oh-my-zsh:
- Theme: fino
- Session variables: NH_FLAKE, WORKSPACE, EDITOR
- Base plugins: colorize, screen, docker, python, poetry, rust, deno, volta, node, npm, etc.
- Dynamic plugins based on: profile modules, distro, platform
- Custom init: DVM support, .secrets loading with permission check
- Profile: Volta setup, PATH configuration, .zprofile.d scripts

### fzf.nix
Fuzzy finder configuration:
- Uses system fzf on Linux, Nix package on macOS
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
Simple wrappers using system binaries on Linux.

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
Git TUI with Tokyo Night theme colors:
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

---

## Programs Modules (`modules/programs/`)

### alacritty.nix
Terminal emulator:
- Theme: tokyo_night_storm (from alacritty-theme package)
- Font: constants.fontFamily, 14pt
- Window: maximized, 0.95 opacity, blur
- Scrollback: uses constants.historySize
- URL hints: Cmd/Ctrl+click to open (cross-platform)
- Bell: visual + notify-send on Linux
- Keybindings: cross-platform (Command on macOS, Control on Linux)

### ghostty.nix
Terminal emulator:
- Font: constants.fontFamily, 12pt
- Theme: Tokyo Night Storm (macOS only via settings)
- Keybindings: uses Ghostty defaults (well-designed out of the box)
- macOS: option-as-alt enabled

### tmux.nix
Terminal multiplexer:
- vi mode, mouse enabled
- Tokyo Night theme plugin (storm variant)
- Plugins: sensible, yank, pain-control, vim-tmux-navigator, resurrect, continuum
- Session persistence: 15-minute autosave, restore on start

### zellij.nix
Terminal multiplexer:
- Theme: tokyo-night-storm
- zjstatus plugin for status bar with theme colors
- Custom keybindings: Alt+hjkl navigation, Alt+[] tabs, Alt+n/t new pane/tab

### lazydocker.nix
Docker TUI:
- Tokyo Night theme colors
- Rounded borders
- Custom commands: bash, sh shell access

### ssh.nix
SSH configuration:
- Forward agent and X11 enabled
- macOS: UseKeychain
- SSH matchBlocks defined in specialisations.nix (work: *.local -> fraggle user)

### btop.nix, glow.nix
Simple wrappers with basic configuration.

---

## Editors Modules (`modules/editors/`)

### vim.nix
Vim configuration:
- Linux: Generates .vimrc for system vim with plugin runtimepath
- macOS: Uses home-manager vim module
- Plugins: airline, vim-nix, commentary, surround, gitgutter
- Settings: numbers, cursor line, 2-space indent, search highlighting

### neovim.nix
Full IDE configuration (~500 lines):

**Plugins**:
- UI: snacks-nvim, tokyonight-nvim, lualine-nvim, nvim-web-devicons
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

## Themes Modules (`modules/themes/`)

### tokyo-night-storm.nix
Color palette definition:
- `name`: "tokyo-night-storm"
- `altName`: "TokyoNight Storm"
- `fileName`: "tokyo_night_storm"
- `colors`: Full 16-color palette + bg/fg

Used by: alacritty, ghostty, lazygit, lazydocker, tmux, zellij, neovim
