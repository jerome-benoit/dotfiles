{ self, pkgs }:

pkgs.runCommand "check-deadnix" { nativeBuildInputs = [ pkgs.deadnix ]; } ''
  deadnix --fail ${self}
  echo "OK" > $out
''
