' Timeline values are source milliseconds, including any playback offset.
function SiloUIPlayerCue(markers as Dynamic, positionMs as Double, durationMs as Double, hasNext as Boolean, dismissed as Boolean) as Object
    cue = {introEndMs: 0, upNext: false}
    if type(markers) = "roArray"
        for each marker in markers
            if type(marker) = "roAssociativeArray"
                if marker.startMs <> invalid and marker.endMs <> invalid
                    if positionMs >= marker.startMs and positionMs < marker.endMs
                        if marker.kind = "intro" then cue.introEndMs = marker.endMs
                        if marker.kind = "credits" then cue.upNext = true
                    end if
                end if
            end if
        end for
    end if
    if durationMs > 0 and positionMs >= 0 and durationMs - positionMs < 30000 then cue.upNext = true
    cue.upNext = cue.upNext and hasNext and not dismissed
    return cue
end function

function SiloUIPlayerNext(item as Dynamic, episodes as Dynamic) as Dynamic
    if type(item) <> "roAssociativeArray" or type(episodes) <> "roArray" then return invalid
    if item.type <> "episode" or item.sourceId = invalid or item.sourceId = "" then return invalid
    seriesId = item.seriesId
    if seriesId = invalid or seriesId = "" then seriesId = item.seriesItemId
    if seriesId = invalid or seriesId = "" then return invalid
    if item.seasonNumber = invalid or item.episodeNumber = invalid then return invalid
    selected = invalid
    for each candidate in episodes
        if type(candidate) = "roAssociativeArray"
            candidateSeries = candidate.seriesId
            if candidateSeries = invalid or candidateSeries = "" then candidateSeries = candidate.seriesItemId
            if candidate.type = "episode" and candidate.itemId <> invalid and candidate.itemId <> "" and candidate.sourceId = item.sourceId and candidateSeries = seriesId and candidate.seasonNumber = item.seasonNumber and candidate.episodeNumber = item.episodeNumber + 1
                if selected <> invalid then return invalid
                selected = candidate
            end if
        end if
    end for
    return selected
end function

' Fixed slots retain action identity while disabled buttons are skipped by Roku.
function SiloUIPlayerActions(cue as Object, introDismissed as Boolean) as Object
    return [
        {text:"Audio and subtitles", buttonIsDisabled:false},
        {text:"Skip intro", buttonIsDisabled:cue.introEndMs <= 0 or introDismissed},
        {text:"Next episode", buttonIsDisabled:not cue.upNext}
    ]
end function

' Recheck current applicability rather than trusting the last rendered buttons.
function SiloUIPlayerAction(index as Integer, cue as Object, introDismissed as Boolean, offsetMs as Double) as Dynamic
    buttons = SiloUIPlayerActions(cue, introDismissed)
    if index < 0 or index >= buttons.Count() then return invalid
    if buttons[index].buttonIsDisabled then return invalid
    if index = 0 then return {kind:"tracks"}
    if index = 1
        seconds = (cue.introEndMs - offsetMs) / 1000
        if seconds < 0 then return invalid
        return {kind:"seek", seconds:seconds}
    end if
    return {kind:"next"}
end function

function SiloUIPlayerMarkerResult(data as Dynamic, itemId as String, versionId as String) as Dynamic
    if type(data) <> "roAssociativeArray" or itemId = "" or versionId = "" then return invalid
    if data.itemId <> itemId or data.versionId <> versionId or type(data.markers) <> "roArray" then return invalid
    return data.markers
end function

' Display labels never expose native internal track identifiers.
function SiloUIPlayerTrackLabel(name as String, language as String, kind as String, index as Integer) as String
    languages = {en:"English", eng:"English", es:"Spanish", spa:"Spanish", fr:"French", fra:"French", fre:"French", de:"German", deu:"German", ger:"German", it:"Italian", ita:"Italian", pt:"Portuguese", por:"Portuguese", ja:"Japanese", jpn:"Japanese", ko:"Korean", kor:"Korean", zh:"Chinese", zho:"Chinese", chi:"Chinese"}
    label = name.Trim()
    code = LCase(language.Trim())
    friendly = languages[code]
    if friendly = invalid then friendly = ""
    if Left(LCase(label), 6) = "#uniq:" then label = ""
    nameLanguage = languages[LCase(label)]
    if nameLanguage <> invalid then label = nameLanguage
    if LCase(label) = "sdh" and friendly <> "" then return friendly + " · SDH"
    if label <> "" then return label
    if friendly <> "" then return friendly
    prefix = "Audio"
    if kind = "subtitle" then prefix = "Subtitle"
    return prefix + " " + index.ToStr()
end function

function SiloUIPlayerCuePresentation(upNext as Boolean, seconds as Integer) as Object
    if upNext then return {width:420, height:160, hint:seconds.ToStr() + " seconds · Pause for next"}
    return {width:260, height:46, hint:"Pause to skip intro"}
end function

' Recovery replaces a transport inside the captured Silo lease. The worker
' revalidates registry scope and owns the server's attempt-key bookkeeping.
function SiloUINativeRecoveryParams(plan as Dynamic, owner as Dynamic, positionMs as Dynamic, requestId as String, reason as String) as Dynamic
    if type(plan) <> "roAssociativeArray" or type(owner) <> "roAssociativeArray" then return invalid
    context = plan.siloPlayback
    if type(context) <> "roAssociativeArray" then return invalid
    if plan.provider <> "silo" or owner.provider <> "silo" then return invalid
    if TextOr(plan.sourceId) = "" or plan.sourceId <> owner.sourceId or context.sourceId <> owner.sourceId or context.profileId <> owner.profileId then return invalid
    if TextOr(plan.sessionId) = "" or context.sessionId <> plan.sessionId or context.fileId <> plan.versionId then return invalid
    count = NumberOr(context.attemptCount,-1)
    position = NumberOr(positionMs,-1)
    if count < 0 or count >= 8 or count <> Int(count) then return invalid
    if position < 0 or position > 604800000 or position <> position then return invalid
    if Len(requestId) < 8 or Len(requestId) > 128 then return invalid
    if reason <> "decoder_failure" and reason <> "buffering_timeout" then return invalid
    key = TextOr(context.planAttemptKey)
    if Len(key) < 8 or type(context.attemptedPlanKeys) <> "roArray" then return invalid
    if context.attemptedPlanKeys.Count() >= 16 then return invalid
    for each attempted in context.attemptedPlanKeys
        if attempted = key then return invalid
    end for
    quality = TextOr(context.qualityPreference)
    if quality <> "original" and quality <> "4k" and quality <> "1080p_high" and quality <> "1080p" and quality <> "720p" and quality <> "480p" then return invalid
    return {sessionId:plan.sessionId,plan:plan,qualityPreference:quality,positionMs:Int(position),replanRequestId:requestId,failureClassification:reason}
end function

' Auto keeps a bounded native inventory; explicit file/track choices have no
' replacement ticket. The worker refreshes inventory and capabilities again.
function SiloUINativeVersionParams(plan as Dynamic, owner as Dynamic, positionMs as Dynamic) as Dynamic
    context = SiloPlaybackContext(plan,owner)
    if context = invalid or not SpNumber(positionMs,604800000) then return invalid
    request = SpField(plan,"autoVersionRequest")
    if type(request) <> "roAssociativeArray" then return invalid
    if request.autoVersion <> true or request.fileId <> context.fileId or request.itemId <> context.itemId then return invalid
    if SiloPlaybackFile(request.detail,context.sourceId,context.itemId,context.fileId,positionMs) = invalid then return invalid
    excluded = SpField(request,"excludedVersionIds")
    if type(excluded) <> "roArray" then return invalid
    if excluded.Count() >= 7 then return invalid
    for each id in excluded
        if not SpOpaque(id) or id = context.fileId then return invalid
    end for
    output = SpCopy(request)
    if SpField(context,"subtitleOffRequired") = true
        output["subtitleMode"] = "off"
        output["subtitleOffRequired"] = true
        output.Delete("subtitleTrackId")
        output.Delete("subtitleTrackIndex")
    end if
    output.excludedVersionIds.Push(context.fileId)
    output["startPositionMs"] = Int(positionMs)
    return output
end function


' Numeric support codes are fixed locally; server and native text never reaches UI.
function SiloUIPlaybackFailureCode(stage as String, result as Dynamic) as String
    if stage = "inventory_empty" then return "1001"
    if stage = "inventory_invalid" then return "1002"
    if stage = "selected_missing" then return "1003"
    if stage = "detail" then return "1004"
    if stage = "experimental_selection" then return "1005"
    if stage = "native" then return "3001"
    if stage = "timeout" then return "3002"
    if stage = "recovery"
        ' Timeout includes the bounded recovery job, not only an HTTP wait.
        if type(result) = "roAssociativeArray"
            if TextOr(result.errorCode) = "network_timeout" then return "3002"
        end if
        return "3003"
    end if
    if stage = "session" then return "3004"
    reason = ""
    code = ""
    if type(result) = "roAssociativeArray"
        reason = TextOr(result.reason)
        code = TextOr(result.errorCode)
    end if
    if reason = "no_playable_source" then return "2002"
    if reason = "no_alternate_version" then return "2003"
    if reason = "hdr_transcode_unsupported" or reason = "dv_conversion_unsupported" then return "2004"
    if reason = "audio_conversion_unsupported" then return "2005"
    if reason = "transcode_start_failed" then return "2016"
    if reason = "subtitle_conversion_unsupported" or reason = "subtitle_codec_unsupported" or reason = "subtitle_burn_in_source_unsupported" then return "2006"
    if code = "unsupported_device" then return "2015"
    if code = "unsupported_protocol" or code = "unsupported_playback_protocol" then return "2007"
    if code = "unsupported_stream" or reason = "client_hls_unsupported" then return "2008"
    if reason = "transcoding_disabled" then return "2009"
    if reason = "conversion_tool_unavailable" then return "2010"
    if reason = "source_metadata_incomplete" then return "2011"
    if reason = "source_unreadable" then return "2012"
    if reason = "bitrate_policy_unavailable" then return "2013"
    if reason = "adaptation_exhausted" then return "2014"
    return "2001"
end function

function SiloUIPlaybackFailureMessage(stage as String, result as Dynamic) as String
    code = SiloUIPlaybackFailureCode(stage,result)
    message = "Playback couldn't be prepared. Check your server connection and try again."
    if code = "1001" then message = "No files available. Check profile and library access."
    if code = "1002" then message = "The file list could not be read."
    if code = "1003" then message = "Selected version is no longer available."
    if code = "1004" then message = "Couldn't open this title."
    if code = "1005" then message = "Experimental selection could not be validated. Choose the version and audio again."
    if code = "2002" then message = "The server has no playable source for this title."
    if code = "2003" then message = "No playable route remains for the selected version. Try Auto or choose another version."
    if code = "2004" then message = "The server cannot prepare this HDR format."
    if code = "2005" then message = "The server cannot prepare this audio format."
    if code = "2006" then message = "The server cannot prepare these subtitles."
    if code = "2007" then message = "The server playback protocol is unsupported."
    if code = "2008" then message = "This playback stream is unsupported."
    if code = "2009" then message = "The server has disabled conversion for this playback."
    if code = "2010" then message = "A required server conversion tool is unavailable."
    if code = "2011" then message = "The server needs more source format information."
    if code = "2012" then message = "The server could not read the source file."
    if code = "2013" then message = "The server cannot meet this bitrate policy."
    if code = "2014" then message = "The server has exhausted its playback alternatives."
    if code = "2015" then message = "No compatible playback route was verified for this Roku and server. Check Roku updates and server conversion settings, then try again."
    if code = "2016" then message = "The server could not start conversion for this playback. Check server conversion settings and try again."
    if code = "3001" then message = "The Roku couldn't open or decode this stream. Try another version or a lower quality."
    if code = "3002" then message = "Playback did not become ready in time. Check the connection and try a lower quality."
    if code = "3003" then message = "No further playback option is available. Choose another version or check server conversion settings."
    if code = "3004" then message = "Playback session changed."
    ' Transport codes describe only the failed request, never an assumed file.
    if code = "2001" and type(result) = "roAssociativeArray"
        error = TextOr(result.errorCode)
        if error = "auth_required" or error = "unauthorized" then message = "Sign in again through Settings, then retry playback."
        if error = "forbidden" then message = "The server refused permission for this request. Check your profile access and retry."
        if error = "not_found" then message = "The server could not find the requested playback endpoint or resource. Check server compatibility and refresh the title."
        if error = "network_timeout" then message = "The server request timed out. Check your connection and try again."
        if error = "network_error" then message = "The app could not connect to the server. Check the server address and connection, then retry."
        if error = "rate_limited" then message = "The server is limiting requests. Wait a moment and try again."
        if error = "server_error" then message = "The server could not complete the request. Try again; if it repeats, check the server."
        if error = "task_failed" then message = "The app could not complete playback preparation. Retry, and record this code if it repeats."
    end if
    if code = "3004" and type(result) = "roAssociativeArray"
        phase = TextOr(result.compatFailurePhase):error = TextOr(result.errorCode)
        allowedError = false
        for each safeError in ["network_timeout","network_error","network_unavailable","tls_setup_failed","transport_failed","response_too_large","session_changed","cancelled","cleanup_deadline","invalid_compat_response","active_unconfirmed"]
            if error = safeError then allowedError = true:exit for
        end for
        if (phase = "playing_ack" or phase = "active_session") and allowedError
            message = "Playback confirmation failed (" + phase + ": " + error
            status = result.compatHttpStatus
            if type(status) = "Integer" or type(status) = "roInt" or type(status) = "roInteger"
                if status >= 100 and status <= 599 then message += "; HTTP " + status.ToStr()
            end if
            message += ")."
        end if
    end if
    native = SiloUIPlaybackNativeErrorNumber(result)
    if Left(code,1) = "3" and native <> "" then message += " (Roku " + native + ")"
    return "#" + code + ": " + message
end function

' Video.errorCode is numeric; private native error text is never accepted.
function SiloUIPlaybackNativeErrorNumber(result as Dynamic) as String
    if type(result) <> "roAssociativeArray" then return ""
    value = result.nativeCode
    kind = type(value)
    if kind <> "Integer" and kind <> "roInt" and kind <> "roInteger" and kind <> "LongInteger" and kind <> "roLongInteger" then return ""
    if value < -9999 or value > 9999 then return ""
    return Int(value).ToStr()
end function


' Local phase labels never claim server progress or echo response text.
function SiloUIPlaybackStatus(phase as String, plan = invalid as Dynamic) as Object
    title = "":detail = ""
    if phase = "request" then title = "Opening title…":detail = "Reading the available files and your playback settings."
    if phase = "prepare" then title = "Preparing playback…":detail = "Asking the server for a stream this Roku can play."
    if phase = "recovery" then title = "Retrying playback…":detail = "Asking the server for another playback option."
    if phase = "version" then title = "Trying another version…":detail = "Checking another available file for this title."
    if phase = "buffering"
        title = "Buffering…"
        detail = "Waiting for video from the server."
        if type(plan) = "roAssociativeArray"
            diagnostics = plan.playbackDiagnostics
            if type(diagnostics) = "roAssociativeArray"
                if diagnostics.delivery = "original_http" then detail = "Direct playback · Waiting for video from the server."
                if diagnostics.delivery = "server_remux_hls" or diagnostics.delivery = "server_remux_progressive" then detail = "Remux · Repackaging video without changing its codec."
                if diagnostics.delivery = "server_transcode_hls" then detail = "Transcode · The server is converting the stream for playback."
            end if
        end if
    end if
    return {title:title,detail:detail}
end function
