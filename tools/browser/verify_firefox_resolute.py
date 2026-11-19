#!/usr/bin/env python3
"""Check the Firefox desktop entry and its codec ABI as the image's desktop user."""
import ctypes
import os
from pathlib import Path
import shutil

from gi.repository import Gio


if os.geteuid() == 0:
    raise RuntimeError("Run the Firefox desktop check as the desktop user")
entries = {app.get_id(): app for app in Gio.AppInfo.get_all()}
app = entries["atlasa1-firefox.desktop"]
assert app.should_show() and app.get_commandline() == "atlasa1-firefox %U"
assert shutil.which(app.get_executable()) == "/usr/bin/atlasa1-firefox"
directory = Path("/opt/atlasa1-firefox/lib")
assert os.access(directory / "libt736_cedar_client.so", os.R_OK)
client = ctypes.CDLL(str(directory / "libt736_cedar_client.so"))
codec = ctypes.CDLL(str(directory / "libavcodec.so.62"))
utility = ctypes.CDLL("libavutil.so.60")
assert codec.avcodec_version() >> 16 == 62 and utility.avutil_version() >> 16 == 60


class AVCodec(ctypes.Structure):
    _fields_ = [("name", ctypes.c_char_p)]


codec.avcodec_find_decoder.argtypes = [ctypes.c_int]
codec.avcodec_find_decoder.restype = ctypes.POINTER(AVCodec)
for codec_id, name in ((27, b"h264_cedar"), (173, b"hevc_cedar")):
    selected = codec.avcodec_find_decoder(codec_id)
    assert selected and selected.contents.name == name, name
print("Desktop user sees the Firefox Cedar launcher; ABI 62/60 selects h264_cedar and hevc_cedar")
