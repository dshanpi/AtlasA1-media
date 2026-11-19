/* SPDX-License-Identifier: MIT
 * Offscreen DMA-BUF import test. Allocates synthetic pixels, never decodes video
 * or changes KMS. Run with the matching PVR runtime and explicit heap path.
 */
#define _GNU_SOURCE
#include <GLES2/gl2.h>
#include <dlfcn.h>
#include <fcntl.h>
#include <linux/dma-heap.h>
#include <linux/dma-buf.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <unistd.h>
typedef void *EGLDisplay;
typedef void *EGLImage;
extern EGLDisplay eglGetCurrentDisplay(void);
extern unsigned eglGetError(void);
extern void *eglGetProcAddress(const char *);
extern const char *eglQueryString(EGLDisplay,int);
static GLuint compile(GLenum type,const char *src)
{
    GLuint shader=glCreateShader(type);GLint ok=0;
    glShaderSource(shader,1,&src,NULL);glCompileShader(shader);glGetShaderiv(shader,GL_COMPILE_STATUS,&ok);
    if(!ok){char log[1024];glGetShaderInfoLog(shader,sizeof(log),NULL,log);fprintf(stderr,"shader %s\n",log);exit(1);}
    return shader;
}
static unsigned char limit(float f){return f<0?0:f>255?255:(unsigned char)(f+.5f);}
static struct {
    int fd,w,h,visible_h,ystride,cstride,voffset,uoffset;
    size_t size;
} real_frame={.fd=-1};
static int fixture(int heap,EGLDisplay display,uint32_t format,int nv21)
{
    const int W=real_frame.fd>=0?real_frame.w:64,H=real_frame.fd>=0?real_frame.h:64;
    const unsigned char rgb[4][3]={{255,0,0},{0,255,0},{0,0,255},{255,255,0}};
    const unsigned char yuv[4][3]={{81,90,240},{145,54,34},{41,240,110},{210,16,146}};
    unsigned char expected[4][3];
    int is_yuv=format!=0x34324241U,result=1;
    struct dma_heap_allocation_data alloc={.len=65536,.fd_flags=O_RDWR|O_CLOEXEC};
    if(real_frame.fd>=0){alloc.fd=dup(real_frame.fd);alloc.len=real_frame.size;if((int)alloc.fd<0)return 1;}
    else if(ioctl(heap,DMA_HEAP_IOCTL_ALLOC,&alloc)){perror("heap allocate");return 1;}
    unsigned char *pixels=mmap(NULL,alloc.len,PROT_READ|(real_frame.fd>=0?0:PROT_WRITE),MAP_SHARED,alloc.fd,0);
    if(pixels==MAP_FAILED){perror("mmap");close(alloc.fd);return 1;}
    struct dma_buf_sync sync={.flags=DMA_BUF_SYNC_START|(real_frame.fd>=0?DMA_BUF_SYNC_READ:DMA_BUF_SYNC_WRITE)};
    if(ioctl(alloc.fd,DMA_BUF_IOCTL_SYNC,&sync)){perror("cpu begin");goto close_buffer;}
    if(real_frame.fd<0){
    memset(pixels,0,alloc.len);
    for(int y=0;y<H;y++)for(int x=0;x<W;x++){
        int q=(x>=W/2)+2*(y>=H/2);
        if(is_yuv){
            pixels[y*W+x]=yuv[q][0];
            if(!(x&1) && !(y&1)){
                pixels[W*H+(y/2)*W+x]=yuv[q][nv21?2:1];
                pixels[W*H+(y/2)*W+x+1]=yuv[q][nv21?1:2];
            }
        }else{memcpy(pixels+4*(y*W+x),rgb[q],3);pixels[4*(y*W+x)+3]=255;}
    }
    for(int q=0;q<4;q++){
        if(is_yuv){
            float y=1.16438356f*(yuv[q][0]-16.f),u=yuv[q][1]-128.f,v=yuv[q][2]-128.f;
            expected[q][0]=limit(y+1.792741f*v);expected[q][1]=limit(y-.213249f*u-.532909f*v);expected[q][2]=limit(y+2.112402f*u);
        }else memcpy(expected[q],rgb[q],3);
    }
    }else{
        for(int q=0;q<4;q++){
            int x=((q%2)*32+16)*W/64+W/128;
            int row=((q/2)*32+16)*real_frame.visible_h/64+real_frame.visible_h/128;
            float y=1.16438356f*(pixels[row*real_frame.ystride+x]-16.f);
            float u=pixels[real_frame.uoffset+(row/2)*real_frame.cstride+x/2]-128.f;
            float v=pixels[real_frame.voffset+(row/2)*real_frame.cstride+x/2]-128.f;
            expected[q][0]=limit(y+1.792741f*v);expected[q][1]=limit(y-.213249f*u-.532909f*v);expected[q][2]=limit(y+2.112402f*u);
        }
    }
    sync.flags=DMA_BUF_SYNC_END|(real_frame.fd>=0?DMA_BUF_SYNC_READ:DMA_BUF_SYNC_WRITE);
    if(ioctl(alloc.fd,DMA_BUF_IOCTL_SYNC,&sync)){perror("cpu end");goto close_buffer;}
    EGLImage(*create)(EGLDisplay,void *,unsigned,void *,const int *)=eglGetProcAddress("eglCreateImageKHR");
    unsigned(*destroy)(EGLDisplay,EGLImage)=eglGetProcAddress("eglDestroyImageKHR");
    void(*image_target)(GLenum,void *)=eglGetProcAddress("glEGLImageTargetTexture2DOES");
    if(!create || !destroy || !image_target){fputs("missing image API\n",stderr);goto close_buffer;}
    int attrs[40],n=0;
#define ATTR(k,v) do {attrs[n++]=(k);attrs[n++]=(v);}while(0)
    ATTR(0x3057,W);ATTR(0x3056,H);ATTR(0x3271,(int)format);
    ATTR(0x3272,(int)alloc.fd);ATTR(0x3273,0);ATTR(0x3274,real_frame.fd>=0?real_frame.ystride:is_yuv?W:W*4);
    if(real_frame.fd>=0){
        ATTR(0x3275,(int)alloc.fd);ATTR(0x3276,real_frame.voffset);ATTR(0x3277,real_frame.cstride);
        ATTR(0x3278,(int)alloc.fd);ATTR(0x3279,real_frame.uoffset);ATTR(0x327a,real_frame.cstride);
        ATTR(0x327b,0x3280);ATTR(0x327c,0x3283);
    }else if(is_yuv){ATTR(0x3275,(int)alloc.fd);ATTR(0x3276,W*H);ATTR(0x3277,W);ATTR(0x327b,0x3280);ATTR(0x327c,0x3283);}
    attrs[n++]=0x3038;
    EGLImage image=create(display,NULL,0x3270,NULL,attrs);
    if(!image){fprintf(stderr,"IMPORT_FAILED fourcc=%08x egl=%x\n",format,eglGetError());goto close_buffer;}
    GLuint tex,program,vs,fs;
    vs=compile(GL_VERTEX_SHADER,"attribute vec2 pos; varying vec2 uv; void main(){gl_Position=vec4(pos,0.,1.);uv=(pos+1.)*.5;}");
    fs=compile(GL_FRAGMENT_SHADER,"#extension GL_OES_EGL_image_external : require\nprecision mediump float; uniform samplerExternalOES image; uniform float yscale; varying vec2 uv; void main(){gl_FragColor=texture2D(image,vec2(uv.x,uv.y*yscale));}");
    program=glCreateProgram();glAttachShader(program,vs);glAttachShader(program,fs);glBindAttribLocation(program,0,"pos");glLinkProgram(program);
    GLint ok=0;glGetProgramiv(program,GL_LINK_STATUS,&ok);
    if(!ok){fputs("link failed\n",stderr);goto close_gl;}
    glGenTextures(1,&tex);glBindTexture(0x8d65,tex);image_target(0x8d65,image);
    glTexParameteri(0x8d65,GL_TEXTURE_MIN_FILTER,GL_NEAREST);glTexParameteri(0x8d65,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
    glTexParameteri(0x8d65,GL_TEXTURE_WRAP_S,GL_CLAMP_TO_EDGE);glTexParameteri(0x8d65,GL_TEXTURE_WRAP_T,GL_CLAMP_TO_EDGE);
    glViewport(0,0,64,64);glUseProgram(program);glUniform1i(glGetUniformLocation(program,"image"),0);glUniform1f(glGetUniformLocation(program,"yscale"),real_frame.fd>=0?(float)real_frame.visible_h/H:1.f);
    const GLfloat vertices[]={-1,-1,1,-1,-1,1,1,1};glVertexAttribPointer(0,2,GL_FLOAT,GL_FALSE,0,vertices);glEnableVertexAttribArray(0);
    glDrawArrays(GL_TRIANGLE_STRIP,0,4);glFinish();
    int maximum=0;
    for(int q=0;q<4;q++){
        unsigned char actual[4]={19,29,39,49};
        glReadPixels((q%2)*32+16,(q/2)*32+16,1,1,GL_RGBA,GL_UNSIGNED_BYTE,actual);
        printf("PIXEL fourcc=%08x q=%d actual=%u,%u,%u expected=%u,%u,%u\n",format,q,actual[0],actual[1],actual[2],expected[q][0],expected[q][1],expected[q][2]);
        for(int c=0;c<3;c++){int error=abs((int)actual[c]-expected[q][c]);if(error>maximum)maximum=error;}
    }
    GLenum error=glGetError();result=maximum>5 || error;
    printf("IMPORT_RESULT fourcc=%08x max_error=%d gl=%x passed=%d\n",format,maximum,error,!result);
    glDeleteTextures(1,&tex);
close_gl:
    glUseProgram(0);glDeleteProgram(program);glDeleteShader(vs);glDeleteShader(fs);destroy(display,image);
close_buffer:
    munmap(pixels,alloc.len);close(alloc.fd);return result;
}

static int probe_run(int argc,char **argv)
{
    if(argc!=2 || strcmp(argv[1],"/dev/dma_heap/t736-ve")){fputs("Usage: cedar-gpu-import /dev/dma_heap/t736-ve\n",stderr);return 2;}
    unsetenv("DISPLAY");unsetenv("WAYLAND_DISPLAY");setenv("SDL_VIDEODRIVER","offscreen",1);
    void *sdl=dlopen("libSDL2-2.0.so.0",RTLD_NOW|RTLD_GLOBAL);if(!sdl){fprintf(stderr,"%s\n",dlerror());return 1;}
#define SDL(ret,name,args) ret(*name)args=dlsym(sdl,#name); if(!name)return 1
    SDL(int,SDL_Init,(unsigned));SDL(void,SDL_Quit,(void));SDL(int,SDL_GL_SetAttribute,(int,int));
    SDL(void *,SDL_CreateWindow,(const char *,int,int,int,int,unsigned));SDL(void,SDL_DestroyWindow,(void *));
    SDL(void *,SDL_GL_CreateContext,(void *));SDL(void,SDL_GL_DeleteContext,(void *));SDL(const char *,SDL_GetError,(void));
    if(SDL_Init(0x20)){fprintf(stderr,"SDL: %s\n",SDL_GetError());return 1;}
    SDL_GL_SetAttribute(21,4);SDL_GL_SetAttribute(17,2);SDL_GL_SetAttribute(18,0);
    SDL_GL_SetAttribute(0,8);SDL_GL_SetAttribute(1,8);SDL_GL_SetAttribute(2,8);
    void *window=SDL_CreateWindow("Cedar GPU import diagnostic",0,0,64,64,2|8);
    void *ctx=window?SDL_GL_CreateContext(window):NULL;
    if(!ctx){fprintf(stderr,"SDL context: %s\n",SDL_GetError());return 1;}
    const char *renderer=(const char *)glGetString(GL_RENDERER);printf("GPU=%s\n",renderer?renderer:"null");
    if(!renderer || !strstr(renderer,"PowerVR"))return 1;
    EGLDisplay display=eglGetCurrentDisplay();printf("EGL_EXT=%s\n",eglQueryString(display,0x3055));
    int heap=open(argv[1],O_RDWR|O_CLOEXEC);if(heap<0){perror("heap");return 1;}
    int failed;
    if(real_frame.fd>=0)failed=fixture(heap,display,0x32315659U,0);
    else{
        failed=fixture(heap,display,0x34324241U,0);
        failed|=fixture(heap,display,0x3231564eU,0);failed|=fixture(heap,display,0x3132564eU,1);
    }
    close(heap);SDL_GL_DeleteContext(ctx);SDL_DestroyWindow(window);SDL_Quit();return failed?1:0;
}

int cedar_gpu_check_yv12(int fd,int w,int h,int visible_h,int ystride,int cstride,
                         int voffset,int uoffset,size_t size)
{
    if(fd<0 || w<=0 || h<=0 || w>4096 || h>4096 || (w&1) || (h&1) ||
       visible_h<=0 || visible_h>h || ystride<w || cstride<w/2 || voffset<0 || uoffset<0 ||
       (size_t)ystride*h>size || (size_t)voffset+(size_t)cstride*(h/2)>size ||
       (size_t)uoffset+(size_t)cstride*(h/2)>size)return 2;
    real_frame=(__typeof__(real_frame)){fd,w,h,visible_h,ystride,cstride,voffset,uoffset,size};
    char *args[]={"cedar-gpu-frame-check","/dev/dma_heap/t736-ve",NULL};
    int rc=probe_run(2,args);real_frame.fd=-1;return rc;
}
int main(int argc,char **argv){return probe_run(argc,argv);}
