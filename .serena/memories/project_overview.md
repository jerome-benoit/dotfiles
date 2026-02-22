# Project Overview

## Purpose

Home Manager configuration using Nix flakes for managing dotfiles and user environment across multiple platforms (Linux and macOS).

## Tech Stack

- **Nix Flakes** - Declarative package management and system configuration
- **Home Manager** - User environment management for Nix
- **Language**: Nix expression language
- **Renovate** - Automated dependency updates

## Flake Inputs

| Input              | Source                                      | Description                          |
| ------------------ | ------------------------------------------- | ------------------------------------ |
| `nixpkgs`          | `github:nixos/nixpkgs?ref=nixpkgs-unstable` | Nix packages (unstable)              |
| `home-manager`     | `github:nix-community/home-manager`         | Home Manager, follows nixpkgs        |
| `opencode`         | `github:anomalyco/opencode`                 | OpenCode TUI/CLI/Desktop             |
| `opencode-nvim`    | `github:NickvanDyke/opencode.nvim`          | Neovim plugin (non-flake)            |
| `agent-of-empires` | `github:njbrake/agent-of-empires`           | AI agent session manager (non-flake) |
| `agent-deck`       | `github:asheshgoplani/agent-deck`           | AI agent command center (non-flake)  |
| `openspec`         | `github:Fission-AI/OpenSpec`                | OpenSpec CLI, follows nixpkgs        |

## Supported Platforms

| Platform | Architecture     | Users                  |
| -------- | ---------------- | ---------------------- |
| Linux    | `x86_64-linux`   | `fraggle`, `almalinux` |
| macOS    | `aarch64-darwin` | `I339261`              |

## Profiles

| Profile   | Description           | Use Case                          |
| --------- | --------------------- | --------------------------------- |
| `desktop` | Full configuration    | Personal workstation, development |
| `server`  | Minimal configuration | Remote servers (ns3108029)        |

## Specialisations

| Name       | Email                         | Signature       |
| ---------- | ----------------------------- | --------------- |
| `work`     | jerome.benoit@sap.com         | SAP Labs France |
| `personal` | jerome.benoit@piment-noir.org | Piment Noir     |

## Known Hosts

| Hostname                   | Profile | Notes             |
| -------------------------- | ------- | ----------------- |
| `rigel`                    | desktop | Bun not supported |
| `ns3108029.ip-54-37-87.eu` | server  | Remote server     |

## Supported Linux Distros

Auto-detected via `/etc/os-release`: `almalinux`, `debian`, `fedora`, `ubuntu`

## Project Structure

```
~/.nix/
├── flake.nix                    # Main flake definition
├── flake.lock                   # Locked dependencies
├── constants.nix                # Global constants (systems, profiles, distros)
├── .editorconfig                # Editor formatting rules
├── renovate.json                # Renovate bot configuration
├── README.md                    # Documentation
├── .gitignore                   # Git ignore rules
├── home-manager/
│   ├── home.nix                 # Main entry point
│   └── modules/
│       ├── default.nix          # Imports all categories
│       ├── core/                # Core modules (8 files)
│       │   ├── default.nix      # Imports all core modules
│       │   ├── constants.nix    # User info (email, gpg, hosts, etc.)
│       │   ├── distro.nix       # Linux distro detection
│       │   ├── home-manager.nix # Home-manager, nix settings, gc
│       │   ├── lib.nix          # Shared library functions
│       │   ├── packages.nix     # Common packages + Homebrew integration
│       │   ├── profile.nix      # Profile system (desktop/server modules)
│       │   └── specialisations.nix # Work/personal contexts
│       ├── shell/               # Shell tools (7 files)
│       │   ├── direnv.nix       # Directory environment management
│       │   ├── eza.nix          # Modern ls replacement
│       │   ├── fd.nix           # Fast file finder
│       │   ├── fzf.nix          # Fuzzy finder (requires fd)
│       │   ├── ripgrep.nix      # Fast grep replacement
│       │   ├── zoxide.nix       # Smart cd command
│       │   └── zsh.nix          # Shell config with oh-my-zsh
│       ├── development/         # Dev tools (11 files)
│       │   ├── agent-deck.nix   # AI agent command center TUI
│       │   ├── aoe.nix          # Agent of Empires session manager
│       │   ├── bun.nix          # JavaScript runtime
│       │   ├── claude-code.nix  # Claude Code AI assistant
│       │   ├── gh.nix           # GitHub CLI + extensions
│       │   ├── git.nix          # Git config with delta, mergiraf, GPG signing
│       │   ├── lazygit.nix      # Git TUI with conventional commits
│       │   ├── opencode.nix     # OpenCode AI assistant
│       │   ├── opencode-hashes.nix # OpenCode package hashes
│       │   └── openspec.nix     # OpenSpec CLI
│       ├── programs/            # Applications (9 files)
│       │   ├── alacritty.nix    # Terminal emulator with theme
│       │   ├── btop.nix         # System monitor
│       │   ├── ghostty.nix      # Terminal emulator
│       │   ├── glow.nix         # Markdown viewer
│       │   ├── himalaya.nix     # CLI email client
│       │   ├── lazydocker.nix   # Docker TUI with theme
│       │   ├── ssh.nix          # SSH config with specialisation overrides
│       │   ├── tmux.nix         # Terminal multiplexer with tokyo-night
│       │   └── zellij.nix       # Terminal multiplexer with zjstatus
│       ├── editors/             # Editors (2 files)
│       │   ├── vim.nix          # Vim config (system vim on Linux)
│       │   └─�� neovim.nix       # Full IDE setup with LSP, treesitter, opencode
│       └── themes/              # Color themes (3 files)
│           ├── tokyo-night.nix       # TokyoNight dark theme
│           ├── tokyo-night-light.nix # TokyoNight light theme
│           └── tokyo-night-storm.nix # TokyoNight Storm theme (default)
├── checks/                      # Flake checks (3 files)
│   ├── default.nix              # Check aggregator
│   ├── formatting.nix           # Nix formatting check (nixfmt)
│   └── symlinks.nix             # Broken symlinks detection
└── .github/
    └── workflows/
        └── check.yml            # CI workflow (Linux + macOS)
```

## Configuration Flow

1. `flake.nix` defines inputs and creates `homeConfigurations` per user
2. `mkHomeConfiguration` passes `arch`, `username`, `constants`, `inputs` to modules
3. `home.nix` detects hostname → determines profile → enables modules accordingly
4. Profile system (`profile.nix`) defines which modules are enabled per profile
5. Specialisations allow runtime switching between work/personal contexts
6. Each module follows `options` + `config = lib.mkIf cfg.enable { ... }` pattern

## Key Design Patterns

- **System packages on Linux**: Most shell tools use system-installed binaries via dummy `pkgs.runCommand` packages
- **Nix packages on macOS**: Full packages installed via Nix on Darwin
- **Profile-driven**: Modules check `profileModules.<category>.<module>` for enable state
- **Theme centralization**: Colors defined in `themes/tokyo-night-storm.nix`, referenced by multiple programs
- **Assertions**: Modules validate dependencies (e.g., lazygit requires git)
- **Homebrew integration**: macOS uses `.Brewfile` for casks not in nixpkgs
