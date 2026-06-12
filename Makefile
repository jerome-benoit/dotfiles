# SOPS Secrets Management
SOPS := nix run nixpkgs\#sops --
FLAKE := .

.PHONY: help decrypt decrypt-personal encrypt edit-personal edit-tokens encrypt-gpg bootstrap build switch clean

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

decrypt-personal:
	@$(SOPS) decrypt --output-type json --output secrets/personal.dec.json.tmp secrets/personal.enc.yaml
	@chmod 600 secrets/personal.dec.json.tmp
	@mv secrets/personal.dec.json.tmp secrets/personal.dec.json

decrypt: decrypt-personal ## Decrypt all secrets to JSON for inspection
	@$(SOPS) decrypt --output-type json --output secrets/tokens.dec.json.tmp secrets/tokens.enc.yaml
	@chmod 600 secrets/tokens.dec.json.tmp
	@mv secrets/tokens.dec.json.tmp secrets/tokens.dec.json
	@echo "\033[33mNote: plaintext secrets on disk. Run 'make clean' when done.\033[0m"

encrypt: ## Re-encrypt all secrets from JSON (after manual editing)
	@test -f secrets/personal.dec.json || { echo "Error: secrets/personal.dec.json not found. Run 'make decrypt' first."; exit 1; }
	@test -f secrets/tokens.dec.json || { echo "Error: secrets/tokens.dec.json not found. Run 'make decrypt' first."; exit 1; }
	@$(SOPS) encrypt --input-type json --output-type yaml --output secrets/personal.enc.yaml.tmp secrets/personal.dec.json
	@$(SOPS) encrypt --input-type json --output-type yaml --output secrets/tokens.enc.yaml.tmp secrets/tokens.dec.json
	@mv secrets/personal.enc.yaml.tmp secrets/personal.enc.yaml
	@mv secrets/tokens.enc.yaml.tmp secrets/tokens.enc.yaml

edit-personal: ## Edit personal secrets interactively via SOPS
	@$(SOPS) secrets/personal.enc.yaml

edit-tokens: ## Edit application tokens interactively via SOPS
	@$(SOPS) secrets/tokens.enc.yaml

encrypt-gpg: decrypt-personal ## (Re)create age-encrypted GPG keypair bundle for home-manager bootstrap
	@trap 'rm -f secrets/personal.dec.json' EXIT; ./scripts/encrypt-gpg-bundle.sh

bootstrap: decrypt-personal ## First-time setup (no nh/home-manager required). Usage: make bootstrap SPEC=work
	@trap 'rm -f secrets/personal.dec.json' EXIT; export NIX_NVIDIA_DRIVER_VERSION="$$(modinfo -F version nvidia 2>/dev/null || true)"; nix run home-manager -- switch --flake $(CURDIR) --impure -b backup $(if $(SPEC),--specialisation $(SPEC))

build: decrypt-personal ## Decrypt then build home-manager configuration (--impure required)
	@trap 'rm -f secrets/personal.dec.json' EXIT; export NIX_NVIDIA_DRIVER_VERSION="$$(modinfo -F version nvidia 2>/dev/null || true)"; NH_FLAKE=$(CURDIR) nh home build --impure -c "$$(whoami)" -- --impure

switch: decrypt-personal ## Decrypt then switch home-manager configuration (--impure required). Usage: make switch SPEC=work
	@trap 'rm -f secrets/personal.dec.json' EXIT; export NIX_NVIDIA_DRIVER_VERSION="$$(modinfo -F version nvidia 2>/dev/null || true)"; NH_FLAKE=$(CURDIR) nh home switch --impure -c "$$(whoami)" $(if $(SPEC),--specialisation $(SPEC)) -- --impure

clean: ## Remove decrypted secrets and temporary files from disk
	@rm -f secrets/*.dec.* secrets/*.tmp
