' Native extras are fetched by their own item ID and begin on their own timeline.
' A resolved selection still needs the normal provider/Roku playback route planner.
' Current Silo detail does not normalize extras; that is an explicit capability gap.
function BuildExtrasPlaylist(detail as Dynamic, originScope as Dynamic, activeScope as Dynamic) as Object
    if not ExScopeMatches(originScope, activeScope) then return ExError("stale", "scope_changed")
    sourceId = ExText(ExField(activeScope, "sourceId"))
    provider = ExProvider(sourceId)
    if provider = "" then return ExError("unsupported", "unsupported_source")
    item = ExField(detail, "item")
    if type(item) <> "roAssociativeArray" then return ExError("unsupported", "detail_required")
    if ExText(ExField(item, "sourceId")) <> sourceId then return ExError("unsupported", "source_mismatch")
    extras = ExField(detail, "extras")
    if type(extras) <> "roArray" then return ExError("unsupported", "extras_not_normalized")
    parentItemId = ExText(ExField(item, "itemId"))

    items = []
    seen = {}
    inspected = 0
    for each extra in extras
        if items.Count() >= 24 or inspected >= 128 then exit for
        inspected += 1
        nativeItem = ExNativeItem(extra, sourceId)
        if nativeItem <> invalid
            itemId = nativeItem["itemId"]
            if itemId <> parentItemId and not seen.DoesExist(itemId)
                seen[itemId] = true
                items.Push(nativeItem)
            end if
        end if
    end for
    if extras.Count() > 0 and items.Count() = 0 then return ExError("unsupported", "no_native_extras")
    state = "available"
    if items.Count() = 0 then state = "empty"
    scope = {sourceId: sourceId, profileId: ExText(ExField(activeScope, "profileId")), generation: ExField(activeScope, "generation")}
    return {ok: true, state: state, items: items, scope: scope}
end function

function ExtrasPlaylistItem(playlist as Dynamic, index as Dynamic, activeScope as Dynamic) as Object
    if not ExScopeMatches(ExField(playlist, "scope"), activeScope) then return ExError("stale", "scope_changed")
    items = ExField(playlist, "items")
    if type(items) <> "roArray" then return ExError("unsupported", "invalid_playlist")
    if not ExIndex(index) then return ExError("unsupported", "index_out_of_range")
    if index >= items.Count() or index >= 24 then return ExError("unsupported", "index_out_of_range")
    item = ExNativeItem(items[index], ExText(ExField(activeScope, "sourceId")))
    if item = invalid then return ExError("unsupported", "no_native_extras")
    return {ok: true, state: "selected", index: index, item: item, action: "detail", params: {itemId: item["itemId"]}}
end function

' Call only after a successful terminal Video completion, never for a failure/Back.
function AdvanceExtrasPlaylist(playlist as Dynamic, currentIndex as Dynamic, activeScope as Dynamic) as Object
    current = ExtrasPlaylistItem(playlist, currentIndex, activeScope)
    if not current.ok then return current
    items = ExField(playlist, "items")
    if currentIndex + 1 >= items.Count() or currentIndex + 1 >= 24 then return ExError("complete", "playlist_complete")
    return ExtrasPlaylistItem(playlist, currentIndex + 1, activeScope)
end function

' Pass only an already scope-validated, source-normalized detail response here.
function ResolveExtraPlayback(playlist as Dynamic, index as Dynamic, extraDetail as Dynamic, activeScope as Dynamic) as Object
    selected = ExtrasPlaylistItem(playlist, index, activeScope)
    if not selected.ok then return selected
    item = ExField(extraDetail, "item")
    if type(item) <> "roAssociativeArray" then return ExError("unsupported", "detail_required")
    sourceId = ExText(ExField(activeScope, "sourceId"))
    if ExText(ExField(item, "sourceId")) <> sourceId then return ExError("unsupported", "source_mismatch")
    metadataId = ExText(ExField(item, "itemId"))
    if metadataId <> selected.item["itemId"] then return ExError("unsupported", "item_mismatch")
    if ExText(ExField(item, "type")) <> "movie" and ExText(ExField(item, "type")) <> "clip" then return ExError("unsupported", "native_video_required")
    provider = ExProvider(sourceId)
    playbackId = metadataId
    if provider = "silo"
        explicitId = ExText(ExField(item, "playItemId"))
        if explicitId <> "" then playbackId = explicitId
        if not ExIdentifier(playbackId) then return ExError("unsupported", "native_video_required")
    end if

    versions = ExField(extraDetail, "versions")
    if type(versions) <> "roArray" then return ExError("unsupported", "native_video_required")
    versionIndex = 0
    for each version in versions
        if versionIndex >= 20 then exit for
        if ExVideoVersion(version, sourceId, metadataId, provider)
            versionId = ExText(ExField(version, "versionId"))
            if provider = "plex"
                params = {itemId: playbackId, detail: extraDetail, versionIndex: versionIndex, partIndex: ExField(version, "partIndex"), startPositionMs: 0}
            else
                params = {itemId: playbackId, fileId: versionId, startPositionMs: 0}
            end if
            return {ok: true, state: "resolved", index: index, metadataItemId: metadataId, playbackItemId: playbackId, versionId: versionId, params: params}
        end if
        versionIndex += 1
    end for
    return ExError("unsupported", "native_video_required")
end function

function ExVideoVersion(version as Dynamic, sourceId as String, itemId as String, provider as String) as Boolean
    if type(version) <> "roAssociativeArray" then return false
    if ExText(ExField(version, "sourceId")) <> sourceId then return false
    if ExText(ExField(version, "versionId")) = "" or ExText(ExField(version, "videoCodec")) = "" then return false
    versionItemId = ExText(ExField(version, "itemId"))
    if provider = "plex"
        if versionItemId <> itemId then return false
        if not ExIndex(ExField(version, "mediaIndex")) or not ExIndex(ExField(version, "partIndex")) then return false
        key = ExText(ExField(version, "partKey"))
        if Left(key, 15) <> "/library/parts/" then return false
        if Instr(1, key, "?") > 0 or Instr(1, key, "#") > 0 or Instr(1, key, "..") > 0 or Instr(1, key, "\") > 0 then return false
    else if provider = "silo"
        if versionItemId <> "" and versionItemId <> itemId then return false
        if not ExIdentifier(ExText(ExField(version, "versionId"))) then return false
    else
        return false
    end if
    return true
end function

function ExNativeItem(raw as Dynamic, sourceId as String) as Dynamic
    if type(raw) <> "roAssociativeArray" then return invalid
    provider = ExProvider(sourceId)
    if provider = "" then return invalid
    if ExText(ExField(raw, "sourceId")) <> sourceId then return invalid
    statedProvider = ExText(ExField(raw, "provider"))
    if statedProvider <> "" and statedProvider <> provider then return invalid
    if ExText(ExField(raw, "site")) <> "" then return invalid
    kind = ExText(ExField(raw, "type"))
    if kind <> "movie" and kind <> "clip" then return invalid
    extraType = ExText(ExField(raw, "extraType"))
    if extraType = "" then return invalid
    itemId = ExText(ExField(raw, "itemId"))
    if not ExIdentifier(itemId) then return invalid
    return {provider: provider, sourceId: sourceId, itemId: itemId, type: "movie", extraType: extraType, title: ExText(ExField(raw, "title")), durationMs: ExNumber(ExField(raw, "durationMs")), resumeMs: 0}
end function

function ExScopeMatches(first as Dynamic, second as Dynamic) as Boolean
    if type(first) <> "roAssociativeArray" or type(second) <> "roAssociativeArray" then return false
    for each key in ["sourceId", "profileId", "generation"]
        one = ExField(first, key)
        two = ExField(second, key)
        if one = invalid or two = invalid then return false
        if key = "generation"
            if not ExIndex(one) or not ExIndex(two) then return false
        else
            if type(one) <> "String" and type(one) <> "roString" then return false
            if type(two) <> "String" and type(two) <> "roString" then return false
        end if
        if one <> two then return false
    end for
    return true
end function

function ExProvider(sourceId as String) as String
    if Left(sourceId, 5) = "plex:" and Len(sourceId) > 5 then return "plex"
    if Left(sourceId, 5) = "silo:" and Len(sourceId) > 5 then return "silo"
    return ""
end function

function ExIndex(value as Dynamic) as Boolean
    kind = type(value)
    if kind <> "Integer" and kind <> "LongInteger" and kind <> "roLongInteger" and kind <> "Float" and kind <> "Double" and kind <> "roInt" and kind <> "roInteger" and kind <> "roFloat" and kind <> "roDouble" then return false
    if value < 0 or value > 2147483647 then return false
    return Int(value) = value
end function

function ExIdentifier(value as String) as Boolean
    if Len(value) < 1 or Len(value) > 128 then return false
    return CreateObject("roRegex", "^[A-Za-z0-9_-]+$", "").IsMatch(value)
end function

function ExField(data as Dynamic, key as String) as Dynamic
    if type(data) <> "roAssociativeArray" then return invalid
    return data[key]
end function

function ExText(value as Dynamic) as String
    if type(value) = "String" or type(value) = "roString" then return value
    return ""
end function

function ExNumber(value as Dynamic) as Double
    kind = type(value)
    if kind = "Integer" or kind = "LongInteger" or kind = "roLongInteger" or kind = "Float" or kind = "Double" or kind = "roInt" or kind = "roInteger" or kind = "roFloat" or kind = "roDouble"
        if value > 0 then return value
    end if
    return 0
end function

function ExError(state as String, code as String) as Object
    return {ok: false, state: state, errorCode: code, items: []}
end function
