' Native Video controls retain time-only seeking when previews are unavailable.
sub TransportInit()
    m.transport = m.top.findNode("playerTransport")
    m.transport.observeField("visible","onTransportVisibility")
    m.transportTitle = m.top.findNode("transportTitle")
    m.transportTime = m.top.findNode("transportTime")
    m.transportHint = m.top.findNode("transportHint")
    m.transportActions = m.top.findNode("transportActions")
    BuildPills(m.transportActions,"transportActions",["Pause / Play","Audio & subtitles","Chapters","Native controls"],12,38,18)
    m.transportProgress = m.top.findNode("transportProgress")
    m.chapterList = m.top.findNode("playerChapterList")
    m.chapterList.observeField("itemSelected", "onTransportChapter")
    m.transportTimer = m.top.findNode("transportTimer")
    m.transportTimer.observeField("fire", "onTransportTimer")
    TransportTrickplayInit()
    TransportReset()
end sub

sub TransportReset()
    TransportTrickplayClear()
    if m.transport = invalid then return
    m.transport.visible = false
    m.top.findNode("playerChapters").visible = false
    m.chapterOpen = false
    m.transportPreviewMs = invalid
    m.transportIndex = 0
    m.transportRepeats = 0
    m.transportIdle = 0
    m.skipUndoMs = invalid
    m.skipUndoTicks = 0
    m.transportSkipped = []
    m.transportTimer.control = "stop"
end sub

sub TransportStart()
    if m.transport = invalid then return
    TransportReset()
    m.transportEnabled = m.memoryHigh <> true
    if m.playPlan.transport = "silo_compat" then m.transportEnabled = true
    TransportNativeUi(not m.transportEnabled)
    m.transportOffsetMs = NumberOr(m.playPlan.timelineOffsetMs, 0)
    m.playChapters = []
    versions = m.playVersions
    request = m.playPlan.autoVersionRequest
    if type(request) = "roAssociativeArray"
        if type(request.detail) = "roAssociativeArray" then versions = request.detail.versions
    end if
    if type(versions) = "roArray"
        for each version in versions
            if version.versionId = m.playPlan.versionId then m.playChapters = SiloUITransportChapters(version.chapters, TransportDuration())
        end for
    end if
    m.transportTimer.control = "start"
end sub

function TransportDuration() as Double
    if m.playPlan <> invalid
        if m.playPlan.transport = "silo_compat" then return SiloUICompatDuration()
    end if
    return PlayerTimelineDurationMs()
end function

function TransportKey(key as String) as Boolean
    if m.transportEnabled <> true or m.transport = invalid then return false
    if m.chapterOpen = true
        if key = "back"
            m.top.findNode("playerChapters").visible = false
            m.chapterOpen = false
            PlayerPlaybackFocus()
            return true
        end if
        return false
    end if
    if key = "back"
        if m.transportPreviewMs <> invalid
            m.transportPreviewMs = invalid
            TransportPaint()
            return true
        end if
        if m.skipUndoMs <> invalid and m.skipUndoTicks > 0
            if PlayerSeekTo(m.skipUndoMs)
                if m.seekReanchor <> invalid
                    m.seekReanchor.marker = {kind:"undo"}
                else
                    m.skipUndoMs = invalid:m.skipUndoTicks = 0:m.introDismissed = true
                    Toast("Skip undone.")
                end if
            end if
            return true
        end if
        if m.transport.visible then m.transport.visible = false : return true
        return false
    end if
    if key = "OK" and m.transportPreviewMs <> invalid
        if not PlayerSeekTo(m.transportPreviewMs) then Toast("Seeking is unavailable for this stream.")
        m.transportPreviewMs = invalid
        m.transportRepeats = 0
        m.transportIdle = 0
        TransportPaint()
        return true
    end if
    if key = "rewind" or key = "fastforward"
        position = m.transportPreviewMs
        if position = invalid then position = PlayerPositionMs()
        if m.transportLastDirection <> key then m.transportRepeats = 0
        m.transportLastDirection = key
        m.transportRepeats = m.transportRepeats + 1
        delta = 10000
        if key = "rewind" then delta = -delta
        m.transportPreviewMs = SiloUITransportSeek(position, TransportDuration(), PlayerSeekOriginMs(), delta, m.transportRepeats)
        m.transport.visible = true
        m.transportIdle = 0
        TransportPaint()
        return true
    end if
    if key = "play"
        TransportTogglePause()
        return true
    end if
    if key = "down"
        m.transport.visible = true
        m.transportIdle = 0
        TransportPaint()
        return true
    end if
    if not m.transport.visible
        if key = "OK" then m.transport.visible = true : m.transportIdle = 0 : TransportPaint() : return true
        return false
    end if
    if key = "left" or key = "right"
        delta = 1
        if key = "left" then delta = -1
        m.transportIndex = (m.transportIndex + delta + 4) mod 4
        m.transportIdle = 0
        TransportPaint()
        return true
    end if
    if key = "OK"
        if m.transportIndex = 0 then TransportTogglePause()
        if m.transportIndex = 1 then m.transport.visible = false : PlayerShowTracks()
        if m.transportIndex = 2 then TransportShowChapters()
        if m.transportIndex = 3
            if m.playPlan <> invalid
                if m.playPlan.transport = "silo_compat" then Toast("Use these playback controls for this stream.") : return true
            end if
            TransportReset()
            m.transportEnabled = false
            TransportNativeUi(true)
            PlayerPlaybackFocus()
            if m.video.enableUI then Toast("Native controls enabled for this playback.")
        end if
        return true
    end if
    return false
end function

sub TransportTogglePause()
    if m.video.state = "playing"
        m.video.control = "pause"
    else if m.video.state = "paused"
        m.video.control = "resume"
    end if
    m.transport.visible = true
    m.transportIdle = 0
    TransportPaint()
end sub

sub TransportPaint()
    TransportTrickplayUpdate()
    if m.transport = invalid or not m.transport.visible then return
    position = PlayerPositionMs()
    if m.transportPreviewMs <> invalid then position = m.transportPreviewMs
    duration = TransportDuration()
    m.playerCue.visible = false
    m.transportTitle.text = Left(TextOr(m.playItem.title), 90)
    m.transportTime.text = SiloUITransportTime(position) + " / " + SiloUITransportTime(duration)
    m.transportProgress.width = 0
    if duration > 0
        width = Int(1080 * position / duration)
        if width < 0 then width = 0
        if width > 1080 then width = 1080
        m.transportProgress.width = width
    end if
    preview = m.transportPreviewMs <> invalid
    m.transportHint.visible = preview
    m.transportActions.visible = not preview
    m.transportHint.text = "Preview · OK to seek · Back to cancel"
    row = m.pillGroups.transportActions
    row.index = m.transportIndex
    row.pills[0].label.text = "Pause"
    if m.video.state = "paused" then row.pills[0].label.text = "Play"
    PaintPills("transportActions",true)
    TransportPaintActions(row)
end sub

' Transport buttons stay legible over video, independently of page pill colors.
sub TransportPaintActions(row as Object)
    for index = 0 to row.pills.Count()-1
        pill = row.pills[index]
        pill.bg.blendColor = "0xFFFFFFFF"
        if index = row.index
            pill.bg.uri = "pkg:/images/ui/transport_button_focus.9.png"
            pill.label.color = "0x09111FFF"
        else
            pill.bg.uri = "pkg:/images/ui/transport_button.9.png"
            pill.label.color = "0xF3F6FBFF"
        end if
    end for
end sub

sub onTransportTimer()
    if m.seekReanchor <> invalid then return
    if m.view <> "player" or m.transportEnabled <> true then return
    if m.skipUndoTicks > 0 then m.skipUndoTicks--
    if m.skipUndoTicks = 0 then m.skipUndoMs = invalid
    if m.transport.visible
        m.transportIdle++
        if m.transportIdle >= 6 and m.transportPreviewMs = invalid and m.video.state = "playing" then m.transport.visible = false
        TransportPaint()
    end if
end sub

sub TransportShowChapters()
    chapters = m.playChapters
    if type(chapters) <> "roArray" or chapters.Count() = 0 then Toast("No chapters available for this version.") : return
    root = CreateObject("roSGNode", "ContentNode")
    for each chapter in chapters
        if chapter.positionMs >= PlayerSeekOriginMs()
            node = root.createChild("ContentNode")
            node.title = SiloUITransportTime(chapter.positionMs) + " · " + chapter.title
            node.addFields({positionMs:chapter.positionMs})
        end if
    end for
    if root.getChildCount() = 0 then Toast("No chapters available in this stream.") : return
    m.chapterList.content = root
    m.chapterList.jumpToItem = 0
    m.transport.visible = false
    m.top.findNode("playerChapters").visible = true
    m.chapterOpen = true
    m.chapterList.setFocus(true)
end sub

sub onTransportChapter()
    if m.view <> "player" or m.chapterOpen <> true then return
    index = m.chapterList.itemSelected
    node = m.chapterList.content.getChild(index)
    if node = invalid then return
    ignored = PlayerSeekTo(node.positionMs)
    m.top.findNode("playerChapters").visible = false
    m.chapterOpen = false
    PlayerPlaybackFocus()
end sub

sub TransportSkip(endMs as Double, automatic = false as Boolean)
    position = PlayerPositionMs()
    duration = TransportDuration()
    if duration > 0 and endMs >= duration then endMs = duration - 1000
    if endMs <= position or endMs < m.transportOffsetMs then return
    if not PlayerSeekTo(endMs) then return
    marker = {kind:"skip",fromMs:position,endMs:endMs,automatic:automatic}
    if m.seekReanchor <> invalid
        m.seekReanchor.marker = marker
        Toast("Seeking…")
        return
    end if
    TransportSeekAcknowledged({marker:marker})
end sub

sub TransportAutoSkip()
    if m.seekReanchor <> invalid then return
    if m.transportEnabled <> true or m.video.state <> "playing" or m.skipUndoMs <> invalid then return
    if type(m.playMarkers) <> "roArray" or type(m.preferences) <> "roAssociativeArray" then return
    position = PlayerPositionMs()
    for each marker in m.playMarkers
        enabled = false
        if marker.kind = "intro"
            enabled = m.preferences.autoSkipIntro = true
            if m.preferences.introSkipMode = "never" or m.preferences.introSkipMode = "ask" then enabled = false
            if m.preferences.introSkipMode = "always" then enabled = true
        end if
        if marker.kind = "recap" then enabled = m.preferences.autoSkipRecap = true
        if marker.kind = "credits" then enabled = m.preferences.autoSkipCredits = true
        if enabled and position >= marker.startMs and position < marker.endMs
            seen = false
            for each finish in m.transportSkipped
                if finish = marker.endMs then seen = true
            end for
            if not seen
                TransportSkip(marker.endMs,true)
                return
            end if
        end if
    end for
end sub

' OS15.3+ can reserve an explicit caption area above custom controls. Older
' firmware keeps native controls when captions need the platform's layout.
sub onTransportVisibility()
    if m.transport <> invalid
        if not m.transport.visible then TransportTrickplayClear()
    end if
    if m.video = invalid or m.transport = invalid then return
    if m.playPlan <> invalid
        if m.playPlan.transport = "silo_compat"
            m.video.enableUI = false:m.video.globalCaptionMode = "Off"
            return
        end if
    end if
    if m.video.hasField("captionRenderArea")
        area = {mode:"fullscreen"}
        if m.transport.visible and m.transportEnabled = true then area = {mode:"override",overridePlacement:true,scaleFonts:"off",keepSafeMargins:true,x:0,y:0,width:1280,height:500}
        m.video.captionRenderArea = area
    else if m.transport.visible and m.transportEnabled = true
        if m.video.globalCaptionMode <> "Off"
            TransportReset()
            m.transportEnabled = false
            TransportNativeUi(true)
            PlayerPlaybackFocus()
            if m.video.enableUI then Toast("Native controls enabled to preserve caption placement.")
        end if
    end if
end sub


' enableTrickPlay only fences firmware trickplay while native UI is enabled.
' If unavailable, keep a lightweight peer-focused custom control surface.
sub TransportNativeUi(enabled as Boolean)
    restricted = false
    if m.playPlan <> invalid
        restricted = m.playPlan.provider = "silo" and m.playPlan.transport <> "silo_compat" and m.playPlan.canSeekAnywhere <> true
    end if
    if m.video.hasField("enableTrickPlay")
        m.video.enableTrickPlay = not restricted
    else if restricted
        enabled = false
        m.transportEnabled = true
        if m.transport <> invalid then m.transport.visible = false
        if m.nativeSeekLimitShown <> true then Toast("Use these controls to seek this stream.")
        m.nativeSeekLimitShown = true
    end if
    m.video.enableUI = enabled
end sub


sub TransportSeekAcknowledged(attempt as Object)
    marker = attempt.marker
    if marker.kind = "undo"
        m.skipUndoMs = invalid:m.skipUndoTicks = 0:m.introDismissed = true
        Toast("Skip undone.")
    else
        m.skipUndoMs = marker.fromMs:m.skipUndoTicks = 6
        if marker.automatic then m.transportSkipped.Push(marker.endMs)
        m.playerCue.visible = false
        Toast("Skipped · Back to undo")
    end if
end sub
