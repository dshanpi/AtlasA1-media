#!/bin/bash
# Build the selectable Cedar heap limit against the known T736 v29 tree.
set -eu -o pipefail

root=$(realpath "${1:?expected existing T736 build workspace}")
work=$(realpath -m "${2:?expected new output directory}")
jobs=${JOBS:-8}
patch_dir=$(cd -- "$(dirname -- "$0")/../patches/linux" && pwd)
old_src=$root/sources/work/linux-media-v28
old_out=$root/build/linux-media-v29
old_pvr=$root/sources/work/pvr-bxm-media-v29-24.2
kernel=$work/kout
release=6.18.63-t736-media-v30
test "$(cat "$old_out/include/config/kernel.release")" = 6.18.63-t736-media-v29
grep -qx 'CONFIG_CMA_SIZE_MBYTES=512' "$old_out/.config"
test "$(sha256sum "$old_src/drivers/misc/t736-cedar-wc.c" | cut -d' ' -f1)" = 5c9a73ed2d701bfb5905aa59da73f7f07f60b1c0636c6746f1b7110a68265402
case "$work/" in
    "$old_src/"*|"$old_out/"*|"$old_pvr/"*) echo "Output must be outside the baseline trees" >&2; exit 2 ;;
esac
mkdir -- "$work"
cp -a --reflink=auto -- "$old_src" "$work/linux"
cp -a --reflink=auto -- "$old_pvr" "$work/pvr-src"
mkdir "$kernel"
cp -- "$old_out/.config" "$kernel/.config"

patch --fuzz=0 -s -d "$work/linux" -p1 -i "$patch_dir/media-v30-cedar-heap-quota.patch"
export ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- KBUILD_BUILD_VERSION=30
"$work/linux/scripts/config" --file "$kernel/.config" --set-str LOCALVERSION -t736-media-v30
kmake=(make -C "$work/linux" O="$kernel" -j"$jobs")
"${kmake[@]}" olddefconfig
diff -u <(sed 's/CONFIG_LOCALVERSION="-t736-media-v29"/CONFIG_LOCALVERSION="-t736-media-v30"/' "$old_out/.config") "$kernel/.config"
"${kmake[@]}" Image allwinner/t736-gpu-candidate.dtb modules
DEB_BUILD_PROFILES=pkg.linux-upstream.nokernelheaders "${kmake[@]}" KDEB_PKGVERSION=6.18.63-30 bindeb-pkg

kbuild=$work/pvr-out/target_aarch64/kbuild
cd "$work/pvr-src"
while IFS= read -r -d '' path; do
    mkdir -p -- "$kbuild/$(dirname -- "$path")"
    ln -s -- "$work/pvr-src/$path" "$kbuild/$path"
done < <(find . -path ./build -prune -o -name '*.c' -type f -print0)
make -C "$work/pvr-src/build/linux/sunxi_linux" -j"$jobs" KERNELDIR="$kernel" OUT="$work/pvr-out" \
    ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- KERNEL_CC=aarch64-linux-gnu-gcc \
    KERNEL_LD=aarch64-linux-gnu-ld KERNEL_NM=aarch64-linux-gnu-gcc-nm \
    KERNEL_OBJCOPY=aarch64-linux-gnu-objcopy GPU_BUILD_TYPE=release BUILD=release \
    SUPPORT_LINUX_DVFS=0 SUPPORT_PDVFS=0 SUPPORT_DMA_FENCE=1 SUPPORT_BUFFER_SYNC=1

dtb=arch/arm64/boot/dts/allwinner/t736-gpu-candidate.dtb
cmp "$kernel/$dtb" "$old_out/$dtb"
cmp "$kernel/Module.symvers" "$old_out/Module.symvers"
test "$(cat "$kernel/include/config/kernel.release")" = "$release"
[[ $(modinfo -F vermagic "$kbuild/pvrsrvkm.ko") == "$release "* ]]
cd "$work"
deb="linux-image-${release}_6.18.63-30_arm64.deb"
test "$(dpkg-deb -f "$deb" Package)" = "linux-image-$release"
sha256sum "$deb" kout/arch/arm64/boot/Image "kout/$dtb" pvr-out/target_aarch64/kbuild/pvrsrvkm.ko > SHA256SUMS
