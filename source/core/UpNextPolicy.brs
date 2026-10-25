' A rendered-clock continuation intent. Provider close/progress remain in Ap/Pd.
' Private scopes may contain Silo's canonical server URL; projections never do.
function UnScope(raw as Dynamic, lease = false as Boolean) as Dynamic
    provider = MpField(raw,"provider","")
    if not MpString(provider) then return invalid
    if provider<>"plex" and provider<>"silo" then return invalid
    if not MpSourceIdentity(MpField(raw,"sourceId",invalid),provider) then return invalid
    if not MpText(MpField(raw,"profileId",invalid),true) or not MpInteger(MpField(raw,"generation",invalid),0) then return invalid
    scope={provider:provider,sourceId:raw.sourceId,profileId:raw.profileId,generation:raw.generation}
    if lease
        sessionId=MpField(raw,"sessionId",invalid)
        if not MpText(sessionId,true) then return invalid
        scope["sessionId"]=sessionId
    end if
    return scope
end function

function UpNextCreate(config as Dynamic) as Dynamic
    scope=UnScope(MpField(config,"scope",invalid))
    lease=UnScope(MpField(config,"leaseScope",invalid),true)
    if scope=invalid or lease=invalid then return invalid
    for each field in ["provider","sourceId","profileId"]
        if scope[field]<>lease[field] then return invalid
    end for
    item=CoOwnedCard(MpField(config,"item",invalid),scope)
    if item=invalid then return invalid
    if item.type<>"episode" then return invalid
    for each field in ["attemptId","versionId","lookupId","previousLookupId","stopId"]
        if not MpText(MpField(config,field,invalid)) then return invalid
    end for
    if not EnLookupId(config.lookupId) or not EnLookupId(config.previousLookupId) then return invalid
    duration=MpField(config,"durationMs",invalid)
    offset=MpField(config,"timelineOffsetMs",invalid)
    streak=MpField(config,"autoplayStreak",invalid)
    if not MpNumber(duration) or not MpNumber(offset) or not MpInteger(streak,0) then return invalid
    if duration<0 or duration>604800000 or offset<0 or offset>604800000 or streak>1000 then return invalid
    for each field in ["relativeTimeline","autoplayAllowed"]
        value=MpField(config,field,invalid)
        if type(value)<>"Boolean" and type(value)<>"roBoolean" then return invalid
    end for
    if not config.relativeTimeline then offset=0
    state={scope:scope,leaseScope:lease,item:item,itemId:item.itemId,attemptId:config.attemptId,versionId:config.versionId,
        lookupId:config.lookupId,previousLookupId:config.previousLookupId,stopId:config.stopId,
        durationMs:duration,offsetMs:offset,autoplayAllowed:config.autoplayAllowed,autoplayStreak:streak,
        read:false,neighborStatus:"unavailable",next:invalid,previous:invalid,nextProof:invalid,previousProof:invalid,
        markers:[],targetMs:0,promptMs:0,phase:"watching",origin:"",target:invalid,
        clipId:-1,renderedEpoch:-1,renderedMs:-1,nativeState:"starting",landed:false,settling:false,
        dismissed:false,asked:false,stillWatching:false,finishedHeld:false,forced:false,focus:"play",
        nativeStopped:false,terminalAck:false}
    UnTiming(state)
    return state
end function

sub UnTiming(state as Object)
    ' Android fb672161 MarkerActions: target is the earliest valid latter-half
    ' credits START. Final is not a later-marker preference for this countdown.
    if state["durationMs"]<=0
        state["targetMs"]=-1
        state["promptMs"]=-1
        return
    end if
    target=-1
    for each marker in state["markers"]
        if marker.type="credits" and marker.endMs>marker.startMs
            if marker.startMs>=state["durationMs"]/2 and marker.startMs<state["durationMs"]
                if target<0 or marker.startMs<target then target=marker.startMs
            end if
        end if
    end for
    if target<0
        lead=state["durationMs"]/10
        if lead>60000 then lead=60000
        target=state["durationMs"]-lead
    end if
    state["targetMs"]=target
    state["promptMs"]=target-30000
    if state["promptMs"]<0 then state["promptMs"]=0
end sub

function UnMatches(state as Object, event as Dynamic, receipt = false as Boolean) as Boolean
    expected=state["scope"]
    fields=["provider","sourceId","profileId","generation"]
    if receipt
        expected=state["leaseScope"]
        fields.Push("sessionId")
    end if
    actual=UnScope(MpField(event,"scope",invalid),receipt)
    if actual=invalid then return false
    for each field in fields
        if MpField(actual,field,invalid)<>expected[field] then return false
    end for
    for each field in ["attemptId","versionId","itemId"]
        value=MpField(event,field,invalid)
        if not MpText(value) then return false
        if value<>state[field] then return false
    end for
    if receipt then return MpField(event,"stopId",invalid)=state["stopId"]
    return true
end function

function UnRendered(state as Object) as Boolean
    return state["clipId"]>=0 and state["renderedEpoch"]=0 and state["renderedMs"]>=0 and state["renderedMs"]<=604800000 and (state["durationMs"]<=0 or state["renderedMs"]<=state["durationMs"])
end function

' Only a previously visible low-answer popup can retain an owned finished frame.
' This flag supplies no native/provider close receipt or progress authority.
function UnFinishedHeld(state as Dynamic) as Boolean
    if type(state)<>"roAssociativeArray" then return false
    if not MpTrue(MpField(state,"finishedHeld",false)) then return false
    if state.phase<>"watching" or state.nativeState<>"finished" then return false
    if not state.asked or not state.stillWatching or state.dismissed then return false
    if not state.landed or state.settling or not UnRendered(state) then return false
    return state.durationMs>0 and state.next<>invalid and (state.forced or state.renderedMs>=state.promptMs)
end function

function UpNextProjection(state as Dynamic) as Object
    projection={active:false,shown:false,closing:false,blocked:false,nextAvailable:false,previousAvailable:false,
        countdownSeconds:0,countdownStarted:false,stillWatching:false,focus:"play",title:"",nextTitle:""}
    if type(state)<>"roAssociativeArray" then return projection
    projection["attemptId"]=state["attemptId"]
    projection["versionId"]=state["versionId"]
    projection["itemId"]=state["itemId"]
    projection["clipId"]=state["clipId"]
    projection["renderedEpoch"]=state["renderedEpoch"]
    if state["phase"]="advanced" or state["phase"]="cancelled" or state["phase"]="complete" then return projection
    projection["active"]=true
    projection["nextAvailable"]=state["next"]<>invalid
    projection["previousAvailable"]=state["previous"]<>invalid
    projection["closing"]=state["phase"]="closing" or state["phase"]="blocked"
    projection["blocked"]=state["phase"]="blocked"
    projection["focus"]=state["focus"]
    projection["stillWatching"]=state["stillWatching"]
    projection["title"]="Up Next"
    if state["stillWatching"] then projection["title"]="Still watching?"
    if state["next"]<>invalid then projection["nextTitle"]=Left(state["next"].title,120)
    if projection["closing"]
        projection["shown"]=true
        return projection
    end if
    if state["nativeState"]="finished" and not UnFinishedHeld(state) then return projection
    due=state["forced"] or state["renderedMs"]>=state["promptMs"]
    projection["shown"]=state["durationMs"]>0 and state["next"]<>invalid and not state["dismissed"] and state["landed"] and UnRendered(state) and not state["settling"] and due
    if projection["shown"] and state["renderedMs"]>=state["promptMs"] and state["autoplayAllowed"] and not state["stillWatching"]
        remaining=(state["targetMs"]-state["renderedMs"])/1000
        if remaining>0
            projection["countdownSeconds"]=-Int(-remaining)
            if projection["countdownSeconds"]>30 then projection["countdownSeconds"]=30
            projection["countdownStarted"]=true
        end if
    end if
    return projection
end function

sub UnClose(state as Object, effects as Object, origin as String, target as Dynamic)
    if state["phase"]<>"watching" then return
    state["phase"]="closing"
    state["finishedHeld"]=false
    state["origin"]=origin
    state["target"]=target
    if origin="manual_next" or origin="manual_previous" then state["autoplayStreak"]=0
    ' The coordinator uses ApClose's actual ledger. No position, completion,
    ' watched or progress-persistence value is synthesized by this intent.
    effects.Push({kind:"close",attemptId:state["attemptId"],versionId:state["versionId"],scope:MpCopy(state["leaseScope"]),
        stopId:state["stopId"],origin:origin,target:target})
end sub

sub UnAdvance(state as Object, effects as Object)
    if state["phase"]<>"closing" and state["phase"]<>"blocked" then return
    if not state["nativeStopped"] or not state["terminalAck"] then return
    if state["target"]=invalid
        if state["neighborStatus"]<>"pending" then state["phase"]="complete"
        return
    end if
    state["phase"]="advanced"
    if state["origin"]="automatic_next" or state["origin"]="ended"
        if state["autoplayStreak"]<1000 then state["autoplayStreak"]++
    end if
    effects.Push({kind:"advance",target:state["target"],origin:state["origin"],attemptId:state["attemptId"],
        versionId:state["versionId"],scope:MpCopy(state["scope"]),autoplayStreak:state["autoplayStreak"]})
end sub

sub UnEvaluate(state as Object, effects as Object, launch as Boolean)
    if state["phase"]<>"watching" then return
    projection=UpNextProjection(state)
    if launch and state["autoplayAllowed"] and projection["shown"] and not state["asked"]
        state["asked"]=true
        if state["autoplayStreak"]>=3 then effects.Push({kind:"ask_still_watching",attemptId:state["attemptId"],versionId:state["versionId"],scope:MpCopy(state["scope"])})
    end if
    if not launch or not state["autoplayAllowed"] or state["dismissed"] or state["stillWatching"] or not state["landed"] or not UnRendered(state) or state["settling"] then return
    if state["nativeState"]="finished"
        if state["next"]<>invalid or state["neighborStatus"]="pending" then UnClose(state,effects,"ended",state["next"])
    else if state["nativeState"]="playing" and state["durationMs"]>0 and state["next"]<>invalid and state["renderedMs"]>=state["targetMs"]
        UnClose(state,effects,"automatic_next",state["next"])
    end if
end sub

function UnCompactProof(proof as Object) as Object
    compact={}
    for each field in ["status","provider","sourceId","profileId","generation","lookupId","currentItemId","nextItemId","seriesId","currentSeasonNumber","nextSeasonNumber","currentSeasonItemId","nextSeasonItemId"]
        compact[field]=MpField(proof,field,invalid)
    end for
    return compact
end function

function UnPreviousAvailable(state as Object, candidate as Object, detail as Dynamic) as Boolean
    item=CoOwnedCard(MpField(detail,"item",invalid),state["scope"])
    if item=invalid or item.itemId<>candidate.itemId then return false
    versions=MpField(detail,"versions",invalid)
    if type(versions)<>"roArray" then return false
    for index=0 to versions.Count()-1
        if index>=20 then exit for
        if EnAvailableVersion(versions[index],item,state["scope"]) then return true
    end for
    return false
end function

function UpNextReduce(previous as Dynamic, event as Dynamic) as Object
    result={state:previous,effects:[],accepted:false,render:invalid}
    if type(previous)<>"roAssociativeArray" or type(event)<>"roAssociativeArray" then return result
    if previous.phase="advanced" or previous.phase="cancelled" or previous.phase="complete" then return result
    kind=MpField(event,"kind","")
    if not MpString(kind) then return result
    receipt=kind="native_stopped" or kind="terminal_result"
    if not UnMatches(previous,event,receipt) then return result
    state=MpCopy(previous)
    effects=result.effects
    if kind="cancel"
        state["phase"]="cancelled"
        state["finishedHeld"]=false
    else if receipt
        if state["phase"]<>"closing" and state["phase"]<>"blocked" then return result
        if kind="native_stopped"
            state["nativeStopped"]=true
        else
            if not MpTrue(MpField(event,"terminal",false)) then return result
            if not MpTrue(MpField(event,"ok",false))
                state["phase"]="blocked"
                state["terminalAck"]=false
            else
                state["terminalAck"]=true
                state["phase"]="closing"
            end if
        end if
        UnAdvance(state,effects)
    else if kind="retry"
        if state["phase"]<>"blocked" then return result
        state["phase"]="closing"
        effects.Push({kind:"retry_terminal",scope:MpCopy(state["leaseScope"]),stopId:state["stopId"],attemptId:state["attemptId"],versionId:state["versionId"]})
    else if kind="neighbors"
        direction=MpField(event,"direction","")
        if not MpString(direction) then return result
        if direction<>"next" and direction<>"previous" then return result
        lookup=state["lookupId"]
        if direction="previous" then lookup=state["previousLookupId"]
        if MpField(event,"lookupId",invalid)<>lookup then return result
        if state["phase"]<>"watching" and (state["origin"]<>"ended" or direction<>"next" or state["target"]<>invalid) then return result
        status=MpField(event,"status","")
        if not MpString(status) then return result
        if status<>"known" and status<>"verified_end" and status<>"retryable" and status<>"ambiguous" then return result
        if direction="next"
            state["neighborStatus"]=status
            state["next"]=invalid
            state["nextProof"]=invalid
        else
            state["previous"]=invalid
            state["previousProof"]=invalid
        end if
        if status="known"
            candidate=CoOwnedCard(MpField(event,"candidate",invalid),state["scope"])
            proof=MpField(event,"proof",invalid)
            proofScope=MpCopy(state["scope"])
            proofScope["lookupId"]=lookup
            valid=false
            if candidate<>invalid
                if direction="next"
                    valid=EpisodeNeighborsProofMatches(proof,state["item"],candidate,proofScope)
                else
                    valid=EpisodeNeighborsProofMatches(proof,candidate,state["item"],proofScope) and UnPreviousAvailable(state,candidate,MpField(event,"detail",invalid))
                end if
            end if
            if valid
                if direction="next"
                    state["next"]=candidate
                    state["nextProof"]=UnCompactProof(proof)
                    if state["origin"]="ended" then state["target"]=candidate
                else
                    state["previous"]=candidate
                    state["previousProof"]=UnCompactProof(proof)
                end if
            else if direction="next"
                state["neighborStatus"]="ambiguous"
            end if
        end if
        UnAdvance(state,effects)
    else if kind="markers"
        if state["phase"]<>"watching" then return result
        state["markers"]=MpMarkers(MpField(event,"markers",invalid),state["durationMs"])
        UnTiming(state)
    else if kind="native"
        if state["phase"]<>"watching" then return result
        status=MpField(event,"status",invalid)
        if MpField(status,"attemptId",invalid)<>state["attemptId"] or MpField(status,"mode",invalid)<>"playback" then return result
        clip=MpField(status,"clipId",invalid)
        if not MpInteger(clip,0) then return result
        if state["clipId"]>=0 and clip<>state["clipId"] then return result
        nativeState=MpField(status,"state","")
        if not MpString(nativeState) then return result
        if nativeState<>"playing" and nativeState<>"paused" and nativeState<>"buffering" and nativeState<>"finished" and nativeState<>"stopping" and nativeState<>"stopped" and nativeState<>"error" then return result
        nativeCode=MpField(status,"errorCode",invalid)
        if not MpInteger(nativeCode,-2147483646) then return result
        priorPopup=UpNextProjection(previous)
        priorHold=previous.asked and previous.stillWatching and priorPopup.shown
        if previous.nativeState="finished" and not UnFinishedHeld(previous) then priorHold=false
        state["clipId"]=clip
        state["nativeState"]=nativeState
        state["landed"]=MpTrue(MpField(event,"landed",false))
        state["settling"]=MpTrue(MpField(event,"settling",false))
        state["renderedMs"]=-1
        state["renderedEpoch"]=-1
        state["finishedHeld"]=false
        seconds=MpField(status,"renderedPosition",invalid)
        epoch=MpField(status,"renderedEpoch",invalid)
        code=MpField(status,"errorCode",invalid)
        renderedClip=MpField(status,"renderedClipId",invalid)
        if MpNumber(seconds) and MpInteger(epoch,0) and MpInteger(code,0) and MpInteger(renderedClip,0)
            if seconds>=0 and seconds<=604800 and epoch=0 and code=0 and renderedClip=clip
                absolute=seconds*1000+state["offsetMs"]
                if absolute<=604800000 and (state["durationMs"]<=0 or absolute<=state["durationMs"])
                    state["renderedMs"]=absolute
                    state["renderedEpoch"]=0
                end if
            end if
        end if
        if nativeCode<>0 or nativeState="error" or nativeState="stopped" or nativeState="stopping"
            state["phase"]="cancelled"
        else
            if nativeState="finished" and priorHold
                state["finishedHeld"]=state.landed and not state.settling and UnRendered(state)
            end if
            if nativeState="playing" and not state["read"]
                state["read"]=true
                state["neighborStatus"]="pending"
                effects.Push({kind:"request_neighbors",scope:MpCopy(state["scope"]),attemptId:state["attemptId"],versionId:state["versionId"],
                    lookupId:state["lookupId"],anchor:state["item"],playbackSessionId:state["leaseScope"].sessionId})
                effects.Push({kind:"request_neighbors",direction:"previous",scope:MpCopy(state["scope"]),attemptId:state["attemptId"],versionId:state["versionId"],
                    lookupId:state["previousLookupId"],anchor:state["item"],playbackSessionId:state["leaseScope"].sessionId})
            end if
            UnEvaluate(state,effects,not MpTrue(MpField(event,"quiet",false)))
        end if
    else if kind="watching_result"
        if state["phase"]<>"watching" or not state["asked"] or state["dismissed"] then return result
        if state["nativeState"]="finished" or not UpNextProjection(state).shown then return result
        value=MpField(event,"probability",invalid)
        if not MpNumber(value) then return result
        if value<0 or value>1 then return result
        if value<=.2 then state["stillWatching"]=true
    else if kind="final_marker"
        if state["phase"]<>"watching" or state["next"]=invalid or state["dismissed"] or not state["landed"] or not UnRendered(state) then return result
        if not MpInteger(MpField(event,"clipId",invalid),0) or not MpInteger(MpField(event,"renderedEpoch",invalid),0) then return result
        if event.clipId<>state["clipId"] or event.renderedEpoch<>0 then return result
        raw=MpField(event,"marker",invalid)
        if not MpString(MpField(raw,"type",invalid)) or not MpNumber(MpField(raw,"startMs",invalid)) or not MpNumber(MpField(raw,"endMs",invalid)) then return result
        hydrated=invalid
        for each marker in state["markers"]
            if MpField(raw,"type",invalid)=marker.type and MpField(raw,"startMs",invalid)=marker.startMs and MpField(raw,"endMs",invalid)=marker.endMs and MpTrue(MpField(raw,"isFinal",false))=marker.isFinal then hydrated=marker
        end for
        if hydrated=invalid then return result
        if not hydrated.isFinal and hydrated.endMs<state["durationMs"]-1500 then return result
        if state["renderedMs"]<hydrated.startMs then return result
        state["forced"]=true
        state["settling"]=MpTrue(MpField(event,"settling",true))
    else if kind="focus"
        if state["phase"]<>"watching" and state["phase"]<>"closing" and state["phase"]<>"blocked" then return result
        focus=MpField(event,"focus",invalid)
        if not MpString(focus) then return result
        if focus<>"play" and focus<>"dismiss" then return result
        state["focus"]=focus
    else if kind="intent"
        if state["phase"]<>"watching" then return result
        action=MpField(event,"action","")
        if action="dismiss"
            state["dismissed"]=true
            state["finishedHeld"]=false
            state["autoplayStreak"]=0
        else
            manualState=state["nativeState"]="playing" or state["nativeState"]="paused" or UnFinishedHeld(state)
            if not UnRendered(state) or state["settling"] or not manualState then return result
            target=invalid
            origin="manual_next"
            if action="next" then target=state["next"]
            if action="previous"
                target=state["previous"]
                origin="manual_previous"
            end if
            if target=invalid then return result
            UnClose(state,effects,origin,target)
        end if
    else
        return result
    end if
    result.state=state
    result.accepted=true
    projection=UpNextProjection(state)
    if FormatJson(projection)<>FormatJson(UpNextProjection(previous)) then result.render=projection
    return result
end function
