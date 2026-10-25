' One stream owns the native media player until its asynchronous stop completes.
' Requests stay private; only VideoOwnerStatus may cross the public status field.
function VideoOwnerInitial() as Object
    return {phase:"idle",active:invalid,queued:invalid,clipId:-1,retiredClipId:-1,nativeState:"none",lastAttemptId:"",lastMode:"",errorCode:0}
end function

function VoField(value as Dynamic, key as String, fallback as Dynamic) as Dynamic
    if type(value) <> "roAssociativeArray" then return fallback
    if not value.DoesExist(key) then return fallback
    return value[key]
end function

function VoIsNumber(value as Dynamic) as Boolean
    kind = type(value)
    ' Native AA integer fields report roInteger, while Box(integer) reports roInt.
    if kind <> "Integer" and kind <> "roInt" and kind <> "roInteger" and kind <> "LongInteger" and kind <> "roLongInteger" and kind <> "Float" and kind <> "roFloat" and kind <> "Double" and kind <> "roDouble" then return false
    return value = value and Abs(value) <= 1000000000000.0
end function

function VoNumber(value as Dynamic, fallback as Double) as Double
    if VoIsNumber(value) then return value
    return fallback
end function

function VoIdentifier(value as Dynamic) as Boolean
    if type(value) <> "String" and type(value) <> "roString" then return false
    if Len(value) = 0 or Len(value) > 128 then return false
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
    for index = 1 to Len(value)
        if Instr(1,allowed,Mid(value,index,1)) = 0 then return false
    end for
    return true
end function

function VoString(value as Dynamic) as Boolean
    return type(value) = "String" or type(value) = "roString"
end function

function VoTrue(value as Dynamic) as Boolean
    if type(value) <> "Boolean" and type(value) <> "roBoolean" then return false
    return value
end function

function VoHeadersValid(headers as Dynamic) as Boolean
    if type(headers) <> "roAssociativeArray" then return false
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!#$%&'*+-.^_`|~"
    for each name in headers
        if Len(name) = 0 or Len(name) > 128 then return false
        for index = 1 to Len(name)
            if Instr(1,allowed,Mid(name,index,1)) = 0 then return false
        end for
        value = headers[name]
        if not VoString(value) then return false
        if Len(value) > 8192 or Instr(1,value,Chr(13)) > 0 or Instr(1,value,Chr(10)) > 0 then return false
    end for
    return true
end function

function VoBounds(bounds as Dynamic) as Dynamic
    if bounds = invalid then return {x:0,y:0,width:1280,height:720}
    if type(bounds) <> "roAssociativeArray" then return invalid
    for each key in ["x","y","width","height"]
        if not VoIsNumber(VoField(bounds,key,invalid)) then return invalid
        if bounds[key] < 0 or bounds[key] > 8192 then return invalid
    end for
    if bounds.width = 0 or bounds.height = 0 then return invalid
    return {x:bounds.x,y:bounds.y,width:bounds.width,height:bounds.height}
end function

function VideoOwnerRequest(value as Dynamic) as Dynamic
    if type(value) <> "roAssociativeArray" then return invalid
    if not VoIdentifier(VoField(value,"attemptId",invalid)) then return invalid
    mode = VoField(value,"mode","")
    if not VoString(mode) then return invalid
    if mode <> "playback" and mode <> "preview" and mode <> "prebuffer" then return invalid
    plan = VoField(value,"plan",invalid)
    if type(plan) <> "roAssociativeArray" then return invalid
    url = VoField(plan,"url",invalid)
    if not VoString(url) then return invalid
    if Len(url) > 16384 or Instr(1,url,Chr(13)) > 0 or Instr(1,url,Chr(10)) > 0 then return invalid
    if Left(LCase(url),7) <> "http://" and Left(LCase(url),8) <> "https://" then return invalid
    format = VoField(plan,"streamFormat",invalid)
    if not VoString(format) then return invalid
    if Len(format) = 0 or Len(format) > 32 then return invalid
    if not VoHeadersValid(VoField(plan,"headers",{})) then return invalid
    for each key in ["startPositionMs","timelineOffsetMs"]
        if plan.DoesExist(key)
            if not VoIsNumber(plan[key]) then return invalid
            if plan[key] < 0 then return invalid
        end if
    end for
    for each key in ["relativeTimeline","canSeekAnywhere"]
        if plan.DoesExist(key)
            if type(plan[key]) <> "Boolean" and type(plan[key]) <> "roBoolean" then return invalid
        end if
    end for
    if plan.DoesExist("subtitleTracks")
        if type(plan.subtitleTracks) <> "roArray" then return invalid
        for each track in plan.subtitleTracks
            if type(track) <> "roAssociativeArray" then return invalid
        end for
    end if
    bounds = VoBounds(VoField(value,"bounds",invalid))
    if bounds = invalid then return invalid
    request = {attemptId:value.attemptId,mode:mode,plan:plan,bounds:bounds}
    if value.DoesExist("trackScope")
        scope=value.trackScope
        if type(scope)<>"roAssociativeArray" then return invalid
        for each field in ["provider","sourceId","profileId"]
            if not VoString(VoField(scope,field,invalid)) then return invalid
        end for
        generation=VoField(scope,"generation",invalid)
        if not VoIsNumber(generation) then return invalid
        if generation<0 or generation>2147483646 or generation<>Int(generation) then return invalid
        if scope.provider<>"plex" and scope.provider<>"silo" then return invalid
        if Len(scope.sourceId)>512 or Len(scope.profileId)>256 or Left(scope.sourceId,5)<>scope.provider+":" then return invalid
        if scope.provider<>VoField(plan,"provider","") or scope.sourceId<>VoField(plan,"sourceId","") then return invalid
        request["trackScope"]={provider:scope.provider,sourceId:scope.sourceId,profileId:scope.profileId,generation:generation}
    end if
    if value.DoesExist("previewPositionMs")
        targetMs = value.previewPositionMs
        if not VoIsNumber(targetMs) then return invalid
        if targetMs < 0 then return invalid
        request["previewPositionMs"] = targetMs
        if mode <> "playback"
            ' The editorial target is absolute; only an explicitly relative
            ' provider timeline contributes an offset, matching UiPlanPositionMs.
            nativeMs = targetMs
            if VoTrue(VoField(plan,"relativeTimeline",false)) then nativeMs = nativeMs - VoNumber(VoField(plan,"timelineOffsetMs",0),0)
            if nativeMs < 0 then return invalid
            ' An unseekable route may be reused only at its exact provider start.
            ' Reject mismatches so the lease owner can abandon it and keep a poster.
            if not VoTrue(VoField(plan,"canSeekAnywhere",true))
                if nativeMs <> VoNumber(VoField(plan,"startPositionMs",0),0) then return invalid
            end if
            ' Never replace saved Resume in the provider plan used for cleanup.
            nativePlan = VoCopy(plan)
            nativePlan["startPositionMs"] = nativeMs
            request.plan = nativePlan
        end if
    end if
    return request
end function

function VoCopy(owner as Dynamic) as Object
    if type(owner) <> "roAssociativeArray" then return VideoOwnerInitial()
    result = {}
    for each key in owner
        result[key] = owner[key]
    end for
    return result
end function

sub VoStart(owner as Object, request as Object)
    owner.active = request
    owner.queued = invalid
    owner.phase = "starting"
    owner["clipId"] = -1
    owner["nativeState"] = "starting"
    owner["lastAttemptId"] = request.attemptId
    owner["lastMode"] = request.mode
    owner["errorCode"] = 0
end sub

function VideoOwnerTransition(previous as Dynamic, event as Dynamic) as Object
    owner = VoCopy(previous)
    effects = []
    result = {owner:owner,effects:effects,accepted:false}
    kind = VoField(event,"kind","")
    if not VoString(kind) then return result
    if kind = "request"
        request = VideoOwnerRequest(VoField(event,"request",invalid))
        if request = invalid then return result
        result.accepted = true
        if owner.active = invalid
            VoStart(owner,request)
            effects.Push({action:"start",request:request})
        else if owner.active.attemptId <> request.attemptId
            owner.queued = request
            if owner.phase <> "stopping"
                owner.phase = "stopping"
                owner["nativeState"] = "stopping"
                effects.Push({action:"stop"})
            end if
        end if
        return result
    end if
    if kind = "command"
        command = VoField(event,"command",invalid)
        action = VoField(command,"action","")
        attempt = VoField(command,"attemptId","")
        if not VoString(action) or not VoString(attempt) then return result
        ' A queued request owns no native stream yet. Cancel its intent without
        ' changing the active owner's in-flight asynchronous teardown.
        if action = "stop" and attempt <> "" and owner.queued <> invalid
            if attempt = owner.queued.attemptId
                result.accepted = true
                effects.Push({action:"cancelled",attemptId:owner.queued.attemptId,mode:owner.queued.mode})
                owner.queued = invalid
                return result
            end if
        end if
        if attempt <> ""
            if owner.active = invalid then return result
            if attempt <> owner.active.attemptId then return result
        end if
        if action = "stop"
            result.accepted = true
            if owner.queued <> invalid then effects.Push({action:"cancelled",attemptId:owner.queued.attemptId,mode:owner.queued.mode})
            owner.queued = invalid
            if owner.active <> invalid and owner.phase <> "stopping"
                owner.phase = "stopping"
                owner["nativeState"] = "stopping"
                effects.Push({action:"stop"})
            end if
            return result
        end if
        if owner.active = invalid or owner.phase = "stopping" then return result
        if attempt <> owner.active.attemptId then return result
        if action = "promote"
            bounds = VoBounds(VoField(command,"bounds",invalid))
            if bounds = invalid then return result
            result.accepted = true
            if owner.active.mode <> "playback"
                active = VoCopy(owner.active)
                active.mode = "playback"
                active.bounds = bounds
                owner.active = active
                owner["lastMode"] = "playback"
                if owner.nativeState <> "playing" then owner.phase = "starting"
                effects.Push({action:"promote",request:active})
            end if
        else if action = "seek"
            if not VoTrue(VoField(owner.active.plan,"canSeekAnywhere",true)) then return result
            position = VoField(command,"positionMs",invalid)
            if not VoIsNumber(position) then return result
            if position < 0 then return result
            result.accepted = true
            effects.Push({action:"seek",position:position / 1000})
        else if action = "pause" or action = "resume"
            if owner.active.mode <> "playback" then return result
            result.accepted = true
            effects.Push({action:action})
        end if
        return result
    end if
    if owner.active = invalid then return result
    attempt = VoField(event,"attemptId","")
    if not VoString(attempt) then return result
    if attempt <> owner.active.attemptId then return result
    if kind = "deadline" or kind = "cap"
        if kind = "cap" and owner.active.mode = "playback" then return result
        result.accepted = true
        if owner.phase = "stopping" then return result
        if kind = "deadline" and owner.phase <> "starting" then return result
        owner.phase = "stopping"
        owner["nativeState"] = "stopping"
        if kind = "deadline" then owner["errorCode"] = -1001
        effects.Push({action:"stop"})
        return result
    end if
    if kind <> "native" then return result
    state = VoField(event,"state","")
    if not VoString(state) then return result
    clip = VoNumber(VoField(event,"clipId",invalid),-1)
    if state = "stopped" and owner.phase = "stopping"
        result.accepted = true
        owner["retiredClipId"] = clip
        if owner.clipId >= 0 then owner["retiredClipId"] = owner.clipId
        owner.active = invalid
        owner.phase = "idle"
        owner["nativeState"] = "stopped"
        owner["clipId"] = -1
        effects.Push({action:"cleanup"})
        queued = owner.queued
        owner.queued = invalid
        if queued <> invalid
            VoStart(owner,queued)
            effects.Push({action:"start",request:queued})
        end if
        return result
    end if
    if owner.phase = "stopping" then return result
    if state <> "buffering" and state <> "playing" and state <> "paused" and state <> "finished" and state <> "error" and state <> "stopped" then return result
    if clip < 0 or clip = owner.retiredClipId then return result
    if owner.clipId >= 0 and clip <> owner.clipId then return result
    result.accepted = true
    owner["clipId"] = clip
    owner["nativeState"] = state
    if state = "playing" or state = "paused" then owner.phase = "active"
    if owner.active.mode = "prebuffer" and VoTrue(VoField(event,"prebufferDone",false)) then owner.phase = "active"
    if state = "stopped"
        owner["retiredClipId"] = clip
        owner.active = invalid
        owner.phase = "idle"
        owner["clipId"] = -1
        effects.Push({action:"cleanup"})
    end if
    return result
end function

function VoStartupMilliseconds(seconds as Dynamic) as Integer
    if not VoIsNumber(seconds) then return -1
    ' Startup has shorter native watchdogs. Reject implausible diagnostics rather
    ' than saturating them into apparently measured values; this is a UI bound.
    if seconds < 0 or seconds > 120 then return -1
    return Int(seconds * 1000 + 0.5)
end function

function VideoOwnerStatus(owner as Object, snapshot as Dynamic) as Object
    result = {attemptId:owner.lastAttemptId,mode:owner.lastMode,state:owner.nativeState,
        clipId:owner.clipId,position:-1,duration:-1,renderedPosition:-1,renderedClipId:-1,renderedEpoch:-1,
        prebufferDone:false,actualStart:-1,errorCode:owner.errorCode,
        startupNativeMs:-1,startupTotalMs:-1,startupManifestMs:-1,startupPrebufferMs:-1,
        startupDrmLoadMs:-1,startupDrmLicenseMs:-1}
    if owner.active = invalid or owner.clipId < 0 then return result
    if VoNumber(VoField(snapshot,"clipId",invalid),-1) <> owner.clipId then return result
    result.position = VoNumber(VoField(snapshot,"position",invalid),-1)
    result.duration = VoNumber(VoField(snapshot,"duration",invalid),-1)
    result["errorCode"] = VoNumber(VoField(snapshot,"errorCode",invalid),0)
    if owner.errorCode <> 0 then result["errorCode"] = owner.errorCode
    info = VoField(snapshot,"positionInfo",invalid)
    renderedClip = VoNumber(VoField(info,"clip_id",invalid),-1)
    epoch = VoNumber(VoField(info,"epoch",invalid),-1)
    if renderedClip = owner.clipId and (epoch = 0 or epoch = 1)
        result["renderedPosition"] = VoNumber(VoField(info,"video",invalid),-1)
        result["renderedClipId"] = renderedClip
        result["renderedEpoch"] = epoch
    end if
    buffering = VoField(snapshot,"bufferingStatus",invalid)
    if VoTrue(VoField(buffering,"prebufferDone",false))
        result["prebufferDone"] = true
        result["actualStart"] = VoNumber(VoField(buffering,"actualStart",invalid),-1)
    end if
    if owner.nativeState = "playing"
        ' Roku reports duration measurements in seconds. Only documented *_dur
        ' numbers are projected; never expose native arrays, URLs or *_start units.
        seconds = VoField(snapshot,"timeToStartStreaming",invalid)
        if VoIsNumber(seconds)
            if seconds >= 0.001 then result["startupNativeMs"] = VoStartupMilliseconds(seconds)
        end if
        timings = VoField(snapshot,"playStartInfo",invalid)
        for each timing in [{source:"total_dur",target:"startupTotalMs"},
            {source:"manifest_dur",target:"startupManifestMs"},
            {source:"prebuf_dur",target:"startupPrebufferMs"},
            {source:"drm_load_dur",target:"startupDrmLoadMs"},
            {source:"drm_lic_acq_dur",target:"startupDrmLicenseMs"}]
            result[timing.target] = VoStartupMilliseconds(VoField(timings,timing.source,invalid))
        end for
    end if
    return result
end function
