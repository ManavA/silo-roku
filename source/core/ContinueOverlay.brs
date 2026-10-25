' Continue Watching outcome policy. References: Android 45774f8b
' domain/home/continuing/ContinueOverlay.kt and current tvOS HomeStore.swift
' 212-216, 512-562, 700-812. Only 32 compact edits live in the active scope.
' No tokens, stream/artwork URLs, headers, or playback plans are retained.

' An explicit scene transition rebinds generation while preserving same-viewer
' outcomes. A source/profile change drops them; asynchronous writes still need
' an exact source/profile/generation match after the transition.
function ContinueOverlayBind(state as Dynamic, scope as Object) as Object
    bound = {sourceId:CoField(scope,"sourceId",""),profileId:CoField(scope,"profileId",""),generation:CoField(scope,"generation",-1),lastRefreshGeneration:-1,edits:[]}
    if CoField(state,"sourceId",invalid) = bound.sourceId and CoField(state,"profileId",invalid) = bound.profileId
        bound["lastRefreshGeneration"] = CoField(state,"lastRefreshGeneration",-1)
        edits = CoField(state,"edits",[])
        if type(edits) = "roArray"
            for each edit in edits
                if bound.edits.Count() >= 32 then exit for
                bound.edits.Push(edit)
            end for
        end if
    end if
    return bound
end function

function ContinueOverlayRecord(state as Dynamic, scope as Object, rawItem as Dynamic, positionMs as Dynamic, durationMs as Dynamic, started as Boolean, finished as Boolean, rawSuccessor = invalid as Dynamic, successorProof = invalid as Dynamic) as Dynamic
    if not CoScopeMatches(state,scope) or not started then return state
    item = CoOwnedCard(rawItem,scope)
    if item = invalid then return state
    position = CoNumber(positionMs,-1)
    duration = CoNumber(durationMs,0)
    if position < 0 or position > 86400000 or duration < 0 or duration > 86400000 then return state
    if duration > 0 and position > duration then position = duration
    completed = finished or (duration > 0 and position * 100 >= duration * 95)
    item["resumeMs"] = position
    item["durationMs"] = duration
    mode = "promote"
    successor = invalid
    if completed
        mode = "complete"
        item["resumeMs"] = 0
        item["watched"] = true
        successor = CoVerifiedSuccessor(item,rawSuccessor,scope,successorProof)
        if successor <> invalid then mode = "advance"
    end if
    edits = [{mode:mode,item:item,successor:successor,refreshes:0}]
    for each previous in CoField(state,"edits",[])
        if edits.Count() >= 32 then exit for
        if CoField(CoField(previous,"item",{}),"itemId","") <> item.itemId
            if CoField(previous,"mode","") = "advance" and CoField(CoField(previous,"successor",{}),"itemId","") = item.itemId
                retiredAdvance = CoCopy(previous)
                retiredAdvance["mode"] = "complete"
                retiredAdvance["successor"] = invalid
                edits.Push(retiredAdvance)
            else
                edits.Push(previous)
            end if
        end if
    end for
    nextState = ContinueOverlayBind(state,scope)
    nextState["edits"] = edits
    return nextState
end function

' A successful watched mutation is a newer user action than playback. Mark
' watched completes the title; Mark unwatched patches cached facts without
' promoting a new Continue card or allowing an old completion to undo it.
function ContinueOverlayWatched(state as Dynamic, scope as Object, rawItem as Dynamic, watched as Boolean) as Dynamic
    if not CoScopeMatches(state,scope) then return state
    item = CoOwnedCard(rawItem,scope)
    if item = invalid then return state
    item["watched"] = watched
    nextState = ContinueOverlayRecord(state,scope,item,item.resumeMs,item.durationMs,true,watched,invalid)
    if nextState.edits.Count() = 0 then return state
    newest = nextState.edits[0]
    if newest.item.itemId <> item.itemId then return state
    if not watched
        newest["mode"] = "patch"
        newest["successor"] = invalid
        newest.item["watched"] = false
        newest.item["resumeMs"] = item.resumeMs
    end if
    return nextState
end function

' Patch bookmark/watched display facts on cached owned cards, without removing
' completed titles from normal library shelves or changing their route IDs.
function ContinueOverlayCards(state as Dynamic, scope as Object, cards as Object) as Object
    output = []
    for each raw in cards
        if output.Count() >= 101 then exit for
        card = raw
        if CoScopeMatches(state,scope) and CoOwnedCard(raw,scope) <> invalid
            for each edit in CoField(state,"edits",[])
                item = CoField(edit,"item",{})
                if CoField(raw,"itemId",invalid) = CoField(item,"itemId","")
                    card = CoCopy(raw)
                    card["resumeMs"] = CoField(item,"resumeMs",0)
                    card["watched"] = CoField(item,"watched",false)
                    exit for
                end if
            end for
        end if
        output.Push(card)
    end for
    return output
end function

' Apply first, then retire, matching tvOS: an edit shapes its third complete
' refresh and releases the following provider paint. Supplemental and Back
' paints do not count; repeated delivery in one generation counts only once.
function ContinueOverlayHome(state as Dynamic, scope as Object, rawCards as Object, completeRefresh as Boolean) as Object
    if not CoScopeMatches(state,scope) then return {state:state,items:rawCards}
    cards = ContinueOverlayCards(state,scope,rawCards)
    history = []
    other = []
    for each card in cards
        if CoHistory(card) and CoField(card,"sourceId","") = scope.sourceId
            history.Push(card)
        else
            other.Push(card)
        end if
    end for
    row = {rowId:"continue.overlay",rowTitle:"Continue watching",sectionType:"continue_watching"}
    if history.Count() > 0
        row = {rowId:CoField(history[0],"rowId","continue.overlay"),rowTitle:CoField(history[0],"rowTitle","Continue watching"),sectionType:CoField(history[0],"sectionType","continue_watching")}
    end if
    output = []
    suppressed = {}
    for each edit in CoField(state,"edits",[])
        item = edit.item
        if edit.mode <> "patch" then suppressed[item.itemId] = true
        promoted = invalid
        if edit.mode = "promote" then promoted = item
        if edit.mode = "advance"
            promoted = edit.successor
            suppressed[promoted.itemId] = true
        end if
        if promoted <> invalid
            index = CoCardIndex(history,promoted.itemId,scope.sourceId)
            card = CoCopy(promoted)
            if index >= 0
                card = CoCopy(history[index])
                card["resumeMs"] = CoField(promoted,"resumeMs",0)
                card["watched"] = CoField(promoted,"watched",false)
            else
                for each field in ["rowId","rowTitle","sectionType"]
                    card[field] = row[field]
                end for
            end if
            output.Push(card)
        end if
    end for
    for each card in history
        if output.Count() >= 100 then exit for
        if not suppressed.DoesExist(CoField(card,"itemId","")) then output.Push(card)
    end for
    for each card in other
        if output.Count() >= 100 then exit for
        output.Push(card)
    end for
    nextState = state
    if completeRefresh and CoField(state,"lastRefreshGeneration",-1) <> scope.generation
        nativeHistory = []
        for each card in rawCards
            if nativeHistory.Count() >= 100 then exit for
            if CoHistory(card) and CoField(card,"sourceId","") = scope.sourceId then nativeHistory.Push(card)
        end for
        nextState = CoRetire(state,scope,nativeHistory)
    end if
    return {state:nextState,items:output}
end function

function CoRetire(state as Object, scope as Object, history as Object) as Object
    nextState = ContinueOverlayBind(state,scope)
    nextState["lastRefreshGeneration"] = scope.generation
    kept = []
    expectedRank = 0
    agreeingPrefix = true
    for each edit in state.edits
        copy = CoCopy(edit)
        refreshes = CoNumber(CoField(edit,"refreshes",0),0) + 1
        index = CoCardIndex(history,edit.item.itemId,scope.sourceId)
        retire = refreshes >= 3
        if edit.mode = "complete" and index < 0 then retire = true
        if edit.mode = "advance"
            if index < 0 or CoCardIndex(history,edit.successor.itemId,scope.sourceId) >= 0 then retire = true
        else if edit.mode = "promote"
            if index < 0
                retire = true
            else
                agrees = index = expectedRank and Abs(CoNumber(CoField(history[index],"resumeMs",-1),-1) - edit.item.resumeMs) <= 1000
                if agreeingPrefix and agrees
                    retire = true
                    expectedRank++
                else
                    agreeingPrefix = false
                end if
            end if
        end if
        if not retire
            copy["refreshes"] = refreshes
            kept.Push(copy)
        end if
    end for
    nextState["edits"] = kept
    return nextState
end function

function CoOwnedCard(raw as Dynamic, scope as Object) as Dynamic
    if type(raw) <> "roAssociativeArray" then return invalid
    sourceId = CoField(scope,"sourceId","")
    if type(sourceId) <> "String" and type(sourceId) <> "roString" then return invalid
    if sourceId = "" or CoField(raw,"sourceId","") <> sourceId then return invalid
    if CoField(raw,"profileId",CoField(scope,"profileId","")) <> CoField(scope,"profileId","") then return invalid
    provider = Left(sourceId,4)
    if Left(sourceId,5) <> "plex:" and Left(sourceId,5) <> "silo:" then return invalid
    if CoField(raw,"provider",provider) <> provider then return invalid
    itemId = CoField(raw,"itemId","")
    title = CoField(raw,"title","")
    kind = CoField(raw,"type","")
    if (type(itemId) <> "String" and type(itemId) <> "roString") or (type(title) <> "String" and type(title) <> "roString") then return invalid
    if kind <> "movie" and kind <> "episode" then return invalid
    if CoField(raw,"extraType","") <> "" then return invalid
    allowed = "^[0-9]{1,20}$"
    if provider = "silo" then allowed = "^[A-Za-z0-9_.:-]{1,256}$"
    if not CreateObject("roRegex",allowed,"").IsMatch(itemId) then return invalid
    title = Left(title.Trim(),120)
    if title = "" or Instr(1,title,Chr(10)) > 0 or Instr(1,title,Chr(13)) > 0 then return invalid
    card = {provider:provider,sourceId:sourceId,itemId:itemId,type:kind,title:title,resumeMs:CoNumber(CoField(raw,"resumeMs",0),0),durationMs:CoNumber(CoField(raw,"durationMs",0),0),watched:CoField(raw,"watched",false) = true}
    if kind = "episode"
        for each field in ["seriesItemId","seriesId","parentItemId"]
            value = CoField(raw,field,"")
            if type(value) = "String" or type(value) = "roString"
                if CreateObject("roRegex",allowed,"").IsMatch(value) then card[field] = value
            end if
        end for
        card["seasonNumber"] = CoNumber(CoField(raw,"seasonNumber",-1),-1)
        card["episodeNumber"] = CoNumber(CoField(raw,"episodeNumber",-1),-1)
    end if
    return card
end function

' The existing Roku episode page proves consecutive same-season membership.
' Unknown parents, page gaps, and season transitions never invent a successor.
function CoVerifiedSuccessor(current as Object, raw as Dynamic, scope as Object, proof = invalid as Dynamic) as Dynamic
    if current.type <> "episode" then return invalid
    nextItem = CoOwnedCard(raw,scope)
    if nextItem = invalid then return invalid
    if nextItem.type <> "episode" or nextItem.itemId = current.itemId then return invalid
    seriesField = "seriesItemId"
    if current.provider = "silo" then seriesField = "seriesId"
    series = CoField(current,seriesField,"")
    if series = "" or CoField(nextItem,seriesField,"") <> series then return invalid
    if proof <> invalid
        if EpisodeNeighborsProofMatches(proof,current,nextItem,scope) then return nextItem
    end if
    if current.provider = "plex"
        parent = CoField(current,"parentItemId","")
        if parent = "" or CoField(nextItem,"parentItemId","") <> parent then return invalid
    end if
    season = CoField(current,"seasonNumber",-1)
    episode = CoField(current,"episodeNumber",-1)
    if season < 0 or episode < 1 or season <> Int(season) or episode <> Int(episode) then return invalid
    if CoField(nextItem,"seasonNumber",-1) <> season or CoField(nextItem,"episodeNumber",-1) <> episode + 1 then return invalid
    return nextItem
end function

function CoScopeMatches(state as Dynamic, scope as Dynamic) as Boolean
    if type(state) <> "roAssociativeArray" or type(scope) <> "roAssociativeArray" then return false
    for each field in ["sourceId","profileId","generation"]
        if not state.DoesExist(field) or not scope.DoesExist(field) then return false
        if state[field] <> scope[field] then return false
    end for
    return true
end function

function CoHistory(card as Dynamic) as Boolean
    rowId = CoField(card,"rowId","")
    section = CoField(card,"sectionType","")
    return rowId = "home.continue" or rowId = "home.ondeck" or rowId = "continue.overlay" or section = "continue_watching" or section = "on_deck"
end function

function CoCardIndex(cards as Object, itemId as String, sourceId as String) as Integer
    for index = 0 to cards.Count() - 1
        if CoField(cards[index],"itemId","") = itemId and CoField(cards[index],"sourceId","") = sourceId then return index
    end for
    return -1
end function

function CoCopy(raw as Object) as Object
    copy = {}
    for each field in raw
        copy[field] = raw[field]
    end for
    return copy
end function

function CoField(raw as Dynamic, field as String, fallback as Dynamic) as Dynamic
    if type(raw) <> "roAssociativeArray" then return fallback
    if not raw.DoesExist(field) or raw[field] = invalid then return fallback
    return raw[field]
end function

function CoNumber(value as Dynamic, fallback as Double) as Double
    kind = type(value)
    if kind = "Integer" or kind = "roInt" or kind = "roInteger" or kind = "LongInteger" or kind = "roLongInteger" or kind = "Float" or kind = "roFloat" or kind = "Double" or kind = "roDouble" then return value
    return fallback
end function
