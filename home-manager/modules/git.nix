{ pkgs, lib, ... }:

let
  systemGit = pkgs.runCommand "git-system" { } "mkdir -p $out";
in
{
  programs.git = lib.mkMerge [
    {
      enable = true;
      package = systemGit;

      settings = {
        user = {
          name = "Jérôme Benoit";
          email = "jerome.benoit@piment-noir.org";
          signingKey = "27B535D3";
        };
        commit = {
          gpgSign = true;
        };
        core = {
          pager = "delta";
        };
        push = {
          default = "current";
        };
        color = {
          diff = "auto";
          status = "auto";
          branch = "auto";
          ui = "auto";
          interactive = "auto";
        };
        interactive = {
          diffFilter = "delta --color-only";
        };
        merge = {
          conflictStyle = "zdiff3";
          tool = "meld";
        };
        mergetool = {
          meld = {
            useAutoMerge = "auto";
          };
        };
        pull = {
          rebase = false;
        };
        delta = {
          navigate = true;
          "line-numbers" = true;
          hyperlinks = true;
          "hyperlinks-file-link-format" = "file://{path}#{line}";
        };
        init = {
          defaultBranch = "main";
        };
      };
    }
    (lib.mkIf pkgs.stdenv.isDarwin {
      settings = {
        credential.helper = "osxkeychain";
      };
    })
  ];
}
