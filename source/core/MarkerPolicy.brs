' Optional marker hydration is independent of provider allocation and progress.
' Only rendered native time may select a Skip action; a saved Resume stays owed.
function MpField(value as Dynamic, key as String, fallback as Dynamic) as Dynamic
    if type(value) <> "roAssociativeArray" then return fallback
    if not value.DoesExist(key) then return fallback
    return value[key]
end function

function MpString(value as Dynamic) as Boolean
    return type(value) = "String" or type(value) = "roString"
end function

function MpText(value as Dynamic, empty = false as Boolean) as Boolean
    if not MpString(value) then return false
    if Len(value) > 256 or (not empty and value = "") then return false
    if Instr(1,value,"://") > 0 then return false
    for index = 1 to Len(value)
        code = Asc(Mid(value,index,1))
        if code < 32 or code = 127 then return false
    end for
    return true
end function

' Source IDs are private captured identities. Silo includes its canonical base
' URL in that identity; it must never be projected into renderer/diagnostic DTOs.
function MpScopeString(value as Dynamic) as Boolean
    if not MpString(value) then return false
    if Len(value)<=5 or Len(value)>512 then return false
    for index = 1 to Len(value)
        code = Asc(Mid(value,index,1))
        if code<=32 or code=127 then return false
    end for
    return true
end function

function MpSourceIdentity(value as Dynamic, provider as String) as Boolean
    if not MpScopeString(value) then return false
    if Left(value,Len(provider)+1)<>provider+":" then return false
    identity = Mid(value,Len(provider)+2)
    if provider="silo" and (Left(identity,8)="https://" or Left(identity,7)="http://")
        canonical = NormalizeServerUrl(identity)
        return canonical.ok and MpField(canonical,"url",invalid)=identity
    end if
    return Instr(1,value,"://")=0
end function

function MpNumber(value as Dynamic) as Boolean
    kind = type(value)
    if kind <> "Integer" and kind <> "roInt" and kind <> "roInteger" and kind <> "LongInteger" and kind <> "roLongInteger" and kind <> "Float" and kind <> "roFloat" and kind <> "Double" and kind <> "roDouble" then return false
    return value = value and Abs(value) <= 2147483647
end function

function MpInteger(value as Dynamic, minimum as Integer) as Boolean
    if not MpNumber(value) then return false
    return value >= minimum and value = Int(value)
end function

function MpTrue(value as Dynamic) as Boolean
    if type(value) <> "Boolean" and type(value) <> "roBoolean" then return false
    return value
end function

function MpCopy(value as Object) as Object
    copy = {}
    for each key in value
        copy[key] = value[key]
    end for
    return copy
end function

function MarkerCreate(config as Dynamic) as Dynamic
    scope = MpField(config,"scope",invalid)
    provider = MpField(scope,"provider","")
    if not MpString(provider) then return invalid
    if provider <> "plex" and provider <> "silo" then return invalid
    sourceId = MpField(scope,"sourceId",invalid)
    if not MpSourceIdentity(sourceId,provider) then return invalid
    if not MpText(MpField(scope,"profileId",invalid),true) or not MpInteger(MpField(scope,"generation",invalid),0) then return invalid
    for each key in ["attemptId","itemId","versionId"]
        if not MpText(MpField(config,key,invalid)) then return invalid
    end for
    duration = MpField(config,"durationMs",invalid)
    offset = MpField(config,"timelineOffsetMs",0)
    if not MpNumber(duration) or not MpNumber(offset) then return invalid
    if duration < 0 or duration > 604800000 or offset < 0 or offset > 604800000 then return invalid
    for each key in ["canSeek","relativeTimeline"]
        value = MpField(config,key,invalid)
        if type(value) <> "Boolean" and type(value) <> "roBoolean" then return invalid
    end for
    if not config.relativeTimeline then offset = 0
    captured = {provider:scope.provider,sourceId:scope.sourceId,profileId:scope.profileId,generation:scope.generation}
    return {scope:captured,attemptId:config.attemptId,itemId:config.itemId,versionId:config.versionId,
        durationMs:duration,offsetMs:offset,canSeek:config.canSeek,clipId:-1,renderedEpoch:-1,renderedMs:-1,
        nativeState:"starting",landed:false,retired:false,read:"none",markers:[],revision:0}
end function

function MpMatches(state as Object, event as Dynamic) as Boolean
    scope = MpField(event,"scope",invalid)
    for each field in ["provider","sourceId","profileId","generation"]
        if MpField(scope,field,invalid) <> state.scope[field] then return false
    end for
    return MpField(event,"attemptId",invalid) = state.attemptId and MpField(event,"versionId",invalid) = state.versionId
end function

function MpOwner(state as Object) as Object
    return {scope:MpCopy(state.scope),attemptId:state.attemptId,versionId:state.versionId,itemId:state.itemId,clipId:state.clipId}
end function

function MpMarkers(raw as Dynamic, duration as Double) as Object
    markers = []
    if type(raw) <> "roArray" then return markers
    scanned = 0
    for each marker in raw
        scanned++
        if scanned > 64 or markers.Count() >= 32 then exit for
        kind = MpField(marker,"type",MpField(marker,"kind",""))
        start = MpField(marker,"startMs",invalid)
        finish = MpField(marker,"endMs",invalid)
        if MpString(kind) and MpNumber(start) and MpNumber(finish)
            if (kind = "intro" or kind = "recap" or kind = "credits") and start >= 0 and finish > start and finish <= 604800000
                if duration <= 0 or finish <= duration
                    markers.Push({type:kind,startMs:start,endMs:finish,isFinal:MpTrue(MpField(marker,"isFinal",false))})
                end if
            end if
        end if
    end for
    return markers
end function

function MarkerProjection(state as Dynamic) as Object
    projection = {available:false,action:invalid}
    if type(state) <> "roAssociativeArray" then return projection
    if state.retired or not state.landed or not state.canSeek or state.durationMs <= 0 or state.renderedMs < 0 then return projection
    if state.nativeState <> "playing" and state.nativeState <> "paused" then return projection
    chosen = invalid
    chosenIndex = -1
    for index = 0 to state.markers.Count()-1
        marker = state.markers[index]
        target = marker.endMs - state.offsetMs
        if state.renderedMs >= marker.startMs and state.renderedMs < marker.endMs and marker.endMs > state.renderedMs + 250 and target >= 0
            better = chosen = invalid
            if chosen <> invalid then better = marker.startMs < chosen.startMs or (marker.startMs = chosen.startMs and marker.endMs < chosen.endMs)
            if better
                chosen = marker
                chosenIndex = index
            end if
        end if
    end for
    if chosen = invalid then return projection
    label = "Skip Intro"
    if chosen.type = "recap" then label = "Skip Recap"
    if chosen.type = "credits" then label = "Skip Credits"
    projection.available = true
    projection.action = {id:"marker-" + state.revision.ToStr() + "-" + chosenIndex.ToStr(),label:label,type:chosen.type,
        startMs:chosen.startMs,endMs:chosen.endMs,isFinal:chosen.isFinal,nativeTargetMs:chosen.endMs-state.offsetMs,
        attemptId:state.attemptId,versionId:state.versionId,itemId:state.itemId,clipId:state.clipId,renderedEpoch:state.renderedEpoch}
    return projection
end function

function MarkerReduce(previous as Dynamic, event as Dynamic) as Object
    result = {state:previous,effects:[],accepted:false,render:invalid}
    if type(previous) <> "roAssociativeArray" or type(event) <> "roAssociativeArray" then return result
    if previous.retired then return result
    kind = MpField(event,"kind","")
    if not MpString(kind) then return result
    state = MpCopy(previous)
    if kind = "retire"
        state.retired = true
        state.markers = []
        state.renderedMs = -1
        state.read = "done"
    else
        if not MpMatches(state,event) then return result
        if kind = "native"
            status = MpField(event,"status",invalid)
            if MpField(status,"attemptId",invalid) <> state.attemptId or MpField(status,"mode",invalid) <> "playback" then return result
            clip = MpField(status,"clipId",invalid)
            if not MpInteger(clip,0) then return result
            if state.clipId >= 0 and clip <> state.clipId then return result
            nativeState = MpField(status,"state",invalid)
            if not MpString(nativeState) then return result
            if nativeState <> "playing" and nativeState <> "paused" and nativeState <> "buffering" and nativeState <> "finished" and nativeState <> "stopping" and nativeState <> "stopped" and nativeState <> "error" then return result
            state.clipId = clip
            state.nativeState = nativeState
            state.landed = MpTrue(MpField(event,"landed",false))
            state.renderedMs = -1
            state.renderedEpoch = -1
            rendered = MpField(status,"renderedPosition",invalid)
            renderedClip = MpField(status,"renderedClipId",invalid)
            epoch = MpField(status,"renderedEpoch",invalid)
            errorCode = MpField(status,"errorCode",invalid)
            valid = MpNumber(rendered) and MpInteger(renderedClip,0) and MpInteger(epoch,0) and MpInteger(errorCode,0)
            if valid
                if rendered >= 0 and rendered <= 604800 and renderedClip = clip and epoch = 0 and errorCode = 0
                    state.renderedMs = rendered * 1000 + state.offsetMs
                    state.renderedEpoch = epoch
                end if
            end if
            if nativeState = "playing" and state.read = "none" and MpInteger(errorCode,0) and errorCode = 0
                state.read = "pending"
                action = "markers"
                if state.scope.provider = "plex" then action = "detail"
                result.effects.Push({kind:"request",action:action,params:{itemId:state.itemId},purpose:"player_markers",scope:MpCopy(state.scope),owner:MpOwner(state)})
            end if
        else if kind = "result"
            if state.read <> "pending" then return result
            if MpField(event,"itemId",invalid) <> state.itemId or MpField(event,"clipId",invalid) <> state.clipId then return result
            state.read = "done"
            if MpTrue(MpField(event,"ok",false))
                data = MpField(event,"data",invalid)
                if MpField(data,"itemId",invalid) = state.itemId and MpField(data,"versionId",invalid) = state.versionId
                    state.markers = MpMarkers(MpField(data,"markers",invalid),state.durationMs)
                    state.revision++
                end if
            end if
        else if kind = "skip"
            if MpField(event,"itemId",invalid) <> state.itemId or MpField(event,"clipId",invalid) <> state.clipId or MpField(event,"renderedEpoch",invalid) <> state.renderedEpoch then return result
            projection = MarkerProjection(state)
            if not projection.available then return result
            if MpField(event,"actionId",invalid) <> projection.action.id then return result
            result.effects.Push({kind:"seek",attemptId:state.attemptId,positionMs:projection.action.nativeTargetMs,
                markerFence:{versionId:state.versionId,clipId:state.clipId,renderedEpoch:state.renderedEpoch}})
        else
            return result
        end if
    end if
    result.state = state
    result.accepted = true
    projection = MarkerProjection(state)
    if FormatJson(projection) <> FormatJson(MarkerProjection(previous)) then result.render = projection
    return result
end function
