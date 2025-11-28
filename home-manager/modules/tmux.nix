{ pkgs, lib, ... }:

let
  systemTmux = pkgs.runCommand "tmux-system" { meta.mainProgram = "tmux"; } "mkdir -p $out";
in
{
  programs.tmux = {
    enable = true;
    package = if pkgs.stdenv.isDarwin then pkgs.tmux else systemTmux;
    mouse = true;
    baseIndex = 1;
    terminal = "screen-256color";
    plugins = with pkgs.tmuxPlugins; [
      sensible
    ];
  };
}
