# Silo for Roku

A native SceneGraph/BrightScript client for Silo libraries, using Roku's native
video and audio players. Connect to your Silo server in the app and sign in.
Saved servers, sessions and preferences remain on the Roku.

Tested on 14 Roku devices, with feedback from 50 testers as of October 23, 2026.

Browse Home, libraries, search, series, people and personal lists; switch
profiles; choose audio and subtitles; and resume playback. Supported servers
also provide audiobook chapters and text-only DRM-free EPUB reading. Reading
progress does not sync. Plex adapters remain in the source, but Plex is hidden
in the shipping interface.

Home row options let you hide, show and move rows. Settings → Manage Home rows
also restores hidden rows or resets this profile’s Home layout. Simultaneous
layout edits from another client can conflict.

## Devices

Supported device families include:

- Roku Ultra (4800 and 4850).
- Roku Streaming Stick 4K and 4K+ (3820 and 3821).
- Roku TVs, including the C208X/C000X family.

Available formats depend on the device, display and server. See [device limits](docs/roku-platform.md) and Roku's [hardware matrix](https://developer.roku.com/dev/docs/hardware).

## Build and test

Python 3.11 and Node 20 are used by the host checks.

```sh
npm ci --prefix tools/brightscript --ignore-scripts
node tools/brs_lint.cjs
SILO_REQUIRE_BRS=1 python3 -m unittest discover -s tests -v
python3 tools/package.py
```

The unsigned development package is `dist/silo-roku.zip`, with `manifest` at its
root. For a focused test run, use `python3 tools/run_tests.py -j 4 MODULE`.
The interpreter checks policies and synthetic fixtures; it does not emulate
Roku rendering, network behavior or media decoding.

## Install

Enable [Developer Mode](https://developer.roku.com/dev/docs/developer-setup) on
the Roku. Run lint, then upload the ZIP through the device's browser installer,
or use the helper:

```sh
node tools/brs_lint.cjs
ROKU_HOST=<device-ip> tools/sideload.sh
```

The helper prompts for the developer password. Sideloading replaces the single
existing development channel. A compile failure can remove that channel and its
saved sign-in. Check the installer result and BrightScript console after upload.
A development ZIP is not a signed store package.

## Controls and settings

Settings offers Top navigation or a saved Left overlay, appearance choices,
playback and subtitle preferences, saved servers and optional metadata. Select
the profile icon to switch profiles. Back or Right dismisses the profile drawer.
During playback, Up toggles diagnostics and Down opens transport controls.
Fwd/Rev previews a seek, OK commits it, Back cancels it, and Play toggles pause.

External metadata is disabled until configured. The
[metadata API](docs/metadata-api.md) describes compatible services, privacy and
registry compatibility. [Playback errors](docs/playback-errors.md) explains the
numbered errors and useful troubleshooting details.

Playback depends on the device, display, selected tracks and server capabilities.
See [device limits](docs/roku-platform.md). Compatibility playback for P8 MKVs requires
Auto, supported EAC3 audio up to 5.1, and subtitles Off. Experimental playback is restricted
to qualified devices and eligible files; its availability does not establish
general Dolby Vision support.

Upstream MPEG-TS copy negotiation is implemented; hardware playback validation
for that route is pending.

## Source and assets

`source/` and `components/` contain the app. `tests/` contains host tests and
synthetic fixtures. `tools/` contains packaging, lint and test helpers. Stock
playback engine files remain under `tools/experiments/onroku_audio/`; packaging
includes the required files without changing their runtime names.

Credentials, signed media URLs, signing keys and generated packages do not belong
in the repository. Sign in through the app. Brand and rating marks retain their
[brand](images/brand/NOTICE.txt) and [rating](images/ratings/NOTICE.txt) notices.
Roboto retains its [Apache 2.0 license](images/fonts/LICENSE.txt) and
[copyright notice](images/fonts/NOTICE.txt). The source is licensed under [AGPL-3.0](LICENSE).
