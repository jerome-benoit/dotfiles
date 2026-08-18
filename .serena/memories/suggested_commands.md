# Suggested Commands

## Home Manager Operations

| Command | Description                                                                  |
| ------- | ---------------------------------------------------------------------------- |
| `hm`    | Apply home-manager changes (default alias, preserves current specialisation) |
| `hmw`   | Switch to work specialisation                                                |
| `hmp`   | Switch to personal specialisation                                            |

**Note**: `hm*` aliases use `_hm_switch` which decrypts sops secrets then calls `nh home switch --impure -c "$(whoami)" -- --impure`. The `-- --impure` is needed because nh has a bug where `--impure` isn't passed to its internal `nix eval` for config discovery.

## Initial Installation

```bash
# Clone repository
git clone <repository-url> ~/.nix
cd ~/.nix

# Ensure age key file exists (required for sops decryption)
# ~/.config/sops/age/keys.txt must exist on each machine (0600, outside repo)

# Bootstrap (with specialisation)
make bootstrap SPEC=work      # or SPEC=personal, or omit SPEC for base
```

After installation, restart your shell to pick up aliases.

## Private Configuration and Credentials (SOPS)

| Command                 | Description                                                     |
| ----------------------- | --------------------------------------------------------------- |
| `make decrypt-private`  | Decrypt private configuration only for Nix evaluation           |
| `make decrypt`          | Decrypt private configuration and credentials for inspection    |
| `make encrypt`          | Re-encrypt private configuration and credentials after editing  |
| `make edit-private`     | Edit private configuration interactively                        |
| `make edit-credentials` | Edit runtime credentials interactively                           |
| `make clean`            | Remove decrypted configuration, credentials, and temporaries     |
| `make switch SPEC=work` | Switch Home Manager with transient private configuration         |
| `make build`            | Build Home Manager with transient private configuration          |

## Formatting

| Command                     | Description                         |
| --------------------------- | ----------------------------------- |
| `nix fmt`                   | Format all .nix files (uses nixfmt) |
| `nix fmt path/to/file.nix`  | Format specific file                |
| `nix fmt path/to/directory` | Format all .nix files in directory  |

## Validation & Testing

| Command                        | Description                                              |
| ------------------------------ | -------------------------------------------------------- |
| `nix flake check`              | Run all checks (formatting, symlinks, build all configs) |
| `nix flake check --show-trace` | Run checks with detailed error traces                    |
| `nix flake show`               | Show all flake outputs                                   |
| `nix flake metadata`           | Show flake metadata and inputs                           |

### What `nix flake check` validates:

1. **formatting** - All .nix files formatted correctly (nixfmt)
2. **symlinks** - No broken symlinks in build output (platform-aware)
3. **statix** - Nix linter (anti-patterns, style)
4. **deadnix** - Dead code detection (unused bindings, inputs)
5. **home-<personal-username>** - Build personal home configuration (Linux)
6. **home-almalinux** - Build almalinux's home configuration (Linux)
7. **home-<work-username>** - Build work home configuration (macOS)

(Usernames come from `privateConfig.identity.username` and `privateConfig.work.username`)

## Dependency Management

| Command                                      | Description             |
| -------------------------------------------- | ----------------------- |
| `nix flake update`                           | Update all flake inputs |
| `nix flake lock --update-input nixpkgs`      | Update specific input   |
| `nix flake lock --update-input home-manager` | Update home-manager     |
| `nix flake lock --update-input opencode`     | Update opencode         |

## Maintenance

| Command                  | Description                              |
| ------------------------ | ---------------------------------------- |
| `nh clean all --keep 3`  | Clean old generations, keep last 3       |
| `nix-collect-garbage -d` | Delete all old generations               |
| `nix store gc`           | Garbage collect unreferenced store paths |
| `nix store optimise`     | Deduplicate store paths                  |

## Debugging

| Command                                                                           | Description                 |
| --------------------------------------------------------------------------------- | --------------------------- |
| `nix repl --file flake.nix`                                                       | Interactive REPL with flake |
| `nix eval --impure ".#homeConfigurations.$(whoami).config.home.packages"`         | Evaluate expression         |
| `nix build --impure ".#homeConfigurations.$(whoami).activationPackage" --dry-run` | Dry-run build               |
