# SOPS Secrets Management
SOPS := nix run nixpkgs\#sops --
FLAKE := .

.PHONY: help decrypt encrypt edit-personal edit-tokens build switch clean

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

decrypt: ## Decrypt personal secrets to JSON (cleaned up automatically by build/switch)
	@$(SOPS) decrypt --output-type json --output secrets/personal.dec.json.tmp secrets/personal.enc.yaml
	@chmod 600 secrets/personal.dec.json.tmp
	@mv secrets/personal.dec.json.tmp secrets/personal.dec.json
	@if [ -z "$(MAKECMDGOALS)" ] || [ "$(MAKECMDGOALS)" = "decrypt" ]; then \
		echo "\033[33mNote: plaintext secrets on disk. Run 'make clean' when done.\033[0m"; \
	fi

encrypt: ## Re-encrypt personal secrets from JSON (after manual editing)
	@$(SOPS) encrypt --input-type json --output-type yaml --output secrets/personal.enc.yaml.tmp secrets/personal.dec.json
	@mv secrets/personal.enc.yaml.tmp secrets/personal.enc.yaml

edit-personal: ## Edit personal secrets interactively via SOPS
	@$(SOPS) secrets/personal.enc.yaml

edit-tokens: ## Edit application tokens interactively via SOPS
	@$(SOPS) secrets/tokens.enc.yaml

build: decrypt ## Decrypt then build home-manager configuration (--impure required)
	@trap 'rm -f secrets/personal.dec.json' EXIT; home-manager build --flake $(FLAKE) --impure

switch: decrypt ## Decrypt then switch home-manager configuration (--impure required)
	@trap 'rm -f secrets/personal.dec.json' EXIT; home-manager switch --flake $(FLAKE) --impure

clean: ## Remove decrypted secrets and temporary files from disk
	@rm -f secrets/*.dec.* secrets/*.tmp
