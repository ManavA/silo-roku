# Playback error numbers

Silo Roku0.2.5 keeps playback errors on screen until **OK** or **Back**. Write
down the four-digit number; native failures can also show a Roku number, such
as `#3001 … (Roku -5)`. The Roku number is a device error, not a diagnosis that
the file, network, audio or video decoder alone is at fault.

| Number | Meaning | Useful next check |
| --- | --- | --- |
|1001 | Server returned no available files, including one fresh retry | Profile quality/library access, indexed file availability and correct episode/item |
|1002 | Invalid or mismatched file inventory/target | App/server version; requested versus returned item identity |
|1003 | Explicitly selected version is unavailable | Reopen detail and choose an existing version |
|1004 | Item or episode details could not be loaded | Connection, authentication, item availability and server response |
|1005 | Experimental selection could not be validated | Reopen the selection and choose the version and audio again; this code does not identify which check failed |
|2001 | Playback preparation failed without a more specific known reason | Server playback decision and conversion/tool readiness |
|2002 | Server has no playable source | Exact source inventory and server decision |
|2003 | Server has no compatible alternate version | Alternate source and adaptation policy; this code alone does not establish a4K transcode block |
|2004 | HDR/DV preparation unsupported | DV profile, server recipe/tool support and compatible HDR10/SDR alternatives |
|2005 | Audio conversion unsupported | Selected audio codec, compatible same-program track and server tools |
|2006 | Subtitle conversion unsupported | Selected subtitle format and fidelity/conversion support |
|2007 | Unsupported playback protocol | Server and client versions; protocolV3 is required |
|2008 | Unsupported returned stream format | Actual container/packaging and negotiated native recipes |
|2009 | Server conversion disabled | Effective account/server conversion policy |
|2010 | Required conversion tool unavailable | Server worker toolchain and recipe readiness |
|2011 | Source format information incomplete | Server scanning/probing and file metadata |
|2012 | Server could not read source | Server storage/mount and file availability |
|2013 | Bitrate policy cannot be met | Requested bandwidth cap and available server outputs |
|2014 | Server alternatives exhausted | Earlier route failures, available sources and conversion tools |
|3001 | Native Roku playback failed | Additional Roku error number, exact file/profile, audio, packaging and device/output |
|3002 | Native playback readiness timed out | Buffering, network, server preparation and supported format |
|3003 | Bounded recovery options exhausted | Last server reason, available versions and conversion policy |
|3004 | Playback session changed | Profile/source/session changes; start a fresh playback attempt |

For support, include the number, app version, Roku model/OS and whether the
failure occurred before buffering or during playback. A screenshot of the
dialog is sufficient to record its number; do not share tokens or media URLs.

## Automatic reports

For a recorded playback attempt, the app makes one optional background POST to
the **connected Silo server's** existing `/api/v2/playback/route-events` endpoint.
The dialog appears first and remains dismissible while reporting runs. Only a
matching accepted receipt adds **“Report sent to your Silo server.”** A receipt
means the server accepted/queued the event, not that support has reviewed it.

The event contains the fixed error number, an allowlisted reason/error name,
an optional numeric Roku error name, a bounded device-model identifier and the
opaque attempt/session identifiers needed to verify ownership. Normal app
version/authentication headers accompany the request. Raw server/native error
text, titles, file paths, media URLs and tokens are excluded from its diagnostic
payload. Authentication remains in request headers.

Reporting is limited to one request with a3-second timeout, with no automatic
retry or token refresh. Unsupported endpoints, expired authentication, rate
limits, transport errors and invalid acknowledgments leave the manual number
available. A report cannot update a dismissed/replaced dialog or another profile.

Inventory/preflight errors have no recorded playback attempt, so these are
**not automatically uploaded**. Sending those would require a new server
contract. Full diagnostic-bundle uploads are a separate API whose current
platform list does not accept Roku.

## Recovery changes

- Empty Silo inventory gets one fresh same-item read. Successful ordinary
  playback gets no added inventory request.
- Series Play resolves a verified episode rather than treating the series as
  a media file. It uses that episode's resume position; an empty episode list
  receives the same single retry. Unrelated/stale responses cannot change the
  requested title.
- A refused HLS format can request a compatible same-file output after cleanup;
  in-play replanning advances the current receipt before retrying.
- Auto quality can descend through1080p,720p and480p, then stops. In-play
  recovery uses only qualities the server advertises. Explicit quality and
  track choices remain fixed, and native version fallback stays in the same
  validated edition/part.

These requests do not override server access, conversion policy or missing
tools. Native DV capability gates are unchanged; a compatible fallback request
is not a guarantee of4K/DV playback on every Roku.
