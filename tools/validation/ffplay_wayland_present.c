/* SPDX-License-Identifier: MIT
 * Add wp_presentation feedback to each newly uploaded SDL video frame.
 * Diagnostic preload only. Requires generated presentation-time protocol code.
 */
#define _GNU_SOURCE
#include <SDL.h>
#undef SDL_VIDEO_DRIVER_X11
#undef SDL_VIDEO_DRIVER_KMSDRM
#include <SDL_syswm.h>
#include <wayland-client.h>
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include "presentation-time-client-protocol.h"

static struct wl_display *display;
static struct wl_event_queue *queue;
static struct wl_registry *registry;
static struct wl_surface *surface;
static struct wp_presentation *presentation;
static int initialized, new_frame;
static unsigned requested, shown, discarded, flags_seen, over25, over40;
static uint64_t first, last, maximum;
static uint64_t uploads[16384], presents[16384];
static unsigned upload_count, present_count;
static _Thread_local uint64_t poll_max, sleep_max;
static _Thread_local unsigned poll_slow, sleep_slow;

static uint64_t monotonic_ns(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ULL + ts.tv_nsec;
}

static int compare_ns(const void *a, const void *b)
{
    uint64_t x = *(const uint64_t *)a, y = *(const uint64_t *)b;
    return (x > y) - (x < y);
}

void SDL_PumpEvents(void)
{
    void (*real)(void) = dlsym(RTLD_NEXT, "SDL_PumpEvents");
    if (!real) abort();
    uint64_t start = monotonic_ns();
    real();
    uint64_t elapsed = monotonic_ns() - start;
    if (elapsed > poll_max) poll_max = elapsed;
    if (elapsed > 20000000) poll_slow++;
}

int av_usleep(unsigned usec)
{
    int (*real)(unsigned) = dlsym(RTLD_NEXT, "av_usleep");
    if (!real) abort();
    uint64_t start = monotonic_ns();
    int result = real(usec);
    uint64_t elapsed = monotonic_ns() - start;
    /* Only track FFplay's short refresh sleeps, not decoder worker delays. */
    if (usec <= 10000) {
        if (elapsed > sleep_max) sleep_max = elapsed;
        if (elapsed > 20000000) sleep_slow++;
    }
    return result;
}

static void global(void *data, struct wl_registry *reg, uint32_t name,
                   const char *interface, uint32_t version)
{
    (void)data; (void)version;
    if (!strcmp(interface, "wp_presentation"))
        presentation = wl_registry_bind(reg, name, &wp_presentation_interface, 1);
}
static void removed(void *data, struct wl_registry *reg, uint32_t name)
{ (void)data; (void)reg; (void)name; }
static const struct wl_registry_listener registry_listener = {global, removed};

static void sync_output(void *data, struct wp_presentation_feedback *f, struct wl_output *output)
{ (void)data; (void)f; (void)output; }
static void presented(void *data, struct wp_presentation_feedback *f,
                      uint32_t hi, uint32_t lo, uint32_t ns, uint32_t refresh,
                      uint32_t seq_hi, uint32_t seq_lo, uint32_t flags)
{
    (void)data; (void)refresh; (void)seq_hi; (void)seq_lo;
    uint64_t stamp = (((uint64_t)hi << 32) | lo) * 1000000000ULL + ns;
    if (!shown) first = stamp;
    else if (stamp >= last) {
        uint64_t gap = stamp - last;
        if (gap > maximum) maximum = gap;
        if (gap > 25000000) over25++;
        if (gap > 40000000) over40++;
    }
    shown++;
    last = stamp;
    flags_seen = shown == 1 ? flags : flags_seen & flags;
    wp_presentation_feedback_destroy(f);
}
static void dropped(void *data, struct wp_presentation_feedback *f)
{
    (void)data;
    discarded++;
    wp_presentation_feedback_destroy(f);
}
static const struct wp_presentation_feedback_listener feedback_listener = {
    sync_output, presented, dropped
};

static void setup_window(SDL_Window *window)
{
    if (initialized) return;
    initialized = 1;
    SDL_bool (*get_info)(SDL_Window *, SDL_SysWMinfo *) = dlsym(RTLD_NEXT, "SDL_GetWindowWMInfo");
    if (!get_info || !window) return;
    SDL_SysWMinfo info;
    memset(&info, 0, sizeof(info));
    SDL_VERSION(&info.version);
    if (!get_info(window, &info) || info.subsystem != SDL_SYSWM_WAYLAND) return;
    display = info.info.wl.display;
    surface = info.info.wl.surface;
    queue = wl_display_create_queue(display);
    if (!queue) return;
    struct wl_display *wrapper = wl_proxy_create_wrapper(display);
    if (!wrapper) return;
    wl_proxy_set_queue((struct wl_proxy *)wrapper, queue);
    registry = wl_display_get_registry(wrapper);
    wl_proxy_wrapper_destroy(wrapper);
    wl_registry_add_listener(registry, &registry_listener, NULL);
    if (wl_display_roundtrip_queue(display, queue) < 0) return;
    fprintf(stderr, "ATLAS_WAYLAND_TRACE protocol=%s\n", presentation ? "wp_presentation" : "unavailable");
}

/* Explicit hook for the direct DMA-BUF diagnostic player. Call once immediately
 * before swapping each decoded frame; it does not fabricate SDL upload events.
 */
void atlas_wayland_frame(SDL_Window *window)
{
    setup_window(window);
    if (presentation) {
        wl_display_dispatch_queue_pending(display, queue);
        struct wp_presentation_feedback *feedback = wp_presentation_feedback(presentation, surface);
        wp_presentation_feedback_add_listener(feedback, &feedback_listener, NULL);
        requested++;
    }
}

int SDL_UpdateYUVTexture(SDL_Texture *texture, const SDL_Rect *rect,
                        const Uint8 *y, int yp, const Uint8 *u, int up, const Uint8 *v, int vp)
{
    int (*real)(SDL_Texture *, const SDL_Rect *, const Uint8 *, int,
                const Uint8 *, int, const Uint8 *, int) = dlsym(RTLD_NEXT, "SDL_UpdateYUVTexture");
    if (!real) abort();
    uint64_t start = monotonic_ns();
    int result = real(texture, rect, y, yp, u, up, v, vp);
    if (upload_count < 16384) uploads[upload_count++] = monotonic_ns() - start;
    if (!result) new_frame = 1;
    return result;
}

void SDL_RenderPresent(SDL_Renderer *renderer)
{
    void (*real)(SDL_Renderer *) = dlsym(RTLD_NEXT, "SDL_RenderPresent");
    if (!real) abort();
    SDL_Window *(*get_window)(SDL_Renderer *) = dlsym(RTLD_NEXT, "SDL_RenderGetWindow");
    if (get_window) setup_window(get_window(renderer));
    if (presentation && new_frame) {
        wl_display_dispatch_queue_pending(display, queue);
        struct wp_presentation_feedback *feedback = wp_presentation_feedback(presentation, surface);
        wp_presentation_feedback_add_listener(feedback, &feedback_listener, NULL);
        requested++;
    }
    new_frame = 0;
    uint64_t start = monotonic_ns();
    real(renderer);
    if (present_count < 16384) presents[present_count++] = monotonic_ns() - start;
}

void atlas_wayland_finish(void)
{
    if (upload_count && present_count) {
        qsort(uploads, upload_count, sizeof(*uploads), compare_ns);
        qsort(presents, present_count, sizeof(*presents), compare_ns);
        fprintf(stderr, "ATLAS_WAYLAND_STAGE upload_p95_ms=%.3f upload_max_ms=%.3f "
                "present_p95_ms=%.3f present_max_ms=%.3f\n",
                uploads[(upload_count-1)*95/100]/1e6, uploads[upload_count-1]/1e6,
                presents[(present_count-1)*95/100]/1e6, presents[present_count-1]/1e6);
        fprintf(stderr, "ATLAS_WAYLAND_EVENTS poll_max_ms=%.3f poll_over_20ms=%u "
                "sleep_max_ms=%.3f sleep_over_20ms=%u\n",
                poll_max/1e6, poll_slow, sleep_max/1e6, sleep_slow);
    }
    if (presentation) {
        /* Finish collecting while SDL's Wayland connection is still alive. */
        for (unsigned i = 0; i < 5 && shown + discarded < requested; i++) {
            struct timespec pause = {0, 20000000};
            nanosleep(&pause, NULL);
            if (wl_display_roundtrip_queue(display, queue) < 0) break;
        }
        fprintf(stderr, "ATLAS_WAYLAND_PRESENT requested=%u shown=%u discarded=%u "
                "span_ms=%.3f fps=%.3f max_gap_ms=%.3f gaps_over_25ms=%u gaps_over_40ms=%u flags=0x%x\n",
                requested, shown, discarded, (last-first)/1e6,
                shown>1 && last>first ? (shown-1)*1e9/(last-first) : 0,
                maximum/1e6, over25, over40, flags_seen);
        wp_presentation_destroy(presentation);
        presentation = NULL;
    }
    if (registry) { wl_registry_destroy(registry); registry = NULL; }
    if (queue) { wl_event_queue_destroy(queue); queue = NULL; }
}

void SDL_DestroyRenderer(SDL_Renderer *renderer)
{
    void (*real)(SDL_Renderer *) = dlsym(RTLD_NEXT, "SDL_DestroyRenderer");
    if (!real) abort();
    atlas_wayland_finish();
    real(renderer);
}
