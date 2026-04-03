{ self, pkgs }:

pkgs.runCommand "check-statix" { nativeBuildInputs = [ pkgs.statix ]; } ''
  cd ${self} && statix check .
  echo "OK" > $out
''
