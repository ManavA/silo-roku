' Optional answers carry no playback authority. Both clocks include queue wait.
function SwWhole(value as Dynamic, maximum = 9000000000000# as Double) as Boolean
    kind=type(value)
    if kind<>"Integer" and kind<>"roInt" and kind<>"roInteger" and kind<>"LongInteger" and kind<>"roLongInteger" and kind<>"Float" and kind<>"roFloat" and kind<>"Double" and kind<>"roDouble" then return false
    if value<>value or value<0 or value>maximum then return false
    ' Int is 32-bit. Validate the small remainder without truncating epoch ms.
    remainder=value-Int(value/1000000#)*1000000#
    return remainder=Int(remainder)
end function

function SwPreference(raw as Dynamic,scope as Object) as Dynamic
    if type(raw)<>"roAssociativeArray" then return invalid
    if raw.Count()<>7 or not SwWhole(MpField(raw,"schemaVersion",invalid),1) then return invalid
    if raw.schemaVersion<>1 then return invalid
    if MpField(raw,"sourceId",invalid)<>scope.sourceId or MpField(raw,"profileId",invalid)<>scope.profileId then return invalid
    for each field in ["personalized","cloudDecisions","stillWatchingCheck"]
        if not MpTrue(MpField(raw,field,invalid)) then return invalid
    end for
    origin=MpField(raw,"gatewayOrigin",invalid)
    if not MpString(origin) then return invalid
    if Len(origin)>512 or Left(origin,8)<>"https://" then return invalid
    return {schemaVersion:1,sourceId:scope.sourceId,profileId:scope.profileId,
        personalized:true,cloudDecisions:true,stillWatchingCheck:true,gatewayOrigin:origin}
end function

function SwViewer(raw as Dynamic) as Dynamic
    if type(raw)<>"roAssociativeArray" then return invalid
    if raw.Count()<>4 then return invalid
    daypart=MpField(raw,"daypart",invalid)
    if not MpString(daypart) then return invalid
    if daypart<>"morning" and daypart<>"day" and daypart<>"evening" and daypart<>"late" then return invalid
    weekend=MpField(raw,"weekend",invalid)
    if type(weekend)<>"Boolean" and type(weekend)<>"roBoolean" then return invalid
    if MpField(raw,"device",invalid)<>"tv" then return invalid
    session=MpField(raw,"session",invalid)
    if type(session)<>"roAssociativeArray" then return invalid
    if session.Count()<>2 then return invalid
    if not SwWhole(MpField(session,"minutes",invalid),10080) or not SwWhole(MpField(session,"episodes_in_row",invalid),1000) then return invalid
    return {daypart:daypart,weekend:weekend,device:"tv",session:{minutes:session.minutes,episodes_in_row:session.episodes_in_row}}
end function

function StillWatchingViewer(hour as Dynamic,day as Dynamic,elapsedMs as Dynamic,streak as Dynamic) as Dynamic
    if not SwWhole(hour,23) or not SwWhole(day,6) or not SwWhole(elapsedMs,604800000) or not SwWhole(streak,1000) then return invalid
    daypart="late"
    if hour>=5 and hour<11 then daypart="morning"
    if hour>=11 and hour<17 then daypart="day"
    if hour>=17 and hour<22 then daypart="evening"
    return {daypart:daypart,weekend:day=0 or day=6,device:"tv",
        session:{minutes:Int(elapsedMs/60000),episodes_in_row:streak}}
end function

function SwFalse(value as Dynamic) as Boolean
    if type(value)<>"Boolean" and type(value)<>"roBoolean" then return false
    return not value
end function

function SwEligible(owner as Dynamic) as Boolean
    if type(owner)<>"roAssociativeArray" then return false
    if UnScope(MpField(owner,"scope",invalid))=invalid then return false
    for each field in ["attemptId","versionId","itemId","lookupId"]
        if not MpText(MpField(owner,field,invalid)) then return false
    end for
    if MpField(owner,"phase",invalid)<>"watching" or not MpTrue(MpField(owner,"asked",invalid)) then return false
    if not MpTrue(MpField(owner,"landed",invalid)) or not MpTrue(MpField(owner,"autoplayAllowed",invalid)) then return false
    for each field in ["dismissed","settling","stillWatching"]
        if not SwFalse(MpField(owner,field,invalid)) then return false
    end for
    if not SwWhole(MpField(owner,"autoplayStreak",invalid),1000) then return false
    native=MpField(owner,"nativeState",invalid)
    if native<>"playing" and native<>"paused" then return false
    if not SwWhole(MpField(owner,"clipId",invalid),2147483646) or not SwWhole(MpField(owner,"renderedEpoch",invalid),0) then return false
    if not UnRendered(owner) then return false
    return UpNextProjection(owner).shown
end function

function StillWatchingCapture(owner as Dynamic,preference as Dynamic,epochMs as Dynamic,monoMs as Dynamic,viewer as Dynamic) as Dynamic
    if not SwEligible(owner) then return invalid
    if not SwWhole(epochMs) or not SwWhole(monoMs) then return invalid
    if epochMs>9000000000000#-800 or monoMs>9000000000000#-800 then return invalid
    pref=SwPreference(preference,owner.scope)
    publicViewer=SwViewer(viewer)
    if pref=invalid or publicViewer=invalid then return invalid
    if owner.autoplayStreak<3 or publicViewer.session.episodes_in_row<>owner.autoplayStreak then return invalid
    state={scope:UnScope(owner.scope),preference:pref,viewer:publicViewer,requestId:"",consumed:false,
        requestedAtMs:epochMs,deadlineMs:epochMs+800#,requestedMonoMs:monoMs,deadlineMonoMs:monoMs+800#}
    for each field in ["attemptId","versionId","itemId","lookupId","clipId","renderedEpoch"]
        state[field]=owner[field]
    end for
    return state
end function

function StillWatchingParams(state as Object) as Object
    return {requestedAtMs:state.requestedAtMs,deadlineMs:state.deadlineMs,viewer:state.viewer}
end function

function StillWatchingNativeMatches(state as Dynamic,status as Dynamic) as Boolean
    if type(state)<>"roAssociativeArray" or type(status)<>"roAssociativeArray" then return false
    if MpField(status,"attemptId",invalid)<>state.attemptId or MpField(status,"mode",invalid)<>"playback" then return false
    native=MpField(status,"state",invalid)
    if native<>"playing" and native<>"paused" then return false
    for each field in ["clipId","renderedClipId"]
        value=MpField(status,field,invalid)
        if not SwWhole(value,2147483646) then return false
        if value<>state.clipId then return false
    end for
    if not SwWhole(MpField(status,"renderedEpoch",invalid),0) or not SwWhole(MpField(status,"errorCode",invalid),0) then return false
    seconds=MpField(status,"renderedPosition",invalid)
    if not MpNumber(seconds) then return false
    return seconds>=0 and seconds<=604800
end function

function StillWatchingOwner(state as Object) as Object
    owner={scope:MpCopy(state.scope)}
    for each field in ["attemptId","versionId","itemId","lookupId","clipId","renderedEpoch"]
        owner[field]=state[field]
    end for
    return owner
end function

function SwOwnerMatches(state as Object,current as Dynamic,eligible = true as Boolean) as Boolean
    if type(current)<>"roAssociativeArray" then return false
    if eligible and not SwEligible(current) then return false
    scope=UnScope(MpField(current,"scope",invalid))
    if scope=invalid then return false
    for each field in ["provider","sourceId","profileId","generation"]
        if scope[field]<>state.scope[field] then return false
    end for
    for each field in ["attemptId","versionId","itemId","lookupId","clipId","renderedEpoch"]
        if MpField(current,field,invalid)<>state[field] then return false
    end for
    return true
end function

function SwJobMatches(state as Dynamic,job as Dynamic,bound = true as Boolean) as Boolean
    if type(state)<>"roAssociativeArray" or type(job)<>"roAssociativeArray" then return false
    if MpField(job,"action",invalid)<>"still_watching" or not MpText(MpField(job,"requestId",invalid)) then return false
    if bound and job.requestId<>state.requestId then return false
    for each field in ["provider","sourceId","profileId","generation"]
        if MpField(job,field,invalid)<>state.scope[field] then return false
    end for
    if not SwOwnerMatches(state,MpField(job,"stillWatchingOwner",invalid),false) then return false
    params=MpField(job,"params",invalid)
    if type(params)<>"roAssociativeArray" then return false
    if params.Count()<>3 then return false
    if MpField(params,"requestedAtMs",invalid)<>state.requestedAtMs or MpField(params,"deadlineMs",invalid)<>state.deadlineMs then return false
    viewer=SwViewer(MpField(params,"viewer",invalid))
    if viewer=invalid then return false
    for each field in ["daypart","weekend","device"]
        if viewer[field]<>state.viewer[field] then return false
    end for
    return viewer.session.minutes=state.viewer.session.minutes and viewer.session.episodes_in_row=state.viewer.session.episodes_in_row
end function

function StillWatchingBind(state as Dynamic,job as Dynamic) as Dynamic
    if type(state)<>"roAssociativeArray" then return invalid
    if state.requestId<>"" or state.consumed or not SwJobMatches(state,job,false) then return invalid
    output=MpCopy(state):output["requestId"]=job.requestId
    return output
end function

function StillWatchingCurrent(state as Dynamic,owner as Dynamic,preference as Dynamic,epochMs as Dynamic,monoMs as Dynamic) as Boolean
    if type(state)<>"roAssociativeArray" then return false
    if state.consumed or not SwOwnerMatches(state,owner) then return false
    if not SwWhole(epochMs) or not SwWhole(monoMs) then return false
    if epochMs<state.requestedAtMs or epochMs>=state.deadlineMs or monoMs<state.requestedMonoMs or monoMs>=state.deadlineMonoMs then return false
    pref=SwPreference(preference,state.scope)
    if pref=invalid then return false
    for each field in ["schemaVersion","sourceId","profileId","personalized","cloudDecisions","stillWatchingCheck","gatewayOrigin"]
        if pref[field]<>state.preference[field] then return false
    end for
    return true
end function

function StillWatchingResult(state as Dynamic,owner as Dynamic,preference as Dynamic,job as Dynamic,result as Dynamic,epochMs as Dynamic,monoMs as Dynamic) as Object
    out={state:state,probability:invalid}
    if not SwJobMatches(state,job) then return out
    current=StillWatchingCurrent(state,owner,preference,epochMs,monoMs)
    out.state=MpCopy(state):out.state.consumed=true
    if not current or type(result)<>"roAssociativeArray" then return out
    for each field in ["provider","sourceId","profileId","generation","requestId","action"]
        if MpField(result,field,invalid)<>job[field] then return out
    end for
    if not MpTrue(MpField(result,"ok",invalid)) then return out
    data=MpField(result,"data",invalid)
    if type(data)<>"roAssociativeArray" then return out
    if data.Count()<>1 then return out
    probability=MpField(data,"probability",invalid)
    if not MpNumber(probability) then return out
    if probability<0 or probability>1 then return out
    out.probability=probability
    return out
end function
