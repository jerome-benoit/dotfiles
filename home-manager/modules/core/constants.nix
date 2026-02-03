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
      type = lib.types.int;
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
  };
}
