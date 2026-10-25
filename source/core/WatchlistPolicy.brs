' A Discover Watchlist ID is global and never a server rating key. Search
' candidates become playable only after an exact provider GUID match.
function MatchOwnedWatchlistItem(seed as Object, candidates as Object, activeSourceId as String) as Dynamic
    if type(seed) <> "roAssociativeArray" or type(candidates) <> "roArray" then return invalid
    seedSource = WlText(WlField(seed, "sourceId"))
    if Left(seedSource, 15) <> "plex-watchlist:" then return invalid
    seedType = WlText(WlField(seed, "type"))
    if seedType <> "movie" and seedType <> "show" then return invalid
    seedGuids = WlField(seed, "guids")
    if type(seedGuids) <> "roArray" or seedGuids.Count() = 0 then return invalid
    for each candidate in candidates
        if type(candidate) = "roAssociativeArray"
            if WlText(WlField(candidate, "sourceId")) = activeSourceId and WlText(WlField(candidate, "type")) = seedType and WlText(WlField(candidate, "itemId")) <> ""
                if WlGuidOverlap(seedGuids, WlField(candidate, "guids")) then return candidate
            end if
        end if
    end for
    return invalid
end function

function WlGuidOverlap(first as Object, second as Dynamic) as Boolean
    if type(second) <> "roArray" then return false
    for each one in first
        if type(one) = "String" or type(one) = "roString"
            if one <> ""
                for each two in second
                    if type(two) = "String" or type(two) = "roString"
                        if one = two then return true
                    end if
                end for
            end if
        end if
    end for
    return false
end function

function WlField(data as Dynamic, key as String) as Dynamic
    if type(data) <> "roAssociativeArray" then return invalid
    return data[key]
end function

function WlText(value as Dynamic) as String
    if type(value) = "String" or type(value) = "roString" then return value
    return ""
end function
