{ self, pkgs }:

pkgs.runCommandLocal "check-deadnix" { nativeBuildInputs = [ pkgs.deadnix ]; } ''
  deadnix --fail --no-lambda-pattern-names ${self}
  touch $out
''
