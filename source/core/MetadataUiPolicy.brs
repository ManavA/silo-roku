' Pure discovery UI policy. Load with MetadataAdapter.brs for normalized identity
' helpers and MatchMetadataOwnedItem; global IDs never enter provider itemId.
function UiMetadataEntries(data as Dynamic, limit = 100 as Integer) as Object
    output = []
    seen = {}
    limit = HmLimit(limit, 100, 100)
    rows = HmField(data, "rows")
    if type(rows) = "roArray"
        inspected = 0
        for each row in rows
            inspected++
            if inspected > 50 or output.Count() >= limit then exit for
            HmUiAppendEntries(output, seen, HmField(row, "items"), HmText(HmField(row, "title"), 120), limit)
        end for
    else
        HmUiAppendEntries(output, seen, HmField(data, "items"), "", limit)
    end if
    return output
end function

sub HmUiAppendEntries(output as Object, seen as Object, values as Dynamic, rowTitle as String, limit as Integer)
    if type(values) <> "roArray" then return
    inspected = 0
    for each raw in values
        inspected++
        if inspected > 180 or output.Count() >= limit then exit for
        item = HmUiSeed(raw)
        if item <> invalid and not seen.DoesExist(item.catalogId)
            item["rowTitle"] = rowTitle
            seen[item.catalogId] = true
            output.Push(item)
        end if
    end for
end sub

function HmUiSeed(raw as Dynamic) as Dynamic
    if HmText(HmField(raw, "provider"), 20) <> "metadata" then return invalid
    kind = HmKind(HmField(raw, "type"))
    title = HmText(HmField(raw, "title"), 120)
    ids = HmIds(raw)
    identity = ids.tmdbId
    if identity = "" and ids.imdbId <> "" then identity = "imdb:" + ids.imdbId
    if identity = "" and ids.tvdbId <> "" then identity = "tvdb:" + ids.tvdbId
    if kind = "" or title = "" or identity = "" then return invalid
    item = {provider: "metadata", catalogId: "metadata:" + kind + ":" + identity, title: title, type: kind, tmdbId: ids.tmdbId, imdbId: ids.imdbId, tvdbId: ids.tvdbId, owned: false, canPlay: false, availability: "unresolved", year: HmUiYear(HmField(raw, "year")), summary: HmText(HmField(raw, "summary"), 2000), thumbKey: HmUiArtwork(HmField(raw, "thumbKey")), backdropKey: HmUiArtwork(HmField(raw, "backdropKey"))}
    return item
end function

function HmUiArtwork(raw as Dynamic) as String
    value = HmText(raw, 1024)
    pattern = "^https://image[.]tmdb[.]org/t/p/(w342|w780)/[A-Za-z0-9_-]+[.](jpg|jpeg|png|webp)$"
    if CreateObject("roRegex", pattern, "i").IsMatch(value) then return value
    return ""
end function

function HmUiYear(raw as Dynamic) as Integer
    year = HmNumber(raw, 0)
    if year < 1880 or year > 3000 or year <> Int(year) then return 0
    return Int(year)
end function

function UiMetadataSearchRequest(seed as Dynamic, provider as String, sourceId as String) as Object
    if not HmUiProviderScope(provider, sourceId) then return HmUiError("invalid_source")
    item = HmUiSeed(seed)
    if item = invalid then return HmUiError("invalid_seed")
    params = {query: item.title, limit: 100}
    action = "search"
    if provider = "silo"
        action = "catalog_query"
        kind = "movie"
        if item.type = "show" then kind = "series"
        params["type"] = kind
    end if
    return {ok: true, state: "search_required", action: action, params: params}
end function

' Resolve only this search page. A missing match does not prove library absence.
' Silo summaries without a comparable external namespace need their own Detail.
function UiMetadataResolveOwnedSearch(seed as Dynamic, provider as String, sourceId as String, data as Dynamic) as Object
    if not HmUiProviderScope(provider, sourceId) then return HmUiError("invalid_source")
    item = HmUiSeed(seed)
    if item = invalid then return HmUiError("invalid_seed")
    values = HmField(data, "items")
    if type(values) <> "roArray" then return HmUiError("invalid_response")
    candidates = UiMetadataLibraryCandidates(values, sourceId, 100)
    owned = MatchMetadataOwnedItem(item, candidates, sourceId)
    if owned <> invalid
        owned["provider"] = provider
        return {ok: true, state: "owned", item: owned}
    end if
    hydration = []
    if provider = "silo"
        wanted = HmIds(item)
        for each candidate in candidates
            if hydration.Count() >= 12 then exit for
            if candidate.type = item.type
                ids = HmIds(candidate)
                comparable = false
                for each namespace in ["tmdbId", "imdbId", "tvdbId"]
                    if wanted[namespace] <> "" and ids[namespace] <> "" then comparable = true
                end for
                if not comparable then hydration.Push(candidate)
            end if
        end for
    end if
    if hydration.Count() > 0 then return {ok: true, state: "needs_detail_hydration", hydrationCandidates: hydration}
    return {ok: true, state: "not_in_search_page"}
end function

' Safe active-library input for AVA. BuildMetadataRequest removes native IDs from
' the actual request body. No artwork, transport headers or URLs survive here.
function UiMetadataLibraryCandidates(items as Dynamic, sourceId as String, limit = 180 as Integer) as Object
    output = []
    seen = {}
    if not HmOwnedSource(sourceId) or type(items) <> "roArray" then return output
    provider = Left(sourceId, 4)
    limit = HmLimit(limit, 180, 180)
    inspected = 0
    for each raw in items
        inspected++
        if inspected > 1000 or output.Count() >= limit then exit for
        candidate = HmUiOwnedCard(raw, provider, sourceId)
        if candidate <> invalid and not seen.DoesExist(candidate.itemId)
            seen[candidate.itemId] = true
            output.Push(candidate)
        end if
    end for
    return output
end function

function HmUiOwnedCard(raw as Dynamic, provider as String, sourceId as String) as Dynamic
    if not HmIsOwned(raw, sourceId) then return invalid
    statedProvider = HmText(HmField(raw, "provider"), 20)
    if statedProvider <> "" and statedProvider <> provider then return invalid
    itemId = HmText(HmField(raw, "itemId"), 256)
    pattern = "^[A-Za-z0-9_.:-]{1,256}$"
    if provider = "plex" then pattern = "^[0-9]{1,128}$"
    if not CreateObject("roRegex", pattern, "").IsMatch(itemId) then return invalid
    kind = HmKind(HmField(raw, "type"))
    if provider = "silo" and HmText(HmField(raw, "type"), 20) = "series" then kind = "show"
    title = HmText(HmField(raw, "title"), 120)
    if kind = "" or title = "" then return invalid
    ids = HmIds(raw)
    result = {provider: provider, sourceId: sourceId, itemId: itemId, title: title, type: kind, year: HmUiYear(HmField(raw, "year")), tmdbId: ids.tmdbId, imdbId: ids.imdbId, tvdbId: ids.tvdbId, owned: true, genres: HmStrings(HmField(raw, "genres"), 8, 80)}
    for each field in ["durationMs", "resumeMs"]
        number = HmNumber(HmField(raw, field), 0)
        if number < 0 or number > 86400000 then number = 0
        result[field] = number
    end for
    watched = HmField(raw, "watched")
    if type(watched) = "Boolean" or type(watched) = "roBoolean" then result["watched"] = watched
    rating = HmNumber(HmField(raw, "rating"), -1)
    if rating >= 0 and rating <= 10 then result["rating"] = rating
    return result
end function

function HmUiProviderScope(provider as String, sourceId as String) as Boolean
    if provider <> "plex" and provider <> "silo" then return false
    return Left(sourceId, 5) = provider + ":" and Len(sourceId) > 5
end function

function HmUiError(code as String) as Object
    return {ok: false, state: code, errorCode: code}
end function
