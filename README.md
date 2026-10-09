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

### OpenClaw desktop and tools

`modules.development.openclaw.enable` installs only
`nix-openclaw.packages.<system>.openclaw-app`, without local packaging. It is
opt-in; desktop and server profile defaults remain unchanged.

The pinned upstream flake currently exports this component only for
`aarch64-darwin`, where Home Manager exposes it in
`~/Applications/Home Manager Apps`. Linux desktop support is blocked until
`nix-openclaw` exports `openclaw-app` for `x86_64-linux`. Enabling it on Linux
currently fails evaluation; it does not silently skip the app or install the
gateway bundle instead.

The standalone `nix-openclaw-tools` remain installed independently of the desktop
toggle (including `imsg`, `peekaboo`, and `poltergeist` on macOS desktop profiles).
Nix does not provision a gateway CLI/service, plugins, gateway configuration, or
app preferences. Choose a remote gateway or local setup in the app; the latter
uses the app’s own CLI installer and service management.

When migrating from the former managed gateway, start a fresh login shell to drop
`OPENCLAW_CONFIG_PATH`. Existing `~/.openclaw` data and `ai.openclaw.mac` preferences
(`openclaw.nixMode`, `openclaw.gateway.attachExistingOnly`) are not deleted or reset;
review them before configuring the app.

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
