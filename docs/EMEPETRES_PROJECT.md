# emepetres — AGPTEK Rocker music player

Experimental Rockbox fork for the **AGPTEK Rocker Hi-Fi**, initially running manufacturer firmware **1.1**.

## Purpose

Make browsing a large local music library much faster and less frustrating, while retaining dependable FLAC playback and adding offline scrobbling for Last.fm.

## Navigation contract (first development milestone)

1. **Home**: a short, predictable emepetres root with Artists, Albums, Search, Last.fm, Shuffle, Now Playing, Settings, and a System submenu for advanced tools.
2. **Primary journey**: Artists → Artist → Albums → Album → Tracks.
3. **Back**: always returns one browsing level, preserving the highlighted item and scroll offset.
4. **Home shortcut**: reachable from anywhere with a consistent, dedicated button gesture. The *exact gesture is provisional*, pending key-map and playback-conflict tests.
5. **Now Playing ↔ Library**: music keeps playing while browsing; returning to the library restores the previous browsing position.
6. **Album playback**: allow playing a complete album without selecting tracks individually.
7. **Shuffle**: available for the whole collection and, secondarily, within an artist.
8. **Appearance**: clean, readable lists designed for the Rocker's 128 × 160 display. Prioritize navigation clarity over elaborate playback graphics.

## Primary milestone: offline Last.fm and Windows sync

Last.fm is an absolute priority, as explicitly clarified by the user. The development branch now records completed PCM output duration in isolated offline playback logs, exports a compatible snapshot from Home -> Last.fm, and provides a Windows application for read-only import, durable account-specific deduplication and explicit scrobble submission. The player requires no Wi-Fi. Real-account authorization was completed manually by the user and verified in the Windows interface on 2026-11-12; no real scrobbles were submitted. Hardware/boot/recovery validation remains separate. See `EMEPETRES_LASTFM.md` and `EMEPETRES_NAVIGATION.md` for the implementation and checks.

## Starting technical facts (verified in this repository)

- Hosted Rocker configuration: `firmware/export/config/agptekrocker.h` (128 × 160).
- Native Rocker configuration also exists: `firmware/export/config/agptekrockernative.h`.
- Hardware key map: `apps/keymaps/keymap-agptekrocker.c`.
- Existing standard mapping: LEFT = cancel/back, long LEFT = quickscreen, long SELECT = context menu; POWER has context-dependent functions.
- Library/database logic: `apps/tagtree.c`, `apps/root_menu.c` and list/tree components.
- Firmware update patching utilities: `tools/agptek_rocker/`. Their README describes a complex update image process; **do not assume an arbitrary build is directly flashable**.

## Safe development sequence

1. Audit target selection, present navigation behavior and button conflicts.
2. Implement the navigation change in a development branch, keeping normal playback controls.
3. Validate with relevant simulator/build tests; avoid claims of hardware compatibility without device testing.
4. Verify the correct boot path and recovery procedure before any update of firmware 1.1.
5. Only then prepare a test artifact and install instructions.

## Data safety

The existing 64 GB microSD contains about 60 GB of music. **Do not format or overwrite it.** Back up the library before installing firmware, and keep any update/test assets separate from the music until the installation procedure is confirmed.

## Development policy

All experimental changes live on the `emepetres/dev` branch. Keep `master` as the unchanged upstream baseline until the first design is verified. Rockbox is GPL-licensed; retain applicable notices and license obligations.
