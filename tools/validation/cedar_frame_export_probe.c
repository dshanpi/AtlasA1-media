/* SPDX-License-Identifier: MIT
 * Inspect one real OMX frame's backing memory. Does not export it to a client
 * or claim playback. Build against the matching GStreamer and Cedar headers.
 */
#include <gst/gst.h>
#include <gst/app/gstappsink.h>
#include <gst/video/video.h>
#include <dlfcn.h>
#include <stdio.h>
#include <gst/allocators/gstdmabuf.h>
int main(int argc,char **argv)
{
    if(argc!=3){fprintf(stderr,"Usage: cedar-frame-export-probe CLIP.mp4 GPU_CHECK_LIBRARY\n");return 2;}
    gst_init(NULL,NULL);
    GError *error=NULL;
    GstElement *pipeline=gst_parse_launch("filesrc name=source ! qtdemux ! h264parse ! omxh264dec ! appsink name=output sync=false max-buffers=2",&error);
    if(!pipeline || error){fprintf(stderr,"pipeline: %s\n",error?error->message:"null");return 1;}
    GstElement *source=gst_bin_get_by_name(GST_BIN(pipeline),"source");
    GstElement *sink=gst_bin_get_by_name(GST_BIN(pipeline),"output");
    g_object_set(source,"location",argv[1],NULL);gst_object_unref(source);
    int result=1;
    if(gst_element_set_state(pipeline,GST_STATE_PLAYING)==GST_STATE_CHANGE_FAILURE)goto done;
    GstSample *sample=gst_app_sink_try_pull_sample(GST_APP_SINK(sink),15*GST_SECOND);
    if(!sample){
        GstBus *bus=gst_element_get_bus(pipeline);GstMessage *message;
        while((message=gst_bus_pop_filtered(bus,GST_MESSAGE_ERROR))){
            gchar *debug=NULL;GError *why=NULL;gst_message_parse_error(message,&why,&debug);
            fprintf(stderr,"decode: %s %s\n",why?why->message:"",debug?debug:"");
            g_clear_error(&why);g_free(debug);gst_message_unref(message);
        }
        gst_object_unref(bus);goto done;
    }
    GstBuffer *buffer=gst_sample_get_buffer(sample);GstVideoInfo info;
    gst_video_info_init(&info);
    if(!gst_video_info_from_caps(&info,gst_sample_get_caps(sample))){gst_sample_unref(sample);goto done;}
    printf("FRAME format=%s size=%ux%u memories=%u\n",gst_video_format_to_string(GST_VIDEO_INFO_FORMAT(&info)),GST_VIDEO_INFO_WIDTH(&info),GST_VIDEO_INFO_HEIGHT(&info),gst_buffer_n_memory(buffer));
    for(guint i=0;i<gst_buffer_n_memory(buffer);i++){
        GstMemory *memory=gst_buffer_peek_memory(buffer,i);
        printf("MEMORY index=%u type=%s offset=%zu size=%zu maxsize=%zu\n",i,memory->allocator?memory->allocator->mem_type:"null",memory->offset,memory->size,memory->maxsize);
    }
    GstMemory *memory=gst_buffer_peek_memory(buffer,0);
    GstVideoCropMeta *crop=gst_buffer_get_video_crop_meta(buffer);
    GstVideoMeta *meta=gst_buffer_get_video_meta(buffer);
    if(gst_buffer_n_memory(buffer)==1 && gst_is_dmabuf_memory(memory) && memory->offset==0 && GST_VIDEO_INFO_FORMAT(&info)==GST_VIDEO_FORMAT_YV12){
        int fd=gst_dmabuf_memory_get_fd(memory);
        int strides[3];size_t offsets[3];
        for(int p=0;p<3;p++){
            strides[p]=meta?meta->stride[p]:info.stride[p];offsets[p]=meta?meta->offset[p]:info.offset[p];
            printf("PLANE index=%d stride=%d offset=%zu dma_fd=%d\n",p,strides[p],offsets[p],fd);
        }
        void *library=dlopen(argv[2],RTLD_NOW|RTLD_LOCAL);
        int(*check)(int,int,int,int,int,int,int,int,size_t)=library?dlsym(library,"cedar_gpu_check_yv12"):NULL;
        if(!check)fprintf(stderr,"GPU checker load: %s\n",dlerror());
        else if(offsets[0]==0 && strides[1]==strides[2] && (!crop || (!crop->x && !crop->y))){
            int visible_h=crop?(int)crop->height:GST_VIDEO_INFO_HEIGHT(&info);
            printf("GPU_CHECK holding_sample=1 crop_height=%d cpu_frame_copy=0\n",visible_h);
            result=check(fd,info.width,info.height,visible_h,strides[0],strides[1],(int)offsets[1],(int)offsets[2],memory->size);
            printf("REAL_FRAME_GPU_IMPORT passed=%d\n",!result);
        }
    }else fputs("frame is not a single YV12 DMA-BUF\n",stderr);
    gst_sample_unref(sample);
done:
    gst_element_set_state(pipeline,GST_STATE_NULL);gst_object_unref(sink);gst_object_unref(pipeline);
    return result;
}
