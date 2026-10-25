' Volatile preview ownership: reads may retire immediately; allocated streams must settle.
function PreviewCreate(runId = "preview" as String) as Object
    if not PvIdentifier(runId,80) then runId = "preview"
    return {runId:runId,serial:0,wanted:invalid,current:invalid,orphan:invalid,phase:"idle",blocked:false}
end function

function PvText(value as Dynamic, limit as Integer) as Boolean
    if type(value) <> "String" and type(value) <> "roString" then return false
    return Len(value) <= limit
end function

function PvIdentifier(value as Dynamic, limit as Integer) as Boolean
    if not PvText(value,limit) then return false
    if Len(value) = 0 then return false
    allowed = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
    for index = 1 to Len(value)
        if Instr(1,allowed,Mid(value,index,1)) = 0 then return false
    end for
    return true
end function

function PvTrue(value as Dynamic) as Boolean
    if type(value) <> "Boolean" and type(value) <> "roBoolean" then return false
    return value = true
end function

function PvCopy(value as Dynamic) as Dynamic
    if type(value) <> "roAssociativeArray" then return invalid
    copied = {}
    for each key in value
        copied[key] = value[key]
    end for
    return copied
end function

function PvScope(value as Dynamic) as Dynamic
    if type(value) <> "roAssociativeArray" then return invalid
    provider = UiField(value,"provider","")
    if not PvText(provider,8) then return invalid
    if provider <> "plex" and provider <> "silo" then return invalid
    sourceId = UiField(value,"sourceId","")
    profileId = UiField(value,"profileId",invalid)
    generation = UiNumber(UiField(value,"generation",invalid),-1)
    if not PvText(sourceId,512) or not PvText(profileId,256) then return invalid
    if sourceId = "" or generation < 0 or generation <> Int(generation) then return invalid
    return {provider:provider,sourceId:sourceId,profileId:profileId,generation:generation}
end function

function PvBounds(value as Dynamic) as Dynamic
    if type(value) <> "roAssociativeArray" then return invalid
    bounds = {}
    for each key in ["x","y","width","height"]
        number = UiNumber(UiField(value,key,invalid),-1)
        if number < 0 or number > 8192 then return invalid
        bounds[key] = number
    end for
    if bounds.width <= 0 or bounds.height <= 0 then return invalid
    return bounds
end function

function PvItem(value as Dynamic, scope as Object, allowShow = false as Boolean) as Dynamic
    if type(value) <> "roAssociativeArray" then return invalid
    itemId = UiField(value,"itemId","")
    kind = UiField(value,"type","")
    if not PvText(itemId,512) or not PvText(kind,16) then return invalid
    if kind = "series" and scope.provider = "silo" then kind = "show"
    if itemId = "" then return invalid
    if kind <> "movie" and kind <> "episode"
        if not allowShow or kind <> "show" then return invalid
    end if
    sourceId = UiField(value,"sourceId","")
    provider = UiField(value,"provider",scope.provider)
    availability = UiField(value,"availability","owned")
    action = UiField(value,"uiAction","")
    if not PvText(sourceId,512) or not PvText(provider,8) or not PvText(availability,16) or not PvText(action,128) then return invalid
    if sourceId <> scope.sourceId or provider <> scope.provider or availability <> "owned" then return invalid
    if kind <> "show"
        if not PvTrue(UiField(value,"playable",true)) then return invalid
    end if
    if action <> "" then return invalid
    return {provider:scope.provider,sourceId:scope.sourceId,itemId:itemId,type:kind,
        durationMs:UiNumber(UiField(value,"durationMs",0),0),resumeMs:UiNumber(UiField(value,"resumeMs",0),0)}
end function

function PvFocus(event as Object, nowMs as Double) as Dynamic
    if not PvTrue(UiField(event,"contentFocused",false)) or not PvTrue(UiField(event,"autoplayAllowed",false)) then return invalid
    scope = PvScope(UiField(event,"scope",invalid))
    if scope = invalid then return invalid
    item = PvItem(UiField(event,"item",invalid),scope,true)
    bounds = PvBounds(UiField(event,"bounds",invalid))
    key = UiField(event,"key","")
    versionIndex = UiNumber(UiField(event,"versionIndex",0),-1)
    versionId = UiField(event,"versionId","")
    if item = invalid or bounds = invalid then return invalid
    if not PvText(key,1024) or not PvText(versionId,512) then return invalid
    if key = "" or versionIndex < 0 or versionIndex > 15 or versionIndex <> Int(versionIndex) then return invalid
    return {scope:scope,key:key,candidateItemId:item.itemId,candidateType:item.type,item:item,bounds:bounds,versionIndex:versionIndex,versionId:versionId,dueMs:nowMs+1200}
end function

function PvSameFocus(first as Dynamic, second as Dynamic) as Boolean
    if first = invalid or second = invalid then return false
    if not UiResultMatches(first.scope,second.scope) or first.key <> second.key or first.candidateItemId <> second.candidateItemId or first.candidateType <> second.candidateType then return false
    if first.versionId <> second.versionId then return false
    ' An exact version ID owns selection; its stale array index is only a hint.
    if first.versionId <> "" then return true
    return first.versionIndex = second.versionIndex
end function

' Same editorial ladder as Android PreviewStartPolicy and tvOS InlinePreviewStartPolicy.
' Choose the earliest usable intro by start, then end; presentation begins at its end.
function PreviewStartPositionMs(item as Object, markers as Dynamic) as Double
    resumeMs = UiNumber(UiField(item,"resumeMs",0),0)
    if resumeMs > 0 then return resumeMs
    durationMs = UiNumber(UiField(item,"durationMs",0),0)
    earliest = invalid
    if type(markers) = "roArray"
        count = 0
        for each marker in markers
            count++
            if count > 32 then exit for
            kind = UiField(marker,"type",UiField(marker,"kind",""))
            startMs = UiNumber(UiField(marker,"startMs",invalid),-1)
            endMs = UiNumber(UiField(marker,"endMs",invalid),-1)
            if PvText(kind,16)
                if kind = "intro" and startMs >= 0 and endMs > startMs
                    if durationMs <= 0 or endMs < durationMs
                        if earliest = invalid
                            earliest = {startMs:startMs,endMs:endMs}
                        else if startMs < earliest.startMs or (startMs = earliest.startMs and endMs < earliest.endMs)
                            earliest = {startMs:startMs,endMs:endMs}
                        end if
                    end if
                end if
            end if
        end for
    end if
    if earliest <> invalid then return earliest.endMs
    if UiField(item,"type","") <> "movie" then return 0
    if durationMs <= 0 then return 45000
    fallback = durationMs - 1000
    if fallback < 0 then return 0
    if fallback > 45000 then return 45000
    return fallback
end function

function PreviewBusy(state as Dynamic) as Boolean
    if type(state) <> "roAssociativeArray" then return false
    if UiField(state,"orphan",invalid) <> invalid then return true
    current = UiField(state,"current",invalid)
    if current = invalid then return false
    return PvTrue(UiField(current,"planPending",false)) or PvTrue(UiField(current,"nativeStarted",false)) or not PvTrue(UiField(current,"cleanupDone",true))
end function

sub PvIdle(state as Object, effects as Object)
    state.phase = "idle"
    if state.blocked then state.phase = "blocked"
    effects.Push({kind:"idle",blocked:state.blocked})
end sub

sub PvInitializeWanted(state as Object, wanted as Object)
    state.serial = state.serial + 1
    wanted["previewId"] = state.runId + "-" + state.serial.ToStr().Trim()
    wanted["retired"] = false
    wanted["prepared"] = false
    wanted["detailPending"] = true
    wanted["planPending"] = false
    wanted["nativeStarted"] = false
    wanted["nativeStopped"] = true
    wanted["nativeStopping"] = false
    wanted["cleanupDone"] = true
    wanted["cleanupPending"] = false
    wanted["cleanupFailed"] = false
    wanted["plan"] = invalid
    wanted["params"] = invalid
    wanted["stopId"] = wanted.previewId + "-stop"
end sub

' Preparation reads are allocation-free, including while a previous lease retires.
' Only the latest wanted candidate may allocate after its original dwell deadline.
sub PvAdvance(state as Object, effects as Object, nowMs as Double)
    if state.blocked
        state.phase = "blocked"
        return
    end if
    if state.orphan <> invalid
        state.phase = "retiring"
        return
    end if
    if state.current = invalid
        if state.wanted = invalid
            PvIdle(state,effects)
            return
        end if
        state.current = PvCopy(state.wanted)
    end if
    current = state.current
    if current.retired or current.planPending or current.nativeStarted then return
    if not current.prepared
        state.phase = "detail"
        return
    end if
    if nowMs < current.dueMs
        state.phase = "dwell"
        return
    end if
    current.planPending = true
    state.phase = "planning"
    effects.Push({kind:"request",action:"playback_start",params:current.params,purpose:"preview_plan",scope:current.scope,previewId:current.previewId})
end sub

function PvCleanupEffect(lease as Object) as Object
    return {kind:"cleanup",previewId:lease.previewId,scope:lease.scope,plan:lease.plan,stopId:lease.stopId}
end function

sub PvCleanup(lease as Object, effects as Object)
    if lease.cleanupDone or lease.cleanupPending or lease.plan = invalid then return
    lease.cleanupPending = true
    lease.cleanupFailed = false
    effects.Push(PvCleanupEffect(lease))
end sub

sub PvAttachPlan(current as Object, plan as Dynamic)
    if type(plan) <> "roAssociativeArray" then return
    current.plan = plan
    current.cleanupDone = true
    sessionId = UiField(plan,"sessionId","")
    if PvText(sessionId,1024)
        if sessionId <> "" then current.cleanupDone = false
    end if
    stopId = UiField(plan,"stopId",invalid)
    if PvIdentifier(stopId,128) then current.stopId = stopId
end sub

sub PvRetire(state as Object, effects as Object)
    current = state.current
    if current = invalid then return
    if current.retired then return
    current.retired = true
    if not current.planPending and not current.nativeStarted and current.plan = invalid
        state.current = invalid
        return
    end if
    state.phase = "retiring"
    if current.nativeStarted and not current.nativeStopped and not current.nativeStopping
        current.nativeStopping = true
        effects.Push({kind:"stop",attemptId:current.previewId})
    end if
    if not current.planPending then PvCleanup(current,effects)
end sub

sub PvSettle(state as Object, effects as Object, nowMs as Double)
    state.blocked = false
    if state.current <> invalid
        current = state.current
        if current.cleanupFailed then state.blocked = true
        if current.retired and not current.planPending and current.nativeStopped and current.cleanupDone then state.current = invalid
    end if
    if state.orphan <> invalid
        if state.orphan.cleanupFailed then state.blocked = true
        if state.orphan.cleanupDone then state.orphan = invalid
    end if
    if state.blocked
        state.phase = "blocked"
        return
    end if
    PvAdvance(state,effects,nowMs)
end sub

function PvResultMatches(current as Dynamic, event as Dynamic) as Boolean
    if current = invalid then return false
    previewId = UiField(event,"previewId","")
    scope = PvScope(UiField(event,"scope",invalid))
    if not PvText(previewId,112) or scope = invalid then return false
    return previewId = current.previewId and UiResultMatches(current.scope,scope)
end function

function PvSelectedVersion(current as Object, data as Dynamic) as Dynamic
    versions = UiField(data,"versions",invalid)
    if type(versions) <> "roArray" then return invalid
    selected = Int(current.versionIndex)
    if current.versionId <> ""
        selected = -1
        for index = 0 to versions.Count()-1
            if index >= 16 then exit for
            versionId = UiField(versions[index],"versionId","")
            if PvText(versionId,512)
                if versionId = current.versionId
                    selected = index
                    exit for
                end if
            end if
        end for
    end if
    if selected < 0 or selected >= versions.Count() then return invalid
    versionId = UiField(versions[selected],"versionId","")
    if not PvText(versionId,512) then return invalid
    if versionId = "" then return invalid
    markers = UiField(versions[selected],"markers",invalid)
    if type(markers) <> "roArray"
        markers = []
        if selected = 0 then markers = UiField(data,"markers",[])
    end if
    return {index:selected,versionId:versionId,markers:markers}
end function

function PvPrepare(wanted as Object, data as Dynamic) as Boolean
    candidateId = UiField(data,"candidateItemId","")
    if not PvText(candidateId,512) then return false
    if candidateId <> wanted.candidateItemId then return false
    item = PvItem(UiField(data,"item",invalid),wanted.scope)
    selected = PvSelectedVersion(wanted,data)
    if item = invalid or selected = invalid then return false
    if wanted.candidateType = "show"
        if item.type <> "episode" then return false
    else
        if item.itemId <> wanted.candidateItemId or item.type <> wanted.candidateType then return false
    end if
    wanted.item = item
    wanted["selectedVersionId"] = selected.versionId
    wanted["selectedVersionIndex"] = selected.index
    wanted["previewPositionMs"] = PreviewStartPositionMs(item,selected.markers)
    ' Backend start keeps saved Resume. Editorial presentation stays a local intent.
    resumeMs = item.resumeMs
    if resumeMs < 0 then resumeMs = 0
    params = {itemId:item.itemId,startPositionMs:resumeMs}
    if wanted.scope.provider = "plex"
        params["detail"] = data
        params["versionIndex"] = selected.index
        params["versionId"] = selected.versionId
        params["forceTranscode"] = true
        params["maxVideoBitrate"] = 2500
        params["videoResolution"] = "1280x720"
    else
        params["fileId"] = selected.versionId
        params["qualityPreference"] = "720p"
        params["bandwidthCapKbps"] = 2500
    end if
    wanted.params = params
    wanted.prepared = true
    wanted.detailPending = false
    return true
end function

function PvPlayablePlan(plan as Dynamic, current as Object) as Boolean
    if type(plan) <> "roAssociativeArray" then return false
    itemId = UiField(plan,"itemId","")
    sourceId = UiField(plan,"sourceId",current.scope.sourceId)
    provider = UiField(plan,"provider",current.scope.provider)
    versionId = UiField(plan,"versionId",current.selectedVersionId)
    if not PvText(itemId,512) or not PvText(sourceId,512) or not PvText(provider,8) or not PvText(versionId,512) then return false
    if itemId <> current.item.itemId or sourceId <> current.scope.sourceId or provider <> current.scope.provider or versionId <> current.selectedVersionId then return false
    ' Use the actual native owner's validation so a rejected start cannot hold the barrier forever.
    return VideoOwnerRequest({attemptId:current.previewId,mode:"preview",plan:plan,bounds:current.bounds,previewPositionMs:current.previewPositionMs}) <> invalid
end function

sub PvAbandonLate(state as Object, effects as Object, event as Object)
    plan = UiField(event,"plan",invalid)
    scope = PvScope(UiField(event,"scope",invalid))
    previewId = UiField(event,"previewId","")
    if type(plan) <> "roAssociativeArray" or scope = invalid or not PvIdentifier(previewId,112) then return
    sessionId = UiField(plan,"sessionId","")
    if not PvText(sessionId,1024) then return
    if sessionId = "" then return
    if state.orphan <> invalid then return
    orphan = {previewId:previewId,scope:scope,plan:invalid,stopId:previewId+"-stop",cleanupDone:true,cleanupPending:false,cleanupFailed:false}
    PvAttachPlan(orphan,plan)
    state.orphan = orphan
    PvCleanup(orphan,effects)
    ' Preserve prepared detail while the unrelated allocation is abandoned.
    ' PvAdvance prevents another allocation until the cleanup receipt arrives.
    state.phase = "retiring"
end sub

function PvCleanupMatches(lease as Dynamic, event as Object) as Boolean
    if lease = invalid then return false
    previewId = UiField(event,"previewId","")
    if not PvText(previewId,112) then return false
    if previewId <> lease.previewId then return false
    if not lease.cleanupPending then return false
    captured = PvScope(UiField(event,"scope",invalid))
    if captured = invalid then return false
    return UiResultMatches(lease.scope,captured)
end function

function PreviewReduce(previous as Dynamic, event as Dynamic) as Object
    state = PvCopy(previous)
    if state = invalid then state = PreviewCreate()
    state.current = PvCopy(state.current)
    state.wanted = PvCopy(state.wanted)
    state.orphan = PvCopy(state.orphan)
    effects = []
    result = {state:state,effects:effects}
    if type(event) <> "roAssociativeArray" then return result
    kind = UiField(event,"kind","")
    if not PvText(kind,32) then return result
    nowMs = UiNumber(UiField(event,"nowMs",0),0)
    if kind = "focus"
        wanted = PvFocus(event,nowMs)
        if PvSameFocus(state.wanted,wanted) then return result
        PvRetire(state,effects)
        state.wanted = wanted
        if wanted <> invalid
            PvInitializeWanted(state,wanted)
            supplied = UiField(event,"detail",invalid)
            if supplied <> invalid and wanted.candidateType <> "show"
                if not PvPrepare(wanted,supplied) then state.wanted = invalid
            else
                effects.Push({kind:"request",action:"preview_detail",params:{itemId:wanted.candidateItemId,type:wanted.candidateType},purpose:"preview_detail",scope:wanted.scope,previewId:wanted.previewId})
            end if
            if state.wanted <> invalid then effects.Push({kind:"timer",milliseconds:1200})
        end if
        PvAdvance(state,effects,nowMs)
    else if kind = "dwell"
        PvAdvance(state,effects,nowMs)
    else if kind = "release"
        state.wanted = invalid
        PvRetire(state,effects)
        PvAdvance(state,effects,nowMs)
    else if kind = "detail_result"
        if not PvResultMatches(state.wanted,event) then return result
        wanted = state.wanted
        if not wanted.detailPending then return result
        usable = false
        if PvTrue(UiField(event,"ok",false)) then usable = PvPrepare(wanted,UiField(event,"data",invalid))
        if not usable
            state.wanted = invalid
            if PvResultMatches(state.current,event)
                if not state.current.planPending and not state.current.nativeStarted then state.current = invalid
            end if
        else if PvResultMatches(state.current,event)
            state.current = PvCopy(wanted)
        end if
        PvAdvance(state,effects,nowMs)
    else if kind = "plan_result"
        if not PvResultMatches(state.current,event)
            PvAbandonLate(state,effects,event)
            return result
        end if
        current = state.current
        if not current.planPending then return result
        current.planPending = false
        returned = UiField(event,"plan",invalid)
        PvAttachPlan(current,returned)
        if current.retired or not PvTrue(UiField(event,"ok",false)) or not PvPlayablePlan(returned,current) or state.orphan <> invalid
            if not current.retired then state.wanted = invalid
            current.retired = true
            state.phase = "retiring"
            PvCleanup(current,effects)
            PvSettle(state,effects,nowMs)
            return result
        end if
        current.nativeStarted = true
        current.nativeStopped = false
        state.phase = "starting"
        effects.Push({kind:"start",attemptId:current.previewId,mode:"preview",plan:current.plan,bounds:current.bounds,previewPositionMs:current.previewPositionMs})
    else if kind = "native"
        current = state.current
        if current = invalid then return result
        attemptId = UiField(event,"attemptId","")
        mode = UiField(event,"mode","")
        if not PvText(attemptId,112) or not PvText(mode,16) then return result
        if attemptId <> current.previewId or mode <> "preview" then return result
        nativeState = UiField(event,"state","")
        if not PvText(nativeState,32) or not current.nativeStarted then return result
        if nativeState = "stopped"
            current.nativeStopped = true
            if not current.retired
                state.wanted = invalid
                PvRetire(state,effects)
            end if
            PvSettle(state,effects,nowMs)
        else if not current.retired
            if nativeState = "playing" then state.phase = "active"
            if nativeState = "stopping" then current.nativeStopping = true
            if nativeState = "finished" or nativeState = "error" or nativeState = "stopping"
                state.wanted = invalid
                PvRetire(state,effects)
            end if
        end if
    else if kind = "cleanup_result"
        lease = invalid
        if PvCleanupMatches(state.current,event) then lease = state.current
        if lease = invalid and PvCleanupMatches(state.orphan,event) then lease = state.orphan
        if lease = invalid then return result
        lease.cleanupPending = false
        lease.cleanupDone = PvTrue(UiField(event,"ok",false))
        lease.cleanupFailed = not lease.cleanupDone
        PvSettle(state,effects,nowMs)
        if state.blocked then effects.Push({kind:"idle",blocked:true})
    else if kind = "retry_cleanup"
        if state.current <> invalid
            if state.current.cleanupFailed then PvCleanup(state.current,effects)
        end if
        if state.orphan <> invalid
            if state.orphan.cleanupFailed then PvCleanup(state.orphan,effects)
        end if
    end if
    return result
end function
