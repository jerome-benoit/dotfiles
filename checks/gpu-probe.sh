#!/usr/bin/env bash
set -euo pipefail

source "$1"

fail() {
  printf 'GPU probe: %s\n' "$1" >&2
  exit 1
}

root="$TMPDIR/gpu-sysfs"
mkdir -p "$root/module/nvidia"
printf '615.71.09' > "$root/module/nvidia/version"
gpu_snapshot_sysfs "$root"
[[ ${NIX_GPU_NVIDIA_DRIVER_VERSION-} == 615.71.09 ]] || fail 'driver without trailing newline'
printf '580.126.20\n' > "$root/module/nvidia/version"
gpu_snapshot_sysfs "$root"
[[ ${NIX_GPU_NVIDIA_DRIVER_VERSION-} == 580.126.20 ]] || fail 'driver snapshot stayed stale'
printf 'invalid\n' > "$root/module/nvidia/version"
gpu_snapshot_sysfs "$root"
[[ -z ${NIX_GPU_NVIDIA_DRIVER_VERSION-} ]] || fail 'malformed driver retained'
printf '615.71.09\n' > "$root/module/nvidia/version"
gpu_snapshot_sysfs "$root"
rm "$root/module/nvidia/version"
gpu_snapshot_sysfs "$root"
[[ -z ${NIX_GPU_NVIDIA_DRIVER_VERSION-} ]] || fail 'missing driver retained'

nodes="$root/class/kfd/kfd/topology/nodes"
for node in 0 1 2 3 4; do
  mkdir -p "$nodes/$node"
  printf '42\n' > "$nodes/$node/gpu_id"
done
printf '000\n' > "$nodes/0/gpu_id"
printf 'gfx_target_version 120001\n' > "$nodes/0/properties"
printf 'gfx_target_version\t90010' > "$nodes/1/properties"
printf 'gfx_target_version 90010\n' > "$nodes/2/properties"
printf 'gfx_target_version 110000\n' > "$nodes/3/properties"
printf 'gfx_target_version invalid\n' > "$nodes/4/properties"
gpu_snapshot_sysfs "$root"
[[ ${NIX_GPU_ROCM_TARGETS-} == gfx90a,gfx1100 ]] || fail 'CPU filtering, hex decoding or target deduplication'
printf 'gfx_target_version 120001\n' > "$nodes/1/properties"
rm "$nodes/2/properties" "$nodes/3/properties"
gpu_snapshot_sysfs "$root"
[[ ${NIX_GPU_ROCM_TARGETS-} == gfx1201 ]] || fail 'topology snapshot stayed stale or missing node blocked a sibling'
for encoded in 0 90016 901600 1000000000; do
  printf 'gfx_target_version %s\n' "$encoded" > "$nodes/4/properties"
  gpu_snapshot_sysfs "$root"
  [[ ${NIX_GPU_ROCM_TARGETS-} == gfx1201 ]] || fail 'out-of-range GFX target accepted'
done
rm "$nodes/1/properties"
gpu_snapshot_sysfs "$root"
[[ -z ${NIX_GPU_ROCM_TARGETS-} ]] || fail 'removed topology retained'

capabilities=$(gpu_parse_cuda_capabilities $' 8.9 \n7.5\n\n8.9\n')
case $capabilities in
  8.9,7.5|7.5,8.9) ;;
  *) fail 'capability normalization or deduplication' ;;
esac
for raw in '' $'8.9\nN/A' $'8.9\ngarbage' '8.9,7.5'; do
  if gpu_parse_cuda_capabilities "$raw" >/dev/null; then
    fail 'empty or partially malformed query accepted'
  fi
done

probe_output=$'8.9\n 12.0 '
probe_exit=0
nvidia-smi() {
  printf '%s\n' "$probe_output"
  return "$probe_exit"
}
gpu_probe_cuda
[[ $NIX_GPU_CUDA_PROBE_STATUS == ok && ${NIX_GPU_CUDA_CAPABILITIES-} == 8.9,12.0 ]] || fail 'valid multi-GPU query rejected'
probe_output=$'8.9\nN/A'
gpu_probe_cuda
[[ $NIX_GPU_CUDA_PROBE_STATUS == failed && -z ${NIX_GPU_CUDA_CAPABILITIES-} ]] || fail 'malformed query kept stale capabilities'
probe_output=8.9
probe_exit=1
gpu_probe_cuda
[[ $NIX_GPU_CUDA_PROBE_STATUS == failed && -z ${NIX_GPU_CUDA_CAPABILITIES-} ]] || fail 'failed query accepted'
NIX_GPU_CUDA_PROBE_STATUS=ok
NIX_GPU_CUDA_CAPABILITIES=6.1
unset -f nvidia-smi
saved_path=$PATH
PATH="$TMPDIR/no-tools"
gpu_probe_cuda
PATH=$saved_path
[[ $NIX_GPU_CUDA_PROBE_STATUS == unavailable && -z ${NIX_GPU_CUDA_CAPABILITIES-} ]] || fail 'missing query tool retained capabilities'

printf 'GPU_PROBE_OK\n'
