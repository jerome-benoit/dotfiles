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

Managed via [SOPS](https://github.com/getsops/sops). Impure Nix evaluation reads decrypted private configuration; sops-nix decrypts runtime credentials.

```bash
make decrypt-private  # Inspect private configuration with raw impure Nix commands
make decrypt          # Decrypt both files for a manual edit or inspection
make encrypt          # Re-encrypt; requires both decrypted JSON files
make edit-private     # Edit private configuration interactively via SOPS
make edit-credentials # Edit runtime credentials interactively via SOPS
make clean            # Remove decrypted files and temporary artifacts directly under secrets/
```

Prefer `make edit-private` or `make edit-credentials` for changes. Interactive
SOPS edits replace ciphertext only after successful encryption. For a manual
edit, start with `make decrypt`, then run `make encrypt` before `make clean`.
`make decrypt-private` is for inspection only: it does not produce the credentials
JSON that `make encrypt` also needs.

If you already edited `secrets/private.dec.json` after `make decrypt-private`,
leave it in place and run `make edit-private`. In the SOPS editor, use the local
file to merge your changes without creating another plaintext copy. Avoid editor
swap files, backups, or persistent history. Run `make clean` only after SOPS
successfully saves the changes to ciphertext.

`make build`, `make switch`, `make bootstrap`, and `make encrypt-gpg` decrypt private
configuration for the duration of the command. They refuse to run while
`secrets/private.dec.json` exists. Clean up after manual inspection before using
these targets.

After an interruption such as `SIGKILL`, first verify that the secrets manager,
the editor, and all supervised processes from that operation have stopped. If
`secrets/.secrets.lock` remains, remove it with `rmdir secrets/.secrets.lock` only
after confirming it is the stale, empty lock directory. Preserve any edits as
described above before running `make clean`.
Check the interrupted process's temporary directory (such as `$TMPDIR` or `/tmp`)
and remove only the leftover `sops-editor-*` workspace from that edit.
`make clean` does not inspect that directory.

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
make encrypt-gpg      # Export from a trusted machine; then commit the bundle
```

Export requires `gpg`, `age`, `age-keygen`, and `tar` on `PATH`. The local GPG
keyring must contain the selected secret key and a usable encryption subkey.
`make encrypt-gpg` uses `jq` to read `identity.gpg.fingerprint` from the transient
private configuration. If no fingerprint is read, it uses Git's `user.signingkey`.
To select a key explicitly without decrypting the SOPS configuration, run
`./scripts/encrypt-gpg-bundle.sh <fingerprint-or-keyid>` from the checkout.
Verify that the selected key's full primary fingerprint matches the configured
`identity.gpg.fingerprint` before exporting, including when you pass an explicit
key selector or use the `user.signingkey` fallback.

The Home Manager generation retains the encrypted bundle if it is present, GPG bootstrap is enabled, and the fingerprint is not a placeholder.
After committing an added or replaced bundle, run `make switch` to activate it.

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
nix flake check --no-build  # Evaluate flake outputs without building the checks
nix flake check             # Evaluate and build checks for the current platform
```

Both commands use placeholder private configuration by default and require no
decryption. Use `make build` to build Home Manager with your real private configuration.

The examples below target an `x86_64-linux` builder. These checks use disposable
secrets and do not activate your environment, download models, or run GPU inference.
Use your system's check outputs on other platforms.

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
