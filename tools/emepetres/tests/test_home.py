#!/usr/bin/env python3
"""Exercise the real Home route state and root dispatcher on a host compiler.

Only database loading/entering is stubbed: these tests isolate route ownership
from the tagcache files and player hardware. No firmware build is started.
"""
from pathlib import Path
import unittest

import test_navigation as navigation

ROOT = Path(__file__).resolve().parents[3]


def declaration(source, signature):
    return navigation.function(source, signature) + ';\n'


class Home(unittest.TestCase):
    def compile_run(self, source):
        navigation.Navigation.compile_run(self, source)

    def shortcut_harness(self, body):
        source = (ROOT / 'apps/tagtree.c').read_text()
        header = (ROOT / 'apps/tagtree.h').read_text()
        definitions = declaration(header, 'enum tagtree_shortcut {')
        definitions += declaration(source, 'struct shortcut_state {')
        real = '\n'.join(navigation.function(source, signature) for signature in (
            'static void shortcut_save(', 'static void shortcut_restore(',
            'bool tagtree_open_shortcut(', 'bool tagtree_at_shortcut_root('))
        return r'''
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#define MAX_TAGS 5
#define MAX_DIR_LEVELS 8
enum { TABLE_ROOT = 1, TABLE_NAVIBROWSE = 2 };
struct tree_context {
    int dirlevel, selected_item, currtable, currextra;
    bool dirfull;
};
struct search_instruction { int result_seek[MAX_TAGS]; };
struct menu_entry { struct search_instruction si; };
struct menu_root { const char *id; int itemcount; struct menu_entry *items[2]; };
''' + definitions + r'''
static struct shortcut_state shortcut_states[TAGTREE_SHORTCUT_COUNT];
static enum tagtree_shortcut current_shortcut;
static int shortcut_base, max_history_level, loaded_entries_crc;
static int selected_item_history[MAX_DIR_LEVELS];
static int first_visible_item_history[MAX_DIR_LEVELS];
static int table_history[MAX_DIR_LEVELS], extra_history[MAX_DIR_LEVELS];
static char current_title[MAX_TAGS][128];
static struct search_instruction *csi;
static struct menu_root *menus[5];
static struct menu_root roots[2][5];
static struct menu_entry entries[2][5][2];
static int menu_count = 5, rootmenu = 0;

/* The Home opener only loads a menu and, for Artists/Albums, enters its
 * first query. Disk searching and list contents belong to tagtree tests. */
static int tagtree_load(struct tree_context *c) {
    assert(c->currtable == TABLE_ROOT);
    assert(c->currextra >= 0 && c->currextra < menu_count);
    return menus[c->currextra]->itemcount;
}
static int tagtree_enter(struct tree_context *c, bool visible) {
    assert(visible && c->selected_item == 0 && c->dirlevel == 1);
    csi = &menus[c->currextra]->items[0]->si;
    c->dirlevel++;
    c->currtable = TABLE_NAVIBROWSE;
    c->currextra = 0;
    return 0;
}
''' + real + r'''
static struct tree_context setup(void) {
    const char *ids[] = {"main", "emepetres_artists", "emepetres_albums",
                        "emepetres_search", "emepetres_shuffle"};
    for (int i = 0; i < 5; ++i) {
        roots[0][i].id = ids[i];
        roots[0][i].itemcount = 2;
        for (int j = 0; j < 2; ++j)
            roots[0][i].items[j] = &entries[0][i][j];
        menus[i] = &roots[0][i];
    }
    csi = &entries[0][0][0].si;
    struct tree_context c = {0, 7, TABLE_ROOT, 0, false};
    return c;
}
int main(void) {
    struct tree_context c = setup();
''' + body + '\nreturn 0;\n}\n'

    def test_routes_keep_positions_scroll_titles_and_search_filters(self):
        # Dropping any copied state or sharing a single saved route loses these
        # distinct positions, titles and query filter offsets on round trips.
        self.compile_run(self.shortcut_harness(r'''
    assert(tagtree_open_shortcut(&c, TAGTREE_ARTISTS));
    c.dirlevel = 4; c.selected_item = 36; c.currextra = 2;
    max_history_level = 6;
    selected_item_history[2] = 15; selected_item_history[7] = 9;
    first_visible_item_history[4] = 32;
    table_history[3] = TABLE_NAVIBROWSE; extra_history[3] = 1;
    strcpy(current_title[0], "Artists"); strcpy(current_title[2], "Artist album");
    csi->result_seek[0] = 1234; csi->result_seek[4] = 5678;

    assert(tagtree_open_shortcut(&c, TAGTREE_ALBUMS));
    assert(c.selected_item == 0 && first_visible_item_history[4] == 0);
    c.dirlevel = 3; c.selected_item = 18; c.currextra = 1;
    selected_item_history[2] = 18; first_visible_item_history[3] = 14;
    strcpy(current_title[1], "Album route"); csi->result_seek[0] = 9876;

    assert(tagtree_open_shortcut(&c, TAGTREE_SEARCH));
    c.dirlevel = 4; c.selected_item = 11; c.currtable = TABLE_NAVIBROWSE;
    c.currextra = 1; csi = &menus[3]->items[1]->si;
    selected_item_history[3] = 8; first_visible_item_history[4] = 6;
    strcpy(current_title[1], "Search result"); csi->result_seek[1] = 4321;

    assert(tagtree_open_shortcut(&c, TAGTREE_ARTISTS));
    assert(c.dirlevel == 4 && c.selected_item == 36 && c.currextra == 2);
    assert(max_history_level == 6 && selected_item_history[2] == 15);
    assert(selected_item_history[7] == 9 && first_visible_item_history[4] == 32);
    assert(table_history[3] == TABLE_NAVIBROWSE && extra_history[3] == 1);
    assert(!strcmp(current_title[0], "Artists"));
    assert(!strcmp(current_title[2], "Artist album"));
    assert(csi == &menus[1]->items[0]->si);
    assert(csi->result_seek[0] == 1234 && csi->result_seek[4] == 5678);
    assert(tagtree_open_shortcut(&c, TAGTREE_ALBUMS));
    assert(c.dirlevel == 3 && c.selected_item == 18 && c.currextra == 1);
    assert(selected_item_history[2] == 18 && first_visible_item_history[3] == 14);
    assert(!strcmp(current_title[1], "Album route") && csi->result_seek[0] == 9876);
    assert(tagtree_open_shortcut(&c, TAGTREE_SEARCH));
    assert(c.selected_item == 11 && selected_item_history[3] == 8);
    assert(first_visible_item_history[4] == 6);
    assert(!strcmp(current_title[1], "Search result"));
    assert(csi == &menus[3]->items[1]->si && csi->result_seek[1] == 4321);
    c.dirfull = true; loaded_entries_crc = 99;
    assert(tagtree_open_shortcut(&c, TAGTREE_DATABASE));
    assert(c.dirlevel == 0 && c.selected_item == 7 && c.currtable == TABLE_ROOT);
    assert(!c.dirfull && loaded_entries_crc == 0);
    assert(!tagtree_at_shortcut_root(&c));
'''))

    def test_restore_rederives_instruction_after_buflib_relocation(self):
        # Saving a raw csi pointer, or restoring the wrong menu/item index,
        # would use the overwritten old allocation below.
        self.compile_run(self.shortcut_harness(r'''
    assert(tagtree_open_shortcut(&c, TAGTREE_ARTISTS));
    csi = &menus[1]->items[1]->si; csi->result_seek[2] = 3210;
    assert(tagtree_open_shortcut(&c, TAGTREE_ALBUMS));
    for (int i = 0; i < 5; ++i) {
        roots[1][i] = roots[0][i];
        for (int j = 0; j < 2; ++j) {
            entries[1][i][j] = entries[0][i][j];
            roots[1][i].items[j] = &entries[1][i][j];
        }
        menus[i] = &roots[1][i];
    }
    csi = &entries[1][2][0].si; /* normal buflib callback updates active csi */
    memset(entries[0], 0, sizeof(entries[0]));
    entries[1][1][1].si.result_seek[2] = 9999;
    assert(tagtree_open_shortcut(&c, TAGTREE_ARTISTS));
    assert(csi == &entries[1][1][1].si && csi->result_seek[2] == 3210);
'''))

    def test_invalid_route_does_not_change_current_browser(self):
        self.compile_run(self.shortcut_harness(r'''
    assert(tagtree_open_shortcut(&c, TAGTREE_ARTISTS));
    c.selected_item = 25; first_visible_item_history[2] = 20;
    assert(!tagtree_open_shortcut(&c, (enum tagtree_shortcut)-1));
    assert(!tagtree_open_shortcut(&c, TAGTREE_SHORTCUT_COUNT));
    assert(current_shortcut == TAGTREE_ARTISTS && c.selected_item == 25);
    assert(first_visible_item_history[2] == 20);
    assert(tagtree_open_shortcut(&c, TAGTREE_ARTISTS));
    assert(c.selected_item == 25); /* selecting the active route must not reset it */
'''))

    def test_missing_reserved_menu_preserves_advanced_database(self):
        self.compile_run(self.shortcut_harness(r'''
    c.dirlevel = 3; c.selected_item = 17; c.currtable = TABLE_NAVIBROWSE;
    c.currextra = 1; first_visible_item_history[3] = 12;
    strcpy(current_title[1], "Custom database"); csi->result_seek[0] = 555;
    menus[1]->id = "my_own_artists";
    assert(!tagtree_open_shortcut(&c, TAGTREE_ARTISTS));
    assert(current_shortcut == TAGTREE_DATABASE);
    assert(c.dirlevel == 3 && c.selected_item == 17 && c.currextra == 1);
    assert(first_visible_item_history[3] == 12);
    assert(!strcmp(current_title[1], "Custom database") && csi->result_seek[0] == 555);
    assert(tagtree_open_shortcut(&c, TAGTREE_ALBUMS));
    menus[3]->id = "my_own_search";
    assert(!tagtree_open_shortcut(&c, TAGTREE_SEARCH));
    assert(current_shortcut == TAGTREE_DATABASE && c.selected_item == 17);
    assert(first_visible_item_history[3] == 12 && csi->result_seek[0] == 555);
'''))

    def test_empty_reserved_menu_falls_back_to_advanced_database(self):
        self.compile_run(self.shortcut_harness(r'''
    c.selected_item = 9; first_visible_item_history[0] = 5;
    menus[1]->itemcount = 0;
    assert(!tagtree_open_shortcut(&c, TAGTREE_ARTISTS));
    assert(current_shortcut == TAGTREE_DATABASE && c.selected_item == 9);
    assert(first_visible_item_history[0] == 5 && !tagtree_at_shortcut_root(&c));
'''))

    def test_back_boundary_and_explicit_shuffle_reset(self):
        self.compile_run(self.shortcut_harness(r'''
    assert(tagtree_open_shortcut(&c, TAGTREE_ARTISTS));
    assert(tagtree_at_shortcut_root(&c));
    c.dirlevel++; assert(!tagtree_at_shortcut_root(&c));
    c.dirlevel--; assert(tagtree_at_shortcut_root(&c));
    assert(tagtree_open_shortcut(&c, TAGTREE_SEARCH));
    assert(tagtree_at_shortcut_root(&c));
    c.dirlevel++; assert(!tagtree_at_shortcut_root(&c));
    assert(tagtree_open_shortcut(&c, TAGTREE_SHUFFLE));
    assert(c.dirlevel == 1 && c.selected_item == 0 && c.currextra == 4);
    c.selected_item = 1; first_visible_item_history[1] = 1;
    assert(tagtree_open_shortcut(&c, TAGTREE_SHUFFLE));
    assert(c.dirlevel == 1 && c.selected_item == 0 && first_visible_item_history[1] == 0);
    assert(tagtree_at_shortcut_root(&c));
'''))

    def test_shuffle_playback_browser_does_not_repeat_shuffle(self):
        source = (ROOT / 'apps/root_menu.c').read_text()
        root = navigation.function(source, 'void root_menu(void)')
        start = root.index('            case GO_TO_SHUFFLE:')
        end = root.index('#endif', start)
        dispatch = root[start:end]
        start = root.index('            case GO_TO_PREVIOUS_BROWSER:')
        end = root.index('            case GO_TO_PREVIOUS_MUSIC:', start)
        previous = root[start:end]
        header = (ROOT / 'apps/root_menu.h').read_text()
        self.compile_run(r'''
#include <assert.h>
#define HAVE_TAGCACHE
#define HAVE_EMEPETRES_HOME
#define CONFIG_TUNER 0
''' + declaration(header, 'enum {') + r'''
static struct { int last_browser; } global_status;
static int previous_browser = GO_TO_DBBROWSER;
static int dispatch(int next_screen) {
    switch (next_screen) {
''' + dispatch + previous + r'''
        default: break;
    }
load_next_screen:
    return next_screen;
}
int main(void) {
    assert(dispatch(GO_TO_SHUFFLE) == GO_TO_SHUFFLE); /* explicit Home command */
    assert(global_status.last_browser == GO_TO_ARTISTS);
    assert(dispatch(GO_TO_PREVIOUS_BROWSER) == GO_TO_ARTISTS); /* WPS Browse */
    return 0;
}
''')


if __name__ == '__main__':
    unittest.main(verbosity=2)
