' One compact source/profile preference owner. Native IDs never enter this state.
function TpoField(value as Dynamic,key as String,fallback as Dynamic) as Dynamic
    if type(value)<>"roAssociativeArray" then return fallback
    if not value.DoesExist(key) then return fallback
    return value[key]
end function
function TpoBool(value as Dynamic) as Boolean
    if type(value)<>"Boolean" and type(value)<>"roBoolean" then return false
    return value
end function
function TpoWhole(value as Dynamic, minimum = 0 as Integer) as Boolean
    kind=type(value)
    if kind<>"Integer" and kind<>"roInt" and kind<>"roInteger" and kind<>"LongInteger" and kind<>"roLongInteger" and kind<>"Float" and kind<>"roFloat" and kind<>"Double" and kind<>"roDouble" then return false
    if value<>value or value<minimum or value>2147483646 then return false
    return value=Int(value)
end function
function TpoScope(raw as Dynamic) as Dynamic
    scoped=TrackPreferenceScope(raw)
    if scoped=invalid then return invalid
    provider=TpoField(raw,"provider",invalid)
    if type(provider)<>"String" and type(provider)<>"roString" then return invalid
    if provider<>"plex" and provider<>"silo" then return invalid
    if Left(scoped.sourceId,5)<>provider+":" then return invalid
    generation=TpoField(raw,"generation",invalid)
    if not TpoWhole(generation) then return invalid
    return {provider:provider,sourceId:scoped.sourceId,profileId:scoped.profileId,generation:generation}
end function
function TpoSame(left as Dynamic,right as Dynamic,viewer = false as Boolean) as Boolean
    first=TpoScope(left):second=TpoScope(right)
    if first=invalid or second=invalid then return false
    fields=["provider","sourceId","profileId","generation"]
    if viewer then fields=["provider","sourceId","profileId"]
    for each key in fields
        if first[key]<>second[key] then return false
    end for
    return true
end function
function TpoRecord(raw as Dynamic,scope as Dynamic) as Dynamic
    if type(raw)<>"roAssociativeArray" then return invalid
    active=TrackPreferenceScope(scope)
    if active=invalid or raw.Count()<>8 then return invalid
    keys={schemaversion:true,sourceid:true,profileid:true,subtitlemode:true,subtitlelanguage:true,subtitlename:true,audiolanguage:true,audioname:true}
    for each key in raw
        if not keys.DoesExist(LCase(key)) then return invalid
    end for
    if not TpoWhole(TpoField(raw,"schemaVersion",invalid),1) then return invalid
    if raw.schemaVersion<>1 or TpoField(raw,"sourceId",invalid)<>active.sourceId or TpoField(raw,"profileId",invalid)<>active.profileId then return invalid
    for each key in ["subtitleMode","subtitleLanguage","subtitleName","audioLanguage","audioName"]
        value=TpoField(raw,key,invalid)
        if type(value)<>"String" and type(value)<>"roString" then return invalid
        if key="subtitleMode"
            if value<>"auto" and value<>"on" and value<>"off" then return invalid
        else if key="subtitleLanguage" or key="audioLanguage"
            if value<>"" and TrackPreferenceLanguage(value)="" then return invalid
        else if value<>"" and TrackPreferenceName(value)=""
            return invalid
        end if
    end for
    normalized=TrackPreferenceNormalize(raw,active)
    if Len(FormatJson(normalized))>1024 then return invalid
    return normalized
end function
function TpoCreate(scope as Dynamic) as Object
    active=TpoScope(scope)
    return {scope:active,preference:TrackPreferenceNormalize(invalid,active),revision:1,manualEpoch:0,sequence:0,
        loaded:false,readPending:invalid,writePending:invalid,queuedWrite:invalid,pendingMode:invalid,nativePending:invalid,status:""}
end function
function TpoCopy(previous as Object) as Object
    ' Trusted model keys may enumerate lowercase on Roku; retain normal lookup.
    state={}
    for each key in previous
        state[key]=previous[key]
    end for
    return state
end function
sub TpoRequest(out as Object,action as String,record as Dynamic)
    state=out.state
    if state.scope=invalid or state.sequence>=2147483646 then return
    state.sequence++
    params={}
    if action="track_pref_set" then params={preference:record}
    owner={operationId:"track-pref-"+state.sequence.ToStr(),manualEpoch:state.manualEpoch,revision:state.revision}
    ' Copy normalized scope with ordinary lookup after native key enumeration.
    captured={}
    for each key in state.scope
        captured[key]=state.scope[key]
    end for
    pending={action:action,params:params,scope:captured,preferenceOwner:owner}
    if action="track_pref_get" then state["readPending"]=pending else state["writePending"]=pending
    out.effects.Push({kind:"request",action:action,params:params,purpose:action,scope:captured,preferenceOwner:owner})
end sub
sub TpoSave(out as Object)
    state=out.state
    state.status="Saving track preference…"
    if state.writePending<>invalid
        state["queuedWrite"]=state.preference
    else
        TpoRequest(out,"track_pref_set",state.preference)
    end if
end sub
function TpoResultMatches(pending as Dynamic,job as Dynamic,result as Dynamic) as Boolean
    if type(pending)<>"roAssociativeArray" or type(job)<>"roAssociativeArray" or type(result)<>"roAssociativeArray" then return false
    id=TpoField(job,"requestId",invalid)
    if type(id)<>"String" and type(id)<>"roString" then return false
    if Len(id)=0 or Len(id)>128 or Instr(1,id,"://")>0 then return false
    if TpoField(result,"requestId",invalid)<>id then return false
    if not TpoSame(pending.scope,job) or not TpoSame(pending.scope,result) then return false
    if TpoField(job,"action",invalid)<>pending.action or TpoField(result,"action",invalid)<>pending.action then return false
    if FormatJson(TpoField(job,"params",invalid))<>FormatJson(pending.params) then return false
    if FormatJson(TpoField(job,"preferenceOwner",invalid))<>FormatJson(pending.preferenceOwner) then return false
    ' Audited worker envelope does not copy owner metadata or params.
    for each key in ["params","preferenceOwner"]
        if result.DoesExist(key)
            if FormatJson(result[key])<>FormatJson(pending[key]) then return false
        end if
    end for
    ok=TpoField(result,"ok",invalid)
    return type(ok)="Boolean" or type(ok)="roBoolean"
end function
function TpoReduce(previous as Object,event as Dynamic) as Object
    state=TpoCopy(previous)
    out={state:state,effects:[],accepted:false}
    kind=TpoField(event,"kind","")
    if kind="viewer"
        active=TpoScope(TpoField(event,"scope",invalid))
        if TpoSame(state.scope,active,true)
            state.scope=active
        else
            state=TpoCreate(active)
            state.sequence=previous.sequence
            out.state=state
        end if
        out.accepted=true
    else if kind="load"
        if state.scope=invalid or state.loaded or state.readPending<>invalid then return out
        TpoRequest(out,"track_pref_get",invalid)
        out.accepted=true
    else if kind="mode"
        mode=TpoField(event,"mode",invalid)
        if type(mode)<>"String" and type(mode)<>"roString" then return out
        record=TrackPreferenceSetMode(state.preference,state.scope,mode)
        if record=invalid or state.revision>=2147483646 or state.manualEpoch>=2147483646 then return out
        state.preference=record
        state.revision++:state["manualEpoch"]=state.manualEpoch+1
        if state.loaded
            TpoSave(out)
        else
            ' Preserve unknown stored audio fields; hold only the latest mode.
            state["pendingMode"]={mode:mode,manualEpoch:state.manualEpoch}
            state.status="Loading track preference before saving…"
            if state.readPending=invalid then TpoRequest(out,"track_pref_get",invalid)
        end if
        out.accepted=true
    else if kind="manual" or kind="automatic"
        command=TpoField(event,"command",invalid)
        if state.scope=invalid or state.nativePending<>invalid or not TpoNativeCommand(command) then return out
        if kind="manual"
            if state.revision>=2147483646 or state.manualEpoch>=2147483646 then return out
            state.revision++:state["manualEpoch"]=state.manualEpoch+1
            state["pendingMode"]=invalid
        end if
        native={}
        for each key in ["commandId","attemptId","versionId","clipId","inventoryRevision","kind","intent","handle"]
            native[key]=command[key]
        end for
        native["preferenceContext"]={scope:state.scope,revision:state.revision,preference:state.preference,remember:state.loaded}
        state["nativePending"]={command:native,scope:state.scope,revision:state.revision,manual:kind="manual"}
        out.effects.Push({kind:"native",command:native})
        out.accepted=true
    else if kind="manual_intent"
        if state.scope=invalid or state.manualEpoch>=2147483646 or state.revision>=2147483646 then return out
        state["manualEpoch"]=state.manualEpoch+1
        state["pendingMode"]=invalid
        state.revision++
        out.accepted=true
    else if kind="retire"
        state["nativePending"]=invalid
        out.accepted=true
    else if kind="native_result"
        pending=state.nativePending
        if pending=invalid then return out
        current=TpoField(event,"current",invalid)
        snapshot=TpoField(event,"snapshot",invalid)
        if not TpoSame(state.scope,pending.scope) then return out
        if not TpoNativeFenceMatches(pending.command,current) or not TpoNativeFenceMatches(pending.command,snapshot) then return out
        ack=TpoField(snapshot,"lastCommand",invalid)
        if TpoField(ack,"commandId",invalid)<>pending.command.commandId then return out
        accepted=TpoField(ack,"accepted",invalid)
        if type(accepted)<>"Boolean" and type(accepted)<>"roBoolean" then return out
        result=TpoField(ack,"result","")
        if result="issued" then return out
        state["nativePending"]=invalid
        out.accepted=true
        state.status="Track could not be selected."
        if not accepted then return out
        if result<>"applied" and result<>"deferred" then return out
        state.status="Track selected."
        if result="deferred" then state.status="Automatic will apply when a matching native lane is available or on the next playback."
        if not pending.manual then return out
        if not TpoBool(TpoField(pending.command.preferenceContext,"remember",false))
            state.status="Track selected; preference will not be saved until settings load."
            return out
        end if
        if result="deferred" and pending.command.intent<>"auto" then return out
        revision=TpoField(ack,"preferenceRevision",invalid)
        if not TpoWhole(revision,1) or revision<>pending.revision or revision<>state.revision then return out
        record=TpoRecord(TpoField(ack,"preference",invalid),state.scope)
        if not TpoNativeRecordMatches(pending.command,record) then return out
        state.preference=record:state.loaded=true
        TpoSave(out)
    else if kind="result"
        job=TpoField(event,"job",invalid):receipt=TpoField(event,"result",invalid)
        action=TpoField(job,"action","")
        pending=invalid
        if action="track_pref_get" then pending=state.readPending
        if action="track_pref_set" then pending=state.writePending
        if not TpoResultMatches(pending,job,receipt) then return out
        if not TpoSame(state.scope,pending.scope,true) then return out
        if action="track_pref_get"
            state["readPending"]=invalid
            waitingMode=state.pendingMode
            mergeMode=waitingMode<>invalid
            if mergeMode then mergeMode=waitingMode.manualEpoch=state.manualEpoch
            if pending.preferenceOwner.manualEpoch<>state.manualEpoch and not mergeMode then return out
            if not TpoBool(receipt.ok)
                state.status="Could not load track preference."
                out.accepted=true
                return out
            end if
            record=TpoRecord(TpoField(TpoField(receipt,"data",invalid),"preference",invalid),state.scope)
            if record=invalid then return out
            if mergeMode
                record=TrackPreferenceSetMode(record,state.scope,waitingMode.mode)
                if record=invalid then return out
            end if
            state.preference=record:state.loaded=true
            state["pendingMode"]=invalid
            if mergeMode then TpoSave(out)
        else
            record=TpoRecord(TpoField(TpoField(receipt,"data",invalid),"preference",invalid),state.scope)
            matched=record<>invalid
            if matched then matched=FormatJson(record)=FormatJson(pending.params.preference)
            if TpoBool(receipt.ok) and not matched then return out
            state["writePending"]=invalid
            state.status="Track preference saved for this source and profile."
            if not TpoBool(receipt.ok) then state.status="Could not save track preference."
            if state.queuedWrite<>invalid
                queued=state.queuedWrite:state["queuedWrite"]=invalid
                TpoRequest(out,"track_pref_set",queued)
                state.status="Saving track preference…"
            end if
        end if
        out.accepted=true
    end if
    return out
end function
function TpoSettings(state as Object) as Object
    if state.scope=invalid then return []
    mode=TpoField(state.preference,"subtitleMode","auto")
    rows=[]
    for each value in [{mode:"auto",title:"Subtitles: Auto English"},{mode:"on",title:"Subtitles: On when available"},{mode:"off",title:"Subtitles: Off"}]
        title=value.title
        if mode=value.mode then title+=" ✓"
        rows.Push({title:title,uiAction:"subtitle_"+value.mode})
    end for
    return rows
end function

function TpoNativeFenceMatches(left as Dynamic,right as Dynamic) as Boolean
    for each key in ["attemptId","versionId"]
        value=TpoField(right,key,invalid)
        if type(value)<>"String" and type(value)<>"roString" then return false
        if Len(value)=0 or Len(value)>256 or Instr(1,value,"://")>0 or value<>TpoField(left,key,invalid) then return false
    end for
    for each key in ["clipId","inventoryRevision"]
        value=TpoField(right,key,invalid)
        minimum=0
        if key="inventoryRevision" then minimum=1
        if not TpoWhole(value,minimum) or value<>TpoField(left,key,invalid) then return false
    end for
    return true
end function
function TpoNativeCommand(command as Dynamic) as Boolean
    if not TpoNativeFenceMatches(command,command) or not TpoWhole(TpoField(command,"commandId",invalid),1) then return false
    kind=TpoField(command,"kind",""):intent=TpoField(command,"intent",""):handle=TpoField(command,"handle",invalid)
    if type(kind)<>"String" and type(kind)<>"roString" then return false
    if type(intent)<>"String" and type(intent)<>"roString" then return false
    if kind<>"audio" and kind<>"subtitle" then return false
    if intent<>"select" and intent<>"off" and intent<>"auto" and intent<>"preference" then return false
    if type(handle)<>"String" and type(handle)<>"roString" then return false
    if Len(handle)>64 or Instr(1,handle,"://")>0 then return false
    if intent="select" then return Len(handle)>0
    return handle="" and (intent<>"off" or kind="subtitle")
end function
function TpoNativeRecordMatches(command as Object,record as Dynamic) as Boolean
    if record=invalid then return false
    before=command.preferenceContext.preference
    untouched=["subtitleMode","subtitleLanguage","subtitleName"]
    if command.kind="subtitle" then untouched=["audioLanguage","audioName"]
    for each key in untouched
        if record[key]<>before[key] then return false
    end for
    if command.intent="auto"
        if command.kind="audio" then return record.audioLanguage="" and record.audioName=""
        return record.subtitleMode="auto" and record.subtitleLanguage="eng" and record.subtitleName=""
    end if
    if command.kind="subtitle"
        if command.intent="off" then return record.subtitleMode="off"
        return record.subtitleMode="on"
    end if
    return record.audioLanguage<>"" or record.audioName<>""
end function

function TpoDispatchFailed(previous as Object,effect as Object) as Object
    state=TpoCopy(previous)
    out={state:state,effects:[],accepted:false}
    action=TpoField(effect,"action","")
    pending=invalid
    if action="track_pref_get" then pending=state.readPending
    if action="track_pref_set" then pending=state.writePending
    if pending=invalid or not TpoSame(pending.scope,TpoField(effect,"scope",invalid)) then return out
    if FormatJson(pending.params)<>FormatJson(TpoField(effect,"params",invalid)) then return out
    if FormatJson(pending.preferenceOwner)<>FormatJson(TpoField(effect,"preferenceOwner",invalid)) then return out
    if action="track_pref_get"
        state["readPending"]=invalid
        state.status="Could not load track preference."
    else
        state["writePending"]=invalid
        state["queuedWrite"]=invalid
        state.status="Could not save track preference."
    end if
    out.accepted=true
    return out
end function
