{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.development.git;
  systemGit = pkgs.runCommand "git-system" { } "mkdir -p $out";
in
{
  options.modules.development.git = {
    enable = lib.mkEnableOption "git configuration";
  };

  config = lib.mkIf cfg.enable {
    programs.git = lib.mkMerge [
      {
        enable = true;
        package = systemGit;

        settings = {
          user = {
            name = config.modules.core.constants.username;
            email = lib.mkDefault config.modules.core.constants.email;
            signingKey = lib.mkDefault config.modules.core.constants.gpg.keyId;
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
  };
}
