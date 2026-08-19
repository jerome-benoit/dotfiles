{
  config,
  lib,
  pkgs,
  inputs,
  ...
}:
let
  cfg = config.modules.core.packages;
  gpu = config.modules.core.gpu;
  acceleration = gpu.acceleration;
  openclawEnabled = config.modules.development.openclaw.enable or false;
  openclawTools = inputs.nix-openclaw-tools.packages.${pkgs.stdenv.hostPlatform.system};
  isDesktop = config.modules.core.profile.name == config.modules.core.constants.profiles.desktop;
  isServer = config.modules.core.profile.name == config.modules.core.constants.profiles.server;
  isDarwin = pkgs.stdenv.hostPlatform.isDarwin;
  ollama =
    if acceleration == "cuda" then
      let
        cudaPackages = gpu.cudaPackages;
        cudaNvcc = cudaPackages.cuda_nvcc.__spliced.buildHost or cudaPackages.cuda_nvcc;
      in
      (pkgs.ollama-cuda.override { inherit cudaPackages; }).overrideAttrs (previousAttrs: {
        # Ollama's CUDA sub-build needs the nvcc root with CMake 4.2+ (NixOS/nixpkgs#545092).
        preBuild = ''
          export CUDAToolkit_ROOT="${lib.getBin cudaNvcc}"
        ''
        + (previousAttrs.preBuild or "");
      })
    else if acceleration == "rocm" then
      pkgs.ollama-rocm.override {
        rocmGpuTargets = gpu.rocmTargets;
      }
    else if acceleration == "vulkan" then
      pkgs.ollama-vulkan
    else
      pkgs.ollama;
  llamaCpp =
    if acceleration == "cuda" then
      pkgs.llama-cpp.override {
        cudaSupport = true;
        cudaPackages = gpu.cudaPackages;
      }
    else if acceleration == "rocm" then
      pkgs.llama-cpp.override {
        rocmSupport = true;
        rocmGpuTargets = gpu.rocmTargets;
      }
    else if acceleration == "vulkan" then
      pkgs.llama-cpp.override {
        vulkanSupport = true;
      }
    else
      pkgs.llama-cpp;
  whisperCpp =
    if acceleration == "cuda" then
      pkgs.whisper-cpp.override {
        cudaSupport = true;
        cudaPackages = gpu.cudaPackages;
      }
    else if acceleration == "rocm" then
      pkgs.whisper-cpp.override {
        rocmSupport = true;
        rocmGpuTargets = lib.concatStringsSep ";" gpu.rocmTargets;
      }
    else if acceleration == "vulkan" then
      pkgs.whisper-cpp.override {
        vulkanSupport = true;
      }
    else
      pkgs.whisper-cpp;
  ggmlCliTools = pkgs.buildEnv {
    name = "ggml-cli-tools";
    paths = [
      llamaCpp
      whisperCpp
    ];
    # Both packages bundle incompatible GGML ABIs under /lib. Their binaries
    # retain runtime references to their original outputs, so expose only CLI
    # assets.
    pathsToLink = [
      "/bin"
      "/share"
    ];
  };
in
{
  options.modules.core.packages = {
    enable = lib.mkEnableOption "common packages";
    crushSupported = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Whether crush is supported on this host";
    };
    antigravitySupported = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Whether antigravity-cli is supported on this host";
    };
  };

  config = lib.mkIf cfg.enable {
    home.packages = [
      pkgs.litellm
      pkgs.mergiraf
      pkgs.nh
      ollama
      ggmlCliTools
      pkgs.volta
    ]
    ++ lib.optionals (!openclawEnabled) [
      openclawTools.camsnap
      openclawTools.discrawl
      openclawTools.gogcli
      openclawTools.goplaces
      openclawTools.sag
      openclawTools.sonoscli
      openclawTools.summarize
      openclawTools.wacrawl
    ]
    ++ lib.optionals isServer [
      pkgs.delta
      pkgs.grc
    ]
    ++ lib.optionals isDesktop [
      pkgs.bruno
      pkgs.cloudfoundry-cli
      pkgs.codex
      pkgs.lychee
      pkgs.nerd-fonts.jetbrains-mono
      pkgs.nil
      pkgs.nixd
      pkgs.nixfmt
      pkgs.obsidian
      pkgs.yazi
    ]
    ++ lib.optionals (isDesktop && cfg.antigravitySupported) [
      pkgs.antigravity-cli
    ]
    ++ lib.optionals (isDesktop && cfg.crushSupported) [
      pkgs.crush
    ]
    ++ lib.optionals (isDesktop && isDarwin) (
      [
        pkgs.age
        pkgs.autoconf
        pkgs.automake
        pkgs.bashInteractive
        pkgs.bat
        pkgs.chroma
        pkgs.cmake
        pkgs.codexbar
        pkgs.coreutils
        pkgs.delta
        pkgs.ffmpeg
        pkgs.firefox
        pkgs.gnused
        pkgs.go
        pkgs.go-task
        pkgs.golangci-lint
        pkgs.google-chrome
        pkgs.gopls
        pkgs.grc
        pkgs.hidden-bar
        pkgs.hyperfine
        pkgs.insomnia
        pkgs.iterm2
        pkgs.jdk25
        pkgs.jetbrains.pycharm
        pkgs.jetbrains.rust-rover
        pkgs.mitmproxy
        pkgs.nheko
        pkgs.ninja
        pkgs.pandoc
        pkgs.pass
        pkgs.pipenv
        pkgs.pkg-config
        pkgs.poetry
        pkgs.poppler-utils
        pkgs.python3
        pkgs.python3Packages.huggingface-hub
        pkgs.python3Packages.virtualenv
        pkgs.qpdf
        pkgs.ruff
        pkgs.rustup
        pkgs.shellcheck
        pkgs.uv
        pkgs.vscode
        pkgs.yq
        pkgs.zed-editor
        pkgs.zoom-us
      ]
      ++ lib.optionals (!openclawEnabled) [
        openclawTools.imsg
        openclawTools.peekaboo
        openclawTools.poltergeist
      ]
    );

    home = {
      file.".Brewfile" = lib.mkIf (isDesktop && isDarwin) {
        text = ''
          tap "moltenbits/tap"
          cask "chatgpt"
          cask "docker-desktop"
          cask "ferdium"
          cask "ghostty"
          cask "gpg-suite@nightly"
          cask "growlrrr"
          cask "podman-desktop"
          brew "mole"
          brew "podman"
          brew "podman-compose"
        '';
      };
      activation.brewBundle = lib.mkIf (isDesktop && isDarwin) (
        lib.hm.dag.entryAfter [ "linkGeneration" ] ''
          _brew=""
          if [[ -f /opt/homebrew/bin/brew ]]; then
            _brew=/opt/homebrew/bin/brew
          elif [[ -f /usr/local/bin/brew ]]; then
            _brew=/usr/local/bin/brew
          fi

          if [[ -n "$_brew" ]]; then
            "$_brew" trust --tap moltenbits/tap 2>/dev/null || true
            "$_brew" trust --cask moltenbits/tap/growlrrr 2>/dev/null || true

            verboseEcho "Installing Homebrew packages from Brewfile"
            run "$_brew" bundle install --global
            run "$_brew" bundle cleanup --global --force
          else
            warnEcho "Homebrew not found"
          fi
          unset _brew
        ''
      );
    };
  };
}
