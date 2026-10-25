# Roku device limits

The client uses SceneGraph and Roku's native Video and Audio nodes. Playback
support depends on the actual device, OS, display, container, codecs, HDR profile,
audio track and subtitle format. A model name or 4K badge does not establish
support. Runtime policies use device capability queries and server capabilities.

Native playback can use copied TS HLS, separate-audio HLS and optional server
DV7-to-DV8.1 conversion when supported. Auto playback tries bounded alternatives
and compatible audio, with HDR10 or SDR fallback where available. An eligible
file can expose Experimental Play on qualified C208X/C000X TVs; this is not a
general original Dolby Vision playback guarantee.

A C208X on OS16.0.4 build842 played a 3834×1602 P8 source through compatibility
HLS with subtitles Off. This path currently requires MKV and supported EAC3
audio up to 5.1. Native Video reported Dolby Vision and EAC3; physical
display HDR and audible audio were not independently confirmed.

Recorded in-house native checks cover Roku TV configurations. Community testing
figures are listed in the README. The 512 MB HD device tier
has not been qualified. Host tests cannot establish focus behavior, memory
limits, startup time, first frame, decoder support or sustained playback on an
untested device. Lossless passthrough, Atmos, arbitrary embedded subtitles and
all HDR/Dolby Vision combinations are not promised.

For a device check, record the exact model, Roku OS, selected stream format,
first frame or numbered error, seek behavior, audio/subtitle behavior and any
unsupported combinations. Omit tokens and signed URLs from reports.

Roku references: [hardware](https://developer.roku.com/dev/docs/hardware),
[media formats](https://developer.roku.com/dev/docs/media),
[device capabilities](https://developer.roku.com/dev/docs/ifdeviceinfo), and
[native video](https://developer.roku.com/dev/docs/playing-videos).

## Manual control screen reader support

Manual browse buttons, pills, navigation destinations and profile controls use
one `roAudioGuide` instance and the system screen reader setting. Focus changes
announce a bounded control label, role and position. Native lists and dialogs
retain Roku's own announcements. Repaints, edge moves, hidden controls and
background focus do not request speech. Profile controls use a fixed menu label.

Device acceptance remains pending: verify speech with the system reader on and
off, manual-to-native focus transitions, dialogs, drawer navigation and background
return on HD and 4K hardware. Enabling the reader while focus is stationary waits
for the next committed focus change; this implementation adds no device polling.
