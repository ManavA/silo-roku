' Volatile active-library facts for AVA. Load with MetadataAdapter,
' MetadataUiPolicy and ServicePolicy for shared scope/native-ID validation.
' This bounded cache is partial; it never establishes library absence.
function AvaCandidateCacheAdd(existing as Dynamic, incoming as Dynamic, scope as Dynamic, limit = 180 as Integer) as Object
    result = {sourceId: "", profileId: "", items: []}
    active = ServiceScope(scope)
    if active = invalid then return result
    result["sourceId"] = active.sourceId
    result["profileId"] = active.profileId
    if limit < 1 then return result
    if limit > 180 then limit = 180
    previous = []
    if ServiceIndexMatches(existing, active) then previous = HmField(existing, "items")
    seen = {}
    for each values in [incoming, previous]
        if type(values) = "roArray"
            inspected = 0
            for each raw in values
                inspected++
                if inspected > 1000 or result.items.Count() >= limit then exit for
                key = ServiceItemKey(raw, active)
                if key <> "" and not seen.DoesExist(key)
                    ' Mark raw native identity before sanitation: a revoked card
                    ' retires prior ownership, and lost IDs replace old IDs.
                    seen[key] = true
                    card = HmUiOwnedCard(raw, active.provider, active.sourceId)
                    if card <> invalid then result.items.Push(card)
                end if
            end for
        end if
    end for
    return result
end function

' Revalidate scope and bounded fields at submission. Title-only Silo cards
' remain useful inventory facts; request encoding removes native identity.
function AvaCandidateCacheItems(cache as Dynamic, scope as Dynamic) as Object
    active = ServiceScope(scope)
    if active = invalid then return []
    if not ServiceIndexMatches(cache, active) then return []
    safe = AvaCandidateCacheAdd(invalid, HmField(cache, "items"), scope)
    return safe.items
end function

' Keep AVA's title-only contract separate from global Discover/Services seeds.
' Entries carry request scope, but no native ID or claimed ownership. Display
' labels are hints; selection always rechecks the current volatile cache.
function UiAvaEntries(data as Dynamic, cache as Dynamic, scope as Dynamic, limit = 30 as Integer) as Object
    active = ServiceScope(scope)
    output = []
    values = HmField(data,"items")
    if active = invalid or type(values) <> "roArray" then return output
    limit = HmLimit(limit,30,30)
    candidates = AvaCandidateCacheItems(cache,scope)
    seen = {}
    inspected = 0
    for each raw in values
        inspected++
        if inspected > 180 or output.Count() >= limit then exit for
        item = AvaRecommendationSeed(raw)
        if item <> invalid and not seen.DoesExist(item.catalogId)
            seen[item.catalogId] = true
            item["avaSourceId"] = active.sourceId
            item["avaProfileId"] = active.profileId
            item["uiAction"] = "ava_recommendation"
            item["rowTitle"] = "Search your source"
            if AvaUniqueOwnedMatch(item,candidates).state = "owned" then item["rowTitle"] = "In your library"
            output.Push(item)
        end if
    end for
    return output
end function

' One current native identity is required. Remakes/duplicate editions and
' multiple external-ID matches are offered as explicit native search choices.
function UiAvaResolveOwned(seed as Dynamic, cache as Dynamic, scope as Dynamic) as Object
    active = ServiceScope(scope)
    if active = invalid then return HmUiError("invalid_source")
    item = AvaScopedSeed(seed,active)
    if item = invalid then return HmUiError("invalid_seed")
    return AvaUniqueOwnedMatch(item,AvaCandidateCacheItems(cache,scope))
end function

function UiAvaSearchRequest(seed as Dynamic, provider as String, scope as Dynamic) as Object
    active = ServiceScope(scope)
    if active = invalid then return HmUiError("invalid_source")
    if active.provider <> provider then return HmUiError("invalid_source")
    item = AvaScopedSeed(seed,active)
    if item = invalid then return HmUiError("invalid_seed")
    params = {query:item.title,limit:100}
    action = "search"
    if provider = "silo"
        action = "catalog_query"
        params["type"] = "movie"
        if item.type = "show" then params["type"] = "series"
    end if
    return {ok:true,state:"search_required",action:action,params:params}
end function

function AvaRecommendationSeed(raw as Dynamic) as Dynamic
    if HmText(HmField(raw,"provider"),20) <> "metadata" then return invalid
    kind = HmKind(HmField(raw,"type"))
    title = HmText(HmField(raw,"title"),120)
    if kind = "" or title = "" then return invalid
    ids = HmIds(raw)
    return {provider:"metadata",catalogId:HmAvaCatalogId(kind,title,ids),title:title,type:kind,tmdbId:ids.tmdbId,imdbId:ids.imdbId,tvdbId:ids.tvdbId,owned:false,canPlay:false,availability:"unresolved"}
end function

function AvaScopedSeed(raw as Dynamic, active as Object) as Dynamic
    if HmField(raw,"avaSourceId") <> active.sourceId or HmField(raw,"avaProfileId") <> active.profileId then return invalid
    return AvaRecommendationSeed(raw)
end function

' candidates are sanitized, bounded, current-scope AvaCandidateCacheItems.
' Any supplied external namespace blocks title fallback; conflicting IDs fail.
function AvaUniqueOwnedMatch(seed as Object, candidates as Object) as Object
    wanted = HmIds(seed)
    hasIds = wanted.tmdbId <> "" or wanted.imdbId <> "" or wanted.tvdbId <> ""
    selected = invalid
    inspected = 0
    for each item in candidates
        inspected++
        if inspected > 180 then exit for
        if item.type = seed.type
            matched = false
            if hasIds
                ids = HmIds(item)
                overlap = false
                conflict = false
                for each namespace in ["tmdbId","imdbId","tvdbId"]
                    if wanted[namespace] <> "" and ids[namespace] <> ""
                        if wanted[namespace] = ids[namespace] then overlap = true else conflict = true
                    end if
                end for
                matched = overlap and not conflict
            else
                matched = LCase(item.title) = LCase(seed.title)
            end if
            if matched
                if selected <> invalid then return {ok:true,state:"search_required",reason:"ambiguous"}
                selected = item
            end if
        end if
    end for
    if selected = invalid then return {ok:true,state:"search_required",reason:"unresolved"}
    selected["availability"] = "owned"
    selected["canPlay"] = selected.type = "movie"
    return {ok:true,state:"owned",item:selected}
end function
