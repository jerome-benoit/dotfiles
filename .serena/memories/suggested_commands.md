# Suggested Commands

## Home Manager Operations

| Command | Description                                                                  |
| ------- | ---------------------------------------------------------------------------- |
| `hm`    | Apply home-manager changes (default alias, preserves current specialisation) |
| `hmw`   | Switch to work specialisation (from an active specialisation)                |
| `hmp`   | Switch to personal specialisation (from an active specialisation)            |

From the base configuration, use `make switch SPEC=work` or `make switch SPEC=personal`.

**Note**: `hm*` aliases use `_hm_switch` which decrypts sops secrets then calls `nh home switch --impure -c "$(whoami)" -- --impure`. The `-- --impure` is needed because nh has a bug where `--impure` isn't passed to its internal `nix eval` for config discovery.

### Ollama user service (Linux)

See the `ollama.nix` section of `modules_reference` for activation rules and
service settings.

Before the first activation, stop any manually managed Ollama server at a chosen
idle point; for the existing launcher, use `~/bin/ollama-serve.sh --stop`.
Then apply Home Manager. `sd-switch` starts the generated service; no imperative
enable command or activation hook is needed. Models remain in their existing
location; the module does not migrate or preload them.

```bash
systemctl --user status ollama.service
journalctl --user -u ollama.service -f
systemctl --user restart ollama.service
```

Check the configured listen address before connecting from another host.
Ollama does not authenticate clients. Match each client's context budget to
the server and model.

The service follows the user manager's lifetime. Continuous operation without
login requires host-managed lingering; Home Manager does not enable it here.

## Bootstrap and secrets

See the repository README for setup and secret handling. Use `make help` for
the available targets.

## Formatting

| Command                     | Description                         |
| --------------------------- | ----------------------------------- |
| `nix fmt`                   | Format all .nix files (uses nixfmt) |
| `nix fmt path/to/file.nix`  | Format specific file                |
| `nix fmt path/to/directory` | Format all .nix files in directory  |

## Validation & Testing

See [Validation](../../README.md#validation) for full and focused check commands.
Add `--show-trace` to diagnose evaluation failures. Use `nix flake show` to list
outputs and `nix flake metadata` to inspect inputs.

### Check coverage

`checks/default.nix` defines the shared checks:

| Checks                            | Coverage                                                                                             |
| --------------------------------- | ---------------------------------------------------------------------------------------------------- |
| `formatting`, `statix`, `deadnix` | Nix formatting, anti-patterns and unused code                                                        |
| `symlinks`                        | Broken symlinks and traversal errors in compatible Home Manager outputs; real filesystem regressions |
| `secrets`, `email`                | Secret lifecycle and account/credential consumers                                                    |
| `consumers`                       | Literal shell arguments, terminal key dispatch, Treesitter/textobjects and real Pyright attachment   |
| `hermes-agent`                    | Generated configuration, plugin paths and service ordering                                           |
| `caveman`                         | Generated integrations, installation ownership and native/shrink hooks                               |
| `development`, `opencode-desktop` | Development-module activation, Ollama service platform/disable boundaries and Desktop CLI staging    |
| `gpu`, `ci-contract`              | GPU selection and CI contracts                                                                       |

`flake.nix` adds Home Manager builds for the selected platform: personal and
`almalinux` on `x86_64-linux`, work on `aarch64-darwin`. It also adds the selected
`prime-agent` package. CI runs Linux and Darwin separately; a local invocation does
not build the other platform's configurations.

### Focused integration checks

The checks use generated configurations. Scenario definitions live in
`checks/secrets-integration.py`, `checks/consumer-{shells,terminals}.py`,
`checks/consumer-editors.lua`, `checks/hermes-agent.nix` and `checks/caveman*.py`.
Synthetic ordering checks do not certify native activation or login behavior.

### Pure and private evaluation

Pure evaluation uses the placeholder identity in `secrets/default.nix`; the focused
checks above do not require decryption. Home Manager check names use that placeholder
identity unless private configuration is supplied.

For raw `--impure` Nix evaluation, the loader reads `NIX_PRIVATE_CONFIG_FILE`
when nonempty; otherwise, it reads `$HOME/.nix/secrets/private.dec.json`. It fails if
the selected file is absent. See the README's
[inspection, editing, and cleanup procedures](../../README.md#private-configuration-and-credentials).

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
