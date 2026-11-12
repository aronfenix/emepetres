# First navigation increment

Scope: implement the existing EMEPETRES_PROJECT.md contract incrementally on
emepetres/dev. The user requested direct implementation; no new design approval
or local development environment is needed for this reversible work.

1. Test the real Rocker keymap with Rockbox's action matching worker. Short Left
   must go back once on release; holding Left opens quickscreen without first
   leaving the list. Use the existing simultaneous volume-button gesture for
   Home in normal lists/menus and playback. Retain Power lock, play/pause,
   stop, seek, skip, volume, and long Up to return to the browser.
2. Preserve the database list's first visible row alongside its existing
   selection history. Save before actions, restore before selecting/drawing,
   invalidate descendant positions with selection history, and reset on reload.
   Restrict the UI integration to the Rocker keypad, shared by both targets.
3. Package a Rocker-only compact database menu: Artists -> Albums -> Tracks,
   Albums, Shuffle Songs, Search, and First Letter. Keep album disc/track order,
   existing tagtree playback/context menu behavior, and user config precedence.
   Put Database first in the Rocker's default root menu. Direct Artists/Albums
   entries in the system Home remain a later increment, rather than introducing
   multiple competing database histories in this change.
4. Run regression tests and build both Rocker simulators on GitHub Actions.
   Compile and package only simulators: no updater, bootloader, flashing script,
   real firmware image, or device storage access. Record exact results and gaps.

Review focus: release after repeat; context chaining and locked keymaps; list
history invalidation after choosing a different artist; empty/short lists;
return from playback/Home or the file browser; pre-existing custom tag menus;
simulator success does not establish hardware or firmware 1.1 compatibility.

Approach: reuse Rockbox database/history/audio. A replacement browser would
duplicate playlist and database logic; a theme alone cannot fix button timing
or preserve the viewport. Gesture choice is an implementation decision: the
volume chord replaces the optional hotkey, with possible small volume movement
if the two keys are pressed at different times. Keyboard, plugins and modal
dialogs keep their own mappings; universal Home there is not claimed.

Progress and verification are recorded in docs/EMEPETRES_NAVIGATION.md.

## Scope expansion requested by user

The user explicitly requested much bolder changes and fewer repeated builds.
Implement a real emepetres Home: Artists, Albums, Search, Shuffle, playback,
Settings, and an advanced System submenu. Open database routes directly, retain
an independent in-memory browsing position for Artists/Albums/Search, return
straight to Home from each route's top level, and retain standard audio behavior.
Search includes first-letter browsing. Existing custom database configs fall back
to their own menu when the reserved route IDs are absent. Run one grouped build
and scripted UI journey for the expanded implementation.
