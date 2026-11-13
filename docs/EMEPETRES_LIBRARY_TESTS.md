# Synthetic library runtime checks

Run from the repository root on an isolated Linux Xvfb display:

```sh
xvfb-run -a python3 tools/emepetres/tests/simulator_library_smoke.py build-agptekrocker
xvfb-run -a python3 tools/emepetres/tests/simulator_library_smoke.py build-agptekrockernative
```

Requires the existing `rockboxui` and `rockbox.zip` in each build folder and
runner packages `xvfb`, `xdotool`, `ffmpeg` (including ffprobe), and
`tesseract-ocr` with English data. No pip dependency, compiler, firmware rebuild,
device mount, real library, account, or network service is involved.

The fixture is created inside a temporary root and removed on exit: 2,054 FLAC
tracks, 258 artists, and 258 unique album labels. A single ffmpeg invocation
encodes a 31-second silent seed. The stdlib helper replaces only Vorbis comments,
preserving STREAMINFO and compressed audio. Its metadata headers follow
[RFC 9639 sections 8.1 and 8.6](https://www.rfc-editor.org/rfc/rfc9639.html#section-8.6).
ffprobe validates tags and ffmpeg fully decodes two representative rewritten
files before launching the simulator. The runner waits for the actual database
staged database header to report all 2,054 scanned tracks, restarts once as
required by the first foreground commit, then requires a clean master header
containing all 2,054 records. This follows Rockbox's deferred initial commit;
the test does not wait indefinitely for a background commit that requires boot.

Bulk artist and album tags use two-letter suffixes from `BCDEFGHJKMNPQRST`:
`Bison BB` / `Opus BB` through `Bison TT` / `Opus TT`; index 20 is `CF`.
Their track titles are `Tune One` through `Tune Eight`. Numeric filenames and
actual track/disc metadata remain numeric. These clear labels avoid ambiguous
OCR digits without accepting substitutions such as letter O for digit zero.
The alphabet excludes A so the three A-query results remain unique.

The checks exercise actual Rocker button input and inspect actual screenshots:

- Artists scrolled beyond the first screen; selected album and track after
  Back and Home; exact list viewport restoration after switching to Albums.
- Independent Albums depth and selection after a detour through Artists.
- Four multidisc tracks selected in disc/track order: One, Two, Three, Four.
  Fixture creation order and filenames deliberately run in the reverse order.
- Aster and Zulu each own an album named Echo. Artist browsing must isolate
  Amber from Indigo; Down wraps back to the same track in each artist's
  single-track Echo. Global Albums browsing selects Amber, then Indigo, then
  wraps back to Amber, proving exactly two tracks.
- Search → First Letter → Artists → A, and Albums → D, with explicit selected
  artist/album and wraparound proving exactly one matching artist or album.
- Artist, Album, and Title searches using the actual on-screen keyboard's
  initial A key. Their unique results are Aster, Delta, and Amber respectively.
  Down must wrap to the first shortcut for Artist/Album and remain on Amber
  for Title. Album shortcuts begin with By album, then All tracks; artist
  shortcuts begin with All tracks.

Every asserted screen retains its PNG, raw whole-screen OCR, isolated selected-row
OCR, and an assertion record with expected and observed values. Selection checks
locate the theme's yellow list cursor and OCR that row; a name visible elsewhere
cannot satisfy them. Selected names must match complete word tokens, so `A`
cannot match `Random` and `Artist` cannot match `Artists`. Only letter case and
whitespace are normalized. Missing,
ambiguous, or incorrect OCR fails the run. Bounded retries recapture the same
state and do not send additional navigation. A pixel comparison checks the
restored scrolled list below the status/title bars.

Journey semantics use the selected-row reader rather than unselected whole-screen
OCR. Whole-screen OCR remains available for visual review. Result counts and
artist isolation are checked by actual Down navigation and exact wraparound
states, rather than by whether an unrelated name is readable elsewhere.

Selected-row recognition keeps the original 8× thresholded PSM 7 result as its
primary raw output. Only when that fails the exact expected phrase, it tries
up to three alternatives: 4× Lanczos grayscale PSM 7, 4× nearest grayscale
PSM 7, and 8× nearest grayscale PSM 13. The same isolated cursor row is used
in every variant. Every attempted variant and its raw text are retained in
`*-selected-variants.json` and the assertion record. No letter substitutions
or approximate string matching are accepted.

Fast runner calibration uses exact PNG bytes copied from CI run 43397843051:

```sh
python3 -m unittest discover -s tools/emepetres/tests -p test_library_ocr.py -v
```

These static fixtures reproduce the Albums/“Albuns” recognition failure and
previously passed Artists, Bison CF, and Tune One states. The test requires
the correct selected label and rejects wrong labels, including other visible
Home items. It needs ffmpeg and Tesseract but no display, simulator, or music.
Hosts without those tools report an explicit skip.

Results go to `BUILD/library-results/`: `fixture.json`, `database-header.json`,
`startup.log`, `assertions.jsonl`, numbered screenshots/OCR files, and
`passed.json` only after every runtime check succeeds. Retain this folder as a
CI artifact, including when the command fails. A fresh invocation removes an
old `passed.json`; do not infer success from screenshots alone.

Portable helper verification:

```sh
python -m unittest discover -s tools/emepetres/tests -p test_library_fixture.py -v
```

These helper checks validate comment encoding, preservation of audio bytes,
rejection of truncated/non-FLAC input, exact fixture scale, unique query results,
duplicate album ownership, and adversarial multidisc data.

## Limits

The user requested that optional validation costs be curtailed on 2026-11-13.
The extended OCR journey is therefore opt-in via workflow_dispatch input
`extended_library=true`; it is not part of ordinary pushes. Last run
43400300387 reached the album first-letter D check in both simulators and
failed to verify that selected letter. Do not report the complete journey as
passed. Earlier selected artist/album/track Back/Home restoration, exact viewport
comparison, album isolation, multidisc order and artist-first-letter steps
completed before that point. Search queries after that point remain unexecuted.

The new runner needs execution against both Linux simulators before runtime
coverage can be claimed. Portable helper tests and Python compilation do not
establish that any SDL navigation or OCR step passed. OCR is deliberately tied
to the packaged default English theme and its yellow selection cursor. Changing
the theme, font, language, keyboard layout, or input mappings may require updating
the runner. The query coverage is one deterministic uppercase A substring per
field, not arbitrary typing, accented search, empty results, or query editing.
The first-letter checks cover A artists and D albums, not every letter or special
character group. A 2,054-track synthetic database is useful scale coverage but
does not establish performance or correctness for a user's complete library,
damaged tags, physical hardware, or every runtime database cache transition.
