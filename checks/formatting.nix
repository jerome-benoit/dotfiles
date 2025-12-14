{
  self,
  pkgs,
  formatter ? pkgs.nixfmt-rfc-style,
}:

let
  findAndFormatScript = checkMode: ''
    files=$(${pkgs.git}/bin/git ls-files '*.nix' 2>/dev/null || find . -name '*.nix' -type f)
    for file in $files; do
      ${
        if checkMode then
          ''
            [ -f "$file" ] && ${formatter}/bin/nixfmt --check "$file" || {
              echo "ERROR: $file not formatted. Run 'nix fmt'" >&2
              exit 1
            }
          ''
        else
          ''[ -f "$file" ] && ${formatter}/bin/nixfmt "$file"''
      }
    done
  '';

  # Creates both check and formatter derivations
  mkCheckFormatter =
    {
      checkName ? "check-nix-formatting",
      formatterName ? "nix-fmt",
    }:
    {
      check = pkgs.runCommand checkName { nativeBuildInputs = [ formatter ]; } ''
        cd ${self}
        ${findAndFormatScript true}
        echo "OK" > $out
      '';

      formatter = pkgs.writeShellScriptBin formatterName ''
        set -euo pipefail
        [[ $# -eq 0 ]] && set -- .

        format_dir() {
          pushd "$1" > /dev/null
          ${findAndFormatScript false}
          popd > /dev/null
        }

        for arg in "$@"; do
          [[ -d "$arg" ]] && format_dir "$arg" && continue
          [[ -f "$arg" ]] && ${formatter}/bin/nixfmt "$arg" && continue
          echo "Error: $arg not found" >&2 && exit 1
        done
      '';
    };

  result = mkCheckFormatter { };

in
{
  inherit (result) check formatter;
  inherit mkCheckFormatter;
}
