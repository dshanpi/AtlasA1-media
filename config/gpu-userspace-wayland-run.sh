#!/bin/sh
set -eu
. /opt/atlasa1-img-wayland/session.env
python3 "$T736_IMG_ROOT/bin/gpu-runtime-view" --prefix "$T736_IMG_ROOT" --verify >/dev/null
exec "$@"
