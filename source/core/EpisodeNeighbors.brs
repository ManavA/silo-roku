' Read-only native successor policy. Android 45774f8b EpisodeNeighbors.kt
' 25-94 supplies exact-membership/native-order guards; tvOS DetailScreen.swift
' 22917-23060 distinguishes authoritative end from unavailable inventories.
' The worker owns transport, session revisions, actual-call and wall-clock caps.
' State retains compact identities only: no headers, routes, artwork or versions.

function EpisodeNeighborsStart(raw as Dynamic, rawScope as Dynamic, direction = "next" as Dynamic) as Object
    state = {status:"ambiguous",stage:"done",scope:{},anchor:invalid,candidate:invalid,proof:invalid,errorCode:"invalid_anchor",sequence:0,currentItems:[],seasons:[],offset:0,pages:0,currentSeasonItemId:"",nextSeasonItemId:"",nextSeasonNumber:-1,seasonsComplete:false}
    direction = EnText(direction)
    if direction <> "next" and direction <> "previous" then return EnFail(state,"ambiguous","invalid_request")
    state["direction"] = direction
    if direction = "previous" then state["adjacentItems"] = []
    scope = EnScope(rawScope)
    if scope = invalid then return state
    state.scope = scope
    anchor = EnCard(raw,scope,"episode")
    if anchor = invalid then return state
    if EnField(scope,"anchorItemId",anchor.itemId) <> anchor.itemId then return state
    state.anchor = anchor
    state.status = "pending"
    state["errorCode"] = ""
    return EnStartContext(state)
end function

function EpisodeNeighborsRequest(state as Dynamic) as Dynamic
    if EnField(state,"status","") <> "pending" then return invalid
    scope = EnField(state,"scope",{})
    anchor = EnField(state,"anchor",{})
    stage = EnField(state,"stage","")
    params = {sourceId:EnField(scope,"sourceId","")}
    action = "detail"
    if stage = "anchor_detail"
        params["itemId"] = anchor.itemId
    else if stage = "season_detail"
        params["itemId"] = state.currentSeasonItemId
    else if stage = "candidate_detail"
        params["itemId"] = state.candidate.itemId
    else if stage = "current" or stage = "adjacent" or stage = "seasons"
        if scope.provider = "plex"
            action = "children"
            params["itemId"] = EnSeries(anchor,scope.provider)
            if stage = "current" then params["itemId"] = state.currentSeasonItemId
            if stage = "adjacent" then params["itemId"] = state.nextSeasonItemId
            params.offset = state.offset
            params.limit = 48
        else
            action = "episodes"
            params["seriesId"] = EnSeries(anchor,scope.provider)
            params["seasonNumber"] = anchor.seasonNumber
            if stage = "adjacent" then params["seasonNumber"] = state.nextSeasonNumber
            if stage = "seasons"
                action = "seasons"
                params.Delete("seasonNumber")
            end if
        end if
    else
        return invalid
    end if
    descriptor = {action:action,params:params,stage:stage,sequence:state.sequence,scope:EnClone(scope),anchorId:anchor.itemId}
    if EnField(state,"direction","next") = "previous" then descriptor["direction"] = "previous"
    return descriptor
end function

function EpisodeNeighborsResult(state as Dynamic, request as Dynamic, response as Dynamic) as Dynamic
    expected = EpisodeNeighborsRequest(state)
    if expected = invalid or not EnRequestMatches(expected,request) then return state
    nextState = EnClone(state)
    nextState.sequence = nextState.sequence + 1
    if EnField(response,"ok",false) <> true then return EnFail(nextState,"retryable",EnSafeError(EnField(response,"errorCode","network_error")))
    data = EnField(response,"data",invalid)
    if type(data) <> "roAssociativeArray" then return EnFail(nextState,"ambiguous","invalid_response")
    stage = state.stage
    if stage = "anchor_detail" or stage = "season_detail" or stage = "candidate_detail"
        return EnDetailResult(nextState,stage,data)
    end if
    return EnInventoryResult(nextState,stage,data)
end function

function EpisodeNeighborsOutcome(state as Dynamic) as Object
    outcome = {status:EnField(state,"status","ambiguous"),anchorId:EnField(EnField(state,"anchor",{}),"itemId",""),scope:EnClone(EnField(state,"scope",{})),candidate:EnClone(EnField(state,"candidate",invalid)),proof:EnClone(EnField(state,"proof",invalid)),errorCode:EnField(state,"errorCode","")}
    if EnField(state,"direction","next") = "previous"
        outcome["direction"] = "previous"
        if outcome.status = "known" then outcome["detail"] = EnClone(EnField(state,"detail",invalid))
    end if
    return outcome
end function

' A proof is usable only for these exact cards in this current viewer generation.
' Native inventory adjacency may cross a season or an episode-number gap.
function EpisodeNeighborsProofMatches(proof as Dynamic, current as Dynamic, following as Dynamic, scope as Dynamic) as Boolean
    if type(proof) <> "roAssociativeArray" or type(scope) <> "roAssociativeArray" then return false
    if EnField(proof,"status","") <> "known" or not EnLookupId(EnField(proof,"lookupId",invalid)) then return false
    provider = EnText(EnField(proof,"provider",invalid))
    if provider <> "plex" and provider <> "silo" then return false
    if EnText(EnField(proof,"sourceId",invalid)) = "" or Left(proof.sourceId,5) <> provider + ":" then return false
    if type(EnField(proof,"profileId",invalid)) <> "String" and type(EnField(proof,"profileId",invalid)) <> "roString" then return false
    if EnField(scope,"provider",provider) <> provider then return false
    for each field in ["sourceId","profileId","generation"]
        if not proof.DoesExist(field) or not scope.DoesExist(field) then return false
        if proof[field] <> scope[field] then return false
    end for
    if not EnInteger(proof.generation,0) then return false
    if EnField(scope,"lookupId",proof.lookupId) <> proof.lookupId then return false
    cardScope = {provider:provider,sourceId:proof.sourceId,profileId:proof.profileId}
    anchor = EnCard(current,cardScope,"episode")
    candidate = EnCard(following,cardScope,"episode")
    if anchor = invalid or candidate = invalid then return false
    if anchor.itemId = candidate.itemId then return false
    if EnField(proof,"currentItemId","") <> anchor.itemId or EnField(proof,"nextItemId","") <> candidate.itemId then return false
    seriesId = EnSeries(anchor,provider)
    if seriesId = "" or EnSeries(candidate,provider) <> seriesId or EnField(proof,"seriesId","") <> seriesId then return false
    if not EnInteger(anchor.seasonNumber,0) or not EnInteger(candidate.seasonNumber,0) then return false
    if EnField(proof,"currentSeasonNumber",-1) <> anchor.seasonNumber or EnField(proof,"nextSeasonNumber",-1) <> candidate.seasonNumber then return false
    if provider = "plex"
        parent = EnParent(anchor)
        nextParent = EnParent(candidate)
        if parent = "" or nextParent = "" then return false
        if EnField(proof,"currentSeasonItemId","") <> parent or EnField(proof,"nextSeasonItemId","") <> nextParent then return false
    end if
    return true
end function

function EnStartContext(state as Object) as Object
    anchor = state.anchor
    provider = state.scope.provider
    series = EnSeries(anchor,provider)
    if provider = "plex" then state["currentSeasonItemId"] = EnParent(anchor)
    if series = ""
        state.stage = "anchor_detail"
        if provider = "plex" and state.currentSeasonItemId <> "" then state.stage = "season_detail"
    else if provider = "plex" and state["currentSeasonItemId"] = ""
        if not EnInteger(anchor.seasonNumber,0) then return EnFail(state,"ambiguous","missing_season")
        state.stage = "seasons"
    else if not EnInteger(anchor.seasonNumber,0)
        state.stage = "anchor_detail"
    else
        state.stage = "current"
    end if
    return state
end function

function EnDetailResult(state as Object, stage as String, data as Object) as Object
    kind = "episode"
    if stage = "season_detail" then kind = "season"
    item = EnCard(EnField(data,"item",invalid),state.scope,kind)
    if item = invalid then return EnFail(state,"ambiguous","identity_mismatch")
    if stage = "anchor_detail"
        if item.itemId <> state.anchor.itemId then return EnFail(state,"ambiguous","identity_mismatch")
        if not EnCompatibleContext(state.anchor,item,state.scope.provider) then return EnFail(state,"ambiguous","identity_mismatch")
        state.anchor = EnMergeCard(state.anchor,item)
        state = EnStartContext(state)
        if state.stage = "anchor_detail" then return EnFail(state,"ambiguous","missing_context")
        return state
    else if stage = "season_detail"
        if item.itemId <> state.currentSeasonItemId or EnSeries(item,"plex") = "" then return EnFail(state,"ambiguous","identity_mismatch")
        state.anchor["seriesItemId"] = EnSeries(item,"plex")
        if not EnInteger(state.anchor.seasonNumber,0) then state.anchor["seasonNumber"] = item.seasonNumber
        if not EnInteger(state.anchor.seasonNumber,0) then return EnFail(state,"ambiguous","missing_context")
        state.stage = "current"
        return state
    end if
    candidate = state.candidate
    if item.itemId <> candidate.itemId or not EnCompatibleContext(candidate,item,state.scope.provider) then return EnFail(state,"ambiguous","identity_mismatch")
    versions = EnField(data,"versions",invalid)
    if type(versions) <> "roArray" or versions.Count() = 0 then return EnFail(state,"ambiguous","unavailable_candidate")
    available = false
    for each version in versions
        if EnAvailableVersion(version,item,state.scope) then available = true
    end for
    if not available then return EnFail(state,"ambiguous","unavailable_candidate")
    candidate = EnMergeCard(candidate,item)
    seriesId = EnSeries(state.anchor,state.scope.provider)
    currentSeasonId = state.currentSeasonItemId
    nextSeasonId = state.nextSeasonItemId
    if state.scope.provider = "plex"
        currentSeasonId = EnParent(state.anchor)
        nextSeasonId = EnParent(candidate)
    end if
    before = state.anchor
    after = candidate
    if EnField(state,"direction","next") = "previous"
        before = candidate
        after = state.anchor
        previousSeasonId = nextSeasonId
        nextSeasonId = currentSeasonId
        currentSeasonId = previousSeasonId
    end if
    proof = {status:"known",provider:state.scope.provider,sourceId:state.scope.sourceId,profileId:state.scope.profileId,generation:state.scope.generation,lookupId:state.scope.lookupId,currentItemId:before.itemId,nextItemId:after.itemId,seriesId:seriesId,currentSeasonNumber:before.seasonNumber,nextSeasonNumber:after.seasonNumber,currentSeasonItemId:currentSeasonId,nextSeasonItemId:nextSeasonId}
    if not EpisodeNeighborsProofMatches(proof,before,after,state.scope) then return EnFail(state,"ambiguous","identity_mismatch")
    if EnField(state,"direction","next") = "previous"
        compactVersions = []
        for index = 0 to versions.Count()-1
            if index >= 20 then exit for
            version = versions[index]
            if EnAvailableVersion(version,candidate,state.scope)
                compact = {sourceId:state.scope.sourceId,itemId:candidate.itemId,versionId:version.versionId}
                if state.scope.provider = "plex"
                    compact["mediaId"] = version.mediaId
                    compact["partId"] = version.partId
                end if
                compactVersions.Push(compact)
            end if
        end for
        if compactVersions.Count() = 0 then return EnFail(state,"ambiguous","unavailable_candidate")
        state["detail"] = {item:EnClone(candidate),versions:compactVersions}
    end if
    state.candidate = candidate
    state.proof = proof
    state.status = "known"
    state.stage = "done"
    return state
end function

' Plex version identities contain the server, item, media and part IDs. They
' are not rating keys. Silo versions use native file IDs instead.
function EnAvailableVersion(version as Dynamic, item as Object, scope as Object) as Boolean
    if type(version) <> "roAssociativeArray" then return false
    if EnField(version,"sourceId",scope.sourceId) <> scope.sourceId then return false
    if EnField(version,"itemId",item.itemId) <> item.itemId then return false
    versionId = EnText(EnField(version,"versionId",invalid))
    if scope.provider = "silo" then return EnNativeId(versionId,"silo") <> ""
    mediaId = EnNativeId(EnField(version,"mediaId",invalid),"plex")
    partId = EnNativeId(EnField(version,"partId",invalid),"plex")
    if mediaId = "" or partId = "" then return false
    return versionId = scope.sourceId + ":" + item.itemId + ":" + mediaId + ":" + partId
end function

function EnInventoryResult(state as Object, stage as String, data as Object) as Object
    items = EnField(data,"items",invalid)
    if type(items) <> "roArray" then return EnFail(state,"ambiguous","invalid_inventory")
    pageLimit = 48
    maxPages = 4
    maxItems = 192
    if stage = "seasons"
        maxPages = 2
        maxItems = 96
    end if
    hasMore = false
    rawCount = items.Count()
    if state.scope.provider = "plex"
        if not data.DoesExist("hasMore") or type(data.hasMore) <> "Boolean" then return EnFail(state,"ambiguous","incomplete_inventory")
        offset = EnField(data,"offset",invalid)
        rawCount = EnField(data,"rawCount",invalid)
        nextOffset = EnField(data,"nextOffset",invalid)
        if not EnInteger(offset,0) or offset <> state.offset then return EnFail(state,"ambiguous","page_mismatch")
        if EnField(data,"pageSize",0) <> pageLimit or not EnInteger(rawCount,0) then return EnFail(state,"ambiguous","page_mismatch")
        if rawCount > pageLimit or items.Count() > rawCount then return EnFail(state,"ambiguous","page_mismatch")
        ' Filtering cannot hide an unreadable slot on an adjacency inventory.
        if items.Count() <> rawCount then return EnFail(state,"ambiguous","incomplete_inventory")
        hasMore = data.hasMore
        if hasMore and (rawCount = 0 or nextOffset <> offset + rawCount) then return EnFail(state,"ambiguous","page_mismatch")
        if not hasMore and nextOffset <> -1 then return EnFail(state,"ambiguous","page_mismatch")
    else
        if data.DoesExist("hasMore")
            if type(data.hasMore) <> "Boolean" then return EnFail(state,"ambiguous","incomplete_inventory")
            if data.hasMore then return EnFail(state,"ambiguous","incomplete_inventory")
        end if
        if EnText(EnField(data,"nextCursor","")) <> "" then return EnFail(state,"ambiguous","incomplete_inventory")
        if items.Count() > maxItems then return EnFail(state,"ambiguous","inventory_budget")
    end if
    state.pages = state.pages + 1
    collected = state.currentItems
    if stage = "seasons" then collected = state.seasons
    if stage = "adjacent"
        collected = []
        if EnField(state,"direction","next") = "previous" then collected = state.adjacentItems
    end if
    kind = "episode"
    if stage = "seasons" then kind = "season"
    expectedSeasonId = state.currentSeasonItemId
    expectedSeasonNumber = state.anchor.seasonNumber
    if stage = "adjacent"
        expectedSeasonId = state.nextSeasonItemId
        expectedSeasonNumber = state.nextSeasonNumber
    end if
    if collected.Count() + items.Count() > maxItems then return EnFail(state,"ambiguous","inventory_budget")
    for each raw in items
        item = EnCard(raw,state.scope,kind)
        if item = invalid then return EnFail(state,"ambiguous","invalid_inventory")
        if EnSeries(item,state.scope.provider) <> EnSeries(state.anchor,state.scope.provider) then return EnFail(state,"ambiguous","identity_mismatch")
        if EnIndex(collected,item.itemId) >= 0 then return EnFail(state,"ambiguous","duplicate_identity")
        if stage = "adjacent" and EnIndex(state.currentItems,item.itemId) >= 0 then return EnFail(state,"ambiguous","duplicate_identity")
        if stage <> "seasons"
            if item.seasonNumber <> expectedSeasonNumber then return EnFail(state,"ambiguous","identity_mismatch")
            if state.scope.provider = "plex"
                parent = EnParent(item)
                if parent <> "" and parent <> expectedSeasonId then return EnFail(state,"ambiguous","identity_mismatch")
                if parent = ""
                    item["parentItemId"] = expectedSeasonId
                    item["seasonItemId"] = expectedSeasonId
                end if
            end if
        end if
        collected.Push(item)
    end for
    if stage = "seasons"
        state.seasons = collected
    else if stage = "current"
        state["currentItems"] = collected
    end if
    ' The first native leaf of an adjacent season is enough to identify its head.
    ' The entire current inventory and season order establish the boundary.
    if stage = "adjacent"
        if EnField(state,"direction","next") = "previous"
            state["adjacentItems"] = collected
            if hasMore
                if state.pages >= maxPages then return EnFail(state,"ambiguous","inventory_budget")
                state.offset = EnField(data,"nextOffset",-1)
                return state
            end if
        end if
        if collected.Count() = 0 then return EnFail(state,"ambiguous","empty_adjacent")
        candidateIndex = 0
        if EnField(state,"direction","next") = "previous" then candidateIndex = collected.Count()-1
        state.candidate = collected[candidateIndex]
        state.stage = "candidate_detail"
        return state
    end if
    if hasMore
        if state.pages >= maxPages then return EnFail(state,"ambiguous","inventory_budget")
        state.offset = EnField(data,"nextOffset",-1)
        return state
    end if
    state.offset = 0
    state.pages = 0
    if stage = "seasons"
        state["seasonsComplete"] = true
        return EnSeasonResult(state)
    end if
    index = EnIndex(state.currentItems,state.anchor.itemId)
    if index < 0 then return EnFail(state,"ambiguous","missing_anchor")
    nativeAnchor = state.currentItems[index]
    if not EnCompatibleContext(state.anchor,nativeAnchor,state.scope.provider) then return EnFail(state,"ambiguous","identity_mismatch")
    state.anchor = EnMergeCard(state.anchor,nativeAnchor)
    candidateIndex = index + 1
    if EnField(state,"direction","next") = "previous" then candidateIndex = index - 1
    if candidateIndex >= 0 and candidateIndex < state.currentItems.Count()
        state.candidate = state.currentItems[candidateIndex]
        state["nextSeasonItemId"] = state.currentSeasonItemId
        state["nextSeasonNumber"] = state.anchor.seasonNumber
        state.stage = "candidate_detail"
        return state
    end if
    if state.seasonsComplete then return EnSeasonResult(state)
    state.stage = "seasons"
    return state
end function

function EnSeasonResult(state as Object) as Object
    seasons = state.seasons
    matches = []
    for index = 0 to seasons.Count() - 1
        season = seasons[index]
        if state.scope.provider = "plex" and state.currentSeasonItemId <> ""
            if season.itemId = state.currentSeasonItemId then matches.Push(index)
        else if season.seasonNumber = state.anchor.seasonNumber
            matches.Push(index)
        end if
    end for
    if matches.Count() <> 1 then return EnFail(state,"ambiguous","missing_season")
    index = matches[0]
    current = seasons[index]
    if current.seasonNumber <> state.anchor.seasonNumber then return EnFail(state,"ambiguous","identity_mismatch")
    state["currentSeasonItemId"] = current.itemId
    if state.scope.provider = "plex"
        state.anchor["parentItemId"] = current.itemId
        state.anchor["seasonItemId"] = current.itemId
    else
        ' Silo's episode endpoint selects a season by number; duplicates cannot
        ' be distinguished even when their season content IDs differ.
        seenNumbers = {}
        for each season in seasons
            key = season.seasonNumber.ToStr()
            if seenNumbers.DoesExist(key) then return EnFail(state,"ambiguous","duplicate_season")
            seenNumbers[key] = true
        end for
    end if
    if state.currentItems.Count() = 0
        state.stage = "current"
        return state
    end if
    adjacentIndex = index + 1
    if EnField(state,"direction","next") = "previous" then adjacentIndex = index - 1
    if adjacentIndex < 0 or adjacentIndex >= seasons.Count() then return EnFail(state,"verified_end","")
    following = seasons[adjacentIndex]
    state["nextSeasonItemId"] = following.itemId
    state["nextSeasonNumber"] = following.seasonNumber
    state.stage = "adjacent"
    return state
end function

function EnScope(raw as Dynamic) as Dynamic
    if type(raw) <> "roAssociativeArray" then return invalid
    provider = EnText(EnField(raw,"provider",invalid))
    if provider <> "plex" and provider <> "silo" then return invalid
    sourceId = EnText(EnField(raw,"sourceId",invalid))
    profileId = EnText(EnField(raw,"profileId",invalid))
    if sourceId = "" or Left(sourceId,5) <> provider + ":" or not raw.DoesExist("profileId") then return invalid
    if type(raw.profileId) <> "String" and type(raw.profileId) <> "roString" then return invalid
    generation = EnField(raw,"generation",invalid)
    lookupId = EnText(EnField(raw,"lookupId",invalid))
    if not EnInteger(generation,0) or not EnLookupId(lookupId) then return invalid
    scope = {provider:provider,sourceId:sourceId,profileId:profileId,generation:generation,lookupId:lookupId}
    for each field in ["anchorItemId","playbackSessionId"]
        if raw.DoesExist(field)
            value = EnField(raw,field,invalid)
            if type(value) <> "String" and type(value) <> "roString" then return invalid
            if field = "anchorItemId"
                if EnNativeId(value,provider) = "" then return invalid
            else
                if Len(value) > 256 or not CreateObject("roRegex","^[A-Za-z0-9_.:-]*$","").IsMatch(value) then return invalid
            end if
            scope[field] = value
        end if
    end for
    return scope
end function

function EnCard(raw as Dynamic, scope as Object, kind as String) as Dynamic
    if type(raw) <> "roAssociativeArray" then return invalid
    if EnField(raw,"sourceId",invalid) <> scope.sourceId or EnField(raw,"provider",scope.provider) <> scope.provider then return invalid
    if EnField(raw,"profileId",scope.profileId) <> scope.profileId then return invalid
    if EnField(raw,"type","") <> kind or EnField(raw,"extraType","") <> "" then return invalid
    itemId = EnNativeId(EnField(raw,"itemId",invalid),scope.provider)
    if itemId = "" then return invalid
    title = Left(EnText(EnField(raw,"title","")),120)
    if Instr(1,title,Chr(10)) > 0 or Instr(1,title,Chr(13)) > 0 then title = ""
    card = {provider:scope.provider,sourceId:scope.sourceId,itemId:itemId,type:kind,title:title,seasonNumber:EnNumber(EnField(raw,"seasonNumber",-1),-1),episodeNumber:EnNumber(EnField(raw,"episodeNumber",-1),-1)}
    for each field in ["seriesItemId","seriesId","parentItemId","seasonItemId"]
        card[field] = EnNativeId(EnField(raw,field,""),scope.provider)
    end for
    for each field in ["durationMs","resumeMs"]
        value = EnNumber(EnField(raw,field,0),0)
        if value < 0 or value > 86400000 then value = 0
        card[field] = value
    end for
    card.watched = EnField(raw,"watched",false) = true
    if kind = "season" and not EnInteger(card.seasonNumber,0) then return invalid
    return card
end function

function EnCompatibleContext(before as Object, after as Object, provider as String) as Boolean
    beforeSeries = EnSeries(before,provider)
    if beforeSeries <> "" and EnSeries(after,provider) <> beforeSeries then return false
    if provider = "plex"
        parent = EnParent(before)
        if parent <> "" and EnParent(after) <> parent then return false
    end if
    for each field in ["seasonNumber","episodeNumber"]
        value = EnField(before,field,-1)
        if EnInteger(value,0) and EnField(after,field,-1) <> value then return false
    end for
    return true
end function

function EnMergeCard(before as Object, after as Object) as Object
    merged = EnClone(before)
    for each field in after
        merged[field] = after[field]
    end for
    return merged
end function

function EnRequestMatches(expected as Object, actual as Dynamic) as Boolean
    if type(actual) <> "roAssociativeArray" then return false
    if EnField(expected,"direction","next") <> EnField(actual,"direction","next") then return false
    for each field in ["action","stage","sequence","anchorId"]
        if EnField(actual,field,invalid) <> expected[field] then return false
    end for
    for each field in ["scope","params"]
        value = EnField(actual,field,invalid)
        if type(value) <> "roAssociativeArray" then return false
        if value.Count() <> expected[field].Count() then return false
        for each key in expected[field]
            if EnField(value,key,invalid) <> expected[field][key] then return false
        end for
    end for
    return true
end function

function EnFail(state as Object, status as String, code as String) as Object
    state.status = status
    state["errorCode"] = code
    state.stage = "done"
    state.candidate = invalid
    state.proof = invalid
    return state
end function

function EnSafeError(raw as Dynamic) as String
    code = EnText(raw)
    for each allowed in ["lookup_budget","timeout","network_error","network_unavailable","session_changed","auth_required","profile_required","profile_locked","not_found","rate_limited","response_too_large"]
        if code = allowed then return code
    end for
    return "network_error"
end function

function EnSeries(item as Object, provider as String) as String
    field = "seriesItemId"
    if provider = "silo" then field = "seriesId"
    return EnText(EnField(item,field,""))
end function

function EnParent(item as Object) as String
    parent = EnText(EnField(item,"parentItemId",""))
    if parent = "" then parent = EnText(EnField(item,"seasonItemId",""))
    return parent
end function

function EnIndex(items as Object, itemId as String) as Integer
    for index = 0 to items.Count() - 1
        if EnField(items[index],"itemId","") = itemId then return index
    end for
    return -1
end function

function EnNativeId(value as Dynamic, provider as String) as String
    value = EnText(value)
    pattern = "^[A-Za-z0-9_-]{1,128}$"
    if provider = "silo" then pattern = "^[A-Za-z0-9_.:-]{1,256}$"
    if not CreateObject("roRegex",pattern,"").IsMatch(value) then return ""
    return value
end function

function EnLookupId(value as Dynamic) as Boolean
    value = EnText(value)
    if value = "" or Len(value) > 128 then return false
    return CreateObject("roRegex","^[A-Za-z0-9_.:-]+$","").IsMatch(value)
end function

function EnInteger(value as Dynamic, minimum as Integer) as Boolean
    kind = type(value)
    if kind <> "Integer" and kind <> "roInt" and kind <> "roInteger" and kind <> "LongInteger" and kind <> "roLongInteger" and kind <> "Float" and kind <> "roFloat" and kind <> "Double" and kind <> "roDouble" then return false
    if value < minimum or value > 2147483599 then return false
    return value = Int(value)
end function

function EnNumber(value as Dynamic, fallback as Integer) as Dynamic
    kind = type(value)
    if kind = "Integer" or kind = "roInt" or kind = "roInteger" or kind = "LongInteger" or kind = "roLongInteger" or kind = "Float" or kind = "roFloat" or kind = "Double" or kind = "roDouble" then return value
    return fallback
end function

function EnText(value as Dynamic) as String
    if type(value) = "String" or type(value) = "roString" then return value
    return ""
end function

function EnField(raw as Dynamic, field as String, fallback as Dynamic) as Dynamic
    if type(raw) <> "roAssociativeArray" then return fallback
    if not raw.DoesExist(field) or raw[field] = invalid then return fallback
    return raw[field]
end function

function EnClone(raw as Dynamic) as Dynamic
    if type(raw) = "roAssociativeArray"
        copy = {}
        for each field in raw
            copy[field] = EnClone(raw[field])
        end for
        return copy
    else if type(raw) = "roArray"
        copy = []
        for each item in raw
            copy.Push(EnClone(item))
        end for
        return copy
    end if
    return raw
end function
