/* SPDX-License-Identifier: MIT
 * FFplay's SDL2 video thread uploads a new I420 image before the next present.
 * Measure that path only; redraws of an existing texture do not count.
 * Build with cc -O2 -Wall -Wextra -shared -fPIC ffplay_present_trace.c -ldl -o trace.so
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

typedef struct SDL_Texture SDL_Texture;
typedef struct SDL_Rect SDL_Rect;
typedef struct SDL_Renderer SDL_Renderer;
static _Thread_local int have_new_pixels;
static _Thread_local uint64_t upload_start;
static uint64_t times[16384];
static uint64_t upload_total, upload_to_present_total;
static unsigned count;
static int overflow;

static uint64_t monotonic_ns(void)
{
    struct timespec now;
    if (clock_gettime(CLOCK_MONOTONIC, &now)) return 0;
    return (uint64_t)now.tv_sec * 1000000000 + now.tv_nsec;
}

int SDL_UpdateYUVTexture(SDL_Texture *texture, const SDL_Rect *rect, const uint8_t *y, int y_pitch,
                         const uint8_t *u, int u_pitch, const uint8_t *v, int v_pitch)
{
    static int (*upload)(SDL_Texture *, const SDL_Rect *, const uint8_t *, int,
                         const uint8_t *, int, const uint8_t *, int);
    if (!upload) upload = dlsym(RTLD_NEXT, "SDL_UpdateYUVTexture");
    if (!upload) abort();
    upload_start = monotonic_ns();
    int ret = upload(texture, rect, y, y_pitch, u, u_pitch, v, v_pitch);
    if (ret == 0) {
        uint64_t end = monotonic_ns();
        if (end >= upload_start) upload_total += end - upload_start;
        have_new_pixels = 1;
    }
    return ret;
}

void SDL_RenderPresent(SDL_Renderer *renderer)
{
    static void (*present)(SDL_Renderer *);
    if (!present) present = dlsym(RTLD_NEXT, "SDL_RenderPresent");
    if (!present) abort();
    present(renderer);
    if (!have_new_pixels) return;
    have_new_pixels = 0;
    if (count == sizeof(times) / sizeof(times[0])) {
        overflow = 1;
        return;
    }
    uint64_t end = monotonic_ns();
    if (end >= upload_start && end) {
        times[count++] = end;
        upload_to_present_total += end - upload_start;
    }
}

static int compare(const void *a, const void *b)
{
    uint64_t left = *(const uint64_t *)a, right = *(const uint64_t *)b;
    return (left > right) - (left < right);
}

__attribute__((destructor)) static void report(void)
{
    if (overflow || count < 2) return;
    unsigned gaps = count - 1;
    uint64_t span = times[count - 1] - times[0];
    for (unsigned i = 0; i < gaps; i++)
        times[i] = times[i + 1] - times[i];
    qsort(times, gaps, sizeof(times[0]), compare);
    fprintf(stderr, "\nT736_FFPLAY_UPLOAD mean_upload_ms=%.3f mean_upload_to_present_ms=%.3f\n",
            upload_total / 1e6 / count, upload_to_present_total / 1e6 / count);
    fprintf(stderr, "\nT736_FFPLAY_PRESENT frames=%u span_ms=%.3f gap_p95_ms=%.3f gap_max_ms=%.3f\n",
            count, span / 1e6, times[(95UL * gaps + 99) / 100 - 1] / 1e6, times[gaps-1] / 1e6);
}
