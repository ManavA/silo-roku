sub init()
    m.video = m.top.FindNode("video")
    m.label = m.top.FindNode("status")
    m.phase = 0
    m.playClock = CreateObject("roTimespan")
    m.seekClock = CreateObject("roTimespan")
    m.seekClock.Mark()
    m.autoTimer = CreateObject("roSGNode","Timer")
    m.autoTimer.duration = 0.25
    m.autoTimer.repeat = true
    m.autoTimer.ObserveField("fire","onTick")
    m.video.ObserveField("state","onState")
    m.video.ObserveField("audioFormat","onNativeFormats")
    m.video.ObserveField("videoFormat","onNativeFormats")
    m.task = CreateObject("roSGNode","LocalHttpTask")
    m.task.ObserveField("ready","onReady")
    m.task.ObserveField("failed","onServerFailed")
    m.task.ObserveField("seekOffer","onSeekOffer")
    m.taskStarted=false
    config=ParseJson(ReadAsciiFile("pkg:/images/config.json"))
    m.stockRuntime=false
    if config<>invalid then m.stockRuntime=config.stockRuntime=true
    QaSeekSceneInit(config)
    if m.seekScene.enabled
        if m.video.HasField("bufferingStatus") then m.video.ObserveField("bufferingStatus","onSeekBuffer")
        if m.video.HasField("streamingSegment") then m.video.ObserveField("streamingSegment","onSeekSegment")
    end if
    if m.stockRuntime
        m.top.ObserveField("stockContext","onStockContext")
        m.label.text="Waiting for in-memory owned stock session"
        onStockContext()
    else
        m.taskStarted=true
        m.task.control="RUN"
    end if
    m.top.SetFocus(true)
end sub
sub onStockContext()
    context=m.top.stockContext
    if context=invalid then return
    ' Release the Scene's staging reference. Task receives its own field copy.
    m.top.stockContext=invalid
    if not m.stockRuntime or m.taskStarted then return
    if not QaStockContextValid(context) then return
    if Type(context.playlist)<>"roString" and Type(context.playlist)<>"String" then return
    if QaStockMediaReference(context.playlist,context.playlist,context.origin,context.routeItemId,context.mediaSourceId,context.sessionId)=invalid then return
    m.task.stockContext=context
    m.taskStarted=true
    m.task.control="RUN"
end sub
sub onReady()
    if m.task.ready
        if m.seekScene.enabled and m.seekScene.stage<>"idle" then return
        playPhase(1)
        m.autoTimer.control = "start"
        QaSeekSceneReady()
    end if
end sub
sub onSeekOffer()
    QaSeekSceneOffer(m.task.seekOffer)
end sub
sub onSeekBuffer()
    QaSeekSceneBuffer(m.video.bufferingStatus)
end sub
sub onSeekSegment()
    QaSeekSceneSegment(m.video.streamingSegment)
end sub
sub onServerFailed()
    if m.task.failed
        if m.seekScene.enabled and m.seekScene.stage<>"idle" then QaSeekSceneFail(7):return
        m.label.text = "Probe setup failed; inspect numerical QA logs"
    end if
end sub
sub playPhase(phase as Integer)
    m.phase = phase
    m.stage = 0
    m.pauseAt = 0
    m.seekTarget = 0
    m.seekGeneration = 0
    m.lastSeekMs = -10000
    m.playClock.Mark()
    m.firstPlaying = true
    m.previousClock = invalid
    m.avCount = 0
    m.avSum = 0#
    m.avMin = 0#
    m.avMax = 0#
    m.video.control = "stop"
    content = CreateObject("roSGNode","ContentNode")
    content.streamFormat = "hls"
    content.url = "http://127.0.0.1:34831/g1/master.m3u8"
    content.title = "Generated multi-fragment probe"
    m.video.content = content
    m.video.control = "play"
    print "qa_play phase="; phase; " wall_ms="; m.playClock.TotalMilliseconds()
end sub
sub onState()
    state = m.video.state
    QaSeekSceneState(state)
    if state = "playing" or state = "buffering" or state = "paused" or state = "finished" or state = "error" or state = "stopped"
        print "qa_video phase="; m.phase; " state="; state; " position="; m.video.position; " wall_ms="; m.playClock.TotalMilliseconds()
        m.label.text = "Case "+m.phase.ToStr()+": "+state+" | Multi-fragment on-Roku EAC3 | Automatic controls in case2"
    end if
    if state = "playing"
        if m.firstPlaying
            print "qa_startup phase="; m.phase; " elapsed_ms="; m.playClock.TotalMilliseconds()
            m.firstPlaying = false
        end if
        onNativeFormats()
    end if
    if state = "error" then print "qa_error phase="; m.phase; " code="; m.video.errorCode
    if state = "finished"
        if m.seekScene.enabled and m.seekScene.stage<>"idle"
            if m.seekScene.stage="waiting_offer" or m.seekScene.stage="await_active" then QaSeekSceneFail(6)
            if m.seekScene.stage="running" or m.seekScene.stage="failed" or m.seekScene.stage="cancelled" then m.autoTimer.control="stop"
            return
        end if
        average = 0#
        if m.avCount > 0 then average = m.avSum/m.avCount
        print "qa_av_summary phase="; m.phase; " count="; m.avCount; " min_ms="; m.avMin; " max_ms="; m.avMax; " mean_ms="; average
        print "qa_case_done phase="; m.phase; " stage="; m.stage; " position="; m.video.position
        if m.task.rollingMode
            m.autoTimer.control = "stop"
        else if m.phase = 1
            playPhase(2)
        else
            m.autoTimer.control = "stop"
        end if
    end if
end sub
sub onTick()
    QaSeekSceneTick()
    if m.seekScene.enabled and m.seekScene.stage="failed" then return
    if m.seekScene.enabled and m.seekScene.playbackEpoch>1 then return
    state = m.video.state
    position = m.video.position
    if m.task.rollingMode and (not m.seekScene.enabled or m.seekScene.playbackEpoch=1) then m.task.playbackPosition=position
    elapsed = m.playClock.TotalMilliseconds()
    snapshot = m.video.positionInfo
    clock = QaRenderedClock(snapshot,m.previousClock,state)
    if clock.ok
        steady = clock.eligible and elapsed-m.lastSeekMs > 1000 and not m.firstPlaying
        print "qa_av phase="; m.phase; " wall_ms="; elapsed; " seek_gen="; m.seekGeneration; " valid=1 stale="; clock.stale; " steady="; steady; " audio_ms="; clock.audioSeconds*1000#; " video_ms="; clock.videoSeconds*1000#; " delta_ms="; clock.deltaMs; " epoch="; clock.epoch
        if steady
            if m.avCount = 0 or clock.deltaMs < m.avMin then m.avMin = clock.deltaMs
            if m.avCount = 0 or clock.deltaMs > m.avMax then m.avMax = clock.deltaMs
            m.avCount += 1
            m.avSum += clock.deltaMs
        end if
    else
        print "qa_av phase="; m.phase; " wall_ms="; elapsed; " seek_gen="; m.seekGeneration; " valid=0"
    end if
    m.previousClock = clock
    if m.task.rollingMode then return
    if m.phase <> 2 then return
    if m.stage = 0 and state = "playing" and position >= 8
        m.stage = 1
        m.pauseAt = elapsed
        m.video.control = "pause"
        print "qa_control event=1 position="; position; " wall_ms="; elapsed
    else if m.stage = 1 and elapsed-m.pauseAt >= 2000
        m.stage = 2
        m.video.control = "resume"
        print "qa_control event=2 paused_ms="; elapsed-m.pauseAt; " position="; position
    else if m.stage = 2 and state = "playing" and position >= 12
        m.seekTarget = position+15
        m.seekGeneration += 1
        m.lastSeekMs = elapsed
        m.stage = 3
        m.video.seek = m.seekTarget
        print "qa_control event=3 from="; position; " target="; m.seekTarget
    else if m.stage = 3 and state = "playing" and position >= m.seekTarget-1
        m.stage = 4
        print "qa_control event=4 position="; position; " target="; m.seekTarget; " elapsed_ms="; elapsed-m.lastSeekMs
    else if m.stage = 4 and state = "playing" and position >= m.seekTarget+3
        m.seekTarget = position-5
        m.seekGeneration += 1
        m.lastSeekMs = elapsed
        m.stage = 5
        m.video.seek = m.seekTarget
        print "qa_control event=5 from="; position; " target="; m.seekTarget
    else if m.stage = 5 and state = "playing" and position <= m.seekTarget+1 and position >= m.seekTarget-1
        m.stage = 6
        print "qa_control event=6 position="; position; " target="; m.seekTarget; " elapsed_ms="; elapsed-m.lastSeekMs
    end if
end sub
function onKeyEvent(key as String, press as Boolean) as Boolean
    if not press then return false
    if m.seekScene.enabled and m.seekScene.stage<>"idle" and key<>"up" and key<>"back" then return true
    if m.task.rollingMode and (key="rewind" or key="fastforward" or key="left" or key="right") then return true
    if key = "rewind"
        playPhase(1)
        m.autoTimer.control = "start"
    else if key = "fastforward"
        playPhase(2)
        m.autoTimer.control = "start"
    else if key = "OK" or key = "play"
        if m.video.state = "playing"
            m.video.control = "pause"
        else if m.video.state = "paused"
            m.video.control = "resume"
        end if
    else if key = "up"
        QaSeekSceneCancel()
        m.autoTimer.control = "stop"
        m.video.control = "stop"
        m.task.stopRequested = true
        print "qa_cancel requested=1 phase="; m.phase; " stage="; m.stage
    else if key = "back"
        QaSeekSceneCancel()
        m.autoTimer.control = "stop"
        m.video.control = "stop"
        m.task.stopRequested = true
        return false
    else
        return false
    end if
    return true
end function
sub onNativeFormats()
    audio = 0
    if m.video.audioFormat = "aac" then audio = 1
    if m.video.audioFormat = "ac3" then audio = 2
    if m.video.audioFormat = "eac3" then audio = 3
    if m.video.audioFormat = "none" then audio = 4
    video = 0
    if m.video.videoFormat = "hevc" then video = 1
    if m.video.videoFormat = "h264" or m.video.videoFormat = "mpeg4_10" then video = 2
    if m.video.videoFormat = "none" then video = 3
    print "qa_formats phase="; m.phase; " audio="; audio; " video="; video
end sub
