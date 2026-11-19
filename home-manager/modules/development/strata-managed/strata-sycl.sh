#!/usr/bin/env bash
# strata-sycl.sh: the SYCL-built engine as a drop-in `exe` for serve/server.py (--engine strata). The port's binary
# needs the oneAPI runtime of the dev image, so this runs it there with stdin/stdout attached (the serve protocol is
# lines on those pipes) and stderr going to the server's log. Paths in the config's args are the container's:
# the data root is mounted at /work.
#   STRATA_SYCL_ROOT   explicit host directory mounted at /work
#   STRATA_SYCL_IMAGE  the runtime image                      (default: strata-sycl-dev)
#   STRATA_SYCL_BIN    explicit host-absolute selected engine binary
#   STRATA_SYCL_CWD    explicit normalized /work working directory, including runtime mirrors
#   STRATA_SYCL_HERE   explicit selected source engine root (flat checkout or engine/)
#   STRATA_SYCL_NAME   the container's name                   (default: strata-sycl-serve)
#   STRATA_SYCL_SHM    1 (default): the host's /dev/shm is the container's /dev/shm. Pictures: the server (on the host) writes the
#                      image embeddings of a request into /dev/shm and names that file on the engine's GENI line, so the engine in
#                      the container must see the same file. 0: the container keeps a private /dev/shm.
# Passed into the container: every variable of this script's environment that starts with STRATA_ (the config's
# "env" block arrives that way: the server puts it in the engine's environment), ONEAPI_ (level_zero:* for a
# two-card split, #423), UR_, IGC_, SYCL_ or ZES_. The port's own defaults (below) are overridden the same way,
# e.g. "env": {"STRATA_VERIFY_NO_HOST": "0"} in the config.
set -euo pipefail
here=$(cd "${STRATA_SYCL_HERE:?managed engine root is required}" && pwd -P)
root=$(cd "${STRATA_SYCL_ROOT:?managed mount is required}" && pwd -P)
mount_prefix=${root%/}
if [ -n "${STRATA_SYCL_CWD:-}" ]; then
    repo_in=$STRATA_SYCL_CWD
    case "$repo_in" in
        /work|/work/*) ;;
        *) printf '%s\n' "STRATA_SYCL_CWD must be within /work" >&2; exit 1 ;;
    esac
    case "/${repo_in#/}/" in
        */../*|*/./*) printf '%s\n' "STRATA_SYCL_CWD must be normalized" >&2; exit 1 ;;
    esac
else
    case "$here" in
        "$root") repo_in=/work ;;
        "$mount_prefix"/*) repo_in=/work/${here#"$mount_prefix"/} ;;
        *) printf '%s\n' "$here is outside the SYCL mount $root; set STRATA_SYCL_CWD for a mounted runtime mirror" >&2; exit 1 ;;
    esac
fi
name=${STRATA_SYCL_NAME:-strata-sycl-serve}
docker rm -f "$name" >/dev/null 2>&1 || true              # a container left behind by a killed server
args=""
for a in "$@"; do args+=" $(printf '%q' "$a")"; done
binary=${STRATA_SYCL_BIN:-build-sycl-aot/strata}
case "$binary" in
    /*) ;;
    *) binary="$repo_in/${binary#./}" ;;
esac
case "$binary" in
    "$root") binary_in=/work ;;
    "$mount_prefix"/*) binary_in=/work/${binary#"$mount_prefix"/} ;;
    *) printf '%s\n' "$binary is outside the SYCL mount $root" >&2; exit 1 ;;
esac
printf -v command 'cd %q && exec %q' "$repo_in" "$binary_in"
# the port's run-time switches: the device-built verify plan, and no host handshakes in it. NO_HOST is for a card on
# the xe driver (the host<->GPU flag stores are not visible there); an i915 card (Arc A-series) runs without it
# (docs/INTEL.md)
# STRATA_CACHE_DIR: the engine's measurements that outlive a run (the int8 prompt experts' crossover, measured at
# the first prompt of each format: ~1.4 s of a B70's first 2K prompt) - under the mounted data root, not in the
# throwaway container's home
declare -A setting=([STRATA_VERIFY_DEVICE_PLAN]=1 [STRATA_VERIFY_NO_HOST]=1 [STRATA_STAGER_THREADS]=12
                    [STRATA_CACHE_DIR]=/work/.strata-cache)
while IFS= read -r k; do
    case "$k" in
        STRATA_SYCL_*) ;;                                 # this script's own settings
        STRATA_*|ONEAPI_*|UR_*|IGC_*|SYCL_*|ZES_*|NEOReadDebugKeys|OverrideDefaultFP64Settings) setting[$k]=${!k} ;;
    esac
done < <(compgen -e)
envs=()
for k in "${!setting[@]}"; do
    # an empty value means "not set", so it is not passed on. A value of 0 is a real value
    # (e.g. STRATA_PREFILL_MMQ=0 selects the FP16 prompt path) and is passed through verbatim.
    case "${setting[$k]}" in "") ;; *) envs+=(-e "$k=${setting[$k]}") ;; esac
done
shm=()
if [ "${STRATA_SYCL_SHM:-1}" != 0 ] && [ -d /dev/shm ]; then shm=(-v /dev/shm:/dev/shm); fi
exec docker run --rm -i --name "$name" --device /dev/dri --oom-score-adj 1000 --stop-timeout 30 --no-healthcheck \
    --ulimit memlock=-1 \
    -v "$root:/work" \
    "${shm[@]}" \
    "${envs[@]}" \
    "${STRATA_SYCL_IMAGE:-strata-sycl-dev}" \
    "$command$args"
