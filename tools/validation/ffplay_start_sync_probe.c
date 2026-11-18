/* SPDX-License-Identifier: MIT */
/* LD_PRELOAD on FFplay with SDL dummy drivers and a non-silent AV fixture.
 * FFPLAY_TEST_VIDEO_DELAY_MS inserts one slow first video filter result. */
#define _GNU_SOURCE
#include <SDL.h>
#include <dlfcn.h>
#include <errno.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <unistd.h>
#include "libavfilter/buffersink.h"

static int64_t clock_us(void)
{
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    return (int64_t)now.tv_sec * 1000000 + now.tv_nsec / 1000;
}

static SDL_AudioCallback audio_callback;
static atomic_int audible;
static int video_delayed, texture_ready, presented;

static void test_audio(void *opaque, Uint8 *stream, int size)
{
    audio_callback(opaque, stream, size);
    if (!atomic_load(&audible)) {
        for (int i = 0; i < size; i++) {
            if (stream[i]) {
                fprintf(stderr, "\nSTART_SYNC_PROBE pcm_us=%lld\n", (long long)clock_us());
                atomic_store(&audible, 1);
                break;
            }
        }
    }
}

SDL_AudioDeviceID SDL_OpenAudioDevice(const char *name, int capture, const SDL_AudioSpec *want,
                                      SDL_AudioSpec *got, int flags)
{
    SDL_AudioDeviceID (*open_device)(const char *, int, const SDL_AudioSpec *, SDL_AudioSpec *, int)
        = dlsym(RTLD_NEXT, "SDL_OpenAudioDevice");
    SDL_AudioSpec spec = *want;
    if (!capture && spec.callback) {
        audio_callback = spec.callback;
        spec.callback = test_audio;
    }
    return open_device(name, capture, &spec, got, flags);
}

int av_buffersink_get_frame_flags(AVFilterContext *sink, AVFrame *frame, int flags)
{
    int (*get)(AVFilterContext *, AVFrame *, int) = dlsym(RTLD_NEXT, "av_buffersink_get_frame_flags");
    int ret = get(sink, frame, flags);
    if (ret >= 0 && frame->width > 0 && !video_delayed) {
        const char *delay = getenv("FFPLAY_TEST_VIDEO_DELAY_MS");
        int ms = delay ? atoi(delay) : 0;
        video_delayed = 1;
        if (ms > 0 && ms <= 5000) {
            struct timespec duration = {ms / 1000, (ms % 1000) * 1000000L};
            while (nanosleep(&duration, &duration) && errno == EINTR) {}
        }
        fprintf(stderr, "\nSTART_SYNC_PROBE decoded_us=%lld\n", (long long)clock_us());
    }
    return ret;
}

int SDL_RenderCopyEx(SDL_Renderer *renderer, SDL_Texture *texture, const SDL_Rect *src,
                     const SDL_Rect *dst, const double angle, const SDL_Point *center,
                     const SDL_RendererFlip flip)
{
    int (*copy)(SDL_Renderer *, SDL_Texture *, const SDL_Rect *, const SDL_Rect *,
                double, const SDL_Point *, SDL_RendererFlip) = dlsym(RTLD_NEXT, "SDL_RenderCopyEx");
    int ret = copy(renderer, texture, src, dst, angle, center, flip);
    if (!ret) texture_ready = 1;
    return ret;
}

void SDL_RenderPresent(SDL_Renderer *renderer)
{
    void (*present)(SDL_Renderer *) = dlsym(RTLD_NEXT, "SDL_RenderPresent");
    present(renderer);
    if (texture_ready && !presented) {
        presented = 1;
        fprintf(stderr, "\nSTART_SYNC_PROBE presented_us=%lld\n", (long long)clock_us());
    }
}
