' A committed session authorizes progress only after its requested resume lands.
function ApCreate(plan as Object, scope as Object, item as Object, attemptId as String) as Object
    captured = {}
    for each key in ["provider","sourceId","profileId","generation"]
        captured[key] = scope[key]
    end for
    captured["sessionId"] = UiField(plan,"sessionId","")
    return {plan:plan,scope:captured,item:item,attemptId:attemptId,closed:false,started:false,
        landed:UiNumber(UiField(plan,"startPositionMs",0),0) <= 0,firstRendered:invalid,status:invalid}
end function

function ApSample(session as Object, status as Dynamic, playingMs as Double) as Object
    if session.closed or type(status) <> "roAssociativeArray" then return session
    if UiField(status,"attemptId","") <> session.attemptId or UiField(status,"mode","") <> "playback" then return session
    state = UiField(status,"state","")
    if state <> "playing" and state <> "paused" and state <> "finished" and state <> "error" then return session
    if state = "playing" then session.started = true
    rendered = UiNumber(UiField(status,"renderedPosition",invalid),-1)
    clipId = UiNumber(UiField(status,"clipId",invalid),-1)
    info = {video:rendered,clip_id:UiField(status,"renderedClipId",invalid),epoch:UiField(status,"renderedEpoch",invalid)}
    if session.firstRendered = invalid and rendered >= 0 and clipId >= 0 and info.clip_id = clipId and info.epoch = 0 then session["firstRendered"] = rendered
    if session.started then session.landed = UiResumeLanded(session.plan,info,playingMs,session.landed,session.firstRendered,clipId)
    if UiNumber(UiField(status,"position",invalid),-1) >= 0 then session.status = status
    return session
end function

function ApProgress(session as Object) as Dynamic
    if session.closed or not session.started or not session.landed or session.status = invalid then return invalid
    position = UiNumber(UiField(session.status,"position",invalid),-1)
    if position < 0 then return invalid
    paused = UiField(session.status,"state","") = "paused"
    state = "playing"
    if paused then state = "paused"
    duration = UiNumber(UiField(session.item,"durationMs",0),0)
    if duration <= 0 then duration = UiNumber(UiField(session.status,"duration",0),0) * 1000
    plan = session.plan
    params = {itemId:UiField(plan,"itemId",UiField(session.item,"itemId","")),sessionId:UiField(plan,"sessionId",""),
        transcodeSessionId:UiField(plan,"sessionId",""),positionMs:UiPlanPositionMs(position,plan,true),
        durationMs:duration,state:state,isPaused:paused,sequence:1}
    installation = UiField(plan,"installationId","")
    if installation <> "" then params["installationId"] = installation
    return params
end function

function ApClose(session as Object, stopId as String) as Object
    if session.closed then return {session:session,params:invalid}
    params = ApProgress(session)
    persist = params <> invalid
    if params = invalid
        params = UiRetiredPlaybackParams(session.plan)
        params["durationMs"] = UiNumber(UiField(session.item,"durationMs",0),0)
    end if
    params["persistProgress"] = persist
    params["state"] = "stopped"
    params["stopId"] = stopId
    session.closed = true
    return {session:session,params:params}
end function
