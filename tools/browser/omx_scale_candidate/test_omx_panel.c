/* SPDX-License-Identifier: MIT */
#include "baseline.inc"

cedar_decoder *cedar_open_panel(enum cedar_codec codec, unsigned width, unsigned height,
                               char *error, size_t size)
{
    assert(width == 3840 && height == 2160);
    return cedar_open(codec, width / 2, height / 2, error, size);
}

int main(void)
{
    assert(!run_baseline());
    int fd;
    pthread_t thread = start_peer(&fd);
    assert(!setup_connection(fd, getuid(), getuid()));
    assert(!t736_client_panel_requested());
    assert(t736_client_open_panel(T736_CODEC_HEVC, 3840, 2160) == -EINVAL);
    panel_requested = 1;
    assert(t736_client_open_panel(T736_CODEC_HEVC, 3840, 2158) == -EINVAL);
    struct t736_open unsupported = { T736_CODEC_HEVC, 3840, 2160, 2 };
    assert(simple(T736_OPEN, 0, &unsupported, sizeof(unsupported), NULL, 0) == -EINVAL);
    int session = t736_client_open_panel(T736_CODEC_HEVC, 3840, 2160);
    assert(session > 0);
    uint8_t packet = 2;
    struct t736_frame frame = {0};
    size_t capacity = 1920U * 1080 * 3 / 2;
    uint8_t *pixels = malloc(capacity);
    assert(pixels);
    assert(!t736_client_push(session, &packet, 1, 431, INT64_MIN));
    assert(t736_client_pull(session, pixels, capacity - 1, &frame, 0) == -ENOSPC);
    assert(t736_client_pull(session, pixels, capacity, &frame, 0) == 1);
    assert(frame.width == 1920 && frame.height == 1080 && frame.bytes_written == capacity);
    /* The stub synthesizes output PTS from its decoded frame ordinal. */
    assert(frame.pts_us == 1);
    expect_frame(pixels, &frame);
    free(pixels);
    assert(!t736_client_close(session));
    assert(t736_client_open(T736_CODEC_HEVC, 3840, 2160) == -ENOSPC);
    int again = t736_client_open_panel(T736_CODEC_HEVC, 3840, 2160);
    assert(again > session);
    assert(!t736_client_push(again, &packet, 1, 522, INT64_MIN));
    pixels = malloc(capacity);
    assert(pixels && t736_client_pull(again, pixels, capacity, &frame, 0) == 1);
    assert(frame.pts_us == 2);
    expect_frame(pixels, &frame);
    free(pixels);
    assert(!t736_client_close(again));
    end_peer(thread);
    puts("Passed full-size transport regression, 4K OPEN / 1080p PULL over SHM, "
         "opt-in, PTS/color/pixels, short buffer, retained-mode separation and scaled reopen");
}
