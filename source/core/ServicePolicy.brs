' Positive ownership evidence from titles observed in the active source/profile.
' This volatile cache never establishes library absence or complete service rows.
' Load with MetadataAdapter.brs and MetadataUiPolicy.brs.
function ServiceOwnedIndexAdd(existing as Dynamic, incoming as Dynamic, scope as Dynamic, limit = 500 as Integer) as Object
    result = {sourceId: "", profileId: "", items: []}
    active = ServiceScope(scope)
    if active = invalid then return result
    result["sourceId"] = active.sourceId
    result["profileId"] = active.profileId
    if limit < 1 then return result
    if limit > 500 then limit = 500
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
                    ' A newer native card with lost IDs or revoked ownership retires
                    ' older positive evidence instead of reviving it from the cache.
                    seen[key] = true
                    card = HmUiOwnedCard(raw, active.provider, active.sourceId)
                    if card <> invalid
                        if card.tmdbId <> "" or card.imdbId <> "" or card.tvdbId <> ""
                            result.items.Push(card)
                        end if
                    end if
                end if
            end for
        end if
    end for
    return result
end function

function ServiceOwnedEntries(data as Dynamic, index as Dynamic, scope as Dynamic, limit = 100 as Integer) as Object
    result = {ok: true, items: [], ownershipComplete: false}
    active = ServiceScope(scope)
    if active = invalid or not ServiceIndexMatches(index, active) then return result
    if limit < 1 then return result
    if limit > 100 then limit = 100
    candidates = HmField(index, "items")
    if type(candidates) <> "roArray" then return result
    ' Typed external-ID buckets avoid rescanning all 500 records for every seed.
    lookup = {}
    inspected = 0
    for each raw in candidates
        inspected++
        if inspected > 500 then exit for
        card = HmUiOwnedCard(raw, active.provider, active.sourceId)
        if card <> invalid
            for each namespace in ["tmdbId", "imdbId", "tvdbId"]
                if card[namespace] <> ""
                    key = card.type + ":" + namespace + ":" + card[namespace]
                    if not lookup.DoesExist(key) then lookup[key] = []
                    lookup[key].Push(card)
                end if
            end for
        end if
    end for
    seen = {}
    for each seed in UiMetadataEntries(data, 100)
        if result.items.Count() >= limit then exit for
        matches = []
        for each namespace in ["tmdbId", "imdbId", "tvdbId"]
            if seed[namespace] <> ""
                key = seed.type + ":" + namespace + ":" + seed[namespace]
                if lookup.DoesExist(key)
                    for each candidate in lookup[key]
                        if matches.Count() >= 1000 then exit for
                        matches.Push(candidate)
                    end for
                end if
            end if
        end for
        owned = MatchMetadataOwnedItem(seed, matches, active.sourceId)
        if owned <> invalid and not seen.DoesExist(owned.itemId)
            seen[owned.itemId] = true
            owned["provider"] = active.provider
            owned["rowTitle"] = seed.rowTitle
            ' The seed has already passed the public TMDB artwork whitelist.
            owned["thumbKey"] = seed.thumbKey
            if seed.thumbKey <> ""
                owned["artworkProvenance"] = "metadata_owned_match"
                owned["artworkProfileId"] = active.profileId
            end if
            owned["summary"] = seed.summary
            result.items.Push(owned)
        end if
    end for
    return result
end function

' Keep a useful native action when the catalog is empty, oversized or unavailable.
' It is not a catalog title and carries no borrowed provider identity.
function ServiceViewEntries(data as Dynamic, index as Dynamic, scope as Dynamic, limit = 100 as Integer) as Object
    result = ServiceOwnedEntries(data, index, scope, limit)
    result.items.Push({title: "Search your source", uiAction: "service_search"})
    return result
end function

function ServiceScope(scope as Dynamic) as Dynamic
    sourceId = HmField(scope, "sourceId")
    profileId = HmField(scope, "profileId")
    if type(sourceId) <> "String" and type(sourceId) <> "roString" then return invalid
    if type(profileId) <> "String" and type(profileId) <> "roString" then return invalid
    if Len(sourceId) > 512 or Len(profileId) > 256 then return invalid
    provider = Left(sourceId, 4)
    if not HmUiProviderScope(provider, sourceId) then return invalid
    return {provider: provider, sourceId: sourceId, profileId: profileId}
end function

function ServiceIndexMatches(index as Dynamic, active as Dynamic) as Boolean
    if type(active) <> "roAssociativeArray" then return false
    return HmField(index, "sourceId") = active.sourceId and HmField(index, "profileId") = active.profileId
end function

function ServiceItemKey(raw as Dynamic, active as Object) as String
    if HmText(HmField(raw, "sourceId"), 512) <> active.sourceId then return ""
    provider = HmText(HmField(raw, "provider"), 20)
    if provider <> "" and provider <> active.provider then return ""
    itemId = HmText(HmField(raw, "itemId"), 256)
    pattern = "^[A-Za-z0-9_.:-]{1,256}$"
    if active.provider = "plex" then pattern = "^[0-9]{1,128}$"
    if not CreateObject("roRegex", pattern, "").IsMatch(itemId) then return ""
    return itemId
end function
