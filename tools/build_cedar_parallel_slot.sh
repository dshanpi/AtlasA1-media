#!/bin/bash
# Compile the opt-in parallel direct-slot library and exercise the actual Gst path.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
work=${1:?supply a fresh output directory}
mkdir -p "$work"
work=$(cd "$work" && pwd)
mkdir "$work/src"
cd "$work/src"
mkdir -p tools/browser/copy_candidate tests
cp "$root"/tools/browser/cedar_backend.{c,h} tools/browser/
cp "$root"/tools/browser/copy_candidate/cedar_parallel_copy.h tools/browser/copy_candidate/
cp "$root"/tests/test_cedar_{backend,parallel_direct}.c tests/
patch --fuzz=0 -p1 < "$root/patches/cedar/backend-parallel-direct-slot.patch"
sdk=${T736_TINA_SDK:-/home/ubuntu/t736-aiot/tina/out/t736/demo_aiot/buildroot/buildroot/host}
sysroot="$sdk/aarch64-buildroot-linux-gnu/sysroot"
export PKG_CONFIG_SYSROOT_DIR="$sysroot"
export PKG_CONFIG_LIBDIR="$sysroot/usr/lib/pkgconfig:$sysroot/usr/share/pkgconfig"
read -r -a includes <<< "$("$sdk/bin/pkg-config" --cflags gstreamer-app-1.0 gstreamer-video-1.0)"
read -r -a libs <<< "$("$sdk/bin/pkg-config" --libs gstreamer-app-1.0 gstreamer-video-1.0)"
common=(-std=c11 -Wall -Wextra -Werror -pthread)
cross="$sdk/bin/aarch64-none-linux-gnu-gcc"
"$cross" "${common[@]}" -O2 -fPIC -shared tools/browser/cedar_backend.c "${includes[@]}" "${libs[@]}" \
    -Wl,-z,relro,-z,now -o "$work/libcedar_backend.so"
hostincludes=()
for f in "${includes[@]}"; do
    if [[ $f == -I* ]]; then hostincludes+=(-idirafter "${f#-I}"); else hostincludes+=("$f"); fi
done
hostlibs=(-l:libgstapp-1.0.so.0 -l:libgstvideo-1.0.so.0 -l:libgstreamer-1.0.so.0
          -l:libgobject-2.0.so.0 -l:libglib-2.0.so.0)
export GST_PLUGIN_SYSTEM_PATH_1_0='' GST_PLUGIN_PATH_1_0='' GST_REGISTRY_1_0="$work/test-registry.bin"
export ASAN_OPTIONS=detect_leaks=0 UBSAN_OPTIONS=halt_on_error=1
for test in backend parallel_direct; do
    "$cross" "${common[@]}" -O2 "tests/test_cedar_$test.c" "${includes[@]}" "${libs[@]}" -o "$work/arm-$test"
    gcc "${common[@]}" -O1 -g -no-pie -fsanitize=address,undefined "tests/test_cedar_$test.c" \
        "${hostincludes[@]}" "${hostlibs[@]}" -o "$work/host-$test"
done
"$work/host-backend" > "$work/host-backend.log" 2>&1
qemu-aarch64-static -L "$sysroot" "$work/arm-backend" > "$work/arm-backend.log" 2>&1
# Only request CPU IDs available inside the build host's actual cpuset.
python3 - > "$work/test-cpu-masks" <<'PY'
import os
allowed = os.sched_getaffinity(0)
preferred = [n for n in (6, 7, 4, 5) if n in allowed]
for count in sorted({len(preferred), min(2, len(preferred))}, reverse=True):
    if count >= 2:
        print(count, ','.join(str(n) for n in preferred[:count]))
print(0, min(allowed))
PY
while read -r count cpus; do
    taskset -c "$cpus" "$work/host-parallel_direct" "$count" > "$work/host-$count.log" 2>&1
    taskset -c "$cpus" qemu-aarch64-static -L "$sysroot" "$work/arm-parallel_direct" "$count" > "$work/arm-$count.log" 2>&1
done < "$work/test-cpu-masks"
sha256sum "$work/libcedar_backend.so"
tail -qn 1 "$work"/*.log
