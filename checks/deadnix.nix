{ self, pkgs }:

pkgs.runCommand "check-deadnix" { nativeBuildInputs = [ pkgs.deadnix ]; } ''
  deadnix --fail --no-lambda-pattern-names ${self}
  echo "OK" > $out
''
