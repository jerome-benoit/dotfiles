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

# Import GPG key (required for sops decryption)
gpg --import gpg-public.asc
gpg --import gpg-private.asc
gpg --edit-key <KEY_ID> trust  # → 5 (ultimate) → quit
# KEY_ID is the GPG key fingerprint from personalSecrets.identity.gpg.keyId

# Ensure GPG can prompt for passphrase (SSH sessions)
export GPG_TTY=$(tty)

# Bootstrap (with specialisation)
make bootstrap SPEC=work      # or SPEC=personal, or omit SPEC for base
```

After installation, restart your shell to pick up aliases.

## Secrets Management (SOPS)

| Command                 | Description                                |
| ----------------------- | ------------------------------------------ |
| `make decrypt`          | Decrypt all secrets to JSON for inspection |
| `make encrypt`          | Re-encrypt after editing                   |
| `make edit-personal`    | Edit personal constants interactively      |
| `make edit-tokens`      | Edit application tokens interactively      |
| `make clean`            | Remove decrypted plaintext from disk       |
| `make switch SPEC=work` | Decrypt + switch with specialisation       |
| `make build`            | Decrypt + build (no activation)            |

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

(Usernames come from `personalSecrets.identity.username` and `personalSecrets.work.username`)

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
