# emepetres: visual update, 2026-11-13

The first installed package retained Rockbox's stock presentation. It did not
fulfil the promised visual redesign. This update changes the library and Home
presentation, using the existing compiled application and Rockbox skin renderer.
The user delegated visual and implementation choices and requested work to
proceed without another design questionnaire or expensive verification loops.

## Design decisions made by the implementer

- Graphite background, warm white text, solid mint selection, no stock icons,
  gradients or decorative background.
- A separate small brand/battery header, large scrolling page title, five
  21-pixel rows and a persistent playback footer on the 128 x 160 display.
- Nimbus 14 for list text and Nimbus 19 for titles. These fonts are public
  domain according to the repository's BDF sources. The small Adobe font and
  its existing licence remain unchanged.
- Consistent minimal playback screen with cover, track title, artist, progress
  and elapsed/total time. Browsing remains the priority.

These colours and typography are new implementation choices, not claimed as
recovered user specifications. Navigation/button logic, playback logging and
music metadata are unchanged by this visual package.

## Delivery and focused verification

Build fonts with the repository's own convbdf. Parse both skins with the actual
Rocker checkwps parser and capture Home in the previously built simulator.
Use one dedicated manually triggered job, without a firmware rebuild, Windows
rebuild, large synthetic library or OCR loop. If the visual check exposes an
actual defect, correct that defect rather than broadening the test scope.

Deliver only a .rockbox overlay and a separate small activation .cfg. Applying
the .cfg changes visual settings and selects Spanish. Preserve the existing
configuration, database, playback logs and Last.fm export. No updater image is
included and no second internal firmware update is required for these assets.
