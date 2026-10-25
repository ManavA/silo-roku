' Pure remote policy. All positions and seek commands are native route-relative
' milliseconds; provider offsets, sessions and committed progress live elsewhere.
function TpField(value as Dynamic, key as String, fallback as Dynamic) as Dynamic
    if type(value) <> "roAssociativeArray" then return fallback
    if not value.DoesExist(key) then return fallback
    return value[key]
end function

function TpNumber(value as Dynamic) as Boolean
    kind = type(value)
    if kind <> "Integer" and kind <> "roInt" and kind <> "roInteger" and kind <> "LongInteger" and kind <> "roLongInteger" and kind <> "Float" and kind <> "roFloat" and kind <> "Double" and kind <> "roDouble" then return false
    return value = value and Abs(value) <= 1000000000000.0
end function

function TpNumeric(value as Dynamic, fallback as Double) as Double
    if TpNumber(value) then return value
    return fallback
end function

function TpString(value as Dynamic) as Boolean
    return type(value) = "String" or type(value) = "roString"
end function

function TpBoolean(value as Dynamic) as Boolean
    return type(value) = "Boolean" or type(value) = "roBoolean"
end function

function TpIdentifier(value as Dynamic, limit as Integer) as Boolean
    if not TpString(value) then return false
    if Len(value) = 0 or Len(value) > limit then return false
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
    for index = 1 to Len(value)
        if Instr(1,allowed,Mid(value,index,1)) = 0 then return false
    end for
    return true
end function

function TpCopy(value as Object) as Object
    copied = {}
    for each key in value
        copied[key] = value[key]
    end for
    return copied
end function

function TpClamp(value as Double, durationMs as Double) as Double
    if value < 0 then return 0
    if durationMs > 0 and value > durationMs then return durationMs
    return value
end function

function TransportCreate(options as Dynamic) as Dynamic
    if type(options) <> "roAssociativeArray" then return invalid
    attempt = TpField(options,"attemptId",invalid)
    if not TpIdentifier(attempt,128) then return invalid
    position = TpField(options,"positionMs",0)
    duration = TpField(options,"durationMs",0)
    nowMs = TpField(options,"nowMs",0)
    for each value in [position,duration,nowMs]
        if not TpNumber(value) then return invalid
        if value < 0 then return invalid
    end for
    if position > 604800000 or duration > 604800000 then return invalid
    paused = TpField(options,"paused",false)
    seekable = TpField(options,"canSeek",false)
    if not TpBoolean(paused) or not TpBoolean(seekable) then return invalid
    buttons = TpField(options,"buttons",["play_pause"])
    if type(buttons) <> "roArray" then return invalid
    if buttons.Count() = 0 or buttons.Count() > 6 then return invalid
    safeButtons = []
    for each button in buttons
        if not TpIdentifier(button,32) then return invalid
        safeButtons.Push(button)
    end for
    return {attemptId:attempt,phase:"hidden",overlay:"none",ready:false,retired:false,nativeState:"starting",
        desiredPaused:paused,controlPending:"",rePausePending:false,rePauseTargetMs:-1,clipId:-1,
        positionMs:TpClamp(position,duration),durationMs:duration,renderedMs:-1,canSeek:seekable,
        buttons:safeButtons,buttonIndex:0,cursorMs:-1,direction:0,repeatCount:0,lastHorizontalAtMs:-1,
        scanRate:0,scanAtMs:-1,commitAtMs:-1,hideAtMs:-1,
        seekTargetMs:-1,seekAnchorMs:-1,seekId:0,seekIssuedAtMs:-1,seekDeadlineMs:-1,
        timerAtMs:-1,timerToken:0,nowMs:nowMs}
end function

sub TpDropCursor(state as Object)
    state["cursorMs"] = -1
    state["direction"] = 0
    state["repeatCount"] = 0
    state["lastHorizontalAtMs"] = -1
    state["scanRate"] = 0
    state["scanAtMs"] = -1
    state["commitAtMs"] = -1
end sub

sub TpRetire(state as Object)
    TpDropCursor(state)
    state["phase"] = "hidden"
    state["overlay"] = "none"
    state["ready"] = false
    state["retired"] = true
    state["rePausePending"] = false
    state["rePauseTargetMs"] = -1
    state["controlPending"] = ""
    state["seekTargetMs"] = -1
    state["seekDeadlineMs"] = -1
    state["hideAtMs"] = -1
end sub

sub TpCommand(state as Object, effects as Object, action as String)
    effects.Push({kind:"command",command:{action:action,attemptId:state["attemptId"]}})
    state["controlPending"] = action
end sub

sub TpBar(state as Object, nowMs as Double)
    state["phase"] = "bar"
    state["hideAtMs"] = nowMs + 3000
end sub

sub TpToggle(state as Object, effects as Object, nowMs as Double)
    TpDropCursor(state)
    if state["phase"] <> "buttons" then TpBar(state,nowMs)
    state["desiredPaused"] = not state["desiredPaused"]
    if state["desiredPaused"]
        if state["seekTargetMs"] >= 0
            ' Pausing a seek before native playing can prevent it from completing.
            state["rePausePending"] = true
            state["rePauseTargetMs"] = state["seekTargetMs"]
        else
            TpCommand(state,effects,"pause")
        end if
    else
        state["rePausePending"] = false
        state["rePauseTargetMs"] = -1
        TpCommand(state,effects,"resume")
    end if
end sub

function TpStep(state as Object) as Double
    stepMs = state["durationMs"] / 120
    if stepMs < 15000 then stepMs = 15000
    return stepMs
end function

function TpCursorBase(state as Object) as Double
    if state["seekTargetMs"] >= 0 then return state["seekTargetMs"]
    return state["positionMs"]
end function

sub TpMoveCursor(state as Object, direction as Integer, nowMs as Double)
    if state["cursorMs"] < 0 then state["cursorMs"] = TpCursorBase(state)
    if state["direction"] = direction and state["lastHorizontalAtMs"] >= 0 and nowMs - state["lastHorizontalAtMs"] <= 460
        state["repeatCount"]++
    else
        state["repeatCount"] = 0
    end if
    multiplier = 1
    if state["repeatCount"] >= 9
        multiplier = 7
    else if state["repeatCount"] >= 5
        multiplier = 4
    else if state["repeatCount"] >= 2
        multiplier = 2
    end if
    state["direction"] = direction
    state["lastHorizontalAtMs"] = nowMs
    state["cursorMs"] = TpClamp(state["cursorMs"] + direction * TpStep(state) * multiplier,state["durationMs"])
    state["phase"] = "scrub"
    state["scanRate"] = 0
    state["scanAtMs"] = -1
    ' Silo Apple/Google commit after the final horizontal input, or on OK.
    state["commitAtMs"] = nowMs + 480
end sub

sub TpScan(state as Object, direction as Integer, repeated as Boolean, nowMs as Double)
    if state["cursorMs"] < 0 then state["cursorMs"] = TpCursorBase(state)
    if state["phase"] = "scan" and state["direction"] = direction
        if not repeated
            if state["scanRate"] = 1
                state["scanRate"] = 2
            else
                state["scanRate"] = 4
            end if
        end if
    else
        state["scanRate"] = 1
    end if
    state["direction"] = direction
    state["phase"] = "scan"
    state["commitAtMs"] = -1
    state["cursorMs"] = TpClamp(state["cursorMs"] + direction * TpStep(state),state["durationMs"])
    ' Initial Roku tuning: 200 ms cursor ticks and a 1/2/4 scan ladder are not
    ' measured native-device optima. No decoder seek is issued by a scan tick.
    state["scanAtMs"] = nowMs + 200
end sub

sub TpCommit(state as Object, effects as Object, nowMs as Double)
    targetMs = state["cursorMs"]
    TpDropCursor(state)
    TpBar(state,nowMs)
    if targetMs < 0 then return
    if state["seekTargetMs"] < 0 and state["renderedMs"] >= 0
        if Abs(targetMs - state["renderedMs"]) < 1 then return
    end if
    state["seekId"]++
    state["seekTargetMs"] = targetMs
    state["seekAnchorMs"] = state["renderedMs"]
    state["seekIssuedAtMs"] = nowMs
    ' Initial tuning: the watchdog bounds UI settlement, not playback recovery.
    ' A timeout never changes observed position or authorizes committed progress.
    state["seekDeadlineMs"] = nowMs + 8000
    state["rePausePending"] = state["desiredPaused"]
    state["rePauseTargetMs"] = -1
    if state["rePausePending"] then state["rePauseTargetMs"] = targetMs
    effects.Push({kind:"command",command:{action:"seek",attemptId:state["attemptId"],positionMs:targetMs}})
end sub

function TpNative(state as Object, status as Dynamic, effects as Object, nowMs as Double) as Boolean
    if type(status) <> "roAssociativeArray" then return false
    if TpField(status,"attemptId",invalid) <> state["attemptId"] or TpField(status,"mode",invalid) <> "playback" then return false
    nativeState = TpField(status,"state",invalid)
    if not TpString(nativeState) then return false
    terminal = nativeState = "stopping" or nativeState = "stopped" or nativeState = "finished" or nativeState = "error"
    if not terminal and nativeState <> "playing" and nativeState <> "paused" and nativeState <> "buffering" then return false
    clip = TpField(status,"clipId",invalid)
    if not TpNumber(clip) then return false
    if clip <> Int(clip) or clip < -1 or clip >= 2147483647 then return false
    if clip < 0 and not terminal then return false
    if clip >= 0 and state["clipId"] >= 0 and clip <> state["clipId"] then return false
    if terminal
        state["nativeState"] = nativeState
        TpRetire(state)
        return true
    end if
    position = TpField(status,"position",-1)
    duration = TpField(status,"duration",-1)
    if not TpNumber(position) or not TpNumber(duration) then return false
    if position < -1 or duration < -1 or position > 604800 or duration > 604800 then return false
    state["nativeState"] = nativeState
    state["clipId"] = clip
    if duration >= 0 then state["durationMs"] = duration * 1000
    if position >= 0 then state["positionMs"] = TpClamp(position * 1000,state["durationMs"])
    if nativeState = "playing" or nativeState = "paused"
        if position >= 0 then state["ready"] = true
    end if
    rendered = TpNumeric(TpField(status,"renderedPosition",invalid),-1)
    renderedClip = TpNumeric(TpField(status,"renderedClipId",invalid),-1)
    epoch = TpNumeric(TpField(status,"renderedEpoch",invalid),-1)
    state["renderedMs"] = -1
    if renderedClip = clip and epoch = 0 and rendered >= 0 and rendered <= 604800
        state["renderedMs"] = rendered * 1000
    end if
    landed = false
    evidenceTarget = state["seekTargetMs"]
    if evidenceTarget < 0 and state["rePausePending"] then evidenceTarget = state["rePauseTargetMs"]
    if evidenceTarget >= 0 and state["renderedMs"] >= 0 and nowMs > state["seekIssuedAtMs"]
        ' The 2 s tolerance is a bounded initial UI policy. Native default seeks
        ' may land on an earlier sync frame; it is not a hardware accuracy promise.
        fresh = state["seekAnchorMs"] < 0 or Abs(state["renderedMs"] - state["seekAnchorMs"]) >= 1
        landed = fresh and Abs(state["renderedMs"] - evidenceTarget) <= 2000
    end if
    if nativeState = "playing"
        ' A playing edge can precede positionInfo's new rendered sample. Pausing
        ' then can pin the old frame; preserve intent until the target is observed.
        if state["rePausePending"] and landed
            state["rePausePending"] = false
            state["rePauseTargetMs"] = -1
            TpCommand(state,effects,"pause")
        else if state["controlPending"] = "resume"
            state["controlPending"] = ""
            state["desiredPaused"] = false
        else if state["seekTargetMs"] < 0 and state["controlPending"] = "" and not state["rePausePending"]
            state["desiredPaused"] = false
        end if
    else if nativeState = "paused"
        if state["controlPending"] <> "resume"
            state["desiredPaused"] = true
            if state["controlPending"] = "pause" then state["controlPending"] = ""
            if landed
                state["rePausePending"] = false
                state["rePauseTargetMs"] = -1
            end if
        end if
    end if
    if landed
        state["seekTargetMs"] = -1
        state["seekDeadlineMs"] = -1
    end if
    return true
end function

function TpKey(state as Object, event as Object, effects as Object, nowMs as Double) as Boolean
    key = TpField(event,"key",invalid)
    press = TpField(event,"press",invalid)
    repeated = TpField(event,"repeat",false)
    if not TpString(key) or not TpBoolean(press) or not TpBoolean(repeated) then return false
    key = LCase(key)
    if key = "rev" then key = "rewind"
    if key = "fwd" then key = "fastforward"
    if not press
        direction = 0
        if key = "rewind" then direction = -1
        if key = "fastforward" then direction = 1
        if state["phase"] <> "scan" or direction <> state["direction"] then return false
        state["phase"] = "scrub"
        state["scanAtMs"] = -1
        state["scanRate"] = 0
        state["commitAtMs"] = nowMs + 480
        return true
    end if
    if key = "back"
        if state["overlay"] <> "none"
            effects.Push({kind:"dismiss",attemptId:state["attemptId"],overlay:state["overlay"]})
            state["overlay"] = "none"
        else if state["phase"] = "scrub" or state["phase"] = "scan"
            TpDropCursor(state)
            TpBar(state,nowMs)
        else if state["phase"] <> "hidden"
            state["phase"] = "hidden"
            state["hideAtMs"] = -1
        else
            effects.Push({kind:"exit",attemptId:state["attemptId"]})
        end if
        return true
    end if
    if state["overlay"] <> "none" or not state["ready"] then return false
    if key = "play" or key = "pause" or key = "playpause"
        TpToggle(state,effects,nowMs)
    else if key = "ok"
        if state["phase"] = "hidden"
            TpBar(state,nowMs)
        else if state["phase"] = "scrub" or state["phase"] = "scan"
            TpCommit(state,effects,nowMs)
        else if state["phase"] = "buttons"
            action = state["buttons"][state["buttonIndex"]]
            if action = "play_pause"
                TpToggle(state,effects,nowMs)
            else
                effects.Push({kind:"action",attemptId:state["attemptId"],action:action})
            end if
        else
            TpToggle(state,effects,nowMs)
        end if
    else if key = "down"
        TpDropCursor(state)
        state["phase"] = "buttons"
    else if key = "up"
        if state["phase"] <> "buttons" then return false
        TpBar(state,nowMs)
    else if key = "left" or key = "right" or key = "rewind" or key = "fastforward"
        direction = 1
        if key = "left" or key = "rewind" then direction = -1
        if state["phase"] = "buttons" and (key = "left" or key = "right")
            index = state["buttonIndex"] + direction
            if index < 0 then index = 0
            if index >= state["buttons"].Count() then index = state["buttons"].Count() - 1
            state["buttonIndex"] = index
        else if not state["canSeek"] or state["durationMs"] <= 0
            TpBar(state,nowMs)
        else if key = "rewind" or key = "fastforward"
            TpScan(state,direction,repeated,nowMs)
        else
            TpMoveCursor(state,direction,nowMs)
        end if
    else
        return false
    end if
    return true
end function

sub TpTimer(state as Object, effects as Object, nowMs as Double)
    if state["seekDeadlineMs"] >= 0 and nowMs >= state["seekDeadlineMs"]
        effects.Push({kind:"settle_timeout",attemptId:state["attemptId"],seekId:state["seekId"]})
        state["seekTargetMs"] = -1
        state["seekDeadlineMs"] = -1
        ' This bounds the UI wait only. Slow native landing must retain requested
        ' pause intent and its target; timeout neither proves landing nor pauses.
    end if
    if state["overlay"] = "none"
        if state["phase"] = "scan" and state["scanAtMs"] >= 0 and nowMs >= state["scanAtMs"]
            state["cursorMs"] = TpClamp(state["cursorMs"] + state["direction"] * TpStep(state) * state["scanRate"],state["durationMs"])
            state["scanAtMs"] = nowMs + 200
        else if state["phase"] = "scrub" and state["commitAtMs"] >= 0 and nowMs >= state["commitAtMs"]
            TpCommit(state,effects,nowMs)
        end if
        if state["phase"] = "bar" and state["hideAtMs"] >= 0 and nowMs >= state["hideAtMs"]
            if not state["desiredPaused"] and state["seekTargetMs"] < 0
                state["phase"] = "hidden"
                state["hideAtMs"] = -1
            end if
        end if
    end if
end sub

sub TpSchedule(state as Object, effects as Object, nowMs as Double)
    if state["phase"] <> "bar" or state["nativeState"] <> "playing" or state["desiredPaused"] or state["seekTargetMs"] >= 0 or state["overlay"] <> "none" or state["retired"]
        state["hideAtMs"] = -1
    else if state["hideAtMs"] < 0
        state["hideAtMs"] = nowMs + 3000
    end if
    due = state["seekDeadlineMs"]
    if state["overlay"] = "none"
        for each deadline in [state["commitAtMs"],state["scanAtMs"],state["hideAtMs"]]
            if deadline >= 0
                if due < 0 or deadline < due then due = deadline
            end if
        end for
    end if
    if due <> state["timerAtMs"]
        state["timerAtMs"] = due
        state["timerToken"]++
        ' atMs=-1 explicitly cancels the coordinator's sole transport timer.
        effects.Push({kind:"timer",attemptId:state["attemptId"],token:state["timerToken"],atMs:due})
    end if
end sub

function TransportProjection(state as Object) as Object
    if state["phase"] = "hidden" then return {visible:false}
    focus = "bar"
    if state["phase"] = "buttons" then focus = "buttons"
    return {visible:true,phase:state["phase"],focus:focus,overlay:state["overlay"],
        positionMs:state["positionMs"],durationMs:state["durationMs"],cursorMs:state["cursorMs"],
        buttonIndex:state["buttonIndex"],buttonId:state["buttons"][state["buttonIndex"]],
        paused:state["desiredPaused"],ready:state["ready"],settling:state["seekTargetMs"] >= 0}
end function

' key: key/press/repeat; native: compact NativePlayer status; tick: timer token;
' overlay: none/popover/info; cancel: discard cursor; retire: end this attempt.
' Effects execute only through the existing single NativePlayer owner. No effect
' from this policy sends provider work, stores progress, or replaces Video content.
function TransportReduce(previous as Dynamic, event as Dynamic) as Object
    result = {state:previous,effects:[],accepted:false,render:invalid}
    if type(previous) <> "roAssociativeArray" or type(event) <> "roAssociativeArray" then return result
    if previous.retired then return result
    if TpField(event,"attemptId",invalid) <> previous.attemptId then return result
    kind = TpField(event,"kind",invalid)
    nowMs = TpField(event,"nowMs",invalid)
    if not TpString(kind) or not TpNumber(nowMs) then return result
    if nowMs < previous.nowMs or nowMs < 0 then return result
    state = TpCopy(previous)
    effects = result.effects
    accepted = false
    if kind = "native"
        accepted = TpNative(state,TpField(event,"status",invalid),effects,nowMs)
    else if kind = "seek_to"
        target = TpField(event,"positionMs",invalid)
        if not TpNumber(target) then return result
        if target < 0 or target > state.durationMs or state.durationMs<=0 then return result
        if not state.ready or not state.canSeek or state.overlay<>"none" or state.seekTargetMs>=0 or state.cursorMs>=0 then return result
        if state.controlPending<>"" or state.rePausePending then return result
        fence = TpField(event,"markerFence",invalid)
        if type(fence)<>"roAssociativeArray" then return result
        version = TpField(fence,"versionId",invalid)
        clip = TpField(fence,"clipId",invalid)
        epoch = TpField(fence,"renderedEpoch",invalid)
        if not TpString(version) or not TpNumber(clip) or not TpNumber(epoch) then return result
        if Len(version)=0 or Len(version)>256 or Instr(1,version,"://")>0 then return result
        for index = 1 to Len(version)
            code = Asc(Mid(version,index,1))
            if code<32 or code=127 then return result
        end for
        if clip<>state.clipId or clip<0 or clip>2147483647 or clip<>Int(clip) then return result
        if epoch<>0 then return result
        state.cursorMs = target
        TpCommit(state,effects,nowMs)
        for each effect in effects
            if effect.kind="command" and effect.command.action="seek" then effect.command["markerFence"] = {versionId:version,clipId:clip,renderedEpoch:epoch}
        end for
        accepted = true
    else if kind = "key"
        accepted = TpKey(state,event,effects,nowMs)
    else if kind = "tick"
        token = TpField(event,"token",invalid)
        if not TpNumber(token) then return result
        if token <> state["timerToken"] or state["timerAtMs"] < 0 or nowMs < state["timerAtMs"] then return result
        TpTimer(state,effects,nowMs)
        accepted = true
    else if kind = "cancel"
        if state["cursorMs"] < 0 then return result
        TpDropCursor(state)
        TpBar(state,nowMs)
        accepted = true
    else if kind = "retire"
        TpRetire(state)
        accepted = true
    else if kind = "overlay"
        overlay = TpField(event,"overlay",invalid)
        if not TpString(overlay) then return result
        if overlay <> "none" and overlay <> "popover" and overlay <> "info" then return result
        state["overlay"] = overlay
        accepted = true
    end if
    if not accepted then return result
    state["nowMs"] = nowMs
    TpSchedule(state,effects,nowMs)
    result.state = state
    result.accepted = true
    ' Hidden native clocks still update state; renderer nodes receive no writes.
    if state["phase"] <> "hidden" or previous.phase <> "hidden" then result.render = TransportProjection(state)
    return result
end function
