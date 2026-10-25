' Runtime track identifiers remain private. Only NativeTrackStatus is a public DTO.
function NativeTrackCreate() as Object
    return {attemptId:"",versionId:"",mode:"",clipId:-1,clipReady:false,inventoryRevision:0,nativeState:"none",errorCode:0,
        audio:[],subtitles:[],currentAudioTrack:"",currentSubtitleTrack:"",captionMode:"",savedCaptionMode:"",
        captionTouched:false,pending:invalid,lastCommand:invalid,highCommandId:0}
end function

function NtField(value as Dynamic, key as String, fallback as Dynamic) as Dynamic
    if type(value) <> "roAssociativeArray" then return fallback
    if not value.DoesExist(key) then return fallback
    return value[key]
end function

function NtString(value as Dynamic) as Boolean
    return type(value) = "String" or type(value) = "roString"
end function

function NtText(value as Dynamic, limit as Integer, empty = false as Boolean) as Boolean
    if not NtString(value) then return false
    if Len(value) > limit or (not empty and Len(value) = 0) then return false
    for index = 1 to Len(value)
        code = Asc(Mid(value,index,1))
        if code < 32 or code = 127 then return false
    end for
    return true
end function

function NtIdentity(value as Dynamic) as Boolean
    if not NtText(value,256) then return false
    return Instr(1,value,"://") = 0
end function

function NtInteger(value as Dynamic, minimum as Integer) as Boolean
    kind = type(value)
    if kind <> "Integer" and kind <> "roInt" and kind <> "roInteger" and kind <> "LongInteger" and kind <> "roLongInteger" then return false
    return value >= minimum and value <= 2147483647
end function

function NtNow(value as Dynamic) as Double
    kind = type(value)
    if kind <> "Integer" and kind <> "roInt" and kind <> "roInteger" and kind <> "LongInteger" and kind <> "roLongInteger" and kind <> "Float" and kind <> "roFloat" and kind <> "Double" and kind <> "roDouble" then return 0
    if value <> value or value < 0 or value > 1000000000000.0 then return 0
    return value
end function

function NtCaption(value as Dynamic) as String
    if not NtString(value) then return ""
    if value = "Off" or value = "On" or value = "Instant replay" or value = "When mute" then return value
    return ""
end function

function NtCopy(previous as Dynamic) as Object
    if type(previous) <> "roAssociativeArray" then return NativeTrackCreate()
    result = {}
    for each key in previous
        result[key] = previous[key]
    end for
    return result
end function

function NtInventory(raw as Dynamic, kind as String) as Object
    result = []
    if type(raw) <> "roArray" then return result
    cap = 24
    idKey = "Track"
    labelKey = "Name"
    fallback = "Audio "
    if kind = "subtitle"
        cap = 32
        idKey = "TrackName"
        labelKey = "Description"
        fallback = "Subtitle "
    end if
    scanned = 0
    for each entry in raw
        scanned = scanned + 1
        if scanned > 64 or result.Count() >= cap then exit for
        rawId = NtField(entry,idKey,invalid)
        if NtText(rawId,4096)
            duplicate = false
            for each track in result
                if track.rawId = rawId then duplicate = true
            end for
            if not duplicate
                label = NtField(entry,labelKey,"")
                if not NtText(label,4096,true) then label = ""
                if label = rawId or Instr(1,LCase(label),"://") > 0 or Left(LCase(label),5) = "data:" then label = ""
                if label = "" then label = fallback + (result.Count() + 1).ToStr()
                result.Push({rawId:rawId,label:Left(label,80)})
            end if
        end if
    end for
    return result
end function

function NtSameInventory(left as Object, right as Object) as Boolean
    if left.Count() <> right.Count() then return false
    for index = 0 to left.Count() - 1
        if left[index].rawId <> right[index].rawId or left[index].label <> right[index].label then return false
    end for
    return true
end function

function NtAvailable(state as Object) as Boolean
    if not NtIdentity(state.attemptId) or not NtIdentity(state.versionId) then return false
    if state.mode <> "playback" or state.clipId < 0 or state.errorCode <> 0 then return false
    if not state.clipReady then return false
    return state.nativeState = "playing" or state.nativeState = "paused" or state.nativeState = "buffering"
end function

function NtHandle(kind as String, revision as Integer, index as Integer) as String
    prefix = "a-"
    if kind = "subtitle" then prefix = "s-"
    return prefix + revision.ToStr() + "-" + index.ToStr()
end function

function NtCurrentHandle(tracks as Object, raw as String, kind as String, revision as Integer) as String
    for index = 0 to tracks.Count() - 1
        if tracks[index].rawId = raw then return NtHandle(kind,revision,index)
    end for
    return ""
end function

function NtPublicTracks(state as Object, kind as String) as Object
    tracks = state.audio
    current = state.currentAudioTrack
    captions = true
    if kind = "subtitle"
        tracks = state.subtitles
        current = state.currentSubtitleTrack
        captions = state.captionMode <> "Off" and state.captionMode <> ""
    end if
    result = []
    for index = 0 to tracks.Count() - 1
        track = tracks[index]
        result.Push({handle:NtHandle(kind,state.inventoryRevision,index),label:track.label,selected:captions and current = track.rawId})
    end for
    return result
end function

function NativeTrackStatus(state as Object) as Object
    pending = invalid
    if state.pending <> invalid
        pending = {commandId:state.pending.commandId,kind:state.pending.kind,intent:state.pending.intent,handle:state.pending.handle}
    end if
    return {attemptId:state.attemptId,versionId:state.versionId,clipId:state.clipId,inventoryRevision:state.inventoryRevision,
        available:NtAvailable(state),audio:NtPublicTracks(state,"audio"),subtitles:NtPublicTracks(state,"subtitle"),
        currentAudioHandle:NtCurrentHandle(state.audio,state.currentAudioTrack,"audio",state.inventoryRevision),
        currentSubtitleHandle:NtCurrentHandle(state.subtitles,state.currentSubtitleTrack,"subtitle",state.inventoryRevision),
        captionMode:state.captionMode,offSupported:NtAvailable(state) and state.savedCaptionMode <> "",
        autoSupported:false,pending:pending,lastCommand:state.lastCommand}
end function

' Only bounded counts, fixed settings and flags enter the device console.
' Compare raw SDK counts with accepted inventory without publishing track IDs.
function NativeTrackDiagnostic(status as Dynamic, rawAudio as Dynamic, rawSubtitles as Dynamic) as Object
    available = NtField(status,"available",false)
    if type(available) <> "Boolean" and type(available) <> "roBoolean" then available = false
    audioHandle = NtField(status,"currentAudioHandle","")
    subtitleHandle = NtField(status,"currentSubtitleHandle","")
    hasAudio = false
    hasSubtitle = false
    if NtString(audioHandle) then hasAudio = Len(audioHandle)>0
    if NtString(subtitleHandle) then hasSubtitle = Len(subtitleHandle)>0
    command = NtField(NtField(status,"lastCommand",invalid),"result","")
    safeCommand = "none"
    for each known in ["issued","applied","timeout","retired","inventory_changed","rejected"]
        if command = known then safeCommand = known
    end for
    return {available:available,rawAudioCount:NtDiagnosticCount(rawAudio,64),rawSubtitleCount:NtDiagnosticCount(rawSubtitles,64),
        audioCount:NtDiagnosticCount(NtField(status,"audio",[]),24),subtitleCount:NtDiagnosticCount(NtField(status,"subtitles",[]),32),
        hasCurrentAudio:hasAudio,hasCurrentSubtitle:hasSubtitle,captionMode:NtCaption(NtField(status,"captionMode","")),command:safeCommand}
end function

function NtDiagnosticCount(value as Dynamic, maximum as Integer) as Integer
    if type(value) <> "roArray" then return 0
    count = value.Count()
    if count > maximum then return maximum
    return count
end function

sub NtCancelPending(state as Object, effects as Object, reason as String)
    if state.pending = invalid then return
    state.lastCommand = {commandId:state.pending.commandId,accepted:false,result:reason}
    state.pending = invalid
    effects.Push({kind:"cancel_timer"})
end sub

sub NtRetire(state as Object, effects as Object)
    if state.attemptId = "" or state.mode = "" then return
    NtCancelPending(state,effects,"retired")
    if state.captionTouched and state.savedCaptionMode <> "" then effects.Push({kind:"caption",mode:state.savedCaptionMode})
    state.inventoryRevision = state.inventoryRevision + 1
    state.mode = ""
    state.clipId = -1
    state.clipReady = false
    state.nativeState = "none"
    state.errorCode = 0
    state.audio = []
    state.subtitles = []
    state.currentAudioTrack = ""
    state.currentSubtitleTrack = ""
    state.captionMode = state.savedCaptionMode
    state.captionTouched = false
    state.savedCaptionMode = ""
end sub

function NtScopeMatches(state as Object, value as Dynamic) as Boolean
    attempt = NtField(value,"attemptId",invalid)
    version = NtField(value,"versionId",invalid)
    if not NtString(attempt) or not NtString(version) then return false
    if attempt <> state.attemptId or version <> state.versionId then return false
    clip = NtField(value,"clipId",invalid)
    revision = NtField(value,"inventoryRevision",invalid)
    if not NtInteger(clip,0) or not NtInteger(revision,1) then return false
    return clip = state.clipId and revision = state.inventoryRevision
end function

function NativeTrackReduce(previous as Dynamic, event as Dynamic) as Object
    state = NtCopy(previous)
    effects = []
    result = {state:state,effects:effects,accepted:false}
    kind = NtField(event,"kind","")
    if not NtString(kind) then return result
    if kind = "retire"
        NtRetire(state,effects)
        result.accepted = true
        return result
    end if
    if kind = "bind"
        attempt = NtField(event,"attemptId",invalid)
        version = NtField(event,"versionId","")
        mode = NtField(event,"mode","")
        if not NtIdentity(attempt) or not NtString(version) or not NtString(mode) then return result
        if mode <> "playback" and mode <> "preview" and mode <> "prebuffer" then return result
        NtRetire(state,effects)
        state.attemptId = attempt
        state.versionId = ""
        if NtIdentity(version) then state.versionId = version
        state.mode = mode
        state.clipReady = false
        state.nativeState = "starting"
        state.savedCaptionMode = NtCaption(NtField(event,"captionMode",invalid))
        state.captionMode = state.savedCaptionMode
        state.lastCommand = invalid
        result.accepted = true
        return result
    end if
    if kind = "sample"
        attempt = NtField(event,"attemptId",invalid)
        version = NtField(event,"versionId",invalid)
        mode = NtField(event,"mode",invalid)
        if not NtString(attempt) or not NtString(version) or not NtString(mode) then return result
        if attempt <> state.attemptId or version <> state.versionId or mode <> state.mode or state.mode = "" then return result
        clip = NtField(event,"clipId",invalid)
        if not NtInteger(clip,0) then return result
        audio = NtInventory(NtField(event,"audio",[]),"audio")
        subtitles = NtInventory(NtField(event,"subtitles",[]),"subtitle")
        if state.clipId <> clip then state.clipReady = false
        changed = state.clipId <> clip or not NtSameInventory(audio,state.audio) or not NtSameInventory(subtitles,state.subtitles)
        if changed
            NtCancelPending(state,effects,"inventory_changed")
            state.inventoryRevision = state.inventoryRevision + 1
            state.clipId = clip
            state.audio = audio
            state.subtitles = subtitles
        end if
        state.nativeState = "none"
        nativeState = NtField(event,"state",invalid)
        if NtString(nativeState)
            if nativeState = "playing" or nativeState = "paused" or nativeState = "buffering" or nativeState = "stopping" or nativeState = "error" then state.nativeState = nativeState
        end if
        errorCode = NtField(event,"errorCode",invalid)
        state.errorCode = -1
        if NtInteger(errorCode,-2147483647) then state.errorCode = errorCode
        ' Rebuffering retains readiness only for a previously confirmed clip.
        ' Metadata inventories during initial buffering do not prove readiness.
        if state.errorCode <> 0 or (state.nativeState <> "playing" and state.nativeState <> "paused" and state.nativeState <> "buffering")
            state.clipReady = false
        else if state.nativeState = "playing" or state.nativeState = "paused"
            state.clipReady = true
        end if
        state.captionMode = NtCaption(NtField(event,"captionMode",invalid))
        state.currentAudioTrack = ""
        state.currentSubtitleTrack = ""
        raw = NtField(event,"currentAudioTrack",invalid)
        if NtText(raw,4096,true) then state.currentAudioTrack = raw
        raw = NtField(event,"currentSubtitleTrack",invalid)
        if NtText(raw,4096,true) then state.currentSubtitleTrack = raw
        if state.pending <> invalid
            pending = state.pending
            applied = false
            if pending.kind = "audio" then applied = state.currentAudioTrack = pending.rawId
            if pending.kind = "subtitle" and pending.intent = "select" then applied = state.currentSubtitleTrack = pending.rawId and state.captionMode = "On"
            if pending.kind = "subtitle" and pending.intent = "off" then applied = state.captionMode = "Off"
            if applied
                state.lastCommand = {commandId:pending.commandId,accepted:true,result:"applied"}
                state.pending = invalid
                effects.Push({kind:"cancel_timer"})
            end if
        end if
        result.accepted = true
        return result
    end if
    if kind = "tick"
        if state.pending = invalid or not NtScopeMatches(state,event) then return result
        commandId = NtField(event,"commandId",invalid)
        if not NtInteger(commandId,1) then return result
        if commandId <> state.pending.commandId or NtNow(NtField(event,"nowMs",0)) < state.pending.deadlineMs then return result
        NtCancelPending(state,effects,"not_selected")
        result.accepted = true
        return result
    end if
    if kind <> "command" then return result
    command = NtField(event,"command",invalid)
    if not NtAvailable(state) or not NtScopeMatches(state,command) then return result
    commandId = NtField(command,"commandId",invalid)
    if not NtInteger(commandId,1) then return result
    if commandId <= state.highCommandId then return result
    state.highCommandId = commandId
    state.lastCommand = {commandId:commandId,accepted:false,result:"rejected"}
    trackKind = NtField(command,"kind",invalid)
    intent = NtField(command,"intent",invalid)
    handle = NtField(command,"handle","")
    if not NtString(trackKind) or not NtString(intent) or not NtText(handle,64,true) then return result
    if trackKind <> "audio" and trackKind <> "subtitle" then return result
    if intent = "auto"
        state.lastCommand.result = "unsupported"
        return result
    end if
    if intent <> "select" and intent <> "off" then return result
    if intent = "off" and (trackKind <> "subtitle" or handle <> "" or state.savedCaptionMode = "") then return result
    rawId = ""
    if intent = "select"
        tracks = state.audio
        if trackKind = "subtitle" then tracks = state.subtitles
        for index = 0 to tracks.Count() - 1
            if handle = NtHandle(trackKind,state.inventoryRevision,index) then rawId = tracks[index].rawId
        end for
        if rawId = "" then return result
        if trackKind = "subtitle" and state.savedCaptionMode = "" then return result
    end if
    if state.pending <> invalid
        state.lastCommand.result = "busy"
        if state.pending.kind = trackKind and state.pending.intent = intent and state.pending.handle = handle then state.lastCommand.result = "duplicate"
        return result
    end if
    already = trackKind = "audio" and state.currentAudioTrack = rawId
    if trackKind = "subtitle" and intent = "off" then already = state.captionMode = "Off"
    if trackKind = "subtitle" and intent = "select" then already = state.currentSubtitleTrack = rawId and state.captionMode = "On"
    if already
        state.lastCommand = {commandId:commandId,accepted:true,result:"applied"}
        result.accepted = true
        return result
    end if
    if trackKind = "audio"
        effects.Push({kind:"audio",trackId:rawId})
    else
        targetCaption = "Off"
        if intent = "select"
            targetCaption = "On"
            effects.Push({kind:"subtitle",trackId:rawId})
        end if
        if state.captionMode <> targetCaption
            state.captionTouched = true
            effects.Push({kind:"caption",mode:targetCaption})
        end if
    end if
    state.pending = {commandId:commandId,kind:trackKind,intent:intent,handle:handle,rawId:rawId,
        deadlineMs:NtNow(NtField(event,"nowMs",0)) + 5000}
    state.lastCommand = {commandId:commandId,accepted:true,result:"issued"}
    effects.Push({kind:"timer",milliseconds:5000,attemptId:state.attemptId,versionId:state.versionId,
        clipId:state.clipId,inventoryRevision:state.inventoryRevision,commandId:commandId})
    result.accepted = true
    return result
end function
