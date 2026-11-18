#!/usr/bin/env python3
"""Run bounded, non-display T736 Cedar/GStreamer media acceptance tests.

The tool intentionally reports ``pending`` when a required fixture, GStreamer
component, encoder, or zero-copy proof is absent.  It never treats software
fallback (decodebin, avdec_*, or a successful process exit without frames) as
hardware acceptance.  All pipelines end in fakesink and do not touch HDMI/X11.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import stat
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import time
from typing import Any

SCHEMA = 1
STATUSES = ("pass", "fail", "pending")
FPS_RE = re.compile(r"(?:rendered|frames)[:= ]+([0-9]+)")
DROP_RE = re.compile(r"(?:dropped|drop)[:= ]+([0-9]+)")
# ``fpsdisplaysink`` prints decimal rates such as ``average: 59.98 fps``.
# Match both the decimal point and the trailing ``fps`` form.
FPS_VALUE_RE = re.compile(
    r"(?:fps|avg)[^0-9]*([0-9]+(?:\.[0-9]+)?)|"
    r"([0-9]+(?:\.[0-9]+)?)\s*fps", re.I)


def result(status: str, reason: str, **fields: Any) -> dict[str, Any]:
    if status not in STATUSES:
        raise ValueError(status)
    value = {"status": status, "reason": reason}
    value.update(fields)
    return value


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def inspect_element(gst_inspect: str, element: str) -> tuple[bool, str]:
    try:
        p = subprocess.run([gst_inspect, element], text=True, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=15, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, repr(exc)
    return p.returncode == 0, p.stdout[-4000:]


def fixture_ok(path: Path) -> tuple[bool, str]:
    if not path:
        return False, "fixture path was not supplied"
    if not path.is_file():
        return False, f"fixture does not exist: {path}"
    try:
        size = path.stat().st_size
    except OSError as exc:
        return False, repr(exc)
    if size <= 0:
        return False, f"fixture is empty: {path}"
    return True, f"{size} bytes"


def codec_elements(codec: str) -> tuple[str, str, str]:
    if codec == "h264":
        return "h264parse", "omxh264dec", "omxh264enc"
    if codec in ("hevc", "h265"):
        return "h265parse", "omxhevcvideodec", "omxh265enc"
    raise ValueError(f"unsupported codec: {codec}")


def make_pipeline(path: Path, codec: str, decoder: str, *, loop: bool = False) -> str:
    parser, _, _ = codec_elements(codec)
    # Annex-B fixtures are preferred because the parser/decoder is explicit.
    # MP4/MKV still use a demuxer but never decodebin, so a software decoder
    # cannot be selected silently.
    suffix = path.suffix.lower()
    if suffix in (".mp4", ".mov"):
        demux = "qtdemux"
    elif suffix in (".mkv", ".webm"):
        demux = "matroskademux"
    else:
        demux = "identity"
    if demux == "identity":
        source = f"filesrc location={shlex.quote(str(path))} ! {parser}"
    else:
        source = f"filesrc location={shlex.quote(str(path))} ! {demux} ! {parser}"
    # fakesink keeps the test headless.  fpsdisplaysink supplies frame and
    # drop counters; sync=false measures decoder throughput without display.
    repeat = " ! queue max-size-buffers=0 max-size-bytes=0 max-size-time=0" if loop else ""
    return (f"{source}{repeat} ! {decoder} ! video/x-raw ! fpsdisplaysink "
            "text-overlay=false video-sink=fakesink sync=false signal-fps-measurements=true")


def run_pipeline(gst_launch: str, pipeline: str, timeout_s: float) -> dict[str, Any]:
    env = os.environ.copy()
    env.setdefault("GST_DEBUG", "2")
    argv = [gst_launch, "-e"] + shlex.split(pipeline, posix=True)
    started = time.monotonic()
    try:
        proc = subprocess.run(argv, text=True, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=timeout_s,
                              check=False, env=env)
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        output = (exc.stdout or "")
        if isinstance(output, bytes):
            output = output.decode(errors="replace")
        return {"returncode": None, "timed_out": True,
                "elapsed_seconds": time.monotonic() - started,
                "frames": parse_int(output, FPS_RE),
                "dropped": parse_int(output, DROP_RE),
                "fps": parse_float(output, FPS_VALUE_RE),
                "log_tail": output[-8000:]}
    return {"returncode": proc.returncode, "timed_out": timed_out,
            "elapsed_seconds": time.monotonic() - started,
            "frames": parse_int(proc.stdout, FPS_RE),
            "dropped": parse_int(proc.stdout, DROP_RE),
            "fps": parse_float(proc.stdout, FPS_VALUE_RE),
            "log_tail": proc.stdout[-8000:]}


def parse_int(text: str, pattern: re.Pattern[str]) -> int | None:
    values = [int(v) for v in pattern.findall(text)]
    return values[-1] if values else None


def parse_float(text: str, pattern: re.Pattern[str]) -> float | None:
    values = []
    for match in pattern.findall(text):
        # FPS_VALUE_RE has two capture groups so accept either form.
        if isinstance(match, tuple):
            match = next((value for value in match if value), "")
        if match:
            values.append(float(match))
    return values[-1] if values else None


def run_decode(name: str, path: Path | None, codec: str, expected_fps: float,
               args: argparse.Namespace, elements: dict[str, bool],
               *, timeout_s: float | None = None, sustained: bool = False) -> dict[str, Any]:
    if path is None:
        return result("pending", "fixture was not supplied", test=name)
    ok, fixture_reason = fixture_ok(path)
    if not ok:
        return result("pending", fixture_reason, test=name, fixture=str(path))
    parser, decoder, _ = codec_elements(codec)
    missing = [e for e in (parser, decoder, "fpsdisplaysink", "fakesink") if not elements.get(e, False)]
    if missing:
        return result("pending", "missing GStreamer elements", test=name,
                      fixture=str(path), missing=missing)
    pipeline = make_pipeline(path, codec, decoder)
    run = run_pipeline(args.gst_launch, pipeline, timeout_s or args.timeout)
    frames = run.get("frames") or 0
    dropped = run.get("dropped")
    if run["timed_out"] and not sustained:
        return result("fail", "pipeline exceeded timeout", test=name, fixture=str(path),
                      expected_fps=expected_fps, pipeline=pipeline, **run)
    if run["timed_out"] and sustained:
        if frames <= 0 or run.get("dropped") not in (None, 0):
            return result("fail", "long-play timeout had no clean frame stream", test=name, fixture=str(path),
                          expected_fps=expected_fps, pipeline=pipeline, **run)
        observed = run.get("fps")
        if observed is None:
            return result("pending", "long-play ran for the target interval but fps was not reported",
                          test=name, fixture=str(path), expected_fps=expected_fps,
                          pipeline=pipeline, **run)
        if observed + 1.0 < expected_fps:
            return result("fail", "long-play observed decoder rate below target", test=name,
                          fixture=str(path), expected_fps=expected_fps, observed_fps=observed,
                          pipeline=pipeline, **run)
        return result("pass", "pipeline sustained the target interval with no reported drops",
                      test=name, fixture=str(path), expected_fps=expected_fps,
                      observed_fps=observed, pipeline=pipeline, **run)
    if run["returncode"] != 0:
        return result("fail", "GStreamer pipeline failed", test=name, fixture=str(path),
                      expected_fps=expected_fps, pipeline=pipeline, **run)
    if frames <= 0:
        return result("pending", "pipeline exited without measurable rendered frames",
                      test=name, fixture=str(path), expected_fps=expected_fps,
                      pipeline=pipeline, **run)
    # A file may contain fewer frames than a requested rate.  We therefore
    # record the observed rate but only pass when fpsdisplaysink reported a
    # stable rate and no drops.  The JSON includes all raw data for review.
    observed = run.get("fps")
    if dropped not in (None, 0):
        return result("fail", "decoder reported dropped frames", test=name, fixture=str(path),
                      expected_fps=expected_fps, pipeline=pipeline, **run)
    if observed is None:
        return result("pending", "rendered frames observed but fps was not reported",
                      test=name, fixture=str(path), expected_fps=expected_fps,
                      pipeline=pipeline, **run)
    if observed + 1.0 < expected_fps:
        return result("fail", "observed decoder rate below target", test=name, fixture=str(path),
                      expected_fps=expected_fps, observed_fps=observed,
                      pipeline=pipeline, **run)
    return result("pass", "explicit hardware decoder pipeline rendered frames with no drops",
                  test=name, fixture=str(path), expected_fps=expected_fps,
                  observed_fps=observed, pipeline=pipeline, **run)


def run_encoder(path: Path | None, codec: str, args: argparse.Namespace,
                elements: dict[str, bool]) -> dict[str, Any]:
    if path is None:
        return result("pending", "encoder fixture was not supplied", test="encode")
    ok, fixture_reason = fixture_ok(path)
    if not ok:
        return result("pending", fixture_reason, test="encode", fixture=str(path))
    _, _, encoder = codec_elements(codec)
    missing = [e for e in (encoder, "videotestsrc", "fakesink") if not elements.get(e, False)]
    if missing:
        return result("pending", "vendor encoder is unavailable", test="encode",
                      fixture=str(path), missing=missing)
    # Verify the input can be driven through a raw source and the vendor
    # encoder.  The file is only used to make the test input explicit.
    pipeline = ("videotestsrc num-buffers=120 ! video/x-raw,width=1920,height=1080,"
                "framerate=60/1,format=NV12 ! " + encoder + " ! fakesink sync=false")
    run = run_pipeline(args.gst_launch, pipeline, args.timeout)
    if run["timed_out"] or run["returncode"] != 0:
        return result("fail", "vendor encoder pipeline failed", test="encode",
                      fixture=str(path), pipeline=pipeline, **run)
    return result("pass", "vendor encoder pipeline completed", test="encode",
                  fixture=str(path), pipeline=pipeline, **run)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--video1080p60", type=Path)
    ap.add_argument("--video4k", type=Path)
    ap.add_argument("--long-input", type=Path)
    ap.add_argument("--switch-a", type=Path)
    ap.add_argument("--switch-b", type=Path)
    ap.add_argument("--switch-command", help="same-process switch helper; must print T736_SWITCH_FRAMES=<n> and T736_SWITCH_DROPS=<n>")
    ap.add_argument("--encode-input", type=Path)
    ap.add_argument("--codec", choices=("h264", "hevc"), default="h264")
    ap.add_argument("--long-seconds", type=float, default=600.0)
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--gst-launch", default="gst-launch-1.0")
    ap.add_argument("--gst-inspect", default="gst-inspect-1.0")
    ap.add_argument("--skip-zero-copy", action="store_true")
    args = ap.parse_args()
    if args.output.exists():
        ap.error(f"refusing to overwrite {args.output}")
    record: dict[str, Any] = {"schema": SCHEMA, "kind": "t736-media-acceptance",
                              "started_unix": time.time(), "host": platform.node(),
                              "tests": {}, "status": "pending"}
    required_cmds = [args.gst_launch, args.gst_inspect]
    missing_cmds = [c for c in required_cmds if not command_exists(c)]
    device_paths = ("/dev/cedar_dev", "/dev/dma_heap/t736-ve")
    devices = {}
    for device in device_paths:
        path = Path(device)
        try:
            mode = path.stat().st_mode
            devices[device] = {"exists": True, "character_device": stat.S_ISCHR(mode),
                               "readable": os.access(path, os.R_OK), "writable": os.access(path, os.W_OK),
                               "mode": oct(mode & 0o7777)}
        except OSError as exc:
            devices[device] = {"exists": False, "error": repr(exc)}
    record["preflight"] = {"commands": {c: command_exists(c) for c in required_cmds},
                            "devices": devices}
    if missing_cmds:
        record["tests"]["preflight"] = result("pending", "GStreamer tools are unavailable",
                                                missing=missing_cmds)
        record["status"] = "pending"
        write_record(args.output, record)
        return 2
    names = ["h264parse", "h265parse", "omxh264dec", "omxhevcvideodec", "omxh264enc",
             "omxh265enc", "fpsdisplaysink", "fakesink", "videotestsrc"]
    elements: dict[str, bool] = {}
    inspect_tail: dict[str, str] = {}
    for element in names:
        elements[element], inspect_tail[element] = inspect_element(args.gst_inspect, element)
    record["preflight"]["elements"] = elements
    record["preflight"]["inspect_tail"] = inspect_tail
    device_ready = all(value.get("exists") and value.get("character_device")
                       and value.get("readable") and value.get("writable")
                       for value in record["preflight"]["devices"].values())
    if not device_ready:
        record["tests"]["preflight"] = result("pending", "Cedar device nodes are missing or inaccessible")
    else:
        record["tests"]["preflight"] = result("pass", "Cedar device nodes and GStreamer tools found")
    record["tests"]["1080p60"] = run_decode("1080p60", args.video1080p60, args.codec,
                                               60.0, args, elements)
    record["tests"]["4k"] = run_decode("4k", args.video4k, args.codec, 30.0, args, elements)
    if args.long_input is None:
        record["tests"]["long_play"] = result("pending", "long-play fixture was not supplied", test="long_play")
    else:
        record["tests"]["long_play"] = run_decode("long_play", args.long_input, args.codec,
                                                    24.0, args, elements,
                                                    timeout_s=args.long_seconds, sustained=True)
        if record["tests"]["long_play"]["status"] == "pass":
            record["tests"]["long_play"]["duration_target_seconds"] = args.long_seconds
    if args.switch_a is None or args.switch_b is None:
        record["tests"]["stream_switch"] = result("pending", "two switch fixtures were not supplied", test="stream_switch")
    elif not args.switch_command:
        # Re-opening two sessions is useful smoke coverage but is not a stream
        # switch. Keep the acceptance item pending until a same-process helper
        # exercises decoder flush/reconfigure and reports its counters.
        first = run_decode("switch_a_reopen", args.switch_a, args.codec, 24.0, args, elements)
        second = run_decode("switch_b_reopen", args.switch_b, args.codec, 24.0, args, elements)
        record["tests"]["stream_switch"] = result("pending",
            "same-process switch helper was not supplied; sequential reopen is smoke coverage",
            test="stream_switch", reopen_a=first, reopen_b=second)
    else:
        env = os.environ.copy()
        env.update({"T736_SWITCH_A": str(args.switch_a), "T736_SWITCH_B": str(args.switch_b),
                    "T736_SWITCH_CODEC": args.codec})
        try:
            proc = subprocess.run(args.switch_command, shell=True, executable="/bin/sh",
                                  text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  timeout=args.timeout, check=False, env=env)
            switch_output = proc.stdout
            frames = parse_int(switch_output, re.compile(r"T736_SWITCH_FRAMES=([0-9]+)"))
            drops = parse_int(switch_output, re.compile(r"T736_SWITCH_DROPS=([0-9]+)"))
            if proc.returncode != 0:
                record["tests"]["stream_switch"] = result("fail", "same-process switch helper failed",
                    test="stream_switch", command=args.switch_command, returncode=proc.returncode,
                    frames=frames, dropped=drops, log_tail=switch_output[-8000:])
            elif frames is None or drops is None:
                record["tests"]["stream_switch"] = result("pending",
                    "switch helper did not emit required frame/drop counters", test="stream_switch",
                    command=args.switch_command, returncode=proc.returncode, log_tail=switch_output[-8000:])
            elif frames <= 0 or drops != 0:
                record["tests"]["stream_switch"] = result("fail", "switch helper reported dropped or zero frames",
                    test="stream_switch", command=args.switch_command, frames=frames, dropped=drops,
                    log_tail=switch_output[-8000:])
            else:
                record["tests"]["stream_switch"] = result("pass",
                    "same-process switch helper completed with no reported drops", test="stream_switch",
                    command=args.switch_command, returncode=proc.returncode, frames=frames,
                    dropped=drops, log_tail=switch_output[-8000:])
        except subprocess.TimeoutExpired as exc:
            output = exc.stdout or ""
            if isinstance(output, bytes):
                output = output.decode(errors="replace")
            record["tests"]["stream_switch"] = result("fail", "same-process switch helper timed out",
                test="stream_switch", command=args.switch_command, log_tail=output[-8000:])
    record["tests"]["encode"] = run_encoder(args.encode_input, args.codec, args, elements)
    if args.skip_zero_copy:
        record["tests"]["zero_copy"] = result("pending", "zero-copy test was explicitly skipped", test="zero_copy")
    else:
        record["tests"]["zero_copy"] = result("pending",
            "no DMABUF/caps trace was supplied; fakesink RAM output is not zero-copy proof",
            test="zero_copy", required="GST_DEBUG caps with video/x-raw(memory:DMABuf) and fd lifecycle evidence")
    statuses = [v["status"] for v in record["tests"].values()]
    record["status"] = "fail" if "fail" in statuses else "pending" if "pending" in statuses else "pass"
    record["completed_unix"] = time.time()
    write_record(args.output, record)
    print(json.dumps({"status": record["status"], "output": str(args.output),
                      "tests": {k: v["status"] for k, v in record["tests"].items()}},
                   ensure_ascii=False))
    return 0 if record["status"] == "pass" else 2


def write_record(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
