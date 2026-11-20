{ pkgs }:
# Keep the source-independent state consumers beside the helper in one closure.
pkgs.runCommand "strata-workspace" { } ''
  mkdir -p "$out"
  cp ${./strata-workspace.py} "$out/strata-workspace.py"
  cp -R ${./strata-managed} "$out/strata-managed"
''
