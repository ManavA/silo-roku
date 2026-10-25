' Small request admission policy. Native Task references live in the coordinator.
function RqCreate(scope as Object) as Object
    return {scope:scope,sequence:0,queued:[],active:[]}
end function

function RqValue(value as Dynamic, key as String, fallback as Dynamic) as Dynamic
    if type(value) <> "roAssociativeArray" then return fallback
    if not value.DoesExist(key) or value[key] = invalid then return fallback
    return value[key]
end function

function RqMatches(scope as Object, job as Object) as Boolean
    for each field in ["provider","sourceId","profileId","generation"]
        if RqValue(scope,field,invalid) <> RqValue(job,field,invalid) then return false
    end for
    return true
end function

function RqExclusive(action as String) as Boolean
    for each name in ["session_status","pin_start","pin_poll","user","resources","select_server","set_server","device_start","device_poll","select_profile","profile_verify","sign_out","track_pref_set","decision_pref_set"]
        if action = name then return true
    end for
    return false
end function

function RqCopy(state as Object) as Object
    output = {scope:state.scope,sequence:state.sequence,queued:[],active:[]}
    for each request in state.queued
        output.queued.Push(request)
    end for
    for each request in state.active
        output.active.Push(request)
    end for
    return output
end function

function RqOffer(state as Object, raw as Dynamic) as Object
    output = RqCopy(state)
    job = RqValue(raw,"job",invalid)
    if type(job) <> "roAssociativeArray" then return {state:output,accepted:false,request:invalid}
    action = RqValue(job,"action","")
    provider = RqValue(job,"provider","")
    if type(action) <> "String" and type(action) <> "roString" then return {state:output,accepted:false,request:invalid}
    if action = "" or (provider <> "plex" and provider <> "silo") then return {state:output,accepted:false,request:invalid}
    cleanup = RqValue(raw,"cleanup",false) = true
    evicted = invalid
    if not cleanup and not RqMatches(output.scope,job) then return {state:output,accepted:false,request:invalid}
    params = RqValue(job,"params",{})
    if type(params) <> "roAssociativeArray" then return {state:output,accepted:false,request:invalid}
    for each group in [output.queued,output.active]
        for each existing in group
            if not cleanup and existing.job.action = action and RqMatches(existing.job,job) and RqValue(existing.job,"previewId","") = RqValue(job,"previewId","") and FormatJson(existing.job.params) = FormatJson(params)
                return {state:output,accepted:false,request:invalid,reason:"duplicate"}
            end if
        end for
    end for
    if output.queued.Count() >= 24
        if not cleanup then return {state:output,accepted:false,request:invalid,reason:"queue_full"}
        removeAt = -1
        for index = output.queued.Count() - 1 to 0 step -1
            if not output.queued[index].cleanup
                removeAt = index
                exit for
            end if
        end for
        if removeAt < 0 then return {state:output,accepted:false,request:invalid,reason:"queue_full"}
        evicted = output.queued[removeAt]
        output.queued.Delete(removeAt)
    end if
    output.sequence++
    envelope = {}
    for each key in job
        envelope[key] = job[key]
    end for
    envelope.params = params
    envelope["requestId"] = "app-" + output.sequence.ToStr()
    priority = 2
    purpose = RqValue(raw,"purpose",action)
    if purpose = "preview_detail" or purpose = "preview_plan" or purpose = "plex_inventory_probe" then priority = 3
    if purpose = "public_artwork" then priority = 4
    if purpose = "decision_pref_get" then priority = 4
    if purpose = "still_watching" then priority = 5
    if purpose = "playback" or action = "playback_replan" or RqExclusive(action) then priority = 1
    if action = "playback_stop" or action = "playback_progress" then priority = 0
    lane = ""
    if action = "playback_stop" or action = "playback_progress" or action = "playback_replan"
        lane = provider + ":" + RqValue(job,"sourceId","") + ":" + RqValue(params,"sessionId","")
    end if
    request = {job:envelope,purpose:purpose,cleanup:cleanup,priority:priority,lane:lane,exclusive:RqExclusive(action)}
    output.queued.Push(request)
    return {state:output,accepted:true,request:request,evicted:evicted}
end function

' Only work that has not entered a Task can be forgotten without a completion.
function RqCancelQueued(state as Object, requestId as String) as Object
    output = RqCopy(state)
    output.queued = []
    removed = invalid
    for each request in state.queued
        if request.job.requestId = requestId
            removed = request
        else
            output.queued.Push(request)
        end if
    end for
    return {state:output,request:removed}
end function

function RqRebind(state as Object, scope as Object) as Object
    output = RqCopy(state)
    output.scope = scope
    output.queued = []
    for each request in state.queued
        if request.cleanup or RqMatches(scope,request.job) or RqRetainPreferenceWrite(scope,request) then output.queued.Push(request)
    end for
    return output
end function

function RqTake(state as Object) as Object
    output = RqCopy(state)
    if output.active.Count() >= 2 then return {state:output,next:invalid}
    for each running in output.active
        if running.exclusive then return {state:output,next:invalid}
    end for
    bestIndex = -1
    bestPriority = 999
    for index = 0 to output.queued.Count() - 1
        request = output.queued[index]
        allowed = true
        if request.exclusive and output.active.Count() > 0 then allowed = false
        if request.lane <> ""
            for each running in output.active
                if running.lane = request.lane then allowed = false
            end for
            for previous = 0 to index - 1
                if output.queued[previous].lane = request.lane then allowed = false
            end for
        end if
        if allowed and request.priority < bestPriority
            bestIndex = index
            bestPriority = request.priority
        end if
        ' A pending session mutation is a barrier to later catalog admission.
        if request.exclusive and bestIndex < 0 then exit for
    end for
    if bestIndex < 0 then return {state:output,next:invalid}
    request = output.queued[bestIndex]
    output.queued.Delete(bestIndex)
    output.active.Push(request)
    return {state:output,next:request}
end function

function RqComplete(state as Object, requestId as String) as Object
    output = RqCopy(state)
    output.active = []
    for each request in state.active
        if request.job.requestId <> requestId then output.active.Push(request)
    end for
    return output
end function

' Already-admitted compact settings writes survive only this viewer's route change.
' This grants no Offer admission, cleanup eviction or other mutation authority.
function RqRetainPreferenceWrite(scope as Dynamic,request as Dynamic) as Boolean
    if type(scope)<>"roAssociativeArray" or type(request)<>"roAssociativeArray" then return false
    if RqValue(request,"purpose","")="decision_pref_set" then return RqRetainDecisionPreferenceWrite(scope,request)
    if RqValue(request,"purpose","")<>"track_pref_set" then return false
    job=RqValue(request,"job",invalid)
    if type(job)<>"roAssociativeArray" or RqValue(job,"action","")<>"track_pref_set" then return false
    for each field in ["provider","sourceId","profileId"]
        value=RqValue(scope,field,invalid)
        if type(value)<>"String" and type(value)<>"roString" then return false
        if value<>RqValue(job,field,invalid) then return false
    end for
    if scope.provider<>"plex" and scope.provider<>"silo" then return false
    if Len(scope.sourceId)<=5 or Left(scope.sourceId,5)<>scope.provider+":" then return false
    params=RqValue(job,"params",invalid)
    if type(params)<>"roAssociativeArray" then return false
    if params.Count()<>1 then return false
    record=RqValue(params,"preference",invalid)
    if type(record)<>"roAssociativeArray" then return false
    if record.Count()<>8 then return false
    allowed={schemaversion:true,sourceid:true,profileid:true,subtitlemode:true,subtitlelanguage:true,subtitlename:true,audiolanguage:true,audioname:true}
    for each key in record
        if not allowed.DoesExist(LCase(key)) then return false
    end for
    schema=RqValue(record,"schemaVersion",invalid)
    kind=type(schema)
    if kind<>"Integer" and kind<>"roInt" and kind<>"roInteger" and kind<>"LongInteger" and kind<>"roLongInteger" then return false
    if schema<>1 or RqValue(record,"sourceId",invalid)<>scope.sourceId or RqValue(record,"profileId",invalid)<>scope.profileId then return false
    for each key in ["subtitleMode","subtitleLanguage","subtitleName","audioLanguage","audioName"]
        value=RqValue(record,key,invalid)
        if type(value)<>"String" and type(value)<>"roString" then return false
        if Len(value)>96 then return false
    end for
    return record.subtitleMode="auto" or record.subtitleMode="on" or record.subtitleMode="off"
end function

function RqPreferenceWhole(value as Dynamic) as Boolean
    kind=type(value)
    if kind<>"Integer" and kind<>"roInt" and kind<>"roInteger" and kind<>"LongInteger" and kind<>"roLongInteger" and kind<>"Float" and kind<>"roFloat" and kind<>"Double" and kind<>"roDouble" then return false
    if value<>value or value<0 or value>2147483646 then return false
    return value=Int(value)
end function

function RqRetainDecisionPreferenceWrite(scope as Object,request as Object) as Boolean
    job=RqValue(request,"job",invalid)
    if type(job)<>"roAssociativeArray" or RqValue(job,"action","")<>"decision_pref_set" then return false
    for each field in ["provider","sourceId","profileId"]
        value=RqValue(scope,field,invalid)
        if type(value)<>"String" and type(value)<>"roString" then return false
        if value<>RqValue(job,field,invalid) then return false
    end for
    if scope.provider<>"plex" and scope.provider<>"silo" then return false
    if Len(scope.sourceId)<=5 or Left(scope.sourceId,5)<>scope.provider+":" then return false
    owner=RqValue(job,"decisionPreferenceOwner",invalid)
    if type(owner)<>"roAssociativeArray" then return false
    if owner.Count()<>2 or not RqPreferenceWhole(RqValue(owner,"revision",invalid)) then return false
    operation=RqValue(owner,"operationId",invalid)
    if type(operation)<>"String" and type(operation)<>"roString" then return false
    if Len(operation)=0 or Len(operation)>96 or Instr(1,operation,"://")>0 then return false
    params=RqValue(job,"params",invalid)
    if type(params)<>"roAssociativeArray" then return false
    if params.Count()<>1 then return false
    record=RqValue(params,"preference",invalid)
    if type(record)<>"roAssociativeArray" then return false
    if record.Count()<>7 then return false
    allowed={schemaversion:true,sourceid:true,profileid:true,personalized:true,clouddecisions:true,stillwatchingcheck:true,gatewayorigin:true}
    seen={}
    for each key in record
        folded=LCase(key)
        if not allowed.DoesExist(folded) or seen.DoesExist(folded) then return false
        seen[folded]=true
    end for
    if not RqPreferenceWhole(RqValue(record,"schemaVersion",invalid)) then return false
    if record.schemaVersion<>1 or RqValue(record,"sourceId",invalid)<>scope.sourceId or RqValue(record,"profileId",invalid)<>scope.profileId then return false
    for each field in ["personalized","cloudDecisions","stillWatchingCheck"]
        value=RqValue(record,field,invalid)
        if type(value)<>"Boolean" and type(value)<>"roBoolean" then return false
    end for
    origin=RqValue(record,"gatewayOrigin",invalid)
    if type(origin)<>"String" and type(origin)<>"roString" then return false
    if Len(origin)>256 or (origin<>"" and Left(origin,8)<>"https://") then return false
    for each value in [operation,origin]
        for index=1 to Len(value)
            code=Asc(Mid(value,index,1))
            if code<32 or code=127 then return false
        end for
    end for
    return true
end function
