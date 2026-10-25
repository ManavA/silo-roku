' Catalog audio is a server selector, independent of Video's native Track IDs.
function PlaybackSourceAudioChoices() as Object
    choices = []
    if m.provider <> "silo" or m.playPlan = invalid or type(m.playVersions) <> "roArray" then return choices
    if m.playPlan.transport = "silo_compat" then return choices
    for each version in m.playVersions
        if version.versionId = m.playPlan.versionId and type(version.audioTracks) = "roArray"
            seen = {}
            inspected = 0
            for each track in version.audioTracks
                inspected++
                if inspected > 64 or choices.Count() >= 32 then exit for
                if type(track) = "roAssociativeArray"
                    if SpNumber(track.index,4095,true)
                        key = Int(track.index).ToStr()
                        if not seen.DoesExist(key)
                            seen[key] = true
                            label = SiloUIPlayerTrackLabel(TextOr(track.title),TextOr(track.language),"audio",choices.Count()+1)
                            label = "Source audio: " + label + " · " + UCase(TextOr(track.codec))
                            choices.Push({kind:"source_audio",title:label,index:track.index,language:TextOr(track.language),name:TextOr(track.title)})
                        end if
                    end if
                end if
            end for
            exit for
        end if
    end for
    return choices
end function

sub PlaybackSelectAudio(choice as Object)
    if m.playPlan <> invalid
        if m.playPlan.transport = "silo_compat" then Toast("Audio changes are unavailable for this stream.") : return
    end if
    if m.playbackChoiceBusy = true or m.recoveringNative = true or m.playPlan = invalid or m.view <> "player" then return
    owner = m.playPlan.cleanupOwner
    if type(owner) <> "roAssociativeArray" then Toast("Playback owner is unavailable.") : return
    position = Int(PlayerPositionMs())
    m.recoverPositionMs = position
    m.playbackChoiceBusy = true
    m.recoveringNative = true
    m.audioChoice = {token:m.playToken,sessionId:m.playPlan.sessionId,planId:m.playPlan.planId,paused:m.video.state="paused",selectedIndex:choice.index,language:choice.language,name:choice.name}
    params = {sessionId:m.playPlan.sessionId,plan:m.playPlan,positionMs:position,audioTrackIndex:choice.index,replanRequestId:SiloUICleanupUuid()}
    ApiOwned("playback_audio_select",params,"audio_select",m.audioChoice,owner)
    Toast("Selecting source audio…")
end sub

sub PlaybackAudioResult(result as Object, extra as Dynamic)
    if type(extra) <> "roAssociativeArray" then return
    if m.view <> "player" or m.playPlan = invalid or extra.token <> m.playToken then return
    if m.playPlan.sessionId <> extra.sessionId or m.playPlan.planId <> extra.planId then return
    m.playbackChoiceBusy = false
    m.recoveringNative = false
    if result.ok <> true or type(result.plan) <> "roAssociativeArray"
        Toast("That source audio is unavailable.")
        if result.leaseUncertain = true
            if type(result.controlReceipt) = "roAssociativeArray"
                m.playPlan.siloPlayback = result.controlReceipt
                m.playPlan.planId = result.controlReceipt.planId
                m.playPlan.planAttemptKey = result.controlReceipt.planAttemptKey
            end if
            PlayerClose(false)
        end if
        return
    end if
    plan = result.plan
    if plan.sessionId <> m.playPlan.sessionId or plan.versionId <> m.playPlan.versionId then Toast("Audio selection changed playback identity.") : PlayerClose(false) : return
    plan["cleanupOwner"] = m.playPlan.cleanupOwner
    sequence = m.progressSequence
    back = m.playerReturn
    captions = m.savedCaptionMode
    m.trackPref.audio = extra.language
    m.trackPrefLanes.audio = extra.name
    PlayerStart(plan)
    if m.playPlan <> invalid
        if m.playPlan.sessionId = plan.sessionId and m.playPlan.planId = plan.planId then PlaybackRememberAudio(result.audioPreference,extra.selectedIndex)
    end if
    m.progressSequence = sequence
    m.playerReturn = back
    m.savedCaptionMode = captions
    m.audioRestorePause = extra.paused
    if extra.paused then m.pauseRestoreMuted = true:m.video.mute = true
    PlayerRestorePausedIntent()
end sub

' Source subtitle selection belongs to the provider plan. Confirm Off there
' so local caption settings cannot be undone by a later replan.
function PlaybackSubtitleOff() as Boolean
    if m.provider <> "silo" or m.playPlan = invalid then return false
    mode = TextOr(m.playPlan.subtitleMode)
    if mode = "off" then return false
    if mode <> "burn_in" and mode <> "render" and mode <> "convert" then Toast("Subtitle controls are unavailable for this stream.") : return true
    if m.playbackChoiceBusy = true or m.recoveringNative = true or m.view <> "player" then return true
    context = SiloPlaybackContext(m.playPlan,SiloUIOwner())
    owner = m.playPlan.cleanupOwner
    if context = invalid or type(owner) <> "roAssociativeArray"
        if mode = "render" or mode = "convert" then return false
        Toast("These subtitles cannot be turned off during playback.") : return true
    end if
    if not SiloPlaybackCanReplan(context) or m.video.content = invalid
        if mode = "render" or mode = "convert" then return false
        Toast("These subtitles cannot be turned off during playback.") : return true
    end if
    if PlaybackSubtitleChangeBegin(invalid,context,owner) then return true
    if mode = "render" or mode = "convert" then return false
    Toast("These subtitles cannot be turned off during playback.")
    return true
end function

' Explicit source ordinals are scoped to this exact successful plan inventory.
sub PlaybackSelectSourceSubtitle(choice as Object)
    if m.playPlan <> invalid
        if m.playPlan.transport = "silo_compat" then Toast("Subtitles stay off for this stream.") : return
    end if
    if m.provider <> "silo" or m.playPlan = invalid or m.view <> "player" then return
    if m.playbackChoiceBusy = true or m.recoveringNative = true then return
    scope = SiloUIOwner()
    pair = SiloUserSubtitleSelection(m.playPlan,scope,choice.trackId,choice.combinedIndex)
    context = SiloPlaybackContext(m.playPlan,scope)
    owner = m.playPlan.cleanupOwner
    if pair = invalid or context = invalid or type(owner) <> "roAssociativeArray" then return
    if not SiloPlaybackCanReplan(context) or m.video.content = invalid then return
    PlaybackSubtitleChangeBegin(pair,context,owner)
end sub

function PlaybackSubtitleChangeBegin(pair as Dynamic, context as Object, owner as Object) as Boolean
    if owner.provider <> m.provider or owner.sourceId <> m.sourceId or owner.profileId <> m.profileId or owner.generation <> m.generation then return false
    if owner.sessionRevision <> context.sessionRevision then return false
    snapshot = ParseJson(FormatJson(m.playPlan))
    if type(snapshot) <> "roAssociativeArray" then return false
    position = Int(PlayerPositionMs())
    m.subtitleChange = {token:m.playToken,sessionId:m.playPlan.sessionId,planId:m.playPlan.planId,positionMs:position,paused:m.video.state="paused",content:m.video.content,owner:ParseJson(FormatJson(owner)),context:context,plan:snapshot,pair:pair,phase:"stopping",requestId:SiloUICleanupUuid(),clock:CreateObject("roTimespan")}
    m.recoverPositionMs = position
    m.playbackChoiceBusy = true
    m.recoveringNative = true
    m.video.control = "stop"
    if m.subtitleChangeTimer <> invalid then m.subtitleChangeTimer.control = "start"
    Toast("Changing source subtitles…")
    return true
end function

sub PlaybackSubtitleChangeObserve()
    attempt = m.subtitleChange
    if attempt = invalid then return
    if not PlaybackSubtitleChangeCurrent(attempt) then return
    if attempt.phase <> "stopping" or m.video.state <> "stopped" then return
    if attempt.clock.TotalMilliseconds() >= 5000
        Toast("Source subtitles are unavailable. Playback stopped.")
        PlayerClose(false)
        return
    end if
    attempt.phase = "requesting"
    params = {sessionId:attempt.sessionId,plan:attempt.plan,positionMs:attempt.positionMs,replanRequestId:attempt.requestId}
    action = "playback_subtitle_off":purpose = "subtitle_off"
    if attempt.pair <> invalid
        params.subtitleTrackId = attempt.pair.id:params.subtitleTrackIndex = attempt.pair.index
        action = "playback_subtitle_select":purpose = "subtitle_select"
    end if
    ApiOwned(action,params,purpose,attempt,attempt.owner)
    attempt.apiRequestId = m.requestId
end sub

function PlaybackSubtitleChangeOwned(attempt as Object) as Boolean
    if m.subtitleChange = invalid or m.view <> "player" or m.playPlan = invalid then return false
    if attempt.requestId <> m.subtitleChange.requestId or attempt.token <> m.playToken then return false
    if attempt.sessionId <> m.playPlan.sessionId or attempt.planId <> m.playPlan.planId then return false
    if attempt.owner.provider <> m.provider or attempt.owner.sourceId <> m.sourceId or attempt.owner.profileId <> m.profileId or attempt.owner.generation <> m.generation then return false
    if FormatJson(m.playPlan.cleanupOwner) <> FormatJson(attempt.owner) then return false
    return true
end function

function PlaybackSubtitleChangeCurrent(attempt as Object) as Boolean
    if not PlaybackSubtitleChangeOwned(attempt) or m.video.content = invalid then return false
    if FormatJson(SiloPlaybackContext(m.playPlan,SiloUIOwner())) <> FormatJson(attempt.context) then return false
    if attempt.pair <> invalid
        if SiloUserSubtitleSelection(m.playPlan,SiloUIOwner(),attempt.pair.id,attempt.pair.index) = invalid then return false
    end if
    return attempt.content.isSameNode(m.video.content)
end function

sub PlaybackSubtitleChangeCancel()
    m.subtitleChange = invalid
    if m.subtitleChangeTimer <> invalid then m.subtitleChangeTimer.control = "stop"
end sub

sub PlaybackSubtitleChangeResult(result as Object, extra as Dynamic)
    if type(extra) <> "roAssociativeArray" then return
    if not PlaybackSubtitleChangeCurrent(extra) then return
    if extra.phase <> "requesting" then return
    if result.requestId <> extra.apiRequestId then return
    plan = result.plan
    valid = result.ok = true and type(plan) = "roAssociativeArray"
    if extra.clock.TotalMilliseconds() >= 60000 then valid = false
    if valid then valid = SiloUISubtitleChangePlan(extra.context,m.playPlan,plan,SiloUIOwner(),extra.pair)
    if valid and extra.pair <> invalid
        kind = plan.selectedSubtitle.kind
        if kind = "sidecar_ready" or kind = "sidecar_pending"
            if SiloUISubtitleBinding(plan,m.generation,result.requestId) = invalid then valid = false
        end if
    end if
    if not valid
        receipt = result.controlReceipt
        if type(result.plan) = "roAssociativeArray" then receipt = result.plan.siloPlayback
        authority = SiloUISubtitleChangeControlPlan(extra,receipt)
        if authority <> invalid
            m.playPlan["siloPlayback"] = authority.siloPlayback
            m.playPlan["planId"] = authority.planId
            m.playPlan["planAttemptKey"] = authority.planAttemptKey
        end if
        Toast("Source subtitles are unavailable. Playback stopped.")
        PlayerClose(false)
        return
    end if
    plan["cleanupOwner"] = m.playPlan.cleanupOwner
    sequence = m.progressSequence:back = m.playerReturn:captions = m.savedCaptionMode
    PlaybackSubtitleChangeCancel()
    m.playbackChoiceBusy = false:m.recoveringNative = false
    if extra.pair <> invalid then m.subtitleLocalOff = invalid:m.nativeSubtitleOverride = invalid:m.trackPref.subtitle = ""
    PlayerStart(plan)
    m.progressSequence = sequence:m.playerReturn = back:m.savedCaptionMode = captions
    if extra.pair = invalid
        m.trackPref.subtitle = "off"
        m.video.globalCaptionMode = "Off"
    else
        m.trackPref.subtitle = ""
        m.subtitleLocalOff = invalid:m.nativeSubtitleOverride = invalid
        if plan.selectedSubtitle.kind = "fetch_failed" then Toast("Subtitles could not load. Playback continues.")
    end if
    m.audioRestorePause = extra.paused
    if extra.paused then m.pauseRestoreMuted = true:m.video.mute = true
    PlayerRestorePausedIntent()
end sub


sub onSubtitleChangeTimer()
    attempt = m.subtitleChange
    if attempt = invalid then return
    if not PlaybackSubtitleChangeCurrent(attempt)
        if PlaybackSubtitleChangeOwned(attempt)
            Toast("Playback changed while selecting subtitles. Playback stopped.")
            PlayerClose(false)
        else
            PlaybackSubtitleChangeCancel()
        end if
        return
    end if
    elapsed = attempt.clock.TotalMilliseconds()
    if elapsed >= 60000 or (attempt.phase = "stopping" and elapsed >= 5000)
        Toast("Source subtitles are unavailable. Playback stopped.")
        PlayerClose(false)
        return
    end if
    PlaybackSubtitleChangeObserve()
end sub

' Drain replacement receipts before generation filtering. Stale work owns its
' old allocation, but must never stop a newer active plan sharing that lease.
sub PlaybackSubtitleChangeApiResult(entry as Object, result as Object)
    extra = entry.extra
    if type(extra) <> "roAssociativeArray" then SiloUISubtitleResultCleanup(entry,result):return
    if extra.apiRequestId <> result.requestId then SiloUISubtitleResultCleanup(entry,result):return
    if entry.generation = m.generation and PlaybackSubtitleChangeCurrent(extra)
        if result.errorCode = "auth_required"
            SiloUISubtitleResultCleanup(entry,result)
            SiloUIAuthExpired(entry)
            return
        end if
        PlaybackSubtitleChangeResult(result,extra)
        SiloUISubtitleResultCleanup(entry,result)
        return
    end if
    SiloUISubtitleResultCleanup(entry,result)
    if PlaybackSubtitleChangeOwned(extra)
        receipt = result.controlReceipt
        if type(result.plan) = "roAssociativeArray" then receipt = result.plan.siloPlayback
        authority = SiloUISubtitleChangeControlPlan(extra,receipt)
        if authority <> invalid
            m.playPlan["siloPlayback"] = authority.siloPlayback
            m.playPlan["planId"] = authority.planId
            m.playPlan["planAttemptKey"] = authority.planAttemptKey
        end if
        PlayerClose(false)
        return
    end if
    activeLease = false
    if m.playPlan <> invalid and type(m.playPlan.cleanupOwner) = "roAssociativeArray"
        owner = m.playPlan.cleanupOwner
        activeLease = m.playPlan.sessionId = extra.sessionId and owner.sourceId = extra.owner.sourceId and owner.profileId = extra.owner.profileId and owner.generation = extra.owner.generation and owner.sessionRevision = extra.owner.sessionRevision
    end if
    if activeLease then return
    receipt = result.controlReceipt
    if type(result.plan) = "roAssociativeArray" then receipt = result.plan.siloPlayback
    cleanupPlan = SiloUISubtitleChangeControlPlan(extra,receipt)
    if cleanupPlan <> invalid then SiloUIQueueCleanup(cleanupPlan,extra.owner)
end sub

' Default-off menu uses only canonical URL-free inventory; it never maps native IDs.
function PlaybackSourceSubtitleChoices() as Object
    choices = []
    if not SpBool(m.sourceSubtitleMenuEnabled) or m.sourceSubtitleMenuEnabled <> true then return choices
    if m.provider <> "silo" or m.playPlan = invalid or m.view <> "player" then return choices
    if m.playPlan.experimentalOriginal = true then return choices
    scope = SiloUIOwner()
    context = SiloPlaybackContext(m.playPlan,scope)
    if context = invalid or not SiloPlaybackCanReplan(context) then return choices
    if SpField(context,"mediaAuthMode") <> "api_header_v1" then return choices
    inventory = SpField(m.playPlan,"sourceSubtitleInventory")
    entries = SpField(inventory,"entries")
    if type(entries) <> "roArray" or entries.Count() = 0 then return choices
    ' One canonical selection validates every row and all immutable owner fields.
    first = entries[0]
    if SiloUserSubtitleSelection(m.playPlan,scope,SpField(first,"trackId"),SpField(first,"combinedIndex")) = invalid then return choices
    for ordinal = 0 to entries.Count()-1
        entry = entries[ordinal]
        label = Left(SiloUIPlayerTrackLabel(entry.label,entry.language,"subtitle",ordinal+1),80)
        if entry.label <> "" and entry.language <> ""
            language = SiloUIPlayerTrackLabel("",entry.language,"subtitle",ordinal+1)
            if language = "Subtitle " + (ordinal+1).ToStr() then language = UCase(entry.language)
            if LCase(label) <> LCase(language) then label += " · " + language
        end if
        label = "Source subtitles: " + label
        if entry.codec <> "" then label += " · " + UCase(entry.codec)
        if entry.forced then label += " · Forced"
        if entry.hearingImpaired then label += " · SDH"
        kind = "source_subtitle"
        if not PlaybackSourceSubtitleText(entry)
            kind = "source_subtitle_unavailable"
            label += " · Unavailable"
        end if
        choices.Push({kind:kind,title:label,trackId:entry.trackId,combinedIndex:entry.combinedIndex,
            owner:ParseJson(FormatJson(inventory.owner)),context:context,token:m.playToken,content:m.video.content})
    end for
    return choices
end function

function PlaybackSourceSubtitleText(entry as Object) as Boolean
    if entry.delivery <> "sidecar" then return false
    codec = LCase(entry.codec)
    return codec = "subrip" or codec = "srt" or codec = "webvtt" or codec = "vtt"
end function

' Revalidate the captured dialog row against current request, lease and inventory.
function PlaybackSourceSubtitleChoiceCurrent(choice as Object) as Boolean
    if not SpBool(m.sourceSubtitleMenuEnabled) or m.sourceSubtitleMenuEnabled <> true then return false
    if m.provider <> "silo" or m.playPlan = invalid or m.view <> "player" then return false
    if m.playPlan.experimentalOriginal = true then return false
    if m.playbackChoiceBusy = true or m.recoveringNative = true then return false
    if choice.token <> m.playToken or choice.content = invalid or m.video.content = invalid then return false
    if not choice.content.isSameNode(m.video.content) then return false
    context = SiloPlaybackContext(m.playPlan,SiloUIOwner())
    if context = invalid or type(choice.context) <> "roAssociativeArray" then return false
    if FormatJson(context) <> FormatJson(choice.context) then return false
    owner = m.playPlan.cleanupOwner
    if type(owner) <> "roAssociativeArray" then return false
    if owner.provider <> m.provider or owner.sourceId <> m.sourceId or owner.profileId <> m.profileId or owner.generation <> m.generation then return false
    if owner.sessionRevision <> context.sessionRevision then return false
    if SpField(context,"mediaAuthMode") <> "api_header_v1" then return false
    if not SiloPlaybackCanReplan(context) then return false
    pair = SiloUserSubtitleSelection(m.playPlan,SiloUIOwner(),choice.trackId,choice.combinedIndex)
    if pair = invalid then return false
    inventory = m.playPlan.sourceSubtitleInventory
    if FormatJson(inventory.owner) <> FormatJson(choice.owner) then return false
    entry = inventory.entries[pair.index]
    return PlaybackSourceSubtitleText(entry)
end function

' Preference writes follow playback binding and never participate in admission.
sub PlaybackRememberAudio(preference as Dynamic, selectedIndex as Dynamic)
    if m.provider <> "silo" or not SiloObject(preference) or not SiloObject(m.playPlan) then return
    if not SiloAudioPreferenceOrdinal(selectedIndex) then return
    audio = SpField(SpField(SpField(m.playPlan,"siloPlayback"),"selectedTracks"),"audio")
    if SpField(audio,"index") <> selectedIndex then return
    if SpField(audio,"id") <> "file:"+m.playPlan.versionId+":audio:"+Int(selectedIndex).ToStr() then return
    params = ParseJson(FormatJson(preference))
    ticket = {owner:SiloUIOwner(),params:params,itemId:m.playPlan.itemId,fileId:m.playPlan.versionId}
    if not PlaybackAudioPreferenceCurrent(ticket) then return
    if m.audioPreferencePending = invalid then m.audioPreferencePending = {}
    key = FormatJson([ticket.owner.provider,ticket.owner.sourceId,ticket.owner.profileId,ticket.owner.generation,params.seriesId])
    m.audioPreferencePending[key] = ticket
    PlaybackAudioPreferenceDrain()
end sub

function PlaybackAudioPreferenceCurrent(ticket as Object) as Boolean
    owner = ticket.owner
    for each key in ["provider","sourceId","profileId","generation"]
        if owner[key] <> m[key] then return false
    end for
    if not SiloObject(m.playPlan) then return false
    return m.playPlan.provider = owner.provider and m.playPlan.sourceId = owner.sourceId and m.playPlan.itemId = ticket.itemId and m.playPlan.versionId = ticket.fileId
end function

sub PlaybackAudioPreferenceDrain()
    if m.audioPreferenceFlight <> invalid or m.audioPreferencePending = invalid then return
    for each key in m.audioPreferencePending
        ticket = m.audioPreferencePending[key]
        m.audioPreferencePending.Delete(key)
        if PlaybackAudioPreferenceCurrent(ticket)
            m.audioPreferenceFlight = ticket
            ApiOwned("audio_pref_set",ticket.params,"audio_preference",ticket,ticket.owner)
            return
        end if
    end for
end sub

sub PlaybackAudioPreferenceResult(ticket as Dynamic)
    if m.audioPreferenceFlight = invalid then return
    if FormatJson(m.audioPreferenceFlight) <> FormatJson(ticket) then return
    m.audioPreferenceFlight = invalid
    PlaybackAudioPreferenceDrain()
end sub
