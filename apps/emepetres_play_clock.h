/* SPDX-License-Identifier: GPL-2.0-or-later
 * A listening session observes consumed PCM audio; pauses, underruns, rebuffering
 * and seeking without output contribute no duration. No audio state is changed.
 */
#ifndef EMEPETRES_PLAY_CLOCK_H
#define EMEPETRES_PLAY_CLOCK_H
#include <stdbool.h>
#include <stdint.h>
struct emepetres_play_clock {
    uint64_t start_usec;
    uint32_t timestamp;
    bool valid;
};
static inline void emepetres_clock_start(struct emepetres_play_clock *clock,
                                        uint64_t consumed_usec, uint32_t timestamp)
{
    clock->start_usec = consumed_usec;
    clock->timestamp = timestamp;
    clock->valid = true;
}
static inline unsigned long emepetres_clock_elapsed_ms(struct emepetres_play_clock *clock,
                                                      uint64_t consumed_usec)
{
    if (!clock->valid)
        return 0;
    uint64_t ms = (consumed_usec - clock->start_usec) / 1000;
    return ms > UINT32_MAX ? UINT32_MAX : (unsigned long)ms;
}
#endif
