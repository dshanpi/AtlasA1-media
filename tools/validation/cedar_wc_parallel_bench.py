#!/usr/bin/env python3
"""Measure parallel reads of one idle, full-size AtlasA1 4K YV12 output buffer."""
import argparse
import ctypes as C
import json
import os
from pathlib import Path
import platform
import re
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

WIDTH, VISIBLE, STORED = 3840, 2160, 2176
PLANE = WIDTH * STORED
SPAN = PLANE * 3 // 2
SIZE = WIDTH * VISIBLE * 3 // 2
LIBC = C.CDLL(None, use_errno=True)
LIBC.mmap.argtypes = [C.c_void_p, C.c_size_t, C.c_int, C.c_int, C.c_int, C.c_long]
LIBC.mmap.restype = C.c_void_p
LIBC.munmap.argtypes = [C.c_void_p, C.c_size_t]
LIBC.memcpy.argtypes = [C.c_void_p, C.c_void_p, C.c_size_t]
LIBC.memcpy.restype = C.c_void_p
LIBC.memcmp.argtypes = [C.c_void_p, C.c_void_p, C.c_size_t]
LIBC.syscall.restype = C.c_long


def irq_count():
    line = next(s for s in Path('/proc/interrupts').read_text().splitlines() if 't736-cedar-wc' in s)
    numbers = re.match(r'\s*((?:\d+\s+)+)', line.split(':', 1)[1])
    return sum(map(int, numbers[1].split()))


def copy_rows(dst, src, first, last):
    # Address the visible Y, U and V planes in the same order as the broker's I420 output.
    for di, si, pitch, scale in ((0, 0, WIDTH, 1),
                                (WIDTH * VISIBLE, PLANE * 5 // 4, WIDTH // 2, 2),
                                (WIDTH * VISIBLE * 5 // 4, PLANE, WIDTH // 2, 2)):
        off = first // scale * pitch
        LIBC.memcpy(dst + di + off, src + si + off, (last - first) // scale * pitch)


def bench(cpus, weights, dst, src, reference, iterations):
    barrier = Barrier(len(cpus) + 1, timeout=20)
    # Split at even luma rows so no workers share a chroma row.
    bounds = [2 * ((VISIBLE // 2) * sum(weights[:i]) // sum(weights)) for i in range(len(cpus)+1)]
    def worker(i):
        try:
            os.sched_setaffinity(0, {cpus[i]})
            for _ in range(iterations+2):
                barrier.wait()
                copy_rows(dst, src, bounds[i], bounds[i+1])
                barrier.wait()
        except BaseException:
            barrier.abort()
            raise

    durations = []
    with ThreadPoolExecutor(max_workers=len(cpus)) as pool:
        futures = [pool.submit(worker, i) for i in range(len(cpus))]
        for step in range(iterations+2):
            start = time.perf_counter_ns()
            barrier.wait()
            barrier.wait()
            if step >= 2:
                durations.append(round((time.perf_counter_ns()-start)/1000))
        for future in futures:
            future.result()
    if LIBC.memcmp(reference, dst, SIZE):
        raise ValueError('visible I420 output differed from the reference')
    return {'cpus':cpus, 'weights':weights, 'us':durations, 'median_us':statistics.median(durations)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pid',required=True,type=int)
    parser.add_argument('--fd',required=True,type=int)
    parser.add_argument('--output',required=True,type=Path)
    args = parser.parse_args()
    if platform.machine() != 'aarch64':
        parser.error('requires Linux AArch64 pidfd_getfd syscall number')
    pidfd = os.pidfd_open(args.pid)
    fd = LIBC.syscall(438, pidfd, args.fd, 0)
    os.close(pidfd)
    if fd < 0:
        raise OSError(C.get_errno(), 'pidfd_getfd')
    with os.fdopen(fd, 'rb', buffering=0) as buffer:
        meta = Path(f'/proc/self/fdinfo/{buffer.fileno()}').read_text()
        if not re.search(r'^exp_name:\s*t736-ve-wc$', meta, re.M) or os.fstat(fd).st_size != SPAN:
            raise ValueError('not a full-size 4K WC buffer')
        src = LIBC.mmap(None, SPAN, 1, 1, fd, 0)  # PROT_READ | MAP_SHARED
        if src == C.c_void_p(-1).value:
            raise OSError(C.get_errno(), 'mmap')
        try:
            start_irq = irq_count()
            ref_memory, dst_memory = C.create_string_buffer(SIZE), C.create_string_buffer(SIZE)
            reference, destination = C.addressof(ref_memory), C.addressof(dst_memory)
            copy_rows(reference, src, 0, VISIBLE)
            configs = [([6], [1]), ([7], [1]), ([6,7], [1,1]),
                       ([6,7,4,5], [3,3,1,1]), ([0,1,2,3], [1]*4),
                       ([6,7,0,1,2,3], [3,3,1,1,1,1]), ([6], [1])]
            results = [bench(cpus, weights, destination, src, reference, 9) for cpus,weights in configs]
            end_irq = irq_count()
            if end_irq != start_irq:
                raise ValueError('decoder IRQ count changed during idle-buffer measurement')
            record = {'kernel':os.uname().release,'method':'PROT_READ existing idle t736-ve-wc YV12 buffer, disjoint visible row bands, libc memcpy into ordinary I420 RAM, two warmup frames per mode',
                      'source_bytes':SPAN,'visible_bytes':SIZE,'irq_before':start_irq,'irq_after':end_irq,
                      'all_outputs_byte_equal':True,'results':results}
            with args.output.open('x') as out:
                json.dump(record,out,indent=2)
                out.write('\n')
            print(json.dumps([(r['cpus'],r['median_us']) for r in results]))
        finally:
            LIBC.munmap(src, SPAN)


if __name__ == '__main__':
    main()
