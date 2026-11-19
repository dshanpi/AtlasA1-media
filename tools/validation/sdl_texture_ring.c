/* SPDX-License-Identifier: MIT
 * Diagnostic SDL2 preload: rotate three YUV textures to test upload stalls.
 * Single video/render thread only, matching FFplay. Never shipped enabled.
 * Uses the stable SDL2 C ABI; no dependency on development headers at runtime.
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
typedef struct SDL_Texture SDL_Texture;
typedef struct SDL_Renderer SDL_Renderer;
typedef struct { int x, y, w, h; } SDL_Rect;
typedef struct { int x, y; } SDL_Point;
static struct {
    SDL_Texture *original, *slots[3];
    SDL_Renderer *renderer;
    uint32_t format;
    int access, width, height, index;
} tracked[16];

#define REAL(name, type) type = dlsym(RTLD_NEXT, #name); if (!real) abort()

SDL_Texture *SDL_CreateTexture(SDL_Renderer *renderer, uint32_t format,
                               int access, int width, int height)
{
    REAL(SDL_CreateTexture, SDL_Texture *(*real)(SDL_Renderer *, uint32_t, int, int, int));
    SDL_Texture *texture = real(renderer, format, access, width, height);
    if (texture) for (unsigned i = 0; i < 16; i++) if (!tracked[i].original) {
        tracked[i].original = texture;
        tracked[i].slots[0] = texture;
        tracked[i].renderer = renderer;
        tracked[i].format = format;
        tracked[i].access = access;
        tracked[i].width = width;
        tracked[i].height = height;
        break;
    }
    return texture;
}

int SDL_UpdateYUVTexture(SDL_Texture *texture, const SDL_Rect *rect,
                         const uint8_t *y, int yp, const uint8_t *u, int up,
                         const uint8_t *v, int vp)
{
    REAL(SDL_UpdateYUVTexture, int (*real)(SDL_Texture *, const SDL_Rect *, const uint8_t *, int, const uint8_t *, int, const uint8_t *, int));
    for (unsigned i = 0; i < 16; i++) if (tracked[i].original == texture) {
        if (!tracked[i].slots[1]) {
            SDL_Texture *(*create)(SDL_Renderer *, uint32_t, int, int, int) = dlsym(RTLD_NEXT, "SDL_CreateTexture");
            void (*destroy)(SDL_Texture *) = dlsym(RTLD_NEXT, "SDL_DestroyTexture");
            int (*getblend)(SDL_Texture *, int *) = dlsym(RTLD_NEXT, "SDL_GetTextureBlendMode");
            int (*setblend)(SDL_Texture *, int) = dlsym(RTLD_NEXT, "SDL_SetTextureBlendMode");
            int blend = 0;
            if (!create || !destroy || !getblend || !setblend) abort();
            getblend(texture, &blend);
            for (int n = 1; n < 3; n++) {
                tracked[i].slots[n] = create(tracked[i].renderer, tracked[i].format,
                    tracked[i].access, tracked[i].width, tracked[i].height);
                if (!tracked[i].slots[n]) {
                    for (int j = 1; j < n; j++) { destroy(tracked[i].slots[j]); tracked[i].slots[j] = NULL; }
                    return real(texture, rect, y, yp, u, up, v, vp);
                }
                setblend(tracked[i].slots[n], blend);
            }
            fprintf(stderr, "ATLAS_TEXTURE_RING slots=3 size=%dx%d\n", tracked[i].width, tracked[i].height);
        }
        tracked[i].index = (tracked[i].index + 1) % 3;
        texture = tracked[i].slots[tracked[i].index];
        break;
    }
    return real(texture, rect, y, yp, u, up, v, vp);
}

int SDL_RenderCopyEx(SDL_Renderer *renderer, SDL_Texture *texture,
                     const SDL_Rect *src, const SDL_Rect *dst, double angle,
                     const SDL_Point *center, int flip)
{
    REAL(SDL_RenderCopyEx, int (*real)(SDL_Renderer *, SDL_Texture *, const SDL_Rect *, const SDL_Rect *, double, const SDL_Point *, int));
    for (unsigned i = 0; i < 16; i++) if (tracked[i].original == texture) {
        texture = tracked[i].slots[tracked[i].index];
        break;
    }
    return real(renderer, texture, src, dst, angle, center, flip);
}

void SDL_DestroyTexture(SDL_Texture *texture)
{
    REAL(SDL_DestroyTexture, void (*real)(SDL_Texture *));
    for (unsigned i = 0; i < 16; i++) if (tracked[i].original == texture) {
        for (int n = 1; n < 3; n++) if (tracked[i].slots[n]) real(tracked[i].slots[n]);
        tracked[i] = (__typeof__(tracked[i])){0};
        break;
    }
    real(texture);
}
