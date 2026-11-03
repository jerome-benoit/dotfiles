{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.development.ollama;
in
{
  options.modules.development.ollama = {
    enable = lib.mkEnableOption "Ollama user service";
  };

  config = lib.mkIf (cfg.enable && pkgs.stdenv.hostPlatform.isLinux) {
    services.ollama = {
      enable = true;
      environmentVariables = {
        OLLAMA_CONTEXT_LENGTH = lib.mkDefault (toString (128 * 1024));
        OLLAMA_FLASH_ATTENTION = lib.mkDefault "1";
        OLLAMA_KV_CACHE_TYPE = lib.mkDefault "q8_0";
      };
    };

    systemd.user.services.ollama.Service = {
      Type = "exec";
      Restart = "on-failure";
      RestartSec = 3;
    };
  };
}
