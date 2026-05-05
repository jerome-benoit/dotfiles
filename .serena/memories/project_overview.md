# Project Overview

## Purpose

Home Manager configuration using Nix flakes for managing dotfiles and user environment across multiple platforms (Linux and macOS).

## Tech Stack

- **Nix Flakes** - Declarative package management and system configuration
- **Home Manager** - User environment management for Nix
- **Language**: Nix expression language
- **Renovate** - Automated dependency updates

## Flake Inputs

| Input                | Source                                      | Description                                                              |
| -------------------- | ------------------------------------------- | ------------------------------------------------------------------------ |
| `nixpkgs`            | `github:nixos/nixpkgs?ref=nixpkgs-unstable` | Nix packages (unstable)                                                  |
| `home-manager`       | `github:nix-community/home-manager`         | Home Manager, follows nixpkgs                                            |
| `opencode`           | `github:anomalyco/opencode`                 | OpenCode TUI/CLI/Desktop                                                 |
| `opencode-nvim`      | `github:NickvanDyke/opencode.nvim`          | Neovim plugin (non-flake)                                                |
| `agent-of-empires`   | `github:njbrake/agent-of-empires`           | AI agent session manager (non-flake)                                     |
| `agent-deck`         | `github:asheshgoplani/agent-deck`           | AI agent command center (non-flake)                                      |
| `openspec`           | `github:Fission-AI/OpenSpec`                | OpenSpec CLI, follows nixpkgs                                            |
| `nix-openclaw`       | `github:openclaw/nix-openclaw`              | OpenClaw AI gateway, follows nixpkgs + home-manager + flake-utils + nix-openclaw-tools |
| `nix-openclaw-tools` | `github:openclaw/nix-openclaw-tools`        | OpenClaw tool binaries, follows nixpkgs                                  |
| `hermes-agent`       | `github:jerome-benoit/hermes-agent/main-patched` | Hermes Agent (fork with darwin fixes), follows nixpkgs + flake-parts + pyproject-nix + uv2nix + pyproject-build-systems |
| `qmd`                | `github:tobi/qmd`                           | QMD CLI, follows nixpkgs + flake-utils                                   |
| `agtx`               | `github:fynnfluegge/agtx`                   | Agtx terminal agent (non-flake)                                          |
| `flake-utils`        | `github:numtide/flake-utils`                | Flake utilities                                                          |
| `flake-parts`        | `github:hercules-ci/flake-parts`            | Flake composition                                                        |
| `pyproject-nix`      | `github:pyproject-nix/pyproject.nix`        | Python packaging for Nix, follows nixpkgs                                |
| `uv2nix`             | `github:pyproject-nix/uv2nix`               | uv lockfile to Nix, follows nixpkgs + pyproject-nix                      |
| `pyproject-build-systems` | `github:pyproject-nix/build-system-pkgs` | Python build systems, follows nixpkgs + pyproject-nix + uv2nix          |

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

| Name       | Email                  | Signature       |
| ---------- | ---------------------- | --------------- |
| `work`     | constants.workEmail    | SAP Labs France |
| `personal` | constants.primaryEmail | Piment Noir     |

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
│       ├── development/         # Dev tools (16 files)
│       │   ├── agent-deck.nix   # AI agent command center TUI
│       │   ├── aoe.nix          # Agent of Empires session manager
│       │   ├── bun.nix          # JavaScript runtime
│       │   ├── claude-code.nix  # Claude Code AI assistant
│       │   ├── gh.nix           # GitHub CLI + extensions
│       │   ├── git.nix          # Git config with delta, mergiraf, GPG signing
│       │   ├── lazygit.nix      # Git TUI with conventional commits
│       │   ├── openclaw.nix     # OpenClaw AI gateway
│       │   ├── opencode.nix     # OpenCode AI assistant
│       │   ├── opencode-hashes.nix # OpenCode desktop Cargo hashes
│       │   ├── openspec.nix     # OpenSpec CLI
│       │   ├── hermes-agent.nix # Hermes Agent (gateway + dashboard services)
│       │   ├── agtx.nix         # Agtx terminal agent
│       │   ├── pi.nix           # Pi coding agent
│       │   └── qmd.nix          # QMD CLI
│       ├── programs/            # Applications (9 files)
│       │   ├── alacritty.nix    # Terminal emulator with theme
│       │   ├── btop.nix         # System monitor
│       │   ├── ghostty.nix      # Terminal emulator
│       │   ├── glow.nix         # Markdown viewer
│       │   ├── himalaya.nix     # CLI email client
│       │   ├── lazydocker.nix   # Docker TUI with theme
│       │   ├── ssh.nix          # SSH config with specialisation overrides
│       │   ├── tmux.nix         # Terminal multiplexer with dynamic theme
│       │   └── zellij.nix       # Terminal multiplexer with zjstatus
│       ├── editors/             # Editors (2 files)
│       │   ├── vim.nix          # Vim config (system vim on Linux)
│       │   └── neovim.nix       # Full IDE setup with LSP, treesitter, opencode
│       └── themes/              # Color themes (1 file)
│           └── default.nix      # Theme registry with mkTheme factory (7 themes)
├── statix.toml                  # Statix linter configuration
├── patches/                     # Upstream PR patches
│   ├── opencode/                # Patches for anomalyco/opencode
│   └── qmd/                     # Patches for tobi/qmd
├── checks/                      # Flake checks (5 files)
│   ├── default.nix              # Check aggregator
│   ├── formatting.nix           # Nix formatting check (nixfmt)
│   ├── symlinks.nix             # Broken symlinks detection (platform-aware)
│   ├── statix.nix               # Nix linter check
│   └── deadnix.nix              # Dead code detection check
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

- **mkPlatformPackage**: Helper in `lib.nix` selects Nix package on Darwin or system stub on Linux
- **mkSystemPackage**: Creates placeholder packages for system-managed binaries on Linux
- **Profile-driven**: Modules check `profileModules.<category>.<module>` for enable state
- **Theme registry**: 7 themes (3 Tokyo Night + 4 Catppuccin) defined via `mkTheme` factory, active theme selected by key, accessed via `config.modules.themes.current`
- **Assertions**: Modules validate dependencies (e.g., lazygit requires git)
- **Homebrew integration**: macOS uses `.Brewfile` for casks not in nixpkgs
