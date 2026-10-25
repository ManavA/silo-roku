' Keep focus on Video so native trick play remains available.
sub DiagnosticsInit()
    m.nativeHdrMode = invalid
    m.nativeVideoSize = invalid
    m.top.findNode("video").observeField("streamingSegment", "onPlayerSegment")
    m.diagnostics = m.top.findNode("playerDiagnostics")
    m.diagnosticsText = m.top.findNode("playerDiagnosticsText")
    m.diagnosticsTimer = m.top.findNode("diagnosticsTimer")
    m.diagnosticsTimer.observeField("fire", "onDiagnosticsTimer")
end sub

sub DiagnosticsClose()
    if m.diagnostics = invalid then return
    m.diagnostics.visible = false
    m.diagnosticsTimer.control = "stop"
    m.diagnosticsText.text = ""
    m.diagnosticsOutputMode = invalid
end sub

sub DiagnosticsToggle()
    if m.diagnostics = invalid then return
    if m.diagnostics.visible
        DiagnosticsClose()
        return
    end if
    if m.view <> "player" or m.playPlan = invalid then return
    m.diagnosticsOutputMode = PlayerVideoMode()
    m.diagnostics.visible = true
    onDiagnosticsTimer()
    m.diagnosticsTimer.control = "start"
end sub

sub onDiagnosticsTimer()
    if m.diagnostics = invalid then return
    if not m.diagnostics.visible then return
    if m.view <> "player" or m.playPlan = invalid
        DiagnosticsClose()
        return
    end if
    stats = {outputMode:m.diagnosticsOutputMode, state:m.video.state, videoFormat:m.video.videoFormat, audioFormat:m.video.audioFormat, position:m.video.position, duration:m.video.duration}
    ' Extract numeric keys only; streamInfo also contains a private streamUrl.
    stream = m.video.streamInfo
    if type(stream) = "roAssociativeArray" then stats.bitrate = stream.streamBitrate
    segment = m.video.streamingSegment
    m.nativeHdrMode = SiloUIDiagnosticsSegmentHDR(m.nativeHdrMode,segment)
    m.nativeVideoSize = SiloUIDiagnosticsSegmentSize(m.nativeVideoSize,segment)
    stats.videoSize = m.nativeVideoSize
    stats.hdrMode = m.nativeHdrMode
    buffering = m.video.bufferingStatus
    if type(buffering) = "roAssociativeArray" then stats.buffering = buffering.percentage
    source = {streamFormat:m.playPlan.streamFormat,originalPlayback:m.playPlan.originalPlayback}
    if m.originalPlayback <> invalid then source.mappingPhase = m.originalPlayback.phase
    if type(m.playPlan.playbackDiagnostics) = "roAssociativeArray"
        source.delivery = m.playPlan.playbackDiagnostics.delivery
        source.recipeRange = m.playPlan.playbackDiagnostics.recipeRange
    end if
    if type(m.playVersions) = "roArray"
        for each version in m.playVersions
            if version.versionId = m.playPlan.versionId and type(version.videoTracks) = "roArray"
                if version.videoTracks.Count() = 1 then source.sourceVideo = version.videoTracks[0]
            end if
        end for
    end if
    m.diagnosticsText.text = SiloUIDiagnosticsText(stats, source)
end sub

sub onPlayerSegment()
    if m.view <> "player" or m.playPlan = invalid then return
    m.nativeHdrMode = SiloUIDiagnosticsSegmentHDR(m.nativeHdrMode,m.video.streamingSegment)
    m.nativeVideoSize = SiloUIDiagnosticsSegmentSize(m.nativeVideoSize,m.video.streamingSegment)
end sub
