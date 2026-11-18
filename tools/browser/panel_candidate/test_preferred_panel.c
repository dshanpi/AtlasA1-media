/* SPDX-License-Identifier: MIT */
#include "baseline.inc"

#ifndef TEST_LEGACY_BROKER
cedar_decoder *cedar_open_panel(enum cedar_codec codec, unsigned width, unsigned height,
                               char *error, size_t size)
{
    assert(width == 3840 && height == 2160);
    return cedar_open(codec, width / 2, height / 2, error, size);
}
#endif

static void check_scaled_stub(const uint8_t *result, unsigned ordinal)
{
    size_t source_start = 0;
    for (unsigned plane = 0; plane < 3; ++plane) {
        unsigned width = plane ? 1920 : 3840, height = plane ? 1080 : 2160;
        for (unsigned y = 0; y < height; y += 2) {
            for (unsigned x = 0; x < width; x += 2) {
                size_t i = source_start + (size_t)y * width + x;
                unsigned sum = (uint8_t)(ordinal + i * 17U)
                             + (uint8_t)(ordinal + (i + 1) * 17U)
                             + (uint8_t)(ordinal + (i + width) * 17U)
                             + (uint8_t)(ordinal + (i + width + 1) * 17U);
                assert(*result++ == (sum + 2) / 4);
            }
        }
        source_start += (size_t)width * height;
    }
}

static void check_preferred(int retained_fullsize)
{
    int fd;
    pthread_t thread = start_peer(&fd);
    assert(!setup_connection(fd, getuid(), getuid()));
    if (retained_fullsize) {
        int original = t736_client_open(T736_CODEC_HEVC, 3840, 2160);
        assert(original > 0 && !t736_client_close(original));
    }
    int expect_omx = !retained_fullsize;
#ifdef TEST_LEGACY_BROKER
    expect_omx = 0;
#endif
    for (int run = 0; run < 2; ++run) {
        unsigned requests = serial_number;
        int lease = t736_client_open_preferred_panel(T736_CODEC_HEVC, 3840, 2160);
        assert(lease > 0 && active_omx_panel == expect_omx);
        assert(serial_number == requests + (expect_omx ? 1U : 2U));
        uint8_t packet = 3;
        struct t736_frame frame = {0};
        assert(!t736_client_push(lease, &packet, 1, 500, INT64_MIN));
        size_t capacity = 1920U * 1080 * 3 / 2;
        uint8_t *output = malloc(capacity);
        assert(output);
        assert(t736_client_pull_fit1080(lease, output, capacity - 1, &frame, 20) == -ENOSPC);
        assert(t736_client_pull_fit1080(lease, output, capacity, &frame, 20) == 1);
        assert(frame.width == 1920 && frame.height == 1080 && frame.bytes_written == capacity);
        assert(frame.pts_us == run + 1 && frame.color_range == 1 && frame.colorspace == 1);
        if (expect_omx)
            expect_frame(output, &frame);
        else
            check_scaled_stub(output, (unsigned)frame.pts_us);
        free(output);
        assert(!t736_client_close(lease));
    }
    /* Both real brokers report the fatal state before processing OPEN flags. */
    pthread_mutex_lock(&hardware_lock);
    poisoned = 1;
    pthread_mutex_unlock(&hardware_lock);
    unsigned requests = serial_number;
    assert(t736_client_open_preferred_panel(T736_CODEC_HEVC, 3840, 2160) == -EIO);
    assert(serial_number == requests + 1);
    end_peer(thread);
}

int main(void)
{
    assert(!run_baseline());
    assert(t736_client_open_preferred_panel(T736_CODEC_HEVC, 3840, 2160) == -EINVAL);
    panel_requested = 1;
    check_preferred(0);
    check_preferred(1);
    puts("PASS: full-size regression, negotiated panel OPEN/PULL twice, retained reuse, "
         "every visible output byte, PTS/color, small buffer, fatal error without retry");
}
