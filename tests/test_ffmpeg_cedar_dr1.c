/* The existing mock supplies AU/PTS/backpressure semantics. Exercise a caller
 * allocator with three independent AVBufferRefs and deliberately padded rows. */
#define main existing_batch_main
#include "test_ffmpeg_cedar_v7_batch.c"
#undef main

static unsigned allocations, callbacks;
static int invalid_stride;

#ifndef OLD_CLIENT
int t736_client_pull_to(int session, size_t capacity, struct t736_frame *frame,
                        unsigned timeout, t736_copy_picture cb, void *opaque)
{
    uint8_t packed[16*16*3/2];
    int ret = t736_client_pull(session, packed, capacity, frame, timeout);
    if (ret != 1) return ret;
    callbacks++;
    int copied = cb(opaque, frame, packed);
    return copied < 0 ? copied : 1;
}
#endif

static int get_image(AVCodecContext *ctx, AVFrame *frame, int flags)
{
    CHECK(ctx->opaque == &allocations);
    CHECK((ctx->codec->capabilities & AV_CODEC_CAP_DR1) != 0);
    CHECK(frame->format == AV_PIX_FMT_YUV420P && frame->width == 16 && frame->height == 16);
    CHECK(!flags);
    allocations++;
    for (int i = 0; i < 3; i++) {
        int n = i == 0 ? 16 : 8;
        frame->linesize[i] = n + 32;
        frame->buf[i] = av_buffer_alloc(frame->linesize[i] * n + 16);
        CHECK(frame->buf[i]);
        memset(frame->buf[i]->data, 0xca, frame->buf[i]->size);
        frame->data[i] = frame->buf[i]->data + 8;
    }
    if (invalid_stride) frame->linesize[1] = 4;
    return 0;
}

static void verify(const AVFrame *frame, uint8_t v)
{
    for (int i = 0; i < 3; i++) {
        const int n = i == 0 ? 16 : 8;
        CHECK(frame->buf[i] && frame->linesize[i] == n+32);
        for (int y = 0; y < n; y++) {
            for (int x = 0; x < frame->linesize[i]; x++) {
                CHECK(frame->data[i][y*frame->linesize[i]+x] == (x<n ? v : 0xca));
            }
        }
        CHECK(frame->buf[i]->data[0] == 0xca);
        CHECK(frame->buf[i]->data[frame->buf[i]->size-1] == 0xca);
    }
}

int main(void)
{
    memset(&stub,0,sizeof(stub)); stub.gate=1;
    AVCodecContext *ctx = context(AV_CODEC_ID_HEVC);
    ctx->opaque = &allocations; ctx->get_buffer2 = get_image;
    AVFrame *one = av_frame_alloc(), *next = av_frame_alloc(); CHECK(one && next);
    CHECK(avcodec_receive_frame(ctx,next) == AVERROR(EAGAIN)); CHECK(allocations == 0);
    AVPacket *p = packet(AV_CODEC_ID_HEVC,0);
    CHECK(avcodec_send_packet(ctx,p) == 0); av_packet_free(&p);
    CHECK(avcodec_receive_frame(ctx,one) == 0 && one->pts == 0 && one->duration == 1000);
    verify(one,1);
    CHECK(avcodec_receive_frame(ctx,next) == AVERROR(EAGAIN)); CHECK(allocations == 1);
    p=packet(AV_CODEC_ID_HEVC,1); CHECK(avcodec_send_packet(ctx,p) == 0); av_packet_free(&p);
    CHECK(avcodec_receive_frame(ctx,next) == 0 && next->pts == 1000); verify(next,2);
    av_frame_unref(next);
    avcodec_flush_buffers(ctx); verify(one,1);
    invalid_stride=1;
    p=packet(AV_CODEC_ID_HEVC,0);
    int ret=avcodec_send_packet(ctx,p); av_packet_free(&p);
    if (!ret) ret=avcodec_receive_frame(ctx,next);
    CHECK(ret==AVERROR(EPROTO)); CHECK(!next->buf[0]);
    avcodec_free_context(&ctx); verify(one,1);
    CHECK(allocations==3);
#ifndef OLD_CLIENT
    CHECK(callbacks==3);
#endif
    av_frame_free(&one); av_frame_free(&next);
    printf("PASS dr1 checks=%u allocations=%u callback=%u\n",checks,allocations,callbacks);
    return 0;
}
