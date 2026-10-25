# Optional metadata API

Metadata is off by default. Settings → Optional metadata server accepts an HTTPS
base URL, optionally with a port and path prefix. Emptying the field disables it.
Credentials, query strings, fragments and cleartext HTTP are rejected. The URL is
stored only on that Roku in a separate `silo.metadata` registry section; a saved
media-server address or legacy metadata endpoint never enables this service.
There is no environment-variable override or bundled endpoint.

A compatible service must implement the routes below. This is the contract used
by [MetadataAdapter.brs](../source/adapters/MetadataAdapter.brs), not a claim that
an arbitrary metadata service supports it. No service is deployed by this app.

| Action | Request relative to the configured base | Accepted response |
| --- | --- | --- |
| Home | `GET /v1/catalog/home/rows?v=20260814-showcase-v7&format=compact` | `rows` array; optional `format: "compact-v1"` and shared `items` table |
| Service catalog | `GET /v1/catalog/service/{slug}?v=20260814-showcase-v7` | `rows` array; slug contains lowercase letters, digits and hyphens |
| Trending | `GET /v1/trending/all/week?page=1` | TMDB-style `results`, `page`, `total_pages`; pages limited to 1–20 |
| Artwork | `GET /v1/enrich/{movie\|tv}/{tmdbId}` | Exact matching `type` and numeric `tmdbId`, optional `posterPath` and `backdropPath` |
| Recommendations | `POST /v1/ava/recommendations` | `reply` string and `matches` array |

Home/service requests support `&cacheOnly=1` or `&refresh=1`. A current compact
Home refresh may return HTTP 204 to acknowledge queued work. Other responses
must contain JSON objects. Ordinary requests use a 10-second timeout; refresh
uses 12 seconds, artwork 4 seconds and recommendations 30 seconds.

A full row has `id`, `title` and `items`. A compact Home response instead has a
shared `items` array and rows with zero-based integer indices in `i`. At most
12 rows and 24 items per row are exposed. Catalog items contain `title`,
`type` (`movie`, `show` or `tv`) and external IDs (`tmdbId`, `imdbId`, `tvdbId`).
Optional display fields include `releaseYear`, `releaseDate`, `overview`,
`posterPath` and `backdropPath`. Artwork paths resolve only through the existing
TMDB image policy; arbitrary server-provided artwork URLs are rejected.
Trending accepts TMDB's `id`, `media_type`, `title`/`name`, `release_date`/
`first_air_date`, `overview`, `poster_path` and `backdrop_path` fields, with at
most 20 accepted results per page.

The recommendation JSON body has `prompt`, `libraryHints`, `libraryCandidates`
and `limit`. The prompt is limited to 1,000 characters. Candidates include only
minimal whitelisted facts from the active library; native item/source IDs,
media URLs and provider credentials are omitted. The response's `matches` use
`title`, `mediaType` and external IDs. A recommendation remains an unresolved
catalog item until an exact active-library identity match establishes ownership.
It cannot authorize playback or change a source/profile identity.

Requests send `Accept: application/json` and `X-Silo-Client: roku/{version}`;
POST also sends `Content-Type: application/json`. This contract requires no API
key. Silo bearer/profile/refresh tokens, Plex tokens, cookies and provider HTTP
headers are never forwarded. Requests start at the configured base; the old
special-case proxy rewrite has been removed. Existing native transport/TLS and
redirect behavior remains unchanged, with no provider credentials to redirect.

Responses are limited to 2 MiB of decoded text, or 96 KiB for artwork. These are
post-receipt validation limits; native string transfer may allocate the response
before rejecting it. Malformed configuration fails before transport. Source,
profile, generation, session revision and external artwork identity checks remain
in force. This host-verified configuration has not been tested on Roku hardware.

## Registry compatibility

UI/type names do not change Roku's signing identity or existing `silo:`/`plex:`
source IDs. On first access, the app enumerates registry sections and reuses the
single namespace whose provider-suffixed section contains a validated session
(or a signed-out provider section with validated local display/playback settings).
A small neutral registry marker preserves that selection after sign-out. The
original session, revision, preferences, address history and search history stay
in place; credentials are neither copied nor rekeyed. A fresh install uses the
`silo` namespace. Metadata configuration always uses its own fresh neutral
section and never inherits a legacy URL.
