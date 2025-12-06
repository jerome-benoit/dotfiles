{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.development.lazygit;
  theme = config.modules.themes.tokyoNight;
in
{
  options.modules.development.lazygit = {
    enable = lib.mkEnableOption "lazygit configuration";
  };

  config = lib.mkIf cfg.enable {
    programs.lazygit = {
      enable = true;

      settings = {
        gui = {
          # Tokyo Night theme colors
          theme = {
            activeBorderColor = [
              theme.blue
              "bold"
            ];
            inactiveBorderColor = [ theme.comment ];
            selectedLineBgColor = [ theme.brightBlack ];
            cherryPickedCommitBgColor = [ theme.cyan ];
            cherryPickedCommitFgColor = [ theme.blue ];
            markedBaseCommitBgColor = [ theme.yellow ];
            markedBaseCommitFgColor = [ theme.blue ];
            unstagedChangesColor = [ theme.red ];
            defaultFgColor = [ theme.fg ];
          };

          # UI configuration (aligned with lazydocker)
          border = "rounded";
          nerdFontsVersion = "3";
          showFileIcons = true;
          scrollHeight = 2;
          mouseEvents = true;
          skipDiscardChangeWarning = false;
          showFileTree = true;
          showCommandLog = true;
          showBottomLine = true;

          commitLength = {
            show = true;
          };

          filterMode = "fuzzy";
        };

        git = {
          # Delta pager configuration (aligned with git.nix)
          paging = {
            colorArg = "always";
            pager = "delta --dark --paging=never --line-numbers --navigate --hyperlinks";
          };

          # Commit configuration
          commit = {
            signOff = false; # GPG signing is handled by git config
            autoWrapCommitMessage = true;
            autoWrapWidth = 72;
          };

          # Merge configuration
          merging = {
            manualCommit = false;
            args = "";
          };

          # Main branches (aligned with git.nix)
          mainBranches = [
            "master"
            "main"
          ];

          # Auto-fetch and auto-refresh
          autoFetch = true;
          autoRefresh = true;
          autoForwardBranches = "onlyMainBranches";
          fetchAll = true;
          autoStageResolvedConflicts = true;

          # Log configuration
          log = {
            order = "topo-order";
            showGraph = "always";
            showWholeGraph = false;
          };

          # Branch sorting
          localBranchSortOrder = "recency";

          # Diff configuration
          diffContextSize = 3;
          renameSimilarityThreshold = 50;

          # Parse emojis in commit messages
          parseEmoji = true;
        };

        # Refresh intervals
        refresher = {
          refreshInterval = 10;
          fetchInterval = 60;
        };

        # Update settings
        update = {
          method = "prompt";
          days = 14;
        };
      };
    };
  };
}
