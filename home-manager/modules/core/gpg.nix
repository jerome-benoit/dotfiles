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

  bundlePath = ../../../secrets/gpg/keypair.tar.gz.age;
  # Retain only the encrypted bundle in the activation closure.
  bundle = if builtins.pathExists bundlePath then "${bundlePath}" else "";
  ageIdentity = config.sops.age.keyFile;
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
        BUNDLE=${lib.escapeShellArg bundle}

        [[ -r "${ageIdentity}" ]] || exit 0
        [[ -r "$BUNDLE" ]] || {
          echo "[gpg] secrets/gpg/keypair.tar.gz.age missing from the flake; run 'make encrypt-gpg' and add the bundle to Git" >&2
          exit 0
        }

        EXPECTED=$("$SHA256" "$BUNDLE" | "$CUT" -d' ' -f1)
        ACTUAL=
        [[ -r "${stamp}" ]] && ACTUAL=$(<"${stamp}")

        if [[ "$ACTUAL" == "$EXPECTED" ]] \
           && "$GPG" --batch --list-secret-keys "${fingerprint}" >/dev/null 2>&1; then
          exit 0
        fi

        if [[ -n "''${DRY_RUN_CMD:-}" ]]; then
          echo "[gpg] bundle drift or key absent; would (re)import ${fingerprint}" >&2
          exit 0
        fi

        TMP=$(mktemp -d 2>/dev/null || mktemp -d -t gpg-bootstrap)
        trap 'rm -rf "$TMP"' EXIT INT TERM HUP

        run "$AGE" -d -i "${ageIdentity}" -o "$TMP/bundle.tar.gz" "$BUNDLE"
        run "$TAR" --use-compress-program="$GZIP" -xf "$TMP/bundle.tar.gz" -C "$TMP"
        run "$GPG" --batch --pinentry-mode loopback \
          --passphrase-file "$TMP/gpg-passphrase.txt" \
          --import "$TMP/gpg-secret.asc"
        echo "${fingerprint}:6:" | run "$GPG" --batch --import-ownertrust

        "$GPG" --batch --list-secret-keys --with-colons "${fingerprint}" 2>/dev/null \
          | "$AWK" -F: '$1 == "fpr" { print $10; exit }' \
          | grep -qi "^${fingerprint}$" \
          || { echo "[gpg] imported key not found or fingerprint mismatch (expected ${fingerprint})" >&2; exit 1; }

        mkdir -p "$(dirname "${stamp}")"
        printf '%s\n' "$EXPECTED" > "${stamp}.tmp" && mv "${stamp}.tmp" "${stamp}"
        echo "[gpg] ${fingerprint} imported"
      )
    '';
  };
}
