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

### GPU acceleration

Use `make bootstrap`, `make build`, `make switch`, or the `hm` commands for host-aware builds. These entry points collect a fresh GPU snapshot through `scripts/gpu-env.sh` and enable impure evaluation. Direct host-aware Nix commands must use the same wrapper and `--impure`.

On Linux, CUDA requires a successful compute-capability probe. The newest usable package scope is selected by the conservative driver floor and all detected/configured GPU targets. Final scope targets and their combined platform constraints are validated, including scopes customized by overlays. Stock scopes are retained when suitable; supported legacy targets use a coherent custom scope. If neither scope is usable, selection tries an older compatible toolkit; failed capability assertions in a candidate's metadata also reject that candidate. AMD uses detected KFD targets supported by the pinned ROCm packages; Vulkan is the fallback when a render node is present. Apple Silicon keeps native package defaults.

On non-NixOS Linux, follow Home Manager's `sudo non-nixos-gpu-setup` instruction when `/run/opengl-driver` needs updating. NVIDIA userspace libraries must match the running kernel module. After an OS driver update, ensure the module and NVML agree before rebuilding; a failed probe disables CUDA rather than assuming compatibility. Home Manager does not update the privileged driver link automatically. NixOS manages its own driver link.

Pure Linux evaluation does not detect host GPUs. The `gpu` flake check exercises native-file snapshots and deterministic CUDA/ROCm/Vulkan selection scenarios without GPU hardware; it is not a GPU inference test.

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
