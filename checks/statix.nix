{ self, pkgs }:

pkgs.runCommandLocal "check-statix" { nativeBuildInputs = [ pkgs.statix ]; } ''
  statix check --config ${self}/statix.toml ${self}
  touch $out
''
