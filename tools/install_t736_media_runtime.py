#!/usr/bin/env python3
import hashlib, json, os, pathlib, shutil, subprocess, sys, tarfile
ARCH=pathlib.Path('/tmp/vendor-media-v29-final.tar.gz')
EXPECTED='648d5588658d7020edd7dd00dad0c02c893a036fe5b883f01a33b075401679f2'
KERNEL='6.18.63-t736-media-v29'
if not ARCH.is_file(): raise SystemExit('archive missing')
h=hashlib.sha256();
with ARCH.open('rb') as f:
    for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
if h.hexdigest()!=EXPECTED: raise SystemExit('archive sha256 mismatch '+h.hexdigest())
root=pathlib.Path('/tmp/t736-vendor-tree')
if root.exists(): shutil.rmtree(root)
root.mkdir()
with tarfile.open(ARCH,'r:gz') as t:
    for m in t.getmembers():
        p=pathlib.PurePosixPath(m.name)
        if p.is_absolute() or '..' in p.parts: raise SystemExit('unsafe archive')
        if m.isfile():
            d=root.joinpath(*p.parts); d.parent.mkdir(parents=True,exist_ok=True)
            with t.extractfile(m) as src, d.open('wb') as out: shutil.copyfileobj(src,out)
manifest=json.loads((root/'manifest.json').read_text())
if manifest.get('kernel_release')!=KERNEL or not manifest.get('private'): raise SystemExit('manifest mismatch')
roles=set()
for item in manifest['files']:
    roles.add(item.get('role'))
    src=root.joinpath(*pathlib.PurePosixPath(item['source']).parts)
    if not src.is_file(): raise SystemExit('missing '+str(src))
    hh=hashlib.sha256(src.read_bytes()).hexdigest()
    if hh.lower()!=item['sha256'].lower(): raise SystemExit('hash mismatch '+item['source'])
    target=pathlib.PurePosixPath(item['target'])
    if not target.is_absolute() or '..' in target.parts: raise SystemExit('unsafe target')
    dst=pathlib.Path(*target.parts)
    dst.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(src,dst)
    if item.get('mode'): os.chmod(dst,int(item['mode'],8))
if not {'gpu_userspace','pvr_module','codec_backend','codec_service','codec_userspace','codec_config','browser_bridge','browser_service','device_rules','ddr_boot'} <= roles:
    raise SystemExit('incomplete roles')
ffmpeg_lib = pathlib.Path('/opt/t736-browser-ffmpeg-v7/lib')
subprocess.run(['/sbin/ldconfig', '-n', str(ffmpeg_lib)], check=True)
for soname in ('libavcodec.so.61', 'libavutil.so.59', 'libswresample.so.5'):
    if not (ffmpeg_lib / soname).is_file():
        raise SystemExit('missing private FFmpeg SONAME: ' + soname)
# Keep the manifest and an auditable role map on the live system.
pathlib.Path('/etc/t736').mkdir(parents=True,exist_ok=True)
shutil.copy2(root/'manifest.json','/etc/t736/vendor-manifest.json')
role_map={}
for item in manifest['files']: role_map.setdefault(item['role'],[]).append(item['target'])
(pathlib.Path('/etc/t736/vendor-roles.json')).write_text(json.dumps(role_map,indent=2,sort_keys=True)+'\n')
# Install the vendor GPU userspace package after copying its exact manifest target.
deb=pathlib.Path('/tmp/t736-vendor/gpu-userspace.deb')
if deb.is_file():
    p=subprocess.run(['dpkg','--unpack',str(deb)],text=True,capture_output=True)
    if p.returncode: print(p.stdout+p.stderr,file=sys.stderr); raise SystemExit('dpkg unpack failed')
    subprocess.run(['dpkg','--configure','-a'],check=False)
# Dedicated broker identities and endpoint permissions.
subprocess.run(['groupadd','--system','t736-cedar'],check=False)
subprocess.run(['groupadd','--system','t736'],check=False)
subprocess.run(['useradd','--system','--gid','t736-cedar','--groups','t736','--home-dir','/nonexistent','--no-create-home','--shell','/usr/sbin/nologin','t736-cedar'],check=False)
if subprocess.run(['getent','passwd','t736'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0:
    subprocess.run(['usermod','--append','--groups','t736','t736'],check=False)
# Apply service/rule files and bring up the socket. Raw devices remain broker-only.
subprocess.run(['udevadm','control','--reload-rules'],check=False)
subprocess.run(['udevadm','trigger','--subsystem-match=misc'],check=False)
subprocess.run(['udevadm','trigger','--subsystem-match=dma_heap'],check=False)
subprocess.run(['depmod', '-a', KERNEL], check=True)
info = ['modinfo', '-k', KERNEL]
indexed = subprocess.check_output([*info, '-n', 'pvrsrvkm'], text=True).strip()
vermagic = subprocess.check_output([*info, '-F', 'vermagic', 'pvrsrvkm'], text=True).split()
if not pathlib.Path(indexed).samefile(role_map['pvr_module'][0]) or vermagic[:1] != [KERNEL]:
    raise SystemExit('PVR module index does not resolve the installed module for '+KERNEL)
subprocess.run(['systemctl','daemon-reload'],check=True)
subprocess.run(['systemctl','disable','t736-cedar.service'],check=True)
subprocess.run(['systemctl','enable','t736-cedar.socket'],check=True)
subprocess.run(['systemctl','restart','t736-cedar.socket'],check=True)
pathlib.Path('/etc/t736/build-info').write_text('board=t736-mainline\nvendor_manifest_sha256='+hashlib.sha256((root/'manifest.json').read_bytes()).hexdigest()+'\ngpu_media_acceptance=pending\n')
print('T736_VENDOR_INSTALL_OK')
