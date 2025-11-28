{ lib, ... }:
{
  options.modules.core.constants = {
    username = lib.mkOption {
      type = lib.types.str;
      default = "Jérôme Benoit";
      description = "The user's full name";
    };
    email = lib.mkOption {
      type = lib.types.str;
      default = "jerome.benoit@piment-noir.org";
      description = "The user's email address";
    };
    workEmail = lib.mkOption {
      type = lib.types.str;
      default = "jerome.benoit@sap.com";
      description = "The user's work email address";
    };
    gpg = {
      keyId = lib.mkOption {
        type = lib.types.str;
        default = "27B535D3";
        description = "The GPG key ID";
      };
      fingerprint = lib.mkOption {
        type = lib.types.str;
        default = "B799 BBF6 8EC8 911B B8D7 CDBC C3B1 92C6 27B5 35D3";
        description = "The GPG key fingerprint";
      };
    };
  };
}
