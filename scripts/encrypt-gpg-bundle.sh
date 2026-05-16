#!/usr/bin/env bash
# (Re)create the age-encrypted GPG keypair bundle.
# Bundle: subkeys + passphrase, encrypted to ~/.config/sops/age/keys.txt recipient.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

AGE_KEY="${AGE_KEY:-$HOME/.config/sops/age/keys.txt}"
[ -r "$AGE_KEY" ] || { echo "missing $AGE_KEY (the project's age identity)" >&2; exit 1; }

FP="${1:-}"
if [ -z "$FP" ] && [ -f secrets/personal.dec.json ]; then
  FP=$(jq -r '.identity.gpg.fingerprint // empty' secrets/personal.dec.json 2>/dev/null || true)
fi
if [ -z "$FP" ]; then
  FP=$(git config --get user.signingkey 2>/dev/null || true)
fi
if [ -z "$FP" ]; then
  echo "Usage: $0 <fingerprint-or-keyid>" >&2
  echo "  or run 'make decrypt-personal' first, or set git config user.signingkey." >&2
  exit 1
fi

command -v age >/dev/null || { echo "age not in PATH" >&2; exit 1; }
command -v age-keygen >/dev/null || { echo "age-keygen not in PATH" >&2; exit 1; }
command -v gpg >/dev/null || { echo "gpg not in PATH" >&2; exit 1; }
command -v tar >/dev/null || { echo "tar not in PATH" >&2; exit 1; }
gpg --list-secret-keys "$FP" >/dev/null 2>&1 \
  || { echo "no secret key for $FP in local keyring" >&2; exit 1; }

if [ -e secrets/gpg/keypair.tar.gz.age ]; then
  gpg --list-secret-keys "$FP" >&2
  printf 'Bundle exists; overwrite with the keys above? [y/N] ' >&2
  read -r REPLY
  case "$REPLY" in
    [yY]) ;;
    *) echo "Aborted." >&2; exit 1 ;;
  esac
fi

RECIPIENT=$(age-keygen -y "$AGE_KEY" | head -n1)

printf 'GPG passphrase for %s (empty if key has none): ' "$FP" >&2
read -rs PASS
echo >&2

TMP=$(mktemp -d 2>/dev/null || mktemp -d -t gpg-encrypt)
trap 'rm -rf "$TMP"' EXIT INT TERM HUP

printf '%s' "$PASS" | gpg --batch --pinentry-mode loopback --passphrase-fd 0 \
  --export-secret-subkeys --armor "$FP" > "$TMP/gpg-secret.asc"
printf '%s' "$PASS" > "$TMP/gpg-passphrase.txt"

mkdir -p "$TMP/test-keyring"
chmod 700 "$TMP/test-keyring"
GNUPGHOME="$TMP/test-keyring" gpg --batch --pinentry-mode loopback \
  --passphrase-file "$TMP/gpg-passphrase.txt" \
  --import "$TMP/gpg-secret.asc" 2>/dev/null \
  || { echo "Bundle import test failed" >&2; exit 1; }

echo validate | GNUPGHOME="$TMP/test-keyring" gpg --batch --pinentry-mode loopback \
  --passphrase-file "$TMP/gpg-passphrase.txt" \
  --sign --output /dev/null 2>/dev/null \
  || { echo "Bundle passphrase test failed: passphrase doesn't unlock the imported subkeys" >&2; exit 1; }

tar czf "$TMP/bundle.tar.gz" -C "$TMP" \
  gpg-secret.asc gpg-passphrase.txt
mkdir -p secrets/gpg
age -r "$RECIPIENT" \
    -o secrets/gpg/keypair.tar.gz.age \
    "$TMP/bundle.tar.gz"
chmod 0644 secrets/gpg/keypair.tar.gz.age

SIZE=$(wc -c < secrets/gpg/keypair.tar.gz.age | tr -d ' ')
age -d -i "$AGE_KEY" secrets/gpg/keypair.tar.gz.age | tar tz >/dev/null
echo "✓ secrets/gpg/keypair.tar.gz.age written and verified (${SIZE} bytes)"
echo "  → git add secrets/gpg/keypair.tar.gz.age && git commit"

