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
  openclawTools = inputs.nix-openclaw-tools.packages.${pkgs.stdenv.hostPlatform.system};
  isDesktop = config.modules.core.profile.name == config.modules.core.constants.profiles.desktop;
  isServer = config.modules.core.profile.name == config.modules.core.constants.profiles.server;
  isDarwin = pkgs.stdenv.hostPlatform.isDarwin;
  ollama =
    if acceleration == "cuda" then
      pkgs.ollama-cuda.override {
        cudaPackages = gpu.cudaPackages;
      }
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
  stableDiffusionCpp =
    if acceleration == "cuda" then
      pkgs.stable-diffusion-cpp.override {
        cudaSupport = true;
        cudaPackages = gpu.cudaPackages;
      }
    else if acceleration == "rocm" then
      pkgs.stable-diffusion-cpp.override {
        rocmSupport = true;
        rocmGpuTargets = gpu.rocmTargets;
      }
    else if acceleration == "vulkan" then
      pkgs.stable-diffusion-cpp.override {
        vulkanSupport = true;
      }
    else
      pkgs.stable-diffusion-cpp;
  whisperCpp =
    if acceleration == "cuda" then
      pkgs.whisper-cpp.override {
        cudaSupport = true;
        cudaPackages = gpu.cudaPackages;
      }
    else if acceleration == "rocm" then
      pkgs.whisper-cpp.override {
        rocmSupport = true;
        llama-cpp = llamaCpp;
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
      stableDiffusionCpp
      whisperCpp
    ];
    # Keep private GGML libraries out of the profile; binaries retain runtime
    # references to their original package outputs.
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
      pkgs.ortie
      ggmlCliTools
      pkgs.volta
    ]
    # Platform packages.
    ++ lib.optionals (!isDarwin) [
      ollama
    ]
    # OpenClaw standalone tools.
    ++ [
      openclawTools.camsnap
      openclawTools.discrawl
      openclawTools.gogcli
      openclawTools.goplaces
      openclawTools.sag
      openclawTools.sonoscli
      openclawTools.summarize
      openclawTools.wacrawl
    ]
    # Server packages.
    ++ lib.optionals isServer [
      pkgs.delta
      pkgs.grc
    ]
    # Desktop packages.
    ++ lib.optionals isDesktop [
      pkgs.bruno
      pkgs.cloudfoundry-cli
      pkgs.codex
      pkgs.ghidra
      pkgs.lychee
      pkgs.nerd-fonts.jetbrains-mono
      pkgs.nil
      pkgs.nixd
      pkgs.nixfmt
      pkgs.obsidian
      pkgs.rtk
      pkgs.yazi
    ]
    ++ lib.optionals (isDesktop && cfg.antigravitySupported) [
      pkgs.antigravity-cli
    ]
    ++ lib.optionals (isDesktop && cfg.crushSupported) [
      pkgs.crush
    ]
    # Desktop Darwin packages.
    ++ lib.optionals (isDesktop && isDarwin) [
      pkgs.age
      pkgs.aria2
      pkgs.autoconf
      pkgs.automake
      pkgs.bashInteractive
      pkgs.bat
      pkgs.chroma
      pkgs.cmake
      pkgs.codexbar
      pkgs.coreutils
      pkgs.delta
      pkgs.deno
      pkgs.ffmpeg
      pkgs.firefox
      pkgs.gawk
      pkgs.gnupatch
      pkgs.gnused
      pkgs.gnutar
      pkgs.go
      pkgs.go-task
      pkgs.golangci-lint
      pkgs.google-chrome
      pkgs.gopls
      pkgs.grc
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
      pkgs.yt-dlp
      pkgs.zed-editor
      pkgs.zoom-us
    ]
    # Desktop Darwin OpenClaw standalone tools.
    ++ lib.optionals (isDesktop && isDarwin) [
      openclawTools.imsg
      openclawTools.peekaboo
      openclawTools.poltergeist
    ];

    home = {
      file.".Brewfile" = lib.mkIf (isDesktop && isDarwin) {
        text = ''
          tap "moltenbits/tap", trusted: true
          tap "jundot/omlx", "https://github.com/jundot/omlx", trusted: true
          tap "incoai/tap", trusted: true
          cask "chatgpt"
          cask "docker-desktop"
          cask "ferdium"
          cask "ghostty"
          cask "gpg-suite@nightly"
          cask "growlrrr"
          cask "openvpn-connect"
          cask "podman-desktop"
          brew "mole"
          brew "ollama", restart_service: true
          brew "jundot/omlx/omlx", restart_service: true
          brew "incoai/tap/splash"
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
