#!/usr/bin/env bash
# Minimal ARM64 SDL2 development sysroot for the private FFplay build.
set -euo pipefail
[[ $# == 1 ]] || { echo "Usage: $0 NEW_SYSROOT" >&2; exit 2; }
root=$(realpath -m "$1")
work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT
version=2.32.4+dfsg-1
origin=https://deb.debian.org/debian/pool/main/libs/libsdl2
cd "$work"
for pkg in libsdl2-2.0-0 libsdl2-dev; do
    if [[ -n ${ATLAS_SOURCE_CACHE:-} ]]; then
        cp "$ATLAS_SOURCE_CACHE/sdl/${pkg}_${version}_arm64.deb" "$pkg.deb"
    else
        curl --fail --location --retry 3 --output "$pkg.deb" "$origin/${pkg}_${version}_arm64.deb"
    fi
done
sha256sum --check <<'SUMS'
6312ccbc29645ac5cc9dde9f9ed8bd5c85a0233690c270c83c963b49f8cd49d5  libsdl2-2.0-0.deb
7def114ccf8fcbb67a2a326e7090ec0aa50074269e4e2108a23cf3328a3abc47  libsdl2-dev.deb
SUMS
mkdir -- "$root"
dpkg-deb -x libsdl2-2.0-0.deb "$root"
dpkg-deb -x libsdl2-dev.deb "$root"
export PKG_CONFIG_SYSROOT_DIR="$root"
export PKG_CONFIG_LIBDIR="$root/usr/lib/aarch64-linux-gnu/pkgconfig"
[[ $(pkg-config --modversion sdl2) == 2.32.4 ]]
pkg-config --cflags --libs sdl2 > sdl.flags
read -r -a flags < sdl.flags
printf '#include <SDL.h>\nint main(void) { return SDL_Init(0); }\n' > abi.c
aarch64-linux-gnu-gcc -I"$root/usr/include/aarch64-linux-gnu" -o abi-test abi.c "${flags[@]}" -Wl,--allow-shlib-undefined
readelf -d abi-test | grep -F 'Shared library: [libSDL2-2.0.so.0]'
