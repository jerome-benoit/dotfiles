{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.core.gpg;
  constants = config.modules.core.constants;
  fingerprint = lib.replaceStrings [ " " ":" ] [ "" "" ] constants.identity.gpg.fingerprint;

  # Placeholder from secrets/default.nix.
  isPlaceholder = fingerprint == "0000000000000000000000000000000000000000";

  bundle = "${toString ../../..}/secrets/gpg/keypair.tar.gz.age";
  ageIdentity = "${config.home.homeDirectory}/.config/sops/age/keys.txt";
  stamp = "${config.xdg.stateHome}/gpg-bootstrap/bundle.sha256";
in
{
  options.modules.core.gpg = {
    enable = lib.mkEnableOption "GPG keypair bootstrap from age-encrypted bundle";
  };

  config = lib.mkIf (cfg.enable && !isPlaceholder) {
    home.activation.importGpgKeypair = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
      (
        GPG=${lib.getExe' pkgs.gnupg "gpg"}
        AGE=${lib.getExe pkgs.age}
        TAR=${lib.getExe' pkgs.gnutar "tar"}
        GZIP=${lib.getExe' pkgs.gzip "gzip"}
        SHA256=${lib.getExe' pkgs.coreutils "sha256sum"}
        CUT=${lib.getExe' pkgs.coreutils "cut"}
        AWK=${lib.getExe' pkgs.gawk "awk"}

        [[ -r "${ageIdentity}" ]] || exit 0
        [[ -r "${bundle}" ]] || {
          echo "[gpg] ${bundle} not found; run 'make encrypt-gpg' to create it" >&2
          exit 0
        }

        EXPECTED=$("$SHA256" "${bundle}" | "$CUT" -d' ' -f1)
        # Idempotent: skip if the key is in the keyring; refresh the stamp on drift.
        if "$GPG" --batch --list-secret-keys "${fingerprint}" >/dev/null 2>&1; then
          if [[ ! -r "${stamp}" || "$(<"${stamp}")" != "$EXPECTED" ]] \
             && [[ -z "''${DRY_RUN_CMD:-}" ]]; then
            mkdir -p "$(dirname "${stamp}")"
            printf '%s\n' "$EXPECTED" > "${stamp}"
          fi
          exit 0
        fi

        TMP=$(mktemp -d 2>/dev/null || mktemp -d -t gpg-bootstrap)
        trap 'rm -rf "$TMP"' EXIT INT TERM HUP

        run "$AGE" -d -i "${ageIdentity}" -o "$TMP/bundle.tar.gz" "${bundle}"
        run "$TAR" --use-compress-program="$GZIP" -xf "$TMP/bundle.tar.gz" -C "$TMP"
        run "$GPG" --batch --pinentry-mode loopback \
          --passphrase-file "$TMP/gpg-passphrase.txt" \
          --import "$TMP/gpg-secret.asc"
        echo "${fingerprint}:6:" | run "$GPG" --batch --import-ownertrust

        if [[ -z "''${DRY_RUN_CMD:-}" ]]; then
          "$GPG" --batch --list-secret-keys --with-colons "${fingerprint}" 2>/dev/null \
            | "$AWK" -F: '$1 == "fpr" { print $10; exit }' \
            | grep -qi "^${fingerprint}$" \
            || { echo "[gpg] imported key not found or fingerprint mismatch (expected ${fingerprint})" >&2; exit 1; }

          mkdir -p "$(dirname "${stamp}")"
          printf '%s\n' "$EXPECTED" > "${stamp}"
          echo "[gpg] ${fingerprint} imported"
        fi
      )
    '';
  };
}
