# Last.fm device handoff and vendor ABI verification

The user explicitly requests continued autonomous implementation, prioritizing
Last.fm and reduced setup. Existing approved platform: Rockbox on Rocker plus
a stdlib Windows Tk application. Work remains on emepetres/dev. No flashing,
formatting, music replacement or automatic real-account submissions.

## Task 1: Import directly from connected storage

Files: `tools/emepetres/lastfm/device.py`, `gui.py`,
`tests/test_device.py`, `tests/test_gui.py`, `docs/EMEPETRES_LASTFM.md`.

Design: one explicit Spanish button "Importar del Rocker" discovers the
known export filename at removable-volume roots. Discovery is local and
read-only; it does not recurse into music, write the card, query Last.fm or
import on startup. A pure `find_exports(roots)` helper accepts explicit roots
for isolated tests. Windows roots come from the drive APIs, not fixed E:.
Each device prefers `.emepetres-scrobbler.log`; legacy exports remain supported
as fallback. One candidate imports using the existing worker/ledger path;
multiple candidates require choosing a file; missing media/export gives a
useful Spanish instruction, keeping manual import available. Network-drive
paths and reparse/symlink exports must not be silently followed by discovery.

Write failing tests first: preferred dedicated log, legacy fallback, multiple
roots, missing/disappearing media, no recursive scan or writes, no startup or
import network, GUI worker routes exact selected file and preserves bytes.
Implement minimally, run the full existing Windows suite plus new tests, and
package one updated executable after review. Keep the existing DPAPI session.

## Task 2: Compare with the vendor's actual libraries

Files: a read-only audit tool under `tools/emepetres/`, a dedicated CI workflow,
and evidence in `docs/EMEPETRES_DEVICE_VERIFICATION.md`.

Inputs: vendor 1.1 ISO SHA256
`d56d5b093477ad32ad50d41f09155d23c9f9a458993d2e40e800dd704c73b8e6`;
successful hosted/native build run 43276572060, source
`9b56f100abb7c824668ca3fb8a35332d290d1dfe`. Unpack the vendor image and rootfs
only in disposable GitHub runner storage using pinned ubi-reader 0.8.16.
Never execute vendor or MIPS binaries. Download compiler outputs from the
completed run; do not rebuild unchanged firmware. Compare ELF architecture,
loader and versioned symbol requirements of hosted core, bootloader and Last.fm
plugin against vendor-provided libraries. Check stock SD mount/startup and
recovery scripts where present. Upload reports/logs only, not proprietary
vendor payloads. Errors or missing symbols fail the audit or are reported as
unresolved explicitly. A passing audit does not validate physical recovery.

## Integration and verification

Independent files allow focused parallel implementation. Review both diffs,
run relevant local Windows tests once, and run CI for actual packaged GUI and
vendor extraction. Keep source compiler outputs separate from install kits.
Record exact revisions, checksums and material limitations. No user credentials,
private music names or local account data enter reports, tests or GitHub.
