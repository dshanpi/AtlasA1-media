#!/usr/bin/env python3
"""Apply the opt-in Cedar candidate to a Chromium 156.0.8078.73 source tree.

This is a development adapter, not an accepted browser release. Run on an
isolated source tree; preserve the source archive and distribution patch list.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('source', type=Path)
args = p.parse_args()
root = args.source.resolve(strict=True)
here = Path(__file__).resolve().parent
assert (root / 'chrome/VERSION').read_text().splitlines() == [
    'MAJOR=156', 'MINOR=0', 'BUILD=8078', 'PATCH=73']
marker = root / 'atlasa1-cedar-candidate.json'
assert not marker.exists(), 'candidate is already staged'
records = {}
changes = {}

def replace(name, old, new):
    path = root / name
    text = changes.get(name, path.read_text())
    assert text.count(old) == 1, (name, 'source context changed')
    changes[name] = text.replace(old, new)

replace('media/base/decoder.h',
        '  kMaxValue = kVideoToolbox',
        '  kCedar = 20,  // AtlasA1 Cedar broker (downstream)\n  kMaxValue = kCedar')
replace('media/base/decoder.cc',
        '    case VideoDecoderType::kVideoToolbox:\n      return "VideoToolboxVideoDecoder";',
        '    case VideoDecoderType::kVideoToolbox:\n      return "VideoToolboxVideoDecoder";\n'
        '    case VideoDecoderType::kCedar:\n      return "CedarVideoDecoder";')
replace('tools/metrics/histograms/enums.xml',
        '  <int value="19" label="VideoToolbox Video Decoder"/>',
        '  <int value="19" label="VideoToolbox Video Decoder"/>\n'
        '  <int value="20" label="AtlasA1 Cedar Video Decoder"/>')
name = 'media/mojo/services/gpu_mojo_media_client_linux.cc'
replace(name, '#include <algorithm>',
        '#include <algorithm>\n#include "media/mojo/services/cedar_video_decoder.h"')
replace(name, '      VideoDecoderTraits& traits) final {',
        '      VideoDecoderTraits& traits) final {\n'
        '    if (CedarVideoDecoder::Available() && !traits.oop_video_decoder)\n'
        '      return std::make_unique<CedarVideoDecoder>();')
replace(name, '  GetPlatformSupportedVideoDecoderConfigs() final {',
        '  GetPlatformSupportedVideoDecoderConfigs() final {\n'
        '    if (CedarVideoDecoder::Available())\n'
        '      return CedarVideoDecoder::SupportedConfigs();')
replace(name, '  VideoDecoderType GetPlatformDecoderImplementationType() final {',
        '  VideoDecoderType GetPlatformDecoderImplementationType() final {\n'
        '    if (CedarVideoDecoder::Available()) return VideoDecoderType::kCedar;')
replace('media/mojo/services/BUILD.gn',
        '      sources += [ "gpu_mojo_media_client_linux.cc" ]',
        '      sources += [ "gpu_mojo_media_client_linux.cc",\n'
        '                   "cedar_video_decoder.cc", "cedar_video_decoder.h",\n'
        '                   "cedar_client.h" ]\n      libs = [ "dl" ]')
# Validate every context before mutating any file.
for name, text in changes.items():
    path = root / name
    records[name] = {'before': hashlib.sha256(path.read_bytes()).hexdigest()}
    path.write_text(text, newline='\n')
    records[name]['after'] = hashlib.sha256(path.read_bytes()).hexdigest()
for source in [here / 'cedar_video_decoder.cc', here / 'cedar_video_decoder.h',
               here.parent / 'shm_v2/cedar_client.h']:
    target = root / 'media/mojo/services' / source.name
    assert not target.exists()
    shutil.copyfile(source, target)
    records[target.relative_to(root).as_posix()] = {
        'added': hashlib.sha256(target.read_bytes()).hexdigest()}
marker.write_text(json.dumps({'status': 'UNVALIDATED_CANDIDATE', 'files': records}, indent=2) + '\n')
print(marker)
