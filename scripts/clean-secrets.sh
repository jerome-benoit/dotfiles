#!/bin/sh

set -eu
umask 077

root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
secrets_directory="$root/secrets"
lock_directory="$secrets_directory/.secrets.lock"

if ! mkdir -- "$lock_directory"; then
  echo "another secrets operation is active; remove stale lock $lock_directory only after verifying no operation is running" >&2
  exit 75
fi

cleanup_lock() {
  rmdir -- "$lock_directory" 2>/dev/null || true
}
trap cleanup_lock EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

rm -f -- \
  "$secrets_directory"/*.dec.* \
  "$secrets_directory"/*.tmp \
  "$secrets_directory"/*.tmp.*
if [ ! -e "$secrets_directory/.secrets-transaction.json" ]; then
  rm -f -- \
    "$secrets_directory"/*.backup.* \
    "$secrets_directory"/*.restore.*
fi
