#!/usr/bin/env python3
"""Run bounded, non-display T736 Cedar/GStreamer media acceptance tests.

The tool intentionally reports ``pending`` when a required fixture, GStreamer
component, encoder, or zero-copy proof is absent.  It never treats software
fallback (decodebin, avdec_*, or a successful process exit without frames) as
hardware acceptance.  Decoded output ends in fakesink. Encoded output is verified in a temporary file.
"""
from __future__ import annotations

import argparse
from fractions import Fraction
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
import tempfile
import time
from typing import Any

SCHEMA = 1
STATUSES = ("pass", "fail", "pending")
FPS_RE = re.compile(r"(?:rendered|frames)[:= ]+([0-9]+)")
DROP_RE = re.compile(r"(?:dropped|drop)[:= ]+([0-9]+)")
FPS_VALUE_RE = re.compile(r"(?:average:\s*|avg[:= ]+)([0-9]+(?:\.[0-9]+)?)", re.I)


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


def make_pipeline(path: Path, codec: str, decoder: str, *, caps: str, paced: bool) -> str:
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
    sync = "true" if paced else "false"
    return (f"{source} ! {decoder} ! {caps} ! fpsdisplaysink "
            f"text-overlay=false video-sink=fakesink sync={sync}")


def video_info(path: Path, *, count_frames: bool = False) -> dict:
    cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0"]
    if count_frames:
        cmd.append("-count_frames")
    cmd.extend(["-show_entries", "stream=width,height,codec_name,avg_frame_rate,nb_read_frames",
                "-of", "json", str(path)])
    data = subprocess.check_output(cmd, text=True, timeout=60)
    return json.loads(data)["streams"][0]


def cedar_irqs() -> int | None:
    try:
        lines = Path("/proc/interrupts").read_text().splitlines()
    except OSError:
        return None
    for line in lines:
        if "t736-cedar-wc" in line:
            match = re.search(r":\s*((?:\d+\s+)+)", line)
            return sum(map(int, match[1].split())) if match else None
    return None


def run_pipeline(gst_launch: str, pipeline: str, timeout_s: float) -> dict[str, Any]:
    env = os.environ.copy()
    env.setdefault("GST_DEBUG", "2")
    env["LC_ALL"] = "C"
    argv = [gst_launch, "-v", "-e"] + shlex.split(pipeline, posix=True)
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
    values = pattern.findall(text)
    return float(values[-1]) if values else None


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
    try:
        info = video_info(path)
        fps = float(Fraction(info["avg_frame_rate"]))
    except (OSError, KeyError, IndexError, ValueError, ZeroDivisionError, subprocess.SubprocessError) as exc:
        return result("pending", f"could not verify fixture metadata: {exc}", test=name)
    size = (info["width"], info["height"])
    wanted = {"1080p60": (1920, 1080), "4k": (3840, 2160)}.get(name)
    if (wanted and size != wanted) or info["codec_name"] != codec or fps + .15 < expected_fps:
        return result("pending", "fixture dimensions, frame rate or codec do not match the test",
                      test=name, fixture_info=info)
    caps = f"video/x-raw,width={size[0]},height={size[1]}"
    pipeline = make_pipeline(path, codec, decoder, caps=caps, paced=sustained)
    before = cedar_irqs()
    run = run_pipeline(args.gst_launch, pipeline, timeout_s or args.timeout)
    after = cedar_irqs()
    irqs = after - before if after is not None and before is not None else None
    observation = dict(test=name, fixture=str(path), fixture_info=info, expected_fps=expected_fps,
                       pipeline=pipeline, irq_delta=irqs, **run)
    if run["timed_out"] and not sustained:
        return result("fail", "pipeline timed out", **observation)
    if not run["timed_out"] and run["returncode"] != 0:
        return result("fail", "pipeline returned an error", **observation)
    if sustained and run["elapsed_seconds"] < timeout_s - .5:
        return result("pending", "fixture ended before the target wall time", **observation)
    frames, dropped, observed = run["frames"], run["dropped"], run["fps"]
    if not frames or observed is None or dropped is None or irqs is None:
        return result("pending", "frame/drop/rate/IRQ evidence incomplete", **observation)
    if dropped > 0 or irqs < .95 * frames or observed < .98 * expected_fps:
        return result("fail", "frame drops, low throughput or missing hardware progress", **observation)
    if sustained and frames < .98 * max(1, timeout_s - 2) * expected_fps:
        return result("fail", "insufficient frames over the long-play interval", **observation)
    return result("pass", "verified OMX output dimensions, frame counters and VE IRQ progress",
                  **observation)


def run_encoder(path: Path | None, codec: str, args: argparse.Namespace,
                elements: dict[str, bool]) -> dict[str, Any]:
    if path is None:
        return result("pending", "encoder fixture was not supplied", test="encode")
    ok, fixture_reason = fixture_ok(path)
    if not ok:
        return result("pending", fixture_reason, test="encode", fixture=str(path))
    parser, _, encoder = codec_elements(codec)
    missing = [element for element in (encoder, parser, "y4mdec", "videoconvert", "filesink")
               if not elements.get(element, False)]
    if missing:
        return result("pending", "required encoder pipeline elements are unavailable", test="encode",
                      fixture=str(path), missing=missing)
    try:
        source = video_info(path, count_frames=True)
        expected = int(source["nb_read_frames"])
    except (OSError, KeyError, IndexError, ValueError, subprocess.SubprocessError) as exc:
        return result("pending", f"Y4M input could not be verified: {exc}", test="encode")
    if source["codec_name"] != "rawvideo" or expected < 1:
        return result("pending", "encoder test requires raw Y4M input frames", test="encode")
    with tempfile.TemporaryDirectory(prefix="t736-encode-") as directory:
        encoded = Path(directory) / ("sample.h264" if codec == "h264" else "sample.h265")
        media = "video/x-h264" if codec == "h264" else "video/x-h265"
        pipeline = (f"filesrc location={shlex.quote(str(path))} ! y4mdec ! videoconvert ! "
                    f"{encoder} ! {parser} ! {media},stream-format=byte-stream,alignment=au ! "
                    f"filesink location={shlex.quote(str(encoded))}")
        run = run_pipeline(args.gst_launch, pipeline, args.timeout)
        fields = dict(test="encode", fixture=str(path), input_frames=expected, pipeline=pipeline, **run)
        if run["timed_out"] or run["returncode"] != 0:
            return result("fail", "encoder pipeline did not finish successfully", **fields)
        try:
            decoded = video_info(encoded, count_frames=True)
            bytes_encoded = encoded.stat().st_size
            frames = int(decoded["nb_read_frames"])
        except (OSError, KeyError, IndexError, ValueError, subprocess.SubprocessError) as exc:
            return result("fail", f"encoded output could not be decoded: {exc}", **fields)
        fields.update(decoded=decoded, bytes_encoded=bytes_encoded)
        if (frames != expected or decoded["codec_name"] != codec or bytes_encoded <= 0
                or any(decoded[k] != source[k] for k in ("width", "height"))):
            return result("fail", "encoded stream readback differs from the input format/count", **fields)
        return result("pass", "explicit OMX encoder output decoded at the expected size and count", **fields)


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
             "omxh265enc", "fpsdisplaysink", "fakesink", "y4mdec", "videoconvert", "filesink"]
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
    if not device_ready:
        for name in ("1080p60", "4k", "long_play", "stream_switch", "encode", "zero_copy"):
            record["tests"][name] = result("pending", "Cedar device access is required")
        write_record(args.output, record)
        return 2
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
