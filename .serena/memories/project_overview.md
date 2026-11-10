# Project Overview

## Purpose

Home Manager configuration using Nix flakes for managing dotfiles and user environment across multiple platforms (Linux and macOS).

## Tech Stack

- **Nix Flakes** - Declarative package management and system configuration
- **Home Manager** - User environment management for Nix
- **SOPS** - Encrypted secrets with PGP and age recipients; sops-nix uses the configured age identity for runtime decryption
- **Language**: Nix expression language
- **Renovate** - Automated dependency updates

## Flake Inputs

| Input                     | Source                                      | Description                                                                                                              |
| ------------------------- | ------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `nixpkgs`                 | `github:nixos/nixpkgs?ref=nixpkgs-unstable` | Nix packages (unstable)                                                                                                  |
| `home-manager`            | `github:nix-community/home-manager`         | Home Manager, follows nixpkgs                                                                                            |
| `opencode`                | `github:anomalyco/opencode`                 | OpenCode TUI/CLI/Desktop, follows nixpkgs                                                                                |
| `opencode-nvim`           | `github:NickvanDyke/opencode.nvim`          | Neovim plugin (non-flake)                                                                                                |
| `agent-of-empires`        | `github:agent-of-empires/agent-of-empires`  | AI agent session manager (flake, follows nixpkgs + flake-parts)                                                          |
| `openspec`                | `github:Fission-AI/OpenSpec`                | OpenSpec CLI, follows nixpkgs                                                                                            |
| `nix-openclaw-tools`      | `github:openclaw/nix-openclaw-tools`        | OpenClaw tool binaries, follows nixpkgs                                                                                  |
| `hermes-agent`            | `github:NousResearch/hermes-agent`          | Hermes Agent (upstream), follows nixpkgs + flake-parts + Home Manager + pyproject-nix + uv2nix + pyproject-build-systems |
| `qmd`                     | `github:tobi/qmd`                           | QMD CLI, follows nixpkgs + flake-utils                                                                                   |
| `flake-utils`             | `github:numtide/flake-utils`                | Flake utilities                                                                                                          |
| `flake-parts`             | `github:hercules-ci/flake-parts`            | Flake composition                                                                                                        |
| `pyproject-nix`           | `github:pyproject-nix/pyproject.nix`        | Python packaging for Nix, follows nixpkgs                                                                                |
| `uv2nix`                  | `github:pyproject-nix/uv2nix`               | uv lockfile to Nix, follows nixpkgs + pyproject-nix                                                                      |
| `pyproject-build-systems` | `github:pyproject-nix/build-system-pkgs`    | Python build systems, follows nixpkgs + pyproject-nix + uv2nix                                                           |

## Supported Platforms

| Platform | Architecture     | Users                                     |
| -------- | ---------------- | ----------------------------------------- |
| Linux    | `x86_64-linux`   | identity.username (personal), `almalinux` |
| macOS    | `aarch64-darwin` | work.username                             |

## Profiles

| Profile   | Description           | Use Case                          |
| --------- | --------------------- | --------------------------------- |
| `desktop` | Full configuration    | Personal workstation, development |
| `server`  | Minimal configuration | Remote servers (ns3108029)        |

## Specialisations

| Name       | Email source                 | Signature source              |
| ---------- | ---------------------------- | ----------------------------- |
| `work`     | privateConfig.work.email     | work.jobTitle + work.employer |
| `personal` | privateConfig.personal.email | identity + personal.domain    |

Specialisation switching: `hmw` / `hmp` aliases (available only from within a specialisation), or `make switch SPEC=work`.

## Known Hosts

`home-manager/modules/core/constants.nix` defines host aliases in `modules.core.constants.hosts`. Only the server address (`hosts.ns3108029`) comes from `privateConfig.hosts.server`; the other aliases are declared locally. Profiles are `desktop` and `server`, not a host inventory. `home-manager/home.nix` applies host-specific feature flags.

## Supported Linux Distros

Auto-detected via `/etc/os-release`: `almalinux`, `debian`, `fedora`, `ubuntu`

## Project Structure

```text
.
├── flake.nix                    # Inputs, packages, Home Manager configurations and checks
├── flake.lock                   # Locked flake inputs
├── constants.nix                # Non-secret systems, profiles and distro names
├── Makefile                     # Secret lifecycle, bootstrap and activation commands
├── README.md                    # User setup and maintenance
├── home-manager/
│   ├── home.nix                 # Profile wiring and host-specific flags
│   └── modules/
│       ├── core/                # Constants, profiles, secrets, services and shared helpers
│       ├── shell/               # Shell tools, including mise and Zsh
│       ├── development/         # Development tools, local builders and JSON source pins
│       ├── programs/            # Applications, including Ortie, SSHM, Sway and Syncthing
│       ├── editors/             # Vim and Neovim
│       └── themes/              # Typed registry and consumer identifiers
├── patches/                     # Local patches; see processes/patch_refresh
├── scripts/                     # Secret management and dependency maintenance helpers
├── secrets/
│   ├── default.nix              # Private configuration loader and pure placeholder
│   ├── private.enc.yaml         # Encrypted evaluation-time configuration
│   └── credentials.enc.yaml     # Encrypted runtime credentials
├── checks/
│   └── default.nix              # Integration, packaging, formatting and lint aggregation
└── .github/workflows/
    ├── check.yml                # CI checks
    └── fix-nix-hashes.yml        # Dependency hash maintenance
```

This map lists entry points, not every file. Category `default.nix` files declare module imports. `checks/default.nix` aggregates focused checks; `flake.nix` adds platform-specific Home Manager and Prime Agent checks. See `suggested_commands` for current validation commands.

## Configuration Flow

1. `flake.nix` defines inputs and creates `homeConfigurations` per user (dynamic names from `privateConfig`)
2. `mkHomeConfiguration` selects `pkgs` from `arch` and passes `profile`, `username`, `constants`, `privateConfig`, `inputs`, and `self` through `extraSpecialArgs`.
3. `secrets/default.nix` loads private configuration: (a) impure + file exists → decrypted JSON, (b) pure/CI (`HOME=""`) → placeholder, (c) impure + file missing → `builtins.abort` with "Run 'make decrypt-private' first"
4. `home.nix` uses the explicit target profile and detects hostname only for host-specific feature flags
5. Profile system (`profile.nix`) defines which modules are enabled per profile
6. Specialisations allow runtime switching between work/personal contexts
7. Each module follows `options` + `config = lib.mkIf cfg.enable { ... }` pattern
8. SOPS decrypts runtime credentials (`credentials.enc.yaml`) via systemd (Linux) or launchd (macOS). Private configuration (`private.enc.yaml`) is decrypted on demand for Nix evaluation (by `_hm_switch` / Makefile), then cleaned up.

## Key Design Patterns

- **mkPlatformPackage**: Helper in `lib.nix` selects Nix package on Darwin or system stub on Linux
- **mkSystemPackage**: Creates placeholder packages for system-managed binaries on Linux
- **Profile-driven**: Modules check `profileModules.<category>.<module>` for enable state
- **Theme registry**: 7 themes (3 Tokyo Night + 4 Catppuccin) defined via `mkTheme` factory, active theme selected by key, accessed via `config.modules.themes.current`
- **Assertions**: Modules validate dependencies (e.g., lazygit requires git)
- **Homebrew integration**: macOS uses `.Brewfile` for casks not in nixpkgs
