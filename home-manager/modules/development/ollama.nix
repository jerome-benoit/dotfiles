{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.modules.development.ollama;
  gpu = config.modules.core.gpu;
  ollamaPackage =
    if gpu.acceleration == "cuda" then
      pkgs.ollama-cuda.override {
        cudaPackages = gpu.cudaPackages;
      }
    else if gpu.acceleration == "rocm" then
      pkgs.ollama-rocm.override {
        rocmGpuTargets = gpu.rocmTargets;
      }
    else if gpu.acceleration == "vulkan" then
      pkgs.ollama-vulkan
    else
      pkgs.ollama;
in
{
  options.modules.development.ollama = {
    enable = lib.mkEnableOption "Ollama configuration";
    enableService = lib.mkEnableOption "Ollama Linux user service";
  };

  config = lib.mkIf cfg.enable (
    lib.mkMerge [
      (lib.mkIf pkgs.stdenv.hostPlatform.isLinux {
        services.ollama = {
          enable = cfg.enableService;
          package = lib.mkDefault ollamaPackage;
          environmentVariables = lib.mkIf config.services.ollama.enable {
            OLLAMA_CONTEXT_LENGTH = lib.mkDefault (toString (128 * 1024));
            OLLAMA_FLASH_ATTENTION = lib.mkDefault "1";
            OLLAMA_KV_CACHE_TYPE = lib.mkDefault "q8_0";
          };
        };

        home.packages = lib.optional (!config.services.ollama.enable) config.services.ollama.package;

        systemd.user.services = lib.mkIf config.services.ollama.enable {
          ollama.Service = {
            Type = "exec";
            Restart = "on-failure";
            RestartSec = 3;
          };
        };
      })
      (lib.mkIf pkgs.stdenv.hostPlatform.isDarwin {
        home.file.".Brewfile".text = lib.mkAfter ''
          brew "ollama", restart_service: true
        '';
      })
    ]
  );
}
