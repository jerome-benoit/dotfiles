#!/usr/bin/env bash
set -euo pipefail

unset NIX_GPU_CUDA_CAPABILITIES
export NIX_GPU_CUDA_PROBE_STATUS=unavailable

if command -v nvidia-smi >/dev/null 2>&1; then
  export NIX_GPU_CUDA_PROBE_STATUS=failed
  if raw_capabilities=$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader,nounits 2>/dev/null); then
    row_count=$(printf '%s\n' "$raw_capabilities" | sed '/^[[:space:]]*$/d' | wc -l)
    valid_capabilities=$(printf '%s\n' "$raw_capabilities" \
      | sed -n 's/^[[:space:]]*\([0-9][0-9]*\.[0-9][0-9]*\)[[:space:]]*$/\1/p')
    valid_count=$(printf '%s\n' "$valid_capabilities" | sed '/^[[:space:]]*$/d' | wc -l)

    if [[ $row_count -gt 0 && $row_count -eq $valid_count ]]; then
      capabilities=$(printf '%s\n' "$valid_capabilities" | sort -u | paste -sd, -)
      if [[ -n $capabilities ]]; then
        export NIX_GPU_CUDA_CAPABILITIES=$capabilities
        export NIX_GPU_CUDA_PROBE_STATUS=ok
      fi
    fi
  fi
fi

exec "$@"
