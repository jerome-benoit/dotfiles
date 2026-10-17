{ pkgs, package }:
pkgs.runCommand "check-caveman-runtime"
  {
    nativeBuildInputs = [ pkgs.python3 ];
    __darwinAllowLocalNetworking = true;
  }
  ''
    python3 ${./caveman.py} ${package} ${pkgs.lib.getExe pkgs.git} ${pkgs.lib.getExe pkgs.nodejs_22}
    touch "$out"
  ''
