# SOPS Private Configuration and Credentials Management
SECRETS := nix run nixpkgs\#python3 -- ./scripts/secrets.py
GPU_ENV := ./scripts/gpu-env.sh

.PHONY: help decrypt decrypt-private encrypt edit-private edit-credentials encrypt-gpg bootstrap build switch clean

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

decrypt-private: ## Decrypt private configuration only for Nix evaluation
	@$(SECRETS) decrypt-private

decrypt: ## Decrypt private configuration and credentials for inspection
	@$(SECRETS) decrypt

encrypt: ## Re-encrypt private configuration and credentials after editing
	@$(SECRETS) encrypt

edit-private: ## Edit private configuration interactively via SOPS
	@$(SECRETS) edit-private

edit-credentials: ## Edit runtime credentials interactively via SOPS
	@$(SECRETS) edit-credentials

encrypt-gpg: ## (Re)create age-encrypted GPG keypair bundle for home-manager bootstrap
	@$(SECRETS) run ./scripts/encrypt-gpg-bundle.sh

bootstrap: ## First-time setup with transient private configuration. Usage: make bootstrap SPEC=work
	@$(SECRETS) run $(GPU_ENV) nix run home-manager -- switch --flake $(CURDIR) --impure -b backup $(if $(SPEC),--specialisation $(SPEC))

build: ## Build Home Manager with transient private configuration (--impure required)
	@$(SECRETS) run $(GPU_ENV) env NH_FLAKE=$(CURDIR) nh home build --impure -c "$$(whoami)" -- --impure

switch: ## Switch Home Manager with transient private configuration. Usage: make switch SPEC=work
	@$(SECRETS) run $(GPU_ENV) env NH_FLAKE=$(CURDIR) nh home switch --impure -c "$$(whoami)" $(if $(SPEC),--specialisation $(SPEC)) -- --impure

clean: ## Remove decrypted private configuration, credentials, and temporary files
	@./scripts/clean-secrets.sh
