' An explicit source audio choice uses server identity, never native Video Track.
' Official v2 audio has no index field: its complete array defines V3 ordinals.
' Legacy explicit-index inventories retain their separate convention; mixed rows refuse.
function SiloUserAudioSelection(current as Object, detail as Object, wire as Dynamic, index as Dynamic) as Dynamic
    if not SpNumber(index,4095,true) or type(wire) <> "roAssociativeArray" then return invalid
    if SpField(wire,"content_id") <> current.itemId then return invalid
    versions = SpField(wire,"versions")
    if type(versions) <> "roArray" then return invalid
    if versions.Count() > 16 then return invalid
    foundFile = invalid
    for each version in versions
        if SpField(version,"file_id") = current.fileId
            if foundFile <> invalid then return invalid
            foundFile = version
        end if
    end for
    tracks = SpField(foundFile,"audio_tracks")
    if type(tracks) <> "roArray" then return invalid
    if tracks.Count() > 32 then return invalid
    foundTrack = invalid:ordinal = 0:wireIndexed = 0
    for each track in tracks
        if type(track) <> "roAssociativeArray" then return invalid
        if track.DoesExist("index") then wireIndexed++
    end for
    if wireIndexed <> 0 and wireIndexed <> tracks.Count() then return invalid
    for each track in tracks
        trackIndex = ordinal
        if wireIndexed > 0 then trackIndex = SpField(track,"index")
        if not SpNumber(trackIndex,4095,true) then return invalid
        if trackIndex = index
            if foundTrack <> invalid then return invalid
            foundTrack = track
        end if
        ordinal++
    end for
    if foundTrack = invalid then return invalid
    file = SiloPlaybackFile(detail,current.sourceId,current.itemId,current.fileId,0)
    if file = invalid then return invalid
    for each track in SpField(file.version,"audioTracks",[])
        if SpField(track,"index") = index and SpField(track,"id") = Int(index).ToStr()
            if SpField(track,"codec") = SpField(foundTrack,"codec") and SpField(track,"channels") = SpField(foundTrack,"channels") then return track
        end if
    end for
    return invalid
end function

' A stopped-content replacement preserves every server decision outside the
' explicit subtitle pair. Contexts are bounded primitive projections.
function SiloUISubtitleChangePlan(captured as Dynamic, currentPlan as Dynamic, returned as Dynamic, scope as Object, pair as Dynamic) as Boolean
    current = SiloPlaybackContext(currentPlan,scope)
    accepted = SiloPlaybackContext(returned,scope)
    if current = invalid or accepted = invalid or type(captured) <> "roAssociativeArray" then return false
    if FormatJson(current) <> FormatJson(captured) then return false
    for each field in ["sourceId","profileId","sessionRevision","itemId","fileId","installationId","sessionId","playbackAttemptId","planAttemptId","qualityPreference","bandwidthCapKbps","mediaAuthMode"]
        if SpField(accepted,field) <> SpField(captured,field) then return false
    end for
    if returned.planId <> accepted.planId or accepted.planId = captured.planId or accepted.planAttemptKey = captured.planAttemptKey then return false
    if FormatJson(SpField(accepted.selectedTracks,"audio")) <> FormatJson(SpField(captured.selectedTracks,"audio")) then return false
    if pair = invalid
        if returned.subtitleMode <> "off" or accepted.selectedTracks.DoesExist("subtitle") then return false
        selected = SpField(returned,"selectedSubtitle")
        if selected <> invalid
            if SpField(selected,"kind") <> "off" or SpField(selected,"mode") <> "off" or SpField(selected,"renderingReady") <> false then return false
            if SpField(selected,"trackId","") <> "" then return false
        end if
        if returned.DoesExist("subtitleArtifact") or returned.DoesExist("subtitleTransport") then return false
        return true
    end if
    if SiloUserSubtitleSelection(returned,scope,pair.id,pair.index) = invalid then return false
    selectedPair = SpField(accepted.selectedTracks,"subtitle")
    if SpField(selectedPair,"id") <> pair.id or SpField(selectedPair,"index") <> pair.index then return false
    if SpField(accepted,"subtitleOffRequired",false) <> false then return false
    selected = SpField(returned,"selectedSubtitle")
    if SpField(selected,"trackId") <> pair.id or SpField(selected,"combinedIndex") <> pair.index then return false
    if SpField(selected,"mode") <> returned.subtitleMode then return false
    kind = SpField(selected,"kind")
    if kind = "burn_in"
        if returned.subtitleMode <> "burn_in" then return false
    else if kind = "embedded_render"
        ' Stream indexes have no qualified mapping to Roku native Track IDs.
        return false
    else if kind = "sidecar_ready" or kind = "sidecar_pending" or kind = "fetch_failed"
        if returned.subtitleMode <> "render" and returned.subtitleMode <> "convert" then return false
    else
        return false
    end if
    if not SpBool(SpField(selected,"renderingReady")) then return false
    if kind = "sidecar_ready" then return selected.renderingReady = true
    if selected.renderingReady <> false then return false
    if kind <> "sidecar_pending"
        if returned.DoesExist("subtitleArtifact") or returned.DoesExist("subtitleTransport") then return false
    end if
    return true
end function

' A refused decision can still advance the server's stop/progress authority.
' Rebuild a bounded plan under the captured scope before adopting that receipt.
function SiloUISubtitleChangeControlPlan(attempt as Object, receipt as Dynamic) as Dynamic
    if type(receipt) <> "roAssociativeArray" then return invalid
    candidate = ParseJson(FormatJson(attempt.plan))
    candidate["siloPlayback"] = receipt
    candidate["planId"] = SpField(receipt,"planId")
    candidate["planAttemptKey"] = SpField(receipt,"planAttemptKey")
    context = SiloPlaybackContext(candidate,attempt.owner)
    if context = invalid then return invalid
    for each field in ["sourceId","profileId","sessionRevision","itemId","fileId","installationId","sessionId","playbackAttemptId","planAttemptId","qualityPreference","bandwidthCapKbps","mediaAuthMode"]
        if SpField(context,field) <> SpField(attempt.context,field) then return invalid
    end for
    candidate["siloPlayback"] = context
    candidate["cleanupOwner"] = attempt.owner
    return candidate
end function
