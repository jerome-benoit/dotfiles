# Home Manager Configuration

Nix flakes configuration for Generic Linux and macOS.

## Installation

```bash
git clone <repository-url> ~/.nix
cd ~/.nix

# Bootstrap
make bootstrap SPEC=work     # or SPEC=personal
```

Restart your shell.

## Usage

### Home Manager

```bash
# Apply changes (preserves current specialisation)
hm

# Switch specialisation
hmw  # work
hmp  # personal

# Or via Makefile
make switch SPEC=work
```

### Caveman

Desktop profiles install the complete Caveman CLI (`caveman`, alias `cave`) and
its seven companions: `caveman-proxy`, `caveman-engine`, `caveman-mcp`, `cavemem`,
`caveman-browse`, `caveman-shrink`, and `caveman-blocks`. Server profiles leave
`modules.development.caveman.enable` disabled.

```bash
nix build .#caveman                # Build without switching Home Manager
./result/bin/caveman --version
./result/bin/caveman setup --json   # Diagnose the installed runtime only
nix build .#checks.x86_64-linux.caveman
```

Installation does not configure agents, install skills or hooks, create a
service, start the proxy, or sign in to Caveman Cloud. Plain `caveman setup`
starts upstream onboarding; use `setup --json` for inspection without wiring
agents. Agent integration remains a separate, explicit user action.

All executables are pinned in the Nix store. Node, Python for Blocks, Git, and
a browser (Chromium on Linux, Google Chrome on macOS) are provided by Nix;
`CAVEMAN_BROWSE_CHROME` can override the browser. Mutable configuration,
credentials, and recovery databases remain outside the store, normally under
`~/.caveman` (override with `CAVEMAN_HOME`). Recovery databases contain original
tool output and should be treated as sensitive.

CLI and Blocks wrappers default telemetry off. Cloud login and Auto routing
remain upstream opt-in actions; telemetry opt-out is not a routing opt-out.
`caveman update`, `setup --install`, and the CLI's internal executable installers
refuse to create a second installation outside Nix. Explicit manual Blocks hook
integration retains upstream's executable-copy and refresh mechanism; the CLI
guards do not govern it. Versions, binaries, and license hashes are maintained
together through
`home-manager/modules/development/pins/caveman.json` and the existing Renovate
hash-update workflow.

### Private configuration and credentials

Managed via [SOPS](https://github.com/getsops/sops). Private configuration is decrypted at eval-time; runtime credentials are decrypted by sops-nix.

```bash
make decrypt-private  # Decrypt private configuration only for Nix evaluation
make decrypt          # Decrypt private configuration and credentials for inspection
make encrypt          # Re-encrypt private configuration and credentials after editing
make edit-private     # Edit private configuration interactively
make edit-credentials # Edit runtime credentials interactively
make clean            # Remove decrypted private configuration, credentials, and temporary files
```

### GPG keypair

Subkeys and passphrase are bundled, age-encrypted to the project's age recipient, and committed at `secrets/gpg/keypair.tar.gz.age`. Home-manager activation imports them idempotently on any machine where the configured SOPS age identity is present.

```bash
make encrypt-gpg      # one-shot from a trusted machine; then commit the bundle
```

Recovery: with the configured SOPS age identity + the git repo, SOPS secrets and GPG subkeys are recoverable. The GPG primary key is not in the bundle; back it up separately offline.

### Formatting

```bash
nix fmt              # Format all .nix files
nix fmt file.nix     # Format specific file
```

### Validation

```bash
nix flake check      # Run all checks:
                     # - Formatting verification
                     # - Symlinks validation
                     # - Build all home-manager configurations
```

### Maintenance

```bash
nix flake update     # Update inputs
nh clean all --keep 3
```
