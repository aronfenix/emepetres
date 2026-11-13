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

The checks exercise actual Rocker button input and inspect actual screenshots:

- Artists scrolled beyond the first screen; selected album and track after
  Back and Home; exact list viewport restoration after switching to Albums.
- Independent Albums depth and selection after a detour through Artists.
- Four multidisc tracks selected in disc/track order: One, Two, Three, Four.
  Fixture creation order and filenames deliberately run in the reverse order.
- Aster and Zulu each own an album named Echo. Artist browsing must isolate
  Amber from Indigo; global Albums browsing intentionally contains both.
- Search → First Letter → Artists → A, and Albums → D, with explicit selected
  artist/album and excluded unrelated library names.
- Artist, Album, and Title searches using the actual on-screen keyboard's
  initial A key. Their unique results are Aster, Delta, and Amber respectively.

Every asserted screen retains its PNG, raw whole-screen OCR, isolated selected-row
OCR, and an assertion record with expected and observed values. Selection checks
locate the theme's yellow list cursor and OCR that row; a name visible elsewhere
cannot satisfy them. Only letter case and whitespace are normalized. Missing,
ambiguous, or incorrect OCR fails the run. Bounded retries recapture the same
state and do not send additional navigation. A pixel comparison checks the
restored scrolled list below the status/title bars.

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
