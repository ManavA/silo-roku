' Resolve and remember only inside NativePlayer, against private SDK inventories.
sub NativePlayerPreferenceBind(request as Object)
    scope=TpoScope(VoField(request,"trackScope",invalid))
    m.trackPreference={scope:scope,revision:0,audioTouched:false,pending:invalid,ack:invalid}
end sub
function NativePlayerPreferencePrepare(command as Object) as Dynamic
    context=VoField(command,"preferenceContext",invalid)
    if context=invalid then return invalid
    denied={ok:false}
    state=VoField(m,"trackPreference",invalid)
    scope=TpoScope(VoField(context,"scope",invalid))
    if state=invalid or not TpoSame(VoField(state,"scope",invalid),scope) then return denied
    if not TpoNativeCommand(command) then return denied
    if not NativePlayerTrackSelectionCurrent() or not NtAvailable(m.nativeTracks) or not NtScopeMatches(m.nativeTracks,command) then return denied
    id=VoField(command,"commandId",invalid)
    revision=VoField(context,"revision",invalid)
    if not NtInteger(id,1) or id<=m.nativeTracks.highCommandId or not TpoWhole(revision,1) then return denied
    if revision<state.revision or m.nativeTracks.pending<>invalid then return denied
    remember=VoField(context,"remember",true)
    if type(remember)<>"Boolean" and type(remember)<>"roBoolean" then return denied
    preference=TpoRecord(VoField(context,"preference",invalid),scope)
    if preference=invalid then return denied
    kind=VoField(command,"kind","")
    intent=VoField(command,"intent","")
    if not VoString(kind) or not VoString(intent) then return denied
    if kind<>"audio" and kind<>"subtitle" then return denied
    prepared={ok:true,native:command,record:invalid,scope:scope,revision:revision,commandId:id,kind:kind,intent:intent}
    for each key in ["attemptId","versionId","clipId","inventoryRevision"]
        prepared[key]=command[key]
    end for
    raw=m.video.availableAudioTracks
    if kind="subtitle" then raw=m.video.availableSubtitleTracks
    if intent="auto" or intent="preference"
        if VoField(command,"handle","")<>"" then return denied
        desired=preference
        if intent="auto"
            if kind="audio"
                if remember then prepared.record=TrackPreferenceRemember(preference,scope,"audio","",raw)
                prepared.direct="applied"
                if state.audioTouched then prepared.direct="deferred"
                return prepared
            end if
            desired=TrackPreferenceSetMode(preference,scope,"auto")
            if remember then prepared.record=desired
        end if
        resolved=invalid
        if kind="subtitle" and desired.subtitleMode="off"
            if m.nativeTracks.savedCaptionMode="" then prepared.direct="deferred":return prepared
            resolved={kind:"subtitle",trackId:"",captionMode:"Off"}
        else
            resolved=TrackPreferenceResolve(desired,scope,kind,raw)
        end if
        if resolved=invalid
            prepared.direct="deferred"
            return prepared
        end if
        converted={}
        for each key in command
            converted[key]=command[key]
        end for
        converted.intent="select"
        if VoField(resolved,"captionMode","")="Off"
            converted.intent="off":converted.handle=""
        else
            tracks=m.nativeTracks.audio
            if kind="subtitle" then tracks=m.nativeTracks.subtitles
            converted.handle=NtCurrentHandle(tracks,resolved.trackId,kind,m.nativeTracks.inventoryRevision)
            if converted.handle="" then prepared.direct="deferred":return prepared
        end if
        prepared.native=converted
        return prepared
    end if
    if intent<>"select" and intent<>"off" then return denied
    selected=""
    if intent="select"
        tracks=m.nativeTracks.audio
        if kind="subtitle" then tracks=m.nativeTracks.subtitles
        handle=VoField(command,"handle",invalid)
        if not VoString(handle) then return denied
        for index=0 to tracks.Count()-1
            if NtHandle(kind,m.nativeTracks.inventoryRevision,index)=handle then selected=tracks[index].rawId
        end for
        if selected="" then return denied
    else if kind<>"subtitle" or VoField(command,"handle","")<>""
        return denied
    end if
    if remember then prepared.record=TrackPreferenceRemember(preference,scope,kind,selected,raw)
    return prepared
end function
sub NativePlayerPreferenceRegister(decision as Object,prepared as Dynamic)
    if prepared=invalid or not VoTrue(VoField(prepared,"ok",false)) or not decision.accepted then return
    if not VoTrue(VoField(decision.state.lastCommand,"accepted",false)) then return
    m.trackPreference.revision=prepared.revision
    m.trackPreference.ack=invalid
    if prepared.kind="audio" and prepared.intent<>"auto" then m.trackPreference.audioTouched=true
    m.trackPreference.pending=prepared
end sub
sub NativePlayerPreferenceDirect(prepared as Object)
    if prepared.commandId<=m.nativeTracks.highCommandId then return
    m.nativeTracks.highCommandId=prepared.commandId
    m.nativeTracks.lastCommand={commandId:prepared.commandId,accepted:true,result:prepared.direct}
    m.trackPreference.revision=prepared.revision
    m.trackPreference.pending=invalid
    m.trackPreference.ack=prepared
    NativePlayerPublishTracks()
end sub
function NativePlayerPreferenceStatus(status as Object) as Object
    state=VoField(m,"trackPreference",invalid)
    if state=invalid or not NativePlayerTrackSelectionCurrent() then return status
    if state.scope<>invalid then status["audioAutomatic"]=not state.audioTouched
    pending=VoField(state,"pending",invalid)
    ack=VoField(status,"lastCommand",invalid)
    if pending<>invalid
        if VoField(ack,"commandId",0)=pending.commandId
            result=VoField(ack,"result","")
            if result="applied" and VoTrue(VoField(ack,"accepted",false))
                state.ack=pending:state.pending=invalid
            else if result<>"issued"
                state.ack=invalid:state.pending=invalid
            end if
        end if
    end if
    remembered=VoField(state,"ack",invalid)
    if remembered=invalid then return status
    if not TpoSame(state.scope,remembered.scope) or remembered.revision<>state.revision then return status
    if not NtScopeMatches(m.nativeTracks,remembered) then return status
    if VoField(ack,"commandId",0)<>remembered.commandId or not VoTrue(VoField(ack,"accepted",false)) then return status
    result=VoField(ack,"result","")
    if result<>"applied" and result<>"deferred" then return status
    record=TpoRecord(remembered.record,state.scope)
    if record<>invalid
        publicAck={commandId:remembered.commandId,accepted:true,result:result,preference:record,preferenceRevision:remembered.revision}
        status["lastCommand"]=publicAck
    end if
    return status
end function
