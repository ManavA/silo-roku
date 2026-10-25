# Silo catalog fixtures

## Device authorization audit

The device capability, start, pending, approved, and refresh fixtures were
checked against Android revision
`d849901c760e1105d8623b6832c55576ef069bc2`, its `AuthDtos.kt`,
`CapabilityDtos.kt`, `SiloLinkFlowImpl.kt`, and committed v2 OpenAPI contract.
Device login requires `state: "available"` and pairing protocol `2`.
The device capability's optional `allowed` field can be absent or null;
it does not decide whether sign-in is supported. Playback retains its
separate protocol `3` and `allowed` checks.

The local Silo server source inspected at
`55d0578cfdf1271a74f07675c0bdf22b850c6f3b` exposes older `/api/v1`
device-auth routes and flat token fields. It does not establish compatibility
with the Roku v2 adapter. No live v2 server URL or account was supplied,
so actual code approval, profiles, token refresh, catalog, and playback remain
pending. The current fixtures contain synthetic credentials only.

The subsequent onboarding audit read Android revision
`45774f8bfe92b0517f42a60e7c8be4ce026f4858`, including the v2 OpenAPI
`DeviceLoginPoll`, `TokenPair`, `ProfileVerification`, profile-list, and
verify-PIN contracts. A full login may return blank profile fields. Approval
now replaces the saved credentials and account/profile metadata together and
returns only public identity to the scene. Profile listing and PIN verification
use bearer auth without the optional selected-profile headers so an expired
profile proof cannot prevent selecting or unlocking another profile. A rejected
PIN is an explicit failure and preserves the saved profile.

`test_silo_auth_task.py` executes the worker and adapters with synthetic HTTP
responses and serialized registry records. It covers start/pending/full approval,
profile selection, restart status, sign-out, one refresh-and-retry, PIN failure
and success, stale-session approval rejection, and failed approval persistence.
This is local contract evidence; live Silo v2 authorization and hardware proof
remain pending.

## Catalog contract

The new marker, recommendation, person, and detail-credit fixtures are synthetic examples of the Silo v2 contract inspected in the Android reference at `e9f2ee94ddd625ba41d7634fcf18d1ad7b464608`:

- `docs/planning/silo-api/openapi.json`
- `backend/silo/src/main/kotlin/tv/silo/backend/silo/dto/CatalogDtos.kt`
- `backend/silo/src/main/kotlin/tv/silo/backend/silo/dto/CollectionDtos.kt`
- `backend/silo/src/main/kotlin/tv/silo/backend/silo/catalog/SiloCatalogApi.kt`

`markers_occurrences.json` uses the current `marker_segments` array. `markers_file.json` exercises the segment-only shape used by the Android `FileMarkersDto` and its `file_markers.json` fixture. The adapter supports that older representation when `marker_segments` is absent. An explicit occurrences array is authoritative, so repeated kinds survive without adding duplicate singular summaries.

Detail and file-version markers use `start`/`end`; the standalone endpoint uses `start_seconds`/`end_seconds`. Version duration remains milliseconds. Filmography uses `POST /api/v2/catalog/query` with `source: "person"`, `person_id`, bounded `limit`, and an optional cursor.

Names, identities, biography, image domains, and timing values are synthetic. Tests add unknown private fields in memory to verify the adapter's whitelist; the fixtures contain no credentials or media URLs. No fixture establishes live-server compatibility or Roku playback behavior.

## External identity fixtures

`catalog_item_detail_external_ids.json` and `episodes_external_ids.json` are
synthetic examples inspected against Android revision
`d849901c760e1105d8623b6832c55576ef069bc2`, its `SiloMapper.kt`, and the
current OpenAPI schema. `CatalogItemDetail` and `Episode` define optional
string fields `tmdb_id`, `imdb_id`, and `tvdb_id`; the Roku adapter validates
and preserves them as `tmdbId`, `imdbId`, and `tvdbId`. Null, missing,
malformed, nonstring, and URL-like values remain empty unknown IDs. Provider
`content_id` remains the item identity.

`CatalogItem` summaries used by Home, catalog query, Similar, and filmography
do not define these fields. Neither does `Season`. Those responses discard
even valid-looking injected IDs. Hydrated Detail records can participate in
Metadata exact matching after binding them to the current full Silo source
ID; catalog summaries still need verified Detail hydration before matching.

## Stock P7 HDR10 compatibility metadata

`stock_p7_hdr10_technical_metadata.json` is a strict technical-field projection
from the successful stock48ae sampler-v4 run. It preserves one native video,
three audio tracks,45PGS tracks, and the observed compatibility metadata/receipt
default and delivery labels. Test wrappers supply synthetic identities and routes.
Native original TrueHD defaults remain distinct from the selected AC3six receipt.

All identifiers, paths, titles, artwork, URLs, credentials, headers, hashes,
wall-clock timestamps and chapters are omitted. Bitrate, duration ticks and
reanchor retain observed technical values. Independent projection/privacy review
found all retained values/types/ordered arrays identical to the private captures.
This is metadata evidence; native Roku playback remains a separate gate.

## Stock Auto quality ladder replay

`stock_auto_1080_ladder.json` preserves the capabilities/catalog metadata and
HTTP201 receipts from the 2026-10-21 stock Auto refusal and separately requested
explicit1080 success. The test composes those responses as a host-only automatic
ladder transcript; the server was not observed completing that automatic sequence.
The failure is `adaptation_unavailable` / `transcode_start_failed`, with
`retryable=false` and no session or plan. The successful receipt is the observed
H2641080 SDR/AAC2 HLS transcode, validated by the shipping receipt validator.

Identity fields, titles, paths, URLs, timestamps, revision fingerprint and messages
are obvious fixture replacements. Technical metadata, field omission, ordered
tracks, transformations, claims and terminal reason/Boolean retain their observed
values. The SDK profile is hypothetical and copied from the private preflight:
AVC main/high through4.2, HEVC main10 through5.1, HDR10 without DV, AAC stereo
without AC3/EAC3. This fixture proves host behavior only; it adds no server-run,
Roku decoder, first-frame or physical playback qualification. See
`docs/evidence/2026-10-21-stock-explicit1080-fallback.md` for the actual probe.
