' Public Metadata /v1 contract: Android d849901c760e1105d8623b6832c55576ef069bc2,
' plus the inspected server AvaRecommendationRoutes/ServiceCatalogRoutes models.
' Global catalog identity never becomes a provider item ID. Keep provider auth out
' of this adapter; only minimal active-library facts go into the AVA POST body.

function BuildMetadataRequest(action as String, config as Object, params as Object) as Object
    base = HmField(config, "baseUrl")
    if base = invalid then base = ""
    if type(base) <> "String" and type(base) <> "roString" then return HmFailure("invalid_server")
    if Len(base) > 1024 then return HmFailure("invalid_server")
    if base = "" then return HmFailure("metadata_disabled")
    base = HmBaseUrl(base)
    if base = "" then return HmFailure("invalid_server")
    version = HmText(HmField(config, "appVersion"), 40)
    if not CreateObject("roRegex", "^[A-Za-z0-9._-]{1,40}$", "").IsMatch(version) then version = "unknown"
    request = {ok: true, method: "GET", url: "", headers: {Accept: "application/json", "X-Silo-Client": "roku/" + version}, body: "", timeoutMs: 10000}
    if action = "metadata_artwork"
        kind = HmText(HmField(params,"type"),10)
        identifier = HmNumericId(HmField(params,"tmdbId"))
        if (kind <> "movie" and kind <> "tv") or identifier = "" then return HmFailure("invalid_request")
        request.url = base + "/v1/enrich/" + kind + "/" + identifier
        request["timeoutMs"] = 4000
    else if action = "home_rows" or action = "service_catalog"
        path = "/v1/catalog/home/rows"
        if action = "service_catalog"
            slug = HmText(HmField(params, "slug"), 100)
            if not CreateObject("roRegex", "^[a-z0-9][a-z0-9-]{0,63}$", "").IsMatch(slug) then return HmFailure("invalid_request")
            path = "/v1/catalog/service/" + slug
        end if
        mode = HmText(HmField(params, "mode"), 20)
        query = "?v=20260814-showcase-v7"
        if action = "home_rows" then query += "&format=compact"
        if mode = "cache_only"
            query += "&cacheOnly=1"
        else if mode = "refresh"
            query += "&refresh=1"
            request["timeoutMs"] = 12000
        else if mode <> "" and mode <> "live"
            return HmFailure("invalid_request")
        end if
        request.url = base + path + query
    else if action = "discover_trending"
        page = HmTrendingPage(HmField(params, "page"))
        request.url = base + "/v1/trending/all/week?page=" + page.ToStr()
    else if action = "ava_recommend"
        prompt = HmText(HmField(params, "prompt"), 1001)
        sourceId = HmText(HmField(params, "sourceId"), 512)
        if prompt = "" or Len(prompt) > 1000 or not HmOwnedSource(sourceId) then return HmFailure("invalid_request")
        request.method = "POST"
        request.url = base + "/v1/ava/recommendations"
        request["timeoutMs"] = 30000
        request.headers["Content-Type"] = "application/json"
        candidates = HmAvaCandidates(HmField(params, "libraryCandidates"), sourceId)
        hints = HmStrings(HmField(params, "libraryHints"), 40, 120)
        request.body = FormatJson({prompt: prompt, libraryHints: hints, libraryCandidates: candidates, limit: HmLimit(HmField(params, "limit"), 30, 30)})
    else
        return HmFailure("unsupported_action")
    end if
    return request
end function

function DecodeMetadataResponse(action as String, body as String, params as Object) as Object
    if action = "metadata_artwork" and Len(body) > 98304 then return HmFailure("response_too_large")
    if Len(body) > 2097152 then return HmFailure("response_too_large")
    decoded = ParseJson(body, "i")
    if type(decoded) <> "roAssociativeArray" then return HmFailure("invalid_response")
    if action = "metadata_artwork"
        kind = HmText(HmField(params,"type"),10)
        identifier = HmNumericId(HmField(params,"tmdbId"))
        if (kind <> "movie" and kind <> "tv") or identifier = "" then return HmFailure("invalid_response")
        if HmText(HmField(decoded,"type"),10) <> kind or HmNumericId(HmField(decoded,"tmdbId")) <> identifier then return HmFailure("invalid_response")
        return {ok:true,data:{type:kind,tmdbId:identifier,posterUri:HmTmdbArtwork(HmField(decoded,"posterPath"),"w342"),backdropUri:HmTmdbArtwork(HmField(decoded,"backdropPath"),"w780")}}
    else if action = "home_rows" or action = "service_catalog"
        if type(decoded.rows) <> "roArray" then return HmFailure("invalid_response")
        if decoded.DoesExist("format")
            if action <> "home_rows" or HmField(decoded, "format") <> "compact-v1" then return HmFailure("invalid_response")
            if type(HmField(decoded, "items")) <> "roArray" then return HmFailure("invalid_response")
        end if
        rows = []
        inspected = 0
        for each raw in decoded.rows
            inspected++
            if rows.Count() >= 12 or inspected > 50 then exit for
            if type(raw) = "roAssociativeArray"
                rowId = HmText(HmField(raw, "id"), 120)
                values = HmField(raw, "items")
                if HmField(decoded, "format") = "compact-v1" then values = HmCompactRowItems(raw, decoded.items)
                if rowId <> "" and type(values) = "roArray"
                    rows.Push({id: rowId, title: HmText(HmField(raw, "title"), 120), items: HmCatalogItems(values, false, 24)})
                end if
            end if
        end for
        data = {rows: rows}
        fetched = HmNumber(HmField(decoded, "fetchedAtEpochMs"), 0)
        if fetched > 0 then data["fetchedAtEpochMs"] = fetched
        return {ok: true, data: data}
    else if action = "discover_trending"
        return HmTrendingResponse(decoded, params)
    else if action = "ava_recommend"
        if type(decoded.matches) <> "roArray" then return HmFailure("invalid_response")
        return {ok: true, data: {reply: HmText(HmField(decoded, "reply"), 180), items: HmCatalogItems(decoded.matches, true, HmLimit(HmField(params, "limit"), 30, 30))}}
    end if
    return HmFailure("unsupported_action")
end function

function HmCompactRowItems(row as Object, table as Object) as Object
    values = []
    indices = HmField(row, "i")
    if type(indices) <> "roArray" then return values
    inspected = 0
    for each index in indices
        inspected++
        if inspected > 180 or values.Count() >= 24 then exit for
        kind = type(index)
        if kind = "Integer" or kind = "roInt" or kind = "Float" or kind = "roFloat" or kind = "Double" or kind = "roDouble"
            if index >= 0 and index < table.Count()
                if index = Int(index) then values.Push(table[Int(index)])
            end if
        end if
    end for
    return values
end function

' The existing trending route returns one TMDB page, avoiding the complete
' curated catalog response. Only explicit movie/TV types with numeric TMDB
' identity can become unresolved discovery seeds.
function HmTrendingResponse(decoded as Object, params as Object) as Object
    if type(HmField(decoded, "results")) <> "roArray" then return HmFailure("invalid_response")
    page = HmNumber(HmField(decoded, "page"), HmTrendingPage(HmField(params, "page")))
    if HmField(decoded, "page") <> invalid
        if HmNumber(HmField(decoded, "page"), -1) = -1 then return HmFailure("invalid_response")
    end if
    if page < 1 or page > 20 or page <> Int(page) then return HmFailure("invalid_response")
    nextPage = 0
    totalPages = HmNumber(HmField(decoded, "total_pages"), 0)
    if page < 20 and totalPages > page then nextPage = Int(page) + 1
    candidates = []
    inspected = 0
    for each raw in decoded.results
        inspected++
        if candidates.Count() >= 20 or inspected > 100 then exit for
        identifier = HmNumber(HmField(raw, "id"), 0)
        kind = HmKind(HmField(raw, "media_type"))
        if identifier >= 1 and identifier <= 2147483647 and kind <> ""
            if identifier = Int(identifier)
                title = HmText(HmField(raw, "title"), 120)
                if title = "" then title = HmText(HmField(raw, "name"), 120)
                if title <> ""
                    releaseDate = HmText(HmField(raw, "release_date"), 10)
                    if releaseDate = "" then releaseDate = HmText(HmField(raw, "first_air_date"), 10)
                    year = 0
                    if CreateObject("roRegex", "^[0-9]{4}-[0-9]{2}-[0-9]{2}$", "").IsMatch(releaseDate) then year = Val(Left(releaseDate, 4))
                    candidates.Push({tmdbId: Int(identifier).ToStr(), type: kind, title: title, releaseYear: year, releaseDate: releaseDate, overview: HmText(HmField(raw, "overview"), 2000), posterPath: HmText(HmField(raw, "poster_path"), 256), backdropPath: HmText(HmField(raw, "backdrop_path"), 256)})
                end if
            end if
        end if
    end for
    items = HmCatalogItems(candidates, false, 20)
    return {ok: true, data: {rows: [{id: "trending-week", title: "Trending This Week", items: items}], page: Int(page), nextPage: nextPage}}
end function

function HmTrendingPage(value as Dynamic) as Integer
    page = HmNumber(value, 1)
    if page <= 1 then return 1
    if page >= 20 then return 20
    return Int(page)
end function

' Resolve only exact external identity in the active server inventory. When both
' parties have an identifier in the same namespace, conflicting IDs reject a match.
function MatchMetadataOwnedItem(seed as Object, candidates as Object, activeSourceId as String) as Dynamic
    if not HmOwnedSource(activeSourceId) or type(candidates) <> "roArray" then return invalid
    if HmText(HmField(seed, "provider"), 20) <> "metadata" then return invalid
    kind = HmKind(HmField(seed, "type"))
    if kind = "" then return invalid
    wanted = HmIds(seed)
    inspected = 0
    for each item in candidates
        inspected++
        if inspected > 1000 then exit for
        if HmIsOwned(item, activeSourceId) and HmKind(HmField(item, "type")) = kind
            ids = HmIds(item)
            overlap = false
            conflict = false
            for each key in ["tmdbId", "imdbId", "tvdbId"]
                if wanted[key] <> "" and ids[key] <> ""
                    if wanted[key] = ids[key]
                        overlap = true
                    else
                        conflict = true
                    end if
                end if
            end for
            if overlap and not conflict
                result = {sourceId: activeSourceId, itemId: HmText(HmField(item, "itemId"), 256), title: HmText(HmField(item, "title"), 120), type: kind, year: HmNumber(HmField(item, "year"), 0), owned: true, canPlay: kind = "movie", availability: "owned"}
                for each key in ["durationMs", "resumeMs"]
                    result[key] = HmNumber(HmField(item, key), 0)
                end for
                if type(HmField(item, "watched")) = "Boolean" then result["watched"] = item.watched
                ' Provider-relative artwork keys are safe; absolute artwork may carry auth.
                thumb = HmText(HmField(item, "thumbKey"), 1024)
                if CreateObject("roRegex", "^/[A-Za-z0-9_./-]+$", "").IsMatch(thumb) then result["thumbKey"] = thumb
                return result
            end if
        end if
    end for
    return invalid
end function

function HmAvaCandidates(values as Dynamic, sourceId as String) as Object
    output = []
    seen = {}
    if type(values) <> "roArray" then return output
    inspected = 0
    for each item in values
        inspected++
        if output.Count() >= 180 or inspected > 1000 then exit for
        if HmIsOwned(item, sourceId)
            title = HmText(HmField(item, "title"), 121)
            kind = HmKind(HmField(item, "type"))
            if Len(title) >= 2 and Len(title) <= 120 and kind <> ""
                ids = HmIds(item)
                identity = ids.tmdbId
                if identity = "" then identity = ids.imdbId
                if identity = "" then identity = LCase(title)
                year = HmNumber(HmField(item, "year"), 0)
                key = kind + ":" + identity + ":" + year.ToStr()
                if not seen.DoesExist(key)
                    seen[key] = true
                    value = {title: title, mediaType: kind, genres: HmStrings(HmField(item, "genres"), 8, 80)}
                    if ids.tmdbId <> "" then value["tmdbId"] = ids.tmdbId
                    if ids.imdbId <> "" then value["imdbId"] = ids.imdbId
                    if year >= 1880 and year <= 3000 and year = Int(year) then value["year"] = year
                    rating = HmNumber(HmField(item, "rating"), -1)
                    if rating >= 0 and rating <= 10 then value["rating"] = rating
                    output.Push(value)
                end if
            end if
        end if
    end for
    return output
end function

function HmCatalogItems(values as Object, ava as Boolean, limit as Integer) as Object
    output = []
    seen = {}
    inspected = 0
    for each raw in values
        inspected++
        if output.Count() >= limit or inspected > 180 then exit for
        kind = HmKind(HmField(raw, "type"))
        if ava then kind = HmKind(HmField(raw, "mediaType"))
        ids = HmIds(raw)
        title = HmText(HmField(raw, "title"), 120)
        identifier = ids.tmdbId
        if identifier = "" then identifier = "imdb:" + ids.imdbId
        if kind <> "" and title <> "" and (ava or ids.tmdbId <> "" or ids.imdbId <> "")
            key = "metadata:" + kind + ":" + identifier
            if ava then key = HmAvaCatalogId(kind,title,ids)
            if not seen.DoesExist(key)
                seen[key] = true
                item = {provider: "metadata", catalogId: key, title: title, type: kind, tmdbId: ids.tmdbId, imdbId: ids.imdbId, tvdbId: ids.tvdbId, owned: false, canPlay: false, availability: "unresolved"}
                if not ava
                    item["year"] = HmNumber(HmField(raw, "releaseYear"), 0)
                    item["summary"] = HmText(HmField(raw, "overview"), 2000)
                    item["thumbKey"] = HmTmdbArtwork(HmField(raw, "posterPath"), "w342")
                    item["backdropKey"] = HmTmdbArtwork(HmField(raw, "backdropPath"), "w780")
                    item["releaseDate"] = HmText(HmField(raw, "releaseDate"), 10)
                end if
                output.Push(item)
            end if
        end if
    end for
    return output
end function

' AVA's server-normalized matches may have only title/mediaType. This key is
' display identity, never a provider itemId or evidence of library ownership.
function HmAvaCatalogId(kind as String, title as String, ids as Object) as String
    identity = ids.tmdbId
    if identity = "" and ids.imdbId <> "" then identity = "imdb:" + ids.imdbId
    if identity = "" and ids.tvdbId <> "" then identity = "tvdb:" + ids.tvdbId
    if identity <> "" then return "metadata:" + kind + ":" + identity
    return "ava:" + kind + ":title:" + LCase(title)
end function

function HmIds(item as Dynamic) as Object
    ids = {tmdbId: HmNumericId(HmField(item, "tmdbId")), imdbId: HmImdbId(HmField(item, "imdbId")), tvdbId: HmNumericId(HmField(item, "tvdbId"))}
    external = HmField(item, "externalIds")
    if ids.tmdbId = "" then ids["tmdbId"] = HmNumericId(HmField(external, "tmdb"))
    if ids.imdbId = "" then ids["imdbId"] = HmImdbId(HmField(external, "imdb"))
    if ids.tvdbId = "" then ids["tvdbId"] = HmNumericId(HmField(external, "tvdb"))
    guids = HmField(item, "guids")
    if type(guids) = "roArray"
        count = 0
        for each raw in guids
            count++
            if count > 16 then exit for
            guid = HmText(raw, 256)
            for each prefix in ["tmdb", "imdb", "tvdb"]
                if Left(guid, Len(prefix) + 3) = prefix + "://"
                    id = Mid(guid, Len(prefix) + 4)
                    if prefix = "imdb"
                        id = HmImdbId(id)
                    else
                        id = HmNumericId(id)
                    end if
                    key = prefix + "Id"
                    if ids[key] = "" then ids[key] = id
                end if
            end for
        end for
    end if
    return ids
end function

function HmNumericId(value as Dynamic) as String
    text = HmText(value, 30)
    if CreateObject("roRegex", "^[0-9]{1,12}$", "").IsMatch(text)
        while Len(text) > 1 and Left(text, 1) = "0"
            text = Mid(text, 2)
        end while
        if text <> "0" then return text
    end if
    return ""
end function

function HmImdbId(value as Dynamic) as String
    text = LCase(HmText(value, 30))
    if CreateObject("roRegex", "^tt[0-9]{1,12}$", "").IsMatch(text) then return text
    return ""
end function

function HmTmdbArtwork(value as Dynamic, size as String) as String
    path = HmText(value, 256)
    if not CreateObject("roRegex", "^/[A-Za-z0-9_-]+[.](jpg|jpeg|png|webp)$", "i").IsMatch(path) then return ""
    return "https://image.tmdb.org/t/p/" + size + path
end function

function HmBaseUrl(value as String) as String
    if not CreateObject("roRegex", "^https://[A-Za-z0-9][A-Za-z0-9.-]*(:[0-9]{1,5})?(/[A-Za-z0-9_/-]*)?$", "").IsMatch(value) then return ""
    authority = Mid(value, 9).Split("/")[0]
    if Instr(1, authority, "..") > 0 or Right(authority, 1) = "." then return ""
    colon = Instr(1, authority, ":")
    if colon > 0
        port = Val(Mid(authority, colon + 1))
        if port < 1 or port > 65535 then return ""
    end if
    while Right(value, 1) = "/"
        value = Left(value, Len(value) - 1)
    end while
    return value
end function

function HmIsOwned(item as Dynamic, sourceId as String) as Boolean
    if type(item) <> "roAssociativeArray" then return false
    if HmText(HmField(item, "sourceId"), 512) <> sourceId or HmText(HmField(item, "itemId"), 256) = "" then return false
    if HmField(item, "owned") = false then return false
    return true
end function

function HmOwnedSource(value as String) as Boolean
    return (Left(value, 5) = "plex:" and Len(value) > 5) or (Left(value, 5) = "silo:" and Len(value) > 5)
end function

function HmKind(value as Dynamic) as String
    kind = LCase(HmText(value, 20))
    if kind = "movie" then return "movie"
    if kind = "show" or kind = "tv" then return "show"
    return ""
end function

function HmStrings(values as Dynamic, limit as Integer, width as Integer) as Object
    output = []
    seen = {}
    if type(values) <> "roArray" then return output
    inspected = 0
    for each raw in values
        inspected++
        if output.Count() >= limit or inspected > 200 then exit for
        value = HmText(raw, width)
        if value <> "" and not seen.DoesExist(value)
            output.Push(value)
            seen[value] = true
        end if
    end for
    return output
end function

function HmLimit(value as Dynamic, fallback as Integer, maximum as Integer) as Integer
    result = Int(HmNumber(value, fallback))
    if result < 1 then result = 1
    if result > maximum then result = maximum
    return result
end function

function HmNumber(value as Dynamic, fallback as Double) as Double
    kind = type(value)
    if kind = "Integer" or kind = "LongInteger" or kind = "Float" or kind = "Double" or kind = "roInt" or kind = "roInteger" or kind = "roLongInteger" or kind = "roFloat" or kind = "roDouble" then return value
    return fallback
end function

function HmField(value as Dynamic, key as String) as Dynamic
    if type(value) <> "roAssociativeArray" then return invalid
    return value[key]
end function

function HmText(value as Dynamic, limit as Integer) as String
    if type(value) <> "String" and type(value) <> "roString" then return ""
    text = value.Replace(Chr(13), " ").Replace(Chr(10), " ").Trim()
    return Left(text, limit)
end function

function HmFailure(code as String) as Object
    return {ok: false, errorCode: code, message: "Metadata could not be loaded."}
end function
