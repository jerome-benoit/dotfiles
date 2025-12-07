{ config, lib, ... }:

let
  emailRegex = "^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}$";
in
{
  options.modules.core.constants = {
    username = lib.mkOption {
      type = lib.types.str;
      default = "Jérôme Benoit";
      description = "The user's full name";
      readOnly = true;
    };
    email = lib.mkOption {
      type = lib.types.strMatching emailRegex;
      default = "jerome.benoit@piment-noir.org";
      description = "The user's email address";
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
    timezone = lib.mkOption {
      type = lib.types.str;
      default = "Europe/Paris";
      description = "Default timezone for programs";
    };
  };
}
