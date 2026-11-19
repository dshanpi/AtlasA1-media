#define _POSIX_C_SOURCE 200809L
#include <EGL/egl.h>
#include <GLES2/gl2.h>
#include <wayland-client.h>
#include <wayland-egl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include "xdg-shell-client-protocol.h"
#include "presentation-time-client-protocol.h"

static struct wl_compositor *compositor;
static struct xdg_wm_base *shell;
static struct wp_presentation *presentation;
static struct wl_surface *surface;
static EGLDisplay egl_display;
static EGLSurface egl_surface;
static int configured, running = 1;
static unsigned submitted, shown, discarded, over25, over40;
static uint32_t presentation_flags;
static uint64_t first_present, last_present, max_gap;
static double started;

static double now(void)
{
    struct timespec stamp;
    clock_gettime(CLOCK_MONOTONIC, &stamp);
    return stamp.tv_sec + stamp.tv_nsec / 1e9;
}

static void ping(void *data, struct xdg_wm_base *base, uint32_t serial)
{
    (void)data;
    xdg_wm_base_pong(base, serial);
}
static const struct xdg_wm_base_listener shell_listener = {ping};

static void global(void *data, struct wl_registry *registry, uint32_t name,
                   const char *interface, uint32_t version)
{
    (void)data;
    (void)version;
    if (!strcmp(interface, "wl_compositor"))
        compositor = wl_registry_bind(registry, name, &wl_compositor_interface, 3);
    else if (!strcmp(interface, "xdg_wm_base")) {
        shell = wl_registry_bind(registry, name, &xdg_wm_base_interface, 1);
        xdg_wm_base_add_listener(shell, &shell_listener, NULL);
    } else if (!strcmp(interface, "wp_presentation"))
        presentation = wl_registry_bind(registry, name, &wp_presentation_interface, 1);
}
static void removed(void *data, struct wl_registry *registry, uint32_t name)
{
    (void)data; (void)registry; (void)name;
}
static const struct wl_registry_listener registry_listener = {global, removed};

static void configure(void *data, struct xdg_surface *xdg, uint32_t serial)
{
    (void)data;
    xdg_surface_ack_configure(xdg, serial);
    configured = 1;
}
static const struct xdg_surface_listener surface_listener = {configure};
static void top_configure(void *data, struct xdg_toplevel *top, int32_t width,
                          int32_t height, struct wl_array *states)
{
    (void)data; (void)top; (void)width; (void)height; (void)states;
}
static void top_close(void *data, struct xdg_toplevel *top)
{
    (void)data; (void)top;
    running = 0;
}
static const struct xdg_toplevel_listener top_listener = {
    .configure = top_configure, .close = top_close
};
static void sync_output(void *data, struct wp_presentation_feedback *feedback,
                        struct wl_output *output)
{
    (void)data; (void)feedback; (void)output;
}
static void presented(void *data, struct wp_presentation_feedback *feedback,
                      uint32_t sec_hi, uint32_t sec_lo, uint32_t nsec,
                      uint32_t refresh, uint32_t seq_hi, uint32_t seq_lo,
                      uint32_t flags)
{
    (void)data; (void)refresh; (void)seq_hi; (void)seq_lo;
    uint64_t stamp = (((uint64_t)sec_hi << 32) | sec_lo) * 1000000000ULL + nsec;
    if (!shown) first_present = stamp;
    else {
        uint64_t gap = stamp - last_present;
        if (gap > max_gap) max_gap = gap;
        if (gap > 25000000) over25++;
        if (gap > 40000000) over40++;
    }
    last_present = stamp;
    shown++;
    presentation_flags |= flags;
    wp_presentation_feedback_destroy(feedback);
}
static void discard(void *data, struct wp_presentation_feedback *feedback)
{
    (void)data;
    discarded++;
    wp_presentation_feedback_destroy(feedback);
}
static const struct wp_presentation_feedback_listener feedback_listener = {
    sync_output, presented, discard
};

static void draw(void);
static void frame(void *data, struct wl_callback *callback, uint32_t stamp)
{
    (void)data; (void)stamp;
    wl_callback_destroy(callback);
    if (now() - started >= 12) running = 0;
    else draw();
}
static const struct wl_callback_listener frame_listener = {frame};
static void draw(void)
{
    struct wl_callback *callback = wl_surface_frame(surface);
    wl_callback_add_listener(callback, &frame_listener, NULL);
    struct wp_presentation_feedback *feedback = wp_presentation_feedback(presentation, surface);
    wp_presentation_feedback_add_listener(feedback, &feedback_listener, NULL);
    glDisable(GL_SCISSOR_TEST);
    glClearColor(0.08f, 0.10f, 0.13f, 1);
    glClear(GL_COLOR_BUFFER_BIT);
    glEnable(GL_SCISSOR_TEST);
    glScissor((submitted * 5) % 1160, 200, 120, 320);
    glClearColor(0.1f, 0.5f, 0.8f, 1);
    glClear(GL_COLOR_BUFFER_BIT);
    if (!eglSwapBuffers(egl_display, egl_surface)) {
        fprintf(stderr, "eglSwapBuffers failed: 0x%x\n", eglGetError());
        running = 0;
    }
    submitted++;
}

int main(void)
{
    struct wl_display *display = wl_display_connect(NULL);
    if (!display) return 2;
    struct wl_registry *registry = wl_display_get_registry(display);
    wl_registry_add_listener(registry, &registry_listener, NULL);
    wl_display_roundtrip(display);
    if (!compositor || !shell || !presentation) return 3;
    surface = wl_compositor_create_surface(compositor);
    struct xdg_surface *xdg = xdg_wm_base_get_xdg_surface(shell, surface);
    xdg_surface_add_listener(xdg, &surface_listener, NULL);
    struct xdg_toplevel *top = xdg_surface_get_toplevel(xdg);
    xdg_toplevel_add_listener(top, &top_listener, NULL);
    xdg_toplevel_set_title(top, "AtlasA1 presentation timing");
    wl_surface_commit(surface);
    while (!configured && wl_display_dispatch(display) >= 0) {}
    egl_display = eglGetDisplay((EGLNativeDisplayType)display);
    EGLint major, minor, count;
    if (!eglInitialize(egl_display, &major, &minor)) return 4;
    EGLint attributes[] = {EGL_SURFACE_TYPE, EGL_WINDOW_BIT, EGL_RENDERABLE_TYPE,
        EGL_OPENGL_ES2_BIT, EGL_RED_SIZE, 8, EGL_GREEN_SIZE, 8, EGL_BLUE_SIZE, 8, EGL_NONE};
    EGLConfig config;
    if (!eglChooseConfig(egl_display, attributes, &config, 1, &count) || count != 1) return 5;
    eglBindAPI(EGL_OPENGL_ES_API);
    EGLint context_attributes[] = {EGL_CONTEXT_CLIENT_VERSION, 2, EGL_NONE};
    EGLContext context = eglCreateContext(egl_display, config, EGL_NO_CONTEXT, context_attributes);
    struct wl_egl_window *window = wl_egl_window_create(surface, 1280, 720);
    egl_surface = eglCreateWindowSurface(egl_display, config, (EGLNativeWindowType)window, NULL);
    if (!eglMakeCurrent(egl_display, egl_surface, egl_surface, context)) return 6;
    printf("renderer=%s\n", glGetString(GL_RENDERER));
    fflush(stdout);
    /* The wl_surface frame callback already paces each draw. */
    eglSwapInterval(egl_display, 0);
    started = now();
    draw();
    while (running && wl_display_dispatch(display) >= 0) {}
    wl_display_roundtrip(display);
    printf("submitted=%u presented=%u discarded=%u elapsed=%.3f presented_fps=%.3f "
           "max_gap_ms=%.3f gaps_over_25ms=%u gaps_over_40ms=%u flags=0x%x\n",
           submitted, shown, discarded, now() - started,
           shown > 1 ? (shown - 1) * 1e9 / (last_present - first_present) : 0,
           max_gap / 1e6, over25, over40, presentation_flags);
    return shown > 1 ? 0 : 7;
}
