' Plex Discover Universal Watchlist, from SiloShared MetadataServerClient.swift.
' This is an account service; its IDs must never become server playback rating keys.
' Pure builders/decoders only. The caller checks HTTP success before decoding.

function PlexWatchlistNeedsAccountLookup(session as Object) as Boolean
    return PwText(PwInputField(session, "accountToken")) <> "" and PwText(PwInputField(session, "accountId")) = ""
end function

function BuildPlexWatchlistRequest(action as String, session as Object, params as Object) as Object
    if action <> "watchlist" and action <> "watchlist_add" and action <> "watchlist_remove" then return PwFailure("unsupported_action")
    accountToken = PwText(PwInputField(session, "accountToken"))
    clientId = PwText(PwInputField(session, "clientId"))
    if accountToken = "" then return PwFailure("auth_required")
    if clientId = "" then return PwFailure("client_identity_missing")
    headers = {"Accept": "application/json", "X-Plex-Token": accountToken, "X-Plex-Client-Identifier": clientId, "X-Plex-Product": "Silo", "X-Plex-Device": "Roku", "X-Plex-Platform": "Roku"}
    request = {ok: true, method: "GET", url: "https://discover.provider.plex.tv", headers: headers, body: ""}
    if action = "watchlist"
        offset = Int(PwNumber(PwInputField(params, "offset"), 0))
        if offset < 0 then offset = 0
        request.headers["X-Plex-Container-Start"] = offset.ToStr()
        request.headers["X-Plex-Container-Size"] = PwLimit(PwInputField(params, "limit")).ToStr()
        request.url += "/library/sections/watchlist/all?includeCollections=1&includeExternalMedia=1&includeGuids=1&includeMeta=1&includeImages=1&sort=watchlistedAt%3Adesc"
    else
        ratingKey = PwText(PwInputField(params, "watchlistRatingKey"))
        if ratingKey = "" then ratingKey = PlexWatchlistRatingKeyFromGuid(PwText(PwInputField(params, "plexGuid")))
        if not PwIdentifier(ratingKey) then return PwFailure("watchlist_identity_required")
        request.method = "PUT"
        path = "/actions/addToWatchlist"
        if action = "watchlist_remove" then path = "/actions/removeFromWatchlist"
        request.url += path + "?ratingKey=" + ratingKey.EncodeUriComponent()
    end if
    return request
end function

function DecodePlexWatchlistResponse(action as String, body as String, params as Object) as Object
    if action = "watchlist_add" or action = "watchlist_remove" then return {ok: true, data: {inWatchlist: action = "watchlist_add"}}
    if action <> "watchlist" then return PwFailure("unsupported_action")
    accountId = PwText(PwInputField(params, "accountId"))
    if not PwIdentifier(accountId) then return PwFailure("account_identity_required")
    root = ParseJson(body)
    container = PwField(root, "MediaContainer")
    metadata = PwField(container, "Metadata")
    if type(container) <> "roAssociativeArray" or type(metadata) <> "roArray" then return PwFailure("invalid_response")
    offset = Int(PwNumber(PwInputField(params, "offset"), 0))
    if offset < 0 then offset = 0
    limit = PwLimit(PwInputField(params, "limit"))
    sourceCount = metadata.Count()
    if sourceCount > limit then sourceCount = limit
    items = []
    seen = {}
    for index = 0 to sourceCount - 1
        item = PwNormalizeItem(metadata[index], "plex-watchlist:" + accountId)
        if item <> invalid
            if not seen.DoesExist(item.itemId)
                seen[item.itemId] = true
                items.Push(item)
            end if
        end if
    end for
    total = Int(PwNumber(PwField(container, "totalSize"), PwNumber(PwField(container, "size"), -1)))
    nextOffset = offset + sourceCount
    hasMore = sourceCount > 0 and nextOffset < total
    if total < 0 then hasMore = sourceCount >= limit
    return {ok: true, data: {items: items, offset: offset, sourceCount: sourceCount, nextOffset: nextOffset, totalSize: total, hasMore: hasMore}}
end function

function PwNormalizeItem(raw as Dynamic, sourceId as String) as Dynamic
    if type(raw) <> "roAssociativeArray" then return invalid
    kind = PwText(PwField(raw, "type"))
    if kind <> "movie" and kind <> "show" then return invalid
    canonical = PwText(PwField(raw, "guid"))
    ratingKey = PlexWatchlistRatingKeyFromGuid(canonical)
    if ratingKey = ""
        canonical = ""
        ratingKey = PwText(PwField(raw, "ratingKey"))
    end if
    if not PwIdentifier(ratingKey) then return invalid
    guids = []
    externalIds = {}
    if canonical <> "" then guids.Push(canonical)
    rawGuids = PwField(raw, "Guid")
    if type(rawGuids) = "roArray"
        for each entry in rawGuids
            if guids.Count() >= 16 then exit for
            guid = PwText(PwField(entry, "id"))
            expression = CreateObject("roRegex", "^(tmdb|tvdb)://([0-9]+)$|^(imdb)://(tt[0-9]+)$", "i")
            if expression.IsMatch(guid)
                parts = guid.Tokenize(":/")
                if parts.Count() = 2
                    provider = LCase(parts[0])
                    if not externalIds.DoesExist(provider)
                        externalIds[provider] = parts[1]
                        guids.Push(guid)
                    end if
                end if
            end if
        end for
    end if
    title = PwText(PwField(raw, "title"))
    if title = "" then title = "Untitled"
    return {provider: "plex", sourceId: sourceId, itemId: "plex-watchlist:" + kind + ":" + ratingKey, title: title, type: kind, summary: PwText(PwField(raw, "summary")), year: PwNumber(PwField(raw, "year"), 0), watchlistRatingKey: ratingKey, plexGuid: canonical, guids: guids, externalIds: externalIds, inWatchlist: true, owned: false, canPlay: false, availability: "unresolved"}
end function

function PlexWatchlistRatingKeyFromGuid(guid as String) as String
    expression = CreateObject("roRegex", "^plex://(movie|show)/([A-Za-z0-9_-]+)$", "i")
    matched = expression.Match(guid)
    if matched.Count() <> 3 then return ""
    return matched[2]
end function

function PwIdentifier(value as String) as Boolean
    if Len(value) = 0 or Len(value) > 128 then return false
    return CreateObject("roRegex", "^[A-Za-z0-9_-]+$", "").IsMatch(value)
end function

function PwField(value as Dynamic, key as String) as Dynamic
    if type(value) <> "roAssociativeArray" then return invalid
    ' Plex carries both scalar "guid" and array "Guid" in the same object.
    value.SetModeCaseSensitive()
    return value.Lookup(key)
end function

function PwInputField(value as Dynamic, key as String) as Dynamic
    if type(value) <> "roAssociativeArray" then return invalid
    return value.LookupCI(key)
end function

function PwText(value as Dynamic) as String
    if type(value) = "String" or type(value) = "roString" then return value
    if type(value) = "Integer" or type(value) = "roInt" or type(value) = "roInteger" or type(value) = "LongInteger" or type(value) = "roLongInteger" then return value.ToStr()
    return ""
end function

function PwNumber(value as Dynamic, fallback as Double) as Double
    kind = type(value)
    if kind = "Integer" or kind = "roInt" or kind = "roInteger" or kind = "LongInteger" or kind = "roLongInteger" or kind = "Float" or kind = "roFloat" or kind = "Double" or kind = "roDouble" then return value
    return fallback
end function

function PwLimit(value as Dynamic) as Integer
    count = Int(PwNumber(value, 48))
    if count < 1 then count = 1
    if count > 100 then count = 100
    return count
end function

function PwFailure(code as String) as Object
    return {ok: false, errorCode: code}
end function
