# SOPS Secrets Management
SOPS := nix run nixpkgs\#sops --
FLAKE := .

.PHONY: help decrypt encrypt edit-personal edit-tokens build switch clean

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

decrypt: ## Decrypt personal secrets to JSON (required before home-manager build)
	@umask 077 && $(SOPS) decrypt --output-type json --output secrets/personal.dec.json.tmp secrets/personal.enc.yaml
	@mv secrets/personal.dec.json.tmp secrets/personal.dec.json

encrypt: ## Re-encrypt personal secrets from JSON (after manual editing)
	@$(SOPS) encrypt --input-type json --output-type yaml --output secrets/personal.enc.yaml.tmp secrets/personal.dec.json
	@mv secrets/personal.enc.yaml.tmp secrets/personal.enc.yaml

edit-personal: ## Edit personal secrets interactively via SOPS
	@$(SOPS) secrets/personal.enc.yaml

edit-tokens: ## Edit application tokens interactively via SOPS
	@$(SOPS) secrets/tokens.enc.yaml

build: decrypt ## Decrypt then build home-manager configuration (--impure required)
	@home-manager build --flake $(FLAKE) --impure; _rc=$$?; rm -f secrets/personal.dec.json; exit $$_rc

switch: decrypt ## Decrypt then switch home-manager configuration (--impure required)
	@home-manager switch --flake $(FLAKE) --impure; _rc=$$?; rm -f secrets/personal.dec.json; exit $$_rc

clean: ## Remove decrypted secrets and temporary files from disk
	@rm -f secrets/*.dec.* secrets/*.tmp
