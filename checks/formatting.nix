{ self, pkgs }:

pkgs.runCommand "check-nix-formatting"
  {
    nativeBuildInputs = [ pkgs.nixfmt-rfc-style ];
  }
  ''
    cd ${self}
    files=$(${pkgs.git}/bin/git ls-files '*.nix' 2>/dev/null || find . -name '*.nix' -type f)
    for file in $files; do
      [ -f "$file" ] && ${pkgs.nixfmt-rfc-style}/bin/nixfmt --check "$file" || {
        echo "ERROR: $file not formatted. Run 'nix fmt'" >&2
        exit 1
      }
    done
    echo "OK" > $out
  ''
