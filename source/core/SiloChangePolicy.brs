' One private Silo change owner. Quality replaces only native transport; Versions
' replace the provider lease after its two independent retirement receipts.
function ScField(value as Dynamic, key as String, fallback = invalid as Dynamic) as Dynamic
    if type(value) <> "roAssociativeArray" then return fallback
    if value.DoesExist(key) then return value[key]
    return fallback
end function

function ScNumericType(value as Dynamic) as String
    return type(value)
end function

function ScNumber(value as Dynamic, maximum as Double) as Boolean
    kind = ScNumericType(value)
    if kind <> "Integer" and kind <> "roInt" and kind <> "roInteger" and kind <> "LongInteger" and kind <> "roLongInteger" and kind <> "Float" and kind <> "roFloat" and kind <> "Double" and kind <> "roDouble" then return false
    return value = value and value >= 0 and value <= maximum
end function

function ScInteger(value as Dynamic, maximum = 2147483646 as Double) as Boolean
    if not ScNumber(value,maximum) then return false
    return value = Int(value)
end function

function ScTrue(value as Dynamic) as Boolean
    if not SpBool(value) then return false
    return value
end function

' Trusted in-process copies retain native AA case-insensitive field semantics.
function ScCopy(value as Object) as Object
    copied = {}
    for each key in value
        copied[key] = value[key]
    end for
    return copied
end function

function ScScope(value as Dynamic, lease = false as Boolean) as Dynamic
    if ScField(value,"provider") <> "silo" then return invalid
    source = ScField(value,"sourceId"):profile = ScField(value,"profileId")
    if not PdSourceId(source,"silo") or not SpText(profile,256) then return invalid
    generation = ScField(value,"generation")
    if not ScInteger(generation) then return invalid
    scope = {provider:"silo",sourceId:source,profileId:profile,generation:generation}
    if lease
        session = ScField(value,"sessionId")
        if not SpOpaque(session) then return invalid
        scope["sessionId"] = session
    end if
    return scope
end function

function ScMatches(left as Dynamic, right as Dynamic, lease = false as Boolean) as Boolean
    a = ScScope(left,lease):b = ScScope(right,lease)
    if a = invalid or b = invalid then return false
    for each field in ["provider","sourceId","profileId","generation"]
        if a[field] <> b[field] then return false
    end for
    if lease then return a.sessionId = b.sessionId
    return true
end function

function ScSettled(transport as Dynamic, attempt as String, clip as Integer) as Boolean
    if ScField(transport,"attemptId") <> attempt or ScField(transport,"clipId") <> clip then return false
    if not ScTrue(ScField(transport,"ready")) or not SpBool(ScField(transport,"retired")) then return false
    if transport.retired then return false
    if ScField(transport,"seekTargetMs") <> -1 or ScField(transport,"cursorMs") <> -1 then return false
    if ScField(transport,"controlPending") <> "" or not SpBool(ScField(transport,"rePausePending")) then return false
    if transport.rePausePending then return false
    phase = ScField(transport,"phase")
    return phase = "hidden" or phase = "bar" or phase = "buttons"
end function

function ScRendered(plan as Object, native as Dynamic, attempt as String, clip as Integer) as Double
    if ScField(native,"attemptId") <> attempt or ScField(native,"mode") <> "playback" then return -1
    state = ScField(native,"state")
    if state <> "playing" and state <> "paused" then return -1
    current = ScField(native,"clipId"):rendered = ScField(native,"renderedClipId")
    if not ScInteger(current) or not ScInteger(rendered) then return -1
    if current <> clip or rendered <> clip then return -1
    epoch = ScField(native,"renderedEpoch"):code = ScField(native,"errorCode")
    if not ScInteger(epoch) or epoch <> 0 or not ScInteger(code) or code <> 0 then return -1
    seconds = ScField(native,"renderedPosition")
    if not ScNumber(seconds,604800) then return -1
    absolute = UiPlanPositionMs(seconds,plan,true)
    if not ScNumber(absolute,604800000) then return -1
    return Int(absolute+0.5)
end function

function ScProof(value as Dynamic, attempt as String, version as String, clip as Integer) as Dynamic
    if not SpFields(value,["attemptId","versionId","clipId","audioSafe","providerAudioIntent","versionDefaults","subtitleMode"],[]) then return invalid
    if value.attemptId <> attempt or value.versionId <> version or value.clipId <> clip then return invalid
    if not ScInteger(value.clipId) or not ScTrue(value.audioSafe) then return invalid
    if not SpBool(value.providerAudioIntent) or not SpBool(value.versionDefaults) then return invalid
    mode = value.subtitleMode
    if mode <> "unchanged" and mode <> "off" and mode <> "auto" then return invalid
    return {audioSafe:true,providerAudioIntent:value.providerAudioIntent,versionDefaults:value.versionDefaults,subtitleMode:mode}
end function

function ScRows(context as Object, detail as Object, fileId as String, changeKind as String, proof as Object) as Object
    rows = []
    if changeKind = "quality"
        if not SiloPlaybackCanReplan(context) then return rows
        for each quality in context.availableQualities
            label = quality.label
            title = ""
            if label = "original" then title = "Original"
            if label = "4k" then title = "Up to 4K"
            if label = "1080p_high" then title = "Up to 1080p (higher bitrate)"
            if label = "1080p" then title = "Up to 1080p"
            if label = "720p" then title = "Up to 720p"
            if title <> "" and rows.Count() < 5
                rows.Push({handle:"sc-1-"+rows.Count().ToStr(),label:title,value:label,selected:label=context.qualityPreference})
            end if
        end for
    else
        if not proof.versionDefaults or proof.providerAudioIntent then return rows
        for index = 0 to detail.versions.Count()-1
            version = detail.versions[index]
            id = version.versionId
            if SiloPlaybackFile(detail,context.sourceId,context.itemId,id,0) = invalid then return []
            title = "Version "+(index+1).ToStr()
            resolution = ScField(version,"resolution","")
            if SpText(resolution,20)
                if CreateObject("roRegex","^[0-9]{1,4}x[0-9]{1,4}$","").IsMatch(resolution) then title = title+" · "+resolution
            end if
            rows.Push({handle:"sc-1-"+rows.Count().ToStr(),label:title,value:id,selected:id=fileId})
        end for
    end if
    return rows
end function

function SiloChangeCreate(config as Dynamic) as Dynamic
    scope = ScScope(ScField(config,"scope"))
    session = ScField(config,"session")
    if scope = invalid or type(session) <> "roAssociativeArray" then return invalid
    if not SpBool(ScField(session,"closed")) or session.closed then return invalid
    if not SpBool(ScField(session,"landed")) then return invalid
    lease = ScScope(ScField(session,"scope"),true)
    if lease = invalid then return invalid
    for each field in ["provider","sourceId","profileId"]
        if scope[field] <> lease[field] then return invalid
    end for
    plan = ScField(session,"plan")
    context = SiloPlaybackContext(plan,scope)
    if context = invalid or context.sessionId <> lease.sessionId then return invalid
    attempt = ScField(session,"attemptId"):operation = ScField(config,"operationId")
    clip = ScField(config,"clipId"):revision = ScField(config,"inventoryRevision")
    if not VoIdentifier(attempt) or not SpOpaque(operation,128,8) then return invalid
    if not ScInteger(clip) or not ScInteger(revision) or revision < 1 then return invalid
    if not ScSettled(ScField(config,"transport"),attempt,clip) then return invalid
    paused = ScField(config,"paused",ScField(config.transport,"desiredPaused"))
    if not SpBool(paused) then return invalid
    proof = ScProof(ScField(config,"intentProof"),attempt,context.fileId,clip)
    if proof = invalid then return invalid
    kind = ScField(config,"changeKind")
    if kind <> "quality" and kind <> "version" then return invalid
    owed = ScField(plan,"originalResumeMs",UiPlanPositionMs(invalid,plan,false))
    if not ScNumber(owed,604800000) then return invalid
    detail = ScField(config,"detail")
    if SiloPlaybackFile(detail,scope.sourceId,context.itemId,context.fileId,owed) = invalid then return invalid
    if VideoOwnerRequest({attemptId:attempt,mode:"playback",plan:plan,trackScope:scope}) = invalid then return invalid
    rows = ScRows(context,detail,context.fileId,kind,proof)
    rendered = ScRendered(plan,ScField(config,"native"),attempt,clip)
    return {phase:"ready",scope:scope,leaseScope:lease,operationId:operation,attemptId:attempt,versionId:context.fileId,
        itemId:context.itemId,clipId:clip,inventoryRevision:revision,changeKind:kind,plan:plan,context:context,detail:detail,
        rows:rows,intentProof:proof,owedMs:owed,renderedMs:rendered,landed:session.landed,paused:paused,targetMs:-1,
        nextVersionId:context.fileId,nextAttemptId:"",requestKind:"",requestId:"",requestOutstanding:false,
        handledRequestId:"",newPlan:invalid,installPending:false,cancelled:false,nativeStopped:false,
        stopId:"",terminalRequested:false,terminalDone:false,terminalFailed:false,lateCleanup:invalid,installed:false,nativeRetirePending:false}
end function

function SiloChangeProjection(state as Dynamic) as Object
    if type(state) <> "roAssociativeArray" then return {available:false,choices:[],pending:false,phase:"unavailable"}
    choices = []
    for each row in state.rows
        choices.Push({handle:row.handle,label:row.label,intent:"select",selected:row.selected,enabled:not row.selected})
    end for
    available = state.phase = "ready" and choices.Count() > 0 and not state.cancelled
    if state.landed and state.renderedMs < 0 then available = false
    return {available:available,choices:choices,pending:SiloChangeBusy(state),phase:state.phase,changeKind:state.changeKind,
        attemptId:state.attemptId,versionId:state.versionId,clipId:state.clipId,inventoryRevision:state.inventoryRevision}
end function

function SiloChangeBusy(state as Dynamic) as Boolean
    if type(state) <> "roAssociativeArray" then return false
    if state.requestOutstanding or state.installPending or state.lateCleanup <> invalid or state.nativeRetirePending then return true
    if state.terminalRequested and (not state.terminalDone or not state.nativeStopped) then return true
    return state.phase = "native_stopping" or state.phase = "closing" or state.phase = "awaiting"
end function

function ScOwner(state as Object, action as String) as Object
    return {operationId:state.operationId,requestKind:action,attemptId:state.attemptId,versionId:state.versionId,
        clipId:state.clipId,inventoryRevision:state.inventoryRevision}
end function

sub ScRequest(state as Object, effects as Object, action as String)
    params = {itemId:state.itemId}
    if action = "playback_replan"
        params = {plan:state.plan,sessionId:state.leaseScope.sessionId,qualityPreference:state.quality,
            positionMs:state.targetMs,replanRequestId:state.operationId}
        if state.intentProof.subtitleMode = "off"
            tracks = {}
            if state.context.selectedTracks.DoesExist("audio") then tracks["audio"] = state.context.selectedTracks.audio
            params["selectedTracks"] = tracks
        end if
    else if action = "playback_start"
        params = {itemId:state.itemId,fileId:state.nextVersionId,versionId:state.nextVersionId,startPositionMs:state.targetMs,
            qualityPreference:state.context.qualityPreference,detail:state.detail}
        if state.context.DoesExist("bandwidthCapKbps") then params["bandwidthCapKbps"] = state.context.bandwidthCapKbps
    end if
    state.requestKind = action:state.requestId = "":state.requestOutstanding = true:state.handledRequestId = ""
    state.phase = "requesting"
    if action = "detail" then state.phase = "verifying"
    effects.Push({kind:"request",action:action,scope:state.scope,params:params,owner:ScOwner(state,action)})
end sub

sub ScRetire(state as Object, effects as Object)
    if state.terminalRequested then return
    state.terminalRequested = true:state.installPending = false
    effect = {kind:"retire",scope:state.leaseScope,stopId:state.stopId}
    if state.landed and state.renderedMs >= 0 then effect["confirmedPositionMs"] = state.renderedMs
    effects.Push(effect)
end sub

sub ScFailed(state as Object, effects as Object, keepPlayback as Boolean)
    state.phase = "failed"
    effects.Push({kind:"failed",keepPlayback:keepPlayback})
end sub

sub ScAdmit(state as Object, effects as Object)
    if state.cancelled or state.phase <> "closing" then return
    if state.nativeStopped and state.terminalDone then ScRequest(state,effects,"playback_start")
end sub

function ScEnvelope(state as Object, event as Dynamic) as Boolean
    if ScField(event,"operationId") <> state.operationId then return false
    if not ScMatches(state.scope,ScField(event,"scope")) then return false
    request = ScField(event,"requestId")
    if not VoIdentifier(request) or request <> state.requestId or request = state.handledRequestId then return false
    return state.requestOutstanding
end function

function ScPlan(state as Object, response as Dynamic) as Dynamic
    plan = ScField(response,"plan")
    context = SiloPlaybackContext(plan,state.scope)
    if context = invalid then return invalid
    if context.itemId <> state.itemId or context.fileId <> state.nextVersionId then return invalid
    if context.sessionRevision <> state.context.sessionRevision or context.installationId <> state.context.installationId then return invalid
    if ScField(context,"bandwidthCapKbps") <> ScField(state.context,"bandwidthCapKbps") then return invalid
    if state.changeKind = "quality"
        if context.sessionId <> state.leaseScope.sessionId or context.playbackAttemptId <> state.context.playbackAttemptId then return invalid
        if context.qualityPreference <> state.quality or context.attemptCount <> state.context.attemptCount+1 then return invalid
        tracks = state.context.selectedTracks
        if state.intentProof.subtitleMode = "off"
            tracks = {}
            if state.context.selectedTracks.DoesExist("audio") then tracks["audio"] = state.context.selectedTracks.audio
        end if
        if FormatJson(context.selectedTracks) <> FormatJson(tracks) then return invalid
    else
        if context.sessionId = state.leaseScope.sessionId or context.playbackAttemptId = state.context.playbackAttemptId then return invalid
        if context.qualityPreference <> state.context.qualityPreference then return invalid
        fresh = ScField(ScField(response,"data"),"playbackDetail")
        if SiloPlaybackFile(fresh,state.scope.sourceId,state.itemId,state.nextVersionId,state.targetMs) = invalid then return invalid
    end if
    original = ScField(plan,"originalResumeMs")
    if not ScNumber(original,604800000) then return invalid
    if Abs(original-state.targetMs) > 1 then return invalid
    for each field in ["startPositionMs","timelineOffsetMs"]
        if not ScNumber(ScField(plan,field),604800000) then return invalid
    end for
    if not ScTrue(ScField(plan,"relativeTimeline")) or not SpBool(ScField(plan,"canSeekAnywhere")) then return invalid
    if state.targetMs < plan.timelineOffsetMs or Abs(UiPlanPositionMs(invalid,plan,false)-state.targetMs) > 1 then return invalid
    if VideoOwnerRequest({attemptId:state.requestId,mode:"playback",plan:plan,trackScope:state.scope}) = invalid then return invalid
    return plan
end function

' The mapped start request owns this minimal returned allocation even if its
' completion envelope/context is malformed. Never infer a new quality lease.
sub ScLateCleanup(state as Object, effects as Object, plan as Dynamic)
    if state.changeKind <> "version" or state.lateCleanup <> invalid then return
    if ScField(plan,"provider") <> "silo" or ScField(plan,"sourceId") <> state.scope.sourceId then return
    if ScField(plan,"itemId") <> state.itemId or ScField(plan,"versionId") <> state.nextVersionId then return
    sessionId = ScField(plan,"sessionId"):installation = ScField(plan,"installationId")
    if not SpOpaque(sessionId) or sessionId = state.leaseScope.sessionId or installation <> state.context.installationId then return
    scope = ScCopy(state.scope):scope["sessionId"] = sessionId
    cleanupPlan = {provider:"silo",sourceId:state.scope.sourceId,itemId:state.itemId,versionId:state.nextVersionId,
        sessionId:sessionId,installationId:installation,startPositionMs:state.targetMs,relativeTimeline:false}
    stopIdentity = state.stopId+"-late"
    ' An already attempted worker abandonment must retain its idempotency key.
    retryStop = ScField(plan,"stopId")
    if SpBool(ScField(plan,"persistProgress"))
        if plan.persistProgress = false and SpOpaque(retryStop,256) then stopIdentity = retryStop
    end if
    state.lateCleanup = {scope:scope,plan:cleanupPlan,stopId:stopIdentity,failed:false}
    effects.Push({kind:"cleanup",scope:scope,plan:cleanupPlan,stopId:state.lateCleanup.stopId,persistProgress:false})
end sub

function SiloChangeReduce(previous as Dynamic, event as Dynamic) as Object
    result = {state:previous,effects:[],accepted:false}
    if type(previous) <> "roAssociativeArray" or type(event) <> "roAssociativeArray" then return result
    state = ScCopy(previous):result.state = state:effects = result.effects
    kind = ScField(event,"kind","")
    if kind = "select"
        if not SiloChangeProjection(state).available or not ScMatches(state.scope,ScField(event,"scope")) then return result
        for each field in ["operationId","attemptId","versionId","clipId","inventoryRevision"]
            if ScField(event,field) <> state[field] then return result
        end for
        if not ScInteger(event.clipId) or not ScInteger(event.inventoryRevision) or not SpBool(ScField(event,"landed")) or not SpBool(ScField(event,"paused")) then return result
        if not ScSettled(ScField(event,"transport"),state.attemptId,state.clipId) then return result
        proof = ScProof(ScField(event,"intentProof"),state.attemptId,state.versionId,state.clipId)
        if proof = invalid then return result
        if FormatJson(proof) <> FormatJson(state.intentProof) then return result
        stopIdentity = ScField(event,"stopId")
        if not SpOpaque(stopIdentity,128) then return result
        selected = invalid
        for each row in state.rows
            if row.handle = ScField(event,"handle") then selected = row
        end for
        if selected = invalid then return result
        if selected.selected then return result
        position = ScRendered(state.plan,ScField(event,"native"),state.attemptId,state.clipId)
        if position >= 0
            state.renderedMs = position
            if event.landed then state.landed = true
        end if
        target = state.owedMs
        if state.landed then target = state.renderedMs
        if not ScNumber(target,604800000) then return result
        if state.changeKind = "version" then state.nextVersionId = selected.value else state["quality"] = selected.value
        if SiloPlaybackFile(state.detail,state.scope.sourceId,state.itemId,state.nextVersionId,target) = invalid then return result
        state.targetMs = target:state.stopId = stopIdentity:state.paused = event.paused
        if state.changeKind = "quality"
            state.phase = "native_stopping"
            effects.Push({kind:"native_stop",attemptId:state.attemptId})
        else
            ScRequest(state,effects,"detail")
        end if
        result.accepted = true
    else if kind = "native"
        native = ScField(event,"status")
        if state.nativeRetirePending and ScField(native,"attemptId") = state.nextAttemptId and ScField(native,"mode") = "playback" and ScField(native,"state") = "stopped"
            state.nativeRetirePending = false:result.accepted = true
            return result
        end if
        if state.phase = "ready"
            position = ScRendered(state.plan,native,state.attemptId,state.clipId)
            if position >= 0
                state.renderedMs = position
                if ScTrue(ScField(event,"landed")) then state.landed = true
            end if
        else if ScField(native,"attemptId") = state.attemptId and ScField(native,"mode") = "playback"
            nativeState = ScField(native,"state")
            if nativeState = "stopped"
                state.nativeStopped = true
                if state.phase = "native_stopping" and not state.cancelled
                    if ScField(native,"errorCode") = 0
                        ScRequest(state,effects,"playback_replan")
                    else
                        ScRetire(state,effects):ScFailed(state,effects,false)
                    end if
                else
                    ScAdmit(state,effects)
                end if
            end if
        else if state.phase = "awaiting" and not state.installPending
            if ScField(native,"attemptId") <> state.nextAttemptId or ScField(native,"mode") <> "playback" then return result
            clip = ScField(native,"clipId")
            if not ScInteger(clip) then return result
            if state.newClipId >= 0 and clip <> state.newClipId then return result
            absolute = ScRendered(state.newPlan,native,state.nextAttemptId,clip)
            if absolute >= 0
                state.newClipId = clip
                if ScTrue(ScField(event,"landed")) and absolute+1 >= state.targetMs
                    state.phase = "done"
                    if state.paused and ScField(native,"state") = "playing" then effects.Push({kind:"pause",attemptId:state.nextAttemptId})
                end if
            end if
        end if
        result.accepted = true
    else if kind = "request_bound"
        if not state.requestOutstanding or state.requestId <> "" then return result
        if ScField(event,"operationId") <> state.operationId or ScField(event,"requestKind") <> state.requestKind then return result
        if not ScMatches(state.scope,ScField(event,"scope")) or not VoIdentifier(ScField(event,"requestId")) then return result
        state.requestId = event.requestId:result.accepted = true
    else if kind = "detail" or kind = "plan"
        if not ScEnvelope(state,event) then return result
        if (kind = "detail") <> (state.requestKind = "detail") then return result
        response = ScField(event,"result")
        valid = ScTrue(ScField(response,"ok")) and ScMatches(state.scope,response)
        valid = valid and ScField(response,"requestId") = state.requestId and ScField(response,"action") = state.requestKind
        state.requestOutstanding = false:state.handledRequestId = state.requestId:result.accepted = true
        if state.requestKind = "detail"
            if state.cancelled then return result
            fresh = ScField(response,"data")
            if not valid or SiloPlaybackFile(fresh,state.scope.sourceId,state.itemId,state.nextVersionId,state.targetMs) = invalid
                ScFailed(state,effects,true)
            else if not state.cancelled
                state.detail = fresh:state.phase = "closing":state.terminalRequested = true
                close = {kind:"close",stopId:state.stopId}
                if state.landed then close["confirmedPositionMs"] = state.renderedMs
                effects.Push(close)
            end if
        else
            plan = invalid
            if valid then plan = ScPlan(state,response)
            if state.cancelled or plan = invalid
                if state.changeKind = "quality"
                    ScRetire(state,effects)
                else
                    ScLateCleanup(state,effects,ScField(response,"plan"))
                end if
                if not state.cancelled then ScFailed(state,effects,false)
            else
                state.newPlan = plan:state.nextAttemptId = state.requestId:state.newClipId = -1
                state.phase = "awaiting":state.installPending = true
                installKind = "install"
                if state.changeKind = "quality" then installKind = "install_same_lease"
                effects.Push({kind:installKind,operationId:state.operationId,scope:state.scope,requestId:state.requestId,
                    attemptId:state.nextAttemptId,versionId:state.nextVersionId,plan:plan,result:response,paused:state.paused,targetMs:state.targetMs})
            end if
        end if
    else if kind = "installed"
        if state.phase <> "awaiting" or not state.installPending then return result
        if not ScMatches(state.scope,ScField(event,"scope")) then return result
        for each field in ["operationId","requestId"]
            if ScField(event,field) <> state[field] then return result
        end for
        if ScField(event,"attemptId") <> state.nextAttemptId or ScField(event,"versionId") <> state.nextVersionId then return result
        state.installPending = false:state.installed = true:result.accepted = true
    else if kind = "cancel"
        if state.cancelled then return result
        wasReady = state.phase = "ready" or state.phase = "failed" or state.phase = "done"
        state.cancelled = true:state.phase = "cancelled"
        effects.Push({kind:"cancel",operationId:state.operationId,requestId:state.requestId})
        if state.changeKind = "quality" and not wasReady and not state.requestOutstanding then ScRetire(state,effects)
        if not wasReady and state.installed
            state.nativeRetirePending = true
            effects.Push({kind:"native_stop",attemptId:state.nextAttemptId})
        end if
        if state.changeKind = "version" and (state.installPending or (state.installed and not wasReady))
            state.installPending = false:ScLateCleanup(state,effects,state.newPlan)
        end if
        result.accepted = true
    else if kind = "request_cancelled" or kind = "request_rejected"
        if not state.requestOutstanding or ScField(event,"operationId") <> state.operationId then return result
        if ScField(event,"requestKind") <> state.requestKind or not ScMatches(state.scope,ScField(event,"scope")) then return result
        if kind = "request_rejected"
            if state.requestId <> "" then return result
        else if state.requestId <> ScField(event,"requestId","")
            return result
        end if
        state.requestOutstanding = false:result.accepted = true
        if state.changeKind = "quality" then ScRetire(state,effects)
        if not state.cancelled then ScFailed(state,effects,state.requestKind="detail")
    else if kind = "terminal"
        ok = ScField(event,"ok")
        if not SpBool(ok) then return result
        cleanup = state.lateCleanup
        if cleanup <> invalid
            if not ScMatches(cleanup.scope,ScField(event,"scope"),true) or ScField(event,"stopId") <> cleanup.stopId then return result
            if ok
                state.lateCleanup = invalid
            else
                copy = ScCopy(cleanup):copy.failed = true:state.lateCleanup = copy
            end if
        else
            if not state.terminalRequested or not ScMatches(state.leaseScope,ScField(event,"scope"),true) then return result
            if ScField(event,"stopId") <> state.stopId or state.terminalDone then return result
            state.terminalDone = ok:state.terminalFailed = not ok
            if not state.cancelled and state.changeKind = "version"
                if ok then state.phase = "closing" else state.phase = "blocked"
                ScAdmit(state,effects)
            end if
        end if
        result.accepted = true
    else if kind = "retry_cleanup"
        if state.lateCleanup <> invalid
            if not state.lateCleanup.failed then return result
            cleanup = ScCopy(state.lateCleanup):cleanup.failed = false:state.lateCleanup = cleanup
            effects.Push({kind:"cleanup",scope:cleanup.scope,plan:cleanup.plan,stopId:cleanup.stopId,persistProgress:false})
        else if state.terminalFailed
            state.terminalFailed = false
            effects.Push({kind:"retry_cleanup"})
        else
            return result
        end if
        result.accepted = true
    else if kind = "pause_intent"
        if ScField(event,"operationId") <> state.operationId or not SpBool(ScField(event,"paused")) then return result
        if not ScMatches(state.scope,ScField(event,"scope")) or state.cancelled then return result
        state.paused = event.paused:result.accepted = true
    end if
    return result
end function
