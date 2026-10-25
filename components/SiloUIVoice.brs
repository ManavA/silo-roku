' Reply synchronously; lease changes and decoder recovery cannot confirm acceptance.
function handleTransport(info as Dynamic) as Object
    rejected = {status:"error.generic"}
    if type(info) <> "roAssociativeArray" then return rejected
    if m.top.appFocused <> true then return rejected
    if m.playLoading = true or m.audioLoading = true or m.playbackChoiceBusy = true or m.recoveringNative = true then return rejected
    if m.transitionIntent <> invalid or m.seekReanchor <> invalid or m.compatPreparation <> invalid then return rejected
    if m.audioRestorePause = true or m.pauseRestoreMuted = true then return rejected
    audio = m.view = "audio"
    if audio
        if m.playPlan <> invalid or m.audioPlan = invalid or m.audioNext <> invalid then return rejected
        if m.audioScope <> HomeProgressScope() then return rejected
        plan = m.audioPlan:owner = m.audioOwner:node = m.audioNode
    else
        if m.view <> "player" or m.playPlan = invalid or m.audioPlan <> invalid then return rejected
        if m.nativePlaybackToken <> m.playToken then return rejected
        plan = m.playPlan:owner = m.nativePlaybackOwner:node = m.video
        if plan.transport = "silo_compat" then return rejected
        if m.originalPlayback <> invalid
            if m.originalPlayback.phase <> "verified_playing" then return rejected
        end if
    end if
    if type(owner) <> "roAssociativeArray" or node = invalid then return rejected
    current = SiloUIOwner()
    for each field in ["provider","sourceId","profileId","generation"]
        if owner[field] = invalid or owner[field] <> current[field] then return rejected
    end for
    if plan.provider = "silo" or current.provider = "silo"
        lease = plan.cleanupOwner
        if type(lease) <> "roAssociativeArray" then return rejected
        for each field in ["provider","sourceId","profileId","generation"]
            if lease[field] = invalid or lease[field] <> current[field] then return rejected
        end for
        if lease.sessionRevision = invalid or lease.sessionRevision <> DetailPhotoSessionRevision() then return rejected
    end if
    if plan.sessionId = invalid or plan.sessionId = "" then return rejected
    if node.state <> "playing" and node.state <> "paused" then return rejected
    command = info.command
    if command = "stop"
        if audio then SiloUIAudioRelease() else PlayerClose(false)
        return {status:"success"}
    else if command = "play" or command = "resume"
        if audio
            if SiloUIAudioPausedSeekCurrent()
                m.audioChapterPaused = false:m.audioPausedSeek = invalid:m.audioPartPaused = false
                node.control = "resume"
            else if node.state = "paused"
                node.control = "resume"
            end if
        else if node.state = "paused"
            node.control = "resume"
        end if
        return {status:"success"}
    else if command = "pause"
        if audio
            if not SiloUIAudioPausedSeekCurrent() then node.control = "pause"
        else
            node.control = "pause"
        end if
        return {status:"success"}
    end if
    delta = invalid
    if command = "forward" then delta = 30000#
    if command = "rewind" then delta = -30000#
    if command = "replay" then delta = -10000#
    if command = "seek"
        duration = info.duration
        if type(duration) <> "String" and type(duration) <> "roString" then return rejected
        if Len(duration) = 0 or Len(duration) > 8 then return rejected
        for i = 1 to Len(duration)
            if Instr(1,"0123456789",Mid(duration,i,1)) = 0 then return rejected
        end for
        delta = Val(duration)*1000#
        if delta <= 0 or delta > 315576000000# then return rejected
        if info.direction = "backward"
            delta = -delta
        else if info.direction <> "forward"
            return rejected
        end if
    end if
    if delta = invalid and command <> "startover" then return rejected
    if audio
        if m.audioIndex < 0 or m.audioIndex >= m.audioQueue.Count() then return rejected
        position = SiloUIAudioGlobal(m.audioQueue,m.audioIndex,m.audioLocalMs)
        last = m.audioQueue[m.audioQueue.Count()-1]
        durationMs = last.offsetMs+last.durationMs
    else
        position = PlayerPositionMs()
        durationMs = NumberOr(m.playItem.durationMs,0)
    end if
    if durationMs <= 0 then return rejected
    target = 0#
    if command <> "startover" then target = position+delta
    status = "success"
    if target < 0 then target = 0:status = "success.seek-start"
    if target >= durationMs then target = durationMs-1000:status = "success.seek-end"
    if target < 0 then target = 0
    if audio
        part = SiloUIAudioTarget(m.audioQueue,target)
        if part = invalid then return rejected
        ' A new part needs an asynchronous lease; do not acknowledge it early.
        if part.index <> m.audioIndex then return rejected
        SiloUIAudioSeek(part.localMs)
    else
        if target < NumberOr(plan.timelineOffsetMs,0) then return rejected
        if plan.provider = "silo" and plan.canSeekAnywhere <> true
            start = plan.seekWindowStartMs:finish = plan.seekWindowEndMs
            if not SiloUIAudioNumber(start,315576000000#) or not SiloUIAudioNumber(finish,315576000000#) then return rejected
            if target < start or target > finish then return rejected
        end if
        if not PlayerSeekTo(target) then return rejected
    end if
    return {status:status}
end function
