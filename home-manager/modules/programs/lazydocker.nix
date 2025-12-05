{
  config,
  lib,
  ...
}:

let
  cfg = config.modules.programs.lazydocker;
in
{
  options.modules.programs.lazydocker = {
    enable = lib.mkEnableOption "lazydocker configuration";
  };

  config = lib.mkIf cfg.enable {
    programs.lazydocker = {
      enable = true;

      settings = {
        gui = {
          scrollHeight = 2;
          language = "auto";
          border = "rounded";
          theme = {
            activeBorderColor = [
              "yellow"
              "bold"
            ];
            inactiveBorderColor = [ "cyan" ];
            selectedLineBgColor = [ "blue" ];
            optionsTextColor = [ "blue" ];
          };
          returnImmediately = false;
          wrapMainPanel = true;
          sidePanelWidth = 0.333;
          showBottomLine = true;
          expandFocusedSidePanel = true;
          showAllContainers = true;
          screenMode = "normal";
          containerStatusHealthStyle = "long";
        };

        logs = {
          timestamps = false;
          since = "60m";
          tail = "300";
        };

        commandTemplates = {
          dockerCompose = "docker compose";
        };

        customCommands = {
          containers = [
            {
              name = "bash";
              attach = true;
              command = "docker exec -it {{ .Container.ID }} bash";
            }
            {
              name = "sh";
              attach = true;
              command = "docker exec -it {{ .Container.ID }} sh";
            }
          ];
        };
      };
    };
  };
}
