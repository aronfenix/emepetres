#!/usr/bin/env python3
"""Compile real keymap/action-worker and tagtree history slices on a host C compiler.

No player, firmware updater, user music or SD card is involved. The small header
stubs isolate Rockbox's UI mappings from hardware; action matching itself is the
production worker, not a reimplementation. Full simulator builds check integration.
"""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]


def function(source, signature):
    start = source.index(signature)
    opening = source.index('{', start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


class Navigation(unittest.TestCase):
    def compile_run(self, source, headers=None):
        compiler = shutil.which(os.environ.get('CC', 'cc'))
        if not compiler:
            self.skipTest('host C compiler required; GitHub Actions runs this test')
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            for name, content in (headers or {}).items():
                (tmp / name).write_text(content)
            (tmp / 'test.c').write_text(source)
            subprocess.run([compiler, '-std=c99', '-Wall', '-Wextra', '-Werror',
                            '-I', str(tmp), str(tmp / 'test.c'), '-o', str(tmp / 'test')],
                           check=True)
            subprocess.run([str(tmp / 'test')], check=True)

    def test_back_home_and_playback(self):
        keymap = (ROOT / 'apps/keymaps/keymap-agptekrocker.c').read_text()
        worker = function((ROOT / 'apps/action.c').read_text(),
                          'static inline int action_code_worker(')
        tokens = sorted(set(re.findall(r'\b(?:ACTION|CONTEXT)_\w+', keymap + worker + ' ACTION_NONE'))
                        - {'CONTEXT_LOCKED', 'CONTEXT_STOPSEARCHING'})
        constants = 'enum { ' + ', '.join(tokens) + ' };\n'
        constants += '#define CONTEXT_LOCKED 0x4000000\n#define CONTEXT_STOPSEARCHING -1\n'
        buttons = (ROOT / 'firmware/target/hosted/agptek/button-target.h').read_text()
        buttons = '\n'.join(re.findall(r'^#define BUTTON_\w+\s+0x[0-9a-fA-F]+', buttons, re.M))
        headers = {
            'config.h': '#define HAVE_VOLUME_IN_LIST\n',
            'settings.h': '',
            'button.h': buttons + '\n#define BUTTON_NONE 0\n#define BUTTON_REL 0x02000000\n#define BUTTON_REPEAT 0x04000000\n',
            'action.h': constants + '''
struct button_mapping { int action_code, button_code, pre_button_code; };
#define LAST_ITEM_IN_LIST { CONTEXT_STOPSEARCHING, BUTTON_NONE, BUTTON_NONE }
#define LAST_ITEM_IN_LIST__NEXTLIST(x) { x, BUTTON_NONE, BUTTON_NONE }
''',
        }
        harness = '''
#include <assert.h>
#include <stdbool.h>
typedef struct { int button; } action_last_t;
typedef struct { int button; const struct button_mapping *items; bool is_prebutton; } action_cur_t;
#define has_flag(value, flag) (((value) & (flag)) == (flag))
'''
        resolver = '''
static int resolve(int context, int button, int previous) {
    action_last_t last = {previous};
    for (int chain = 0; chain < 8; ++chain) {
        action_cur_t cur = {button, get_context_mapping(context), false};
        int end = 0;
        int action = action_code_worker(&last, &cur, &end);
        if (action != ACTION_UNKNOWN) return action;
        context = cur.items[end].action_code;
        if (context == CONTEXT_STOPSEARCHING) return ACTION_UNKNOWN;
    }
    assert(0); return ACTION_UNKNOWN;
}
int main(void) {
    int contexts[] = {CONTEXT_STD, CONTEXT_TREE, CONTEXT_LIST, CONTEXT_SETTINGS};
    for (unsigned i = 0; i < sizeof(contexts)/sizeof(contexts[0]); ++i) {
        int c = contexts[i];
        assert(resolve(c, BUTTON_LEFT, BUTTON_NONE) == ACTION_UNKNOWN);
        assert(resolve(c, BUTTON_LEFT|BUTTON_REL, BUTTON_LEFT) == ACTION_STD_CANCEL);
        assert(resolve(c, BUTTON_LEFT|BUTTON_REPEAT, BUTTON_LEFT) == ACTION_STD_QUICKSCREEN);
        assert(resolve(c, BUTTON_LEFT|BUTTON_REL, BUTTON_LEFT|BUTTON_REPEAT) == ACTION_UNKNOWN);
        assert(resolve(c, BTN_VOL_COMBO, BUTTON_VOLUP) == ACTION_STD_MENU);
        assert(resolve(c, BTN_VOL_COMBO, BUTTON_VOLDOWN) == ACTION_STD_MENU);
        assert(resolve(c, BUTTON_VOLUP|BUTTON_REL, BTN_VOL_COMBO) == ACTION_UNKNOWN);
        assert(resolve(c, BUTTON_VOLDOWN|BUTTON_REL, BUTTON_VOLUP|BUTTON_REL) == ACTION_UNKNOWN);
    }
    assert(resolve(CONTEXT_MAINMENU, BTN_VOL_COMBO, BUTTON_VOLUP) == ACTION_STD_MENU);
    assert(resolve(CONTEXT_WPS, BTN_VOL_COMBO, BUTTON_VOLUP) == ACTION_WPS_MENU);
    assert(resolve(CONTEXT_WPS, BTN_VOL_COMBO|BUTTON_REPEAT, BTN_VOL_COMBO) == ACTION_UNKNOWN);
    assert(resolve(CONTEXT_WPS, BUTTON_VOLUP|BUTTON_REL, BTN_VOL_COMBO|BUTTON_REPEAT) == ACTION_UNKNOWN);
    assert(resolve(CONTEXT_WPS, BUTTON_VOLDOWN|BUTTON_REL, BUTTON_VOLUP|BUTTON_REL) == ACTION_UNKNOWN);
    assert(resolve(CONTEXT_WPS, BUTTON_POWER, BUTTON_NONE) == ACTION_STD_KEYLOCK);
    assert(resolve(CONTEXT_WPS, BUTTON_SELECT|BUTTON_REL, BUTTON_SELECT) == ACTION_WPS_PLAY);
    assert(resolve(CONTEXT_WPS, BUTTON_SELECT|BUTTON_REPEAT, BUTTON_SELECT) == ACTION_WPS_STOP);
    assert(resolve(CONTEXT_WPS, BUTTON_UP|BUTTON_REPEAT, BUTTON_UP) == ACTION_WPS_BROWSE);
    assert(resolve(CONTEXT_WPS, BUTTON_LEFT|BUTTON_REL, BUTTON_LEFT) == ACTION_WPS_SKIPPREV);
    assert(resolve(CONTEXT_WPS, BUTTON_RIGHT|BUTTON_REL, BUTTON_RIGHT) == ACTION_WPS_SKIPNEXT);
    assert(resolve(CONTEXT_WPS, BUTTON_LEFT|BUTTON_REPEAT, BUTTON_LEFT) == ACTION_WPS_SEEKBACK);
    assert(resolve(CONTEXT_WPS, BUTTON_RIGHT|BUTTON_REPEAT, BUTTON_RIGHT) == ACTION_WPS_SEEKFWD);
    assert(resolve(CONTEXT_WPS, BUTTON_LEFT|BUTTON_REL, BUTTON_LEFT|BUTTON_REPEAT) == ACTION_WPS_STOPSEEK);
    assert(resolve(CONTEXT_WPS, BUTTON_RIGHT|BUTTON_REL, BUTTON_RIGHT|BUTTON_REPEAT) == ACTION_WPS_STOPSEEK);
    assert(resolve(CONTEXT_WPS, BUTTON_VOLUP, BUTTON_NONE) == ACTION_WPS_VOLUP);
    assert(resolve(CONTEXT_WPS, BUTTON_VOLDOWN|BUTTON_REPEAT, BUTTON_VOLDOWN) == ACTION_WPS_VOLDOWN);
    assert(resolve(CONTEXT_WPS|CONTEXT_LOCKED, BUTTON_POWER, BUTTON_NONE) == ACTION_STD_KEYLOCK);
    return 0;
}
'''
        self.compile_run(keymap + harness + worker + resolver, headers)

    def test_home_in_root_and_settings_menus(self):
        source = (ROOT / 'apps/menu.c').read_text()
        handler = function(source, 'if (action == ACTION_STD_MENU)')
        self.compile_run('''
#include <assert.h>
#include <stdbool.h>
#define CONFIG_KEYPAD 42
#define AGPTEK_ROCKER_PAD 42
enum { ACTION_STD_MENU, GO_TO_ROOT, GO_TO_PREVIOUS };
static int root_menu_, settings_menu;
static int home(int *menu) {
    int action = ACTION_STD_MENU, ret = -1;
    bool done = false;
''' + handler + '''
    assert(done); return ret;
}
int main(void) {
    assert(home(&root_menu_) == GO_TO_ROOT);
    assert(home(&settings_menu) == GO_TO_ROOT);
    return 0;
}
''')

    def test_database_scroll_history(self):
        source = (ROOT / 'apps/tagtree.c').read_text()
        # Missing functions is an explicit failure before this feature exists.
        self.assertTrue('void tagtree_save_scroll(' in source,
                        'database viewport history is not implemented')
        save = function(source, 'void tagtree_save_scroll(')
        restore = function(source, 'int tagtree_get_scroll(')
        leave = function(source, 'void tagtree_exit(')
        enter = function(source, 'int tagtree_enter(')
        history = function(enter, 'if (is_visible) /* update selection history')
        self.compile_run('''
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#define MAX_DIR_LEVELS 8
#define MAX(a,b) ((a) > (b) ? (a) : (b))
#define logf(...) ((void)0)
#define DEBUGF(...) ((void)0)
struct tree_context { int dirlevel, selected_item, currtable, currextra; bool dirfull; };
static int selected_item_history[MAX_DIR_LEVELS];
static int first_visible_item_history[MAX_DIR_LEVELS];
static int table_history[MAX_DIR_LEVELS], extra_history[MAX_DIR_LEVELS];
static int max_history_level;
''' + save + restore + leave + '''
static void enter_history(struct tree_context *c, bool is_visible, bool is_random_item) {
''' + history + '''
}
int main(void) {
    struct tree_context c = {0, 36, 1, 0, false};
    tagtree_save_scroll(&c, 32);
    enter_history(&c, true, false);
    c.dirlevel = 1; c.selected_item = 15;
    tagtree_save_scroll(&c, 11);
    enter_history(&c, true, false);
    c.dirlevel = 2; c.selected_item = 9;
    tagtree_save_scroll(&c, 5);
    tagtree_exit(&c, true);
    assert(c.dirlevel == 1 && c.selected_item == 15 && tagtree_get_scroll(&c) == 11);
    tagtree_exit(&c, true);
    assert(c.dirlevel == 0 && c.selected_item == 36 && tagtree_get_scroll(&c) == 32);
    enter_history(&c, true, false);
    c.dirlevel = 1; assert(tagtree_get_scroll(&c) == 11);
    c.dirlevel = 0; c.selected_item = 37; enter_history(&c, true, false);
    c.dirlevel = 1; assert(tagtree_get_scroll(&c) == 0);
    c.dirlevel = -1; tagtree_save_scroll(&c, 42); assert(tagtree_get_scroll(&c) == 0);
    c.dirlevel = MAX_DIR_LEVELS; tagtree_save_scroll(&c, 42); assert(tagtree_get_scroll(&c) == 0);
    return 0;
}
''')


if __name__ == '__main__':
    unittest.main(verbosity=2)
