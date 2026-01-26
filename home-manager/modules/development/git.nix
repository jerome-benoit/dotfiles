{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.development.git;
  constants = config.modules.core.constants;
  mkSystemPackage = config.modules.core.lib.mkSystemPackage;
in
{
  options.modules.development.git = {
    enable = lib.mkEnableOption "git configuration";
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = constants.gpg.keyId != "";
        message = "git: GPG key ID must be configured for commit signing";
      }
    ];

    programs.git = lib.mkMerge [
      {
        enable = true;
        package = mkSystemPackage "git" { };

        settings = {
          core = {
            pager = "delta";
            attributesfile = "${config.xdg.configHome}/git/attributes";
            commitGraph = true;
            untrackedCache = true;
            fsmonitor = true;
          };
          feature = {
            manyFiles = true;
          };
          user = {
            name = lib.mkDefault constants.username;
            email = lib.mkDefault constants.email;
            signingKey = lib.mkDefault constants.gpg.keyId;
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
            driver = "mergiraf merge --git %O %A %B -s %S -x %X -y %Y -p %P -l %L --timeout 30000";
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
          log = {
            abbrevCommit = true;
            follow = true;
          };
          diff = {
            algorithm = "histogram";
            colorMoved = "default";
            colorMovedWs = "allow-indentation-change";
            mnemonicPrefix = true;
            renames = true;
          };
          stash = {
            showPatch = true;
          };
          interactive = {
            diffFilter = "delta --color-only";
          };
          delta = {
            navigate = true;
            line-numbers = true;
            side-by-side = false;
            hyperlinks = true;
            hyperlinks-file-link-format = "file://{path}#{line}";
            dark = true;
            syntax-theme = "Visual Studio Dark+";
            true-color = "always";
            max-line-length = 0;
            features = "decorations";
            whitespace-error-style = "22 reverse";
            file-style = "bold #DCDCAA ul";
            file-decoration-style = "none";
            hunk-header-style = "file line-number syntax";
            hunk-header-decoration-style = "#569cd6 box";
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

    xdg.configFile."git/attributes".text = ''
      * merge=mergiraf
    '';
  };
}
