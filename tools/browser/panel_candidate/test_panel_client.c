/* SPDX-License-Identifier: MIT */
/* Exercise the normal client with a socketpair peer and an ordinary mapped
 * I420 slot. No Cedar driver, service or board is required. */
#include "cedar_client.c"
#include <assert.h>

static void return_picture(int peer, const struct t736_picture *picture)
{
    struct t736_message reply = { T736_MAGIC, T736_PROTOCOL_VERSION, T736_PULL,
        sizeof(*picture), serial_number + 1, active_session, 1, 0 };
    assert(send(peer, &reply, sizeof(reply), 0) == (ssize_t)sizeof(reply));
    assert(send(peer, picture, sizeof(*picture), 0) == (ssize_t)sizeof(*picture));
}

static void check_request(int peer, unsigned capacity)
{
    struct t736_message request;
    struct t736_pull pull;
    assert(recv(peer, &request, sizeof(request), MSG_WAITALL) == (ssize_t)sizeof(request));
    assert(request.operation == T736_PULL && request.session == active_session);
    assert(request.length == sizeof(pull));
    assert(recv(peer, &pull, sizeof(pull), MSG_WAITALL) == (ssize_t)sizeof(pull));
    assert(pull.capacity == capacity && pull.timeout_ms == 20);
}

int main(void)
{
    struct t736_picture picture = { 3840, 2160, T736_MAX_FRAME, 2, 9, 0, 17268107 };
    struct t736_frame frame = { 0 };
    struct timeval timeout = { .tv_sec = 2 };
    int pair[2];
    uint8_t *output = malloc(T736_MAX_FRAME);
    uint8_t *source = mmap(NULL, T736_MAX_FRAME, PROT_READ | PROT_WRITE,
                           MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    assert(output && source != MAP_FAILED);
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
    for (int i = 0; i < 2; ++i)
        assert(setsockopt(pair[i], SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout)) == 0);
    connection = pair[0];
    shared_pixels = source;
    connected_pid = getpid();
    active_session = 3;
    active_width = 3840;
    active_height = 2160;
    for (size_t i = 0; i < T736_MAX_FRAME; ++i) source[i] = (uint8_t)(i * 43 + (i >> 14));

    assert(!t736_client_panel_requested());
    assert(t736_client_pull_fit1080(3, output, T736_PANEL_BYTES, &frame, 20) == -EINVAL);
    panel_requested = 1;
    assert(t736_client_panel_requested());
    assert(t736_client_pull_fit1080(3, output, T736_PANEL_BYTES - 1, &frame, 20) == -ENOSPC);
    assert(t736_client_pull_fit1080(4, output, T736_PANEL_BYTES, &frame, 20) == -EINVAL);
    assert(!serial_number);
    return_picture(pair[1], &picture);
    assert(t736_client_pull_fit1080(3, output, T736_PANEL_BYTES, &frame, 20) == 1);
    check_request(pair[1], T736_MAX_FRAME);
    assert(frame.width == 1920 && frame.height == 1080 && frame.bytes_written == T736_PANEL_BYTES);
    assert(frame.pts_us == picture.pts_us && frame.color_range == 2 && frame.colorspace == 9);
    return_picture(pair[1], &picture);
    assert(t736_client_pull(3, output, T736_MAX_FRAME, &frame, 20) == 1);
    check_request(pair[1], T736_MAX_FRAME);
    assert(frame.width == 3840 && frame.height == 2160 && frame.bytes_written == T736_MAX_FRAME);
    assert(!memcmp(output, source, T736_MAX_FRAME));
    active_width = picture.width = 1920;
    active_height = picture.height = 1080;
    picture.bytes = T736_PANEL_BYTES;
    assert(t736_client_pull_fit1080(3, output, T736_PANEL_BYTES, &frame, 20) == -EINVAL);
    assert(serial_number == 2);
    return_picture(pair[1], &picture);
    assert(t736_client_pull(3, output, T736_PANEL_BYTES, &frame, 20) == 1);
    check_request(pair[1], T736_PANEL_BYTES);
    assert(frame.width == 1920 && frame.height == 1080 && frame.bytes_written == T736_PANEL_BYTES);
    assert(!memcmp(output, source, T736_PANEL_BYTES));
    disconnect_client();
    close(pair[1]);
    free(output);
    puts("Client protocol passed: opt-in, capacity, session, PTS, color, full 4K and 1080p pulls");
    return 0;
}
