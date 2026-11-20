{ pkgs }:
# Keep one atomic ledger for the helper; checks consume the same ordered source delta.
pkgs.writeText "strata-source.patch" (
  builtins.concatStringsSep "\n" (
    map builtins.readFile [
      # Managed source/bootstrap and workspace/source leases are one protocol.
      # Remove with equivalent publication, receipts and service handoffs.
      ../../../patches/strata-workspace-source-lifecycle.patch
      # Keep Windows batch contexts in their native CRLF form.
      # Remove with equivalent native vision CMake metadata handling.
      ../../../patches/strata-windows-cmake-metadata.patch
      # Setup, forecast and progress share one artifact-role layout.
      # Remove when all consumers use the same selected destinations.
      ../../../patches/strata-setup-directory-roles.patch
      # Capacity depends on role destinations, not the input GGUF filesystem.
      # Remove with equivalent split-destination accounting.
      ../../../patches/strata-destination-budgets.patch
      # Workaround: native argument checks follow optional dependency acquisition.
      # Remove when preflight and dispatch share upstream validation.
      ../../../patches/strata-cli-validation.patch
      # Workaround: doctor cannot map SYCL launcher paths to their host mount.
      # Remove when doctor resolves both executable and argument paths.
      ../../../patches/strata-engine-inspection.patch
      # Workaround: upstream cannot verify the selected manifest executable.
      # Remove when upstream verifies that selected file and its execute bit.
      ../../../patches/strata-selected-executable.patch
    ]
  )
)
