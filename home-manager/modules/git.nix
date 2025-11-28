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
          email = lib.mkDefault "jerome.benoit@piment-noir.org";
          signingKey = lib.mkDefault "27B535D3";
        };
        commit = {
          gpgSign = true;
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
        merge = {
          conflictStyle = "zdiff3";
          tool = lib.mkDefault "meld";
        };
        mergetool = {
          meld = {
            useAutoMerge = "auto";
          };
        };
        pull = {
          rebase = true;
        };
        init = {
          defaultBranch = "main";
        };
        core = {
          pager = "delta";
        };
        interactive = {
          diffFilter = "delta --color-only";
        };
        delta = {
          navigate = true;
          line-numbers = true;
          hyperlinks = true;
          hyperlinks-file-link-format = "file://{path}#{line}";
        };
      };
    }
    (lib.mkIf pkgs.stdenv.isDarwin {
      settings = {
        merge = {
          tool = "opendiff";
        };
        credential = {
          helper = "osxkeychain";
        };
      };
    })
  ];
}
