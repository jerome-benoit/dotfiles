# SOPS Secrets Management
# GPG key: B799BBF68EC8911BB8D7CDBCC3B192C627B535D3
SOPS := nix run nixpkgs\#sops --
FLAKE := .

.PHONY: help decrypt encrypt edit-personal edit-tokens build switch

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

decrypt: ## Decrypt personal secrets to JSON (required before home-manager build)
	$(SOPS) -d --output-type json secrets/personal.enc.yaml > secrets/personal.dec.json

encrypt: ## Re-encrypt personal secrets from JSON (after manual editing)
	$(SOPS) --encrypt --input-type json --output-type yaml secrets/personal.dec.json > secrets/personal.enc.yaml

edit-personal: ## Edit personal secrets interactively via SOPS
	$(SOPS) secrets/personal.enc.yaml

edit-tokens: ## Edit application tokens interactively via SOPS
	$(SOPS) secrets/tokens.enc.yaml

build: decrypt ## Decrypt then build home-manager configuration (--impure required)
	home-manager build --flake $(FLAKE) --impure

switch: decrypt ## Decrypt then switch home-manager configuration (--impure required)
	home-manager switch --flake $(FLAKE) --impure
