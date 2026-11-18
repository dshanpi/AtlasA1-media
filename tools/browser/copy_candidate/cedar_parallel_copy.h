/* SPDX-License-Identifier: MIT
 * AtlasA1 direct-slot candidate. The externally serialized decoder owns these
 * threads. Jobs finish before the caller unmaps the Gst frame or sends the slot.
 */
#include <sched.h>

#define CEDAR_COPY_WORKERS 4

struct cedar_copy_pool;
struct cedar_copy_worker {
    struct cedar_copy_pool *pool;
    unsigned index, cpu, weight;
    GThread *thread;
};

struct cedar_copy_pool {
    GMutex lock;
    GCond changed, finished;
    struct cedar_copy_worker workers[CEDAR_COPY_WORKERS];
    unsigned count, ready, completed, generation;
    gboolean tried, stopping, affinity_error;
    const uint8_t *source[3];
    uint8_t *destination[3];
    unsigned row_bytes[3], luma_rows[CEDAR_COPY_WORKERS + 1], chroma_rows[CEDAR_COPY_WORKERS + 1];
};

static gpointer cedar_copy_thread(gpointer argument)
{
    struct cedar_copy_worker *w = argument;
    struct cedar_copy_pool *p = w->pool;
    cpu_set_t mask;
    CPU_ZERO(&mask);
    CPU_SET(w->cpu, &mask);
    gboolean pinned = sched_setaffinity(0, sizeof(mask), &mask) == 0;
    unsigned last = 0;
    g_mutex_lock(&p->lock);
    p->affinity_error |= !pinned;
    p->ready++;
    g_cond_signal(&p->finished);
    for (;;) {
        while (!p->stopping && last == p->generation)
            g_cond_wait(&p->changed, &p->lock);
        if (p->stopping)
            break;
        last = p->generation;
        g_mutex_unlock(&p->lock);
        for (unsigned plane = 0; plane < 3; plane++) {
            const unsigned *rows = plane ? p->chroma_rows : p->luma_rows;
            size_t start = (size_t)rows[w->index] * p->row_bytes[plane];
            size_t size = (size_t)(rows[w->index + 1] - rows[w->index]) * p->row_bytes[plane];
            memcpy(p->destination[plane] + start, p->source[plane] + start, size);
        }
        g_mutex_lock(&p->lock);
        if (++p->completed == p->count)
            g_cond_signal(&p->finished);
    }
    g_mutex_unlock(&p->lock);
    return NULL;
}

static void cedar_copy_pool_close(struct cedar_copy_pool *p)
{
    if (!p->count)
        return;
    g_mutex_lock(&p->lock);
    p->stopping = TRUE;
    g_cond_broadcast(&p->changed);
    g_mutex_unlock(&p->lock);
    for (unsigned i = 0; i < p->count; i++)
        g_thread_join(p->workers[i].thread);
    p->count = 0;
    g_cond_clear(&p->finished);
    g_cond_clear(&p->changed);
    g_mutex_clear(&p->lock);
}

static void cedar_copy_pool_start(struct cedar_copy_pool *p)
{
    static const unsigned order[] = {6, 7, 4, 5};
    cpu_set_t allowed;
    p->tried = TRUE;
    if (sched_getaffinity(0, sizeof(allowed), &allowed) != 0)
        return;
    unsigned cpus[CEDAR_COPY_WORKERS], count = 0;
    for (unsigned i = 0; i < G_N_ELEMENTS(order); i++)
        if (CPU_ISSET(order[i], &allowed))
            cpus[count++] = order[i];
    if (count < 2)
        return;
    g_mutex_init(&p->lock);
    g_cond_init(&p->changed);
    g_cond_init(&p->finished);
    g_mutex_lock(&p->lock);
    for (unsigned i = 0; i < count; i++) {
        struct cedar_copy_worker *w = &p->workers[i];
        w->pool = p;
        w->index = i;
        w->cpu = cpus[i];
        w->weight = cpus[i] >= 6 ? 3 : 1;
        w->thread = g_thread_try_new("cedar-copy", cedar_copy_thread, w, NULL);
        if (!w->thread)
            break;
        p->count++;
    }
    while (p->ready < p->count)
        g_cond_wait(&p->finished, &p->lock);
    g_mutex_unlock(&p->lock);
    if (!p->count) {
        g_cond_clear(&p->finished);
        g_cond_clear(&p->changed);
        g_mutex_clear(&p->lock);
    } else if (p->affinity_error || p->count < 2) {
        cedar_copy_pool_close(p);
    }
    fprintf(stderr, "CEDAR_PARALLEL_COPY: workers=%u\n", p->count);
}

static gboolean cedar_copy_packed(struct cedar_copy_pool *p, unsigned width, unsigned height,
                                  const uint8_t *sy, const uint8_t *su, const uint8_t *sv,
                                  uint8_t *dy, uint8_t *du, uint8_t *dv)
{
    if (!p->tried)
        cedar_copy_pool_start(p);
    if (!p->count)
        return FALSE;
    unsigned total_weight = 0, apportioned = 0, chroma_height = (height + 1) / 2;
    g_mutex_lock(&p->lock);
    p->source[0] = sy; p->source[1] = su; p->source[2] = sv;
    p->destination[0] = dy; p->destination[1] = du; p->destination[2] = dv;
    p->row_bytes[0] = width;
    p->row_bytes[1] = p->row_bytes[2] = (width + 1) / 2;
    for (unsigned i = 0; i < p->count; i++)
        total_weight += p->workers[i].weight;
    for (unsigned i = 0; i < p->count; i++) {
        apportioned += p->workers[i].weight;
        p->chroma_rows[i+1] = chroma_height * apportioned / total_weight;
        p->luma_rows[i+1] = MIN(height, 2 * p->chroma_rows[i+1]);
    }
    p->completed = 0;
    p->generation++;
    g_cond_broadcast(&p->changed);
    while (p->completed < p->count)
        g_cond_wait(&p->finished, &p->lock);
    g_mutex_unlock(&p->lock);
    return TRUE;
}
