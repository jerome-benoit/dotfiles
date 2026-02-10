# Workaround for https://github.com/anomalyco/opencode/issues/11755
# Upstream desktop.nix is missing outputHashes for git dependencies.
#
# MAINTENANCE: After `nix flake update`, if build fails with hash errors:
# 1. Set the stale hash to lib.fakeHash (requires passing lib to this file)
#    or use "sha256-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
# 2. Run build, copy correct hash from error message
# 3. Update this file with the new hash
{
  "specta-2.0.0-rc.22" = "sha256-YsyOAnXELLKzhNlJ35dHA6KGbs0wTAX/nlQoW8wWyJQ=";
  "tauri-2.9.5" = "sha256-dv5E/+A49ZBvnUQUkCGGJ21iHrVvrhHKNcpUctivJ8M=";
  "tauri-specta-2.0.0-rc.21" = "sha256-n2VJ+B1nVrh6zQoZyfMoctqP+Csh7eVHRXwUQuiQjaQ=";
}
