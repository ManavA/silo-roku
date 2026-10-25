# Selected LAN identity check

`LanIdentityTask` checks one explicitly selected entry from the discovery policy's
current candidate list. The sign-in chooser starts it only after the user selects a discovered
server and confirms its address. Set `job` to `{token, generation, candidates, selected}`;
`selected` is a zero-based index. Cancellation or a changed token/generation
suppresses publication. The result preserves token/generation and reports `ok`
or `errorCode`. Success includes `serverId` and `trusted: false`.

The Task sends only an anonymous `GET /api/v2/system/identity` over a new TCP
connection to the candidate's literal RFC1918 IPv4 address and SRV port. It sends
Host, Accept, Accept-Encoding, and Connection headers only. No credentials,
cookies, device identity, discovery hostname, TXT URL, or arbitrary endpoint enter
the request. Redirect responses fail; no second connection follows them.

The response must be HTTP/1.0 or HTTP/1.1 status 200 with one Content-Length or
chunked transfer framing. Ambiguous framing, duplicate framing headers,
nonidentity content encoding, chunk extensions, and close-delimited bodies fail.
Limits are 4 KiB of response headers, 16 KiB of accumulated decoded body, 32 KiB
of wire response, 128 chunk records including the terminal zero chunk, 128 bytes
per chunk-size line, and 1 KiB of trailers. Read buffers are fixed at 1 KiB; these
limits describe retained protocol data, not total native allocation or JSON
object memory. JSON nesting is checked before ParseJson and limited to 16 levels.
The entire operation has a monotonic five-second budget and closes its socket on
completion, failure, timeout, cancellation, and replacement. Socket readiness is
polled with waits of at most 25 ms. The message port enables nonblocking socket
operations; socket event notifications stay disabled so writable events cannot
turn those waits into a busy loop.

Only exact `server_id` equality with the selected discovery ID succeeds. Unknown
JSON fields are ignored within the body/depth limits. The public server contract
has no display-name field: `internal/apiv2/system_identity.go` at `6f906c7c3` in the
read-only server reference. Equality establishes consistency between discovery
and HTTP; it does not authenticate the server or authorize sign-in.

## API evidence and verification limits

The existing generic HTTP helper uses AsyncGetToString and checks body size after
receipt. The current [ifUrlTransfer reference](https://developer.roku.com/dev/docs/ifurltransfer)
documents neither redirect suppression nor a streaming response byte ceiling.
This Task therefore uses the endpoint-specific socket framing above.

[ifSocket](https://developer.roku.com/dev/docs/ifsocket) and
[ifSocketConnection](https://developer.roku.com/dev/docs/ifsocketconnection)
document nonblocking behavior when a valid message port is assigned. Connect can
still be pending. The Task checks socket errors before accepting either
IsConnected or IsWritable as readiness to attempt Send. Send/Receive return byte
counts and retain their error checks.
[ifSocketStatus](https://developer.roku.com/dev/docs/ifsocketstatus) documents eOK
as including asynchronous not-ready conditions. The
[roStreamSocket example](https://developer.roku.com/dev/docs/rostreamsocket)
treats zero received bytes as peer closure. References read on 2026-10-25.

Host tests execute the real BrightScript policy, framing parser, and Task loop,
substituting the native socket/clock seam. They do not prove Roku SDK transport
behavior. A limited native harness on a C208X with Roku OS 16.0.4 observed
Connect and eInProgress true, IsConnected remaining false, and IsWritable true.
Accepting writable readiness sent 137 request bytes and received 245 response
bytes; the public server ID matched exactly and the result remained untrusted.
That harness also observed 15,344 polls in five seconds with writable
notifications enabled, motivating the timed polling above. A second native run using the final production Task with notifications
disabled also completed discovery and the exact identity check. Native partial-send/read, cancellation,
and resource cleanup qualification remain pending. This evidence does not
qualify the sign-in UI or authentication.

The integrated chooser reached QR sign-in on the same Roku using a controlled
host discovery responder. Approval through the server API then opened the
signed-in home screen. Manual-entry cancellation and discovery from saved-server
choices were also exercised. The original saved profile and HDMI input were
preserved. Phone-app interaction, other hardware, and default Docker bridge
discovery remain outside this smoke test.
