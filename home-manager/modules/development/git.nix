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
          core = {
            pager = "delta";
            attributesfile = "~/.gitattributes";
            commitGraph = true;
            untrackedCache = true;
            fsmonitor = true;
          };
          feature = {
            manyFiles = true;
          };
          user = {
            name = config.modules.core.constants.username;
            email = lib.mkDefault config.modules.core.constants.email;
            signingKey = lib.mkDefault config.modules.core.constants.gpg.keyId;
          };
          commit = {
            gpgSign = true;
            signOff = true;
            verbose = true;
          };
          push = {
            default = "current";
            autoSetupRemote = true;
            followTags = true;
            useForceIfIncludes = true;
          };
          color = {
            diff = "auto";
            status = "auto";
            branch = "auto";
            ui = "auto";
            interactive = "auto";
          };
          merge = {
            conflictStyle = "diff3";
            tool = lib.mkDefault "meld";
          };
          "merge.mergiraf" = {
            name = "mergiraf";
            driver = "mergiraf merge --git %O %A %B -s %S -x %X -y %Y -p %P -l %L --timeout 5000";
          };
          mergetool = {
            meld = {
              useAutoMerge = "auto";
            };
          };
          pull = {
            rebase = true;
          };
          fetch = {
            all = true;
            prune = true;
            pruneTags = true;
            fsckobjects = true;
          };
          transfer = {
            fsckobjects = true;
          };
          receive = {
            fsckobjects = true;
          };
          init = {
            defaultBranch = "main";
          };
          rebase = {
            autoSquash = true;
            autoStash = true;
            updateRefs = true;
          };
          rerere = {
            enabled = true;
            autoUpdate = true;
          };
          branch = {
            sort = "-committerdate";
          };
          column = {
            ui = "auto";
          };
          tag = {
            sort = "version:refname";
          };
          help = {
            autocorrect = "prompt";
          };
          diff = {
            algorithm = "histogram";
            colorMoved = "default";
            colorMovedWs = "allow-indentation-change";
            mnemonicPrefix = true;
            renames = true;
          };
          interactive = {
            diffFilter = "delta --color-only";
          };
          delta = {
            navigate = true;
            line-numbers = true;
            hyperlinks = true;
            hyperlinks-file-link-format = "file://{path}#{line}";
            dark = true;
            syntax-theme = "Visual Studio Dark+";
            true-color = "always";
            max-line-length = 0;
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

    home.file.".gitattributes".text = ''
      * merge=mergiraf
    '';
  };
}
