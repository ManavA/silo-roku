' Volatile delivery lane; callers own dispatch, timers and retirement.
' Load with ServerUrlPolicy.brs. State holds the normalized source URL, but no
' credentials, media URLs, headers or playback plan. Take reserves one event:
' call DispatchFailed on queue refusal or Complete once after transport.
' Terminal cleanup uses the captured scope even after navigation.
function ProgressDeliveryBind(raw as Dynamic, scope as Dynamic) as Dynamic
    active = PdScope(scope)
    if active = invalid then return invalid
    result = {scope:active,sequence:0,serial:0,pending:invalid,inFlight:invalid,terminal:false}
    if not PdScopeMatches(PdField(raw,"scope",invalid),active) then return result
    result["sequence"] = PdInteger(PdField(raw,"sequence",0),0,2147483646,0)
    result["serial"] = PdInteger(PdField(raw,"serial",0),0,2147483646,0)
    result["terminal"] = PdField(raw,"terminal",false) = true
    result["pending"] = PdEvent(PdField(raw,"pending",invalid),active)
    result["inFlight"] = PdEvent(PdField(raw,"inFlight",invalid),active)
    return result
end function

function ProgressDeliveryOffer(raw as Dynamic, scope as Dynamic, action as String, params as Dynamic, nowMs as Double) as Object
    state = PdState(raw)
    result = {state:state,accepted:false}
    if state = invalid or not PdScopeMatches(state.scope,scope) then return result
    if state.terminal then return result
    if action <> "playback_progress" and action <> "playback_stop" then return result
    sample = PdSample(params,state.scope,action)
    if sample = invalid then return result
    if state.sequence >= 2147483646 or state.serial >= 2147483646 then return result
    sequence = state.sequence + 1
    if sample.sequence > sequence then sequence = sample.sequence
    state["sequence"] = sequence
    state["serial"] = state.serial + 1
    sample["sequence"] = sequence
    state["pending"] = {eventId:"progress-" + state.serial.ToStr(),action:action,params:sample,attempts:0,nextAttemptAt:nowMs}
    if action = "playback_stop" then state["terminal"] = true
    result["accepted"] = true
    return result
end function

function ProgressDeliveryTake(raw as Dynamic, scope as Dynamic, nowMs as Double) as Object
    state = PdState(raw)
    result = {state:state,event:invalid,waitMs:0}
    if state = invalid or not PdScopeMatches(state.scope,scope) then return result
    if state.inFlight <> invalid or state.pending = invalid then return result
    if state.pending.nextAttemptAt > nowMs
        result["waitMs"] = state.pending.nextAttemptAt - nowMs
        return result
    end if
    event = state.pending
    event["attempts"] = event.attempts + 1
    state["pending"] = invalid
    state["inFlight"] = event
    result["event"] = event
    return result
end function

function ProgressDeliveryComplete(raw as Dynamic, scope as Dynamic, eventId as String, ok as Boolean, errorCode as String, nowMs as Double) as Dynamic
    state = PdState(raw)
    if not PdFlightMatches(state,scope,eventId) then return state
    event = state.inFlight
    state["inFlight"] = invalid
    ' Newest pending progress, or terminal stop, supersedes a failed old sample.
    if ok or state.pending <> invalid then return state
    if not PdRetryable(errorCode) or event.attempts >= 3 then return state
    delayMs = 1000
    if event.attempts = 2 then delayMs = 2000
    event["nextAttemptAt"] = nowMs + delayMs
    state["pending"] = event
    return state
end function

function ProgressDeliveryDispatchFailed(raw as Dynamic, scope as Dynamic, eventId as String) as Dynamic
    state = PdState(raw)
    if not PdFlightMatches(state,scope,eventId) then return state
    event = state.inFlight
    state["inFlight"] = invalid
    if state.pending = invalid
        event["attempts"] = event.attempts - 1
        state["pending"] = event
    end if
    return state
end function

function PdState(raw as Dynamic) as Dynamic
    if type(raw) <> "roAssociativeArray" then return invalid
    return ProgressDeliveryBind(raw,PdField(raw,"scope",invalid))
end function

function PdScope(raw as Dynamic) as Dynamic
    if type(raw) <> "roAssociativeArray" then return invalid
    provider = PdField(raw,"provider","")
    sourceId = PdField(raw,"sourceId","")
    profileId = PdField(raw,"profileId",invalid)
    sessionId = PdField(raw,"sessionId","")
    generation = PdInteger(PdField(raw,"generation",invalid),0,2147483646,-1)
    if provider <> "plex" and provider <> "silo" then return invalid
    if not PdSourceId(sourceId,provider) then return invalid
    ' Plex direct play has no transcode/server session. Silo's playback routes
    ' require the opaque server session, while generation fences Plex teardown.
    if not PdIdentifier(profileId,256,true) or not PdOpaqueId(sessionId,256,provider = "plex") then return invalid
    if generation < 0 then return invalid
    return {provider:provider,sourceId:sourceId,profileId:profileId,generation:generation,sessionId:sessionId}
end function

function PdScopeMatches(left as Dynamic, right as Dynamic) as Boolean
    if type(left) <> "roAssociativeArray" or type(right) <> "roAssociativeArray" then return false
    for each field in ["provider","sourceId","profileId","generation","sessionId"]
        if PdField(left,field,invalid) <> PdField(right,field,invalid) then return false
    end for
    return true
end function

function PdSourceId(value as Dynamic, provider as String) as Boolean
    if type(value) <> "String" and type(value) <> "roString" then return false
    if Len(value) > 512 or Len(value) <= 5 then return false
    if Left(value,5) <> provider + ":" then return false
    identity = Mid(value,6)
    if provider = "silo" and (Left(identity,8) = "https://" or Left(identity,7) = "http://")
        normalized = NormalizeServerUrl(identity)
        return normalized.ok and PdField(normalized,"url","") = identity
    end if
    return PdIdentifier(value,512,false)
end function

function PdSample(raw as Dynamic, scope as Object, action as String) as Dynamic
    if type(raw) <> "roAssociativeArray" then return invalid
    itemId = PdField(raw,"itemId","")
    sessionId = PdField(raw,"sessionId","")
    if sessionId <> scope.sessionId then return invalid
    cleanupWithoutItem = scope.provider = "silo" and action = "playback_stop" and PdField(raw,"persistProgress",true) = false
    if not PdIdentifier(itemId,256,cleanupWithoutItem) then return invalid
    if scope.provider = "plex"
        if not CreateObject("roRegex","^[0-9]{1,20}$","").IsMatch(itemId) then return invalid
    end if
    position = PdMilliseconds(PdField(raw,"positionMs",invalid))
    duration = PdMilliseconds(PdField(raw,"durationMs",0))
    sequence = PdInteger(PdField(raw,"sequence",0),0,2147483646,-1)
    if position < 0 or duration < 0 or sequence < 0 then return invalid
    paused = PdField(raw,"isPaused",invalid)
    if type(paused) <> "Boolean" and type(paused) <> "roBoolean" then return invalid
    playbackState = PdField(raw,"state","")
    if playbackState <> "playing" and playbackState <> "paused" and playbackState <> "stopped" then return invalid
    if action = "playback_progress" and playbackState = "stopped" then return invalid
    if action = "playback_stop"
        playbackState = "stopped"
        paused = false
    end if
    result = {itemId:itemId,sessionId:sessionId,positionMs:position,durationMs:duration,state:playbackState,sequence:sequence,isPaused:paused}
    if action = "playback_stop" and PdField(raw,"persistProgress",true) = false then result["persistProgress"] = false
    for each key in ["transcodeSessionId","installationId","stopId"]
        if raw.DoesExist(key)
            value = raw[key]
            if not PdOpaqueId(value,256,true) then return invalid
            result[key] = value
        end if
    end for
    if scope.provider = "silo" and action = "playback_stop"
        if PdField(result,"stopId","") = "" then return invalid
    end if
    return result
end function

function PdEvent(raw as Dynamic, scope as Object) as Dynamic
    if type(raw) <> "roAssociativeArray" then return invalid
    action = PdField(raw,"action","")
    if action <> "playback_progress" and action <> "playback_stop" then return invalid
    eventId = PdField(raw,"eventId","")
    if not PdIdentifier(eventId,32,false) then return invalid
    if not CreateObject("roRegex","^progress-[0-9]+$","").IsMatch(eventId) then return invalid
    params = PdSample(PdField(raw,"params",invalid),scope,action)
    if params = invalid then return invalid
    attempts = PdInteger(PdField(raw,"attempts",invalid),0,3,-1)
    dueAt = PdField(raw,"nextAttemptAt",invalid)
    if attempts < 0 or not PdNumber(dueAt) then return invalid
    if dueAt < 0 then return invalid
    return {eventId:eventId,action:action,params:params,attempts:attempts,nextAttemptAt:dueAt}
end function

function PdFlightMatches(state as Dynamic, scope as Dynamic, eventId as String) as Boolean
    if state = invalid then return false
    if not PdScopeMatches(state.scope,scope) then return false
    if state.inFlight = invalid then return false
    return state.inFlight.eventId = eventId
end function

function PdRetryable(code as String) as Boolean
    return code = "timeout" or code = "network_timeout" or code = "network_error" or code = "network_unavailable" or code = "server_error" or code = "rate_limited" or code = "task_unavailable"
end function

function PdOpaqueId(value as Dynamic, maximum as Integer, allowEmpty as Boolean) as Boolean
    if type(value) <> "String" and type(value) <> "roString" then return false
    if Len(value) > maximum then return false
    if value = "" then return allowEmpty
    if Instr(1,value,"://") > 0 then return false
    return CreateObject("roRegex","^[A-Za-z0-9_.:/-]+$","").IsMatch(value)
end function

function PdMilliseconds(value as Dynamic) as Integer
    if not PdNumber(value) then return -1
    if value < 0 or value > 604800000 then return -1
    return Int(value)
end function

function PdIdentifier(value as Dynamic, maximum as Integer, allowEmpty as Boolean) as Boolean
    if type(value) <> "String" and type(value) <> "roString" then return false
    if Len(value) > maximum then return false
    if value = "" then return allowEmpty
    return CreateObject("roRegex","^[A-Za-z0-9_.:-]+$","").IsMatch(value)
end function

function PdNumber(value as Dynamic) as Boolean
    kind = type(value)
    return kind = "Integer" or kind = "roInt" or kind = "roInteger" or kind = "LongInteger" or kind = "roLongInteger" or kind = "Double" or kind = "roDouble" or kind = "Float" or kind = "roFloat"
end function

function PdInteger(value as Dynamic, minimum as Integer, maximum as Integer, fallback as Integer) as Integer
    if not PdNumber(value) then return fallback
    if value < minimum or value > maximum then return fallback
    if value <> Int(value) then return fallback
    return Int(value)
end function

function PdField(raw as Dynamic, key as String, fallback as Dynamic) as Dynamic
    if type(raw) <> "roAssociativeArray" then return fallback
    if not raw.DoesExist(key) or raw[key] = invalid then return fallback
    return raw[key]
end function
