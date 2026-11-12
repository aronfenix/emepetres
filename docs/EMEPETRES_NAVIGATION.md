# emepetres Home and offline Last.fm — 2026-11-12

Work lives on `emepetres/dev`; `master` remains the untouched upstream baseline.
No device, bootloader, original firmware or real microSD has been accessed.

## Implemented

The Rocker now has its own Home, titled **emepetres**: Artists, Albums, Search,
Last.fm, Shuffle Songs, playback/resume, Settings and System. System keeps the
original Files, advanced Database, playlists, bookmarks, plugins and utilities.
Existing customized Home ordering is respected; reset Main Menu settings to see
these defaults if an old custom order is present.

Artists and Albums open directly into their lists. Search opens artist/album/title
queries and first-letter browsing. Each route retains its own selection, viewport,
query offsets and titles when switching sections. Stored query references use
menu/item indices, so moving the database buffer cannot leave stale pointers.
Custom database configurations without the reserved entry points fall back to
their existing database view, preserving its position. Database reload clears
in-memory route snapshots.

Short Left returns one level on release; holding Left opens quickscreen without
first going back. At the top of a Home route, Left returns straight to Home.
Pressing both volume buttons is the shared Home gesture in normal menus,
browsing and playback. It replaces the optional configurable hotkey. Power lock,
play/pause, stop, track skip, seeking and ordinary volume controls remain mapped.
Specialized keyboard/plugin/modal screens keep their own controls. Physical
chord ergonomics and timing remain unverified on hardware.

Shuffle is an explicit playback command. Returning from playback opens Artists,
never repeats the shuffle command, and a previous Shuffle screen cannot auto-run
on startup.

## Last.fm is a primary feature

Playback logging is enabled by default for new emepetres configurations. A small
listening counter records start time and completed PCM output duration without
crediting pauses, seeks or buffering silence. It observes mixer consumption and
does not move track position or alter audio processing. New raw logs and exports have independent
emepetres filenames, leaving legacy Rockbox logs untouched. Home -> Last.fm ->
Preparar sincronizacion exports metadata while retaining the source logs.

The Windows application imports read-only copies, previews queued listens,
protects authorization with current-user Windows DPAPI and submits explicit
batches to Last.fm. Reimports are deduplicated per account; unknown timezones and
uncertain network outcomes require review. There is no claim of exactly-once
network delivery or of a real authorized account test yet.

See [EMEPETRES_LASTFM.md](EMEPETRES_LASTFM.md) for activation, protocol,
credentials, limitations and the Windows utility.

## Verification

The host C regression suite covers key mappings, menu Home handling, viewport
restoration, route snapshots and relocation, custom/empty-config fallback,
explicit shuffle dispatch, listening-clock pause/seek/wrap behavior and Last.fm
eligibility. The Windows suite covers parser/import, queue persistence, account
isolation, signing, individual responses, rate limits, unknown timezones,
timeouts/interrupted sends, DPAPI and actual Tkinter worker interactions.

GitHub Actions builds both full Rocker Linux simulators and a standalone Windows
application. The simulator journey uses only generated FLACs in a temporary root:
Home -> Artists -> Albums -> Tracks -> Back -> playback -> Stop -> Last.fm export.
Screenshots and the synthetic exported log are retained for inspection. No real
Last.fm submissions or player data are part of these tests.

Grouped verification of the expanded scope is in progress. Earlier successful
runs (43250826563 and 43252271573) cover the smaller initial navigation increment;
they must not be presented as proof of this expanded implementation.

## Boot and recovery audit: unresolved installation gate

The repository contains two distinct targets:

| Target | Model number | Application output | Boot path |
| --- | --- | --- | --- |
| Hosted Rocker | 105 | `rockbox.rocker` | Manufacturer Linux/HiBy environment |
| Native Rocker | 133 | `rockbox.rockern` | Native X1000 port and bootloader |

These outputs must not be treated as interchangeable. The simulator builds do
not exercise either real boot path, hardware drivers, audio DAC, USB or recovery.
The native target's status in `tools/builds.pm` is also different from hosted.

`tools/agptek_rocker/README`, `bootloader_install.sh`, `Dockerfile`,
`bootloader/hibyos_linux.c` and `bootloader/x1000/` were inspected. The old hosted
installation script rebuilds an ISO9660 `.upt` image and its UBIFS rootfs; its
Dockerfile references Debian 9 and its clone command contains an obsolete/invalid
`ttp://` URL. It was **not executed**. The native bootloader has separate original
firmware/recovery paths, which have not been validated on this user's unit.

No original firmware 1.1 image, exact hardware revision, installed bootloader,
recoverability or real cross-compiled build has been verified. Before any device
test: identify the exact boot path and revision, verify an original recovery
image/procedure and backups, build the appropriate target, and validate using
separate test storage. The existing 64 GB card and approximately 60 GB of music
must remain untouched.

## Remaining work

- Activate the Windows client with the user's personal Last.fm application and
  browser authorization, then perform an explicitly authorized real-account test.
- Broaden UI data fixtures (large lists, multi-disc sets and duplicate album names)
  and exercise Search/First Letter and advanced Files round trips.
- Verify the exact player's hardware revision, appropriate cross-compiled build,
  bootloader and recovery procedure before preparing any on-device installation.
