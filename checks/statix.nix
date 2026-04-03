{ self, pkgs }:

pkgs.runCommand "check-statix" { nativeBuildInputs = [ pkgs.statix ]; } ''
  statix check ${self}
  echo "OK" > $out
''
