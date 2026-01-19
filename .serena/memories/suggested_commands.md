# Suggested Commands

## Home Manager Operations

| Command | Description |
|---------|-------------|
| `hm` | Apply home-manager changes (default alias, preserves current specialisation) |
| `hmw` | Switch to work specialisation |
| `hmp` | Switch to personal specialisation |

**Note**: `hm*` aliases use `nh home switch` under the hood with `--impure` flag.

## Initial Installation

```bash
# Clone repository
git clone <repository-url> ~/.nix
cd ~/.nix

# Bootstrap (choose one)
nix run home-manager -- switch --flake . --impure -b backup
nix run home-manager -- switch --flake . --impure -b backup --specialisation personal
nix run home-manager -- switch --flake . --impure -b backup --specialisation work
```

After installation, restart your shell to pick up aliases.

## Formatting

| Command | Description |
|---------|-------------|
| `nix fmt` | Format all .nix files (uses nixfmt) |
| `nix fmt path/to/file.nix` | Format specific file |
| `nix fmt path/to/directory` | Format all .nix files in directory |

## Validation & Testing

| Command | Description |
|---------|-------------|
| `nix flake check` | Run all checks (formatting, symlinks, build all configs) |
| `nix flake check --show-trace` | Run checks with detailed error traces |
| `nix flake show` | Show all flake outputs |
| `nix flake metadata` | Show flake metadata and inputs |

### What `nix flake check` validates:
1. **formatting** - All .nix files formatted correctly
2. **symlinks** - No broken symlinks in build output
3. **home-fraggle** - Build fraggle's home configuration (Linux)
4. **home-almalinux** - Build almalinux's home configuration (Linux)
5. **home-I339261** - Build I339261's home configuration (macOS)

## Dependency Management

| Command | Description |
|---------|-------------|
| `nix flake update` | Update all flake inputs |
| `nix flake lock --update-input nixpkgs` | Update specific input |
| `nix flake lock --update-input home-manager` | Update home-manager |
| `nix flake lock --update-input opencode` | Update opencode |

## Maintenance

| Command | Description |
|---------|-------------|
| `nh clean all --keep 3` | Clean old generations, keep last 3 |
| `nix-collect-garbage -d` | Delete all old generations |
| `nix store gc` | Garbage collect unreferenced store paths |
| `nix store optimise` | Deduplicate store paths |

## Debugging

| Command | Description |
|---------|-------------|
| `nix repl --file flake.nix` | Interactive REPL with flake |
| `nix eval .#homeConfigurations.fraggle.config.home.packages` | Evaluate expression |
| `nix build .#homeConfigurations.fraggle.activationPackage --dry-run` | Dry-run build |

## Development Tools (installed by configuration)

| Tool | Command | Description |
|------|---------|-------------|
| ripgrep | `rg <pattern>` | Fast recursive grep |
| fd | `fd <pattern>` | Fast file finder |
| fzf | `fzf` | Fuzzy finder |
| eza | `eza` | Modern ls replacement |
| zoxide | `z <path>` | Smart directory jumper |
| lazygit | `lazygit` | Git TUI |
| lazydocker | `lazydocker` | Docker TUI |
| btop | `btop` | System monitor |
| glow | `glow <file.md>` | Markdown viewer |
| opencode | `opencode` | AI coding assistant |

## Git Aliases (via oh-my-zsh git plugin)

Common git aliases available when git plugin is enabled (desktop profile):
- `gst` - git status
- `gco` - git checkout
- `gcm` - git commit -m
- `gp` - git push
- `gl` - git pull
- `glog` - git log --oneline --decorate --graph

## Conventional Commits (lazygit)

Press `C` in lazygit files panel to create a conventional commit with:
- Type selection (feat, fix, docs, style, refactor, perf, test, build, ci, chore, revert)
- Optional scope
- Description
- Breaking change indicator
- Optional body
