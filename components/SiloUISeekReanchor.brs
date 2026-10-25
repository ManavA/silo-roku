' Ordinary same-lease seek lifecycle. The shipping entry gate stays disabled
' until host review and native cohort acceptance have completed.
function SiloUISeekBegin(targetMs as Double) as Boolean
    if not SpNumber(targetMs,604800000#,false) then return false
    if m.seekReanchorEnabled <> true or m.seekReanchor <> invalid or m.manualFocus = invalid then return false
    if SiloUIPlaybackAdmissionBlocked() then return false
    if m.view <> "player" or m.transitionIntent <> invalid or m.playbackChoiceBusy = true or m.recoveringNative = true then return false
    if m.audioRestorePause = true or m.pauseRestoreMuted = true then return false
    if m.video.state <> "playing" and m.video.state <> "paused" then return false
    context = SiloPlaybackContext(m.playPlan,SiloUIOwner())
    descriptor = SiloSeekDescriptor(m.playPlan,SiloUIOwner())
    if context = invalid or descriptor = invalid or m.video.content = invalid then return false
    owner = m.playPlan.cleanupOwner
    if type(owner) <> "roAssociativeArray" then return false
    if not SoSeekScopeEqual(SpScope(owner),SiloUIOwner()) or owner.sessionRevision <> context.sessionRevision then return false
    position = m.video.position * 1000# + NumberOr(m.playPlan.timelineOffsetMs,0)
    if not SpNumber(position,604800000#,false) then return false
    m.seekReanchor = {
        phase:"stopping", operationId:SiloUICleanupUuid(), token:m.playToken,
        owner:SpCopy(owner), context:context, plan:SpCopy(m.playPlan),
        node:m.video, content:m.video.content, peer:m.manualFocus, targetMs:targetMs,
        lastObservedMs:position, reportSequence:m.progressSequence,
        transportState:{undoMs:m.skipUndoMs,undoTicks:m.skipUndoTicks,skipped:SpCopy(m.transportSkipped)},
        desiredPaused:m.video.state="paused", clock:CreateObject("roTimespan")
    }
    m.playbackChoiceBusy = true
    m.video.control = "stop"
    if m.manualFocus <> invalid then m.manualFocus.setFocus(true)
    if m.seekReanchorTimer <> invalid then m.seekReanchorTimer.control = "start"
    return true
end function

function SiloUISeekOwned(attempt as Object) as Boolean
    if m.seekReanchor = invalid or m.view <> "player" or m.playPlan = invalid then return false
    if attempt.operationId <> m.seekReanchor.operationId or attempt.token <> m.playToken then return false
    if not SoSeekScopeEqual(SpScope(attempt.owner),SiloUIOwner()) then return false
    owner = m.playPlan.cleanupOwner
    if type(owner) <> "roAssociativeArray" then return false
    for each field in ["provider","sourceId","profileId","generation","sessionRevision"]
        if owner[field] <> attempt.owner[field] then return false
    end for
    if m.video.content = invalid then return false
    if not attempt.node.isSameNode(m.video) or not attempt.content.isSameNode(m.video.content) then return false
    return m.playPlan.sessionId = attempt.context.sessionId and m.playPlan.planId = attempt.context.planId and m.playPlan.planAttemptKey = attempt.context.planAttemptKey
end function

function SiloUISeekCurrent(attempt as Object) as Boolean
    if not SiloUISeekOwned(attempt) or m.video.content = invalid then return false
    if not attempt.node.isSameNode(m.video) or not attempt.content.isSameNode(m.video.content) then return false
    for each field in ["sourceId","profileId","sessionRevision","installationId","sessionId","playbackAttemptId","planId","planAttemptId","planAttemptKey"]
        if SpField(m.playPlan.siloPlayback,field) <> SpField(attempt.context,field) then return false
    end for
    return m.playPlan.planId = attempt.context.planId and m.playPlan.planAttemptKey = attempt.context.planAttemptKey
end function

' Only observed playing intervals advance the expected source landing point.
' Loading, buffering and paused time cannot excuse a native overshoot.
function SiloUISeekPlayingElapsed(attempt as Object) as Double
    elapsed = NumberOr(attempt.playingElapsedMs,0)
    if m.video.state = "playing"
        if attempt.playingClock = invalid then attempt.playingClock = CreateObject("roTimespan")
        return elapsed + attempt.playingClock.TotalMilliseconds()
    end if
    if attempt.playingClock <> invalid
        elapsed = elapsed + attempt.playingClock.TotalMilliseconds()
        attempt.playingElapsedMs = elapsed
        attempt.playingClock = invalid
    end if
    return elapsed
end function

sub SiloUISeekObserve(positionObserved = false as Boolean)
    attempt = m.seekReanchor
    if attempt = invalid then return
    if not SiloUISeekCurrent(attempt) then return
    if attempt.phase = "binding" or attempt.phase = "pausing"
        if m.video.state = "error" or m.video.state = "finished" then PlayerClose(false):return
        expectedMs = attempt.targetMs + SiloUISeekPlayingElapsed(attempt)
    end if
    if attempt.phase = "binding"
        if attempt.bindingClock.TotalMilliseconds() >= 120000 then PlayerClose(false):return
        if m.video.state <> "playing" or not positionObserved then return
        localMs = m.video.position*1000#
        if not SpNumber(localMs,315576000000#,false) or localMs <= 0 then return
        if Abs(localMs+NumberOr(m.playPlan.timelineOffsetMs,0)-expectedMs) > 1000 then return
        if attempt.desiredPaused
            attempt.phase = "pausing":attempt.pauseClock = CreateObject("roTimespan")
            m.video.control = "pause"
        else
            SiloUISeekFinish()
        end if
        return
    end if
    if attempt.phase = "pausing"
        if attempt.pauseClock.TotalMilliseconds() >= 10000 then PlayerClose(false):return
        localMs = m.video.position*1000#
        if not SpNumber(localMs,315576000000#,false) then return
        if m.video.state = "paused" and Abs(localMs+NumberOr(m.playPlan.timelineOffsetMs,0)-expectedMs) <= 1000 then SiloUISeekFinish()
        return
    end if
    if attempt.phase <> "stopping" or m.video.state <> "stopped" then return
    if attempt.clock.TotalMilliseconds() >= 5000 then PlayerClose(false):return
    live = SiloSeekDescriptor(m.playPlan,SiloUIOwner())
    frozen = SiloSeekDescriptor(attempt.plan,SiloUIOwner())
    if live = invalid or frozen = invalid then PlayerClose(false):return
    if not SiloSeekEqual(live,frozen) then PlayerClose(false):return
    attempt.phase = "requesting"
    params = {sessionId:attempt.context.sessionId,plan:attempt.plan,positionMs:attempt.targetMs,replanRequestId:attempt.operationId}
    ApiOwned("playback_seek_reanchor",params,"seek_reanchor",attempt,attempt.owner)
    attempt.apiRequestId = m.requestId
end sub

sub SiloUISeekCancel()
    m.seekReanchor = invalid
    if m.seekReanchorTimer <> invalid then m.seekReanchorTimer.control = "stop"
end sub

sub SiloUISeekResult(entry as Object, result as Object)
    attempt = entry.extra
    if type(attempt) <> "roAssociativeArray" then SiloUISubtitleResultCleanup(entry,result):return
    if attempt.apiRequestId <> result.requestId then SiloUISubtitleResultCleanup(entry,result):return
    if entry.generation = m.generation and SiloUISeekCurrent(attempt) and attempt.phase = "requesting"
        valid = result.ok = true and type(result.plan) = "roAssociativeArray"
        if attempt.clock.TotalMilliseconds() >= 60000 or m.video.state <> "stopped" then valid = false
        if valid
            accepted = SiloSeekDescriptor(result.plan,SiloUIOwner())
            frozen = SiloSeekDescriptor(attempt.plan,SiloUIOwner())
            live = SiloSeekDescriptor(m.playPlan,SiloUIOwner())
            valid = accepted <> invalid and frozen <> invalid and live <> invalid
            if valid then valid = SiloSeekEqual(live,frozen)
            if valid then valid = SiloSeekEqual(accepted.control,attempt.context) and SiloSeekEqual(accepted.route,frozen.route) and SiloSeekEqual(accepted.request,frozen.request)
            target = NumberOr(result.plan.startPositionMs,-1)+NumberOr(result.plan.timelineOffsetMs,-1)
            if Abs(target-attempt.targetMs) > 1000 then valid = false
        end if
        if valid
            plan = result.plan
            plan["cleanupOwner"] = attempt.owner
            sequence = m.progressSequence:back = m.playerReturn:captions = m.savedCaptionMode
            ' Only this owned handoff ends the 60s control budget.
            attempt.phase = "binding"
            attempt.bindingClock = CreateObject("roTimespan")
            PlayerStart(plan)
            m.progressSequence = sequence:m.playerReturn = back:m.savedCaptionMode = captions
            m.skipUndoMs = attempt.transportState.undoMs:m.skipUndoTicks = attempt.transportState.undoTicks
            m.transportSkipped = attempt.transportState.skipped
            attempt.context = SiloPlaybackContext(plan,SiloUIOwner())
            attempt.content = m.video.content
            if m.manualFocus <> invalid then m.manualFocus.setFocus(true)
            m.playbackChoiceBusy = true:m.recoveringNative = false
            m.playLastPositionMs = attempt.lastObservedMs
            m.audioRestorePause = attempt.desiredPaused
            if attempt.desiredPaused then m.video.mute = true
            SiloUISubtitleResultCleanup(entry,result)
            return
        end if
        authority = SiloUISubtitleChangeControlPlan({plan:attempt.plan,context:attempt.context,owner:attempt.owner},result.controlReceipt)
        if authority <> invalid then m.playPlan.siloPlayback = authority.siloPlayback:m.playPlan.planId = authority.planId:m.playPlan.planAttemptKey = authority.planAttemptKey
        SiloUISubtitleResultCleanup(entry,result)
        PlayerClose(false)
        return
    end if
    SiloUISubtitleResultCleanup(entry,result)
    if SiloUISeekOwned(attempt) then PlayerClose(false):return
    SiloUISeekRetireCaptured(attempt)
end sub

sub SiloUISeekFinish()
    attempt = m.seekReanchor
    if attempt = invalid then return
    m.playLastPositionMs = m.video.position*1000#+NumberOr(m.playPlan.timelineOffsetMs,0)
    m.audioRestorePause = false:m.pauseRestoreMuted = false:m.video.mute = false
    m.playbackChoiceBusy = false
    m.nativeSeenPlaying = true:m.playWaitClock = invalid
    if attempt.marker <> invalid
        if attempt.marker.kind = "native_skip"
            m.introDismissed = true:m.playerCue.visible = false
        else
            TransportSeekAcknowledged(attempt)
        end if
    end if
    SiloUISeekCancel()
    PlayerUpdateNativeActions(PlayerCurrentCue())
    PlayerPlaybackFocus()
end sub

sub onSeekReanchorTimer()
    attempt = m.seekReanchor
    if attempt = invalid then return
    if not SiloUISeekCurrent(attempt)
        if SiloUISeekOwned(attempt) then PlayerClose(false) else SiloUISeekRetireCaptured(attempt)
        return
    end if
    if attempt.phase = "stopping" or attempt.phase = "requesting"
        elapsed = attempt.clock.TotalMilliseconds()
        if elapsed >= 60000 or (attempt.phase = "stopping" and elapsed >= 5000) then PlayerClose(false):return
    else if attempt.phase = "binding"
        if attempt.bindingClock.TotalMilliseconds() >= 120000 then PlayerClose(false):return
    else if attempt.phase = "pausing"
        if attempt.pauseClock.TotalMilliseconds() >= 10000 then PlayerClose(false):return
    end if
    SiloUISeekObserve()
end sub


' Retired callbacks own only the captured lease. Current same-lease content
' belongs to its newer binding and must survive an old response or watchdog.
sub SiloUISeekRetireCaptured(attempt as Object)
    ' A disappeared content field cannot prove a newer binding. Close only the
    ' captured empty native node under its unchanged full control authority.
    if m.view = "player" and type(m.playPlan) = "roAssociativeArray" and m.video.content = invalid
        if m.playToken = attempt.token and attempt.node.isSameNode(m.video)
            current = SiloPlaybackContext(m.playPlan,SiloUIOwner())
            owner = m.playPlan.cleanupOwner
            if type(owner) = "roAssociativeArray" and SiloSeekEqual(current,attempt.context)
                if SoSeekScopeEqual(SpScope(owner),attempt.owner) and owner.sessionRevision = attempt.owner.sessionRevision
                    PlayerClose(false,false)
                    return
                end if
            end if
        end if
    end if
    protected = false
    if type(m.playPlan) = "roAssociativeArray" and m.view = "player" and m.video.content <> invalid
        live = SiloPlaybackContext(m.playPlan,SiloUIOwner())
        if live <> invalid
            owner = SpField(m.playPlan,"cleanupOwner")
            if type(owner) = "roAssociativeArray"
                protected = SoSeekScopeEqual(SpScope(owner),SiloUIOwner()) and owner.sessionRevision = live.sessionRevision
                protected = protected and live.sessionId = attempt.context.sessionId and live.installationId = attempt.context.installationId and live.sourceId = attempt.context.sourceId and live.profileId = attempt.context.profileId
            end if
        end if
    end if
    if not protected then SiloUIQueueCleanup(attempt.plan,attempt.owner,{positionMs:attempt.lastObservedMs,sequence:attempt.reportSequence+1,isPaused:attempt.desiredPaused})
    if m.seekReanchor <> invalid
        if m.seekReanchor.operationId = attempt.operationId then SiloUISeekCancel()
    end if
end sub
