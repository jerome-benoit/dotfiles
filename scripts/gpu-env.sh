#!/usr/bin/env bash

gpu_snapshot_sysfs() {
  local root=$1 version='' node gpu_id='' encoded='' key='' value='' extra=''
  local major minor stepping target targets=
  local version_pattern='^[0-9]{3}\.[0-9]{2,3}(\.[0-9]{2,3})?$'
  local integer_pattern='^[0-9]{1,9}$'

  unset NIX_GPU_NVIDIA_DRIVER_VERSION NIX_GPU_ROCM_TARGETS

  if { IFS= read -r version || [[ -n $version ]]; } 2>/dev/null < "$root/module/nvidia/version"; then
    if [[ $version =~ $version_pattern ]]; then
      export NIX_GPU_NVIDIA_DRIVER_VERSION=$version
    fi
  fi

  for node in "$root"/class/kfd/kfd/topology/nodes/*; do
    [[ -d $node ]] || continue
    gpu_id=
    if ! { IFS= read -r gpu_id || [[ -n $gpu_id ]]; } 2>/dev/null < "$node/gpu_id"; then
      continue
    fi
    [[ $gpu_id =~ ^[0-9]+$ ]] || continue
    [[ $gpu_id =~ ^0+$ ]] && continue

    encoded=
    if ! {
      while IFS=$' \t' read -r key value extra || [[ -n $key ]]; do
        if [[ $key == gfx_target_version ]]; then
          [[ -z $extra ]] && encoded=$value
          break
        fi
      done
    } 2>/dev/null < "$node/properties"; then
      continue
    fi

    [[ $encoded =~ $integer_pattern ]] || continue
    encoded=$((10#$encoded))
    major=$((encoded / 10000))
    minor=$((encoded / 100 % 100))
    stepping=$((encoded % 100))
    ((major > 0 && minor < 16 && stepping < 16)) || continue
    printf -v target 'gfx%d%x%x' "$major" "$minor" "$stepping"
    case ",$targets," in
      *",$target,"*) ;;
      *) targets=${targets:+$targets,}$target ;;
    esac
  done

  if [[ -n $targets ]]; then
    export NIX_GPU_ROCM_TARGETS=$targets
  fi
  return 0
}

gpu_parse_cuda_capabilities() {
  local raw=$1 row='' capability capabilities=''
  local pattern='^[[:space:]]*([0-9]+\.[0-9]+)[[:space:]]*$'

  while IFS= read -r row || [[ -n $row ]]; do
    [[ $row =~ ^[[:space:]]*$ ]] && continue
    [[ $row =~ $pattern ]] || return 1
    capability=${BASH_REMATCH[1]}
    case ",$capabilities," in
      *",$capability,"*) ;;
      *) capabilities=${capabilities:+$capabilities,}$capability ;;
    esac
  done <<< "$raw"

  [[ -n $capabilities ]] || return 1
  printf '%s\n' "$capabilities"
}

gpu_probe_cuda() {
  local raw_capabilities capabilities
  unset NIX_GPU_CUDA_CAPABILITIES
  export NIX_GPU_CUDA_PROBE_STATUS=unavailable

  if command -v nvidia-smi >/dev/null 2>&1; then
    export NIX_GPU_CUDA_PROBE_STATUS=failed
    if raw_capabilities=$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader,nounits 2>/dev/null); then
      if capabilities=$(gpu_parse_cuda_capabilities "$raw_capabilities"); then
        export NIX_GPU_CUDA_CAPABILITIES=$capabilities
        export NIX_GPU_CUDA_PROBE_STATUS=ok
      fi
    fi
  fi
  return 0
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
  set -euo pipefail
  gpu_snapshot_sysfs /sys
  gpu_probe_cuda
  exec "$@"
fi
