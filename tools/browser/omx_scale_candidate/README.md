# Decoder-side half-resolution output on AtlasA1

This experiment requests 1920×1080 decoded frames for an 8-bit 4:2:0
3840×2160 H.264 or HEVC source. It requires the native player and the explicit
environment setting `T736_CEDAR_PANEL=1920x1080`. A compressed-stream caps
filter checks the original dimensions after parsing. A separate check accepts
only a 1920×1080 visible crop from the private OMX output pool. The service
still imports the hardware buffers and copies the visible image into the
ordinary shared-memory frame. The retained instance is keyed by codec, source
dimensions and output mode.

In Tina's gst-omx decoder, the `scale` property is passed to
`OMX_IndexConfigCommonScale` when opening the component. In libcedarc,
`openmax/vdec/src/omx_vdec.c` forwards it to `AWOMX_IndexVendorSetScale`.
`omx_vdec_aw_decoder_linux.c` stores the selector in `mScale` and applies it
to both horizontal and vertical ratios in the decoder configuration. The
backend checks each output buffer's crop to verify what the component produced.

## Cross-build and transport test

Run on a Linux host with the project's configured FFmpeg 7.1.5 build, including
`libavcodec/elbg.o`, the Debian ARM64 cross-toolchain, QEMU AArch64 and the
Tina Buildroot SDK. Set `T736_TINA_SDK` to the SDK's `host` directory.

```sh
bash tools/browser/omx_scale_candidate/build_omx_panel.sh \
    tools/browser "$FFMPEG_BUILD" "$PWD/omx-scale-build"
```

The build emits the broker, backend, FFmpeg decoder and client, then tests
source/output geometry, pixels, PTS, short buffers and reuse with a simulated
backend on the host and under qemu-aarch64.

## Board measurement

Use a fresh v30 boot with a 256 MiB Cedar heap. Apply the candidate broker
and backend to the executable and libraries actually used by the active service.
The ELF loader path and effective systemd configuration can differ across media
images. Keep the original service limits and use private player libraries for
the test. The first run uses the 750-frame 3840×2160 HEVC fixture. A second
run of that exact video plus AAC exercises the same retained instance. Keep
the player, PowerVR renderer, refresh fix, CPU affinity, presentation tracer
and timing thresholds consistent with the full-size and client-filter runs.

Correlate the client pull and broker lease for 3840×2160 input with a
1920×1080 hardware frame, the actual decoder crop, the player filter size,
and the SDL presentation count. Record wall time, late frames, presentation
intervals and A/V skew. The GStreamer property and a successful open only
record a request. A test with a 1080p output raster measures 4K-source
playback on a 1080p display.

## One-shot board configuration on 2026-11-18

The test board booted `6.18.63-t736-media-v30` with a 256 MiB Cedar
heap and 512 MiB CMA. Its default eMMC boot entry was v29. The hardware
keeps retired decoder allocations until reboot, so the first 4K run used a
fresh v30 boot. The executable files for the test came from the root-owned
`/opt/t736-v30-omx-scale-test` directory. The board mounted `/run` with
`noexec`. Only temporary systemd configuration went under `/run/systemd/system`.

These are the active `BindReadOnlyPaths` source and destination pairs observed
for `t736-cedar.service` in that boot.

| File on the board | File as seen by the service |
| --- | --- |
| `/opt/t736-v30-omx-scale-test/bin/cedar-broker` | `/opt/t736-cedar-direct-test/bin/cedar-broker` |
| `/opt/t736-v30-omx-scale-test/lib/libcedar_backend.so` | `/opt/t736-cedar-direct-test/libcedar_backend.so` |
| `/opt/t736-cedar-direct-test/cedarc-4k.conf` | `/etc/cedarc.conf` |
| `/opt/t736-cedar-direct-test/libOmxVdec-4k.so` | `/opt/t736-cedar-wc-v5/lib/libOmxVdec.so` |

The board's broker received a 3840×2160 stream and reported a 1920×1080
visible crop in YV12 storage of 1920×1088. Matching the service's loaded
broker and backend hashes and checking this crop identifies the tested
path. [Board hashes and playback measurements](../../../evidence/media-v30-4k-omx-panel-20261118.json)
