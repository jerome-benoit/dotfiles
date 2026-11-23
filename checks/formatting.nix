{
  self,
  pkgs,
  formatter ? pkgs.nixfmt,
}:

let
  findNixFiles = "${pkgs.lib.getExe pkgs.findutils} . -name '*.nix' -type f -not -path './result/*'";

  findAndFormatScript = checkMode: ''
    ${findNixFiles} | while IFS= read -r file; do
      ${
        if checkMode then
          ''
            [ -f "$file" ] && ${pkgs.lib.getExe formatter} --check "$file" || {
              echo "ERROR: $file not formatted. Run 'nix fmt'" >&2
              exit 1
            }
          ''
        else
          ''[ -f "$file" ] && ${pkgs.lib.getExe formatter} "$file"''
      }
    done
  '';

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
          if [[ -d "$arg" ]]; then
            format_dir "$arg"
          elif [[ -f "$arg" ]]; then
            ${pkgs.lib.getExe formatter} "$arg"
          else
            echo "Error: no file or directory at $arg" >&2
            exit 1
          fi
        done
      '';
    };

  result = mkCheckFormatter { };

in
{
  inherit (result) check formatter;
  inherit mkCheckFormatter;
}
