# Suggested Commands

## Home Manager Operations

| Command | Description                                                                  |
| ------- | ---------------------------------------------------------------------------- |
| `hm`    | Apply home-manager changes (default alias, preserves current specialisation) |
| `hmw`   | Switch to work specialisation (from an active specialisation)                |
| `hmp`   | Switch to personal specialisation (from an active specialisation)            |

From the base configuration, use `make switch SPEC=work` or `make switch SPEC=personal`.

**Note**: `hm*` aliases use `_hm_switch` which decrypts sops secrets then calls `nh home switch --impure -c "$(whoami)" -- --impure`. The `-- --impure` is needed because nh has a bug where `--impure` isn't passed to its internal `nix eval` for config discovery.

## Initial Installation

```bash
# Clone repository
git clone <repository-url> ~/.nix
cd ~/.nix

# Ensure age key file exists (required for sops decryption)
# The configured SOPS age identity must exist on each machine (0600, outside repo)

# Bootstrap (with specialisation)
make bootstrap SPEC=work      # or SPEC=personal, or omit SPEC for base
```

After installation, restart your shell to pick up aliases.

## Private Configuration and Credentials (SOPS)

| Command                 | Description                                                    |
| ----------------------- | -------------------------------------------------------------- |
| `make decrypt-private`  | Decrypt private configuration only for Nix evaluation          |
| `make decrypt`          | Decrypt private configuration and credentials for inspection   |
| `make encrypt`          | Re-encrypt private configuration and credentials after editing |
| `make edit-private`     | Edit private configuration interactively                       |
| `make edit-credentials` | Edit runtime credentials interactively                         |
| `make clean`            | Remove decrypted configuration, credentials, and temporaries   |
| `make switch SPEC=work` | Switch Home Manager with transient private configuration       |
| `make build`            | Build Home Manager with transient private configuration        |

## Formatting

| Command                     | Description                         |
| --------------------------- | ----------------------------------- |
| `nix fmt`                   | Format all .nix files (uses nixfmt) |
| `nix fmt path/to/file.nix`  | Format specific file                |
| `nix fmt path/to/directory` | Format all .nix files in directory  |

## Validation & Testing

| Command                        | Description                           |
| ------------------------------ | ------------------------------------- |
| `nix flake check`              | Run checks for the current platform   |
| `nix flake check --show-trace` | Run checks with detailed error traces |
| `nix flake show`               | Show all flake outputs                |
| `nix flake metadata`           | Show flake metadata and inputs        |

### Check coverage

`checks/default.nix` defines the shared checks:

| Checks                            | Coverage                                                                                           |
| --------------------------------- | -------------------------------------------------------------------------------------------------- |
| `formatting`, `statix`, `deadnix` | Nix formatting, anti-patterns and unused code                                                      |
| `symlinks`                        | Broken symlinks in compatible Home Manager outputs                                                 |
| `secrets`, `email`                | Secret lifecycle and account/credential consumers                                                  |
| `consumers`                       | Literal shell arguments, terminal key dispatch, Treesitter/textobjects and real Pyright attachment |
| `hermes-agent`                    | Generated configuration, plugin paths and service ordering                                         |
| `caveman`                         | Generated integrations, installation ownership and native/shrink hooks                             |
| `development`, `opencode-desktop` | Development-module activation and Desktop CLI staging                                              |
| `strata`, `gpu`, `ci-contract`    | Workspace/runtime validation, GPU selection and CI contracts                                       |

`flake.nix` adds Home Manager builds for the selected platform: personal and
`almalinux` on `x86_64-linux`, work on `aarch64-darwin`. It also adds the selected
`prime-agent` package. CI runs Linux and Darwin separately; a local invocation does
not build the other platform's configurations.

### Focused integration checks

These commands require an `x86_64-linux` builder:

```bash
nix build .#checks.x86_64-linux.secrets
nix build .#checks.x86_64-linux.consumers
nix build .#checks.x86_64-linux.hermes-agent
nix build .#checks.x86_64-linux.caveman
```

The checks use disposable secrets and generated configurations without user
activation, model downloads or GPU inference. Scenario definitions live in
`checks/secrets-integration.py`, `checks/consumer-{shells,terminals}.py`,
`checks/consumer-editors.lua`, `checks/hermes-agent.nix` and `checks/caveman*.py`.
Synthetic ordering checks do not certify native activation or login behavior.

### Pure and private evaluation

Pure evaluation uses the placeholder identity in `secrets/default.nix`; the focused
checks above do not require decryption. Home Manager check names use that placeholder
identity unless private configuration is supplied.

For evaluation with the real private identity, run `make decrypt-private` before
adding `--impure`. The loader reads `NIX_PRIVATE_CONFIG_FILE` when set, otherwise
`$HOME/.nix/secrets/private.dec.json`, and fails if the file is absent. Run
`make clean` after inspection. Prefer `make build` and `make switch` for transient
private configuration during normal Home Manager operations.

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
