"""Clock and export policy tests; no user audio or Last.fm traffic."""
import unittest
import test_navigation as navigation

ROOT = navigation.ROOT


class ScrobbleFirmware(unittest.TestCase):
    def compile_run(self, source):
        navigation.Navigation.compile_run(self, source)

    def test_clock_counts_consumed_audio_not_pause_seek_or_buffering(self):
        path = ROOT / 'apps/emepetres_play_clock.h'
        self.assertTrue(path.exists(), 'offline listening clock is not implemented')
        self.compile_run(path.read_text() + r'''
#include <assert.h>
int main(void) {
    struct emepetres_play_clock clock = {0};
    assert(emepetres_clock_elapsed_ms(&clock, 1000000) == 0);
    emepetres_clock_start(&clock, 1000000, 1700000000);
    assert(emepetres_clock_elapsed_ms(&clock, 11000000) == 10000);
    /* No consumed samples during pause, seeking, underrun or rebuffering. */
    assert(emepetres_clock_elapsed_ms(&clock, 11000000) == 10000);
    assert(emepetres_clock_elapsed_ms(&clock, 26000000) == 25000);
    assert(clock.timestamp == 1700000000);
    emepetres_clock_start(&clock, UINT64_MAX - 1500, 1700001000);
    assert(emepetres_clock_elapsed_ms(&clock, 2000) == 3);
    emepetres_clock_start(&clock, 0, 1700002000);
    assert(emepetres_clock_elapsed_ms(&clock, UINT64_MAX) == UINT32_MAX);
    return 0;
}
''')

    def test_lastfm_eligibility_half_or_four_minutes_over_thirty_seconds(self):
        source = (ROOT / 'apps/plugins/lastfm_scrobbler.c').read_text()
        self.assertTrue('static bool sbl_is_listened(' in source,
                        'Last.fm listening policy is not implemented')
        self.compile_run(r'''
#include <stdbool.h>
#include <assert.h>
#define MIN(a,b) ((a) < (b) ? (a) : (b))
static bool emepetres_export;
static struct { int savepct; } gConfig = {50};
struct scrobbler_entry { unsigned long elapsed, length; };
''' + navigation.function(source, 'static unsigned long sbl_get_threshold(')
            + navigation.function(source, 'static bool sbl_is_listened(') + r'''
int main(void) {
    emepetres_export = true;
    struct scrobbler_entry entry = {16000, 31000};
    assert(sbl_is_listened(&entry));
    entry.elapsed = 14999; assert(!sbl_is_listened(&entry));
    entry.elapsed = 30000; entry.length = 30000; assert(!sbl_is_listened(&entry));
    entry.length = 3600000; entry.elapsed = 240000; assert(sbl_is_listened(&entry));
    entry.elapsed = 239999; assert(!sbl_is_listened(&entry));
    emepetres_export = false;
    assert(sbl_get_threshold(3600000) == 1800000);
    return 0;
}
''')


if __name__ == '__main__':
    unittest.main(verbosity=2)
