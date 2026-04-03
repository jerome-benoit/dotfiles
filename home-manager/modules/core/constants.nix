{
  config,
  lib,
  constants,
  ...
}:

let
  emailRegex = "^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}$";
in
{
  options.modules.core.constants = {
    systems = lib.mkOption {
      type = lib.types.attrsOf (
        lib.types.submodule {
          options = {
            name = lib.mkOption {
              type = lib.types.str;
              description = "System name";
            };
            arch = lib.mkOption {
              type = lib.types.str;
              description = "System architecture";
            };
          };
        }
      );
      default = constants.systems;
      description = "Systems";
      readOnly = true;
    };
    profiles = lib.mkOption {
      type = lib.types.attrsOf lib.types.str;
      default = constants.profiles;
      description = "Profiles";
      readOnly = true;
    };
    distros = lib.mkOption {
      type = lib.types.attrsOf lib.types.str;
      default = constants.distros;
      description = "Supported GNU/Linux distributions";
      readOnly = true;
    };
    username = lib.mkOption {
      type = lib.types.str;
      default = "Jérôme Benoit";
      description = "The user's full name";
      readOnly = true;
    };
    primaryEmail = lib.mkOption {
      type = lib.types.strMatching emailRegex;
      default = "jerome.benoit@piment-noir.org";
      description = "The user's primary email address";
      readOnly = true;
    };
    secondaryEmail = lib.mkOption {
      type = lib.types.strMatching emailRegex;
      default = "jbenoit100@gmail.com";
      description = "The user's secondary email address";
      readOnly = true;
    };
    workEmail = lib.mkOption {
      type = lib.types.strMatching emailRegex;
      default = "jerome.benoit@sap.com";
      description = "The user's work email address";
      readOnly = true;
    };
    gpg = {
      keyId = lib.mkOption {
        type = lib.types.strMatching "^([0-9A-Fa-f]{8}|[0-9A-Fa-f]{16})$";
        default = "27B535D3";
        description = "The user's GPG key ID";
        readOnly = true;
      };
      fingerprint = lib.mkOption {
        type = lib.types.strMatching "^([0-9A-Fa-f]{40}|[0-9A-Fa-f]{4}([ :]?[0-9A-Fa-f]{4}){9})$";
        default = "B799 BBF6 8EC8 911B B8D7 CDBC C3B1 92C6 27B5 35D3";
        description = "The user's GPG key fingerprint";
        readOnly = true;
      };
    };
    historySize = lib.mkOption {
      type = lib.types.ints.positive;
      default = 50000;
      description = "Default history size for shells and terminal emulators";
    };
    fontFamily = lib.mkOption {
      type = lib.types.str;
      default = "JetBrainsMono Nerd Font";
      description = "Default monospace font family for terminal emulators and editors";
      readOnly = true;
    };
    timezone = lib.mkOption {
      type = lib.types.str;
      default = "Europe/Paris";
      description = "Default timezone for programs";
    };
    hosts = lib.mkOption {
      type = lib.types.attrsOf lib.types.str;
      default = {
        rigel = "rigel";
        ns3108029 = "ns3108029.ip-54-37-87.eu";
      };
      description = "Hostnames";
      readOnly = true;
    };
    deltaConfig = lib.mkOption {
      type = lib.types.submodule {
        options = {
          navigate = lib.mkOption {
            type = lib.types.bool;
            description = "Navigate mode for jumping between diff sections";
          };
          line-numbers = lib.mkOption {
            type = lib.types.bool;
            description = "Line number display in diff output";
          };
          side-by-side = lib.mkOption {
            type = lib.types.bool;
            description = "Side-by-side diff layout";
          };
          hyperlinks = lib.mkOption {
            type = lib.types.bool;
            description = "OSC 8 hyperlinks in diff output";
          };
          hyperlinks-file-link-format = lib.mkOption {
            type = lib.types.str;
            description = "Format string for file hyperlinks (e.g. file://{path}#{line})";
          };
          dark = lib.mkOption {
            type = lib.types.bool;
            description = "Dark background mode";
          };
          syntax-theme = lib.mkOption {
            type = lib.types.str;
            description = "Syntax highlighting theme name";
          };
          true-color = lib.mkOption {
            type = lib.types.enum [
              "always"
              "never"
              "auto"
            ];
            description = "24-bit (true color) ANSI output mode";
          };
          max-line-length = lib.mkOption {
            type = lib.types.ints.unsigned;
            description = "Maximum line length before wrapping (0 = no limit)";
          };
          features = lib.mkOption {
            type = lib.types.str;
            description = "Delta feature name to enable";
          };
          whitespace-error-style = lib.mkOption {
            type = lib.types.str;
            description = "Whitespace error style";
          };
          file-style = lib.mkOption {
            type = lib.types.str;
            description = "File header style";
          };
          file-decoration-style = lib.mkOption {
            type = lib.types.str;
            description = "File header decoration style";
          };
          hunk-header-style = lib.mkOption {
            type = lib.types.str;
            description = "Hunk header style";
          };
          hunk-header-decoration-style = lib.mkOption {
            type = lib.types.str;
            description = "Hunk header decoration style";
          };
        };
      };
      default = {
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
      description = "Shared delta pager configuration";
      readOnly = true;
    };
    deltaConfigToCli = lib.mkOption {
      type = lib.types.functionTo lib.types.str;
      default =
        cfg:
        let
          boolFlag = name: value: lib.optional value "--${name}";
          strFlag = name: value: [ "--${name}='${value}'" ];
          intFlag = name: value: [ "--${name}=${toString value}" ];
          enumFlag = name: value: [ "--${name}=${value}" ];
        in
        lib.strings.concatStringsSep " " (
          lib.lists.flatten [
            "--paging=never"
            (boolFlag "navigate" cfg.navigate)
            (boolFlag "line-numbers" cfg.line-numbers)
            (boolFlag "side-by-side" cfg.side-by-side)
            (boolFlag "hyperlinks" cfg.hyperlinks)
            (strFlag "hyperlinks-file-link-format" cfg.hyperlinks-file-link-format)
            (boolFlag "dark" cfg.dark)
            (strFlag "syntax-theme" cfg.syntax-theme)
            (enumFlag "true-color" cfg.true-color)
            (intFlag "max-line-length" cfg.max-line-length)
            (strFlag "features" cfg.features)
            (strFlag "whitespace-error-style" cfg.whitespace-error-style)
            (strFlag "file-style" cfg.file-style)
            (strFlag "file-decoration-style" cfg.file-decoration-style)
            (strFlag "hunk-header-style" cfg.hunk-header-style)
            (strFlag "hunk-header-decoration-style" cfg.hunk-header-decoration-style)
          ]
        );
      description = "Function to convert deltaConfig to CLI flags string";
      readOnly = true;
    };
  };
}
