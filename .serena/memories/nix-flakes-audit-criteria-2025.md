# Nix Flakes + Home-Manager Audit Criteria (2025-2026)

## PHASE 1: MODERN FLAKE PATTERNS

### 1.1 Inputs Management & Hygiene
**BEST PRACTICE**: Explicit `follows` for all transitive dependencies
- ✅ **Pattern**: Every input with its own inputs should have explicit `follows` statements
  ```nix
  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
    home-manager = {
      url = "github:nix-community/home-manager";
      inputs.nixpkgs.follows = "nixpkgs";  # CRITICAL
    };
    sops-nix = {
      url = "github:mic92/sops-nix";
      inputs.nixpkgs.follows = "nixpkgs";  # CRITICAL
    };
  };
  ```
- ✅ **Rationale**: Prevents multiple nixpkgs versions in lock file (bloat, inconsistency)
- ❌ **Anti-pattern**: Missing `follows` → multiple nixpkgs instances in flake.lock

**BEST PRACTICE**: Organize inputs logically with comments
- ✅ Group by category (ecosystem, tools, services)
- ✅ Alphabetical order within groups
- ✅ Pin to specific branches/tags when appropriate

**BEST PRACTICE**: Use `systems` input for multi-architecture support
```nix
inputs.systems.url = "github:nix-systems/default-linux";
# Then: forEachSystem = f: lib.genAttrs (import systems) (system: f {...});
```

### 1.2 Outputs Structure
**BEST PRACTICE**: Explicit system declaration (no magic defaults)
```nix
let
  supportedSystems = [ "x86_64-linux" "aarch64-linux" "x86_64-darwin" "aarch64-darwin" ];
  forEachSupportedSystem = f: lib.genAttrs supportedSystems (system: f {
    pkgs = import nixpkgs { inherit system; };
  });
in {
  packages = forEachSupportedSystem ({ pkgs }: { ... });
  devShells = forEachSupportedSystem ({ pkgs }: { ... });
}
```
- ✅ **Rationale**: Clear, maintainable, no hidden dependencies
- ❌ **Anti-pattern**: Using `flake-utils.eachDefaultSystem` (obscures which systems are included)

**BEST PRACTICE**: Provide `default` outputs
- ✅ `packages.<system>.default`
- ✅ `devShells.<system>.default`
- ✅ `apps.<system>.default`

**BEST PRACTICE**: Use `specialArgs` to pass `inputs` and `outputs` to modules
```nix
nixosConfigurations.myhost = lib.nixosSystem {
  modules = [ ./hosts/myhost ];
  specialArgs = { inherit inputs outputs; };
};
```

### 1.3 Flake-Utils vs. Plain Nix (2025 Consensus)
**RECOMMENDATION**: Avoid `flake-utils` and `flake-parts` if possible
- ✅ Use `nixpkgs.lib.genAttrs` instead (already a dependency)
- ✅ Reduces evaluation dependencies
- ✅ More explicit and maintainable
- ⚠️ **Exception**: `flake-parts` acceptable for large, modular projects (but adds complexity)

**EVIDENCE**: Determinate Systems (2025) + Nixcademy (2025) both recommend avoiding these

### 1.4 nixConfig for Binary Caches
**BEST PRACTICE**: Declare binary caches in flake.nix
```nix
nixConfig = {
  extra-substituters = [
    "https://cache.nixos.org"
    "https://nix-community.cachix.org"
  ];
  extra-trusted-public-keys = [
    "cache.nixos.org-1:6NCHdD59X431o0gWypQtVrp8wsJlS5HVDFm3Z+uNJ0="
    "nix-community.cachix.org-1:mB9FSh9qf2QlZceNZSfqkLcV+sxpPqn1dxNaWXn/5V0="
  ];
};
```

---

## PHASE 2: HOME-MANAGER MODULE BEST PRACTICES

### 2.1 Module Structure
**BEST PRACTICE**: Proper module signature with all parameters
```nix
{ lib, config, pkgs, outputs, ... }:
let
  cfg = config.mymodule;
  inherit (lib) mkOption mkEnableOption types;
in {
  options.mymodule = {
    enable = mkEnableOption "my module";
    # ... more options
  };
  config = lib.mkIf cfg.enable {
    # ... implementation
  };
}
```

**BEST PRACTICE**: Use `mkEnableOption` for boolean toggles
```nix
enable = lib.mkEnableOption "feature name";
# NOT: enable = mkOption { type = types.bool; default = false; };
```

**BEST PRACTICE**: Use `mkPackageOption` for package selections
```nix
package = lib.mkPackageOption pkgs "myapp" { };
```

**BEST PRACTICE**: Use `types.submodule` for nested configurations
```nix
monitors = mkOption {
  type = types.listOf (types.submodule {
    options = {
      name = mkOption { type = types.str; };
      primary = mkOption { type = types.bool; default = false; };
    };
  });
  default = [];
};
```

### 2.2 Option Types
**BEST PRACTICE**: Use specific types, not generic `types.attrs`
- ✅ `types.str`, `types.int`, `types.bool`, `types.path`
- ✅ `types.enum [ "option1" "option2" ]`
- ✅ `types.strMatching "regex"` for validation
- ❌ `types.attrs` (too permissive)

**BEST PRACTICE**: Provide meaningful defaults and examples
```nix
myOption = mkOption {
  type = types.str;
  default = "sensible-default";
  example = "custom-value";
  description = "Clear description of what this does";
};
```

### 2.3 Assertions & Validation
**BEST PRACTICE**: Use assertions for cross-option validation
```nix
config = {
  assertions = [
    {
      assertion = (lib.length config.monitors) != 0 -> 
                  (lib.length (lib.filter (m: m.primary) config.monitors)) == 1;
      message = "Exactly one monitor must be set to primary.";
    }
  ];
};
```

---

## PHASE 3: NIX ANTI-PATTERNS TO AVOID

### 3.1 Language Anti-Patterns
❌ **`with pkgs;` in module scope**
- Problem: Pollutes namespace, makes dependencies implicit
- ✅ **Fix**: Use explicit `pkgs.package` or `inherit (pkgs) package;`

❌ **`rec { ... }` for self-referential sets**
- Problem: Creates implicit dependencies, harder to refactor
- ✅ **Fix**: Use `let ... in { ... }` instead

❌ **`import <nixpkgs>`**
- Problem: Non-reproducible, depends on NIX_PATH
- ✅ **Fix**: Use flake inputs: `import nixpkgs { ... }`

❌ **Excessive `let` nesting**
- Problem: Reduces readability
- ✅ **Fix**: Extract to separate files or use `lib.pipe`

### 3.2 Flake Anti-Patterns
❌ **Missing `follows` statements**
- Creates multiple nixpkgs versions in lock file

❌ **Using `flake-utils.eachDefaultSystem` without explicit list**
- Obscures which systems are actually supported

❌ **Putting secrets in flake.nix**
- Secrets end up in world-readable Nix store
- ✅ **Fix**: Use `sops-nix` or `agenix`

❌ **Not staging files in git before flake operations**
- Flakes only see git-tracked files
- ✅ **Fix**: `git add` files before `nix flake` commands

### 3.3 Module Anti-Patterns
❌ **Using `mkOption` for simple booleans**
- ✅ **Fix**: Use `mkEnableOption` instead

❌ **Overly permissive types (e.g., `types.attrs`)**
- ✅ **Fix**: Use specific types with validation

❌ **No assertions for interdependent options**
- ✅ **Fix**: Add assertions for cross-option validation

---

## PHASE 4: THEME/STYLING SYSTEMS

### 4.1 Recommended Approaches (2025)

**Option A: nix-colors (Misterio77)**
- ✅ Lightweight, Nix-native
- ✅ Provides color scheme generation
- ✅ Used in production configs (Misterio77/nix-config)
- Pattern:
  ```nix
  inputs.nix-colors.url = "github:misterio77/nix-colors";
  # Then: inherit (inputs.nix-colors.lib.conversions) hexToRGBString;
  ```

**Option B: Catppuccin (Community-driven)**
- ✅ Pre-built themes for many apps
- ✅ Consistent across ecosystem
- ✅ Easy to fetch from GitHub
- Pattern:
  ```nix
  xdg.configFile."app/theme.yml".source = pkgs.fetchurl {
    url = "https://raw.githubusercontent.com/catppuccin/app/...";
    sha256 = "...";
  };
  ```

**Option C: Stylix (Newer, integrated)**
- ✅ Declarative theme system
- ✅ Generates themes from base color
- ⚠️ Adds complexity, newer ecosystem

### 4.2 Best Practice Pattern
```nix
# Custom module for theme management
{ lib, config, pkgs, ... }:
let
  cfg = config.colorscheme;
  hexColor = lib.types.strMatching "#([0-9a-fA-F]{3}){1,2}";
in {
  options.colorscheme = {
    mode = lib.mkOption {
      type = lib.types.enum [ "dark" "light" ];
      default = "dark";
    };
    colors = lib.mkOption {
      type = lib.types.attrsOf hexColor;
      readOnly = true;
    };
  };
  config = {
    # Apply colors to all apps
  };
}
```

---

## PHASE 5: CI/CHECKS BEST PRACTICES

### 5.1 GitHub Actions Workflow
**BEST PRACTICE**: Minimal checks workflow
```yaml
name: Check
on: [push, pull_request, workflow_dispatch]

jobs:
  checks:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: cachix/install-nix-action@v26
        with:
          install_url: https://nixos.org/nix/install
          extra_nix_config: |
            experimental-features = nix-command flakes
      - run: nix flake check
```

### 5.2 Formatting & Linting
**BEST PRACTICE**: Use treefmt-nix + pre-commit
```nix
# fmt-hooks.nix
{ inputs, ... }:
{
  imports = [
    inputs.git-hooks.flakeModule
    inputs.treefmt-nix.flakeModule
  ];

  perSystem = {
    pre-commit.settings = {
      excludes = [ "flake.lock" ];
      hooks.treefmt.enable = true;
    };

    treefmt.programs = {
      nixfmt.enable = true;
      prettier.enable = true;
    };
  };
}
```

**TOOLS TO INCLUDE**:
- ✅ `nixfmt` or `alejandra` (Nix formatting)
- ✅ `statix` (Nix linting)
- ✅ `deadnix` (unused variable detection)
- ✅ `nil` (LSP checks)
- ✅ `prettier` (YAML, JSON, Markdown)

### 5.3 Checks Output
**BEST PRACTICE**: Define `checks` output
```nix
checks.x86_64-linux = {
  formatting = pkgs.runCommand "check-formatting" {} ''
    ${pkgs.nixfmt}/bin/nixfmt --check ${self}
  '';
};
```

---

## PHASE 6: FLAKE INPUTS HYGIENE

### 6.1 Pinning Strategy
**BEST PRACTICE**: Pin to specific branches/tags
```nix
inputs = {
  nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";  # Branch
  nixpkgs-stable.url = "github:nixos/nixpkgs/nixos-25.11";  # Tag
  home-manager.url = "github:nix-community/home-manager";  # Latest
};
```

**BEST PRACTICE**: Use `flake.lock` for reproducibility
- ✅ Commit `flake.lock` to git
- ✅ Update regularly with `nix flake update`
- ✅ Review lock file changes in PRs

### 6.2 Input Organization
**BEST PRACTICE**: Logical grouping with comments
```nix
inputs = {
  # Core ecosystem
  nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
  systems.url = "github:nix-systems/default-linux";

  # NixOS/Home-Manager
  home-manager = {
    url = "github:nix-community/home-manager";
    inputs.nixpkgs.follows = "nixpkgs";
  };

  # Tools & Services
  sops-nix = {
    url = "github:mic92/sops-nix";
    inputs.nixpkgs.follows = "nixpkgs";
  };
};
```

### 6.3 Dependency Minimization
**BEST PRACTICE**: Only include necessary inputs
- ❌ Don't add inputs you don't use
- ✅ Lazy-load optional dependencies
- ✅ Use `flake = false;` for non-flake sources

---

## AUDIT CHECKLIST

### Structure & Organization
- [ ] `flake.nix` exists and is valid
- [ ] `flake.lock` is committed to git
- [ ] Inputs are organized with comments
- [ ] All transitive inputs have `follows` statements
- [ ] No unused inputs

### Outputs
- [ ] All outputs specify systems explicitly
- [ ] `default` outputs provided for packages/devShells
- [ ] `specialArgs` passes `inputs` and `outputs` to modules
- [ ] No `flake-utils.eachDefaultSystem` (use `lib.genAttrs` instead)

### Home-Manager Modules
- [ ] Modules use proper signature: `{ lib, config, pkgs, ... }`
- [ ] Boolean options use `mkEnableOption`
- [ ] Package options use `mkPackageOption`
- [ ] Options have descriptions and examples
- [ ] Assertions validate cross-option constraints
- [ ] No `with pkgs;` in module scope

### Anti-Patterns
- [ ] No `import <nixpkgs>`
- [ ] No excessive `rec { ... }`
- [ ] No `with pkgs;` at module level
- [ ] No secrets in flake.nix
- [ ] No missing `follows` statements

### CI/Checks
- [ ] GitHub Actions workflow runs `nix flake check`
- [ ] Formatting tool configured (nixfmt/alejandra)
- [ ] Linting tool configured (statix)
- [ ] Pre-commit hooks enabled
- [ ] `checks` output defined

### Theme System
- [ ] Theme system chosen (nix-colors/catppuccin/stylix)
- [ ] Theme configuration is modular
- [ ] Colors are validated (hex format)
- [ ] Theme can be switched without full rebuild

### Documentation
- [ ] README explains flake structure
- [ ] Module options documented
- [ ] Installation instructions provided
- [ ] Contributing guidelines present

---

## REFERENCES

**Official Documentation**:
- https://nix.dev/concepts/flakes
- https://wiki.nixos.org/wiki/Flakes
- https://nix-community.github.io/home-manager/options.xhtml

**Best Practices (2025)**:
- Determinate Systems: https://determinate.systems/blog/best-practices-for-nix-at-work/
- Nixcademy: https://nixcademy.com/posts/1000-instances-of-flake-utils/

**Example Configs**:
- Misterio77/nix-config: https://github.com/Misterio77/nix-config
- fufexan/dotfiles: https://github.com/fufexan/dotfiles
