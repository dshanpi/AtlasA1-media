/* Exercise the candidate's actual Gst direct-slot path with distinct physical
 * chroma planes, visible cropping, padding, tail rows, and poisoned end guards. */
#include "../tools/browser/cedar_backend.c"
#include <assert.h>

static void test_layout(GstVideoFormat format, unsigned width, unsigned height,
                        unsigned padding, unsigned workers)
{
    unsigned cw = (width + 1) / 2, sh = height + 16, ch = (sh + 1) / 2;
    gint strides[GST_VIDEO_MAX_PLANES] = {width + padding, cw + padding, cw + padding, 0};
    gsize offsets[GST_VIDEO_MAX_PLANES] = {0, (gsize)sh*strides[0], 0, 0};
    offsets[2] = offsets[1] + (gsize)ch*strides[1];
    gsize span = offsets[2] + (gsize)ch*strides[2];
    GstBuffer *buffer = gst_buffer_new_allocate(NULL, span, NULL);
    GstVideoInfo info;
    gst_video_info_set_format(&info, format, width, sh);
    assert(gst_buffer_add_video_meta_full(buffer, 0, format, width, sh, 3, offsets, strides));
    GstVideoCropMeta *crop = gst_buffer_add_video_crop_meta(buffer);
    crop->x = 0; crop->y = 6; crop->width = width; crop->height = height;
    GstMapInfo map;
    assert(gst_buffer_map(buffer, &map, GST_MAP_WRITE));
    for (gsize i = 0; i < span; i++)
        map.data[i] = (uint8_t)(i*39 + (i >> 6) + (i >> 17));
    gst_buffer_unmap(buffer, &map);
    GstCaps *caps = gst_video_info_to_caps(&info);
    GstSample *sample = gst_sample_new(buffer, caps, NULL, NULL);
    cedar_decoder *d = calloc(1, sizeof(*d));
    assert(d);
    d->width = width; d->height = height;
    cedar_frame reference = {0}, direct = {0};
    assert(copy_sample(d, sample, &reference, NULL, 0) == CEDAR_FRAME);
    assert(reference.size == (size_t)width*height + 2U*(size_t)cw*((height+1)/2));
    uint8_t *slot = malloc(reference.size+18);
    assert(slot);
    for (unsigned i = 0; i < 5; i++) {
        memset(slot, 0xcc, reference.size+18);
        assert(copy_sample(d, sample, &direct, slot+9, reference.size) == CEDAR_FRAME);
        assert(direct.data == NULL && direct.size == reference.size);
        assert(memcmp(slot+9, reference.data, reference.size) == 0);
        for (unsigned j = 0; j < 9; j++)
            assert(slot[j] == 0xcc && slot[9+reference.size+j] == 0xcc);
    }
    assert(d->copy_pool.count == (padding ? 0 : workers));
    free(slot);
    cedar_frame_free(&reference);
    cedar_close(d);
    gst_sample_unref(sample);
    gst_caps_unref(caps);
    gst_buffer_unref(buffer);
}

int main(int argc, char **argv)
{
    assert(argc == 2);
    unsigned workers = (unsigned)atoi(argv[1]);
    gst_init(NULL, NULL);
    test_layout(GST_VIDEO_FORMAT_YV12, 3840, 2160, 0, workers);
    test_layout(GST_VIDEO_FORMAT_I420, 1921, 1081, 0, workers);
    test_layout(GST_VIDEO_FORMAT_YV12, 1920, 1080, 4, workers);
    printf("PASS: validated direct frames, both planar orders, cropped 4K, odd extents, padded strides, repeated dispatch and teardown, %u workers\n", workers);
}
