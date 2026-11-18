/* SPDX-License-Identifier: MIT */
#ifndef T736_CEDAR_PANEL_H
#define T736_CEDAR_PANEL_H

#include <errno.h>
#include <stddef.h>
#include <stdint.h>
#ifdef __aarch64__
#include <arm_neon.h>
#endif

#define T736_PANEL_WIDTH 1920U
#define T736_PANEL_HEIGHT 1080U
#define T736_PANEL_BYTES (T736_PANEL_WIDTH * T736_PANEL_HEIGHT * 3U / 2U)

/* Average each 2x2 box with a single rounding step. Both plane dimensions
 * are even; the right edge need not be a multiple of the vector width. */
static void t736_half_plane(uint8_t *dst, const uint8_t *src,
                            unsigned width, unsigned height)
{
    for (unsigned y = 0; y < height; y += 2) {
        const uint8_t *top = src + (size_t)y * width;
        const uint8_t *bottom = top + width;
        unsigned x = 0;
#ifdef __aarch64__
        for (; x + 16 <= width; x += 16) {
            uint16x8_t upper = vpaddlq_u8(vld1q_u8(top + x));
            uint16x8_t lower = vpaddlq_u8(vld1q_u8(bottom + x));
            vst1_u8(dst + x / 2, vrshrn_n_u16(vaddq_u16(upper, lower), 2));
        }
#endif
        for (; x < width; x += 2)
            dst[x / 2] = (top[x] + top[x + 1] + bottom[x] + bottom[x + 1] + 2) / 4;
        dst += width / 2;
    }
}

static int t736_panel_i420(uint8_t *dst, size_t capacity,
                           const uint8_t *src, size_t length,
                           unsigned width, unsigned height)
{
    if (!dst || !src || width != 2 * T736_PANEL_WIDTH ||
        height != 2 * T736_PANEL_HEIGHT || length != 4 * T736_PANEL_BYTES)
        return -EINVAL;
    if (capacity < T736_PANEL_BYTES)
        return -ENOSPC;
    for (unsigned plane = 0; plane < 3; plane++) {
        unsigned w = plane ? width / 2 : width;
        unsigned h = plane ? height / 2 : height;
        t736_half_plane(dst, src, w, h);
        src += (size_t)w * h;
        dst += (size_t)(w / 2) * (h / 2);
    }
    return 0;
}
#endif
