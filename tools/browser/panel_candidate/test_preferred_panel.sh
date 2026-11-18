#!/bin/sh
# Tests actual client/broker code in one process with the software decoder stub.
set -eu
browser=$(cd "$(dirname "$0")/.." && pwd)
mkdir "$1"
stage=$(cd "$1" && pwd)
sh "$browser/../player/prepare_panel_sources.sh" "$stage/client"
for variant in legacy omx; do
    tree="$stage/$variant"
    mkdir -p "$tree/shm_v2"
    cp "$browser"/shm_v2/*.[ch] "$tree/shm_v2/"
    sed -i 's/\r$//' "$tree"/shm_v2/*.[ch]
    extra=''
    if [ "$variant" = omx ]; then
        awk '/^--- a\// { keep=($2=="a/shm_v2/cedar_broker.c" || $2=="a/shm_v2/cedar_protocol.h" || $2=="a/shm_v2/cedar_backend.h") } keep' \
            "$browser/omx_scale_candidate/omx-panel.patch" | patch --fuzz=0 -d "$tree" -p1
    else
        extra='-DTEST_LEGACY_BROKER'
    fi
    # The legacy and new headers name the same fourth uint32_t reserved and
    # flags respectively. The test-only alias lets the two TUs be included in
    # the existing harness without changing the real legacy broker.
    python3 - "$browser/../../tests/test_cedar_shm_transport.c" "$tree/baseline.inc" <<'PY'
from pathlib import Path
import sys
text = Path(sys.argv[1]).read_text()
text = text.replace('../tools/browser/shm_v2/cedar_broker.c', 'shm_v2/cedar_broker.c')
text = text.replace('#include "../tools/browser/shm_v2/cedar_client.c"', '''#ifdef TEST_LEGACY_BROKER
#define T736_OPEN_PANEL1080 1U
#define flags reserved
#endif
#include "../client/shm_v2/cedar_client.c"
#ifdef TEST_LEGACY_BROKER
#undef flags
#endif''')
Path(sys.argv[2]).write_text(text.replace('int main(void)', 'static int run_baseline(void)'))
PY
    cp "$browser/panel_candidate/test_preferred_panel.c" "$tree/"
    for arch in host arm64; do
        bin="$tree/$arch"
        if [ "$arch" = host ]; then
            gcc -std=gnu11 -O2 -fsanitize=address,undefined -no-pie -pthread $extra "$tree/test_preferred_panel.c" -o "$bin"
            "$bin" > "$bin.log" 2>&1
        else
            aarch64-linux-gnu-gcc -std=gnu11 -O3 -pthread $extra "$tree/test_preferred_panel.c" -o "$bin"
            qemu-aarch64-static -L /usr/aarch64-linux-gnu "$bin" > "$bin.log" 2>&1
        fi
        tail -1 "$bin.log"
    done
done
