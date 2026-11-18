#include <SDL.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef unsigned GLenum;
typedef unsigned char GLubyte;

int main(void)
{
    static const unsigned char colors[][4] = {
        {255, 0, 0, 255}, {0, 255, 0, 255}, {0, 0, 255, 255}, {255, 255, 0, 255}
    };
    if (getenv("DISPLAY") || getenv("WAYLAND_DISPLAY")) {
        fprintf(stderr, "Unset DISPLAY and WAYLAND_DISPLAY for this offscreen test\n");
        return 2;
    }
    if (SDL_setenv("SDL_VIDEODRIVER", "offscreen", 1) != 0 || SDL_Init(SDL_INIT_VIDEO) != 0) {
        fprintf(stderr, "SDL init: %s\n", SDL_GetError());
        return 1;
    }
    int result = 1;
    SDL_Window *window = NULL;
    SDL_GLContext context = NULL;
    const char *driver = SDL_GetCurrentVideoDriver();
    printf("SDL_VIDEODRIVER=%s\n", driver ? driver : "(none)");
    if (!driver || strcmp(driver, "offscreen")) goto out;
    SDL_GL_SetAttribute(SDL_GL_CONTEXT_PROFILE_MASK, SDL_GL_CONTEXT_PROFILE_ES);
    SDL_GL_SetAttribute(SDL_GL_CONTEXT_MAJOR_VERSION, 2);
    SDL_GL_SetAttribute(SDL_GL_CONTEXT_MINOR_VERSION, 0);
    SDL_GL_SetAttribute(SDL_GL_RED_SIZE, 8);
    SDL_GL_SetAttribute(SDL_GL_GREEN_SIZE, 8);
    SDL_GL_SetAttribute(SDL_GL_BLUE_SIZE, 8);
    window = SDL_CreateWindow("AtlasA1 offscreen QA", 0, 0, 32, 32, SDL_WINDOW_OPENGL | SDL_WINDOW_HIDDEN);
    if (!window) { fprintf(stderr, "SDL_CreateWindow: %s\n", SDL_GetError()); goto out; }
    context = SDL_GL_CreateContext(window);
    if (!context) { fprintf(stderr, "SDL_GL_CreateContext: %s\n", SDL_GetError()); goto out; }
#define GL_PROC(ret, name, args) ret (*name) args = SDL_GL_GetProcAddress(#name); \
    if (!name) { fprintf(stderr, "Missing " #name "\n"); goto out; }
    GL_PROC(const GLubyte *, glGetString, (GLenum))
    GL_PROC(void, glClearColor, (float,float,float,float))
    GL_PROC(void, glClear, (GLenum))
    GL_PROC(void, glFinish, (void))
    GL_PROC(void, glReadPixels, (int,int,int,int,GLenum,GLenum,void *))
    GL_PROC(GLenum, glGetError, (void))
    const char *vendor = (const char *)glGetString(0x1f00);
    const char *renderer = (const char *)glGetString(0x1f01);
    const char *version = (const char *)glGetString(0x1f02);
    if (!vendor || !renderer || !version) { fputs("Missing GLES identity\n",stderr); goto out; }
    printf("GL_VENDOR=%s\nGL_RENDERER=%s\nGL_VERSION=%s\n",vendor,renderer,version);
    if (!strstr(version, "OpenGL ES")) { fputs("Unexpected GL context\n",stderr); goto out; }
    for (size_t i=0; i<sizeof(colors)/sizeof(colors[0]); i++) {
        unsigned char pixel[4] = {0};
        const unsigned char *c = colors[i];
        glClearColor(c[0]/255.0f,c[1]/255.0f,c[2]/255.0f,1.0f);
        glClear(0x4000);
        glFinish();
        glReadPixels(16,16,1,1,0x1908,0x1401,pixel);
        GLenum error = glGetError();
        printf("color%zu=%u,%u,%u,%u gl_error=0x%x\n",i,pixel[0],pixel[1],pixel[2],pixel[3],error);
        if (error || memcmp(pixel,c,3)) { fputs("Pixel readback mismatch\n",stderr); goto out; }
        SDL_GL_SwapWindow(window);
    }
    if (!(strstr(vendor, "Imagination") || strstr(renderer,"PowerVR") || strstr(renderer,"BXM")) ||
        strstr(renderer, "llvmpipe") || strstr(renderer, "softpipe")) {
        fputs("RGB readback passed; renderer is not IMG PowerVR\n",stderr);
        result = 3;
        goto out;
    }
    puts("PASS PowerVR offscreen GLES color readback");
    result = 0;
out:
    if (context) SDL_GL_DeleteContext(context);
    if (window) SDL_DestroyWindow(window);
    SDL_Quit();
    return result;
}
