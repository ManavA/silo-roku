' Foreground playback on the native Video node with Roku's built-in trick play.
' The plan URL and headers stay on the Video node only; nothing is logged.

sub PlayerInit()
    DiagnosticsInit()
    m.subtitleChangeTimer = m.top.findNode("subtitleChangeTimer")
    m.subtitleChangeTimer.observeField("fire", "onSubtitleChangeTimer")
    m.subtitleChange = invalid
    m.seekReanchor = invalid
    m.seekReanchorEnabled = false
    m.seekReanchorTimer = m.top.findNode("seekReanchorTimer")
    m.seekReanchorTimer.observeField("fire", "onSeekReanchorTimer")
    m.sourceSubtitleMenuEnabled = false
    m.trackChoices = []
    m.playerStatusPanel = m.top.findNode("playerStatusPanel")
    m.playerStatusTitle = m.top.findNode("playerStatusTitle")
    m.playerStatusDetail = m.top.findNode("playerStatusDetail")
    m.video = m.top.findNode("video")
    m.video.observeField("state", "onVideoState")
    m.progressTimer = m.top.findNode("progressTimer")
    m.progressTimer.observeField("fire", "onProgressTimer")
    m.top.observeField("memoryPressure", "onPlayerMemoryPressure")
    m.playPlan = invalid
    m.subtitleBinding = invalid
    m.subtitleRetired = []
    m.subtitleBindingGeneration = 0
    m.nativeSubtitleOverride = invalid
    m.nativeSubtitleContent = invalid
    m.nativeSubtitleInventoryFresh = false
    m.subtitleLocalOff = invalid
    m.playToken = 0
    m.playVersionExplicit = false
    m.originalPlayback = invalid
    m.originalGeneration = 0
    m.originalTimer = m.top.findNode("originalPlaybackTimer")
    m.originalTimer.observeField("fire", "onOriginalPlaybackTimer")
    m.trackPref = {}
    m.trackPrefLanes = {}
    m.playLoading = false : PlayerSetPlaybackStatus("")
    m.recoveringNative = false
    m.playLastPositionMs = 0
    m.playWaitClock = invalid
    m.playMarkers = []
    m.video.observeField("position", "onPlayerPosition")
    m.video.observeField("playbackActionButtonSelected", "onPlayerNativeAction")
    m.video.observeField("availableAudioTracks", "onPlayerTracks")
    m.video.observeField("availableSubtitleTracks", "onPlayerTracks")
    m.video.observeField("currentSubtitleTrack", "onPlayerTracks")
    m.upNextTimer = m.top.findNode("upNextTimer")
    m.upNextTimer.observeField("fire", "onUpNextTick")
    m.playerCue = m.top.findNode("playerCue")
    m.playerCueText = m.top.findNode("playerCueText")
    m.trackList = m.top.findNode("playerTrackList")
    m.trackList.observeField("itemSelected", "onPlayerTrackChoice")
    TransportInit()
end sub

' startMs < 0 lets the server choose its saved position.
sub PlayItem(item as Object, startMs as Dynamic, selectedVersion = "" as String, audioChoice = invalid as Dynamic, experimentalChoice = invalid as Dynamic)
    if item.homeCached = true then DetailOpen(item):return
    HomeCacheYield()
    if m.seekReanchor <> invalid then return
    if m.transitionIntent <> invalid or m.compatPreparation <> invalid then return
    if SiloUIPlaybackAdmissionBlocked() then SiloUIShowPlaybackAdmissionFailure() : return
    if m.compatPlayAttempt <> invalid
        ' Only a genuine foreground entry after ownership drains resets history.
        if SpScope(m.compatNativeStopFailure) <> invalid
            PlayerShowFailure("session",{errorCode:"cleanup_unconfirmed"})
            return
        end if
        if m.cleanupFailed = true or m.cleanupUnconfirmed = true then return
        if m.playPlan <> invalid or m.prebuf <> invalid or m.audioPlan <> invalid or m.audioNext <> invalid then return
        if m.audioSyncFlight <> invalid or m.audioSyncPending <> invalid then return
        if m.video.content <> invalid or m.cleanupTickets.Count() <> 0 then return
        for each key in m.pending
            job = m.pending[key].task.job
            if type(job) = "roAssociativeArray"
                if SiloContains(["playback_start","playback_replan","playback_stop","audio_start","playback_audio_select","playback_subtitle_select","playback_subtitle_off","playback_seek_reanchor"],job.action) then return
            end if
        end for
    end if
    ' Preserve the original version argument before audio/experimental pinning.
    versionExplicit = selectedVersion <> ""
    if experimentalChoice <> invalid
        if not PlayerExperimentalChoiceValid(experimentalChoice,item,selectedVersion,audioChoice,DetailPlaybackVersions(TextOr(item.itemId))) then Toast("Experimental selection changed. Choose it again.") : return
        selectedVersion = experimentalChoice.fileId
    end if
    if audioChoice <> invalid
        if m.provider <> "silo" or type(audioChoice) <> "roAssociativeArray" then Toast("Choose audio again before playing.") : return
        if audioChoice.visit <> m.detailToken or m.view <> "detail" or audioChoice.sourceId <> m.sourceId or audioChoice.profileId <> m.profileId or audioChoice.generation <> m.generation then Toast("Audio selection changed. Choose audio again.") : return
        if selectedVersion <> "" and selectedVersion <> audioChoice.fileId then Toast("Version changed. Choose audio again.") : return
        selectedVersion = TextOr(audioChoice.fileId)
        choiceVersions = m.detailVersions
        if m.detailEpisode <> invalid then choiceVersions = DetailPlaybackVersions(TextOr(item.itemId))
        if SiloUIDetailAudioMatch(audioChoice,TextOr(item.itemId),selectedVersion,choiceVersions) = invalid then Toast("Audio selection changed. Choose audio again.") : return
    end if
    m.compatPlayAttempt = invalid
    if (m.shuffle <> invalid or m.shuffleBusy = true) and m.shuffleAdvancing <> true then ShuffleLeave()
    if m.bingeAdvancing <> true then m.bingeAdvances = 0
    m.bingeAdvancing = false
    if m.view = "player" then PlayerClose(false)
    m.playHomeScope = HomeProgressScope()
    PlayerResetChrome()
    m.playDetailEmptyRetries = 0
    m.playNativeErrorCode = invalid
    m.playSelectedVersion = selectedVersion
    m.playVersionExplicit = versionExplicit
    m.playAudioChoice = audioChoice
    m.playExperimentalChoice = experimentalChoice
    pre = m.prebuf
    if pre <> invalid and pre.ready = true and pre.itemId = item.itemId and selectedVersion = "" and audioChoice = invalid and experimentalChoice = invalid and (startMs < 0 or Abs(startMs - pre.startMs) < 3000)
        m.prebuf = invalid
        m.playItem = pre.item
        m.playVersions = pre.versions
        m.playMarkers = pre.markers
        m.playClock = CreateObject("roTimespan")
        PlayerStart(pre.plan, true)
        return
    end if
    PlayerDiscardPrebuffer()
    m.playToken = m.playToken + 1
    m.prebufferForeground = invalid
    retiringPrebuffer = pre <> invalid
    for each key in m.pending
        if m.pending[key].purpose = "play_prebuf" then retiringPrebuffer = true
    end for
    if retiringPrebuffer then m.prebufferForeground = {token:m.playToken,owner:SiloUIOwner(),params:invalid}
    m.playItem = item
    m.playStartMs = startMs
    m.playLoading = true
    PlayerSetPlaybackStatus("request")
    m.playClock = CreateObject("roTimespan")
    if m.provider = "silo" and (TextOr(item.type) = "series" or TextOr(item.type) = "show")
        Api("playback_detail", {itemId:item.itemId,type:item.type}, "play_target", m.playToken)
        return
    end if
    Api("detail", {itemId: item.itemId}, "play_detail", m.playToken)
end sub

' Navigation retires only a foreground preparation, never an active player.
' Allocation callbacks retain their captured owner and release late leases.
sub PlayerCancelPreparation()
    if m.playLoading <> true or m.view = "player" then return
    SiloUICancelPendingPlayback()
    m.prebufferForeground = invalid
    m.playLoading = false : PlayerSetPlaybackStatus("")
    m.playToken = m.playToken + 1
    m.playAudioChoice = invalid
    m.playExperimentalChoice = invalid
    if m.toast <> invalid then m.toast.text = ""
    if m.toastTimer <> invalid then m.toastTimer.control = "stop"
end sub

sub PlayerResult(purpose as String, result as Object, data as Object, extra as Dynamic)
    compatResume = invalid
    if purpose = "play_start" and type(m.compatNativeResume) = "roAssociativeArray"
        if result.requestId = m.compatNativeResume.requestId
            compatResume = m.compatNativeResume:m.compatNativeResume = invalid
            if compatResume.token <> m.playToken or not SoScopeEqual(compatResume.owner,SiloUIOwner()) or compatResume.owner.sessionRevision <> DetailPhotoSessionRevision()
                if result.ok = true and type(result.plan) = "roAssociativeArray" then PlayerStopSession(result.plan,false)
                return
            end if
            if result.ok = true and type(result.plan) = "roAssociativeArray"
                if SiloContains(compatResume.excludedVersionIds,result.plan.versionId)
                    PlayerStopSession(result.plan,false)
                    m.playLoading = false : PlayerSetPlaybackStatus(""):PlayerShowFailure("prepare",{errorCode:"playback_terminal"})
                    return
                end if
            end if
        end if
    end if
    if purpose = "play_error_report"
        PlayerFailureReportResult(result,data,extra)
        return
    end if
    if purpose = "play_hero_detail"
        request = m.heroPrebufferRequest
        if request = invalid or type(extra) <> "roAssociativeArray" then return
        if request.token <> extra.token or request.generation <> m.generation then return
        m.heroPrebufferRequest = invalid
        if result.ok <> true or m.heroItem = invalid then return
        if not SiloUISpeedHero(m.homeRows, TextOr(m.heroItem.itemId), m.view, m.zone) then return
        if type(data.item) <> "roAssociativeArray" then return
        if TextOr(data.item.itemId) <> request.itemId then return
        if type(data.versions) <> "roArray" then return
        if data.versions.Count() <> 1 then return
        PlayerPrebuffer(data.item, data.versions, data.markers, data)
        return
    end if
    if purpose = "play_prebuf"
        pre = m.prebuf
        if pre = invalid or extra <> pre.token then
            ' Superseded: release the server session it created.
            if result.ok = true and type(result.plan) = "roAssociativeArray" then PlayerStopSession(result.plan, false)
            return
        end if
        if result.ok <> true or type(result.plan) <> "roAssociativeArray" or TextOr(result.plan.url) = "" then m.prebuf = invalid : return
        if type(result.plan.originalPlayback) = "roAssociativeArray"
            PlayerStopSession(result.plan, false)
            m.prebuf = invalid
            return
        end if
        if type(data.effectiveMarkers) = "roArray" then pre.markers = data.effectiveMarkers
        pre.plan = result.plan
        PlayerBind(result.plan, TextOr(pre.title), pre.versions)
        m.video.visible = false
        m.video.mute = true
        m.video.control = "prebuffer"
        pre.ready = true
        return
    end if
    if purpose = "play_report" then return
    if extra <> m.playToken
        if (purpose = "play_start" or purpose = "play_recover_version") and result.ok = true and type(result.plan) = "roAssociativeArray" then PlayerStopSession(result.plan, false)
        return
    end if
    if purpose = "play_recover" or purpose = "play_recover_version"
        if m.recoveringNative <> true or m.view <> "player" or m.playPlan = invalid then return
        plan = result.plan
        if result.ok <> true or type(plan) <> "roAssociativeArray"
            if purpose = "play_recover" and (result.errorCode = "playback_terminal" or result.errorCode = "no_new_playback_route")
                if PlayerRecoverNativeVersion() then return
            end if
            failure = PlayerFailureResult(result,m.playPlan)
            PlayerClose(false)
            PlayerShowFailure("recovery",failure)
            return
        end if
        if purpose = "play_recover" and plan.sessionId <> m.playPlan.sessionId
            failure = PlayerFailureResult({},m.playPlan)
            PlayerClose(false)
            PlayerShowFailure("session",failure)
            return
        end if
        if purpose = "play_recover"
            scope = SiloUIOwner()
            owner = m.playPlan.cleanupOwner
            current = SiloPlaybackContext(m.playPlan,scope)
            accepted = SiloPlaybackContext(plan,scope)
            owned = type(owner) = "roAssociativeArray" and current <> invalid and accepted <> invalid
            if owned
                for each field in ["provider","sourceId","profileId","generation"]
                    if SpField(owner,field) <> SpField(scope,field) then owned = false
                end for
                if owner.sessionRevision <> current.sessionRevision then owned = false
                for each field in ["sourceId","profileId","sessionRevision","itemId","fileId","installationId","sessionId","playbackAttemptId","planAttemptId"]
                    if SpField(current,field) <> SpField(accepted,field) then owned = false
                end for
            end if
            if not owned
                Toast("Playback recovery changed ownership. Playback stopped.")
                PlayerClose(false)
                return
            end if
            plan["cleanupOwner"] = ParseJson(FormatJson(owner))
        end if
        sequence = m.progressSequence
        if purpose = "play_recover_version"
            PlayerReport("playback_stop")
            sequence = 0
            m.playMarkers = []
            if type(data.effectiveMarkers) = "roArray" then m.playMarkers = data.effectiveMarkers
        end if
        back = m.playerReturn
        captions = m.savedCaptionMode
        PlayerStart(plan)
        m.progressSequence = sequence
        m.playerReturn = back
        m.savedCaptionMode = captions
        return
    end if
    if purpose = "play_markers"
        if m.view <> "player" or m.playPlan = invalid or result.ok <> true then return
        markers = SiloUIPlayerMarkerResult(data, TextOr(m.playItem.itemId), TextOr(m.playPlan.versionId))
        if markers <> invalid
            m.playMarkers = markers
            onPlayerPosition()
        end if
        return
    end if
    if purpose = "play_episodes"
        if m.view = "player" and result.ok = true
            m.playNext = SiloUIPlayerNext(m.playItem, data.items)
            onPlayerPosition()
        end if
        return
    end if
    if purpose = "play_target"
        if result.ok <> true then m.playLoading = false : PlayerSetPlaybackStatus("") : PlayerShowFailure("detail",result) : return
        leaf = data.item
        if type(leaf) <> "roAssociativeArray" or type(m.playItem) <> "roAssociativeArray" then m.playLoading = false : PlayerSetPlaybackStatus("") : PlayerShowFailure("inventory_invalid",result) : return
        if TextOr(data.candidateItemId) <> TextOr(m.playItem.itemId) or TextOr(leaf.seriesId) <> TextOr(m.playItem.itemId) or TextOr(leaf.type) <> "episode" or TextOr(leaf.itemId) = "" then m.playLoading = false : PlayerSetPlaybackStatus("") : PlayerShowFailure("inventory_invalid",result) : return
        m.playItem = leaf
        m.playStartMs = -1
        purpose = "play_detail"
    end if
    print "Silo play timing stage="; purpose; " ms="; m.playClock.TotalMilliseconds()
    if purpose = "play_detail"
        if result.ok <> true then m.playLoading = false : PlayerSetPlaybackStatus("") : PlayerShowFailure("detail",result) : return
        if type(data.item) <> "roAssociativeArray" or type(m.playItem) <> "roAssociativeArray" then m.playLoading = false : PlayerSetPlaybackStatus("") : PlayerShowFailure("inventory_invalid",result) : return
        if TextOr(data.item.itemId) = "" or TextOr(data.item.itemId) <> TextOr(m.playItem.itemId) then m.playLoading = false : PlayerSetPlaybackStatus("") : PlayerShowFailure("inventory_invalid",result) : return
        versions = data.versions
        if type(versions) <> "roArray" then m.playLoading = false : PlayerSetPlaybackStatus("") : PlayerShowFailure("inventory_invalid",result) : return
        if versions.Count() = 0
            if m.provider = "silo" and NumberOr(m.playDetailEmptyRetries,0) = 0 and type(m.playItem) = "roAssociativeArray"
                if TextOr(m.playItem.itemId) <> ""
                    m.playDetailEmptyRetries = 1
                    Api("detail", {itemId:m.playItem.itemId}, "play_detail", m.playToken)
                    return
                end if
            end if
            m.playLoading = false : PlayerSetPlaybackStatus("")
            PlayerShowFailure("inventory_empty",result)
            return
        end if
        fileId = SiloUIDetailVersion(versions, m.playSelectedVersion)
        if fileId = "" then m.playLoading = false : PlayerSetPlaybackStatus("") : PlayerShowFailure("selected_missing",result) : return
        if m.playExperimentalChoice <> invalid
            if not PlayerExperimentalChoiceValid(m.playExperimentalChoice,data.item,fileId,m.playAudioChoice,versions) then m.playLoading = false : PlayerSetPlaybackStatus("") : Toast("Experimental selection changed. Choose it again.") : return
        end if
        selectedAudio = invalid
        if m.playAudioChoice <> invalid
            if m.provider <> "silo" or m.view <> "detail" or m.playAudioChoice.visit <> m.detailToken or m.playAudioChoice.sourceId <> m.sourceId or m.playAudioChoice.profileId <> m.profileId or m.playAudioChoice.generation <> m.generation then m.playLoading = false : PlayerSetPlaybackStatus("") : Toast("Source or detail changed. Choose audio again.") : return
            selectedAudio = SiloUIDetailAudioMatch(m.playAudioChoice,TextOr(data.item.itemId),fileId,versions)
            if selectedAudio = invalid then m.playLoading = false : PlayerSetPlaybackStatus("") : Toast("Audio selection changed. Choose audio again.") : return
        end if
        item = data.item
        start = m.playStartMs
        if start < 0 then start = NumberOr(item.resumeMs, 0)
        if item.watched = true and start < 0 then start = 0
        m.playItem = item
        m.playVersions = versions
        m.playMarkers = data.markers
        for each version in versions
            if version.versionId = fileId and type(version.markers) = "roArray" then m.playMarkers = version.markers
        end for
        params = {itemId: item.itemId, fileId: fileId, startPositionMs: Int(start)}
        qualityParams = SiloUISettingsPlayback(m.provider, m.preferences)
        for each key in qualityParams
            params[key] = qualityParams[key]
        end for
        if m.provider = "silo"
            params.subtitleMode = SiloUISettingsPreferences(m.preferences).subtitles
            params.subtitlePreferences = SiloUISettingsPreferences(m.preferences)
            params.detail = data
            params.autoVersion = m.playSelectedVersion = ""
            if selectedAudio <> invalid
                params.autoVersion = false
                params.audioTrackIndex = selectedAudio.sourceOrdinal
                params.audioTrackId = "file:" + fileId + ":audio:" + selectedAudio.sourceOrdinal.ToStr()
            end if
            params.qualityExplicit = m.qualityExplicit = true
            for each version in versions
                if version.versionId = fileId then params.qualityPreference = SiloUISettingsPreferences(m.preferences).quality
            end for
        end if
        if m.provider = "plex"
            params.detail = data
            params.versionIndex = 0
            for index = 0 to versions.Count() - 1
                if versions[index].versionId = fileId then params.versionIndex = index
            end for
            params.Delete("fileId")
        end if
        if m.playExperimentalChoice <> invalid
            params.experimentalOriginal = true
            params.qualityPreference = "original"
            params.qualityExplicit = true
            params.subtitleMode = "off"
            params.autoVersion = false
        end if
        PlayerSetPlaybackStatus("prepare")
        if m.prebufferForeground <> invalid
            m.prebufferForeground.params = params
            PlayerDrainPrebufferForeground()
        else
            Api("playback_start", params, "play_start", m.playToken)
        end if
    else if purpose = "play_start"
        plan = result.plan
        if result.ok <> true or type(plan) <> "roAssociativeArray" or TextOr(plan.url) = ""
            m.playLoading = false : PlayerSetPlaybackStatus("")
            PlayerShowFailure("prepare",result)
            return
        end if
        if m.playExperimentalChoice <> invalid
            valid = PlayerExperimentalChoiceValid(m.playExperimentalChoice,m.playItem,m.playSelectedVersion,m.playAudioChoice,m.playVersions)
            if not valid or plan.experimentalOriginal <> true
                PlayerStopSession(plan,false)
                m.playLoading = false : PlayerSetPlaybackStatus("")
                Toast("Experimental selection changed. Choose it again.")
                return
            end if
        end if
        if type(data.effectiveMarkers) = "roArray" then m.playMarkers = data.effectiveMarkers
        explicitAudio = m.playAudioChoice
        PlayerStart(plan)
        if type(explicitAudio) = "roAssociativeArray" and m.playPlan <> invalid
            current = m.view = "player" and m.playPlan.sessionId = plan.sessionId and m.playPlan.planId = plan.planId
            current = current and explicitAudio.sourceId = m.sourceId and explicitAudio.profileId = m.profileId and explicitAudio.generation = m.generation
            if current and explicitAudio.itemId = m.playPlan.itemId and explicitAudio.fileId = m.playPlan.versionId then PlaybackRememberAudio(result.audioPreference,explicitAudio.sourceOrdinal)
        end if
        if compatResume <> invalid
            if compatResume.playerReturn <> invalid then m.playerReturn = compatResume.playerReturn
            if compatResume.savedCaptionMode <> invalid then m.savedCaptionMode = compatResume.savedCaptionMode
        end if
    end if
end sub

' Length is qualified for an exact original file, not a rebased server stream.
function PlayerOriginalLength(plan as Dynamic, versions as Dynamic) as Dynamic
    if type(plan) <> "roAssociativeArray" or type(versions) <> "roArray" then return invalid
    if plan.provider <> "silo" or versions.Count() > 16 then return invalid
    if type(plan.playbackDiagnostics) <> "roAssociativeArray" then return invalid
    if plan.playbackDiagnostics.delivery <> "original_http" then return invalid
    for each key in ["sourceId","itemId","versionId"]
        if type(plan[key]) <> "String" and type(plan[key]) <> "roString" then return invalid
        if Len(plan[key]) = 0 then return invalid
    end for
    if plan.timelineOffsetMs <> invalid
        if not PlayerDurationNumber(plan.timelineOffsetMs) then return invalid
        if plan.timelineOffsetMs <> 0 then return invalid
    end if
    matches = 0
    duration = invalid
    for each version in versions
        if type(version) = "roAssociativeArray"
            if version.versionId = plan.versionId
                matches += 1
                if version.sourceId <> plan.sourceId or version.itemId <> plan.itemId then return invalid
                duration = version.durationMs
            end if
        end if
    end for
    if matches <> 1 or not PlayerDurationNumber(duration) then return invalid
    if duration <> duration or duration < 1000 or duration > 604800000# then return invalid
    return Int(duration / 1000#)
end function

function PlayerDurationNumber(value as Dynamic) as Boolean
    for each kind in ["Integer","roInt","roInteger","LongInteger","roLongInteger","Float","roFloat","Double","roDouble"]
        if type(value) = kind then return true
    end for
    return false
end function

sub PlayerBind(plan as Object, title as String, durationVersions = invalid as Dynamic)
    m.nativeMovementClock = invalid
    PlayerOriginalClear()
    SiloUISubtitleRetireBound()
    if type(plan.originalPlayback) = "roAssociativeArray"
        m.originalGeneration = Int(NumberOr(m.originalGeneration,0)) + 1
        m.originalOldInventory = SiloUIOriginalInventorySignature(m.video.availableAudioTracks)
        m.video.control = "stop"
        m.video.content = invalid
        raw = m.video.availableAudioTracks
        m.originalDrained = type(raw) <> "roArray"
        if type(raw) = "roArray" then m.originalDrained = raw.Count() = 0
    end if
    content = CreateObject("roSGNode", "ContentNode")
    content.url = plan.url
    content.streamFormat = plan.streamFormat
    content.title = title
    content.playStart = NumberOr(plan.startPositionMs, 0) / 1000
    if durationVersions = invalid then durationVersions = m.playVersions
    durationSeconds = PlayerOriginalLength(plan,durationVersions)
    if durationSeconds <> invalid then content.Length = durationSeconds
    subtitles = plan.subtitleTracks
    if type(subtitles) = "roArray" and subtitles.Count() > 0 then content.subtitleTracks = subtitles
    if plan.transport = "silo_compat" and SpField(SpField(plan,"compatCaption"),"disposition") = "ready"
        uri = plan.compatCaption.uri
        if SiloUISubtitleLocalUri(uri,"srt")
            content.SubtitleConfig = {TrackName:uri}
            m.video.subtitleTrack = uri
        end if
    end if
    binding = SiloUISubtitleBinding(plan,m.generation,m.subtitleResultRequestId)
    if binding <> invalid
        content.SubtitleTracks = [{Language:binding.language,Description:binding.description,TrackName:binding.uri}]
        content.SubtitleConfig = {TrackName:binding.uri}
        m.video.subtitleTrack = binding.uri
    end if
    headers = plan.headers
    if type(headers) <> "roAssociativeArray" then headers = {}
    agent = CreateObject("roHttpAgent")
    agent.SetCertificatesFile("common:/certs/ca-bundle.crt")
    list = []
    for each name in headers
        agent.AddHeader(name, headers[name])
        list.Push(name + ": " + headers[name])
    end for
    content.HttpHeaders = list
    content.HttpCertificatesFile = "common:/certs/ca-bundle.crt"
    m.video.SetHttpAgent(agent)
    if plan.transport = "silo_compat"
        m.compatMediaBinding = {content:content,agent:agent,holderId:plan.holderId,attemptId:plan.attemptId,planGeneration:plan.planGeneration}
    end if
    m.nativeSubtitleContent = content
    m.nativeSubtitleInventoryFresh = false
    if binding <> invalid
        m.subtitleBindingGeneration++
        binding["content"] = content
        binding["bindingGeneration"] = m.subtitleBindingGeneration
        m.subtitleBinding = binding
    end if
    m.video.content = content
end sub

sub PlayerStart(plan as Object, bound = false as Boolean)
    if PlayerSeekPausePending() then m.video.mute = true
    descriptor = SpField(plan,"originalPlayback")
    if SpField(descriptor,"qualifiedRoute") <> invalid
        scope = SpScope(SpField(descriptor,"scope"))
        valid = (SiloUIOriginalQualifiedP8(descriptor) or SiloUIOriginalQualifiedFilm(descriptor)) and scope <> invalid
        if valid then valid = SoScopeEqual(scope,SiloUIOwner())
        if valid then valid = descriptor.outputFingerprint = PlayerOriginalOutputFingerprint()
        if not valid
            SiloUIQueueCleanup(plan,plan.cleanupOwner)
            m.playLoading = false : PlayerSetPlaybackStatus("")
            Toast("Playback changed. Choose Play again.")
            return
        end if
    end if
    PlayerCloseTracks()
    if m.subtitleChange <> invalid then PlaybackSubtitleChangeCancel()
    m.playbackChoiceBusy = false
    m.audioChoice = invalid
    m.audioRestorePause = false
    m.pauseRestoreMuted = false
    m.pauseRestoreClock = invalid
    m.playLoading = false : PlayerSetPlaybackStatus("")
    m.recoveringNative = false
    m.nativeHdrMode = invalid
    m.nativeVideoSize = invalid
    m.nativeSeenPlaying = false
    m.nativeMovementClock = invalid
    m.playLastPositionMs = Int(NumberOr(plan.startPositionMs,0)+NumberOr(plan.timelineOffsetMs,0))
    m.playWaitClock = CreateObject("roTimespan")
    subtitleScope = {provider:m.provider,sourceId:m.sourceId,profileId:m.profileId,generation:m.generation}
    if not SiloUISubtitleOverrideOwned(m.nativeSubtitleOverride,plan,subtitleScope) then m.nativeSubtitleOverride = invalid
    if not SiloUISubtitleLocalOffOwned(m.subtitleLocalOff,plan,subtitleScope) then m.subtitleLocalOff = invalid
    m.playPlan = plan
    PlayerSetPlaybackStatus("buffering",plan)
    m.nativePlaybackOwner = SiloUIOwner()
    m.nativePlaybackToken = m.playToken
    m.savedCaptionMode = m.video.globalCaptionMode
    m.playNext = SiloUIPlayerNext(m.playItem, m.detailEpisodes)
    if m.shuffle <> invalid
        if m.shuffle.current.itemId = m.playItem.itemId then m.playNext = m.shuffle.next
    end if
    if m.provider = "silo" and m.playNext = invalid and m.playItem.type = "episode" and TextOr(m.playItem.seriesId) <> ""
        Api("episodes", {seriesId: m.playItem.seriesId, seasonNumber: m.playItem.seasonNumber}, "play_episodes", m.playToken)
    end if
    if m.provider = "plex" and m.playNext = invalid and m.playItem.type = "episode" and TextOr(m.playItem.seasonItemId) <> ""
        Api("children", {itemId: m.playItem.seasonItemId, limit: 100}, "play_episodes", m.playToken)
    end if
    m.progressSequence = 0
    if not bound then PlayerBind(plan, TextOr(m.playItem.title))
    m.video.mute = PlayerSeekPausePending()
    if type(plan.originalPlayback) = "roAssociativeArray"
        descriptor = plan.originalPlayback
        owner = SiloUIOwner()
        identityMatches = descriptor.sourceId = plan.sourceId and descriptor.itemId = plan.itemId and descriptor.fileId = plan.versionId and descriptor.sessionId = plan.sessionId and descriptor.planId = plan.planId
        if identityMatches and plan.streamFormat = "mkv" and descriptor.sourceId = owner.sourceId and type(descriptor.scope) = "roAssociativeArray"
            experimental = (type(plan.experimentalOriginal) = "Boolean" or type(plan.experimentalOriginal) = "roBoolean") and plan.experimentalOriginal = true
            if descriptor.scope.profileId = owner.profileId then m.originalPlayback = SiloUIOriginalCreate(descriptor,m.playToken,m.originalGeneration,0,experimental)
        end if
        m.originalClock = CreateObject("roTimespan")
        m.originalOutputFingerprint = PlayerOriginalOutputFingerprint()
        m.originalContent = m.video.content
        m.originalBinding = PlayerOriginalCaptureBinding()
        m.originalFreshState = false
        m.video.mute = true
        if m.originalTimer <> invalid then m.originalTimer.control = "start"
    end if
    m.playerReturn = {view: m.view, zone: m.zone}
    for each name in ["home", "detail", "library", "search"]
        m.top.findNode(name).visible = false
    end for
    m.nav.visible = false
    m.view = "player"
    m.video.visible = true
    if m.transport <> invalid then TransportStart()
    m.video.control = "play"
    if type(plan.originalPlayback) = "roAssociativeArray" and m.originalPlayback = invalid
        if not PlayerRecoverNativeFailure("decoder_failure")
            failure = PlayerFailureResult({},m.playPlan)
            PlayerClose(false)
            PlayerShowFailure("native",failure)
        end if
        return
    end if
    PlayerPlaybackFocus()
    m.zone = "player"
    m.toast.text = ""
    subtitleNotice = SiloUISubtitleStartupNotice(plan)
    if subtitleNotice <> "" then Toast(subtitleNotice)
    m.progressTimer.control = "start"
    onPlayerTracks()
    PlayerUpdateNativeActions(PlayerCurrentCue())
end sub

function PlayerPositionMs() as Integer
    if m.compatPreparation <> invalid
        if m.compatPreparation.engine <> invalid and m.compatPreparation.stockPositionMs <> invalid then return Int(m.compatPreparation.stockPositionMs)
        if m.compatPreparation.stockSeek <> invalid then return Int(m.compatPreparation.stockSeek.positionMs)
    end if
    if m.seekReanchor <> invalid then return Int(m.seekReanchor.targetMs)
    if m.playPlan <> invalid
        if m.playPlan.transport = "silo_compat" and m.compatPreparation <> invalid
            if m.compatPreparation.landed <> true then return Int(m.compatPreparation.intent.startPositionMs)
        end if
        if m.playPlan.transport = "silo_compat" and m.compatPreparation = invalid then return Int(NumberOr(m.playLastPositionMs,0))
    end if
    if m.recoveringNative = true then return Int(NumberOr(m.recoverPositionMs,0))
    if m.audioRestorePause = true and m.playPlan <> invalid
        target = NumberOr(m.playPlan.startPositionMs,0)+NumberOr(m.playPlan.timelineOffsetMs,0)
        return Int(NumberOr(m.playPlan.originalResumeMs,target))
    end if
    if m.originalPlayback <> invalid
        if m.originalPlayback.phase <> "verified_playing" then return Int(NumberOr(m.playLastPositionMs,0))
    end if
    offset = 0
    if m.playPlan <> invalid then offset = NumberOr(m.playPlan.timelineOffsetMs, 0)
    if m.video.state = "finished" and NumberOr(m.video.position,0) = 0 then return Int(NumberOr(m.playLastPositionMs,0))
    return Int(m.video.position * 1000 + offset)
end function

' All custom seek consumers dispatch here; compatibility reanchors its owner.
function PlayerSeekTo(positionMs as Dynamic) as Boolean
    if m.playPlan = invalid then return false
    if m.playPlan.transport = "silo_compat" then return SiloUICompatSeek(positionMs)
    number = NumberOr(positionMs,-1)
    if number < 0 or number > 315576000000# or number <> number then return false
    if m.seekReanchor <> invalid then return false
    duration = 0
    if m.playItem <> invalid then duration = NumberOr(m.playItem.durationMs,0)
    if duration > 0 and positionMs > duration then return false
    if m.playPlan.provider = "silo" and m.playPlan.canSeekAnywhere <> true
        if m.playbackChoiceBusy = true or m.recoveringNative = true or m.audioRestorePause = true or m.pauseRestoreMuted = true then return false
        start = m.playPlan.seekWindowStartMs:finish = m.playPlan.seekWindowEndMs
        covered = SpNumber(start,315576000000#,false) and SpNumber(finish,315576000000#,false)
        if covered then covered = finish >= start and positionMs >= start and positionMs <= finish and positionMs >= NumberOr(m.playPlan.timelineOffsetMs,0)
        if not covered
            if SiloUISeekBegin(positionMs) then return true
            Toast("Seeking is unavailable for this stream.")
            return false
        end if
    end if
    if positionMs < NumberOr(m.playPlan.timelineOffsetMs,0) then return false
    m.video.seek = (positionMs-NumberOr(m.playPlan.timelineOffsetMs,0))/1000#
    return true
end function

sub PlayerReport(action as String, positionMs = invalid as Dynamic, finalSample = invalid as Dynamic)
    if m.playPlan = invalid then return
    if m.playPlan.transport = "silo_compat"
        if positionMs = invalid then positionMs = PlayerPositionMs()
        if action = "playback_progress" then SiloUICompatReport("progress",positionMs)
        return
    end if
    paused = m.video.state = "paused"
    if finalSample <> invalid
        m.progressSequence = finalSample.sequence
        paused = finalSample.isPaused
    else
        m.progressSequence = m.progressSequence + 1
    end if
    if positionMs = invalid then positionMs = PlayerPositionMs()
    params = {sessionId: TextOr(m.playPlan.sessionId), installationId: TextOr(m.playPlan.installationId), positionMs: positionMs, sequence: m.progressSequence, isPaused: paused}
    if m.provider = "plex" then params = SiloUIPlexReport(m.playPlan, positionMs, paused)
    Api(action, params, "play_report", -1)
end sub

function PlayerNativeMovementTimedOut() as Boolean
    eligible = m.view = "player" and m.playPlan <> invalid and m.recoveringNative <> true and m.transitionIntent = invalid
    eligible = eligible and m.seekReanchor = invalid and m.subtitleChange = invalid and m.originalPlayback = invalid
    eligible = eligible and m.audioRestorePause <> true and m.pauseRestoreMuted <> true and m.playbackChoiceBusy <> true
    if eligible
        eligible = m.video.state = "playing" and m.playPlan.transport <> "silo_compat" and m.playPlan.originalPlayback = invalid and m.playPlan.experimentalOriginal <> true
        eligible = eligible and type(m.nativePlaybackOwner) = "roAssociativeArray" and m.nativePlaybackToken = m.playToken
        if eligible
            owner = SiloUIOwner()
            for each field in ["provider","sourceId","profileId","generation"]
                if SpField(m.nativePlaybackOwner,field) <> SpField(owner,field) then eligible = false
            end for
        end if
    end if
    if not eligible
        m.nativeMovementClock = invalid
        return false
    end if
    position = PlayerPositionMs()
    if m.nativeMovementClock = invalid or position <> m.nativeMovementPositionMs
        m.nativeMovementClock = CreateObject("roTimespan")
        m.nativeMovementPositionMs = position
        return false
    end if
    ' Leave slow native streams the same grace period as buffering.
    return m.nativeMovementClock.TotalMilliseconds() >= 120000
end function

sub onProgressTimer()
    if PlayerNativeMovementTimedOut()
        if not PlayerRecoverNativeFailure("buffering_timeout")
            failure = PlayerFailureResult({},m.playPlan)
            PlayerClose(false)
            PlayerShowFailure("timeout",failure)
        end if
        return
    end if
    if m.seekReanchor <> invalid then onSeekReanchorTimer():return
    if m.view <> "player" or m.playPlan = invalid or m.recoveringNative = true then return
    if m.audioRestorePause = true and m.pauseRestoreClock <> invalid
        if m.pauseRestoreClock.TotalMilliseconds() >= 10000
            Toast("The paused position could not be restored. Playback stopped.")
            PlayerClose(false)
            return
        end if
    end if
    if m.originalPlayback <> invalid
        onOriginalPlaybackTimer()
        if m.originalPlayback = invalid or m.recoveringNative = true then return
        if m.originalPlayback.phase <> "verified_playing" then return
    end if
    if m.video.state = "playing" or m.video.state = "paused"
        if m.audioRestorePause = true then return
        m.playLastPositionMs = PlayerPositionMs()
        PlayerReport("playback_progress")
    else if m.playWaitClock <> invalid
        if m.playWaitClock.TotalMilliseconds() >= 120000
            if m.playPlan.transport = "silo_compat" then SiloUICompatFailure("buffering_timeout") : return
            if not PlayerRecoverNativeFailure("buffering_timeout")
                failure = PlayerFailureResult({},m.playPlan)
                PlayerClose(false)
                PlayerShowFailure("timeout",failure)
            end if
        end if
    end if
end sub

function PlayerRecoverNativeFailure(reason as String) as Boolean
    if m.seekReanchor <> invalid then return false
    if m.playPlan <> invalid
        if m.playPlan.transport = "silo_compat" then return false
        if m.playPlan.experimentalOriginal = true then return false
    end if
    if m.view <> "player" or m.playPlan = invalid or m.recoveringNative = true or m.transitionIntent <> invalid then return false
    if m.playPlan.provider <> "silo" then return false
    position = NumberOr(m.playLastPositionMs,PlayerPositionMs())
    params = SiloUINativeRecoveryParams(m.playPlan,SiloUIOwner(),position,SiloUICleanupUuid(),reason)
    if params = invalid then return PlayerRecoverNativeVersion()
    PlayerOriginalClear()
    m.recoverPositionMs = params.positionMs
    m.recoveringNative = true
    m.playLoading = true
    m.playToken = m.playToken + 1
    m.progressTimer.control = "stop"
    m.video.control = "stop"
    PlayerSetPlaybackStatus("recovery")
    Api("playback_replan",params,"play_recover",m.playToken)
    return true
end function

function PlayerRecoverNativeVersion() as Boolean
    if m.playPlan <> invalid
        if m.playPlan.transport = "silo_compat" then return false
        if m.playPlan.experimentalOriginal = true then return false
    end if
    if m.view <> "player" or m.playPlan = invalid or m.transitionIntent <> invalid then return false
    position = NumberOr(m.playLastPositionMs,PlayerPositionMs())
    params = SiloUINativeVersionParams(m.playPlan,SiloUIOwner(),position)
    if params = invalid then return false
    PlayerOriginalClear()
    m.recoverPositionMs = params.startPositionMs
    m.recoveringNative = true
    m.playLoading = true
    m.playToken = m.playToken + 1
    m.progressTimer.control = "stop"
    m.video.control = "stop"
    PlayerSetPlaybackStatus("version")
    Api("playback_start",params,"play_recover_version",m.playToken)
    return true
end function

function PlayerCompletionDurationMs() as Double
    if m.playPlan = invalid then return 0
    if type(m.playVersions) = "roArray"
        matches = 0
        duration = 0
        for each version in m.playVersions
            if type(version) = "roAssociativeArray"
                if version.versionId = m.playPlan.versionId and version.sourceId = m.playPlan.sourceId and version.itemId = m.playPlan.itemId
                    matches++
                    duration = NumberOr(version.durationMs,0)
                end if
            end if
        end for
        if matches > 0
            if matches = 1 and duration > 0 and duration <= 604800000# then return duration
            return 0
        end if
    end if
    duration = NumberOr(m.video.duration,0)*1000#
    if duration <= 0 then return 0
    return duration+NumberOr(m.playPlan.timelineOffsetMs,0)
end function

function PlayerFinishedNaturally(duration as Double) as Boolean
    if m.audioRestorePause = true then return false
    if m.nativeSeenPlaying <> true or duration <= 0 or duration > 604800000# then return false
    position = NumberOr(m.playLastPositionMs,0)
    ' Some native decoders reset position before delivering finished.
    current = NumberOr(m.video.position,0)*1000#
    if current > 0 and m.playPlan.transport <> "silo_compat" then position = current+NumberOr(m.playPlan.timelineOffsetMs,0)
    m.playLastPositionMs = Int(position)
    tolerance = duration*0.05
    ' Position notifications arrive once per second, including on short clips.
    if tolerance < 1000 then tolerance = 1000
    if tolerance > 10000 then tolerance = 10000
    if tolerance > duration/2 then tolerance = duration/2
    return position > 0 and position >= duration-tolerance and position <= duration+10000
end function

sub onVideoState()
    SiloUISubtitleDrainRetired()
    SiloUICompatObserveLocalStop()
    if SiloUICompatStockSeekState() then return
    if m.seekReanchor <> invalid then SiloUISeekObserve() : return
    if m.subtitleChange <> invalid then PlaybackSubtitleChangeObserve() : return
    if m.recoveringNative = true then return
    state = m.video.state
    if state <> "playing" then m.nativeMovementClock = invalid
    if m.playPlan <> invalid
        if m.playPlan.transport = "silo_compat" and state = "playing" then SiloUICompatPlaying()
        if m.playPlan.transport = "silo_compat" and state = "paused" then SiloUICompatRestorePause()
        if m.playPlan.transport = "silo_compat" and state = "finished"
            current = m.compatPreparation
            natural = false
            if current <> invalid
                natural = current.phase = "playing" and current.landed = true and current.activeConfirmed = true and m.nativeSeenPlaying = true
                if current.content = invalid or m.video.content = invalid then natural = false
                if natural then natural = current.content.isSameNode(m.video.content) and SiloUICompatCurrent(current)
            end if
            duration = 0
            if natural
                finishedFile = SiloPlaybackFile(current.detail,current.owner.sourceId,current.intent.itemId,current.intent.fileId,current.intent.startPositionMs)
                if finishedFile <> invalid then duration = finishedFile.durationMs
            end if
            natural = natural and PlayerFinishedNaturally(duration)
            if natural
                if m.playNext <> invalid and m.upNextActive = true and m.upNextDismissed <> true and SiloUISettingsPreferences(m.preferences).autoPlayNext <> false
                    PlayerAutoAdvance()
                else
                    PlayerClose(true)
                end if
            else
                SiloUICompatFailure("decoder_failure")
            end if
            return
        end if
        if m.playPlan.transport = "silo_compat" and state = "error" then SiloUICompatFailure("decoder_failure") : return
    end if
    if state = "finished"
        if m.view <> "player" or m.playPlan = invalid or m.transitionIntent <> invalid then return
        if type(m.nativePlaybackOwner) = "roAssociativeArray"
            owner = SiloUIOwner()
            for each field in ["provider","sourceId","profileId","generation"]
                if SpField(m.nativePlaybackOwner,field) <> SpField(owner,field) then return
            end for
            if m.nativePlaybackToken <> m.playToken then return
        end if
    end if
    if m.originalPlayback <> invalid
        PlayerOriginalObserve()
        if m.recoveringNative = true or m.view <> "player" then return
        if state = "finished" and m.originalPlayback <> invalid
            if m.originalPlayback.phase <> "verified_playing" then return
        end if
    end if
    if state = "buffering" or state = "none" or state = "stopped"
        if m.view = "player" then m.playWaitClock = CreateObject("roTimespan")
    end if
    if m.view = "player" and m.playPlan <> invalid and m.transitionIntent = invalid and m.playLoading <> true
        if state = "buffering" then PlayerSetPlaybackStatus("buffering",m.playPlan)
        if state = "playing" or state = "paused" then PlayerSetPlaybackStatus("")
    end if
    PlayerRestorePausedIntent()
    if state = "playing"
        m.playWaitClock = invalid
        if m.view = "player" and m.playPlan <> invalid and m.transitionIntent = invalid
            m.nativeSeenPlaying = true
            m.playLastPositionMs = PlayerPositionMs()
        end if
    end if
    if m.playClock <> invalid then print "Silo play timing video="; state; " ms="; m.playClock.TotalMilliseconds()
    if state = "playing" then PlayerLoadMarkers()
    if m.launchInitialized = true then SiloUILaunchReady()
    if state = "finished"
        if not PlayerFinishedNaturally(PlayerCompletionDurationMs())
            if PlayerRecoverNativeFailure("decoder_failure") then return
            failure = PlayerFailureResult({},m.playPlan)
            PlayerClose(false)
            PlayerShowFailure("native",failure)
            return
        end if
        if m.view = "player" and m.playNext <> invalid and m.upNextActive and not m.upNextDismissed and SiloUISettingsPreferences(m.preferences).autoPlayNext <> false
            PlayerAutoAdvance()
        else
            PlayerClose(true)
        end if
    else if state = "error"
        print "Silo video error code="; m.video.errorCode
        m.playNativeErrorCode = m.video.errorCode
        if PlayerRecoverNativeFailure("decoder_failure") then return
        failure = PlayerFailureResult({},m.playPlan)
        PlayerClose(false)
        PlayerShowFailure("native",failure)
    end if
end sub

sub PlayerClose(finished as Boolean, refresh = true as Boolean)
    position = invalid
    finalSample = invalid
    seekClose = m.seekReanchor
    guardedClose = m.originalPlayback <> invalid
    ' Snapshot only active playback, before cancellation or native STOP.
    ' Outside-player calls still retire pending controllers before returning.
    if m.view = "player"
        position = PlayerPositionMs()
        finalSample = {sequence:m.progressSequence+1,isPaused:m.video.state="paused"}
        if seekClose <> invalid then position = seekClose.lastObservedMs
        if m.subtitleChange <> invalid then position = m.subtitleChange.positionMs
        if guardedClose then position = PlayerPositionMs()
        if seekClose <> invalid then finalSample.isPaused = seekClose.desiredPaused
    end if
    if seekClose <> invalid
        SiloUISeekCancel()
        finished = false
    end if
    if m.subtitleChange <> invalid
        PlaybackSubtitleChangeCancel()
        finished = false
    end if
    if guardedClose
        if m.originalPlayback.phase <> "verified_playing" then finished = false
    end if
    PlayerOriginalClear()
    m.playbackChoiceBusy = false
    m.audioChoice = invalid
    m.audioRestorePause = false
    m.pauseRestoreClock = invalid
    if m.shuffle <> invalid and m.shuffleAdvancing <> true then ShuffleLeave()
    if m.view <> "player" then return
    m.progressTimer.control = "stop"
    SiloUICancelPendingPlayback()
    m.playToken = m.playToken + 1
    PlayerResetChrome()
    ' Compat captures and stops through its own owner/ACK path above.
    compatibilityClose = false
    if m.playPlan <> invalid then compatibilityClose = m.playPlan.transport = "silo_compat"
    if not compatibilityClose then m.video.control = "stop"
    if seekClose <> invalid
        m.progressSequence = finalSample.sequence
        SiloUIQueueCleanup(m.playPlan,seekClose.owner,{positionMs:position,sequence:finalSample.sequence,isPaused:finalSample.isPaused})
    else
        PlayerReport("playback_stop",position,finalSample)
    end if
    m.recoveringNative = false
    m.playWaitClock = invalid
    m.playPlan = invalid
    m.nativeHdrMode = invalid
    m.nativeVideoSize = invalid
    SiloUISubtitleRetireBound()
    m.video.control = "stop"
    m.video.content = invalid
    m.video.visible = false
    if m.savedCaptionMode <> invalid then m.video.globalCaptionMode = m.savedCaptionMode
    ' Reflect the new resume point locally so Home/Detail are right at once.
    if m.playItem <> invalid
        if finished
            m.playItem.resumeMs = 0
            m.playItem.watched = true
        else
            m.playItem.resumeMs = position
            if position > 0 then m.playItem.watched = false
        end if
    end if
    if m.playItem <> invalid then HomeUpdateProgress(m.playItem, m.playHomeScope)
    back = m.playerReturn
    if back = invalid then back = {view: "home", zone: "heroButtons"}
    ShowView(back.view)
    if refresh and back.view = "home"
        if m.homeReload = true then HomeLoad() else HomeRefreshHero()
    end if
    if refresh and back.view = "library" and m.libraryReload = true then LibraryOpen(m.libraryType) : return
    if refresh and back.view = "detail" and m.detailItem = invalid and m.detailReloadItem <> invalid then DetailOpen(m.detailReloadItem) : return
    if refresh and back.view = "detail" and m.detailItem <> invalid then Api("detail", {itemId: m.detailItem.itemId}, "detail_item", m.detailToken) : SetBackdrop(DetailBackdrop())
    SetZone(back.zone)
    if m.launchInitialized = true then SiloUILaunchReady()
end sub

function PlayerKey(key as String) as Boolean
    if m.seekReanchor <> invalid
        if key = "up" then DiagnosticsToggle():return true
        if key = "back"
            if m.diagnostics <> invalid
                if m.diagnostics.visible then DiagnosticsClose():return true
            end if
            PlayerClose(false)
        end if
        return true
    end if
    if m.subtitleChange <> invalid
        if key = "back" then PlayerClose(false)
        return true
    end if
    if m.trackDialog <> invalid
        if key = "back" or key = "options"
            PlayerCloseTracks()
            PlayerPlaybackFocus()
            return true
        end if
        return false
    end if
    if key = "up"
        if m.transport <> invalid then m.transport.visible = false
        DiagnosticsToggle()
        return true
    end if
    if key = "back" and m.diagnostics <> invalid
        if m.diagnostics.visible then DiagnosticsClose() : return true
    end if
    if key = "options" then PlayerShowTracks() : return true
    if m.transport <> invalid
        cueSelect = key = "OK" and m.playerCue.visible and m.transportPreviewMs = invalid and not m.transport.visible
        if not cueSelect
            if TransportKey(key) then return true
        end if
    end if
    if key = "back"
        if m.playerCue.visible
            if m.upNextActive
                m.upNextDismissed = true
            else
                m.introDismissed = true
            end if
            m.playerCue.visible = false
            m.upNextTimer.control = "stop"
            if m.playPlan <> invalid then PlayerUpdateNativeActions(PlayerCurrentCue())
        else
            PlayerClose(false)
        end if
        return true
    end if
    if key = "OK" and m.playerCue.visible
        if m.upNextActive
            PlayerAdvance()
        else if m.introEndMs > 0
            offset = NumberOr(m.playPlan.timelineOffsetMs, 0)
            if m.transportEnabled = true
                TransportSkip(m.introEndMs)
            else
                if PlayerSeekTo(m.introEndMs)
                    if m.seekReanchor <> invalid
                        m.seekReanchor.marker = {kind:"native_skip"}
                    else
                        m.playerCue.visible = false
                    end if
                end if
            end if
        end if
        return true
    end if
    return false
end function

sub PlayerResetChrome()
    m.nativeHdrMode = invalid
    m.nativeVideoSize = invalid
    PlayerSetPlaybackStatus("")
    m.playbackChoiceBusy = false
    m.audioChoice = invalid
    m.audioRestorePause = false
    if m.transport <> invalid then TransportReset()
    DiagnosticsClose()
    if m.bingeDialog <> invalid then m.bingeDialog.close = true
    m.bingeDialog = invalid
    m.upNextTimer.control = "stop"
    m.playerCue.visible = false
    m.upNextActive = false
    m.upNextDismissed = false
    m.introDismissed = false
    m.introEndMs = 0
    m.playNext = invalid
    m.playMarkers = []
    m.markerLookupStarted = false
    m.nativeActionSignature = invalid
    m.video.playbackActionButtons = []
    PlayerCloseTracks()
end sub

sub onPlayerPosition()
    if m.seekReanchor <> invalid then SiloUISeekObserve(true):return
    if m.view <> "player" or m.playPlan = invalid or m.recoveringNative = true then return
    if m.playPlan.transport = "silo_compat" then SiloUICompatObservePosition()
    PlayerRestorePausedIntent()
    if m.originalPlayback <> invalid
        PlayerOriginalObserve()
        if m.recoveringNative = true or m.view <> "player" then return
        if m.originalPlayback <> invalid
            if m.originalPlayback.phase <> "verified_playing" then return
        end if
    end if
    if m.video.state = "playing" or m.video.state = "paused" then m.playLastPositionMs = PlayerPositionMs()
    if m.transport <> invalid then TransportAutoSkip()
    cue = PlayerCurrentCue()
    PlayerUpdateNativeActions(cue)
    if m.introEndMs <> cue.introEndMs then m.introDismissed = false
    m.introEndMs = cue.introEndMs
    m.playSkipLabel = TextOr(cue.skipLabel)
    if cue.upNext
        if not m.upNextActive
            m.upNextActive = true
            binge = SiloUISettingsBinge(m.preferences, NumberOr(m.bingeAdvances,0))
            m.upNextSeconds = binge.seconds
            art = ItemArt(m.playNext)
            if type(art) <> "roAssociativeArray" then art = {}
            m.top.findNode("nextStill").uri = ArtField(art, "still")
            if binge.autoplay and binge.seconds > 0 then m.upNextTimer.control = "start"
        end if
        PlayerPaintNext()
    else
        m.upNextActive = false
        m.upNextTimer.control = "stop"
        m.top.findNode("nextStill").uri = ""
        m.playerCue.visible = cue.introEndMs > 0 and not m.introDismissed
        PlayerPaintCue(false)
    end if
end sub

sub PlayerPaintNext()
    m.playerCue.visible = true
    PlayerPaintCue(true)
end sub

sub PlayerPaintCue(upNext as Boolean)
    seconds = 0
    if upNext then seconds = m.upNextSeconds
    presentation = SiloUIPlayerCuePresentation(upNext, seconds)
    if upNext
        if SiloUISettingsPreferences(m.preferences).autoPlayNext = false then presentation.hint = "Autoplay off · Pause for next"
        if seconds = 0 and SiloUISettingsPreferences(m.preferences).autoPlayNext <> false then presentation.hint = "At episode end · Pause for next"
    end if
    background = m.top.findNode("playerCueBackground")
    background.width = presentation.width
    background.height = presentation.height
    m.top.findNode("nextStill").visible = upNext
    title = m.top.findNode("playerCueTitle")
    title.visible = upNext
    if upNext
        m.playerCue.translation = [800, 440]
        title.text = "Up next: " + TextOr(m.playNext.title)
        m.playerCueText.translation = [12, 112]
        m.playerCueText.width = 396
    else
        m.playerCue.translation = [960, 500]
        m.playerCueText.translation = [12, 4]
        m.playerCueText.width = 236
    end if
    m.playerCueText.text = presentation.hint
    if m.transportEnabled = true
        m.playerCueText.text = CreateObject("roRegex", "Pause", "").ReplaceAll(presentation.hint, "OK")
        if not upNext and TextOr(m.playSkipLabel) <> "" then m.playerCueText.text = "OK to " + m.playSkipLabel
    end if
    if m.transport <> invalid
        if m.transport.visible or m.chapterOpen = true then m.playerCue.visible = false
    end if
end sub

sub onUpNextTick()
    if m.seekReanchor <> invalid then return
    if m.view <> "player" or not m.upNextActive or m.upNextDismissed then return
    if m.trackDialog <> invalid or m.video.state <> "playing" then return
    if not SiloUISettingsBinge(m.preferences, NumberOr(m.bingeAdvances,0)).autoplay then return
    m.upNextSeconds = m.upNextSeconds - 1
    if m.upNextSeconds <= 0 then PlayerAutoAdvance() else PlayerPaintNext()
end sub

sub PlayerAdvance(automatic = false as Boolean)
    if m.shuffle <> invalid
        if m.shuffle.current.itemId = m.playItem.itemId then ShuffleAdvance(automatic) : return
    end if
    nextItem = m.playNext
    if nextItem = invalid then return
    if PlayerDeferCompatNext(nextItem,automatic) then return
    if automatic then m.bingeAdvances = NumberOr(m.bingeAdvances,0) + 1 else m.bingeAdvances = 0
    m.bingeAdvancing = true
    PlayerClose(true, false)
    PlayItem(nextItem, 0)
end sub

function PlayerDeferCompatNext(nextItem as Object, automatic as Boolean) as Boolean
    if m.playPlan = invalid then return false
    if m.playPlan.transport <> "silo_compat" then return false
    state = m.compatPreparation
    if state = invalid or state.phase <> "playing" then return true
    if not SiloUICompatCurrent(state) then return true
    if not SpOpaque(nextItem.itemId) or nextItem.sourceId <> state.owner.sourceId then Toast("The next episode is unavailable.") : return true
    state.nextIntent = {item:SpCopy(nextItem),token:m.playToken+1,owner:SpCopy(state.owner),returnView:m.playerReturn.view,shuffle:m.shuffleAdvancing=true}
    if automatic then m.bingeAdvances = NumberOr(m.bingeAdvances,0)+1 else m.bingeAdvances = 0
    m.bingeAdvancing = true
    PlayerClose(true,false)
    return true
end function

sub PlayerAutoAdvance()
    if m.playbackChoiceBusy = true then return
    if m.view <> "player" then return
    binge = SiloUISettingsBinge(m.preferences, NumberOr(m.bingeAdvances,0))
    if not binge.autoplay then return
    if binge.ask
        PlayerStillWatching()
    else
        PlayerAdvance(true)
    end if
end sub

sub PlayerStillWatching()
    if m.bingeDialog <> invalid then return
    m.upNextTimer.control = "stop"
    if m.video.state = "playing" then m.video.control = "pause"
    dialog = CreateObject("roSGNode", "Dialog")
    dialog.title = "Still watching?"
    dialog.message = "Continue to the next episode?"
    dialog.buttons = ["Continue", "Stop watching"]
    dialog.observeField("buttonSelected", "onPlayerStillWatching")
    dialog.observeField("wasClosed", "onPlayerStillWatchingClosed")
    m.bingeToken = m.playToken
    m.bingeDialog = dialog
    m.top.dialog = dialog
end sub

sub onPlayerStillWatching(event = invalid as Dynamic)
    if m.bingeDialog = invalid then return
    if event <> invalid
        if not m.bingeDialog.isSameNode(event.getRoSGNode()) then return
    end if
    continueWatching = m.bingeDialog.buttonSelected = 0
    dialog = m.bingeDialog
    m.bingeDialog = invalid
    dialog.close = true
    if m.bingeToken <> m.playToken or m.view <> "player" then return
    PlayerPlaybackFocus()
    if continueWatching
        m.bingeAdvances = 0
        PlayerAdvance(true)
    else
        PlayerClose(false)
    end if
end sub

sub onPlayerStillWatchingClosed(event = invalid as Dynamic)
    if m.bingeDialog = invalid then return
    if event <> invalid
        if not m.bingeDialog.isSameNode(event.getRoSGNode()) then return
    end if
    m.bingeDialog = invalid
    if m.bingeToken = m.playToken and m.view = "player" then PlayerClose(false)
end sub

sub PlayerCloseTracks()
    if m.trackDialog <> invalid then m.trackDialog.visible = false
    m.trackDialog = invalid
    m.trackChoices = []
end sub

sub PlayerShowTracks()
    if m.playPlan <> invalid
        if m.playPlan.transport = "silo_compat" then Toast("Audio, subtitles and quality changes are unavailable for this stream.") : return
    end if
    if m.transport <> invalid then m.transport.visible = false
    if m.trackDialog <> invalid then return
    choices = []
    for each kind in ["audio", "subtitle"]
        tracks = m.video.availableAudioTracks
        if kind = "subtitle"
            tracks = m.video.availableSubtitleTracks
            subtitleIntent = SiloUISubtitleIntent(m.playPlan)
            choices.Push({kind: kind, trackId: "", language: "", title: "Subtitles: Off"})
        end if
        inventory = TrackPreferenceInventory(tracks, kind)
        if kind = "subtitle" and subtitleIntent <> "preference" and subtitleIntent <> "off" then inventory = invalid
        if kind = "subtitle" and m.playPlan <> invalid
            if m.playPlan.experimentalOriginal = true then inventory = invalid
        end if
        if kind = "audio" and m.originalPlayback <> invalid then inventory = invalid
        if inventory <> invalid
            trackIndex = 0
            for each track in inventory
                trackIndex++
                label = SiloUIPlayerTrackLabel(track.name, track.language, kind, trackIndex)
                track.kind = kind
                track.title = kind + ": " + label
                choices.Push(track)
            end for
        end if
    end for
    if m.shuffle <> invalid then choices.Push({kind:"shuffle_controls",title:"Shuffle controls"})
    sourceSubtitles = PlaybackSourceSubtitleChoices()
    for sourceIndex = 0 to sourceSubtitles.Count()-1
        choices.Push(sourceSubtitles[sourceIndex])
    end for
    if m.provider = "silo"
        for each choice in PlaybackSourceAudioChoices()
            choices.Push(choice)
        end for
    end if
    content = CreateObject("roSGNode", "ContentNode")
    for each choice in choices
        entry = content.createChild("ContentNode")
        entry.title = choice.title
    end for
    m.trackChoices = choices
    m.trackList.content = content
    m.trackDialog = m.top.findNode("playerTracks")
    m.trackDialog.visible = true
    m.trackList.setFocus(true)
end sub

sub onPlayerTrackChoice()
    if m.seekReanchor <> invalid then return
    if m.playPlan <> invalid
        if m.playPlan.transport = "silo_compat" then PlayerCloseTracks() : Toast("Track changes are unavailable for this stream.") : return
    end if
    if m.view <> "player" or m.trackDialog = invalid then return
    index = m.trackList.itemSelected
    if index < 0 or index >= m.trackChoices.Count() then return
    choice = m.trackChoices[index]
    if choice.kind = "subtitle" and m.playPlan <> invalid
        if m.playPlan.experimentalOriginal = true then Toast("Subtitles stay off during experimental playback.") : return
    end if
    if choice.kind = "source_subtitle" or choice.kind = "source_subtitle_unavailable"
        if choice.kind = "source_subtitle_unavailable"
            Toast("These source subtitles are unavailable on this playback route.")
            return
        end if
        if not PlaybackSourceSubtitleChoiceCurrent(choice)
            Toast("Subtitle selection changed or playback is busy. Choose it again.")
            return
        end if
        PlayerCloseTracks()
        PlayerPlaybackFocus()
        PlaybackSelectSourceSubtitle(choice)
        return
    end if
    if choice.kind = "shuffle_controls"
        PlayerCloseTracks()
        ShuffleDialog()
        return
    end if
    if choice.kind = "source_audio"
        PlayerCloseTracks()
        PlayerPlaybackFocus()
        PlaybackSelectAudio(choice)
        return
    end if
    if m.provider = "silo" and choice.kind = "subtitle" and choice.trackId = ""
        if PlaybackSubtitleOff()
            m.nativeSubtitleOverride = invalid
            m.subtitleLocalOff = invalid
            PlayerCloseTracks()
            PlayerPlaybackFocus()
            return
        end if
    end if
    if choice.kind = "audio" and m.originalPlayback <> invalid then return
    if choice.kind = "subtitle" and choice.trackId <> "" and SiloUISubtitleIntent(m.playPlan) = "off"
        subtitleScope = {provider:m.provider,sourceId:m.sourceId,profileId:m.profileId,generation:m.generation}
        chosen = SiloUISubtitleOverrideCapture(m.playPlan,subtitleScope,choice,m.video.availableSubtitleTracks)
        if chosen = invalid then Toast("Subtitle selection changed. Choose it again.") : return
        m.nativeSubtitleOverride = chosen
    end if
    m.trackPref[choice.kind] = choice.language
    if m.trackPrefLanes = invalid then m.trackPrefLanes = {}
    m.trackPrefLanes[choice.kind] = choice.name
    if choice.kind = "audio"
        m.video.audioTrack = choice.trackId
    else if choice.trackId = ""
        m.trackPref.subtitle = "off"
        m.nativeSubtitleOverride = invalid
        if SiloUISubtitleIntent(m.playPlan) = "selected"
            m.subtitleLocalOff = {sourceId:m.sourceId,profileId:m.profileId,generation:m.generation,sessionId:m.playPlan.sessionId,fileId:m.playPlan.versionId}
        end if
        m.video.globalCaptionMode = "Off"
    else
        m.subtitleLocalOff = invalid
        m.video.subtitleTrack = choice.trackId
        m.video.globalCaptionMode = "On"
    end if
    PlayerCloseTracks()
    PlayerPlaybackFocus()
end sub

sub onPlayerTracks(event = invalid as Dynamic)
    if m.playPlan <> invalid
        if m.playPlan.transport = "silo_compat"
            if m.playPlan.subtitleMode = "on" and SiloUISubtitleLocalUri(m.playPlan.compatCaptionUri,"srt")
                m.video.subtitleTrack = m.playPlan.compatCaptionUri
                m.video.globalCaptionMode = "On"
            else
                m.video.globalCaptionMode = "Off"
            end if
            return
        end if
    end if
    freshSubtitle = false
    if event <> invalid then freshSubtitle = event.GetField() = "availableSubtitleTracks"
    if freshSubtitle and m.subtitleBinding <> invalid and m.video.content <> invalid
        if m.subtitleBinding.content.isSameNode(m.video.content) then m.subtitleBinding["inventoryFresh"] = true
    end if
    if freshSubtitle and m.nativeSubtitleContent <> invalid and m.video.content <> invalid
        if m.nativeSubtitleContent.isSameNode(m.video.content) then m.nativeSubtitleInventoryFresh = true
    end if
    if m.view <> "player" or m.playPlan = invalid then return
    if m.originalPlayback <> invalid and m.originalClock <> invalid
        freshAudio = false
        if event <> invalid then freshAudio = event.GetField() = "availableAudioTracks"
        PlayerOriginalInventory(freshAudio)
        if m.recoveringNative = true or m.view <> "player" then return
    end if
    subtitleIntent = SiloUISubtitleIntent(m.playPlan)
    if m.playPlan.experimentalOriginal = true
        m.video.globalCaptionMode = "Off"
    else if subtitleIntent = "burn_in"
        m.video.globalCaptionMode = "Off"
    else if subtitleIntent = "off"
        m.video.globalCaptionMode = "Off"
        if m.nativeSubtitleInventoryFresh = true and m.nativeSubtitleContent <> invalid and m.video.content <> invalid
            if m.nativeSubtitleContent.isSameNode(m.video.content)
                subtitleScope = {provider:m.provider,sourceId:m.sourceId,profileId:m.profileId,generation:m.generation}
                candidate = SiloUISubtitleOverrideCandidate(m.nativeSubtitleOverride,m.playPlan,subtitleScope,m.video.availableSubtitleTracks)
                if candidate <> invalid
                    if freshSubtitle then m.video.subtitleTrack = candidate
                    if m.video.currentSubtitleTrack = candidate then m.video.globalCaptionMode = "On"
                end if
            end if
        end if
    else if subtitleIntent = "selected"
        m.video.globalCaptionMode = "Off"
        if m.subtitleLocalOff = invalid and m.subtitleBinding <> invalid and m.video.content <> invalid
            if m.subtitleBinding.content.isSameNode(m.video.content) and m.subtitleBinding.inventoryFresh = true
                candidate = SiloUISubtitleNativeCandidate(m.subtitleBinding,m.video.availableSubtitleTracks)
                if candidate <> invalid
                    if freshSubtitle then m.video.subtitleTrack = candidate
                    m.subtitleBinding["currentVerified"] = SiloUISubtitleCurrentMatches(m.subtitleBinding,m.video.currentSubtitleTrack,m.video.availableSubtitleTracks)
                    if m.subtitleBinding.currentVerified = true then m.video.globalCaptionMode = "On"
                end if
            end if
        end if
    else if m.trackPref.subtitle = invalid
        inventory = TrackPreferenceInventory(m.video.availableSubtitleTracks, "subtitle")
        audioLanguage = ""
        if m.trackPref.audio <> invalid then audioLanguage = m.trackPref.audio
        if audioLanguage = "" and type(m.video.availableAudioTracks) = "roArray"
            for each audio in m.video.availableAudioTracks
                if audio.Track = m.video.audioTrack then audioLanguage = TextOr(audio.Language)
            end for
        end if
        selected = SiloUISettingsSelectSubtitle(m.preferences, inventory, audioLanguage)
        m.video.globalCaptionMode = "Off"
        if selected <> ""
            m.video.subtitleTrack = selected
            m.video.globalCaptionMode = "On"
        end if
    end if
    for each kind in ["audio", "subtitle"]
        language = m.trackPref[kind]
        if kind = "audio" and m.originalPlayback <> invalid then language = invalid
        if kind = "subtitle" and (m.playPlan.experimentalOriginal = true or subtitleIntent <> "preference") then language = invalid
        if language <> invalid and language <> ""
            tracks = m.video.availableAudioTracks
            if kind = "subtitle" then tracks = m.video.availableSubtitleTracks
            inventory = TrackPreferenceInventory(tracks, kind)
            if kind = "subtitle" and language = "off" then m.video.globalCaptionMode = "Off"
            if inventory <> invalid
                wantedName = ""
                if m.trackPrefLanes <> invalid
                    name = m.trackPrefLanes[kind]
                    if type(name) = "roString" or type(name) = "String" then wantedName = name
                end if
                selectedTrack = invalid
                bestScore = -1000
                for each track in inventory
                    if track.language = language
                        score = TrackPreferenceLaneScore(track, kind, wantedName)
                        if track.name = wantedName then score = score + 1000
                        if score > bestScore then selectedTrack = track : bestScore = score
                    end if
                end for
                if selectedTrack <> invalid
                    if kind = "audio"
                        m.video.audioTrack = selectedTrack.trackId
                    else
                        m.video.subtitleTrack = selectedTrack.trackId
                        m.video.globalCaptionMode = "On"
                    end if
                end if
            end if
        end if
    end for
end sub

' Start loading a title's stream while its detail page is open.
sub PlayerPrebuffer(item as Object, versions as Dynamic, markers = invalid as Dynamic, detail = invalid as Dynamic)
    if SiloUIPlaybackAdmissionBlocked() then return
    if m.compatPreparation <> invalid or m.compatPlayAttempt <> invalid then return
    if m.speculationDisabled = true or m.memoryHigh = true then return
    if m.provider <> "silo" or m.playLoading = true then return
    if m.view <> "detail" and m.view <> "home" then return
    if type(versions) <> "roArray" or versions.Count() = 0 then return
    if m.prebuf <> invalid and m.prebuf.itemId = item.itemId then return
    PlayerDiscardPrebuffer()
    m.playToken = m.playToken + 1
    start = NumberOr(item.resumeMs, 0)
    if item.watched = true then start = 0
    m.prebuf = {token: m.playToken, itemId: item.itemId, startMs: start, title: TextOr(item.title), item: item, versions:versions, markers: markers, ready: false}
    params = {itemId:item.itemId,fileId:versions[0].versionId,startPositionMs:Int(start),qualityPreference:SiloUISettingsPreferences(m.preferences).quality,qualityExplicit:m.qualityExplicit=true,autoVersion:true}
    if type(detail) <> "roAssociativeArray" then m.prebuf = invalid : return
    params.detail = detail
    params.speculativePrebuffer = true
    HomeCacheYield()
    Api("playback_start", params, "play_prebuf", m.playToken)
end sub

sub PlayerDiscardPrebuffer()
    m.heroPrebufferRequest = invalid
    pre = m.prebuf
    if pre = invalid then return
    m.prebuf = invalid
    for each key in m.pending
        if m.pending[key].purpose = "play_prebuf" and m.pending[key].extra = pre.token
            task = m.pending[key].task
            task.cancelled = true
        end if
    end for
    if pre.ready = true
        SiloUISubtitleRetireBound()
        m.video.control = "stop"
        m.video.content = invalid
        PlayerStopSession(pre.plan, false)
    end if
end sub

' Close a server session that never played, without touching resume state.
sub PlayerStopSession(plan as Object, persist as Boolean)
    owner = plan.cleanupOwner
    if type(owner) <> "roAssociativeArray" then m.cleanupUnconfirmed = true : return
    SiloUIQueueCleanup(plan, owner)
end sub

' Pause-screen actions are the documented entry point when Video owns Options.
function PlayerCurrentCue() as Object
    duration = NumberOr(m.playItem.durationMs, 0)
    if duration <= 0 and m.video.duration > 0
        duration = m.video.duration * 1000 + NumberOr(m.playPlan.timelineOffsetMs, 0)
    end if
    cue = SiloUIPlayerCue(m.playMarkers, PlayerPositionMs(), duration, m.playNext <> invalid, m.upNextDismissed)
    if type(m.preferences) = "roAssociativeArray"
        if m.preferences.introSkipMode = "never" then cue.introEndMs = 0
    end if
    if m.transportEnabled = true
        skip = SiloUITransportSkipCue(m.playMarkers,PlayerPositionMs(),TextOr(m.preferences.introSkipMode))
        cue.introEndMs = 0
        if skip <> invalid then cue.introEndMs = skip.endMs : cue.skipLabel = skip.label
    end if
    return cue
end function

sub PlayerUpdateNativeActions(cue as Object)
    buttons = SiloUIPlayerActions(cue, m.introDismissed)
    signature = FormatJson(buttons)
    if signature = m.nativeActionSignature then return
    m.nativeActionSignature = signature
    m.video.playbackActionButtons = buttons
end sub

sub onPlayerNativeAction()
    if m.seekReanchor <> invalid then return
    if m.view <> "player" or m.playPlan = invalid or m.trackDialog <> invalid then return
    if m.video.state <> "playing" and m.video.state <> "paused" then return
    cue = PlayerCurrentCue()
    action = SiloUIPlayerAction(m.video.playbackActionButtonSelected, cue, m.introDismissed, NumberOr(m.playPlan.timelineOffsetMs, 0))
    if action = invalid then return
    if action.kind = "tracks"
        PlayerShowTracks()
    else if action.kind = "seek"
        if not PlayerSeekTo(action.seconds*1000#+NumberOr(m.playPlan.timelineOffsetMs,0)) then return
        if m.seekReanchor <> invalid
            m.seekReanchor.marker = {kind:"native_skip"}
            return
        end if
        if m.video.state = "paused" and m.playPlan.transport <> "silo_compat" then m.video.control = "resume"
        m.introDismissed = true
        m.playerCue.visible = false
        PlayerUpdateNativeActions(cue)
        ' The selected native button is now disabled; return remote ownership
        ' to Video after replacing its actions, as when closing the track list.
        PlayerPlaybackFocus()
    else if action.kind = "next"
        PlayerAdvance()
    end if
end sub

sub PlayerLoadMarkers()
    if m.view <> "player" or m.provider <> "silo" or m.playPlan = invalid or m.markerLookupStarted = true then return
    if type(m.playMarkers) = "roArray"
        if m.playMarkers.Count() > 0 then return
    end if
    m.markerLookupStarted = true
    Api("markers", {itemId:m.playItem.itemId}, "play_markers", m.playToken)
end sub


function PlayerSpeedQuality(version as Object) as String
    quality = SiloUISettingsPreferences(m.preferences).quality
    explicit = m.qualityExplicit = true
    resolution = version.resolution
    if type(resolution) <> "roString" and type(resolution) <> "String" then return quality
    mode = PlayerVideoMode()
    return SiloUISpeedQuality(m.provider, quality, explicit, resolution, mode)
end function

' One attempt per Home load: cycling the carousel never churns allocations.
sub PlayerSyncHeroPrebuffer()
    if type(m.heroItem) = "roAssociativeArray" then if m.heroItem.homeCached = true then return
    if SiloUIPlaybackAdmissionBlocked() then return
    if m.compatPreparation <> invalid or m.compatPlayAttempt <> invalid then return
    if m.speculationDisabled = true then return
    if m.view <> "home" then return
    eligible = false
    if m.heroItem <> invalid then eligible = SiloUISpeedHero(m.homeRows, TextOr(m.heroItem.itemId), m.view, m.zone)
    if m.top.memoryPressure >= 80 then eligible = false
    if not eligible
        PlayerDiscardPrebuffer()
        return
    end if
    if m.provider <> "silo" or m.playLoading = true or m.heroPrebufferAttempt = true then return
    m.heroPrebufferAttempt = true
    m.playToken = m.playToken + 1
    m.heroPrebufferRequest = {token: m.playToken, generation: m.generation, itemId: m.heroItem.itemId}
    Api("detail", {itemId: m.heroItem.itemId}, "play_hero_detail", m.heroPrebufferRequest)
end sub

sub onPlayerMemoryPressure()
    SiloUIMemoryPressure()
end sub


function PlayerVideoMode() as String
    try
        mode = CreateObject("roDeviceInfo").GetVideoMode()
        if type(mode) = "String" or type(mode) = "roString" then return mode
    catch exception
    end try
    return ""
end function

' Video consumes transport keys even with enableUI=false. A peer must own
' custom remote handling, including after track and chapter dialogs close.
sub PlayerPlaybackFocus()
    if m.seekReanchor <> invalid
        m.seekReanchor.peer.setFocus(true)
        return
    end if
    if m.transportEnabled = true and m.manualFocus <> invalid
        m.manualFocus.setFocus(true)
    else
        m.video.setFocus(true)
    end if
end sub

' These observations belong only to the current foreground ContentNode.
sub PlayerOriginalClear()
    if m.originalPlayback <> invalid and m.video <> invalid then m.video.SetFields({control:"stop"})
    m.originalPlayback = invalid
    m.originalClock = invalid
    m.originalContent = invalid
    m.originalBinding = invalid
    if m.originalTimer <> invalid then m.originalTimer.control = "stop"
    if m.video <> invalid and not PlayerSeekPausePending() then m.video.mute = false
end sub

sub PlayerOriginalApply(result as Object)
    m.originalPlayback = result.state
    if result.command = invalid then return
    if result.command.kind = "select"
        m.video.mute = true
        m.video.audioTrack = result.command.trackId
    else if result.command.kind = "restart"
        ' Restart only the native load; keep the same owned lease and deadline.
        m.originalGeneration = m.originalPlayback.generation
        m.originalFreshState = false
        m.originalDrained = false
        m.originalOldInventory = SiloUIOriginalInventorySignature(m.video.availableAudioTracks)
        m.nativeHdrMode = invalid
        m.nativeVideoSize = invalid
        m.video.mute = true
        m.video.SetFields({control:"stop"})
        m.video.SetFields({control:"play"})
    else if result.command.kind = "recover"
        reason = "decoder_failure"
        if result.command.reason = "startup_timeout" or result.command.reason = "stall_timeout" then reason = "buffering_timeout"
        if not PlayerRecoverNativeFailure(reason)
            failure = PlayerFailureResult({},m.playPlan)
            PlayerClose(false)
            stage = "native"
            if reason = "buffering_timeout" then stage = "timeout"
            PlayerShowFailure(stage,failure)
        end if
    end if
end sub

sub PlayerOriginalInventory(freshAudio = false as Boolean)
    if m.originalPlayback = invalid or m.originalClock = invalid then return
    if m.video.content = invalid or m.originalContent = invalid then return
    if not m.video.content.isSameNode(m.originalContent) then return
    raw = m.video.availableAudioTracks
    empty = type(raw) <> "roArray"
    if type(raw) = "roArray" then empty = raw.Count() = 0
    if empty then m.originalDrained = true
    if m.video.state = "buffering" then m.originalFreshState = true
    if m.originalFreshState <> true then return
    if m.originalPlayback.phase = "restarting" and m.video.state = "buffering"
        PlayerOriginalObserve()
        if m.originalPlayback = invalid then return
    end if
    sameContent = false
    if m.originalPlayback.restartCount = 1 and m.originalPlayback.initialRestartMapping = true and m.originalPlayback.seenBuffering = true and type(m.originalBinding) = "roAssociativeArray"
        if not PlayerOriginalBindingValid()
            PlayerOriginalRejectBinding()
            return
        end if
        sameContent = true
    end if
    if m.originalDrained <> true and not freshAudio and not sameContent and SiloUIOriginalInventorySignature(raw) = m.originalOldInventory then return
    event = {kind:"inventory",token:m.playToken,generation:m.originalGeneration,nowMs:m.originalClock.TotalMilliseconds(),inventory:raw,freshInventory:freshAudio or m.originalDrained = true}
    if sameContent
        event.provenance = "same_content_restart"
        event.bindingValidated = true
    end if
    PlayerOriginalApply(SiloUIOriginalReduce(m.originalPlayback,event))
end sub

sub PlayerOriginalObserve()
    if m.originalPlayback = invalid or m.originalClock = invalid then return
    if m.video.content = invalid or m.originalContent = invalid then return
    if not m.video.content.isSameNode(m.originalContent) then return
    if m.video.state = "buffering" then m.originalFreshState = true
    if m.originalFreshState <> true and m.video.state <> "finished" and m.video.state <> "error" then return
    if m.originalPlayback.mappingProvenance = "same_content_restart"
        if not PlayerOriginalBindingValid()
            PlayerOriginalRejectBinding()
            return
        end if
        if SiloUIOriginalInventorySignature(m.video.availableAudioTracks) <> m.originalPlayback.inventorySignature
            PlayerOriginalInventory()
            if m.originalPlayback = invalid then return
        end if
    end if
    event = {kind:"observation",token:m.playToken,generation:m.originalGeneration,nowMs:m.originalClock.TotalMilliseconds(),nativeState:m.video.state,positionMs:Int(m.video.position*1000),audioTrack:m.video.currentAudioTrack,audioFormat:m.video.audioFormat,outputFingerprint:m.originalOutputFingerprint}
    PlayerOriginalApply(SiloUIOriginalReduce(m.originalPlayback,event))
    if m.originalPlayback <> invalid
        if m.originalPlayback.phase = "verified_playing"
            if m.pauseRestoreMuted <> true then m.video.mute = false
            PlayerRestorePausedIntent()
        end if
    end if
end sub

sub onOriginalPlaybackTimer()
    if m.view <> "player" or m.recoveringNative = true or m.originalPlayback = invalid then return
    m.originalOutputFingerprint = PlayerOriginalOutputFingerprint()
    PlayerOriginalInventory()
    PlayerOriginalObserve()
    if m.originalPlayback = invalid then return
    event = {kind:"tick",token:m.playToken,generation:m.originalGeneration,nowMs:m.originalClock.TotalMilliseconds(),nativeState:m.video.state}
    PlayerOriginalApply(SiloUIOriginalReduce(m.originalPlayback,event))
end sub

function PlayerOriginalOutputFingerprint() as String
    try
        device = CreateObject("roDeviceInfo")
        details = device.GetModelDetails()
        os = device.GetOSVersion()
        display = device.GetDisplayProperties()
        if type(details) <> "roAssociativeArray" or type(os) <> "roAssociativeArray" or type(display) <> "roAssociativeArray" then return ""
        model = TextOr(device.GetModel())
        mode = TextOr(device.GetVideoMode())
        if model.Trim() = "" or TextOr(details.ModelNumber).Trim() = "" or mode.Trim() = "" then return ""
        for each field in ["major","minor","revision","build"]
            if TextOr(os[field]).Trim() = "" then return ""
        end for
        if type(display.Hdr10) <> "Boolean" and type(display.Hdr10) <> "roBoolean" then return ""
        fingerprint = model + "/" + TextOr(details.ModelNumber)
        fingerprint += "/" + TextOr(os.major) + "." + TextOr(os.minor) + "." + TextOr(os.revision) + "." + TextOr(os.build) + "/" + mode
        if display.Hdr10 = true then fingerprint += "/hdr10"
        return fingerprint
    catch exception
    end try
    return ""
end function

' This binding remains on the render thread. Its URL never enters policy/events.
function PlayerOriginalPlanIdentity(plan as Object) as String
    context = plan.siloPlayback
    if type(context) <> "roAssociativeArray" then context = {}
    return FormatJson({provider:plan.provider,sourceId:plan.sourceId,itemId:plan.itemId,fileId:plan.versionId,sessionId:plan.sessionId,planId:plan.planId,playbackAttemptId:context.playbackAttemptId,contextSourceId:context.sourceId,contextProfileId:context.profileId,contextFileId:context.fileId,contextSessionId:context.sessionId,contextPlanId:context.planId,planAttemptId:context.planAttemptId,planAttemptKey:context.planAttemptKey})
end function

function PlayerOriginalCaptureBinding() as Dynamic
    if m.originalPlayback = invalid or m.playPlan = invalid or m.video = invalid or m.originalContent = invalid then return invalid
    content = m.video.content
    if content = invalid then return invalid
    if not content.isSameNode(m.originalContent) then return invalid
    if TextOr(content.url) = "" or content.streamFormat <> "mkv" then return invalid
    if TextOr(m.playPlan.url) <> content.url then return invalid
    context = m.playPlan.siloPlayback
    if type(context) <> "roAssociativeArray" then return invalid
    if context.playbackAttemptId <> m.originalPlayback.descriptor.playbackAttemptId then return invalid
    return {video:m.video,content:content,url:content.url,streamFormat:content.streamFormat,token:m.playToken,ownerSignature:FormatJson(SiloUIOwner()),planSignature:PlayerOriginalPlanIdentity(m.playPlan),descriptorSignature:FormatJson(m.originalPlayback.descriptor),output:PlayerOriginalOutputFingerprint()}
end function

function PlayerOriginalBindingValid() as Boolean
    binding = m.originalBinding
    if type(binding) <> "roAssociativeArray" or m.originalPlayback = invalid or m.playPlan = invalid then return false
    if m.video = invalid or m.video.content = invalid or m.originalContent = invalid then return false
    if not m.video.isSameNode(binding.video) then return false
    if not m.video.content.isSameNode(binding.content) then return false
    if not m.originalContent.isSameNode(binding.content) then return false
    if TextOr(m.playPlan.url) <> binding.url then return false
    if m.video.content.url <> binding.url or m.video.content.streamFormat <> binding.streamFormat or m.playPlan.streamFormat <> binding.streamFormat then return false
    if m.playToken <> binding.token or FormatJson(SiloUIOwner()) <> binding.ownerSignature then return false
    if PlayerOriginalPlanIdentity(m.playPlan) <> binding.planSignature then return false
    if FormatJson(m.playPlan.originalPlayback) <> binding.descriptorSignature or FormatJson(m.originalPlayback.descriptor) <> binding.descriptorSignature then return false
    if PlayerOriginalOutputFingerprint() <> binding.output or binding.output <> m.originalPlayback.descriptor.outputFingerprint then return false
    return true
end function

sub PlayerOriginalRejectBinding()
    PlayerOriginalApply({state:m.originalPlayback,command:{kind:"recover",reason:"binding_changed"}})
end sub

' Resanitize at capture and display; copy only bounded presentation facts.
function PlayerStartResponseFacts(raw as Dynamic) as Dynamic
    if type(raw) <> "roAssociativeArray" then return invalid
    facts = {}
    status = SpField(raw,"httpStatus")
    if SpNumber(status,599,true)
        if status < 100 then return invalid
        facts["httpStatus"] = status
    else if status = "unknown"
        facts["httpStatus"] = "unknown"
    else
        return invalid
    end if
    allowed = {protocol:["v3","other","missing","null","invalid"],outcome:["plan","playable","terminal","adaptation_unavailable","other","missing","null","invalid"],sessionId:["missing","null","empty","valid","invalid"],planSessionId:["missing","null","empty","valid","invalid","unavailable"]}
    for each name in allowed
        value = SpField(raw,name)
        if type(value) <> "String" and type(value) <> "roString" then return invalid
        found = false
        for each item in allowed[name]
            if value = item then found = true:exit for
        end for
        if not found then return invalid
        facts[name] = value
    end for
    for each name in ["playbackPlanPresent","playbackPlanObject","terminalShapeValid"]
        value = SpField(raw,name)
        if not SpBool(value) then return invalid
        facts[name] = value
    end for
    return facts
end function

function PlayerFailureButtons() as Object
    buttons = ["OK","Device info"]
    if PlayerStartResponseFacts(m.playbackFailureResponseFacts) <> invalid then buttons.Push("Response info")
    if SiloStartRequestFacts(m.playbackFailureRequestFacts) <> invalid then buttons.Push("Request info")
    if SiloStartAttempts(m.playbackFailureAttempts).Count() > 0 then buttons.Push("Start attempts")
    return buttons
end function

function PlayerStartResponseMessage(facts as Object) as String
    present = "No":objectPlan = "No":terminalShape = "No"
    if facts.playbackPlanPresent then present = "Yes"
    if facts.playbackPlanObject then objectPlan = "Yes"
    if facts.terminalShapeValid then terminalShape = "Yes"
    lines = ["HTTP " + facts.httpStatus.ToStr() + " · Protocol " + facts.protocol,"Outcome " + facts.outcome,"Session ID " + facts.sessionId,"Plan present " + present + " · Object " + objectPlan,"Plan session ID " + facts.planSessionId,"Terminal shape valid " + terminalShape,"Facts do not confirm cleanup."]
    return lines.Join(Chr(10))
end function

' Standard modal remains visible until OK or Back. Capture focus after any
' player cleanup so its dialog outlives the return-view transition.
sub PlayerShowFailure(stage as String, result as Dynamic)
    PlayerSetPlaybackStatus("")
    if m.playbackFailureDialog <> invalid then m.playbackFailureDialog.close = true
    dialog = CreateObject("roSGNode", "Dialog")
    dialog.title = "Playback error"
    dialog.message = SiloUIPlaybackFailureMessage(stage,result)
    if stage = "session" and SpField(result,"errorCode") = "cleanup_unconfirmed" then dialog.message = "#3004: Previous playback cleanup is unconfirmed. Restart the app before playing again."
    if SpField(result,"errorCode") = "allocation_identity_unknown" then dialog.message = "#3004: Playback session identity or cleanup could not be confirmed; new playback is paused. End the session on your server before restarting the app. Restart alone does not confirm cleanup. Return to browsing or photograph Device info."
    if stage = "session" and SpField(result,"errorCode") = "cleanup_pending" then dialog.message = "#3004: Previous playback cleanup is pending. Retry session cleanup in Settings before playing again."
    m.playbackFailureAttempts = SiloStartAttempts(SpField(result,"startAttempts"))
    m.playbackFailureRequestFacts = SiloStartRequestFacts(SpField(result,"startRequestFacts"))
    m.playbackFailureResponseFacts = PlayerStartResponseFacts(SpField(result,"startResponseFacts"))
    m.playbackFailureResponseTitle = "Response info"
    purpose = SpField(result,"startResponsePurpose")
    if purpose = "play_start" then m.playbackFailureResponseTitle = "Play Start response"
    if purpose = "play_prebuf" then m.playbackFailureResponseTitle = "Preload Start response"
    if purpose = "play_recover_version" then m.playbackFailureResponseTitle = "Recovery Start response"
    if purpose = "audio_start" then m.playbackFailureResponseTitle = "Audio Start response"
    dialog.buttons = PlayerFailureButtons()
    m.playbackFailureMessage = dialog.message
    m.playbackFailureInfo = false
    dialog.observeField("buttonSelected","onPlayerFailureChoice")
    dialog.observeField("wasClosed","onPlayerFailureClosed")
    m.playbackFailureReturn = {view:m.view,zone:m.zone,generation:m.generation,sourceId:m.sourceId,profileId:m.profileId,provider:m.provider}
    m.playbackFailureDialog = dialog
    m.playbackFailureSequence = Int(NumberOr(m.playbackFailureSequence,0)) + 1
    m.playbackFailureReportFence = invalid
    m.playbackFailureReported = false
    m.top.dialog = dialog
    ' Show the number first. Reporting is optional and never blocks dismissal.
    code = SiloUIPlaybackFailureCode(stage,result)
    if Left(code,1) = "1" or m.provider <> "silo" then return
    if type(result) <> "roAssociativeArray" then return
    report = result.report
    if type(report) <> "roAssociativeArray" then return
    if TextOr(report.installationId) = "" or TextOr(report.playbackAttemptId) = "" then return
    if type(result.reportOwner) = "roAssociativeArray"
        owner = result.reportOwner
        if owner.sourceId <> m.sourceId or owner.profileId <> m.profileId or owner.generation <> m.generation then return
    end if
    descriptor = {installationId:TextOr(report.installationId),playbackAttemptId:TextOr(report.playbackAttemptId)}
    if TextOr(report.sessionId) <> "" then descriptor["sessionId"] = TextOr(report.sessionId)
    fence = {token:m.playbackFailureSequence,generation:m.generation,sourceId:m.sourceId,profileId:m.profileId}
    m.playbackFailureReportFence = fence
    params = {report:descriptor,supportCode:code,errorCode:TextOr(result.errorCode)}
    native = SiloUIPlaybackNativeErrorNumber(result)
    if native <> "" then params.errorCode = "roku_native_" + native
    if TextOr(result.reason) <> "" then params.reason = TextOr(result.reason)
    Api("playback_error_report",params,"play_error_report",fence)
end sub

' Capture the owned attempt before PlayerClose clears the private plan.
function PlayerFailureResult(result as Dynamic, plan as Dynamic) as Object
    output = {errorCode:"native_playback_failed"}
    if SiloUIPlaybackNativeErrorNumber({nativeCode:m.playNativeErrorCode}) <> "" then output["nativeCode"] = m.playNativeErrorCode
    if type(result) = "roAssociativeArray"
        if TextOr(result.errorCode) <> "" then output.errorCode = TextOr(result.errorCode)
        if TextOr(result.reason) <> "" then output.reason = TextOr(result.reason)
    end if
    if type(plan) <> "roAssociativeArray" then return output
    context = plan.siloPlayback
    if type(context) <> "roAssociativeArray" then return output
    if plan.provider <> "silo" or plan.sourceId <> m.sourceId or context.sourceId <> m.sourceId or context.profileId <> m.profileId then return output
    if plan.sessionId <> context.sessionId then return output
    if TextOr(context.installationId) = "" or TextOr(context.playbackAttemptId) = "" then return output
    output["startAttempts"] = SiloStartAttempts(SpField(plan,"startAttempts"))
    output["startRequestFacts"] = SiloStartRequestFacts(SpField(plan,"startRequestFacts"))
    output.report = {installationId:TextOr(context.installationId),playbackAttemptId:TextOr(context.playbackAttemptId)}
    if TextOr(context.sessionId) <> "" then output.report["sessionId"] = TextOr(context.sessionId)
    output.reportOwner = {sourceId:m.sourceId,profileId:m.profileId,generation:m.generation}
    return output
end function

sub PlayerFailureReportResult(result as Object, data as Object, extra as Dynamic)
    if type(extra) <> "roAssociativeArray" or type(m.playbackFailureReportFence) <> "roAssociativeArray" then return
    if m.playbackFailureDialog = invalid or m.playbackFailureReported = true then return
    fence = m.playbackFailureReportFence
    if extra.token <> fence.token or extra.generation <> fence.generation or extra.sourceId <> fence.sourceId or extra.profileId <> fence.profileId then return
    if fence.generation <> m.generation or fence.sourceId <> m.sourceId or fence.profileId <> m.profileId then return
    if m.top.dialog = invalid or m.playbackFailureDialog.close = true then return
    if not m.playbackFailureDialog.isSameNode(m.top.dialog) then return
    if result.ok <> true or data.reported <> true then return
    m.playbackFailureReported = true
    m.playbackFailureMessage = m.playbackFailureMessage + Chr(10) + "Report sent to your Silo server."
    if m.playbackFailureInfo <> true then m.playbackFailureDialog.message = m.playbackFailureMessage
end sub

sub onPlayerFailureChoice(event = invalid as Dynamic)
    if event = invalid or m.playbackFailureDialog = invalid then return
    if not m.playbackFailureDialog.isSameNode(event.getRoSGNode()) then return
    if m.top.dialog = invalid or m.playbackFailureDialog.close = true then return
    if not m.playbackFailureDialog.isSameNode(m.top.dialog) then return
    back = m.playbackFailureReturn
    if type(back) <> "roAssociativeArray" then return
    if back.generation <> m.generation or back.view <> m.view or back.sourceId <> m.sourceId or back.profileId <> m.profileId or back.provider <> m.provider
        m.playbackFailureDialog.close = true
        return
    end if
    choice = m.playbackFailureDialog.buttonSelected
    if not SpNumber(choice,4,true) then return
    if m.playbackFailureInfo = true
        if choice <> 0 then return
        m.playbackFailureInfo = false
        ' buttonSelected is read-only and may retain zero after Back. A fresh
        ' main dialog guarantees its first OK produces a field notification.
        PlayerFailurePanel("Playback error",m.playbackFailureMessage,PlayerFailureButtons())
    else if choice = 1
        m.playbackFailureInfo = true
        PlayerFailurePanel("Device info",PlayerDeviceSupportSnapshot(),["Back"])
    else if choice = 2 and PlayerStartResponseFacts(m.playbackFailureResponseFacts) <> invalid
        facts = PlayerStartResponseFacts(m.playbackFailureResponseFacts)
        if facts = invalid then return
        m.playbackFailureInfo = true
        PlayerFailurePanel(m.playbackFailureResponseTitle,PlayerStartResponseMessage(facts),["Back"])
    else if choice = PlayerFailureButtons().Count()-1 and SiloStartAttempts(m.playbackFailureAttempts).Count() > 0
        m.playbackFailureInfo = true
        PlayerFailurePanel("Start attempts",PlayerStartAttemptsMessage(m.playbackFailureAttempts),["Back"])
    else if choice = 2 or choice = 3
        expected = 2
        if PlayerStartResponseFacts(m.playbackFailureResponseFacts) <> invalid then expected = 3
        if choice <> expected then return
        facts = SiloStartRequestFacts(m.playbackFailureRequestFacts)
        if facts = invalid then return
        m.playbackFailureInfo = true
        PlayerFailurePanel("Request info",PlayerStartRequestMessage(facts),["Back"])
    else
        m.playbackFailureDialog.close = true
    end if
end sub

sub onPlayerFailureClosed(event = invalid as Dynamic)
    if event = invalid or m.playbackFailureDialog = invalid then return
    if not m.playbackFailureDialog.isSameNode(event.getRoSGNode()) then return
    if m.top.dialog <> invalid
        if not m.playbackFailureDialog.isSameNode(m.top.dialog) then return
    end if
    back = m.playbackFailureReturn
    m.playbackFailureDialog = invalid
    m.playbackFailureAttempts = invalid
    m.playbackFailureRequestFacts = invalid
    m.playbackFailureResponseFacts = invalid
    m.playbackFailureResponseTitle = invalid
    m.playbackFailureReturn = invalid
    m.playbackFailureReportFence = invalid
    if type(back) <> "roAssociativeArray" then return
    if back.view <> m.view or back.generation <> m.generation or back.sourceId <> m.sourceId or back.profileId <> m.profileId or back.provider <> m.provider then return
    if TextOr(back.zone) <> "" then SetZone(back.zone)
end sub


' Detail consent is memory-only and tied to the current file, audio and visit.
function PlayerExperimentalChoiceValid(choice as Dynamic, item as Dynamic, selected as String, audio as Dynamic, versions as Dynamic) as Boolean
    if type(choice) <> "roAssociativeArray" or type(item) <> "roAssociativeArray" then return false
    if m.provider <> "silo" or m.view <> "detail" or choice.kind <> "experimental_original" then return false
    if choice.visit <> m.detailToken or choice.sourceId <> m.sourceId or choice.profileId <> m.profileId or choice.generation <> m.generation then return false
    if TextOr(choice.fileId) = "" or choice.itemId <> TextOr(item.itemId) then return false
    if selected <> "" and selected <> choice.fileId then return false
    current = TextOr(m.detailSelectedVersion)
    currentAudio = m.detailAudioChoice
    if choice.scope = "episode"
        state = m.detailEpisode
        if type(state) <> "roAssociativeArray" then return false
        if not BrowseContextCurrent(state.context) or state.season <> m.detailSeasonRequest then return false
        if state.item.itemId <> choice.itemId or state.experimentalAvailable <> true then return false
        focused = DetailFocusedEpisode()
        if focused = invalid then return false
        if TextOr(focused.itemId) <> choice.itemId then return false
        if state.experimentalTicket = invalid then return false
        if state.experimentalTicket.probe <> choice.probe then return false
        current = TextOr(state.selected)
        currentAudio = state.audio
    end if
    if current <> "" and current <> choice.fileId then return false
    if choice.audioSignature <> FormatJson(audio) or choice.audioSignature <> FormatJson(currentAudio) then return false
    return SiloUIDetailExperimentalVersion(m.provider,item,versions,choice.fileId) = choice.fileId
end function

' Native playing can precede playStart seeking. Restore pause after its local
' timeline lands; a rebased provider stream legitimately starts at zero.
sub PlayerRestorePausedIntent()
    if m.seekReanchor <> invalid then return
    if m.view <> "player" or m.playPlan = invalid then return
    if m.pauseRestoreMuted = true and m.video.state = "paused"
        m.pauseRestoreMuted = false
        m.video.mute = false
    end if
    if m.audioRestorePause <> true or m.video.state <> "playing" then return
    if m.originalPlayback <> invalid
        if m.originalPlayback.phase <> "verified_playing" then return
    end if
    target = NumberOr(m.playPlan.startPositionMs,0)
    if NumberOr(m.video.position,0)*1000 < target-1000
        if m.pauseRestoreClock = invalid then m.pauseRestoreClock = CreateObject("roTimespan")
        return
    end if
    m.pauseRestoreClock = invalid
    m.audioRestorePause = false
    m.video.control = "pause"
end sub


' Nonfocusable status stays separate from temporary toasts and player controls.
sub PlayerSetPlaybackStatus(phase as String, plan = invalid as Dynamic)
    if m.playerStatusPanel = invalid or m.playerStatusTitle = invalid or m.playerStatusDetail = invalid then return
    status = SiloUIPlaybackStatus(phase,plan)
    m.playerStatusTitle.text = status.title
    m.playerStatusDetail.text = status.detail
    m.playerStatusPanel.visible = status.title <> ""
end sub

' On-demand public SDK facts only; none of these probes grant playback authority.
function PlayerDeviceSupportSnapshot() as String
    model = "Unknown":number = "Unknown":kind = "Unknown":osText = "Unknown":mode = "Unknown"
    hdr = invalid:avc = invalid:hevc = invalid:mp4 = invalid:ts = invalid
    device = invalid
    try
        device = CreateObject("roDeviceInfo")
    catch error
    end try
    if device <> invalid
        try
            model = PlayerSupportToken(device.GetModel())
        catch error
        end try
        try
            details = device.GetModelDetails()
            number = PlayerSupportToken(SpField(details,"ModelNumber"))
            value = SpField(details,"ModelType")
            if value = "TV" or value = "STB" then kind = value
        catch error
        end try
        try
            value = device.GetModelType()
            if value = "TV" or value = "STB" then kind = value
        catch error
        end try
        try
            os = device.GetOSVersion():parts = []
            for each key in ["major","minor","revision","build"]
                value = SpField(os,key)
                text = SiloText(value)
                if not CreateObject("roRegex","^[0-9]{1,8}$","").IsMatch(text) then parts = []:exit for
                parts.Push(text)
            end for
            if parts.Count() = 4 then osText = parts.Join(".")
        catch error
        end try
        try
            mode = PlayerSupportToken(device.GetVideoMode())
        catch error
        end try
        try
            hdr = device.GetDisplayProperties()
        catch error
        end try
        try
            avc = device.CanDecodeVideo({codec:"mpeg4 avc"})
        catch error
        end try
        try
            hevc = device.CanDecodeVideo({codec:"hevc"})
        catch error
        end try
        try
            mp4 = device.CanDecodeAudio({codec:"aac",container:"mp4",chcnt:2,passthru:0})
        catch error
        end try
        try
            ts = device.CanDecodeAudio({codec:"aac",container:"ts",chcnt:2,passthru:0})
        catch error
        end try
    end if
    lines = ["Photograph for support · Capability only",Left(m.playbackFailureMessage,6)+" · App "+RuntimeAppVersion(),"Model "+model+" / "+number+" / "+kind,"OS "+osText+" · Output "+mode,"HDR10 "+PlayerSupportBoolean(SpField(hdr,"Hdr10"))+" · HDR10+ "+PlayerSupportBoolean(SpField(hdr,"Hdr10Plus")),"HLG "+PlayerSupportBoolean(SpField(hdr,"HLG"))+" · Dolby Vision "+PlayerSupportBoolean(SpField(hdr,"DolbyVision")),"H264 "+PlayerSupportBoolean(SpField(avc,"result"))+" · HEVC "+PlayerSupportBoolean(SpField(hevc,"result")),"AAC MP4 stereo "+PlayerSupportBoolean(SpField(mp4,"result")),"AAC TS stereo "+PlayerSupportBoolean(SpField(ts,"result")),"No playback, HDR or audibility guarantee."]
    return lines.Join(Chr(10))
end function

function PlayerSupportToken(value as Dynamic) as String
    if type(value) <> "String" and type(value) <> "roString" then return "Unknown"
    if not CreateObject("roRegex","^[A-Za-z0-9._-]{1,24}$","").IsMatch(value) then return "Unknown"
    return value
end function

function PlayerSupportBoolean(value as Dynamic) as String
    if type(value) <> "Boolean" and type(value) <> "roBoolean" then return "Unknown"
    if value then return "Yes"
    return "No"
end function


' Source-wide previews are offered only to this attempt's negotiated dispatcher.
function PlayerSeekOriginMs() as Double
    origin = NumberOr(m.playPlan.timelineOffsetMs,0)
    if m.seekReanchorEnabled <> true or m.playPlan.provider <> "silo" or m.playPlan.transport = "silo_compat" then return origin
    if SiloSeekDescriptor(m.playPlan,SiloUIOwner()) <> invalid then return 0
    return origin
end function


function PlayerSeekPausePending() as Boolean
    if m.seekReanchor = invalid then return false
    return m.seekReanchor.desiredPaused = true and (m.seekReanchor.phase = "binding" or m.seekReanchor.phase = "pausing")
end function

' Foreground Play waits for owned speculative allocation results, including
' preloads retired by earlier navigation, before cleanup can be considered done.
sub PlayerDrainPrebufferForeground()
    wait = m.prebufferForeground
    if wait = invalid then return
    owner = wait.owner
    if wait.token <> m.playToken or m.playLoading <> true or m.transitionIntent <> invalid or owner.provider <> m.provider or owner.sourceId <> m.sourceId or owner.profileId <> m.profileId or owner.generation <> m.generation
        m.prebufferForeground = invalid
        return
    end if
    if m.cleanupFailed = true or m.unresolvedAllocation <> invalid
        m.prebufferForeground = invalid
        m.playToken = m.playToken + 1
        m.playLoading = false
        PlayerSetPlaybackStatus("")
        SiloUIShowPlaybackAdmissionFailure()
        return
    end if
    for each key in m.pending
        entry = m.pending[key]
        if entry.purpose = "play_prebuf" then return
    end for
    if SiloUIPlaybackAdmissionBlocked() or wait.params = invalid then return
    m.prebufferForeground = invalid
    ApiOwned("playback_start",wait.params,"play_start",wait.token,owner)
end sub

function PlayerRequestYes(value as Boolean) as String
    if value then return "yes"
    return "no"
end function

function PlayerStartRequestMessage(facts as Object) as String
    source = "Source " + facts.videoCodec
    if facts.DoesExist("width") and facts.DoesExist("height") then source += " " + facts.width.ToStr() + "x" + facts.height.ToStr()
    dv = "DV metadata unknown"
    if facts.DoesExist("dvProfile") then dv = "DV profile " + facts.dvProfile.ToStr()
    if facts.DoesExist("dvBaseCompatibility") then dv += " · base compatibility " + facts.dvBaseCompatibility.ToStr()
    hevc = "HEVC admitted " + PlayerRequestYes(facts.hevcAdmitted)
    if facts.DoesExist("hlsHevcAdmitted") then hevc = "HEVC device/HLS " + PlayerRequestYes(facts.hevcAdmitted) + "/" + PlayerRequestYes(facts.hlsHevcAdmitted)
    copyMpegts = "unknown"
    if facts.DoesExist("copyMpegts") then copyMpegts = PlayerRequestYes(facts.copyMpegts)
    lines = [source,dv,"Audio " + facts.audioCodec + " · Quality " + facts.quality + " · Source " + facts.selection,"Device/output HDR10 " + facts.hdr10 + " · DV " + facts.dolbyVision,hevc,"HLS enabled/supported " + PlayerRequestYes(facts.hlsEnabled) + "/" + PlayerRequestYes(facts.hlsSupported) + " · Original " + PlayerRequestYes(facts.originalEnabled) + "/" + PlayerRequestYes(facts.originalSupported),"hls_copy_mpegts_v1 " + copyMpegts,"native_hls_mpegts_v1 " + PlayerRequestYes(facts.mpegts),"native_hls_separate_audio_v1 " + PlayerRequestYes(facts.separateAudio),"server_dv7_to_dv81_v1 " + PlayerRequestYes(facts.dv7To81),"Last Start request evidence; not output proof."]
    return lines.Join(Chr(10))
end function

' Fallback for remotes whose Back event bubbles to the Scene. Never consume a
' foreign modal or restore a stale return view; wasClosed retains that fence.
function PlayerFailureBack() as Boolean
    if m.playbackFailureDialog = invalid or m.top.dialog = invalid then return false
    if not m.playbackFailureDialog.isSameNode(m.top.dialog) then return false
    if m.playbackFailureDialog.close = true then return false
    m.playbackFailureDialog.close = true
    return true
end function

' Assigning a fresh Dialog gives its buttons native focus and resets the
' read-only selection field. Late callbacks from the closed node stay fenced.
sub PlayerFailurePanel(title as String, message as String, buttons as Object)
    old = m.playbackFailureDialog
    dialog = CreateObject("roSGNode", "Dialog")
    dialog.title = title
    dialog.message = message
    dialog.buttons = buttons
    dialog.observeField("buttonSelected","onPlayerFailureChoice")
    dialog.observeField("wasClosed","onPlayerFailureClosed")
    m.playbackFailureDialog = dialog
    m.top.dialog = dialog
    old.close = true
end sub

function PlayerStartAttemptsMessage(raw as Dynamic) as String
    attempts = SiloStartAttempts(raw)
    if attempts.Count() = 0 then return ""
    message = ""
    indices = [0]
    if attempts.Count() > 1 then indices.Push(attempts.Count()-1)
    for each index in indices
        attempt = attempts[index]
        label = "First Start"
        if index > 0 then label = "Last Start"
        if message <> "" then message = message + Chr(10) + Chr(10)
        message = message + label + ": " + attempt.request.quality
        message = message + Chr(10) + "HTTP " + attempt.httpStatus.ToStr() + " / " + attempt.outcome
        message = message + Chr(10) + "Original: " + attempt.originalReason
        if attempt.DoesExist("validationStage") then message += Chr(10) + "Validation: " + attempt.validationStage + " / " + attempt.validationReason
        source = "Source " + attempt.request.videoCodec
        if attempt.request.DoesExist("width") and attempt.request.DoesExist("height") then source += " " + attempt.request.width.ToStr() + "x" + attempt.request.height.ToStr()
        message = message + Chr(10) + source + " / " + attempt.request.audioCodec
    end for
    return message
end function
