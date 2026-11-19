#!/usr/bin/env bash
# Diagnostic only: capture existing DRM/DE tracepoints during the DMA-BUF probe.
# Traced measurements are for attribution, not playback acceptance.
set -euo pipefail
[[ $EUID == 0 && $# == 4 ]] || { echo "Usage (root): $0 PROBE_DIR CLIP h264|hevc NEW_PREFIX" >&2; exit 2; }
here=$(cd "$(dirname "$0")" && pwd)
prefix=$(realpath -m "$4")
for suffix in log trace stats present.tsv stages.tsv; do test ! -e "$prefix.$suffix"; done
mountpoint -q /sys/kernel/tracing || mount -t tracefs tracefs /sys/kernel/tracing
instance=/sys/kernel/tracing/instances/atlasa1-media-$$
mkdir "$instance"
cleanup() {
    set +o noclobber
    echo 0 >"$instance/tracing_on"
    echo 0 >"$instance/events/enable"
    rmdir "$instance"
}
trap cleanup EXIT
echo 0 >"$instance/tracing_on"
echo mono >"$instance/trace_clock"
echo 8192 >"$instance/buffer_size_kb"
echo 1 >"$instance/events/drm/enable"
echo 1 >"$instance/events/sunxi_drm_trace/enable"
if [[ ${ATLAS_TRACE_FENCES:-0} == 1 ]]; then
    printf '%s\n' drm_atomic_helper_wait_for_fences drm_atomic_helper_wait_for_dependencies \
        sunxi_drm_atomic_helper_commit >"$instance/set_ftrace_filter"
    echo function_graph >"$instance/current_tracer"
    echo 1 >"$instance/options/funcgraph-abstime"
    echo 1 >"$instance/options/sleep-time"
fi
echo 1 >"$instance/tracing_on"
status=0
ATLAS_PRESENT_TIMING="$prefix.present.tsv" ATLAS_DMA_TIMING="$prefix.stages.tsv" \
    bash "$here/run_gnome_dmabuf_probe.sh" "$1" "$2" "$3" "$prefix.log" || status=$?
echo 0 >"$instance/tracing_on"
set -o noclobber
cat "$instance/trace" >"$prefix.trace"
for stats in "$instance"/per_cpu/cpu*/stats; do
    echo "$stats"
    cat "$stats"
done >"$prefix.stats"
exit "$status"
