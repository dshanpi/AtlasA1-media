/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "cedar_panel.h"
#include <assert.h>
#include <inttypes.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

struct guarded {
    uint8_t *mapping, *data;
    size_t size;
};

static struct guarded guard_after(size_t size)
{
    size_t page = (size_t)sysconf(_SC_PAGESIZE);
    size_t usable = (size + page - 1) / page * page;
    uint8_t *p = mmap(NULL, usable + 2 * page, PROT_NONE,
                      MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    assert(p != MAP_FAILED);
    assert(mprotect(p + page, usable, PROT_READ | PROT_WRITE) == 0);
    return (struct guarded){p, p + page + usable - size, usable + 2 * page};
}

static void free_guard(struct guarded buf)
{
    assert(munmap(buf.mapping, buf.size) == 0);
}

static unsigned sample_rng = 557839;
static void fill_source(uint8_t *p, size_t n)
{
    for (size_t i = 0; i < n; ++i) {
        sample_rng ^= sample_rng << 13;
        sample_rng ^= sample_rng >> 17;
        sample_rng ^= sample_rng << 5;
        p[i] = (uint8_t)sample_rng;
    }
}

static uint64_t check_plane(const uint8_t *src, unsigned width, unsigned height,
                            const uint8_t *dst)
{
    uint64_t hash = UINT64_C(14695981039346656037);
    for (unsigned row = 0; row < height / 2; ++row) {
        for (unsigned col = 0; col < width / 2; ++col) {
            size_t i = (size_t)2 * row * width + 2 * col;
            unsigned sum = src[i] + src[i + 1] + src[i + width] + src[i + width + 1];
            uint8_t value = dst[(size_t)row * (width / 2) + col];
            assert(value == (sum + 2) / 4);
            hash = (hash ^ value) * UINT64_C(1099511628211);
        }
    }
    return hash;
}

int main(void)
{
    size_t length = 4 * T736_PANEL_BYTES;
    struct guarded src = guard_after(length);
    struct guarded dst = guard_after(T736_PANEL_BYTES);
    fill_source(src.data, length);
    memset(dst.data, 0xa5, T736_PANEL_BYTES);
    assert(t736_panel_i420(dst.data, T736_PANEL_BYTES - 1, src.data, length, 3840, 2160) == -ENOSPC);
    assert(t736_panel_i420(dst.data, T736_PANEL_BYTES, src.data, length - 1, 3840, 2160) == -EINVAL);
    assert(t736_panel_i420(dst.data, T736_PANEL_BYTES, src.data, length, 3840, 2159) == -EINVAL);
    assert(t736_panel_i420(dst.data, T736_PANEL_BYTES, src.data, length, 1920, 1080) == -EINVAL);
    for (size_t i = 0; i < T736_PANEL_BYTES; ++i) assert(dst.data[i] == 0xa5);
    assert(t736_panel_i420(dst.data, T736_PANEL_BYTES, src.data, length, 3840, 2160) == 0);
    size_t offset = 0;
    for (int plane = 0; plane < 3; ++plane) {
        unsigned w = plane ? 1920 : 3840;
        unsigned h = plane ? 1080 : 2160;
        uint64_t hash = check_plane(src.data + offset, w, h, dst.data + offset / 4);
        printf("I420[%d] bytes=%zu FNV-1a=%016" PRIx64 "\n", plane, (size_t)w * h / 4, hash);
        offset += (size_t)w * h;
    }
    free_guard(src);
    free_guard(dst);
    for (unsigned w = 2; w <= 66; w += 2) {
        for (unsigned h = 2; h <= 8; h += 2) {
            size_t n = (size_t)w * h;
            struct guarded a = guard_after(n), b = guard_after(n / 4);
            fill_source(a.data, n);
            t736_half_plane(b.data, a.data, w, h);
            check_plane(a.data, w, h, b.data);
            free_guard(a);
            free_guard(b);
        }
    }
    puts("132 guard-page plane shapes and invalid capacity, size and geometry passed");
}
