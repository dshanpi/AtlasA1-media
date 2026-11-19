/* SPDX-License-Identifier: MIT
 * Diagnostic only: OMX DMA-BUF -> EGLImage -> GLES -> GNOME Wayland.
 * No audio, subtitles, browser integration or production privilege model.
 * Retains each GstSample until glFinish or its EGL fence; imported cache is
 * destroyed before the decoder pipeline. Never copies video pixels on CPU.
 */
#define _GNU_SOURCE
#include <SDL.h>
#include <GLES2/gl2.h>
#include <gst/gst.h>
#include <gst/app/gstappsink.h>
#include <gst/video/video.h>
#include <gst/allocators/gstdmabuf.h>
#include <dlfcn.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>
typedef void *EGLDisplay;
typedef void *EGLImage;
extern EGLDisplay eglGetCurrentDisplay(void);
extern unsigned eglGetError(void);
extern void *eglGetProcAddress(const char *);
static struct entry { dev_t dev;ino_t ino;int fd,w,h,strides[3];size_t offsets[3];GLuint texture;EGLImage image; } cache[64];
static unsigned cached;
static struct frame_timing {uint64_t begin,pulled,imported,drawn,deadline,swap_begin,swap_end;} timing[16384];
static EGLImage(*create_image)(EGLDisplay,void *,unsigned,void *,const int *);
static unsigned(*destroy_image)(EGLDisplay,EGLImage);
static void(*image_target)(GLenum,void *);
static uint64_t now_ns(void){struct timespec ts;clock_gettime(CLOCK_MONOTONIC,&ts);return (uint64_t)ts.tv_sec*1000000000ULL+ts.tv_nsec;}
static GLuint shader(GLenum type,const char *src)
{
    GLuint s=glCreateShader(type);GLint ok=0;glShaderSource(s,1,&src,NULL);glCompileShader(s);glGetShaderiv(s,GL_COMPILE_STATUS,&ok);
    if(!ok){char log[1024];glGetShaderInfoLog(s,sizeof(log),NULL,log);fprintf(stderr,"SHADER %s\n",log);exit(1);}return s;
}
static struct entry *import_sample(EGLDisplay display,GstSample *sample,int *visible_w,int *visible_h)
{
    GstBuffer *b=gst_sample_get_buffer(sample);GstVideoInfo info;
    if(!gst_video_info_from_caps(&info,gst_sample_get_caps(sample)) || GST_VIDEO_INFO_FORMAT(&info)!=GST_VIDEO_FORMAT_YV12 || gst_buffer_n_memory(b)!=1)return NULL;
    GstMemory *mem=gst_buffer_peek_memory(b,0);
    if(!gst_is_dmabuf_memory(mem) || mem->offset || info.width<=0 || info.height<=0 || info.width>4096 || info.height>4096 || (info.width&1) || (info.height&1))return NULL;
    GstVideoMeta *meta=gst_buffer_get_video_meta(b);GstVideoCropMeta *crop=gst_buffer_get_video_crop_meta(b);
    if(crop && (crop->x || crop->y || crop->width>(unsigned)info.width || crop->height>(unsigned)info.height))return NULL;
    *visible_w=crop?(int)crop->width:info.width;*visible_h=crop?(int)crop->height:info.height;
    int strides[3];size_t offsets[3];
    for(int i=0;i<3;i++){
        strides[i]=meta?meta->stride[i]:info.stride[i];offsets[i]=meta?meta->offset[i]:info.offset[i];
        if(strides[i]<(info.width>>(i!=0)) || offsets[i]+(size_t)strides[i]*(info.height>>(i!=0))>mem->size)return NULL;
    }
    int fd=gst_dmabuf_memory_get_fd(mem);struct stat st;if(fstat(fd,&st))return NULL;
    if(!cached)printf("DMA_FORMAT format=YV12 coded=%dx%d visible=%dx%d bytes=%zu\n",info.width,info.height,*visible_w,*visible_h,mem->size);
    for(unsigned i=0;i<cached;i++)if(cache[i].dev==st.st_dev && cache[i].ino==st.st_ino){
        if(cache[i].w!=info.width || cache[i].h!=info.height || memcmp(cache[i].strides,strides,sizeof(strides)) || memcmp(cache[i].offsets,offsets,sizeof(offsets)))return NULL;
        return &cache[i];
    }
    if(cached==64)return NULL;
    struct entry *e=&cache[cached];e->fd=fcntl(fd,F_DUPFD_CLOEXEC,3);if(e->fd<0)return NULL;
    e->dev=st.st_dev;e->ino=st.st_ino;e->w=info.width;e->h=info.height;
    memcpy(e->strides,strides,sizeof(strides));memcpy(e->offsets,offsets,sizeof(offsets));
    const int attrs[]={0x3057,info.width,0x3056,info.height,0x3271,0x32315659,
        0x3272,e->fd,0x3273,(int)offsets[0],0x3274,strides[0],
        0x3275,e->fd,0x3276,(int)offsets[1],0x3277,strides[1],
        0x3278,e->fd,0x3279,(int)offsets[2],0x327a,strides[2],
        0x327b,0x3280,0x327c,0x3283,0x3038};
    e->image=create_image(display,NULL,0x3270,NULL,attrs);
    if(!e->image){fprintf(stderr,"IMPORT egl=%x\n",eglGetError());close(e->fd);return NULL;}
    glGenTextures(1,&e->texture);glBindTexture(0x8d65,e->texture);image_target(0x8d65,e->image);
    glTexParameteri(0x8d65,GL_TEXTURE_MIN_FILTER,GL_LINEAR);glTexParameteri(0x8d65,GL_TEXTURE_MAG_FILTER,GL_LINEAR);
    glTexParameteri(0x8d65,GL_TEXTURE_WRAP_S,GL_CLAMP_TO_EDGE);glTexParameteri(0x8d65,GL_TEXTURE_WRAP_T,GL_CLAMP_TO_EDGE);
    cached++;return e;
}
int main(int argc,char **argv)
{
    int hevc=argc==3 && !strcmp(argv[2],"--hevc");
    if((argc!=2 && !hevc) || !getenv("WAYLAND_DISPLAY")){fputs("Run in the board Wayland session: dmabuf-player CLIP.mp4 [--hevc]\n",stderr);return 2;}
    void(*trace)(SDL_Window *)=dlsym(RTLD_DEFAULT,"atlas_wayland_frame");
    void(*finish_trace)(void)=dlsym(RTLD_DEFAULT,"atlas_wayland_finish");
    if(!trace || !finish_trace){fputs("Presentation tracer is required\n",stderr);return 2;}
    setenv("SDL_VIDEODRIVER","wayland",1);gst_init(NULL,NULL);
    if(SDL_Init(SDL_INIT_VIDEO)){fprintf(stderr,"SDL %s\n",SDL_GetError());return 1;}
    SDL_GL_SetAttribute(SDL_GL_CONTEXT_PROFILE_MASK,SDL_GL_CONTEXT_PROFILE_ES);
    SDL_GL_SetAttribute(SDL_GL_CONTEXT_MAJOR_VERSION,2);SDL_GL_SetAttribute(SDL_GL_CONTEXT_MINOR_VERSION,0);
    SDL_GL_SetAttribute(SDL_GL_RED_SIZE,8);SDL_GL_SetAttribute(SDL_GL_GREEN_SIZE,8);SDL_GL_SetAttribute(SDL_GL_BLUE_SIZE,8);
    SDL_Window *window=SDL_CreateWindow("AtlasA1 DMA-BUF playback diagnostic",SDL_WINDOWPOS_CENTERED,SDL_WINDOWPOS_CENTERED,1920,1080,SDL_WINDOW_OPENGL|SDL_WINDOW_FULLSCREEN_DESKTOP);
    SDL_GLContext context=window?SDL_GL_CreateContext(window):NULL;
    if(!context){fprintf(stderr,"SDL context %s\n",SDL_GetError());return 1;}
    int vsync=getenv("ATLAS_DMA_VSYNC") && !strcmp(getenv("ATLAS_DMA_VSYNC"),"1");
    int unpaced=getenv("ATLAS_DMA_UNPACED") && !strcmp(getenv("ATLAS_DMA_UNPACED"),"1");
    SDL_ShowCursor(SDL_DISABLE);
    if(SDL_GL_SetSwapInterval(vsync)){fprintf(stderr,"swap interval: %s\n",SDL_GetError());return 1;}
    printf("DMA_PACING vsync=%d unpaced=%d\n",vsync,unpaced);
    const char *gpu=(const char *)glGetString(GL_RENDERER);printf("GPU=%s\n",gpu?gpu:"null");
    if(!gpu || !strstr(gpu,"PowerVR"))return 1;
    EGLDisplay display=eglGetCurrentDisplay();create_image=eglGetProcAddress("eglCreateImageKHR");destroy_image=eglGetProcAddress("eglDestroyImageKHR");image_target=eglGetProcAddress("glEGLImageTargetTexture2DOES");
    if(!display || !create_image || !destroy_image || !image_target)return 1;
    int async=getenv("ATLAS_DMA_ASYNC") && !strcmp(getenv("ATLAS_DMA_ASYNC"),"1");
    void *(*create_sync)(EGLDisplay,unsigned,const int *)=eglGetProcAddress("eglCreateSyncKHR");
    unsigned(*wait_sync)(EGLDisplay,void *,int,uint64_t)=eglGetProcAddress("eglClientWaitSyncKHR");
    unsigned(*destroy_sync)(EGLDisplay,void *)=eglGetProcAddress("eglDestroySyncKHR");
    struct {GstSample *sample;void *fence;} pending[3]={{0}};
    if(async && (!create_sync || !wait_sync || !destroy_sync))return 1;
    GLuint vs=shader(GL_VERTEX_SHADER,"attribute vec2 pos; varying vec2 uv; void main(){gl_Position=vec4(pos,0.,1.);uv=vec2((pos.x+1.)*.5,(1.-pos.y)*.5);}");
    GLuint fs=shader(GL_FRAGMENT_SHADER,"#extension GL_OES_EGL_image_external : require\nprecision mediump float; uniform samplerExternalOES image; uniform vec2 scale; varying vec2 uv; void main(){gl_FragColor=texture2D(image,uv*scale);}");
    GLuint program=glCreateProgram();glAttachShader(program,vs);glAttachShader(program,fs);glBindAttribLocation(program,0,"pos");glLinkProgram(program);
    GLint linked=0;glGetProgramiv(program,GL_LINK_STATUS,&linked);if(!linked)return 1;
    glUseProgram(program);glUniform1i(glGetUniformLocation(program,"image"),0);
    const GLfloat vertices[]={-1,-1,1,-1,-1,1,1,1};glVertexAttribPointer(0,2,GL_FLOAT,GL_FALSE,0,vertices);glEnableVertexAttribArray(0);
    for(int i=0;i<5;i++){SDL_PumpEvents();glClearColor(0,0,0,1);glClear(GL_COLOR_BUFFER_BIT);SDL_GL_SwapWindow(window);SDL_Delay(20);}
    GError *error=NULL;
    GstElement *pipeline=gst_parse_launch(hevc?
        "filesrc name=source ! qtdemux ! h265parse ! omxhevcvideodec ! appsink name=output sync=false max-buffers=4":
        "filesrc name=source ! qtdemux ! h264parse ! omxh264dec ! appsink name=output sync=false max-buffers=4",&error);
    if(!pipeline || error){fprintf(stderr,"pipeline %s\n",error?error->message:"null");return 1;}
    GstElement *source=gst_bin_get_by_name(GST_BIN(pipeline),"source"),*sink=gst_bin_get_by_name(GST_BIN(pipeline),"output");
    g_object_set(source,"location",argv[1],NULL);gst_object_unref(source);
    int failed=0;unsigned frames=0;uint64_t start=0,first_pts=0,last_pts=0,max_late=0,draw_ns=0;
    if(gst_element_set_state(pipeline,GST_STATE_PLAYING)==GST_STATE_CHANGE_FAILURE)failed=1;
    while(!failed){
        uint64_t frame_begin=now_ns();
        unsigned pending_slot=frames%3;
        if(pending[pending_slot].sample){
            if(wait_sync(display,pending[pending_slot].fence,1,1000000000ULL)!=0x30f6){failed=1;break;}
            destroy_sync(display,pending[pending_slot].fence);
            gst_sample_unref(pending[pending_slot].sample);pending[pending_slot].sample=NULL;
        }
        GstSample *sample=gst_app_sink_try_pull_sample(GST_APP_SINK(sink),10*GST_SECOND);
        uint64_t frame_pulled=now_ns();
        if(!sample){if(!gst_app_sink_is_eos(GST_APP_SINK(sink)))failed=1;break;}
        GstBuffer *b=gst_sample_get_buffer(sample);uint64_t pts=GST_BUFFER_PTS(b);
        int visible_w,visible_h;struct entry *e=import_sample(display,sample,&visible_w,&visible_h);
        uint64_t frame_imported=now_ns();
        if(!e || pts==GST_CLOCK_TIME_NONE || (frames && pts<last_pts)){gst_sample_unref(sample);failed=1;break;}
        int w,h;SDL_GL_GetDrawableSize(window,&w,&h);glViewport(0,0,w,h);
        glBindTexture(0x8d65,e->texture);glUniform2f(glGetUniformLocation(program,"scale"),(float)visible_w/e->w,(float)visible_h/e->h);
        uint64_t draw_start=now_ns();glDrawArrays(GL_TRIANGLE_STRIP,0,4);
        if(async){
            const int attrs[]={0x3038};pending[pending_slot].fence=create_sync(display,0x30f9,attrs);glFlush();
            if(!pending[pending_slot].fence){glFinish();gst_sample_unref(sample);failed=1;break;}
            pending[pending_slot].sample=sample;
        }else glFinish();
        draw_ns+=now_ns()-draw_start;
        if(glGetError()){glFinish();if(!async)gst_sample_unref(sample);failed=1;break;}
        /* Decoder cannot recycle this frame until all GPU reads have completed. */
        if(!async)gst_sample_unref(sample);
        uint64_t frame_drawn=now_ns();
        if(!frames){start=now_ns();first_pts=pts;}
        uint64_t deadline=start+pts-first_pts;
        struct timespec ts={(time_t)(deadline/1000000000ULL),(long)(deadline%1000000000ULL)};
        if(!unpaced)clock_nanosleep(CLOCK_MONOTONIC,TIMER_ABSTIME,&ts,NULL);
        uint64_t stamp=now_ns();if(stamp>deadline && stamp-deadline>max_late)max_late=stamp-deadline;
        trace(window);SDL_GL_SwapWindow(window);
        if(frames<16384)timing[frames]=(struct frame_timing){frame_begin,frame_pulled,frame_imported,frame_drawn,deadline,stamp,now_ns()};
        frames++;last_pts=pts;
        SDL_Event event;while(SDL_PollEvent(&event))if(event.type==SDL_QUIT || (event.type==SDL_KEYDOWN && event.key.keysym.sym==SDLK_ESCAPE))failed=1;
    }
    uint64_t end=now_ns();finish_trace();glFinish();
    const char *timing_path=getenv("ATLAS_DMA_TIMING");
    if(timing_path){
        FILE *out=fopen(timing_path,"wx");
        if(!out){perror("timing output");failed=1;}
        else{
            fputs("frame\tbegin_ns\tpulled_ns\timported_ns\tdrawn_ns\tdeadline_ns\tswap_begin_ns\tswap_end_ns\n",out);
            for(unsigned i=0;i<frames && i<16384;i++){
                struct frame_timing *t=&timing[i];
                fprintf(out,"%u\t%llu\t%llu\t%llu\t%llu\t%llu\t%llu\t%llu\n",i,(unsigned long long)t->begin,(unsigned long long)t->pulled,(unsigned long long)t->imported,(unsigned long long)t->drawn,(unsigned long long)t->deadline,(unsigned long long)t->swap_begin,(unsigned long long)t->swap_end);
            }
            fclose(out);
        }
    }
    for(unsigned i=0;i<3;i++)if(pending[i].sample){destroy_sync(display,pending[i].fence);gst_sample_unref(pending[i].sample);}
    printf("DMA_PLAYER frames=%u elapsed_ms=%.3f pts_span_ms=%.3f submit_mean_ms=%.3f max_late_ms=%.3f imports=%u cpu_frame_copies=0 audio=none async=%d failed=%d\n",frames,start?(end-start)/1e6:0.,frames?(last_pts-first_pts)/1e6:0.,frames?draw_ns/1e6/frames:0.,max_late/1e6,cached,async,failed);
    for(unsigned i=0;i<cached;i++){glDeleteTextures(1,&cache[i].texture);destroy_image(display,cache[i].image);close(cache[i].fd);}
    gst_element_set_state(pipeline,GST_STATE_NULL);gst_object_unref(sink);gst_object_unref(pipeline);
    glDeleteProgram(program);glDeleteShader(vs);glDeleteShader(fs);SDL_GL_DeleteContext(context);SDL_DestroyWindow(window);SDL_Quit();
    return failed?1:0;
}
