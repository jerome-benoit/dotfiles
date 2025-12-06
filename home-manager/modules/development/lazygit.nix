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

          border = "rounded";
          showFileIcons = true;
          scrollHeight = 2;
          language = "auto";
          screenMode = "normal";
          sidePanelWidth = 0.3333;
          mouseEvents = true;
          skipDiscardChangeWarning = false;
          showFileTree = true;
          showCommandLog = true;
          showBottomLine = true;
          scrollPastBottom = true;
          scrollOffMargin = 2;
          commitHashLength = 8;
          showBranchCommitHash = false;
          showRandomTip = false;
          promptToReturnFromSubprocess = false;

          commitLength = {
            show = true;
          };

          filterMode = "substring";
        };

        git = {
          pagers = [
            {
              colorArg = "always";
              pager = "delta --paging=never --line-numbers --navigate --hyperlinks --hyperlinks-file-link-format='file://{path}#{line}' --dark --syntax-theme='Visual Studio Dark+' --true-color=always";
            }
          ];

          commit = {
            signOff = true;
            autoWrapCommitMessage = true;
            autoWrapWidth = 72;
            verbose = "default";
          };

          merging = {
            manualCommit = false;
            args = "";
          };

          mainBranches = [
            "master"
            "main"
          ];

          autoFetch = true;
          autoRefresh = true;
          autoForwardBranches = "onlyMainBranches";
          fetchAll = true;
          autoStageResolvedConflicts = true;

          log = {
            order = "topo-order";
            showGraph = "always";
            showWholeGraph = false;
          };

          localBranchSortOrder = "recency";

          diffContextSize = 3;
          renameSimilarityThreshold = 50;

          parseEmoji = true;
        };

        refresher = {
          refreshInterval = 10;
          fetchInterval = 60;
        };

        update = {
          method = "never";
          days = 14;
        };

        customCommands = [
          {
            key = "C";
            context = "files";
            description = "Conventional commit";
            prompts = [
              {
                type = "menu";
                key = "Type";
                title = "Select commit type";
                options = [
                  {
                    name = "feat";
                    description = "New feature";
                    value = "feat";
                  }
                  {
                    name = "fix";
                    description = "Bug fix";
                    value = "fix";
                  }
                  {
                    name = "docs";
                    description = "Documentation";
                    value = "docs";
                  }
                  {
                    name = "style";
                    description = "Formatting";
                    value = "style";
                  }
                  {
                    name = "refactor";
                    description = "Refactoring";
                    value = "refactor";
                  }
                  {
                    name = "perf";
                    description = "Performance";
                    value = "perf";
                  }
                  {
                    name = "test";
                    description = "Tests";
                    value = "test";
                  }
                  {
                    name = "build";
                    description = "Build";
                    value = "build";
                  }
                  {
                    name = "ci";
                    description = "CI/CD";
                    value = "ci";
                  }
                  {
                    name = "chore";
                    description = "Chores";
                    value = "chore";
                  }
                  {
                    name = "revert";
                    description = "Revert";
                    value = "revert";
                  }
                ];
              }
              {
                type = "input";
                title = "Scope (optional)";
                key = "Scope";
                initialValue = "";
              }
              {
                type = "input";
                title = "Description";
                key = "Message";
                initialValue = "";
              }
              {
                type = "menu";
                title = "Breaking change?";
                key = "Breaking";
                options = [
                  {
                    name = "No";
                    value = "";
                  }
                  {
                    name = "Yes";
                    value = "true";
                  }
                ];
              }
              {
                type = "input";
                title = "Body (optional)";
                key = "Body";
                initialValue = "";
              }
            ];
            command = ''git commit -m "{{.Form.Type}}{{if .Form.Scope}}({{.Form.Scope}}){{end}}{{if .Form.Breaking}}!{{end}}: {{.Form.Message}}"{{if .Form.Body}} -m "{{.Form.Body}}"{{end}}{{if and .Form.Breaking .Form.Body}} -m "BREAKING CHANGE: {{.Form.Body}}"{{end}}'';
            loadingText = "Committing...";
            output = "terminal";
          }
        ];
      };
    };
  };
}
