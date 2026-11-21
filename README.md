# Home Manager Configuration

Nix flakes configuration for Generic Linux and macOS.

## Installation

Before bootstrapping, install the configured SOPS age identity outside the repository with permissions `0600`.

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

# Switch specialisation (from an active specialisation)
hmw  # work
hmp  # personal

# Or via Makefile
make switch SPEC=work
```

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

Interactive SOPS edits replace existing ciphertext only after successful encryption.
Edits use private temporary files, removed after the editor and its supervised processes stop.
Uncatchable termination or machine failure may leave plaintext behind.

### Hermes plugin layout migration

Home Manager now links individual plugin files into a writable directory under
`<hermesHome>/plugins/<name>` (`~/.hermes/plugins/github-copilot` by default for
Copilot). On the first switch to this layout, keep the previous generation's
plugin sources unchanged. Change plugin sources in a second switch: Home
Manager checks for file collisions before it can remove the old directory link.

To roll back to a generation that used whole-directory links:

1. Move each affected plugin directory to a new backup path **outside**
   `<hermesHome>/plugins`. Preserve the whole directory, including any local files.
2. Activate the old generation. Home Manager can then install its directory link
   at the vacant path.
3. Keep the backup until you have verified the old generation. If activation
   fails and the original path is still vacant, move the backup back.

### Email

Account preference order: **work** — `work`, `piment-noir`, `gmail`; **personal** — `piment-noir`, `gmail`. The first account is the default.

| Account       | Service                         | Backend            | Authentication    |
| ------------- | ------------------------------- | ------------------ | ----------------- |
| `piment-noir` | OVHcloud Mail                   | IMAP/SMTP over TLS | Password (SOPS)   |
| `work`        | Microsoft 365 (Exchange Online) | Microsoft Graph    | OAuth 2.0 (Ortie) |
| `gmail`       | Gmail                           | Gmail API          | OAuth 2.0 (Ortie) |

After Home Manager activation:

```bash
ortie auth get -a msgraph          # Authorize Microsoft 365 (work only)
ortie auth get -a gmail            # Authorize Gmail
himalaya envelope list -a gmail   # List Gmail messages (both specs)
```

Tokens use the unlocked system keyring and refresh on demand. The Google project must enable Gmail API; in Testing, Gmail refresh tokens expire after seven days. Microsoft tenant policy may require administrator consent.

### GPG keypair

Subkeys and passphrase are bundled at `secrets/gpg/keypair.tar.gz.age`, encrypted to the recipient derived from the selected age identity. The export script selects `AGE_KEY`, then `SOPS_AGE_KEY_FILE`, then the platform's default SOPS age identity path. It does not read `.sops.yaml`. Home Manager activation decrypts the bundle with the identity at `sops.age.keyFile`. Export using that configured identity for machines that must import the bundle.

```bash
make encrypt-gpg      # one-shot from a trusted machine; then commit the bundle
```

Recovery requires the repository and identities that can decrypt the SOPS secrets and the GPG bundle. The GPG primary key is not in the bundle; back it up separately offline.

GPG bundle exports replace the previous bundle only after successful encryption and verification.
Bundle passphrases preserve leading and trailing whitespace.

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
                     # - Build Home Manager configurations for the current platform
```

Focused integration checks require an `x86_64-linux` builder. They use disposable secrets
and do not activate your environment, download models, or run GPU inference.

```bash
nix build .#checks.x86_64-linux.secrets
nix build .#checks.x86_64-linux.consumers
nix build .#checks.x86_64-linux.hermes-agent
nix build .#checks.x86_64-linux.caveman
```

### Maintenance

```bash
nix flake update     # Update inputs
nh clean all --keep 3 --optimise
```
