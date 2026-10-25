' One current viewer; provider storage receipts are authoritative for enabling.
function DpoWhole(value as Dynamic) as Boolean
    kind=type(value)
    if kind<>"Integer" and kind<>"roInt" and kind<>"roInteger" and kind<>"LongInteger" and kind<>"roLongInteger" and kind<>"Float" and kind<>"roFloat" and kind<>"Double" and kind<>"roDouble" then return false
    if value<>value or value<0 or value>2147483646 then return false
    return value=Int(value)
end function
function DpoScope(raw as Dynamic) as Dynamic
    provider=DpField(raw,"provider")
    if not DpText(provider,4) then return invalid
    if provider<>"plex" and provider<>"silo" then return invalid
    active=DpScope(raw):generation=DpField(raw,"generation")
    if active=invalid or not DpoWhole(generation) then return invalid
    return {provider:provider,sourceId:active.sourceId,profileId:active.profileId,generation:Int(generation)}
end function
function DpoSame(first as Dynamic,second as Dynamic,viewer=false as Boolean) as Boolean
    leftScope=DpoScope(first):rightScope=DpoScope(second)
    if leftScope=invalid or rightScope=invalid then return false
    fields=["provider","sourceId","profileId","generation"]
    if viewer then fields=["provider","sourceId","profileId"]
    for each key in fields
        if leftScope[key]<>rightScope[key] then return false
    end for
    return true
end function
function DpoFlat(raw as Dynamic) as Dynamic
    if type(raw)<>"roAssociativeArray" then return invalid
    result={}
    for each key in raw
        result[key]=raw[key]
    end for
    return result
end function
function DpoPendingCopy(raw as Dynamic) as Dynamic
    result=DpoFlat(raw)
    if result=invalid then return invalid
    result.scope=DpoFlat(DpField(raw,"scope"))
    result["decisionPreferenceOwner"]=DpoFlat(DpField(raw,"decisionPreferenceOwner"))
    if DpField(raw,"params")<>invalid
        result.params=DpoFlat(DpField(raw,"params"))
        record=DpField(DpField(raw,"params"),"preference")
        if record<>invalid then result.params.preference=DpoFlat(record)
    end if
    return result
end function
function DpoCopy(raw as Object) as Object
    result=DpoFlat(raw)
    for each key in ["scope","confirmed","desired","dirty"]
        result[key]=DpoFlat(DpField(raw,key))
    end for
    for each key in ["readPending","writePending","editor"]
        result[key]=DpoPendingCopy(DpField(raw,key))
    end for
    return result
end function
function DpoCreate(scope as Dynamic) as Object
    active=DpoScope(scope):record=DecisionPreferenceDefaults(active)
    return {scope:active,confirmed:record,desired:DpoFlat(record),dirty:{},loaded:false,error:false,
        sequence:0,revision:1,readPending:invalid,writePending:invalid,editor:invalid,status:""}
end function
function DpoId(raw as Dynamic) as Boolean
    if not DpText(raw,128) then return false
    return CreateObject("roRegex","^[A-Za-z0-9_.:-]+$","").IsMatch(raw)
end function
function DpoOwner(raw as Dynamic,origin=false as Boolean) as Boolean
    if not DpKeys(raw,["operationId","revision"]) then return false
    id=DpField(raw,"operationId"):revision=DpField(raw,"revision")
    if not DpoId(id) or not DpoWhole(revision) then return false
    if revision<1 then return false
    prefix="decision-pref-"
    if origin then prefix="decision-origin-"
    return CreateObject("roRegex","^"+prefix+"[0-9]{1,10}$","").IsMatch(id)
end function
function DpoHasField(raw as Dynamic,key as String) as Boolean
    if type(raw)<>"roAssociativeArray" then return false
    for each name in raw.Keys()
        if LCase(name)=LCase(key) then return true
    end for
    return false
end function
function DpoOwnersEqual(first as Dynamic,second as Dynamic,origin=false as Boolean) as Boolean
    if not DpoOwner(first,origin) or not DpoOwner(second,origin) then return false
    return DpField(first,"operationId")=DpField(second,"operationId") and DpField(first,"revision")=DpField(second,"revision")
end function
function DpoRecordsEqual(first as Dynamic,second as Dynamic,scope as Dynamic) as Boolean
    leftRecord=DecisionPreferenceNormalize(first,scope):rightRecord=DecisionPreferenceNormalize(second,scope)
    if leftRecord=invalid or rightRecord=invalid then return false
    for each key in ["schemaVersion","sourceId","profileId","personalized","cloudDecisions","stillWatchingCheck","gatewayOrigin"]
        if DpField(leftRecord,key)<>DpField(rightRecord,key) then return false
    end for
    return true
end function
function DpoParamsEqual(action as String,first as Dynamic,second as Dynamic,scope as Dynamic) as Boolean
    if type(first)<>"roAssociativeArray" or type(second)<>"roAssociativeArray" then return false
    if action="decision_pref_get" then return first.Count()=0 and second.Count()=0
    if action<>"decision_pref_set" then return false
    if not DpKeys(first,["preference"]) or not DpKeys(second,["preference"]) then return false
    return DpoRecordsEqual(DpField(first,"preference"),DpField(second,"preference"),scope)
end function
function DpoEffectMatches(pending as Dynamic,raw as Dynamic) as Boolean
    if type(pending)<>"roAssociativeArray" or type(raw)<>"roAssociativeArray" then return false
    if not DpoSame(pending.scope,DpField(raw,"scope")) then return false
    if DpField(raw,"action")<>pending.action or DpField(raw,"purpose")<>pending.action then return false
    cleanup=DpField(raw,"cleanup")
    if not DpBool(cleanup) then return false
    if cleanup then return false
    if not DpoOwnersEqual(pending.decisionPreferenceOwner,DpField(raw,"decisionPreferenceOwner")) then return false
    return DpoParamsEqual(pending.action,pending.params,DpField(raw,"params"),pending.scope)
end function
function DpoJobMatches(pending as Dynamic,job as Dynamic) as Boolean
    if type(pending)<>"roAssociativeArray" or type(job)<>"roAssociativeArray" then return false
    if not DpoSame(pending.scope,job) or DpField(job,"action")<>pending.action then return false
    if not DpoId(DpField(job,"requestId")) then return false
    if not DpoOwnersEqual(pending.decisionPreferenceOwner,DpField(job,"decisionPreferenceOwner")) then return false
    return DpoParamsEqual(pending.action,pending.params,DpField(job,"params"),pending.scope)
end function
sub DpoRequest(out as Object,action as String)
    state=out.state
    if state.scope=invalid or state.sequence>=2147483646 then return
    state.sequence++
    params={}
    if action="decision_pref_set" then params={preference:DpoFlat(state.desired)}
    owner={operationId:"decision-pref-"+state.sequence.ToStr(),revision:state.revision}
    pending={action:action,scope:DpoFlat(state.scope),params:params,decisionPreferenceOwner:owner,requestId:""}
    if action="decision_pref_get" then state["readPending"]=pending else state["writePending"]=pending
    out.effects.Push({kind:"request",action:action,purpose:action,scope:DpoFlat(state.scope),params:params,
        decisionPreferenceOwner:DpoFlat(owner),cleanup:false})
end sub
sub DpoSync(out as Object)
    state=out.state
    if state.readPending<>invalid or state.writePending<>invalid then return
    if not state.loaded or state.error
        state.status="Loading decision settings…"
        DpoRequest(out,"decision_pref_get")
    else if not DpoRecordsEqual(state.desired,state.confirmed,state.scope)
        state.status="Saving decision settings…"
        DpoRequest(out,"decision_pref_set")
    else
        state.dirty={}
        state.status=""
    end if
end sub
function DpoEffective(state as Dynamic,currentScope as Dynamic) as Dynamic
    if type(state)<>"roAssociativeArray" then return invalid
    if not DpoSame(state.scope,currentScope) then return invalid
    if not DpBool(state.loaded) or not DpBool(state.error) then return invalid
    if not state.loaded or state.error or state.readPending<>invalid or state.writePending<>invalid or state.editor<>invalid then return invalid
    if state.dirty.Count()<>0 or not DpoRecordsEqual(state.desired,state.confirmed,state.scope) then return invalid
    return DecisionPreferenceNormalize(state.confirmed,state.scope)
end function
function DpoReduce(previous as Object,event as Dynamic) as Object
    state=DpoCopy(previous):out={state:state,effects:[],accepted:false}
    kind=DpField(event,"kind","")
    if kind="viewer"
        active=DpoScope(DpField(event,"scope"))
        if DpoSame(state.scope,active) or (state.scope=invalid and active=invalid) then return out
        if DpoSame(state.scope,active,true)
            state.scope=active:state.loaded=false:state.error=false:state.status=""
            state["readPending"]=invalid:state["writePending"]=invalid:state.editor=invalid
        else
            state=DpoCreate(active):state.sequence=previous.sequence
            state.revision=previous.revision:out.state=state
        end if
        if state.revision<2147483646 then state.revision++
        out.accepted=true
        return out
    end if
    if state.scope=invalid then return out
    if kind="load"
        if state.readPending<>invalid or state.writePending<>invalid then return out
        if state.loaded and not state.error and state.dirty.Count()=0 then return out
        DpoSync(out):out.accepted=true
    else if kind="change"
        field=DpField(event,"field"):value=DpField(event,"value")
        if field="gatewayOrigin"
            value=DecisionGatewayOrigin(value)
            if value=invalid
                state.error=true:state.status="Enter an HTTPS gateway origin with no path."
                out.accepted=true:return out
            end if
        else
            if field<>"personalized" and field<>"cloudDecisions" and field<>"stillWatchingCheck" then return out
            if not DpBool(value) then return out
        end if
        if state.revision>=2147483646 then return out
        state.desired[field]=value:state.dirty[field]=true:state.revision++:state.editor=invalid
        DpoSync(out):out.accepted=true
    else if kind="gateway"
        if state.sequence>=2147483646 then return out
        state.sequence++
        owner={operationId:"decision-origin-"+state.sequence.ToStr(),revision:state.revision}
        state.editor={scope:DpoFlat(state.scope),decisionPreferenceOwner:owner}
        out.effects.Push({kind:"keyboard",purpose:"decision_gateway",title:"Decision gateway HTTPS address",
            value:state.desired.gatewayOrigin,submitLabel:"Save",scope:DpoFlat(state.scope),decisionPreferenceOwner:DpoFlat(owner)})
        out.accepted=true
    else if kind="origin_result" or kind="origin_cancel"
        editor=state.editor
        if editor=invalid or not DpoSame(editor.scope,DpField(event,"scope")) then return out
        owner=DpField(event,"decisionPreferenceOwner")
        if not DpoOwner(owner,true) then return out
        if not DpoOwnersEqual(owner,editor.decisionPreferenceOwner,true) or DpField(owner,"revision")<>state.revision then return out
        if not DpoSame(state.scope,editor.scope) then return out
        state.editor=invalid
        if kind="origin_cancel"
            out.accepted=true:return out
        end if
        return DpoReduce(state,{kind:"change",field:"gatewayOrigin",value:DpField(event,"value")})
    else if kind="bound" or kind="result"
        job=DpField(event,"job"):action=DpField(job,"action")
        pending=invalid
        if action="decision_pref_get" then pending=state.readPending
        if action="decision_pref_set" then pending=state.writePending
        if not DpoJobMatches(pending,job) then return out
        if not DpoSame(state.scope,pending.scope) then return out
        if kind="bound"
            if pending.requestId<>"" then return out
            pending["requestId"]=DpField(job,"requestId"):out.accepted=true:return out
        end if
        if pending.requestId="" or pending.requestId<>DpField(job,"requestId") then return out
        receipt=DpField(event,"result")
        if type(receipt)<>"roAssociativeArray" then return out
        if not DpoSame(pending.scope,receipt) then return out
        if DpField(receipt,"requestId")<>pending.requestId or DpField(receipt,"action")<>pending.action then return out
        ok=DpField(receipt,"ok")
        if not DpBool(ok) then return out
        if DpoHasField(receipt,"params")
            if not DpoParamsEqual(pending.action,pending.params,DpField(receipt,"params"),pending.scope) then return out
        end if
        if DpoHasField(receipt,"decisionPreferenceOwner")
            if not DpoOwnersEqual(pending.decisionPreferenceOwner,DpField(receipt,"decisionPreferenceOwner")) then return out
        end if
        record=invalid
        if ok
            record=DecisionPreferenceNormalize(DpField(DpField(receipt,"data"),"preference"),state.scope)
            if record=invalid then return out
            if action="decision_pref_set"
                if not DpoRecordsEqual(record,pending.params.preference,state.scope) then return out
            end if
        end if
        if action="decision_pref_get" then state["readPending"]=invalid else state["writePending"]=invalid
        out.accepted=true
        if not ok
            state.error=true:state.status="Could not load decision settings. Choose Retry decision settings."
            if action="decision_pref_set" then state.status="Could not save decision settings. Choose Retry decision settings."
            return out
        end if
        state.confirmed=record:state.loaded=true:state.error=false
        if action="decision_pref_get"
            merged=DpoFlat(record)
            for each field in state.dirty
                merged[field]=state.desired[field]
            end for
            state.desired=merged
        end if
        DpoSync(out)
    else if kind="rejected"
        effect=DpField(event,"effect"):action=DpField(effect,"action")
        pending=invalid
        if action="decision_pref_get" then pending=state.readPending
        if action="decision_pref_set" then pending=state.writePending
        if not DpoEffectMatches(pending,effect) then return out
        if pending.requestId<>"" or not DpoSame(state.scope,pending.scope) then return out
        if action="decision_pref_get" then state["readPending"]=invalid else state["writePending"]=invalid
        state.error=true:state.status="Decision settings could not be queued. Choose Retry decision settings."
        out.accepted=true
    end if
    return out
end function
function DpoSettings(state as Object) as Object
    if state.scope=invalid then return []
    rows=[]
    for each field in [{key:"personalized",label:"Personalization"},{key:"cloudDecisions",label:"Cloud decisions"},{key:"stillWatchingCheck",label:"Still watching check"}]
        label=field.label+": Off"
        if state.desired[field.key] then label=field.label+": On"
        if state.writePending<>invalid or not state.loaded then label+=" (pending)"
        rows.Push({uiAction:"decision_"+field.key,title:label})
    end for
    label="Decision gateway: Not set"
    if state.desired.gatewayOrigin<>"" then label="Decision gateway: Configured"
    rows.Push({uiAction:"decision_gateway",title:label})
    if state.error then rows.Push({uiAction:"decision_retry",title:"Retry decision settings"})
    return rows
end function
