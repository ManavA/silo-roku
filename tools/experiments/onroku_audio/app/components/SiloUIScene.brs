sub init()
    m.video = m.top.FindNode("video")
    m.label = m.top.FindNode("status")
    m.phase = 0
    m.video.ObserveField("state", "onState")
    m.video.ObserveField("audioFormat", "onNativeFormats")
    m.video.ObserveField("videoFormat", "onNativeFormats")
    m.task = CreateObject("roSGNode", "LocalHttpTask")
    m.task.ObserveField("ready", "onReady")
    m.task.ObserveField("failed", "onServerFailed")
    m.task.control = "RUN"
    m.top.SetFocus(true)
end sub
sub onReady()
    if m.task.ready then playPhase(2)
end sub
sub onServerFailed()
    if m.task.failed then m.label.text = "Probe setup failed; inspect numerical QA logs"
end sub
sub playPhase(phase as Integer)
    m.phase = phase
    m.video.control = "stop"
    content = CreateObject("roSGNode", "ContentNode")
    content.streamFormat = "hls"
    if phase = 1
        content.url = "http://127.0.0.1:34831/master.m3u8"
    else
        content.url = "http://127.0.0.1:34831/master.m3u8"
    end if
    content.title = "Generated transport probe"
    m.video.content = content
    m.video.control = "play"
    print "qa_play phase="; phase
end sub
sub onState()
    state = m.video.state
    if state = "playing" or state = "buffering" or state = "paused" or state = "finished" or state = "error" or state = "stopped"
        print "qa_video phase="; m.phase; " state="; state; " position="; m.video.position
        m.label.text = "Phase " + m.phase.ToStr() + ": " + state + " | On-Roku derived EAC3 | Right: seek 3s | OK: pause/resume"
    end if
    if state = "playing" then onNativeFormats()
    if state = "error"
        print "qa_error phase="; m.phase; " code="; m.video.errorCode
    end if
    if (state = "finished" or state = "error") and m.phase = 1 then playPhase(2)
end sub
function onKeyEvent(key as String, press as Boolean) as Boolean
    if not press then return false
    if key = "rewind"
        playPhase(1)
    else if key = "fastforward"
        playPhase(2)
    else if key = "right"
        m.video.seek = 3
        print "qa_seek phase="; m.phase; " seconds=3"
    else if key = "OK" or key = "play"
        if m.video.state = "playing"
            m.video.control = "pause"
        else if m.video.state = "paused"
            m.video.control = "resume"
        else
            playPhase(2)
        end if
    else if key = "back"
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
