{
  self,
  pkgs,
  formatter ? pkgs.nixfmt,
}:

let
  findNixFiles = "${pkgs.findutils}/bin/find . -name '*.nix' -type f -not -path './result/*'";

  findAndFormatScript = checkMode: ''
    ${findNixFiles} | while IFS= read -r file; do
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
      check = pkgs.runCommandLocal checkName { nativeBuildInputs = [ formatter ]; } ''
        set -o pipefail
        cd ${self}
        ${findAndFormatScript true}
        touch $out
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
