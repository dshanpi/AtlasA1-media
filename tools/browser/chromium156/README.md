# Chromium 156 Cedar development candidate

Status: not built or hardware validated as a complete browser. Do not install
this as the production Chromium package or claim hardware decode acceptance.
The existing installed browser still uses FFmpeg software decoding.

`apply_candidate.py` targets exactly Chromium 156.0.8078.73. It adds a separate
`CedarVideoDecoder` identity and the Linux GPU media factory integration.
`client-preconnect.patch` is applied to a separate copy of `shm_v2/cedar_client.c`;
the shared production client is unchanged. The client alone cross-compiles with
`-Wall -Wextra -Werror`. Its constructor opt-in requires both
`T736_CEDAR_ENABLE=1` and `T736_CEDAR_CHROMIUM=1` and checks the executable and UID.
It is intended to connect before the GPU process sandbox, without disabling it.

Remaining acceptance includes building the full browser, sandboxed broker IPC,
Annex-B parameter sets, actual Cedar output, PTS, EOS, seek/reset and error
fallback, concurrent players, colours, A/V sync, 1080p60 and 4K performance.
The current candidate copies frames into owned I420 memory; it is not zero-copy.
