' Private provider lanes; public handles never contain provider stream IDs.
function PaField(value as Dynamic, key as String, fallback as Dynamic) as Dynamic
    if type(value) <> "roAssociativeArray" then return fallback
    if not value.DoesExist(key) then return fallback
    return value[key]
end function

function PaTrue(value as Dynamic) as Boolean
    if type(value) <> "Boolean" and type(value) <> "roBoolean" then return false
    return value
end function

function PaNumber(value as Dynamic, maximum as Double) as Boolean
    kind = type(value)
    if kind <> "Integer" and kind <> "roInt" and kind <> "roInteger" and kind <> "LongInteger" and kind <> "roLongInteger" and kind <> "Float" and kind <> "roFloat" and kind <> "Double" and kind <> "roDouble" then return false
    return value = value and value >= 0 and value <= maximum
end function

function PaInteger(value as Dynamic) as Boolean
    if not PaNumber(value,2147483646) then return false
    return value = Int(value)
end function

function PaText(value as Dynamic, maximum as Integer, empty = false as Boolean) as Boolean
    if type(value) <> "String" and type(value) <> "roString" then return false
    if Len(value) > maximum or (not empty and Len(value) = 0) then return false
    if Instr(1,value,"://") > 0 or Left(LCase(value),5) = "data:" then return false
    for index = 1 to Len(value)
        code = Asc(Mid(value,index,1))
        if code < 32 or code = 127 then return false
    end for
    return true
end function

function PaScope(value as Dynamic, lease = false as Boolean) as Dynamic
    if type(value) <> "roAssociativeArray" then return invalid
    if PaField(value,"provider","") <> "plex" then return invalid
    if not PaText(PaField(value,"sourceId",invalid),512) then return invalid
    if not PaText(PaField(value,"profileId",invalid),256,true) then return invalid
    if not PaInteger(PaField(value,"generation",invalid)) then return invalid
    result = {provider:"plex",sourceId:value.sourceId,profileId:value.profileId,generation:value.generation}
    if lease
        session = PaField(value,"sessionId",invalid)
        if not PaText(session,256,true) then return invalid
        result["sessionId"] = session
    end if
    return result
end function

function PaScopeMatches(scope as Dynamic, value as Dynamic, lease = false as Boolean) as Boolean
    if PaScope(scope,lease) = invalid or PaScope(value,lease) = invalid then return false
    for each field in ["provider","sourceId","profileId","generation"]
        if PaField(scope,field,invalid) <> PaField(value,field,invalid) then return false
    end for
    if lease then return PaField(scope,"sessionId",invalid) = PaField(value,"sessionId",invalid)
    return true
end function

function PaCopy(value as Object) as Object
    result = {}
    for each key in value
        result[key] = value[key]
    end for
    return result
end function

function PaAbsolute(state as Object, native as Dynamic) as Double
    if type(native) <> "roAssociativeArray" then return -1
    if PaField(native,"attemptId","") <> state.attemptId or PaField(native,"mode","") <> "playback" then return -1
    if PaField(native,"state","") <> "playing" and PaField(native,"state","") <> "paused" then return -1
    if not PaInteger(PaField(native,"clipId",invalid)) or not PaInteger(PaField(native,"renderedClipId",invalid)) then return -1
    if PaField(native,"clipId",invalid) <> state.clipId or PaField(native,"renderedClipId",invalid) <> state.clipId then return -1
    epoch = PaField(native,"renderedEpoch",invalid)
    errorCode = PaField(native,"errorCode",invalid)
    if not PaInteger(epoch) or epoch <> 0 or not PaInteger(errorCode) or errorCode <> 0 then return -1
    position = PaField(native,"renderedPosition",invalid)
    if not PaNumber(position,604800) then return -1
    absolute = UiPlanPositionMs(position,state.plan,true)
    if not PaNumber(absolute,604800000) then return -1
    return Int(absolute + 0.5)
end function

function PaRows(raw as Dynamic) as Object
    rows = []
    if type(raw) <> "roArray" then return rows
    seen = {}
    scanned = 0
    for each track in raw
        scanned++
        if scanned > 64 or rows.Count() >= 24 then exit for
        id = PaField(track,"id",invalid)
        if PaText(id,20)
            if CreateObject("roRegex","^[0-9]{1,20}$","").IsMatch(id) and not seen.DoesExist(id)
                seen[id] = true
                label = PaField(track,"title","")
                if not PaText(label,80) then label = PaField(track,"language","")
                if not PaText(label,80) or Instr(1,label,id) > 0 then label = "Audio " + (rows.Count()+1).ToStr()
                rows.Push({id:id,label:label,handle:"pa-1-" + rows.Count().ToStr()})
            end if
        end if
    end for
    return rows
end function

function ProviderAudioCreate(config as Dynamic) as Dynamic
    if type(config) <> "roAssociativeArray" then return invalid
    scope = PaScope(PaField(config,"scope",invalid))
    session = PaField(config,"session",invalid)
    if scope = invalid or type(session) <> "roAssociativeArray" then return invalid
    closed = PaField(session,"closed",invalid)
    if type(closed) <> "Boolean" and type(closed) <> "roBoolean" then return invalid
    if closed then return invalid
    lease = PaScope(PaField(session,"scope",invalid),true)
    if lease = invalid then return invalid
    for each field in ["provider","sourceId","profileId"]
        if scope[field] <> lease[field] then return invalid
    end for
    plan = PaField(session,"plan",invalid)
    detail = PaField(config,"detail",invalid)
    item = PaField(detail,"item",invalid)
    if type(plan) <> "roAssociativeArray" or type(item) <> "roAssociativeArray" then return invalid
    if PaField(plan,"provider","") <> "plex" or PaField(plan,"sourceId","") <> scope.sourceId then return invalid
    if PaField(item,"sourceId","") <> scope.sourceId or PaField(plan,"itemId",invalid) <> PaField(item,"itemId",invalid) then return invalid
    if not PaText(PaField(plan,"itemId",invalid),128) or not PaText(PaField(plan,"versionId",invalid),256) then return invalid
    if PaField(plan,"sessionId",invalid) <> lease.sessionId then return invalid
    attempt = PaField(session,"attemptId",invalid)
    operation = PaField(config,"operationId",invalid)
    clip = PaField(config,"clipId",invalid)
    if not PaText(attempt,128) or not PaText(operation,128) or not PaInteger(clip) then return invalid
    versions = PaField(detail,"versions",invalid)
    if type(versions) <> "roArray" or versions.Count() > 16 then return invalid
    selected = invalid
    selectedIndex = -1
    for index = 0 to versions.Count()-1
        version = versions[index]
        if PaField(version,"versionId",invalid) = plan.versionId
            if selected <> invalid then return invalid
            selected = version
            selectedIndex = index
        end if
    end for
    if selected = invalid or not PaInteger(PaField(selected,"mediaIndex",invalid)) or not PaInteger(PaField(selected,"partIndex",invalid)) then return invalid
    changeKind=PaField(config,"changeKind","audio")
    if changeKind<>"audio" and changeKind<>"quality" and changeKind<>"version" then return invalid
    client=PrIntent(PaField(plan,"clientIntent",invalid),scope.sourceId,plan.itemId,plan.versionId)
    rows=PaRows(PaField(selected,"audio",invalid))
    if changeKind<>"audio"
        if client=invalid or PrFile(detail,plan.versionId,0)=invalid then return invalid
        if changeKind="quality" then rows=PrQualityRows(client) else rows=PrVersionRows(detail,plan.versionId)
    end if
    owed = PaField(plan,"originalResumeMs",UiPlanPositionMs(invalid,plan,false))
    if not PaNumber(owed,604800000) then return invalid
    state = {phase:"ready",scope:scope,leaseScope:lease,operationId:operation,attemptId:attempt,
        versionId:plan.versionId,itemId:plan.itemId,clipId:clip,inventoryRevision:1,plan:plan,detail:detail,
        versionIndex:selectedIndex,partIndex:selected.partIndex,rows:rows,changeKind:changeKind,clientIntent:client,nextVersionId:plan.versionId,requestParams:invalid,
        owedMs:owed,renderedMs:-1,landed:PaTrue(PaField(session,"landed",false)),paused:PaTrue(PaField(config,"paused",false)),
        targetMs:-1,trackId:"",stopId:"",nativeStopped:false,terminalDone:false,requestId:"",
        allocationOutstanding:false,installPending:false,lateCleanup:invalid,acceptedRequestId:"",rejectedRequestId:""}
    state.renderedMs = PaAbsolute(state,PaField(config,"native",invalid))
    return state
end function

function ProviderAudioProjection(state as Dynamic) as Object
    hidden = {available:false,choices:[],pending:false,phase:"unavailable"}
    if type(state) <> "roAssociativeArray" then return hidden
    available = state.phase = "ready" and state.rows.Count() > 0
    if state.landed and state.renderedMs < 0 then available = false
    choices = []
    for each row in state.rows
        choices.Push({handle:row.handle,label:row.label,intent:"select",selected:PaTrue(PaField(row,"selected",false))})
    end for
    return {available:available,attemptId:state.attemptId,versionId:state.versionId,clipId:state.clipId,
        inventoryRevision:state.inventoryRevision,choices:choices,phase:state.phase,changeKind:state.changeKind,
        pending:state.phase="closing" or state.phase="requesting" or state.phase="awaiting"}
end function

function ProviderAudioBusy(state as Dynamic) as Boolean
    if type(state) <> "roAssociativeArray" then return false
    if state.allocationOutstanding or PaTrue(PaField(state,"installPending",false)) then return true
    return type(state.lateCleanup) = "roAssociativeArray"
end function

sub PaAdmit(state as Object, effects as Object)
    if state.phase <> "closing" or not state.nativeStopped or not state.terminalDone then return
    state.phase = "requesting"
    state.allocationOutstanding = true
    params=state.requestParams
    if params=invalid
        params = {itemId:state.itemId,detail:state.detail,versionIndex:state.versionIndex,partIndex:state.partIndex,
            versionId:state.versionId,audioStreamId:state.trackId,startPositionMs:state.targetMs,forceTranscode:true}
    end if
    effects.Push({kind:"request",scope:state.scope,params:params,owner:{operationId:state.operationId}})
end sub

function ProviderAudioReduce(previous as Dynamic, event as Dynamic) as Object
    result = {state:previous,effects:[],accepted:false}
    if type(previous) <> "roAssociativeArray" or type(event) <> "roAssociativeArray" then return result
    state = PaCopy(previous)
    result.state = state
    effects = result.effects
    kind = PaField(event,"kind","")
    if kind = "cancel"
        if PaTrue(PaField(state,"installPending",false))
            state["installPending"]=false
            cleanupScope=PaCopy(state.scope)
            cleanupScope["sessionId"]=PaField(state.newPlan,"sessionId","")
            cleanupStopId=state.stopId+"-late"
            state["lateCleanup"]={scope:cleanupScope,stopId:cleanupStopId,plan:state.newPlan,failed:false}
            effects.Push({kind:"cleanup",scope:state.scope,plan:state.newPlan,stopId:cleanupStopId})
        end if
        if state.phase <> "cancelled"
            state.phase = "cancelled"
            effects.Push({kind:"cancel",operationId:state.operationId,requestId:state.requestId})
        end if
        result.accepted = true
    else if kind = "select"
        if not ProviderAudioProjection(state).available or not PaScopeMatches(state.scope,PaField(event,"scope",invalid)) then return result
        if not PaInteger(PaField(event,"clipId",invalid)) or not PaInteger(PaField(event,"inventoryRevision",invalid)) then return result
        for each field in ["attemptId","versionId","clipId","inventoryRevision"]
            if PaField(event,field,invalid) <> state[field] then return result
        end for
        stopId = PaField(event,"stopId",invalid)
        if not PaText(stopId,256) then return result
        selected = invalid
        for each row in state.rows
            if row.handle = PaField(event,"handle",invalid) then selected = row
        end for
        if selected = invalid then return result
        position = PaAbsolute(state,PaField(event,"native",invalid))
        if position >= 0 then state.renderedMs = position
        if PaTrue(PaField(event,"landed",false)) then state.landed = true
        target = state.owedMs
        if state.landed then target = state.renderedMs
        if not PaNumber(target,604800000) then return result
        if state.clientIntent<>invalid
            params=PrParams(state,selected,target)
            if params=invalid then return result
            if state.changeKind<>"audio" and PaTrue(PaField(selected,"selected",false)) then return result
            state["requestParams"]=params
            state["nextVersionId"]=params.versionId
        else if state.changeKind<>"audio"
            return result
        end if
        if state.changeKind="audio" then state.trackId=selected.id
        state.targetMs = target
        state.stopId = stopId
        state.paused = PaTrue(PaField(event,"paused",false))
        state.phase = "closing"
        closeEffect = {kind:"close",stopId:stopId}
        if state.landed then closeEffect["confirmedPositionMs"] = state.renderedMs
        effects.Push(closeEffect)
        result.accepted = true
    else if kind = "native"
        native = PaField(event,"status",invalid)
        if state.phase = "ready"
            position = PaAbsolute(state,native)
            if position >= 0 then state.renderedMs = position
            if PaTrue(PaField(event,"landed",false)) then state.landed = true
        else if state.phase = "closing" or state.phase = "blocked"
            if PaField(native,"attemptId","") = state.attemptId and PaField(native,"mode","") = "playback" and PaField(native,"state","") = "stopped" then state.nativeStopped = true
        else if state.phase = "awaiting"
            if PaField(native,"attemptId","") <> state.requestId or PaField(native,"mode","") <> "playback" then return result
            sampleState = PaCopy(state)
            sampleState.attemptId = state.requestId
            sampleState.plan = state.newPlan
            clip = PaField(native,"clipId",invalid)
            if not PaInteger(clip) then return result
            sampleState.clipId = clip
            position = PaAbsolute(sampleState,native)
            if PaTrue(PaField(event,"landed",false)) and position >= 0
                state.phase = "done"
                if state.paused and PaField(native,"state","") = "playing" then effects.Push({kind:"pause",attemptId:state.requestId})
            end if
        end if
        result.accepted = true
    else if kind = "terminal"
        receiptScope = PaField(event,"scope",invalid)
        stopId = PaField(event,"stopId",invalid)
        ok = PaField(event,"ok",invalid)
        if type(ok) <> "Boolean" and type(ok) <> "roBoolean" then return result
        if type(state.lateCleanup) = "roAssociativeArray"
            if PaScopeMatches(state.lateCleanup.scope,receiptScope,true) and stopId = state.lateCleanup.stopId
                if ok
                    state.lateCleanup = invalid
                else
                    cleanup = PaCopy(state.lateCleanup)
                    cleanup["failed"] = true
                    state.lateCleanup = cleanup
                end if
                result.accepted = true
            end if
        else if (state.phase = "closing" or state.phase = "blocked") and PaScopeMatches(state.leaseScope,receiptScope,true) and stopId = state.stopId
            state.terminalDone = ok
            if ok
                state.phase = "closing"
            else
                state.phase = "blocked"
            end if
            result.accepted = true
        end if
    else if kind = "retry_cleanup"
        if type(state.lateCleanup) = "roAssociativeArray"
            if PaTrue(PaField(state.lateCleanup,"failed",false))
                cleanup = PaCopy(state.lateCleanup)
                cleanup["failed"] = false
                state.lateCleanup = cleanup
                effects.Push({kind:"cleanup",scope:cleanup.scope,plan:cleanup.plan,stopId:cleanup.stopId})
                result.accepted = true
            end if
        else if state.phase = "blocked"
            effects.Push({kind:"retry_cleanup"})
            result.accepted = true
        end if
    else if kind = "pause_intent"
        paused = PaField(event,"paused",invalid)
        if type(paused) <> "Boolean" and type(paused) <> "roBoolean" then return result
        if state.phase = "closing" or state.phase = "blocked" or state.phase = "requesting" or state.phase = "awaiting"
            state.paused = paused
            result.accepted = true
        end if
    else if kind = "request_bound"
        if state.phase <> "requesting" or PaField(event,"operationId","") <> state.operationId then return result
        if not PaScopeMatches(state.scope,PaField(event,"scope",invalid)) or not PaText(PaField(event,"requestId",invalid),128) then return result
        state.requestId = event.requestId
        result.accepted = true
    else if kind = "install_bound"
        if state.phase<>"awaiting" or not PaTrue(PaField(state,"installPending",false)) then return result
        if PaField(event,"operationId","")<>state.operationId or not PaScopeMatches(state.scope,PaField(event,"scope",invalid)) then return result
        if PaField(event,"requestId","")<>state.acceptedRequestId or PaField(event,"versionId","")<>state.nextVersionId then return result
        state["installPending"]=false
        result.accepted=true
    else if kind = "request_cancelled"
        if PaField(event,"operationId","") <> state.operationId then return result
        state.allocationOutstanding = false
        result.accepted = true
    else if kind = "plan"
        response = PaField(event,"result",invalid)
        plan = PaField(response,"plan",invalid)
        requestId = PaField(event,"requestId","")
        if state.acceptedRequestId <> "" and requestId = state.acceptedRequestId then return result
        if state.rejectedRequestId <> "" and requestId = state.rejectedRequestId then return result
        owned = PaField(event,"operationId","") = state.operationId and PaScopeMatches(state.scope,PaField(event,"scope",invalid))
        if not owned or requestId <> state.requestId then return result
        if owned and requestId = state.requestId then state.allocationOutstanding = false
        valid = owned and state.phase = "requesting" and requestId <> "" and requestId = state.requestId
        valid = valid and PaTrue(PaField(response,"ok",false)) and PaScopeMatches(state.scope,response) and PaField(response,"requestId","") = requestId
        if valid
            valid = PaField(plan,"provider","") = "plex" and PaField(plan,"sourceId","") = state.scope.sourceId
            valid = valid and PaField(plan,"itemId","") = state.itemId and PaField(plan,"versionId","") = state.nextVersionId
            start = PaField(plan,"startPositionMs",invalid)
            valid = valid and PaNumber(start,604800000)
            if valid then valid = start = state.targetMs and not PaTrue(PaField(plan,"relativeTimeline",false))
            if valid and state.requestParams<>invalid
                fresh=PaField(PaField(response,"data",invalid),"playbackDetail",invalid)
                file=PrFile(fresh,state.nextVersionId,state.targetMs)
                valid=PrSameFile(file,state.requestParams.replacementFile)
                carried=PrIntent(PaField(plan,"clientIntent",invalid),state.scope.sourceId,state.itemId,state.nextVersionId)
                wanted=PrIngress(state.requestParams,plan,fresh)
                if carried=invalid or wanted=invalid then valid=false
                if valid then valid=FormatJson(carried)=FormatJson(wanted)
            end if
            if valid then valid = VideoOwnerRequest({attemptId:requestId,mode:"playback",plan:plan}) <> invalid
        end if
        if valid
            state.phase = "awaiting"
            state.newPlan = plan
            state.acceptedRequestId = requestId
            state["installPending"] = true
            effects.Push({kind:"install",result:response,operationId:state.operationId})
        else
            if type(plan) = "roAssociativeArray"
                state.rejectedRequestId = requestId
                cleanupScope = PaCopy(PaField(event,"scope",state.scope))
                cleanupScope["sessionId"] = PaField(plan,"sessionId","")
                cleanupStopId = state.stopId + "-late"
                state.lateCleanup = {scope:cleanupScope,stopId:cleanupStopId,plan:plan,failed:false}
                effects.Push({kind:"cleanup",scope:PaField(event,"scope",state.scope),plan:plan,stopId:cleanupStopId})
            end if
            if state.phase <> "cancelled"
                state.phase = "failed"
                effects.Push({kind:"failed"})
            end if
        end if
        result.accepted = true
    end if
    PaAdmit(state,effects)
    return result
end function
