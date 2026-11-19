/* SPDX-License-Identifier: MIT
 * FFplay-only diagnostic: upload packed I420 bytes as RGBA8, then decode the
 * three planes in a GLES2 shader. Fullscreen, even 1920x1080 BT.709 limited
 * fixtures only. No production launcher enables this experiment.
 */
#define _GNU_SOURCE
#include <GLES2/gl2.h>
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef struct SDL_Texture SDL_Texture;
typedef struct SDL_Renderer SDL_Renderer;
typedef struct SDL_Window SDL_Window;
typedef struct { int x,y,w,h; } SDL_Rect;
typedef struct { int x,y; } SDL_Point;
extern int SDL_RenderFlush(SDL_Renderer *);
extern SDL_Window *SDL_GL_GetCurrentWindow(void);
extern void SDL_GL_GetDrawableSize(SDL_Window *, int *, int *);
static SDL_Renderer *owner;
static SDL_Texture *target;
static GLuint program, textures[3];
static int slot, ready;
static int checked;
static unsigned draws;
static const int sample_x[3]={200,960,1700},sample_y[3]={100,540,900};
static uint8_t expected_rgb[3][3];
static uint8_t pixels[1920*1080*3/2];
static const char *vertex =
    "attribute vec2 pos; varying vec2 uv; void main(){gl_Position=vec4(pos,0.,1.);uv=vec2((pos.x+1.)*.5,(1.-pos.y)*.5);}";
static const char *fragment =
    "precision highp float; varying vec2 uv; uniform sampler2D image;"
    "float byte_at(float off){float q=floor(off/4.);vec4 p=texture2D(image,vec2((mod(q,480.)+.5)/480.,(floor(q/480.)+.5)/1620.));"
    "float c=mod(off,4.);if(c<1.)return p.r;if(c<2.)return p.g;if(c<3.)return p.b;return p.a;}"
    "void main(){vec2 p=floor(clamp(uv,vec2(0.),vec2(.999999))*vec2(1920.,1080.));"
    "float y=1.16438356*(byte_at(p.y*1920.+p.x)-16./255.);"
    "float off=floor(p.y/2.)*960.+floor(p.x/2.);"
    "float u=byte_at(2073600.+off)-128./255.;float v=byte_at(2592000.+off)-128./255.;"
    "gl_FragColor=vec4(y+1.792741*v,y-.213249*u-.532909*v,y+2.112402*u,1.);}";

static GLuint shader(GLenum kind,const char *source)
{
    GLuint s=glCreateShader(kind); GLint ok=0;
    glShaderSource(s,1,&source,NULL);glCompileShader(s);glGetShaderiv(s,GL_COMPILE_STATUS,&ok);
    if(!ok){char log[1024];glGetShaderInfoLog(s,sizeof(log),NULL,log);fprintf(stderr,"PACKED_SHADER: %s\n",log);abort();}
    return s;
}

SDL_Texture *SDL_CreateTexture(SDL_Renderer *r,uint32_t f,int a,int w,int h)
{
    SDL_Texture *(*real)(SDL_Renderer *,uint32_t,int,int,int)=dlsym(RTLD_NEXT,"SDL_CreateTexture");
    if(!real)abort();
    SDL_Texture *t=real(r,f,a,w,h);
    /* SDL_PIXELFORMAT_IYUV, SDL_PIXELFORMAT_YV12. */
    if(t && w==1920 && h==1080 && (f==0x56555949 || f==0x32315659)){target=t;owner=r;}
    return t;
}

int SDL_UpdateYUVTexture(SDL_Texture *t,const SDL_Rect *rect,const uint8_t *y,int yp,
                        const uint8_t *u,int up,const uint8_t *v,int vp)
{
    if(t!=target || rect){
        int(*real)(SDL_Texture *,const SDL_Rect *,const uint8_t *,int,const uint8_t *,int,const uint8_t *,int)=dlsym(RTLD_NEXT,"SDL_UpdateYUVTexture");
        if(!real)abort();
        return real(t,rect,y,yp,u,up,v,vp);
    }
    SDL_RenderFlush(owner);
    if(!checked) for(int i=0;i<3;i++) {
        int x=sample_x[i],row=sample_y[i];
        float yy=1.16438356f*(y[row*yp+x]-16.f);
        float uu=u[(row/2)*up+x/2]-128.f,vv=v[(row/2)*vp+x/2]-128.f;
        float rgb[3]={yy+1.792741f*vv,yy-.213249f*uu-.532909f*vv,yy+2.112402f*uu};
        for(int c=0;c<3;c++)expected_rgb[i][c]=(uint8_t)(rgb[c]<0?0:rgb[c]>255?255:rgb[c]+.5f);
    }
    GLint binding,alignment;glGetIntegerv(GL_TEXTURE_BINDING_2D,&binding);glGetIntegerv(GL_UNPACK_ALIGNMENT,&alignment);
    if(!ready){
        GLuint vs=shader(GL_VERTEX_SHADER,vertex),fs=shader(GL_FRAGMENT_SHADER,fragment);
        program=glCreateProgram();glAttachShader(program,vs);glAttachShader(program,fs);
        glBindAttribLocation(program,0,"pos");glLinkProgram(program);
        GLint ok;glGetProgramiv(program,GL_LINK_STATUS,&ok);if(!ok)abort();
        glDeleteShader(vs);glDeleteShader(fs);glGenTextures(3,textures);
        for(int i=0;i<3;i++){
            glBindTexture(GL_TEXTURE_2D,textures[i]);
            glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
            glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_S,GL_CLAMP_TO_EDGE);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_T,GL_CLAMP_TO_EDGE);
            glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA,480,1620,0,GL_RGBA,GL_UNSIGNED_BYTE,NULL);
        }
        ready=1;fprintf(stderr,"ATLAS_PACKED_YUV rgba=480x1620 bt709_limited=1\n");
    }
    const uint8_t *src=y;
    if(yp!=1920 || up!=960 || vp!=960 || u!=y+2073600 || v!=u+518400){
        for(int n=0;n<1080;n++)memcpy(pixels+n*1920,y+n*yp,1920);
        for(int n=0;n<540;n++){memcpy(pixels+2073600+n*960,u+n*up,960);memcpy(pixels+2592000+n*960,v+n*vp,960);}
        src=pixels;
    }
    slot=(slot+1)%3;glBindTexture(GL_TEXTURE_2D,textures[slot]);glPixelStorei(GL_UNPACK_ALIGNMENT,1);
    glTexSubImage2D(GL_TEXTURE_2D,0,0,0,480,1620,GL_RGBA,GL_UNSIGNED_BYTE,src);
    GLenum error=glGetError();glBindTexture(GL_TEXTURE_2D,binding);glPixelStorei(GL_UNPACK_ALIGNMENT,alignment);
    if(error){fprintf(stderr,"PACKED_UPLOAD_ERROR %x\n",error);abort();}return 0;
}

int SDL_RenderCopyEx(SDL_Renderer *r,SDL_Texture *t,const SDL_Rect *src,const SDL_Rect *dst,
                     double angle,const SDL_Point *center,int flip)
{
    if(t!=target || !ready){
        int(*real)(SDL_Renderer *,SDL_Texture *,const SDL_Rect *,const SDL_Rect *,double,const SDL_Point *,int)=dlsym(RTLD_NEXT,"SDL_RenderCopyEx");
        if(!real)abort();
        return real(r,t,src,dst,angle,center,flip);
    }
    if(src || angle || flip)abort();
    SDL_RenderFlush(r);
    GLint oldprogram,viewport[4],active,binding,buffer,enabled,size,stride,type,normalized,attrbuffer;void *pointer;
    glGetIntegerv(GL_CURRENT_PROGRAM,&oldprogram);glGetIntegerv(GL_VIEWPORT,viewport);
    glGetIntegerv(GL_ACTIVE_TEXTURE,&active);glActiveTexture(GL_TEXTURE0);glGetIntegerv(GL_TEXTURE_BINDING_2D,&binding);
    glGetIntegerv(GL_ARRAY_BUFFER_BINDING,&buffer);
    glGetVertexAttribiv(0,GL_VERTEX_ATTRIB_ARRAY_ENABLED,&enabled);glGetVertexAttribiv(0,GL_VERTEX_ATTRIB_ARRAY_SIZE,&size);
    glGetVertexAttribiv(0,GL_VERTEX_ATTRIB_ARRAY_STRIDE,&stride);glGetVertexAttribiv(0,GL_VERTEX_ATTRIB_ARRAY_TYPE,&type);
    glGetVertexAttribiv(0,GL_VERTEX_ATTRIB_ARRAY_NORMALIZED,&normalized);glGetVertexAttribiv(0,GL_VERTEX_ATTRIB_ARRAY_BUFFER_BINDING,&attrbuffer);
    glGetVertexAttribPointerv(0,GL_VERTEX_ATTRIB_ARRAY_POINTER,&pointer);
    GLboolean blend=glIsEnabled(GL_BLEND),scissor=glIsEnabled(GL_SCISSOR_TEST),depth=glIsEnabled(GL_DEPTH_TEST);
    glDisable(GL_BLEND);glDisable(GL_SCISSOR_TEST);glDisable(GL_DEPTH_TEST);
    int w,h;SDL_GL_GetDrawableSize(SDL_GL_GetCurrentWindow(),&w,&h);
    if(dst)glViewport(dst->x,h-dst->y-dst->h,dst->w,dst->h);else glViewport(0,0,w,h);
    glUseProgram(program);glUniform1i(glGetUniformLocation(program,"image"),0);glBindTexture(GL_TEXTURE_2D,textures[slot]);
    const GLfloat vertices[]={-1,-1,1,-1,-1,1,1,1};glBindBuffer(GL_ARRAY_BUFFER,0);
    glVertexAttribPointer(0,2,GL_FLOAT,GL_FALSE,0,vertices);glEnableVertexAttribArray(0);glDrawArrays(GL_TRIANGLE_STRIP,0,4);
    /* Wayland's first EGL backbuffer can precede fullscreen configure. */
    if(!checked && ++draws >= 10){
        if(w!=1920 || h!=1080 || (dst && (dst->x || dst->y || dst->w!=1920 || dst->h!=1080)))abort();
        int maximum=0;
        for(int i=0;i<3;i++){
            uint8_t actual[4]={19,29,39,49};glReadPixels(sample_x[i],h-1-sample_y[i],1,1,GL_RGBA,GL_UNSIGNED_BYTE,actual);
            fprintf(stderr,"PACKED_PIXEL %d,%d expected=%u,%u,%u actual=%u,%u,%u error=%x\n",sample_x[i],sample_y[i],expected_rgb[i][0],expected_rgb[i][1],expected_rgb[i][2],actual[0],actual[1],actual[2],glGetError());
            for(int c=0;c<3;c++){int diff=abs((int)actual[c]-expected_rgb[i][c]);if(diff>maximum)maximum=diff;}
        }
        fprintf(stderr,"ATLAS_PACKED_COLOR samples=3 max_error=%d\n",maximum);
        if(maximum>4)abort();
        checked=1;
    }
    glBindBuffer(GL_ARRAY_BUFFER,attrbuffer);glVertexAttribPointer(0,size,type,normalized,stride,pointer);
    if(!enabled)glDisableVertexAttribArray(0);
    glBindBuffer(GL_ARRAY_BUFFER,buffer);
    glBindTexture(GL_TEXTURE_2D,binding);glActiveTexture(active);glUseProgram(oldprogram);
    glViewport(viewport[0],viewport[1],viewport[2],viewport[3]);
    if(blend)glEnable(GL_BLEND);
    if(scissor)glEnable(GL_SCISSOR_TEST);
    if(depth)glEnable(GL_DEPTH_TEST);
    return 0;
}

void SDL_DestroyTexture(SDL_Texture *t)
{
    void(*real)(SDL_Texture *)=dlsym(RTLD_NEXT,"SDL_DestroyTexture");if(!real)abort();
    if(t==target){if(ready){glDeleteTextures(3,textures);glDeleteProgram(program);}target=NULL;owner=NULL;ready=0;checked=0;draws=0;}
    real(t);
}
