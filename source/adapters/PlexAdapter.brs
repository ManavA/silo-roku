' Plex wire reference: Android worktree e9f2ee94ddd625ba41d7634fcf18d1ad7b464608.
' Pure request/decoder functions. Tokens belong to headers or credential results,
' never URLs, error text, media cards, or diagnostic output.

function BuildPlexRequest(action as String, session as Object, params as Object) as Object
    headers = PlexHeaders(session, false)
    if headers["X-Plex-Client-Identifier"] = "" then return PlexFailure("client_identity_missing", "Create a client identity before connecting.")
    request = { ok: true, method: "GET", url: "", headers: headers, body: "" }
    if action = "pin_start"
        request.method = "POST"
        request.url = "https://plex.tv/api/v2/pins?strong=false"
        request["timeoutMs"] = 8000
        return request
    else if action = "pin_poll"
        pinId = PlexText(PlexField(params, "pinId"))
        if not PlexIdentifier(pinId) then return PlexFailure("invalid_request", "The connection code is missing.")
        request.url = "https://plex.tv/api/v2/pins/" + pinId.EncodeUriComponent()
        ' PIN state changes after approval. Ask caches to revalidate each poll
        ' and keep a stalled attempt within the other apps' five-second bound.
        request.headers["Cache-Control"] = "no-cache"
        request.headers["Pragma"] = "no-cache"
        request["timeoutMs"] = 5000
        return request
    end if

    if action = "user" or action = "resources"
        ' plex.tv account APIs require the account PIN token. A selected or
        ' shared server can have a different resource access token.
        accountToken = PlexText(PlexField(session, "accountToken"))
        if accountToken = "" then return PlexFailure("auth_required", "Sign in to Plex to continue.")
        request.headers["X-Plex-Token"] = accountToken
    else
        token = PlexText(PlexField(session, "token"))
        if token = "" then token = PlexText(PlexField(session, "accountToken"))
        if action <> "identity" and token = "" then return PlexFailure("auth_required", "Sign in to Plex to continue.")
        request.headers = PlexHeaders(session, true)
    end if
    if action = "user"
        request.url = "https://plex.tv/api/v2/user"
        return request
    else if action = "resources"
        request.url = "https://plex.tv/api/v2/resources?includeHttps=1&includeRelay=1"
        return request
    end if

    base = PlexBaseUrl(PlexField(session, "baseUrl"), PlexBoolean(PlexField(session, "local")))
    if base = "" then return PlexFailure("invalid_server", "Enter a valid server address.")
    count = PlexLimit(PlexField(params, "limit"), 24)
    offset = PlexPageOffset(PlexField(params, "offset"))
    itemId = PlexText(PlexField(params, "itemId"))
    sectionId = PlexText(PlexField(params, "sectionId"))
    if action = "identity"
        request.url = base + "/identity"
    else if action = "transcode_inventory"
        request.url = base + "/transcode/sessions"
        request["responseBodyLimit"] = 32768
        request["capturePlexContainerHeaders"] = true
        request["timeoutMs"] = 2000
    else if action = "sections"
        request.url = base + "/library/sections"
    else if action = "artwork_detail"
        if not CreateObject("roRegex", "^[0-9]{1,20}$", "").IsMatch(itemId) then return PlexFailure("invalid_request", "Choose an item first.")
        ' Identity hydration needs GUIDs, not playback, markers, cast or extras.
        request.url = base + "/library/metadata/" + itemId.EncodeUriComponent() + "?includeGuids=1"
        request["responseBodyLimit"] = 98304
        request["timeoutMs"] = 4000
    else if action = "home_continue" or action = "home_on_deck"
        path = "/hubs/home/continueWatching"
        if action = "home_on_deck" then path = "/hubs/home/onDeck"
        request.url = base + path + "?count=12&includeGuids=1&includeLibrarySectionTitle=1"
        request.headers["X-Plex-Container-Start"] = "0"
        request.headers["X-Plex-Container-Size"] = "12"
    else if action = "library_items" or action = "section_hubs"
        if not PlexIdentifier(sectionId) then return PlexFailure("invalid_request", "Choose a library first.")
        if action = "library_items"
            sort = PlexText(PlexField(params, "sort"))
            if sort = "" then sort = "titleSort:asc"
            request.url = base + "/library/sections/" + sectionId.EncodeUriComponent() + "/all?includeGuids=1&sort=" + sort.EncodeUriComponent()
            request.url += "&X-Plex-Container-Start=" + offset.ToStr() + "&X-Plex-Container-Size=" + count.ToStr()
        else
            request.url = base + "/hubs/sections/" + sectionId.EncodeUriComponent() + "?count=24&includeGuids=1&includeLibrarySectionTitle=1"
            request.headers["X-Plex-Container-Start"] = "0"
            request.headers["X-Plex-Container-Size"] = "24"
        end if
    else if action = "search"
        query = PlexText(PlexField(params, "query"))
        request.url = base + "/hubs/search?query=" + query.EncodeUriComponent() + "&limit=" + count.ToStr() + "&includeCollections=0&includeGuids=1"
    else if action = "detail" or action = "children" or action = "related"
        if not PlexIdentifier(itemId) then return PlexFailure("invalid_request", "Choose an item first.")
        request.url = base + "/library/metadata/" + itemId.EncodeUriComponent()
        if action = "children"
            request.url += "/children?includeGuids=1"
            request.url += "&X-Plex-Container-Start=" + offset.ToStr() + "&X-Plex-Container-Size=" + count.ToStr()
        else if action = "related"
            request.url += "/related"
        else
            request.url += "?includeOnDeck=1&includeMarkers=1&includeExtras=1&includeChapters=1&includeReviews=0"
        end if
    else if action = "transcode_decision" or action = "transcode_start" or action = "transcode_stop"
        return PlexTranscodeRequest(action, session, params, request, base)
    else if action = "timeline"
        if not PlexIdentifier(itemId) then return PlexFailure("invalid_request", "Choose an item first.")
        state = PlexText(PlexField(params, "state"))
        if state <> "playing" and state <> "paused" and state <> "stopped" then return PlexFailure("invalid_request", "Playback state is unavailable.")
        position = Int(PlexNumber(PlexField(params, "positionMs"), 0))
        duration = Int(PlexNumber(PlexField(params, "durationMs"), 0))
        if position < 0 then position = 0
        if duration < 0 then duration = 0
        request.url = base + "/:/timeline?ratingKey=" + itemId.EncodeUriComponent() + "&key=" + ("/library/metadata/" + itemId).EncodeUriComponent()
        request.url += "&state=" + state + "&time=" + position.ToStr() + "&duration=" + duration.ToStr() + "&hasMDE=1"
    else if action = "scrobble" or action = "unscrobble"
        if not PlexIdentifier(itemId) then return PlexFailure("invalid_request", "Choose an item first.")
        request.url = base + "/:/" + action + "?key=" + itemId.EncodeUriComponent() + "&identifier=com.plexapp.plugins.library"
    else
        return PlexFailure("unsupported_action", "This Plex operation is unavailable.")
    end if
    return request
end function

function PlexTranscodeRequest(action as String, session as Object, params as Object, request as Object, base as String) as Object
    playbackId = PlexText(PlexField(params, "transcodeSessionId"))
    if not PlexIdentifier(playbackId) then return PlexFailure("invalid_request", "A playback session is required.")
    if action = "transcode_stop"
        request.url = base + "/video/:/transcode/universal/stop?session=" + playbackId.EncodeUriComponent()
        return request
    end if
    itemId = PlexText(PlexField(params, "itemId"))
    if not PlexIdentifier(itemId) then return PlexFailure("invalid_request", "Choose an item first.")
    profile = PlexText(PlexField(params, "profileExtra"))
    if profile = "" then return PlexFailure("capabilities_required", "Measure playback capabilities before requesting a stream.")
    bitrate = Int(PlexNumber(PlexField(params, "maxVideoBitrate"), 8000))
    if bitrate < 1 or bitrate > 200000 then return PlexFailure("invalid_request", "Choose a valid playback quality.")
    resolution = PlexText(PlexField(params, "videoResolution"))
    if resolution = "" then resolution = "1920x1080"
    if not CreateObject("roRegex", "^[0-9]+x[0-9]+$", "").IsMatch(resolution) then return PlexFailure("invalid_request", "Choose a valid playback resolution.")
    mediaIndex = Int(PlexNumber(PlexField(params, "mediaIndex"), 0))
    partIndex = Int(PlexNumber(PlexField(params, "partIndex"), 0))
    if mediaIndex < 0 or partIndex < 0 then return PlexFailure("invalid_request", "Choose a valid media version.")
    endpoint = "decision"
    protocol = "*"
    if action = "transcode_start"
        endpoint = "start.m3u8"
        protocol = "hls"
    end if
    location = "wan"
    if PlexBoolean(PlexField(session, "local")) then location = "lan"
    path = "/library/metadata/" + itemId
    request.url = base + "/video/:/transcode/universal/" + endpoint + "?path=" + path.EncodeUriComponent()
    request.url += "&audioBoost=100&autoAdjustQuality=0&directPlay=0&directStream=1&directStreamAudio=1&fastSeek=1"
    if action = "transcode_start"
        ' Keep the canonical manifest at zero. Roku ContentNode.PlayStart
        ' selects the resume position without a server-relative timeline.
        request.url += "&offset=0"
    end if
    request.url += "&hasMDE=1&location=" + location + "&maxVideoBitrate=" + bitrate.ToStr() + "&mediaBufferSize=209664"
    request.url += "&mediaIndex=" + mediaIndex.ToStr() + "&partIndex=" + partIndex.ToStr() + "&protocol=" + protocol.EncodeUriComponent()
    request.url += "&session=" + playbackId.EncodeUriComponent() + "&subtitles=none"
    if action = "transcode_start" then request.url += "&subtitleSize=100"
    request.url += "&videoQuality=100&videoResolution=" + resolution + "&X-Plex-Client-Profile-Extra=" + profile.EncodeUriComponent()
    audioId = PlexText(PlexField(params, "audioStreamId"))
    if audioId <> "" then request.url += "&audioStreamID=" + audioId.EncodeUriComponent()
    for each key in ["X-Plex-Client-Identifier", "X-Plex-Product", "X-Plex-Version", "X-Plex-Platform", "X-Plex-Platform-Version", "X-Plex-Device", "X-Plex-Model"]
        value = request.headers[key]
        request.url += "&" + key + "=" + value.EncodeUriComponent()
    end for
    return request
end function

function DecodePlexResponse(action as String, body as String, params as Object) as Object
    if action = "timeline" or action = "transcode_stop" or action = "scrobble" or action = "unscrobble" then return { ok: true, data: {} }
    root = ParseJson(body)
    if action = "resources" then return PlexDecodeResources(root)
    if not PlexIsObject(root) then return PlexFailure("decode_error", "Plex returned an unreadable response.")
    if action = "pin_start"
        pinId = PlexText(PlexField(root, "id"))
        code = PlexText(PlexField(root, "code"))
        if not PlexIdentifier(pinId) or code = "" then return PlexFailure("decode_error", "Plex did not return a connection code.")
        nowMs = PlexNumber(PlexField(params, "nowMs"), 0)
        expiresIn = PlexNumber(PlexField(root, "expiresIn"), 1800)
        expiry = nowMs + expiresIn * 1000
        isoExpiry = PlexText(PlexField(root, "expiresAt"))
        if isoExpiry <> ""
            date = CreateObject("roDateTime")
            date.FromISO8601String(isoExpiry)
            epoch = date.AsSeconds()
            if epoch > 0 then expiry = epoch * 1000.0#
        end if
        return { ok: true, data: { pinId: pinId, code: code, linkUrl: "https://plex.tv/link", expiresAtMs: expiry, pollIntervalMs: 2000 } }
    else if action = "pin_poll"
        token = PlexText(PlexField(root, "authToken"))
        if token <> "" then return { ok: true, data: { state: "linked" }, session: { accountToken: token } }
        state = "pending"
        expiry = PlexNumber(PlexField(params, "expiresAtMs"), 0)
        nowMs = PlexNumber(PlexField(params, "nowMs"), 0)
        if expiry > 0 and nowMs > expiry then state = "expired"
        return { ok: true, data: { state: state } }
    else if action = "user"
        accountId = PlexText(PlexField(root, "id"))
        if accountId = "" then return PlexFailure("decode_error", "Plex did not identify the account.")
        name = PlexText(PlexField(root, "username"))
        if name = "" then name = PlexText(PlexField(root, "title"))
        return { ok: true, data: { accountId: accountId, accountName: name } }
    end if
    container = PlexField(root, "MediaContainer")
    if not PlexIsObject(container) then return PlexFailure("decode_error", "Plex returned an unreadable media response.")
    if action = "identity"
        machineId = PlexText(PlexField(container, "machineIdentifier"))
        if machineId = "" then return PlexFailure("decode_error", "The server did not identify itself.")
        expected = PlexText(PlexField(params, "machineId"))
        if expected <> "" and expected <> machineId then return PlexFailure("server_mismatch", "This connection belongs to a different Plex server.")
        return { ok: true, data: { machineId: machineId, sourceId: "plex:" + machineId } }
    else if action = "sections"
        sections = []
        directories = PlexField(container, "Directory")
        if directories <> invalid
            if not PlexIsArray(directories) then return PlexFailure("decode_error", "Plex returned an unreadable library list.")
        end if
        for each directory in PlexArray(directories)
            kind = LCase(PlexText(PlexField(directory, "type")))
            id = PlexText(PlexField(directory, "key"))
            if (kind = "movie" or kind = "show") and PlexIdentifier(id)
                sections.Push({ sourceId: PlexSourceId(params), sectionId: id, title: PlexText(PlexField(directory, "title")), type: kind })
                if sections.Count() >= 24 then exit for
            end if
        end for
        return { ok: true, data: { sections: sections } }
    else if action = "transcode_decision"
        return PlexDecodeDecision(container)
    else if action = "detail"
        metadata = PlexField(container, "Metadata")
        if not PlexIsArray(metadata) then return PlexFailure("decode_error", "Plex returned unreadable item details.")
        if metadata.Count() = 0 then return PlexFailure("not_found", "This item is no longer in the library.")
        item = PlexNormalizeItem(metadata[0], PlexSourceId(params))
        if item = invalid then return PlexFailure("decode_error", "Plex did not identify the item.")
        return { ok: true, data: { item: item, versions: PlexVersions(metadata[0], item), versionsComplete: PlexVersionInventoryComplete(metadata[0]), markers: PlexMarkers(PlexField(metadata[0], "Marker")), cast: PlexCredits(PlexField(metadata[0], "Role"), item["sourceId"], "Acting"), crew: PlexCredits(PlexField(metadata[0], "Director"), item["sourceId"], "Directing"), extras: PlexExtras(PlexField(metadata[0], "Extras"), item["sourceId"]) } }
    else if action = "library_items" or action = "children" or action = "home_continue" or action = "home_on_deck" or action = "search" or action = "section_hubs" or action = "related"
        return PlexDecodeItems(container, action, params)
    end if
    return PlexFailure("unsupported_action", "This Plex response is unavailable.")
end function

function PlexDecodeResources(root as Dynamic, preferredMachineId = "" as String) as Object
    if not PlexIsArray(root) then return PlexFailure("decode_error", "Plex returned an unreadable server list.")
    servers = []
    if preferredMachineId <> ""
        ' A previously visible uncached choice may shift beyond the ordinary
        ' 24-server list before selection. Resolve that exact account resource.
        for each resource in root
            if PlexText(PlexField(resource, "clientIdentifier")) = preferredMachineId
                server = PlexResourceServer(resource)
                if server <> invalid
                    servers.Push(server)
                    exit for
                end if
            end if
        end for
        return {ok: true, data: {servers: servers}}
    end if
    ' The HTTP body is capped before decoding. Prefer owned resources before
    ' applying the 24-server cap, so earlier shared servers cannot hide them.
    ' Two passes retain provider order without allocating an unbounded list.
    for each preferredOwnership in [true, false]
        for each resource in root
            owned = PlexBoolean(PlexField(resource, "owned"))
            if owned = preferredOwnership
                server = PlexResourceServer(resource)
                if server <> invalid then servers.Push(server)
                if servers.Count() >= 24 then exit for
            end if
        end for
        if servers.Count() >= 24 then exit for
    end for
    return { ok: true, data: { servers: servers } }
end function

function PlexResourceServer(resource as Dynamic) as Dynamic
    machineId = PlexText(PlexField(resource, "clientIdentifier"))
    provides = PlexText(PlexField(resource, "provides"))
    if machineId = "" or Instr(1, provides, "server") = 0 then return invalid
    connections = []
    for each connection in PlexArray(PlexField(resource, "connections"))
        local = PlexBoolean(PlexField(connection, "local"))
        base = PlexBaseUrl(PlexField(connection, "uri"), local)
        if base <> "" then connections.Push({baseUrl:base, local:local, relay:PlexBoolean(PlexField(connection,"relay"))})
        if connections.Count() >= 12 then exit for
    end for
    if connections.Count() = 0 then return invalid
    return {sourceId:"plex:" + machineId, machineId:machineId, name:PlexText(PlexField(resource,"name")), token:PlexText(PlexField(resource,"accessToken")), owned:PlexBoolean(PlexField(resource,"owned")), connections:connections}
end function

function PlexDecodeItems(container as Object, action as String, params as Object) as Object
    if action = "children" or action = "library_items" then return PlexDecodeMetadataPage(container, params)
    if action = "section_hubs" then return PlexDecodeSectionHubs(container, params)
    limit = PlexLimit(PlexField(params, "limit"), 24)
    if action = "home_continue" or action = "home_on_deck" then limit = 12
    items = []
    hubs = PlexField(container, "Hub")
    metadata = PlexField(container, "Metadata")
    if metadata <> invalid
        if not PlexIsArray(metadata) then return PlexFailure("decode_error", "Plex returned an unreadable item list.")
    end if
    if hubs <> invalid
        if not PlexIsArray(hubs) then return PlexFailure("decode_error", "Plex returned an unreadable row list.")
    end if
    if PlexIsArray(hubs)
        for each hub in hubs
            kind = LCase(PlexText(PlexField(hub, "type")))
            allowed = true
            if action = "search" or action = "related" then allowed = kind = "movie" or kind = "show" or kind = "episode"
            if allowed
                PlexAppendItems(items, PlexField(hub, "Metadata"), PlexSourceId(params), limit)
                if items.Count() >= limit then exit for
            end if
        end for
    else
        PlexAppendItems(items, metadata, PlexSourceId(params), limit)
    end if
    offset = Int(PlexNumber(PlexField(container, "offset"), 0))
    total = Int(PlexNumber(PlexField(container, "totalSize"), items.Count()))
    data = { items: items, offset: offset, totalSize: total }
    if action = "home_continue" or action = "home_on_deck"
        rowId = "home.continue"
        title = "Continue watching"
        if action = "home_on_deck"
            rowId = "home.ondeck"
            title = "On deck"
        end if
        data["rows"] = []
        if items.Count() > 0 then data.rows.Push({id:rowId,title:title,sourceId:PlexSourceId(params),items:items})
    end if
    return { ok: true, data: data }
end function

' Home follows Android 45774f8b PlexCatalogApi's section order and history
' exclusion. Roku retains two shelves of six cards per section, at most six
' sections, so the whole scene stays below its 100-card presentation budget.
function PlexDecodeSectionHubs(container as Object, params as Object) as Object
    hubs = PlexField(container, "Hub")
    if hubs <> invalid and not PlexIsArray(hubs) then return PlexFailure("decode_error", "Plex returned an unreadable row list.")
    rows = []
    items = []
    seen = {}
    sectionId = PlexText(PlexField(params, "sectionId"))
    if not PlexIdentifier(sectionId) then return PlexFailure("invalid_request", "Choose a library first.")
    ordinal = 0
    for each hub in PlexArray(hubs)
        ordinal++
        if ordinal > 48 or rows.Count() >= 2 then exit for
        if PlexIsObject(hub)
            identifier = PlexText(PlexField(hub, "hubIdentifier"))
            title = Left(PlexText(PlexField(hub, "title")),100)
            markers = LCase(identifier)
            history = Instr(1,markers,"inprogress") > 0 or Instr(1,markers,"ondeck") > 0 or Instr(1,markers,"continue") > 0
            kind = LCase(PlexText(PlexField(hub, "type")))
            if not history and (kind = "movie" or kind = "show" or kind = "episode")
                if not CreateObject("roRegex", "^[A-Za-z0-9._:-]{1,100}$", "").IsMatch(identifier) then identifier = ordinal.ToStr()
                rowId = "plex." + sectionId + "." + identifier
                if not seen.DoesExist(rowId)
                    cards = []
                    PlexAppendItems(cards,PlexField(hub,"Metadata"),PlexSourceId(params),6)
                    if cards.Count() > 0
                        seen[rowId] = true
                        if title = "" then title = "Library"
                        rows.Push({id:rowId,title:title,sourceId:PlexSourceId(params),sectionId:sectionId,items:cards})
                        for each card in cards
                            items.Push(card)
                        end for
                    end if
                end if
            end if
        end if
    end for
    return {ok:true,data:{rows:rows,items:items}}
end function

' Library /all and /children use query ranges (Android ContainerPaging.kt, d849901c).
' Advance by consumed raw slots: filtered items must not overlap the next page.
function PlexDecodeMetadataPage(container as Object, params as Object) as Object
    pageSize = PlexLimit(PlexField(params, "limit"), 24)
    requestedOffset = PlexPageOffset(PlexField(params, "offset"))
    offset = requestedOffset
    reportedOffset = PlexField(container, "offset")
    if reportedOffset <> invalid
        offset = PlexPageInteger(reportedOffset, -1)
        if offset <> requestedOffset then return PlexFailure("page_mismatch", "Plex did not return the requested page.")
    end if
    metadata = PlexField(container, "Metadata")
    if metadata <> invalid
        if not PlexIsArray(metadata) then return PlexFailure("decode_error", "Plex returned an unreadable item list.")
    end if

    items = []
    rawCount = 0
    for each raw in PlexArray(metadata)
        if rawCount >= pageSize then exit for
        rawCount += 1
        item = PlexNormalizeItem(raw, PlexSourceId(params))
        if item <> invalid then items.Push(item)
    end for
    total = PlexPageInteger(PlexField(container, "totalSize"), -1)
    totalKnown = total >= 0
    boundaryOffset = offset + rawCount
    hasMore = false
    if rawCount > 0
        if totalKnown
            hasMore = boundaryOffset < total
        else
            ' Container.size is this page's count, never the complete library/child total.
            hasMore = rawCount = pageSize
        end if
    end if
    nextOffset = -1
    if hasMore then nextOffset = boundaryOffset
    if not totalKnown then total = boundaryOffset
    return {ok: true, data: {items: items, offset: offset, pageSize: pageSize, rawCount: rawCount, totalSize: total, totalKnown: totalKnown, hasMore: hasMore, nextOffset: nextOffset}}
end function

function PlexPageOffset(value as Dynamic) as Integer
    offset = PlexNumber(value, 0)
    if offset < 0 then return 0
    ' Leave room for a complete 48-item window in the Roku integer range.
    if offset > 2147483599 then return 2147483599
    return Int(offset)
end function

function PlexPageInteger(value as Dynamic, fallback as Integer) as Integer
    kind = Type(value)
    if kind = "String" or kind = "roString"
        if not CreateObject("roRegex", "^[0-9]+$", "").IsMatch(value.Trim()) then return fallback
    else if kind <> "Integer" and kind <> "LongInteger" and kind <> "Float" and kind <> "Double" and kind <> "roInt" and kind <> "roInteger" and kind <> "roLongInteger" and kind <> "roFloat" and kind <> "roDouble"
        return fallback
    end if
    number = PlexNumber(value, fallback)
    if number < 0 or number > 2147483647 then return fallback
    if Int(number) <> number then return fallback
    return Int(number)
end function

sub PlexAppendItems(items as Object, metadata as Dynamic, sourceId as String, limit as Integer)
    for each raw in PlexArray(metadata)
        if items.Count() >= limit then exit for
        item = PlexNormalizeItem(raw, sourceId)
        if item <> invalid then items.Push(item)
    end for
end sub

function PlexNormalizeItem(raw as Dynamic, sourceId as String) as Dynamic
    itemId = PlexText(PlexField(raw, "ratingKey"))
    kind = LCase(PlexText(PlexField(raw, "type")))
    extraType = ""
    if kind = "clip"
        ' Plex trailers/featurettes have their own native rating key and media.
        ' A detail fetch resolves them through the same movie playback route.
        extraType = PlexText(PlexField(raw, "subtype"))
        if extraType = "" then extraType = "clip"
        kind = "movie"
    end if
    if not PlexIdentifier(itemId) then return invalid
    if kind <> "movie" and kind <> "show" and kind <> "season" and kind <> "episode" then return invalid
    thumb = PlexSafeKey(PlexField(raw, "thumb"))
    if kind = "episode"
        seriesThumb = PlexSafeKey(PlexField(raw, "grandparentThumb"))
        if seriesThumb <> "" then thumb = seriesThumb
    end if
    parentId = PlexText(PlexField(raw, "parentRatingKey"))
    seriesId = PlexText(PlexField(raw, "grandparentRatingKey"))
    if not PlexIdentifier(parentId) then parentId = ""
    if not PlexIdentifier(seriesId) then seriesId = ""
    seasonId = ""
    seriesTitle = PlexText(PlexField(raw, "grandparentTitle"))
    seasonNumber = PlexNumber(PlexField(raw, "parentIndex"), 0)
    episodeNumber = PlexNumber(PlexField(raw, "index"), 0)
    if kind = "episode" then seasonId = parentId
    if kind = "season"
        seriesId = parentId
        seasonId = itemId
        seriesTitle = PlexText(PlexField(raw, "parentTitle"))
        seasonNumber = PlexNumber(PlexField(raw, "index"), 0)
        episodeNumber = 0
    end if
    item = {
        provider: "plex", sourceId: sourceId, itemId: itemId
        title: PlexText(PlexField(raw, "title")), type: kind
        summary: PlexText(PlexField(raw, "summary")), thumbKey: thumb
        backdropKey: PlexSafeKey(PlexField(raw, "art"))
        durationMs: PlexNumber(PlexField(raw, "duration"), 0)
        resumeMs: PlexNumber(PlexField(raw, "viewOffset"), 0)
        year: PlexNumber(PlexField(raw, "year"), 0)
        seriesTitle: seriesTitle, seriesItemId: seriesId
        parentItemId: parentId, seasonItemId: seasonId
        seasonNumber: seasonNumber, episodeNumber: episodeNumber
        guids: PlexGuids(raw)
    }
    codecs = []
    for each key in raw.Keys()
        if key = "Media" or key = "media"
            for each media in PlexArray(raw[key])
                codec = Left(PlexText(PlexField(media,"videoCodec")),32)
                if codec <> "" and codecs.Count() < 16 then codecs.Push(codec)
            end for
        end if
    end for
    if codecs.Count() > 0 then item["badges"] = {videoCodecs:codecs}
    if extraType <> "" then item["extraType"] = extraType
    viewCount = PlexField(raw, "viewCount")
    if viewCount <> invalid then item.watched = PlexNumber(viewCount, 0) > 0
    return item
end function

function PlexGuids(raw as Dynamic) as Object
    guids = []
    legacy = PlexText(PlexExactField(raw, "guid"))
    if PlexValidGuid(legacy) then guids.Push(legacy)
    for each entry in PlexArray(PlexExactField(raw, "Guid"))
        if guids.Count() >= 16 then exit for
        guid = PlexText(PlexField(entry, "id"))
        if PlexValidGuid(guid)
            duplicate = false
            for each existing in guids
                if existing = guid then duplicate = true
            end for
            if not duplicate then guids.Push(guid)
        end if
    end for
    return guids
end function

function PlexValidGuid(guid as String) as Boolean
    if Len(guid) > 256 then return false
    return CreateObject("roRegex", "^plex://(movie|show|season|episode)/[A-Za-z0-9_-]+$|^(tmdb|tvdb)://[0-9]+$|^imdb://tt[0-9]+$", "i").IsMatch(guid)
end function

function PlexExactField(value as Dynamic, key as String) as Dynamic
    if not PlexIsObject(value) then return invalid
    ' PMS can include both scalar guid and array Guid. Preserve exact JSON keys
    ' across Roku ParseJson and the interpreter's documented JSON bridge.
    value.SetModeCaseSensitive()
    return value.Lookup(key)
end function

function PlexCredits(raw as Dynamic, sourceId as String, department as String) as Object
    credits = []
    for each person in PlexArray(raw)
        name = PlexText(PlexField(person, "tag"))
        if name <> ""
            personId = PlexText(PlexField(person, "id"))
            if not PlexIdentifier(personId) then personId = ""
            credits.Push({ sourceId: sourceId, personId: personId, name: name, role: PlexText(PlexField(person, "role")), department: department, thumbKey: PlexSafeKey(PlexField(person, "thumb")) })
            if credits.Count() >= 32 then exit for
        end if
    end for
    return credits
end function

function PlexExtras(raw as Dynamic, sourceId as String) as Object
    extras = []
    PlexAppendItems(extras, PlexField(raw, "Metadata"), sourceId, 24)
    return extras
end function

' Replacement identity requires every physical row to fit the 16-row bound.
' Ordinary playback keeps its existing bounded version list.
function PlexVersionInventoryComplete(raw as Object) as Boolean
    count=0
    for each key in raw.Keys()
        if key="Media" or key="media"
            mediaList=PlexArray(raw[key])
            if mediaList.Count()>16 then return false
            for each media in mediaList
                count+=PlexArray(PlexField(media,"Part")).Count()
                if count>16 then return false
            end for
        end if
    end for
    return true
end function

function PlexVersions(raw as Object, item as Object) as Object
    versions = []
    ' Roku JSON arrays preserve case: the two spellings can coexist.
    ' Inspect exact keys so an emulator using case-insensitive AAs does not
    ' append the same array twice when only one spelling exists.
    upperMedia = invalid
    lowerMedia = invalid
    for each rawKey in raw.Keys()
        if rawKey = "Media" then upperMedia = raw[rawKey]
        if rawKey = "media" then lowerMedia = raw[rawKey]
    end for
    mediaList = []
    for each media in PlexArray(upperMedia)
        mediaList.Push(media)
    end for
    for each media in PlexArray(lowerMedia)
        mediaList.Push(media)
    end for
    mediaIndex = 0
    for each media in PlexArray(mediaList)
        partIndex = 0
        for each part in PlexArray(PlexField(media, "Part"))
            mediaId = PlexText(PlexField(media, "id"))
            partId = PlexText(PlexField(part, "id"))
            if PlexIdentifier(mediaId) and PlexIdentifier(partId)
                container = LCase(PlexText(PlexField(part, "container")))
                if container = "" then container = LCase(PlexText(PlexField(media, "container")))
                version = {
                    sourceId: item["sourceId"], itemId: item["itemId"]
                    versionId: item["sourceId"] + ":" + item["itemId"] + ":" + mediaId + ":" + partId
                    mediaId: mediaId, partId: partId, mediaIndex: mediaIndex, partIndex: partIndex, partCount:PlexArray(PlexField(media,"Part")).Count()
                    partKey: PlexPartKey(PlexField(part, "key")), container: container
                    videoCodec: LCase(PlexText(PlexField(media, "videoCodec")))
                    audioCodec: LCase(PlexText(PlexField(media, "audioCodec")))
                    audioChannels: PlexNumber(PlexField(media, "audioChannels"), 0)
                    width: PlexNumber(PlexField(media, "width"), 0), height: PlexNumber(PlexField(media, "height"), 0)
                    bitrateKbps: PlexNumber(PlexField(media, "bitrate"), 0)
                    durationMs: PlexNumber(PlexField(part, "duration"), item["durationMs"])
                    audio: [], subtitles: []
                }
                for each stream in PlexArray(PlexField(part, "Stream"))
                    streamType = PlexNumber(PlexField(stream, "streamType"), 0)
                    track = { id: PlexText(PlexField(stream, "id")), codec: LCase(PlexText(PlexField(stream, "codec"))), channels: PlexNumber(PlexField(stream, "channels"), 0), title: PlexText(PlexField(stream, "displayTitle")), language: PlexText(PlexField(stream, "languageCode")), selected: PlexBoolean(PlexField(stream, "selected")), default: PlexBoolean(PlexField(stream, "default")), forced: PlexBoolean(PlexField(stream, "forced")), key: PlexSafeKey(PlexField(stream, "key")) }
                    if track.language = "" then track.language = PlexText(PlexField(stream, "language"))
                    if streamType = 2 and version.audio.Count() < 32 then version.audio.Push(track)
                    if streamType = 3 and version.subtitles.Count() < 32 then version.subtitles.Push(track)
                end for
                versions.Push(version)
                if versions.Count() >= 16 then return versions
            end if
            partIndex += 1
        end for
        mediaIndex += 1
    end for
    return versions
end function

function PlexMarkers(raw as Dynamic) as Object
    markers = []
    for each marker in PlexArray(raw)
        startMs = PlexNumber(PlexField(marker, "startTimeOffset"), -1)
        endMs = PlexNumber(PlexField(marker, "endTimeOffset"), -1)
        if startMs >= 0 and endMs > startMs
            markers.Push({ type: PlexText(PlexField(marker, "type")), startMs: startMs, endMs: endMs, isFinal: PlexBoolean(PlexField(marker, "final")) })
            if markers.Count() >= 32 then exit for
        end if
    end for
    return markers
end function

function PlexDirectPlan(detail as Object, mediaIndex as Integer, partIndex as Integer, session as Object) as Object
    item = PlexField(detail, "item")
    if not PlexIsObject(item) then return PlexFailure("resolve_error", "Reload this item before playing.")
    sourceId = PlexText(PlexField(session, "sourceId"))
    if sourceId <> "" and sourceId <> item["sourceId"] then return PlexFailure("source_mismatch", "Select this item's Plex server before playing.")
    selected = invalid
    for each version in PlexArray(PlexField(detail, "versions"))
        if version["mediaIndex"] = mediaIndex and version["partIndex"] = partIndex then selected = version
    end for
    if selected = invalid then return PlexFailure("resolve_error", "This media version is no longer available.")
    key = PlexPartKey(selected["partKey"])
    base = PlexBaseUrl(PlexField(session, "baseUrl"), PlexBoolean(PlexField(session, "local")))
    token = PlexText(PlexField(session, "token"))
    if key = "" or base = "" then return PlexFailure("resolve_error", "Plex did not provide a safe media route.")
    if token = "" then return PlexFailure("auth_required", "Sign in to Plex to play this item.")
    audioCodec = selected["audioCodec"]
    audioChannels = selected["audioChannels"]
    audio = invalid
    for each track in selected.audio
        if audio = invalid then audio = track
        if track.selected or track.default
            audio = track
            exit for
        end if
    end for
    if audio <> invalid
        audioCodec = audio.codec
        audioChannels = audio.channels
    end if
    return { ok: true, provider: "plex", sourceId: item["sourceId"], itemId: item["itemId"], versionId: selected["versionId"], url: base + key, headers: PlexHeaders(session, true), streamFormat: selected.container, container: selected.container, delivery: "direct_play", videoCodec: selected["videoCodec"], audioCodec: audioCodec, audioChannels: audioChannels, width: selected.width, height: selected.height, bitrateKbps: selected["bitrateKbps"], durationMs: selected["durationMs"], startPositionMs: item["resumeMs"], mediaIndex: mediaIndex, partIndex: partIndex, audio: selected.audio, subtitles: selected.subtitles }
end function

function PlexTranscodePlan(request as Object, session as Object, detail as Object, mediaIndex as Integer, partIndex as Integer) as Object
    if not PlexBoolean(PlexField(request, "ok")) then return PlexFailure("resolve_error", "Plex did not provide a playback request.")
    url = PlexText(PlexField(request, "url"))
    base = PlexBaseUrl(PlexField(session, "baseUrl"), PlexBoolean(PlexField(session, "local")))
    prefix = base + "/video/:/transcode/universal/start.m3u8?"
    if base = "" or Left(url, Len(prefix)) <> prefix then return PlexFailure("resolve_error", "Plex did not provide a matching playback route.")
    if Instr(1, LCase(url), "x-plex-token=") > 0 then return PlexFailure("resolve_error", "Plex did not provide a safe playback route.")
    plan = PlexDirectPlan(detail, mediaIndex, partIndex, session)
    if not plan.ok then return plan
    if PlexQueryValue(url, "path") <> "/library/metadata/" + plan["itemId"] then return PlexFailure("resolve_error", "Plex returned a route for a different item.")
    if PlexQueryValue(url, "mediaIndex") <> mediaIndex.ToStr() or PlexQueryValue(url, "partIndex") <> partIndex.ToStr() then return PlexFailure("resolve_error", "Plex returned a route for a different media version.")
    offsetSeconds = PlexQueryValue(url, "offset")
    if offsetSeconds <> "" and offsetSeconds <> "0" then return PlexFailure("resolve_error", "Plex did not provide a canonical playback route.")
    plan.url = url
    plan["streamFormat"] = "hls"
    plan.container = "mpegts"
    plan.delivery = "transcode"
    plan["originalResumeMs"] = plan["startPositionMs"]
    plan["timelineOffsetMs"] = 0
    plan["relativeTimeline"] = false
    ' The decision response supplies output codecs; original-file codec fields
    ' cannot establish the HLS output's decode requirements.
    plan["videoCodec"] = ""
    plan["audioCodec"] = ""
    plan["audioChannels"] = 0
    return plan
end function

function PlexQueryValue(url as String, name as String) as String
    queryStart = Instr(1, url, "?")
    if queryStart = 0 then return ""
    query = Mid(url, queryStart + 1)
    prefix = name + "="
    for each pair in query.Split("&")
        if Left(pair, Len(prefix)) = prefix
            encoded = Mid(pair, Len(prefix) + 1)
            return encoded.DecodeUriComponent()
        end if
    end for
    return ""
end function

function PlexDecodeDecision(container as Object) as Object
    code = PlexNumber(PlexField(container, "generalDecisionCode"), 0)
    if code >= 2000 and code <= 2999 then return PlexFailure("plex_decision_refused", "Plex cannot deliver this item for these playback capabilities.")
    decision = LCase(PlexText(PlexField(container, "videoDecision")))
    delivery = "unknown"
    if decision = "copy" or decision = "direct" or decision = "directplay" or decision = "directstream" then delivery = "direct_stream"
    if decision = "transcode" then delivery = "transcode"
    return { ok: true, data: { delivery: delivery, videoDecision: decision, audioDecision: PlexText(PlexField(container, "audioDecision")), container: PlexText(PlexField(container, "container")), videoCodec: PlexText(PlexField(container, "videoCodec")), audioCodec: PlexText(PlexField(container, "audioCodec")), audioChannels: PlexNumber(PlexField(container, "audioChannels"), 0), width: PlexNumber(PlexField(container, "width"), 0), height: PlexNumber(PlexField(container, "height"), 0), bitrateKbps: PlexNumber(PlexField(container, "bitrate"), 0), generalDecisionCode: code } }
end function

function PlexHeaders(session as Object, authenticated as Boolean) as Object
    osVersion = PlexText(PlexField(session, "platformVersion"))
    if osVersion = "" then osVersion = PlexText(PlexField(session, "osVersion"))
    headers = { "Accept": "application/json", "X-Plex-Client-Identifier": PlexText(PlexField(session, "clientId")), "X-Plex-Product": "Silo", "X-Plex-Version": "0.1.0", "X-Plex-Platform": "Roku", "X-Plex-Platform-Version": osVersion, "X-Plex-Device": "Roku", "X-Plex-Device-Name": "Silo Roku", "X-Plex-Model": PlexText(PlexField(session, "model")), "X-Plex-Provides": "player,timeline" }
    if authenticated
        token = PlexText(PlexField(session, "token"))
        if token = "" then token = PlexText(PlexField(session, "accountToken"))
        if token <> "" then headers["X-Plex-Token"] = token
    end if
    return headers
end function

function PlexFailure(code as String, message as String) as Object
    return { ok: false, errorCode: code, message: message }
end function

function PlexSourceId(params as Object) as String
    source = PlexText(PlexField(params, "sourceId"))
    if source = "" then source = "plex"
    return source
end function

function PlexField(value as Dynamic, key as String) as Dynamic
    if PlexIsObject(value) then return value[key]
    return invalid
end function

function PlexIsObject(value as Dynamic) as Boolean
    return Type(value) = "roAssociativeArray"
end function

function PlexIsArray(value as Dynamic) as Boolean
    return Type(value) = "roArray"
end function

function PlexArray(value as Dynamic) as Object
    if PlexIsArray(value) then return value
    return []
end function

function PlexText(value as Dynamic) as String
    kind = Type(value)
    if kind = "String" or kind = "roString" then return value.Trim()
    if kind = "Integer" or kind = "LongInteger" or kind = "roInt" or kind = "roInteger" or kind = "roLongInteger" then return value.ToStr()
    return ""
end function

function PlexNumber(value as Dynamic, fallback as Double) as Double
    kind = Type(value)
    if kind = "Integer" or kind = "LongInteger" or kind = "Float" or kind = "Double" or kind = "roInt" or kind = "roInteger" or kind = "roLongInteger" or kind = "roFloat" or kind = "roDouble" then return value
    if kind = "String" or kind = "roString" then return Val(value)
    return fallback
end function

function PlexBoolean(value as Dynamic) as Boolean
    if Type(value) = "Boolean" or Type(value) = "roBoolean" then return value
    return PlexNumber(value, 0) = 1
end function

function PlexLimit(value as Dynamic, fallback as Integer) as Integer
    count = Int(PlexNumber(value, fallback))
    if count < 1 then count = 1
    if count > 48 then count = 48
    return count
end function

function PlexIdentifier(value as String) as Boolean
    return CreateObject("roRegex", "^[A-Za-z0-9_-]+$", "").IsMatch(value)
end function

function PlexBaseUrl(value as Dynamic, local as Boolean) as String
    base = PlexText(value)
    if not CreateObject("roRegex", "^https?://[^/?#@\s]+(/[^?#@\s]*)?$", "i").IsMatch(base) then return ""
    if LCase(Left(base, 7)) = "http://" and not local then return ""
    while Right(base, 1) = "/"
        base = Left(base, Len(base) - 1)
    end while
    return base
end function

function PlexSafeKey(value as Dynamic) as String
    key = PlexText(value)
    if Left(key, 9) <> "/library/" then return ""
    if Instr(1, key, "?") > 0 or Instr(1, key, "#") > 0 or Instr(1, key, "..") > 0 or Instr(1, key, "\") > 0 then return ""
    return key
end function

function PlexPartKey(value as Dynamic) as String
    key = PlexSafeKey(value)
    if Left(key, 15) <> "/library/parts/" then return ""
    return key
end function
