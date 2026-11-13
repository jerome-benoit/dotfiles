{
  pkgs,
  src,
  self,
  home-manager,
}:
let
  sourcePatch = ../patches/strata-setup-directory-roles.patch;
  supportedPlatform = pkgs.stdenv.hostPlatform.system == "x86_64-linux";
  configureWith =
    selectedPkgs: settings:
    home-manager.lib.homeManagerConfiguration {
      pkgs = selectedPkgs;
      extraSpecialArgs = {
        inherit self;
        inputs.strata = src;
      };
      modules = [
        ../home-manager/modules/development/strata.nix
        {
          home = {
            username = "strata-check";
            homeDirectory = "/home/strata-check";
            stateVersion = "26.05";
          };
          modules.development.strata = settings;
        }
      ];
    };
  configure = configureWith pkgs;
  defaults = configure { };
  custom = configure {
    enable = supportedPlatform;
    package = pkgs.hello;
    workspaceDirectory = "/workspace with spaces";
    dataDirectory = "/data with spaces";
    modelsDirectory = "/GGUF's $(touch injected)";
  };
  directoryTypes = map (name: defaults.options.modules.development.strata.${name}.type) [
    "dataDirectory"
    "modelsDirectory"
  ];
  launcherPkgs = pkgs.extend (
    _final: previous: {
      nix = previous.writeShellScriptBin "nix" ''
        exec ${previous.python3}/bin/python3 -c 'import json, sys; print(json.dumps(sys.argv[1:]))' "$@"
      '';
    }
  );
  launcherFixtures = pkgs.writeText "strata-launchers.json" (
    builtins.toJSON (
      map
        (
          directories:
          let
            configuration = configureWith launcherPkgs (
              {
                enable = supportedPlatform;
                workspaceDirectory = "/workspace's $(touch injected)";
              }
              // directories
            );
            settings = configuration.config.modules.development.strata;
          in
          {
            launcher = "${settings.package}/bin/strata";
            expected = [
              settings.workspaceDirectory
              src.rev
              (if settings.dataDirectory == null then "" else settings.dataDirectory)
              (if settings.modelsDirectory == null then "" else settings.modelsDirectory)
            ];
          }
        )
        [
          { }
          {
            dataDirectory = "/data's $(touch injected)";
            modelsDirectory = "/GGUF's $(touch injected)";
          }
        ]
    )
  );
in
assert
  defaults.config.modules.development.strata.workspaceDirectory
  == "/home/strata-check/.local/share/strata";
assert defaults.config.modules.development.strata.dataDirectory == null;
assert defaults.config.modules.development.strata.modelsDirectory == null;
assert
  pkgs.lib.count (package: package == pkgs.hello) custom.config.home.packages
  == (if supportedPlatform then 1 else 0);
assert
  supportedPlatform
  || !(builtins.tryEval (builtins.deepSeq (configure { enable = true; }).config.home.packages true))
  .success;
assert !(builtins.elem pkgs.hello defaults.config.home.packages);
assert custom.config.modules.development.strata.modelsDirectory == "/GGUF's $(touch injected)";
assert builtins.all (
  type:
  type.check null
  && type.check "/a path"
  && !(type.check "")
  && !(type.check "relative/path")
  && !(type.check "/nix/store")
  && !(type.check "/nix/store/model")
  && !(type.check ../README.md)
) directoryTypes;
pkgs.runCommand "check-strata-workspace"
  {
    nativeBuildInputs = [
      pkgs.git
      pkgs.nix
      (pkgs.python3.withPackages (python: [
        python.numpy
        python.jinja2
        python.pip
        python.regex
      ]))
    ];
  }
  ''
    export HOME=$TMPDIR/home
    mkdir -p "$HOME"
    python3 ${./strata.py} ${../home-manager/modules/development/strata-workspace.py} ${src} ${launcherFixtures} ${sourcePatch}
    touch $out
  ''
