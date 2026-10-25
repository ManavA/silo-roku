' Compatibility continuation. Public receipts stay credential-free;
' one-use private payloads bind only the exact retained holder and content.
function SiloUICompatStockQualification(state as Object, prepared=invalid as Dynamic) as Dynamic
    if SpField(state,"eligibilityKind") <> "experimental_query_p7_hdr10_fmp4_v1" then return invalid
    if not SpNumber(SpField(state.intent,"startPositionMs"),2147483646,true) or state.planGeneration <> 1 then return invalid
    qualification = SpField(prepared,"stockQualification")
    if not SpFields(qualification,["schemaVersion","kind","approved","sourceId","profileId","generation","sessionRevision","holderId","attemptId","planGeneration","origin","transportPolicy","transportEvidence","rootListenerRequired","fileId","mediaSourceId","audioOrdinal","audioStreamIndex"],["requestedStartPositionMs"]) then return invalid
    if qualification.schemaVersion <> 1 or qualification.kind <> "stock-p7-ac3-root-v1" then return invalid
    if qualification.approved <> true or qualification.rootListenerRequired <> true then return invalid
    for each name in ["sourceId","profileId","generation","sessionRevision"]
        if qualification[name] <> state.owner[name] then return invalid
    end for
    if qualification.holderId <> state.holderId or qualification.attemptId <> state.attemptId or qualification.planGeneration <> state.planGeneration then return invalid
    if not SpNumber(SpField(qualification,"requestedStartPositionMs",0),2147483646,true) or SpField(qualification,"requestedStartPositionMs",0) <> state.intent.startPositionMs then return invalid
    if qualification.fileId <> state.intent.fileId or qualification.audioOrdinal <> state.intent.audioTrackIndex then return invalid
    if not SpText(qualification.mediaSourceId,128) or not SpNumber(qualification.audioStreamIndex,2147483646,true) or not SpText(qualification.origin,2048) then return invalid
    if not SiloStockTransportPolicyValid(qualification.transportPolicy,qualification.transportEvidence,qualification.origin) then return invalid
    return SpCopy(qualification)
end function

function SiloUICompatStockLocalBinding(state as Object) as Dynamic
    if state.planGeneration <> 1 or state.intent.startPositionMs <> 0 or state.engine = invalid then return invalid
    if state.engine.ready <> true or state.engine.failed = true or state.engine.drainState <> "pending" then return invalid
    plan = {provider:"silo",transport:"silo_compat",sourceId:state.owner.sourceId,itemId:state.intent.itemId,versionId:state.intent.fileId,holderId:state.holderId,attemptId:state.attemptId,planGeneration:1,startPositionMs:0,timelineOffsetMs:0,subtitleMode:"off"}
    payload = {url:"http://127.0.0.1:34831/g1/master.m3u8",streamFormat:"hls",startPositionMs:0,headers:{},transport:"silo_compat",holderId:state.holderId,attemptId:state.attemptId,planGeneration:1}
    return {plan:plan,payload:payload}
end function

function SiloUICompatContinuation(entry as Object, result as Object) as Boolean
    if entry.purpose <> "play_start" or result.errorCode <> "compat_prepare_required" then return false
    c = result.compatContinuation
    if type(c) <> "roAssociativeArray" then return true
    kind = SpField(c,"eligibilityKind")
    if c.DoesExist("eligibilityKind")
        if not SpText(kind,64) then return true
        if kind <> "experimental_query_p8_ts_v1" and kind <> "experimental_query_p8_hdr10_fmp4_v1" and kind <> "experimental_query_p7_hdr10_fmp4_v1" and kind <> "experimental_query_p7_hdr10_aac_fmp4_v1" and kind <> "experimental_query_p8_hdr10_ac3_fmp4_v1" then return true
    end if
    if result.action <> "playback_start" then return true
    if result.ok <> false or result.plan <> invalid or c.schemaVersion <> 1 then return true
    if m.transitionIntent <> invalid or m.compatPreparation <> invalid or m.playLoading <> true or m.view = "player" then return true
    if entry.extra <> m.playToken or not SoScopeEqual(entry.owner,SiloUIOwner()) or not SoScopeEqual(result,entry.owner) or not SoScopeEqual(c.owner,entry.owner) then return true
    if not SpNumber(result.sessionRevision,2147483646,true) or c.owner.sessionRevision <> result.sessionRevision then return true
    if entry.owner.sessionRevision <> invalid and entry.owner.sessionRevision <> result.sessionRevision then return true
    job = entry.task.job
    if type(job) <> "roAssociativeArray" or job.action <> "playback_start" or not SoScopeEqual(job,entry.owner) then return true
    if not SpNumber(c.requestId,2147483646,true) or not SpNumber(c.owner.sessionRevision,2147483646,true) then return true
    if c.requestId <> result.requestId or c.requestId <> job.requestId or not SpOpaque(c.playbackAttemptId) then return true
    if type(c.nativeClosure) <> "roAssociativeArray" then return true
    if result.DoesExist("leaseUncertain")
        if not SpBool(result.leaseUncertain) or result.leaseUncertain <> false then return true
    end if
    closure = c.nativeClosure
    if closure.state = "not_allocated"
        if not SiloContains(["native_selection_lower_resolution","native_source_unproven"],c.reason) or closure.Count() <> 1 then return true
    else if closure.state = "acknowledged"
        if c.reason <> "native_routes_exhausted" or c.nativeSelectedFileId <> c.fileId then return true
        if not SpFields(closure,["state","sessionId","installationId","stopId","owner","requestId","playbackAttemptId"],[]) then return true
        if not SpFields(closure.owner,["provider","sourceId","profileId","generation","sessionRevision"],[]) then return true
        if not SpNumber(closure.requestId,2147483646,true) or not SpNumber(closure.owner.sessionRevision,2147483646,true) then return true
        if not SoScopeEqual(closure.owner,c.owner) or closure.owner.sessionRevision <> result.sessionRevision then return true
        if closure.requestId <> c.requestId or closure.playbackAttemptId <> c.playbackAttemptId then return true
        if not SpOpaque(closure.sessionId) or not SpOpaque(closure.installationId) then return true
        if not SpText(closure.stopId,36) then return true
        if not CreateObject("roRegex","^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$","").IsMatch(closure.stopId) then return true
    else
        return true
    end if
    if SpScope(m.compatNativeStopFailure) <> invalid then return true
    if m.playPlan <> invalid or m.prebuf <> invalid or m.audioPlan <> invalid or m.cleanupUnconfirmed = true or m.cleanupFailed = true then return true
    if m.audioSyncFlight <> invalid or m.audioSyncPending <> invalid then return true
    if m.cleanupTickets <> invalid
        if m.cleanupTickets.Count() <> 0 then return true
    end if
    for each key in m.pending
        pendingJob = m.pending[key].task.job
        if type(pendingJob) = "roAssociativeArray"
            if pendingJob.action = "playback_stop" then return true
        end if
        p = m.pending[key].purpose
        if p = "play_start" or p = "play_prebuf" or p = "play_recover" or p = "play_recover_version" or p = "audio_start" or p = "audio_select" or p = "seek_reanchor" or p = "subtitle_off" or p = "subtitle_select" then return true
    end for
    if m.video = invalid then return true
    if m.video.content <> invalid then return true
    params = job.params
    if type(params) <> "roAssociativeArray" then return true
    manualVersion = SiloUICompatFieldCount(c,"manualVersionSelection") = 1
    if SiloUICompatFieldCount(c,"manualVersionSelection") > 1 then return true
    if manualVersion and kind <> "experimental_query_p8_ts_v1" then return true
    manualAC3 = kind = "experimental_query_p8_hdr10_ac3_fmp4_v1"
    p7 = kind = "experimental_query_p7_hdr10_fmp4_v1" or kind = "experimental_query_p7_hdr10_aac_fmp4_v1"
    aac = kind = "experimental_query_p7_hdr10_aac_fmp4_v1"
    qualification = invalid
    if aac
        qualification = SiloCompatP7AACQualification(c.owner,SpField(c,"instanceQualification"))
        if qualification = invalid or SiloUICompatFieldCount(c,"instanceQualification") <> 1 or SiloUICompatFieldCount(params,"instanceQualification") <> 1 then return true
        if FormatJson(qualification) <> FormatJson(SpField(c,"instanceQualification")) or FormatJson(qualification) <> FormatJson(SpField(params,"instanceQualification")) then return true
    ' A dormant caller opt-in cannot qualify a non-AAC lane; it stays inert here.
    else if SiloUICompatFieldCount(c,"instanceQualification") <> 0
        return true
    end if
    autoCount = SiloUICompatFieldCount(c,"autoAudioSelection")
    if autoCount > 1 or SiloUICompatFieldCount(params,"autoAudioSelection") <> 0 then return true
    automatic = p7 and autoCount = 1
    if autoCount <> 0 and not automatic then return true
    if params.subtitleTrackId <> invalid or params.subtitleTrackIndex <> invalid then return true
    if manualAC3
        if c.requestedFileId <> c.fileId or c.nativeSelectedFileId <> c.fileId then return true
        if closure.state <> "not_allocated" or c.reason <> "native_source_unproven" then return true
        if not SpBool(params.experimentalOriginal) or params.experimentalOriginal <> true then return true
        if not SpBool(params.autoVersion) or params.autoVersion <> false then return true
        if params.speculativePrebuffer = true or params.originalDisabled = true then return true
        for each name in ["subtitleTrackId","subtitleTrackIndex","excludedVersionIds"]
            if SiloUICompatFieldCount(params,name) <> 0 then return true
        end for
        if not SpBool(c.autoVersion) or c.autoVersion <> false then return true
        if not PlayerExperimentalChoiceValid(m.playExperimentalChoice,m.playItem,m.playSelectedVersion,m.playAudioChoice,m.playVersions) then return true
        if TextOr(m.playSelectedVersion) <> c.fileId then return true
        detail = SpField(params,"detail")
        if not SiloObject(detail) or not SiloArray(SpField(detail,"versions")) then return true
        choice = SiloUIDetailAudioMatch(m.playAudioChoice,c.itemId,c.fileId,detail.versions)
        if choice = invalid then return true
        if params.audioTrackIndex <> c.audioTrackIndex or params.audioTrackId <> c.audioTrackId or choice.sourceOrdinal <> c.audioTrackIndex then return true
    else if p7
        if closure.state <> "not_allocated" or c.reason <> "native_source_unproven" then return true
        if not SpBool(m.playVersionExplicit) or m.playVersionExplicit <> false then return true
        if m.playExperimentalChoice <> invalid then return true
        if automatic
            if SiloUICompatFieldCount(c,"eligibilityKind") <> 1 then return true
            if SiloUICompatFieldCount(params,"autoVersion") <> 1 or SiloUICompatFieldCount(c,"autoVersion") <> 1 then return true
            if not SpBool(SpField(params,"autoVersion")) or SpField(params,"autoVersion") <> true then return true
            if not SpBool(SpField(c,"autoVersion")) or SpField(c,"autoVersion") <> true then return true
            if m.playAudioChoice <> invalid or TextOr(m.playSelectedVersion) <> "" then return true
            for each name in ["audioTrackId","audioTrackIndex","subtitleTrackId","subtitleTrackIndex","excludedVersionIds"]
                if SiloUICompatFieldCount(params,name) <> 0 then return true
            end for
        else
            if not SpBool(params.autoVersion) or params.autoVersion <> false or not SpBool(c.autoVersion) or c.autoVersion <> false then return true
            if TextOr(m.playSelectedVersion) <> c.fileId then return true
            choice = m.playAudioChoice
            if type(choice) <> "roAssociativeArray" or m.view <> "detail" then return true
            if choice.visit <> m.detailToken or choice.sourceId <> m.sourceId or choice.profileId <> m.profileId or choice.generation <> m.generation then return true
            detail = SpField(params,"detail")
            if not SiloObject(detail) or not SiloArray(SpField(detail,"versions")) then return true
            selected = SiloUIDetailAudioMatch(choice,c.itemId,c.fileId,detail.versions)
            if selected = invalid then return true
            if SiloUIDetailAudioMatch(choice,c.itemId,c.fileId,m.detailVersions) = invalid then return true
            if not SpNumber(c.audioTrackIndex,31,true) or selected.sourceOrdinal <> c.audioTrackIndex then return true
            if c.audioTrackId <> "file:"+c.fileId+":audio:"+Int(selected.sourceOrdinal).ToStr() then return true
            if params.audioTrackIndex <> c.audioTrackIndex or params.audioTrackId <> c.audioTrackId then return true
        end if
    else if manualVersion
        if not SiloCompatManualVersionValid(c,c.fileId) then return true
        if params.autoVersion <> false or not SpBool(params.autoVersion) then return true
        if c.requestedFileId <> c.fileId or c.nativeSelectedFileId <> c.fileId then return true
        if closure.state <> "not_allocated" or c.reason <> "native_source_unproven" then return true
        if TextOr(m.playSelectedVersion) <> c.fileId or m.playExperimentalChoice <> invalid then return true
        if c.manualVersionSelection.DoesExist("explicitAudioSelection")
            if not SiloUICompatExplicitAudioCurrent(c,params.detail) then return true
            if params.audioTrackId <> c.audioTrackId or params.audioTrackIndex <> c.audioTrackIndex then return true
        else
            if not SpBool(m.playVersionExplicit) or m.playVersionExplicit <> true then return true
            if m.playAudioChoice <> invalid then return true
            if params.audioTrackId <> invalid or params.audioTrackIndex <> invalid then return true
        end if
    else
        if params.autoVersion <> true or c.autoVersion <> true then return true
        if params.audioTrackId <> invalid or params.audioTrackIndex <> invalid then return true
        if m.playAudioChoice <> invalid or m.playExperimentalChoice <> invalid or TextOr(m.playSelectedVersion) <> "" then return true
    end if
    captions = kind = "experimental_query_p8_ts_v1" and c.subtitleMode = "on"
    if c.startPaused <> false or c.qualityPreference <> "original" then return true
    if not captions and c.subtitleMode <> "off" then return true
    if params.qualityPreference <> "original" or params.subtitleMode <> c.subtitleMode or c.qualityExplicit <> params.qualityExplicit then return true
    prefs = SiloUISettingsPreferences(m.preferences)
    if not manualAC3 and (prefs.quality <> "original" or (not captions and prefs.subtitles <> "off") or (captions and prefs.subtitles <> "always")) then return true
    if c.itemId <> TextOr(m.playItem.itemId) or c.itemId <> params.itemId or c.requestedFileId <> params.fileId then return true
    if c.reason = "native_source_unproven" and not manualAC3 and not manualVersion
        if not SiloArray(SpField(params.detail,"versions")) then return true
        if params.detail.versions.Count() <> 1 then return true
        if c.fileId <> c.requestedFileId or c.nativeSelectedFileId <> c.fileId then return true
        inventory = SiloNativeSelection(params.detail,m.sourceId,c.itemId,"")
        if inventory = invalid then return true
        if inventory.allowAlternateVersions <> true or inventory.allowedFileIds.Count() <> 1 or inventory.fileId <> c.fileId then return true
        if inventory.allowedFileIds[0] <> c.fileId then return true
    end if
    if c.startPositionMs <> params.startPositionMs or not SpNumber(c.startPositionMs,2147483646,true) then return true
    if SpField(c,"bandwidthCapKbps",0) <> SpField(params,"bandwidthCapKbps",0) then return true
    file = SiloPlaybackFile(params.detail,m.sourceId,c.itemId,c.fileId,c.startPositionMs)
    if file = invalid then return true
    if automatic
        selection = SpField(c,"autoAudioSelection")
        if not SiloUICompatAutoBasis(selection,file.version,c.itemId,c.fileId,kind) then return true
        fresh = SiloUICompatFreshAutoSelection(CreateObject("roDeviceInfo"),selection.basis,kind)
        if fresh = invalid or FormatJson(fresh) <> FormatJson(selection) then return true
        if selection.audio_track_id <> c.audioTrackId or selection.audio_track_index <> c.audioTrackIndex then return true
    end if
    if type(file.version.audioTracks) <> "roArray" then return true
    if not SpNumber(c.audioTrackIndex,file.version.audioTracks.Count()-1,true) then return true
    intent = {itemId:c.itemId,fileId:c.fileId,audioTrackId:c.audioTrackId,audioTrackIndex:c.audioTrackIndex,startPositionMs:c.startPositionMs,qualityPreference:"original",subtitleMode:c.subtitleMode}
    if params.DoesExist("bandwidthCapKbps") then intent["bandwidthCapKbps"] = params.bandwidthCapKbps
    if kind <> invalid then intent["eligibilityKind"] = kind
    if manualVersion
        intent["autoVersion"] = false:intent["manualVersionSelection"] = SpCopy(c.manualVersionSelection)
    end if
    if manualAC3 then intent["autoVersion"] = false
    if automatic
        intent["autoVersion"] = true
        intent["autoAudioSelection"] = SpCopy(selection)
    end if
    if m.compatPlayAttempt <> invalid then return true
    video = invalid:videos = SpField(file.version,"videoTracks")
    if SiloArray(videos) then if videos.Count() = 1 then video = videos[0]
    snapshot = SiloCompatSnapshotForKind(CreateObject("roDeviceInfo"),file.version.audioTracks[c.audioTrackIndex],kind,video)
    if aac then intent["instanceQualification"] = qualification
    proof = SiloCompatCandidate(params.detail,c.owner,intent,snapshot,kind,qualification)
    if proof = invalid then return true
    nativeFiles = SpCopy(SpField(params,"excludedVersionIds",[]))
    if closure.state = "acknowledged" then if not SiloContains(nativeFiles,c.fileId) then nativeFiles.Push(c.fileId)
    m.compatPlayAttempt = {owner:SpCopy(c.owner),playToken:m.playToken,itemId:c.itemId,fileId:c.fileId,requestId:c.requestId,playbackAttemptId:c.playbackAttemptId,compatibilityAttempted:true,phase:"admitted",resumeConsumed:false,nativeAttemptedFileIds:nativeFiles}
    if aac then m.compatPlayAttempt["instanceQualification"] = SpCopy(qualification)
    if automatic
        m.compatPlayAttempt["audioSelectionMode"] = "auto"
        m.compatPlayAttempt["autoAudioSelection"] = SpCopy(selection)
    end if
    holderId = SiloUICleanupUuid()
    if not SpOpaque(holderId) then m.compatPlayAttempt.phase = "failed":return true
    task = CreateObject("roSGNode", "SiloCompatTask")
    if task = invalid then m.compatPlayAttempt.phase = "failed":return true
    command = {action:"prepare",commandId:holderId+"-prepare",holderId:holderId,attemptId:c.playbackAttemptId,owner:c.owner,params:intent}
    m.compatPreparation = {task:task,holderId:holderId,attemptId:c.playbackAttemptId,owner:c.owner,token:m.playToken,commandId:command.commandId,prepareCommandId:command.commandId,closeSequence:0,phase:"preparing",intent:intent,detail:params.detail,qualityExplicit:c.qualityExplicit,requestedFileId:c.requestedFileId}
    if manualVersion
        m.compatPreparation["manualVersionSelection"] = SpCopy(c.manualVersionSelection)
        m.compatPreparation["autoVersion"] = false
        m.compatPlayAttempt["manualVersionSelection"] = SpCopy(c.manualVersionSelection)
    end if
    if aac then m.compatPreparation["instanceQualification"] = SpCopy(qualification)
    if kind <> invalid
        m.compatPreparation["eligibilityKind"] = kind
        m.compatPreparation["snapshot"] = SpCopy(proof.snapshot)
        m.compatPlayAttempt["eligibilityKind"] = kind
    end if
    if automatic
        m.compatPreparation["autoVersion"] = true
        m.compatPreparation["autoAudioSelection"] = SpCopy(selection)
    end if
    if manualAC3
        consent = {ticket:SpCopy(m.playExperimentalChoice),audio:SpCopy(m.playAudioChoice),itemId:c.itemId,fileId:c.fileId,audioTrackId:c.audioTrackId,audioTrackIndex:c.audioTrackIndex,holderId:holderId,attemptId:c.playbackAttemptId}
        m.compatPreparation["manualConsent"] = SpCopy(consent)
        m.compatPlayAttempt["manualConsent"] = SpCopy(consent)
    end if
    m.compatPreparation.prepareClock = CreateObject("roTimespan")
    SiloUICompatWatch(m.compatPreparation)
    m.compatPlayAttempt.phase = "preparing"
    task.observeField("result","onSiloUICompatResult")
    task.cancelled = false
    task.command = command
    task.control = "run"
    return true
end function

' Only fixed local enums may survive a preparation refusal or reach diagnostics.
function SiloUICompatPreparationError(result as Object) as String
    code = SpField(result,"errorCode")
    if SiloContains(["subtitle_selection_unsupported","subtitle_fetch_failed","unsupported_source","source_changed","audio_ambiguous","audio_required","unsupported_listener","source_mismatch","unsafe_recipe","preparation_failed","transport_failed","network_timeout","not_found","auth_required","unsupported_device","unsupported_protocol","unsupported_playback_protocol","unsupported_stream"],code) then return code
    return "preparation_failed"
end function

sub onSiloUICompatResult(event as Object)
    state = m.compatPreparation
    if state = invalid then return
    result = event.getData()
    if type(result) <> "roAssociativeArray" then return
    if result.holderId <> state.holderId or result.attemptId <> state.attemptId then return
    knownCommand = result.commandId = state.commandId
    if result.cancelled = true and state.closeSequence <= 1 and result.commandId = state.prepareCommandId and (result.phase = "closed" or result.phase = "refused") then knownCommand = true
    if not SoScopeEqual(result.owner,state.owner) then return
    if result.owner.sessionRevision <> state.owner.sessionRevision then return
    if result.phase = "binding" and state.phase <> "binding"
        stale = state.task.privateBinding
        if type(stale) = "roAssociativeArray"
            if stale.holderId = state.holderId and stale.attemptId = state.attemptId and stale.bindingNonce = result.bindingNonce and stale.planGeneration = result.planGeneration
                state.task.privateBinding = invalid
                stale.headers = invalid:stale.url = ""
            end if
        end if
        return
    end if
    if not knownCommand then return
    if state.phase = "stock_preparing" and (result.phase = "stock_context_refused" or result.phase = "refused")
        SiloUICompatStockAbort(state)
        return
    end if
    if result.phase = "seek_refused" or result.phase = "binding_refused"
        state.reanchorTarget = invalid:state.failurePending = true:state.failureStage = "session"
        if SiloContains(["source_changed","audio_changed","subtitle_changed","session_changed","invalid_seek"],result.errorCode) then state.resumeRefused = true
        if result.errorCode = "cleanup_unconfirmed"
            state.phase = "cleanup_pending":m.cleanupFailed = true:m.playLoading = false : PlayerSetPlaybackStatus("")
            Toast("Session cleanup pending. Retry in Settings.")
            return
        end if
        state.phase = "closing":state.closeSequence++
        state.commandId = state.holderId+"-close-"+state.closeSequence.ToStr()
        state.task.command = {action:"close",commandId:state.commandId,holderId:state.holderId,attemptId:state.attemptId,owner:state.owner,planGeneration:state.planGeneration,localRetired:state.localRetired=true,positionMs:SpField(state,"positionMs",state.intent.startPositionMs),isPaused:state.isPaused=true}
        return
    end if
    if (result.phase = "playing" or result.phase = "progress") and result.planGeneration = state.planGeneration
        state.reportInFlight = false
        if result.ok <> true
            state.reportFailed = true
            Toast("Playback progress could not be confirmed.")
            if result.phase = "playing"
                state.failureResult = {errorCode:result.errorCode,compatFailurePhase:result.compatFailurePhase,compatHttpStatus:result.compatHttpStatus}
                SiloUICompatFailure("session_unconfirmed")
            end if
        else if result.phase = "playing"
            state.activeConfirmed = result.activeConfirmed = true
        end if
        pending = state.pendingProgress:state.pendingProgress = invalid
        if pending <> invalid and state.phase = "playing" then SiloUICompatReport("progress",pending)
        return
    end if
    if result.phase = "binding" and state.phase = "binding"
        payload = state.task.privateBinding
        state.task.privateBinding = invalid
        if not SiloUICompatCurrent(state) or type(payload) <> "roAssociativeArray" then state.task.cancelled = true:return
        if result.ok <> true or result.bindingNonce <> state.bindingNonce or result.planGeneration <> state.planGeneration then state.task.cancelled = true:return
        if payload.bindingNonce <> state.bindingNonce or payload.holderId <> state.holderId or payload.attemptId <> state.attemptId or payload.planGeneration <> state.planGeneration then state.task.cancelled = true:return
        if not SoScopeEqual(payload.owner,state.owner) or payload.owner.sessionRevision <> state.owner.sessionRevision then state.task.cancelled = true:return
        if payload.transport <> "silo_compat" or payload.streamFormat <> "hls" or payload.timelineOffsetMs <> 0 or payload.startPositionMs <> state.intent.startPositionMs then state.task.cancelled = true:return
        if type(payload.headers) <> "roAssociativeArray" or payload.headers.Count() <> 1 or not SiloCompatPattern(payload.headers.Authorization,"^Bearer [!-~]+$",4103) then state.task.cancelled = true:return
        durationFile = SiloPlaybackFile(state.detail,state.owner.sourceId,state.intent.itemId,state.intent.fileId,state.intent.startPositionMs)
        if durationFile = invalid then state.task.cancelled = true:return
        plan = {provider:"silo",transport:"silo_compat",sourceId:state.owner.sourceId,itemId:state.intent.itemId,versionId:state.intent.fileId,holderId:state.holderId,attemptId:state.attemptId,planGeneration:state.planGeneration,startPositionMs:state.intent.startPositionMs,timelineOffsetMs:0,subtitleMode:"off"}
        if state.intent.subtitleMode = "on"
            caption = payload.compatCaption
            if not SiloUICompatCaptionBinding(caption,state) then state.task.cancelled = true:return
            plan.subtitleMode = "on"
            if caption.disposition = "ready"
                payload.subtitleTracks = [{Language:SiloUISubtitleLanguage(caption.track.language),Description:"Selected subtitle",TrackName:caption.uri}]
                plan["compatCaptionUri"] = caption.uri
            end if
        else if payload.DoesExist("compatCaption")
            state.task.cancelled = true:return
        end if
        state.phase = "playing"
        state.localRetired = false:state.playingSent = false:state.reportInFlight = false:state.activeConfirmed = false
        state.pendingProgress = invalid:state.reanchorTarget = invalid
        PlayerBind(payload,TextOr(m.playItem.title))
        if SpField(state,"eligibilityKind") = "experimental_query_p8_hdr10_ac3_fmp4_v1" then state.manualBound = true
        state.content = m.video.content
        state.durationCache = {durationMs:durationFile.durationMs,owner:SpCopy(state.owner),token:state.token,holderId:state.holderId,attemptId:state.attemptId,planGeneration:state.planGeneration,sourceId:state.owner.sourceId,itemId:state.intent.itemId,fileId:state.intent.fileId,content:state.content}
        payload.headers = invalid:payload.url = "":payload = invalid
        priorReturn = state.playerReturn:priorCaption = state.savedCaptionMode
        PlayerStart(plan,true)
        if state.intent.subtitleMode = "on"
            if caption.disposition = "unavailable" then Toast("No subtitles are available for this file.")
        end if
        if priorReturn <> invalid then m.playerReturn = priorReturn else state.playerReturn = m.playerReturn
        if priorCaption <> invalid then m.savedCaptionMode = priorCaption else state.savedCaptionMode = m.savedCaptionMode
        if state.startPaused = true then m.video.mute = true
        state.landed = false:state.landingClock = invalid:state.pendingPause = false
        state.startupClock = CreateObject("roTimespan")
        SiloUICompatWatch(state)
        m.compatPlayAttempt.phase = "playing"
        return
    end if
    if result.phase = "stock_context_prepared" and state.phase = "stock_preparing"
        handoff = state.task.privateStockContext
        state.task.privateStockContext = invalid
        if result.ok <> true or result.planGeneration <> state.planGeneration or not SiloUICompatCurrent(state) or type(handoff) <> "roAssociativeArray" then
            SiloUICompatStockAbort(state)
            return
        end if
        if type(handoff.owner) <> "roAssociativeArray" or handoff.owner.holderId <> state.holderId or handoff.owner.attemptId <> state.attemptId or handoff.owner.planGeneration <> state.planGeneration or not SoScopeEqual(handoff.owner,state.owner) or handoff.owner.sessionRevision <> state.owner.sessionRevision or handoff.startPositionMs <> state.intent.startPositionMs or handoff.class <> "copied_p7_hdr10_fmp4" then
            SiloUICompatStockAbort(state)
            return
        end if
        if type(handoff.context) <> "roAssociativeArray" then SiloUICompatStockAbort(state):return
        if handoff.context.transportPolicy <> state.stockQualification.transportPolicy or handoff.context.transportEvidence <> state.stockQualification.transportEvidence or handoff.context.authMode <> "bearer" or handoff.context.origin <> state.stockQualification.origin then SiloUICompatStockAbort(state):return
        engine = CreateObject("roSGNode","SiloStockEngineTask")
        if engine = invalid then SiloUICompatStockAbort(state):return
        state.engine = engine:state.phase = "stock_starting"
        state.engineClock = CreateObject("roTimespan")
        engine.observeField("seekOffer","onSiloUICompatStockEngine")
        engine.observeField("ready","onSiloUICompatStockEngine")
        engine.observeField("failed","onSiloUICompatStockEngine")
        engine.observeField("drainState","onSiloUICompatStockEngine")
        engine.stockContext = handoff.context
        handoff.context = invalid:handoff = invalid
        engine.control = "run"
        return
    end if
    if result.phase = "prepared" and (state.phase = "preparing" or state.phase = "seeking")
        if state.phase = "preparing" and result.mediaNeverRequested <> true then state.task.cancelled = true:return
        expectedGeneration = 1
        if state.phase = "seeking" then expectedGeneration = state.planGeneration+1
        expectedClass = SiloCompatClassForKind(SpField(state,"eligibilityKind"))
        if expectedClass = invalid or result.ok <> true or not SpBool(result.mediaNeverRequested) or result.fileMatched <> true or result.audioMatched <> true or result.class <> expectedClass or result.planGeneration <> expectedGeneration
            state.task.cancelled = true
            return
        end if
        if SiloUICompatCurrent(state)
            if state.phase = "seeking" then state.intent.startPositionMs = state.reanchorTarget
            state.planGeneration = expectedGeneration
            qualification = SiloUICompatStockQualification(state,result)
            if state.phase = "preparing" and qualification <> invalid
                state.phase = "stock_preparing":state.planGeneration = expectedGeneration
                state.stockQualification = qualification
                state.commandId = state.holderId+"-stock-context-"+expectedGeneration.ToStr()
                state.task.command = {action:"prepare_stock_context",commandId:state.commandId,holderId:state.holderId,attemptId:state.attemptId,owner:state.owner,planGeneration:expectedGeneration,qualification:qualification}
                return
            end if
            state.phase = "binding":state.planGeneration = expectedGeneration
            state.bindingNonce = SiloUICleanupUuid():state.commandId = state.holderId+"-bind-"+expectedGeneration.ToStr()
            bindCommand = {action:"bind",commandId:state.commandId,holderId:state.holderId,attemptId:state.attemptId,owner:state.owner,planGeneration:expectedGeneration,bindingNonce:state.bindingNonce}
            if state.DoesExist("eligibilityKind") then bindCommand["eligibilityKind"] = state.eligibilityKind
            if state.DoesExist("instanceQualification") then bindCommand["instanceQualification"] = SpCopy(state.instanceQualification)
            if SiloUICompatFieldCount(state,"autoAudioSelection") = 1
                bindCommand["autoVersion"] = true
                bindCommand["autoAudioSelection"] = SpCopy(state.autoAudioSelection)
            end if
            if SpField(state,"eligibilityKind") = "experimental_query_p8_hdr10_ac3_fmp4_v1" then bindCommand["autoVersion"] = false
            if state.DoesExist("manualVersionSelection")
                bindCommand["autoVersion"] = false:bindCommand["manualVersionSelection"] = SpCopy(state.manualVersionSelection)
            end if
            state.task.command = bindCommand
            return
        end if
        if type(m.compatPlayAttempt) = "roAssociativeArray" then m.compatPlayAttempt.phase = "closing"
        state.phase = "closing":state.closeSequence = 1:state.commandId = state.holderId+"-close-1"
        state.task.command = {action:"close",commandId:state.commandId,holderId:state.holderId,attemptId:state.attemptId,owner:state.owner}
        return
    end if
    if result.phase <> "closed" and result.phase <> "refused" then return
    if state.phase = "preparing" and result.phase = "refused" and not SiloContains(["session_changed","cancelled"],result.errorCode)
        state.preparationError = SiloUICompatPreparationError(result)
        if SiloContains(["subtitle_selection_unsupported","subtitle_fetch_failed"],state.preparationError) then Toast("Subtitles could not be prepared for this file.")
        print "qa_compat preparation_refused code="; state.preparationError
    end if
    mediaClosed = result.mediaNeverRequested = true
    if state.localRetired = true and result.mediaClosed = true then mediaClosed = true
    if result.cleanupUnconfirmed <> false or not SpBool(result.credentialRevoked) or not mediaClosed
        if type(m.compatPlayAttempt) = "roAssociativeArray" then m.compatPlayAttempt.phase = "cleanup_pending"
        state.phase = "cleanup_pending"
        m.cleanupFailed = true:m.speculationDisabled = true
        if state.token = m.playToken then m.playLoading = false : PlayerSetPlaybackStatus("")
        SiloUIDrainMaybeDone()
        if m.transitionIntent = invalid then Toast("Session cleanup pending. Retry in Settings.")
        return
    end if
    if type(m.compatPlayAttempt) = "roAssociativeArray" then m.compatPlayAttempt.phase = result.phase
    state.task.unobserveField("result")
    if state.watchdog <> invalid then state.watchdog.control = "stop"
    m.compatPreparation = invalid
    if m.cleanupTickets.Count() = 0 and m.cleanupUnconfirmed <> true
        m.cleanupFailed = false:m.speculationDisabled = m.memoryHigh = true
    end if
    if result.phase = "refused" and not SiloContains(["session_changed","cancelled"],result.errorCode) then state.failurePending = true
    closedAuthority = result.credentialRevoked = true or (result.mediaNeverRequested = true and result.cleanupUnconfirmed = false)
    if state.failurePending = true and closedAuthority
        if SiloUICompatResumeNative(state) then return
    end if
    if state.token = m.playToken then m.playLoading = false : PlayerSetPlaybackStatus("")
    SiloUIDrainMaybeDone()
    nextIntent = state.nextIntent
    if type(nextIntent) = "roAssociativeArray" and m.transitionIntent = invalid
        current = SoScopeEqual(nextIntent.owner,SiloUIOwner()) and nextIntent.owner.sessionRevision = DetailPhotoSessionRevision()
        if current and nextIntent.token = m.playToken and nextIntent.returnView = m.view and m.cleanupFailed <> true and m.cleanupUnconfirmed <> true
            state.nextIntent = invalid
            m.shuffleAdvancing = nextIntent.shuffle = true
            PlayItem(nextIntent.item,0)
            m.shuffleAdvancing = false
            return
        end if
    end if
    if state.failurePending = true and state.token = m.playToken and m.transitionIntent = invalid
        if m.view = "player" then PlayerClose(false,false)
        if state.preparationError <> invalid
            PlayerShowFailure("prepare",{errorCode:state.preparationError})
        else
            stage = TextOr(state.failureStage)
            if stage = "" then stage = "session"
            PlayerShowFailure(stage,SpField(state,"failureResult",{}))
        end if
    end if
end sub

sub SiloUICompatStockAbort(state as Object, failed = true as Boolean)
    if state = invalid then return
    if failed then state.failurePending = true
    state.task.privateStockContext = invalid
    if state.engine <> invalid
        if state.content = invalid then state.localRetired = true
        state.phase = "stock_stopping"
        if state.stockStopClock = invalid then state.stockStopClock = CreateObject("roTimespan")
        state.engine.stopRequested = true
        SiloUICompatWatch(state)
    else
        state.localRetired = true
        state.phase = "closing":state.closeSequence++
        state.commandId = state.holderId+"-close-"+state.closeSequence.ToStr()
        state.task.command = {action:"close",commandId:state.commandId,holderId:state.holderId,attemptId:state.attemptId,owner:state.owner,planGeneration:state.planGeneration,localRetired:true,positionMs:state.intent.startPositionMs,isPaused:false}
    end if
end sub

sub onSiloUICompatStockEngine(event as Object)
    state = m.compatPreparation
    if state = invalid or state.engine = invalid then return
    if not state.engine.isSameNode(event.getRoSGNode()) then return
    if state.stockSeek <> invalid and (state.phase = "playing" or state.phase = "stock_resuming")
        if state.engine.failed = true then SiloUICompatFailure("decoder_failure"):return
        SiloUICompatStockSeekOffer(state,state.engine.seekOffer)
        return
    end if
    if state.phase = "stock_starting"
        if state.token <> m.playToken or state.task.cancelled = true or state.planGeneration <> 1 then SiloUICompatStockAbort(state,false):return
        if state.engine.failed = true then SiloUICompatStockAbort(state):return
        if state.engine.ready <> true then return
        if not SiloUICompatCurrent(state) then SiloUICompatStockAbort(state):return
        durationFile = SiloPlaybackFile(state.detail,state.owner.sourceId,state.intent.itemId,state.intent.fileId,state.intent.startPositionMs)
        if durationFile = invalid then SiloUICompatStockAbort(state):return
        if state.intent.startPositionMs > 0
            state.stockDurationMs = durationFile.durationMs
            SiloUICompatStockResumeBegin(state)
            return
        end if
        local = SiloUICompatStockLocalBinding(state)
        if local = invalid then SiloUICompatStockAbort(state):return
        plan = local.plan:payload = local.payload
        state.phase = "playing":state.localRetired = false:state.playingSent = false:state.reportInFlight = false:state.activeConfirmed = false
        state.pendingProgress = invalid:state.reanchorTarget = invalid
        PlayerBind(payload,TextOr(m.playItem.title))
        state.content = m.video.content
        state.durationCache = {durationMs:durationFile.durationMs,owner:SpCopy(state.owner),token:state.token,holderId:state.holderId,attemptId:state.attemptId,planGeneration:state.planGeneration,sourceId:state.owner.sourceId,itemId:state.intent.itemId,fileId:state.intent.fileId,content:state.content}
        PlayerStart(plan,true)
        state.landed = false:state.landingClock = invalid:state.pendingPause = false
        state.startupClock = CreateObject("roTimespan")
        SiloUICompatWatch(state)
        m.compatPlayAttempt.phase = "playing"
        return
    end if
    if state.engine.failed = true and state.phase = "playing" then SiloUICompatFailure("decoder_failure"):return
    SiloUICompatStockDrain(state)
end sub

sub SiloUICompatStockDrain(state as Object)
    if state.phase <> "stock_stopping" or state.engine = invalid then return
    if state.engine.drainState = "pending"
        if state.stockStopClock <> invalid and state.stockStopClock.TotalMilliseconds() >= 15000
            state.phase = "cleanup_pending":m.cleanupFailed = true:m.speculationDisabled = true
            if state.token = m.playToken then m.playLoading = false:PlayerSetPlaybackStatus("")
            SiloUIDrainMaybeDone()
        end if
        return
    end if
    if state.engine.drainState <> "drained" or state.localRetired <> true
        state.phase = "cleanup_pending":m.cleanupFailed = true:m.speculationDisabled = true
        if state.token = m.playToken then m.playLoading = false:PlayerSetPlaybackStatus("")
        SiloUIDrainMaybeDone()
        return
    end if
    state.engine.unobserveField("seekOffer")
    state.engine.unobserveField("ready"):state.engine.unobserveField("failed"):state.engine.unobserveField("drainState")
    state.engine = invalid
    state.phase = "closing":state.closeSequence++
    state.commandId = state.holderId+"-close-"+state.closeSequence.ToStr()
    state.task.command = {action:"close",commandId:state.commandId,holderId:state.holderId,attemptId:state.attemptId,owner:state.owner,planGeneration:state.planGeneration,localRetired:true,positionMs:SpField(state,"positionMs",state.intent.startPositionMs),isPaused:SpField(state,"isPaused",false)}
end sub

function SiloUICompatManualCurrent(state as Object) as Boolean
    attempt = m.compatPlayAttempt:consent = SpField(state,"manualConsent")
    if not SiloObject(attempt) or not SiloObject(consent) then return false
    if FormatJson(consent) <> FormatJson(SpField(attempt,"manualConsent")) then return false
    if attempt.playToken <> state.token or attempt.playbackAttemptId <> state.attemptId or not SoScopeEqual(attempt.owner,state.owner) then return false
    if attempt.owner.sessionRevision <> state.owner.sessionRevision then return false
    if consent.holderId <> state.holderId or consent.attemptId <> state.attemptId then return false
    for each name in ["itemId","fileId","audioTrackId","audioTrackIndex"]
        if consent[name] <> state.intent[name] then return false
    end for
    if SiloUICompatFieldCount(state.intent,"autoVersion") <> 1 or not SpBool(state.intent.autoVersion) or state.intent.autoVersion <> false then return false
    if SiloUICompatFieldCount(state,"autoVersion") <> 0 then return false
    if SiloUICompatFieldCount(state.intent,"autoAudioSelection") <> 0 or SiloUICompatFieldCount(attempt,"autoAudioSelection") <> 0 or SiloUICompatFieldCount(attempt,"audioSelectionMode") <> 0 then return false
    if SpField(state,"manualBound",false) <> true
        if FormatJson(consent.ticket) <> FormatJson(m.playExperimentalChoice) or FormatJson(consent.audio) <> FormatJson(m.playAudioChoice) then return false
        if TextOr(m.playSelectedVersion) <> consent.fileId then return false
        if not PlayerExperimentalChoiceValid(m.playExperimentalChoice,m.playItem,m.playSelectedVersion,m.playAudioChoice,m.playVersions) then return false
    end if
    return true
end function

function SiloUICompatCurrent(state as Object) as Boolean
    if state.token <> m.playToken or m.transitionIntent <> invalid or state.task.cancelled = true then return false
    if not SoScopeEqual(state.owner,SiloUIOwner()) or DetailPhotoSessionRevision() <> state.owner.sessionRevision then return false
    prefs = SiloUISettingsPreferences(m.preferences)
    manualAC3 = SpField(state,"eligibilityKind") = "experimental_query_p8_hdr10_ac3_fmp4_v1"
    captions = SpField(state,"eligibilityKind") = "experimental_query_p8_ts_v1" and state.intent.subtitleMode = "on"
    if not manualAC3 and (prefs.quality <> "original" or (not captions and prefs.subtitles <> "off") or (captions and prefs.subtitles <> "always")) then return false
    file = SiloPlaybackFile(state.detail,state.owner.sourceId,state.intent.itemId,state.intent.fileId,state.intent.startPositionMs)
    if file = invalid then return false
    autoCount = SiloUICompatFieldCount(state,"autoAudioSelection")
    if autoCount > 1 then return false
    if autoCount = 1
        if SiloUICompatFieldCount(state,"autoVersion") <> 1 or not SpBool(SpField(state,"autoVersion")) or SpField(state,"autoVersion") <> true then return false
        if SiloUICompatFieldCount(state.intent,"autoVersion") <> 1 or not SpBool(SpField(state.intent,"autoVersion")) or SpField(state.intent,"autoVersion") <> true then return false
        if SpField(state,"eligibilityKind") <> "experimental_query_p7_hdr10_fmp4_v1" and SpField(state,"eligibilityKind") <> "experimental_query_p7_hdr10_aac_fmp4_v1" then return false
        if SpField(m.compatPlayAttempt,"audioSelectionMode") <> "auto" then return false
        if SiloUICompatFieldCount(state.intent,"autoAudioSelection") <> 1 or SiloUICompatFieldCount(m.compatPlayAttempt,"autoAudioSelection") <> 1 then return false
        selection = SpField(state,"autoAudioSelection")
        if FormatJson(selection) <> FormatJson(SpField(state.intent,"autoAudioSelection")) or FormatJson(selection) <> FormatJson(SpField(m.compatPlayAttempt,"autoAudioSelection")) then return false
        if not SiloUICompatAutoBasis(selection,file.version,state.intent.itemId,state.intent.fileId,SpField(state,"eligibilityKind")) then return false
        if SpField(selection,"audio_track_id") <> state.intent.audioTrackId or SpField(selection,"audio_track_index") <> state.intent.audioTrackIndex then return false
        if not SpBool(m.playVersionExplicit) or m.playVersionExplicit <> false then return false
        if m.playAudioChoice <> invalid or m.playExperimentalChoice <> invalid or TextOr(m.playSelectedVersion) <> "" then return false
    else if state.DoesExist("manualVersionSelection")
        if not SiloCompatManualVersionValid(state.intent,state.intent.fileId) then return false
        if state.autoVersion <> false or not SpBool(state.autoVersion) then return false
        if FormatJson(state.manualVersionSelection) <> FormatJson(state.intent.manualVersionSelection) or FormatJson(state.manualVersionSelection) <> FormatJson(m.compatPlayAttempt.manualVersionSelection) then return false
        if state.requestedFileId <> state.intent.fileId or TextOr(m.playSelectedVersion) <> state.intent.fileId then return false
        if m.playExperimentalChoice <> invalid then return false
        if state.manualVersionSelection.DoesExist("explicitAudioSelection")
            if not SiloUICompatExplicitAudioCurrent(state.intent,state.detail) then return false
        else
            if not SpBool(m.playVersionExplicit) or m.playVersionExplicit <> true then return false
            if m.playAudioChoice <> invalid then return false
        end if
    else if manualAC3
        if not SiloUICompatManualCurrent(state) then return false
    else if SiloUICompatFieldCount(state,"autoVersion") <> 0 or SiloUICompatFieldCount(state.intent,"autoVersion") <> 0 or SiloUICompatFieldCount(state.intent,"autoAudioSelection") <> 0 or SiloUICompatFieldCount(m.compatPlayAttempt,"autoAudioSelection") <> 0 or SiloUICompatFieldCount(m.compatPlayAttempt,"audioSelectionMode") <> 0
        return false
    end if
    ordinal = state.intent.audioTrackIndex
    if not SpNumber(ordinal,file.version.audioTracks.Count()-1,true) then return false
    kind = SpField(state,"eligibilityKind")
    aac = kind = "experimental_query_p7_hdr10_aac_fmp4_v1"
    qualification = invalid
    if aac
        qualification = SiloCompatP7AACQualification(state.owner,SpField(state,"instanceQualification"))
        if qualification = invalid or SiloUICompatFieldCount(state,"instanceQualification") <> 1 or SiloUICompatFieldCount(state.intent,"instanceQualification") <> 1 or SiloUICompatFieldCount(m.compatPlayAttempt,"instanceQualification") <> 1 then return false
        if FormatJson(qualification) <> FormatJson(SpField(state.intent,"instanceQualification")) or FormatJson(qualification) <> FormatJson(SpField(m.compatPlayAttempt,"instanceQualification")) then return false
    else if SiloUICompatFieldCount(state,"instanceQualification") <> 0 or SiloUICompatFieldCount(state.intent,"instanceQualification") <> 0 or SiloUICompatFieldCount(m.compatPlayAttempt,"instanceQualification") <> 0
        return false
    end if
    if state.DoesExist("eligibilityKind")
        if not SpText(kind,64) then return false
        if kind <> "experimental_query_p8_ts_v1" and kind <> "experimental_query_p8_hdr10_fmp4_v1" and kind <> "experimental_query_p7_hdr10_fmp4_v1" and kind <> "experimental_query_p7_hdr10_aac_fmp4_v1" and kind <> "experimental_query_p8_hdr10_ac3_fmp4_v1" then return false
        if SpField(state.intent,"eligibilityKind") <> kind or SpField(m.compatPlayAttempt,"eligibilityKind") <> kind then return false
        if not SiloObject(SpField(state,"snapshot")) then return false
    else if state.intent.DoesExist("eligibilityKind") or state.DoesExist("snapshot")
        return false
    end if
    video = invalid:videos = SpField(file.version,"videoTracks")
    if SiloArray(videos) then if videos.Count() = 1 then video = videos[0]
    snapshot = SiloCompatSnapshotForKind(CreateObject("roDeviceInfo"),file.version.audioTracks[ordinal],kind,video)
    proof = SiloCompatCandidate(state.detail,state.owner,state.intent,snapshot,kind,qualification)
    if proof = invalid then return false
    if kind <> invalid then return SpField(proof,"eligibilityKind") = kind and FormatJson(snapshot) = FormatJson(state.snapshot)
    return true
end function

sub SiloUICompatCancel()
    state = m.compatPreparation
    if state = invalid then return
    state.reanchorTarget = invalid
    if state.stockSeek <> invalid
        s = state.stockSeek
        if s.generationId <> invalid then state.engine.seekAck = {action:"cancel",requestId:s.requestId,generationId:s.generationId}
        state.stockPositionMs = s.positionMs
        state.stockSeek = invalid
    end if
    if state.phase = "stock_stopping" then return
    if state.phase = "stock_starting" or state.phase = "stock_resuming"
        SiloUICompatStockAbort(state,false)
        return
    end if
    if state.content <> invalid and state.localRetired <> true
        SiloUICompatBeginClose()
    else
        state.task.cancelled = true
    end if
end sub

sub SiloUICompatBeginClose(capturePosition = true as Boolean)
    state = m.compatPreparation
    if state = invalid or state.phase = "local_stopping" or state.phase = "closing" or state.phase = "cleanup_pending" then return
    if state.content = invalid then return
    if m.video.content <> invalid
        if not state.content.isSameNode(m.video.content)
            state.phase = "cleanup_pending":m.cleanupFailed = true:m.playLoading = false : PlayerSetPlaybackStatus("")
            Toast("Playback cleanup changed ownership. Retry in Settings.")
            return
        end if
    end if
    if capturePosition
        state.positionMs = PlayerPositionMs():state.isPaused = m.video.state = "paused"
    end if
    m.playLastPositionMs = state.positionMs
    state.pendingProgress = invalid:state.phase = "local_stopping"
    state.stopClock = CreateObject("roTimespan")
    SiloUICompatWatch(state)
    m.video.control = "stop"
    SiloUICompatObserveLocalStop()
end sub

' Retire only the old binding after the local decoder stops. A delayed close
' may erase the old content headers but cannot touch a replacement agent.
sub SiloUICompatObserveLocalStop()
    state = m.compatPreparation
    if state = invalid then return
    if state.phase <> "local_stopping" and not (state.phase = "cleanup_pending" and state.localRetired <> true) then return
    if m.video.state <> "stopped" and m.video.state <> "none"
        if state.stopClock <> invalid
            if state.stopClock.TotalMilliseconds() >= 5000
                state.phase = "cleanup_pending":m.cleanupFailed = true
                if state.token = m.playToken then m.playLoading = false : PlayerSetPlaybackStatus("")
                if state.watchdog <> invalid then state.watchdog.control = "stop"
                Toast("Playback stop could not be confirmed. Retry in Settings.")
                SiloUIDrainMaybeDone()
            end if
        end if
        return
    end if
    binding = m.compatMediaBinding
    if binding = invalid or state.content = invalid then return
    if binding.holderId <> state.holderId or binding.attemptId <> state.attemptId or binding.planGeneration <> state.planGeneration then return
    if not binding.content.isSameNode(state.content) then return
    ownsVideo = m.video.content = invalid
    if m.video.content <> invalid then ownsVideo = state.content.isSameNode(m.video.content)
    state.content.HttpHeaders = []:state.content.url = ""
    if m.nativeSubtitleContent <> invalid
        if state.content.isSameNode(m.nativeSubtitleContent) then m.nativeSubtitleContent = invalid
    end if
    if ownsVideo
        m.video.content = invalid
        agent = CreateObject("roHttpAgent")
        agent.SetCertificatesFile("common:/certs/ca-bundle.crt")
        m.video.SetHttpAgent(agent)
    end if
    binding.agent = invalid:m.compatMediaBinding = invalid
    if state.watchdog <> invalid then state.watchdog.control = "stop"
    if state.engine <> invalid
        state.localRetired = true
        state.phase = "stock_stopping"
        if state.stockStopClock = invalid then state.stockStopClock = CreateObject("roTimespan")
        state.engine.stopRequested = true
        SiloUICompatWatch(state)
        return
    end if
    state.localRetired = true:state.phase = "closing":state.closeSequence++
    state.commandId = state.holderId+"-close-"+state.closeSequence.ToStr()
    command = {action:"close",commandId:state.commandId,holderId:state.holderId,attemptId:state.attemptId,owner:state.owner,planGeneration:state.planGeneration,localRetired:true,positionMs:state.positionMs,isPaused:state.isPaused}
    if state.reanchorTarget <> invalid
        state.phase = "seeking":command.action = "seek"
        state.prepareClock = CreateObject("roTimespan"):SiloUICompatWatch(state)
        command["targetPositionMs"] = state.reanchorTarget:command["startPaused"] = state.startPaused
        if state.DoesExist("eligibilityKind") then command["eligibilityKind"] = state.eligibilityKind
        if SpField(state,"eligibilityKind") = "experimental_query_p8_hdr10_ac3_fmp4_v1" then command["autoVersion"] = false
        if SiloUICompatFieldCount(state,"autoAudioSelection") = 1
            command["autoVersion"] = true
            command["autoAudioSelection"] = SpCopy(state.autoAudioSelection)
        end if
        if state.DoesExist("manualVersionSelection")
            command["autoVersion"] = false:command["manualVersionSelection"] = SpCopy(state.manualVersionSelection)
        end if
        if state.DoesExist("instanceQualification") then command["instanceQualification"] = SpCopy(state.instanceQualification)
    end if
    state.task.command = command
end sub

sub onSiloUICompatTick()
    SiloUICompatObserveLocalStop()
    state = m.compatPreparation
    if state = invalid then return
    if (state.phase = "stock_starting" or state.phase = "stock_resuming") and state.engineClock <> invalid
        if state.engineClock.TotalMilliseconds() >= 120000 then SiloUICompatStockAbort(state)
        return
    end if
    if state.phase = "stock_stopping"
        SiloUICompatStockDrain(state)
        return
    end if
    if state.phase = "preparing" or state.phase = "binding" or state.phase = "seeking" or state.phase = "stock_preparing"
        if state.prepareClock <> invalid
            if state.prepareClock.TotalMilliseconds() >= 120000
                state.task.cancelled = true:state.reanchorTarget = invalid:state.phase = "cleanup_pending"
                m.cleanupFailed = true:m.speculationDisabled = true
                if state.token = m.playToken then m.playLoading = false : PlayerSetPlaybackStatus("")
                state.watchdog.control = "stop"
                Toast("Playback preparation cleanup is unconfirmed. Retry in Settings.")
                SiloUIDrainMaybeDone()
            end if
        end if
        return
    end if
    if state.phase <> "playing" then return
    if state.stockSeek <> invalid
        timeoutMs = 120000
        if state.stockSeek.stage = "stopping" or state.stockSeek.stage = "quiescing" then timeoutMs = 5000
        if state.stockSeek.stage <> "running" and state.stockSeek.clock.TotalMilliseconds() >= timeoutMs
            SiloUICompatFailure("position_unconfirmed")
            return
        end if
    end if
    if state.engine <> invalid then SiloUICompatObservePosition()
    if state.playingSent <> true
        if state.startupClock <> invalid
            if state.startupClock.TotalMilliseconds() >= 120000 then SiloUICompatFailure("buffering_timeout")
        end if
        return
    end if
    if state.pendingPause = true
        if state.pauseClock.TotalMilliseconds() >= 10000 then SiloUICompatFailure("position_unconfirmed")
        return
    end if
    if state.landed = true then return
    if state.landingClock <> invalid
        if state.landingClock.TotalMilliseconds() >= 10000
            SiloUICompatFailure("position_unconfirmed")
        end if
    end if
end sub

sub SiloUICompatFailure(reason as String)
    state = m.compatPreparation
    if state = invalid then return
    if state.phase = "stock_resuming"
        SiloUICompatStockAbort(state)
        return
    end if
    if state.phase <> "playing" then return
    if not SiloContains(["decoder_failure","buffering_timeout","position_unconfirmed","session_unconfirmed"],reason) then return
    state.failurePending = true:state.reanchorTarget = invalid
    state.failureStage = "session"
    if reason = "decoder_failure" then state.failureStage = "native"
    if reason = "buffering_timeout" then state.failureStage = "timeout"
    m.playLoading = true
    Toast("Closing playback before trying another available version…")
    SiloUICompatBeginClose()
end sub

' Reuse the consumed foreground attempt. This does not open a new PlayItem or
' grant a second compatibility attempt; mark consumed before the native job.
function SiloUICompatResumeNative(state as Object) as Boolean
    if state.DoesExist("manualVersionSelection") then return false
    attempt = m.compatPlayAttempt
    if attempt = invalid or attempt.resumeConsumed = true or state.qualityExplicit <> false or state.resumeRefused = true then return false
    if not SiloUICompatCurrent(state) or state.token <> attempt.playToken or attempt.playToken <> m.playToken then return false
    if m.transitionIntent <> invalid or m.cleanupUnconfirmed = true or m.cleanupFailed = true or SpScope(m.compatNativeStopFailure) <> invalid then return false
    if m.video.content <> invalid or m.cleanupTickets.Count() <> 0 or m.prebuf <> invalid or m.audioPlan <> invalid then return false
    if m.playAudioChoice <> invalid or m.playExperimentalChoice <> invalid or TextOr(m.playSelectedVersion) <> "" then return false
    if TextOr(m.playItem.itemId) <> state.intent.itemId then return false
    excluded = SpCopy(attempt.nativeAttemptedFileIds)
    if excluded.Count() >= 8 then return false
    available = false
    for each version in state.detail.versions
        if not SiloContains(excluded,version.versionId) then available = true
    end for
    if not available then return false
    position = SpField(state,"positionMs",state.intent.startPositionMs)
    if not SpNumber(position,2147483646,true) then return false
    params = {itemId:state.intent.itemId,fileId:state.requestedFileId,detail:SpCopy(state.detail),autoVersion:true,qualityPreference:"original",qualityExplicit:false,subtitleMode:state.intent.subtitleMode,startPositionMs:position,excludedVersionIds:excluded,compatExcludedFileIds:[state.intent.fileId]}
    if state.intent.DoesExist("bandwidthCapKbps") then params["bandwidthCapKbps"] = state.intent.bandwidthCapKbps
    attempt.resumeConsumed = true:attempt.phase = "native_resume":attempt.nativeAttemptedFileIds = excluded
    m.compatNativeResume = {requestId:m.requestId+1,owner:state.owner,token:m.playToken,excludedVersionIds:SpCopy(excluded),compatExcludedFileIds:SpCopy(params.compatExcludedFileIds),playerReturn:state.playerReturn,savedCaptionMode:state.savedCaptionMode}
    m.playPlan = invalid:m.playLoading = true
    ApiOwned("playback_start",params,"play_start",m.playToken,state.owner)
    return true
end function

sub SiloUICompatWatch(state as Object)
    if state.watchdog = invalid
        state.watchdog = CreateObject("roSGNode","Timer")
        state.watchdog.repeat = true:state.watchdog.duration = 1
        state.watchdog.observeField("fire","onSiloUICompatTick")
    end if
    state.watchdog.control = "start"
end sub

sub SiloUICompatObservePosition()
    state = m.compatPreparation
    if state = invalid or state.phase <> "playing" then return
    if state.engine <> invalid and state.content <> invalid and m.video.content <> invalid
        if state.content.isSameNode(m.video.content) and PlayerDurationNumber(m.video.position) and m.video.position >= 0 then state.engine.playbackPosition = m.video.position
    end if
    if state.stockSeek <> invalid
        SiloUICompatStockSeekPosition()
        return
    end if
    if state.landed = true then return
    if state.content = invalid or m.video.content = invalid or not SiloUICompatCurrent(state) then return
    if not state.content.isSameNode(m.video.content) then return
    if m.video.state <> "playing" and m.video.state <> "paused" then return
    position = m.video.position*1000#
    if not PlayerDurationNumber(position) or position <> position or position < 0 or position > 2147483646 then return
    if Abs(position-state.intent.startPositionMs) > 2000 then return
    state.landed = true
    if state.startPaused = true
        state.pendingPause = true:state.pauseClock = CreateObject("roTimespan")
        m.video.control = "pause"
        SiloUICompatRestorePause()
    end if
    SiloUICompatLandingWatch(state)
end sub

sub SiloUICompatLandingWatch(state as Object)
    if state.watchdog <> invalid and state.pendingPause <> true and state.engine = invalid then state.watchdog.control = "stop"
end sub

sub SiloUICompatRestorePause()
    state = m.compatPreparation
    if state = invalid or state.phase <> "playing" or state.pendingPause <> true or state.landed <> true then return
    if m.video.state <> "paused" or state.content = invalid or m.video.content = invalid then return
    if not state.content.isSameNode(m.video.content) or not SiloUICompatCurrent(state) then return
    state.pendingPause = false:state.startPaused = false
    m.video.mute = false
    if state.watchdog <> invalid and state.engine = invalid then state.watchdog.control = "stop"
end sub

sub SiloUICompatPlaying()
    state = m.compatPreparation
    if state = invalid or state.phase <> "playing" or state.playingSent = true then return
    if m.playPlan = invalid or m.playPlan.transport <> "silo_compat" or m.video.content = invalid or state.content = invalid then return
    if not state.content.isSameNode(m.video.content) or not SiloUICompatCurrent(state) then return
    state.playingSent = true
    state.landingClock = CreateObject("roTimespan")
    SiloUICompatReport("playing",m.playLastPositionMs)
end sub

' Cached source duration with local ownership checks only. Capability/source
' validation remains on actual commands, never on each transport paint.
function SiloUICompatDuration() as Double
    state = m.compatPreparation
    if not SiloObject(state) then return 0
    if state.phase <> "playing" or m.transitionIntent <> invalid then return 0
    if state.task = invalid or state.task.cancelled = true then return 0
    cache = SpField(state,"durationCache")
    if not SiloObject(cache) or not SpNumber(SpField(cache,"durationMs"),604800000) then return 0
    if cache.durationMs <= 0 or cache.token <> m.playToken or cache.token <> state.token then return 0
    if not SoScopeEqual(cache.owner,SiloUIOwner()) or not SoScopeEqual(cache.owner,state.owner) then return 0
    if cache.owner.sessionRevision <> state.owner.sessionRevision or cache.owner.sessionRevision <> DetailPhotoSessionRevision() then return 0
    attempt = m.compatPlayAttempt
    if not SiloObject(attempt) or not SoScopeEqual(cache.owner,attempt.owner) then return 0
    if attempt.owner.sessionRevision <> cache.owner.sessionRevision or attempt.playToken <> cache.token or attempt.playbackAttemptId <> cache.attemptId then return 0
    if attempt.itemId <> cache.itemId or attempt.fileId <> cache.fileId then return 0
    if state.holderId <> cache.holderId or state.attemptId <> cache.attemptId or state.planGeneration <> cache.planGeneration then return 0
    if state.owner.sourceId <> cache.sourceId or state.intent.itemId <> cache.itemId or state.intent.fileId <> cache.fileId then return 0
    plan = m.playPlan:binding = m.compatMediaBinding
    if not SiloObject(plan) or not SiloObject(binding) then return 0
    if plan.transport <> "silo_compat" or plan.provider <> "silo" or plan.versionId <> cache.fileId then return 0
    if SpField(m.playItem,"itemId") <> cache.itemId then return 0
    for each field in ["holderId","attemptId","planGeneration","sourceId","itemId"]
        if plan[field] <> cache[field] then return 0
    end for
    for each field in ["holderId","attemptId","planGeneration"]
        if binding[field] <> cache[field] then return 0
    end for
    if cache.content = invalid or state.content = invalid or binding.content = invalid or m.video.content = invalid then return 0
    if not cache.content.isSameNode(state.content) or not cache.content.isSameNode(binding.content) or not cache.content.isSameNode(m.video.content) then return 0
    return cache.durationMs
end function

function SiloUICompatSeek(targetMs as Dynamic) as Boolean
    state = m.compatPreparation
    if state = invalid or state.phase <> "playing" or state.activeConfirmed <> true then return false
    if not SpNumber(targetMs,2147483646,true) or not SiloUICompatCurrent(state) then return false
    duration = SiloUICompatDuration()
    if duration <= 0 or targetMs >= duration then return false
    if state.engine <> invalid then return SiloUICompatStockSeekBegin(state,targetMs)
    state.reanchorTarget = targetMs:state.startPaused = m.video.state = "paused"
    SiloUICompatBeginClose()
    return true
end function

sub SiloUICompatReport(action as String, positionMs as Dynamic)
    state = m.compatPreparation
    if state = invalid or state.phase <> "playing" or not SiloUICompatCurrent(state) then return
    if state.content = invalid or m.video.content = invalid then return
    if not state.content.isSameNode(m.video.content) or not SpNumber(positionMs,2147483646,true) then return
    if state.reportInFlight = true
        if action = "progress" then state.pendingProgress = positionMs
        return
    end if
    state.reportSequence = Int(NumberOr(state.reportSequence,0))+1
    state.commandId = state.holderId+"-"+action+"-"+state.reportSequence.ToStr()
    state.reportInFlight = true
    state.task.command = {action:action,commandId:state.commandId,holderId:state.holderId,attemptId:state.attemptId,owner:state.owner,planGeneration:state.planGeneration,positionMs:positionMs,isPaused:m.video.state="paused"}
end sub

' Existing explicit cleanup Retry is the only way to submit another close.
sub SiloUICompatRetry()
    state = m.compatPreparation
    if state = invalid or state.phase <> "cleanup_pending" then return
    if state.engine <> invalid
        if state.localRetired <> true and state.content <> invalid
            state.phase = "playing"
            SiloUICompatBeginClose(false)
        else if state.engine.drainState = "drained" and state.localRetired = true
            state.phase = "stock_stopping"
            SiloUICompatStockDrain(state)
        end if
        return
    end if
    if state.content <> invalid and state.localRetired <> true
        state.phase = "playing"
        SiloUICompatBeginClose(false)
        return
    end if
    state.closeSequence++
    state.commandId = state.holderId+"-close-"+state.closeSequence.ToStr()
    state.phase = "closing"
    if type(m.compatPlayAttempt) = "roAssociativeArray" then m.compatPlayAttempt.phase = "closing"
    command = {action:"close",commandId:state.commandId,holderId:state.holderId,attemptId:state.attemptId,owner:state.owner}
    if state.localRetired = true
        command["localRetired"] = true:command["planGeneration"] = state.planGeneration
        command["positionMs"] = state.positionMs:command["isPaused"] = state.isPaused
    end if
    state.task.command = command
end sub

' Internal AA evidence must never downgrade through null or case aliases.
function SiloUICompatFieldCount(raw as Dynamic, name as String) as Integer
    count = 0
    if SiloObject(raw)
        for each key in raw
            if LCase(key) = LCase(name) then count++
        end for
    end if
    return count
end function

' Revalidate source selection against both the correlated job detail and the
' version inventory actually accepted by PlayerResult. Auto needs no Detail UI.
function SiloUICompatAutoBasis(selection as Dynamic, version as Dynamic, itemId as String, fileId as String, kind = invalid as Dynamic) as Boolean
    if not SiloObject(selection) then return false
    facts = SpField(version,"autoAudioFacts")
    verified = SiloAutoAudioChoose(facts,SpField(selection,"queries"))
    if kind = "experimental_query_p7_hdr10_aac_fmp4_v1" then verified = SiloAutoAudioAACConversion(facts,SpField(selection,"queries"))
    if verified = invalid then return false
    if FormatJson(verified) <> FormatJson(selection) then return false
    if selection.file_id <> fileId or not SiloArray(m.playVersions) then return false
    if m.playVersions.Count() <> 1 then return false
    accepted = m.playVersions[0]
    if SpField(accepted,"versionId") <> fileId or SpField(accepted,"itemId") <> itemId or SpField(accepted,"sourceId") <> m.sourceId then return false
    return FormatJson(SpField(accepted,"autoAudioFacts")) = FormatJson(facts)
end function

' All-track MP4 facts are recollected once at admission, never while painting
' transport UI. Each failed SDK read remains unknown rather than a false fact.
function SiloUICompatFreshAutoSelection(device as Object, facts as Object, kind = invalid as Dynamic) as Dynamic
    queries = []
    for each track in facts.tracks
        decode = invalid:passthrough = invalid
        try
            decode = SiloCompatDecodeEvidence(device.CanDecodeAudio({codec:track.codec,chcnt:track.channels,container:"mp4",passthru:0}))
        catch exception
        end try
        try
            passthrough = SiloCompatDecodeEvidence(device.CanDecodeAudio({codec:track.codec,chcnt:track.channels,container:"mp4",passthru:1}))
        catch exception
        end try
        queries.Push({source_ordinal:track.source_ordinal,codec:track.codec,channels:track.channels,container:"mp4",decode:decode,passthrough:passthrough})
    end for
    if kind = "experimental_query_p7_hdr10_aac_fmp4_v1" then return SiloAutoAudioAACConversion(facts,queries)
    return SiloAutoAudioChoose(facts,queries)
end function

' Stock generation IDs are engine-local; server holder planGeneration remains 1.
' Startup has no native decoder. Keep its ownership separate from ordinary seek.
sub SiloUICompatStockResumeBegin(state as Object)
    if state.phase <> "stock_starting" or state.content <> invalid or m.video.content <> invalid then return
    if state.task.cancelled = true or state.token <> m.playToken or m.transitionIntent <> invalid then return
    if not SiloUICompatCurrent(state) or not SpNumber(state.intent.startPositionMs,2147483646,true) or state.intent.startPositionMs <= 0 then return
    targetUs& = state.intent.startPositionMs
    targetUs& = targetUs&*1000&
    state.phase = "stock_resuming":state.stockRequestId = 1
    state.stockSeek = {initial:true,intent:SpCopy(state.intent),requestId:1,targetTitleUs:targetUs&,previousGenerationId:1,stage:"waiting_offer",engine:state.engine,content:invalid,token:state.token,holderId:state.holderId,attemptId:state.attemptId,owner:SpCopy(state.owner),paused:false,positionMs:state.intent.startPositionMs,clock:CreateObject("roTimespan")}
    state.engine.seekRequest = {requestId:1,targetTitleUs:targetUs&}
    SiloUICompatWatch(state)
end sub

function SiloUICompatStockSeekBegin(state as Object, targetMs as Dynamic) as Boolean
    if state.stockSeek <> invalid then if state.stockSeek.stage <> "running" or state.stockSeek.released <> true then return false
    if state.task.cancelled = true or m.transitionIntent <> invalid then return false
    if state.content = invalid or m.video.content = invalid then return false
    if not state.content.isSameNode(m.video.content) then return false
    requestId = 1
    if state.stockRequestId <> invalid then requestId = state.stockRequestId+1
    if requestId > 2147483646 then return false
    targetUs& = targetMs
    targetUs& = targetUs&*1000&
    generation = 1
    if state.stockGeneration <> invalid then generation = state.stockGeneration
    state.stockRequestId = requestId
    state.stockSeek = {requestId:requestId,targetTitleUs:targetUs&,previousGenerationId:generation,stage:"waiting_offer",engine:state.engine,content:state.content,token:state.token,holderId:state.holderId,attemptId:state.attemptId,owner:SpCopy(state.owner),paused:m.video.state="paused",positionMs:PlayerPositionMs(),clock:CreateObject("roTimespan")}
    state.engine.seekRequest = {requestId:requestId,targetTitleUs:targetUs&}
    SiloUICompatWatch(state)
    return true
end function

function SiloUICompatStockSeekOwned(state as Object) as Boolean
    s = state.stockSeek
    if s = invalid or state.engine = invalid or state.task.cancelled = true then return false
    if s.initial <> true and state.phase <> "playing" then return false
    if s.initial = true and state.phase <> "stock_resuming" and state.phase <> "playing" then return false
    if s.initial = true then if FormatJson(s.intent) <> FormatJson(state.intent) then return false
    if s.token <> m.playToken or s.token <> state.token or m.transitionIntent <> invalid then return false
    if s.holderId <> state.holderId or s.attemptId <> state.attemptId or not SoScopeEqual(s.owner,state.owner) then return false
    if s.owner.sessionRevision <> state.owner.sessionRevision then return false
    if not s.engine.isSameNode(state.engine) or not SiloUICompatCurrent(state) then return false
    if s.initial = true and state.phase = "stock_resuming"
        return state.content = invalid and s.content = invalid and m.video.content = invalid and state.planGeneration = 1 and s.targetTitleUs = state.intent.startPositionMs*1000#
    end if
    if state.content = invalid or s.content = invalid or m.video.content = invalid then return false
    if not s.content.isSameNode(state.content) then return false
    return state.content.isSameNode(m.video.content)
end function

function SiloUICompatStockSeekPlan(offer as Dynamic, s as Object) as Boolean
    if type(offer) <> "roAssociativeArray" then return false
    if offer.requestId <> s.requestId or offer.previousGenerationId <> s.previousGenerationId then return false
    if not SpNumber(offer.generationId,2147483646,true) or offer.generationId <= s.previousGenerationId then return false
    p = offer.plan
    if type(p) <> "roAssociativeArray" then return false
    if p.requestId <> s.requestId or p.generationId <> offer.generationId or p.requestedTitleUs <> s.targetTitleUs then return false
    for each field in ["titleOriginUs","offsetUs","sourceStartIndex","revision"]
        if not SpNumber(p[field],9007199254740991#,true) then return false
    end for
    if p.titleOriginUs+p.offsetUs <> s.targetTitleUs or not SpText(p.binding,2048) then return false
    return offer.localMasterUrl = "http://127.0.0.1:34831/g"+offer.generationId.ToStr()+"/master.m3u8"
end function

sub SiloUICompatStockSeekOffer(state as Object, offer as Dynamic)
    if not SiloUICompatStockSeekOwned(state) then return
    s = state.stockSeek
    if type(offer) <> "roAssociativeArray" then return
    if offer.requestId = s.requestId and (offer.status = "failed" or offer.status = "cancelled")
        if s.generationId <> invalid then if offer.generationId <> s.generationId then return
        SiloUICompatFailure("position_unconfirmed")
        return
    end if
    if not SiloUICompatStockSeekPlan(offer,s) then return
    if s.stage = "waiting_offer" and offer.previousRetired = true then return
    if s.stage = "waiting_offer" and offer.status = "quiesce"
        s.plan = SpCopy(offer.plan):s.generationId = offer.generationId:s.url = offer.localMasterUrl
        s.stage = "quiescing":s.clock = CreateObject("roTimespan")
        if s.initial = true
            s.retired = true:s.quiesced = true:s.stage = "quiesced"
            state.engine.seekAck = {action:"quiesced",requestId:s.requestId,generationId:s.generationId,previousGenerationId:s.previousGenerationId}
        else
            m.video.control = "stop"
        end if
        return
    end if
    if s.stage = "quiesced"
        if FormatJson(s.plan) <> FormatJson(offer.plan) or offer.generationId <> s.generationId or offer.localMasterUrl <> s.url then return
        if offer.status <> "offered" or offer.previousRetired <> true then return
    end if
    if (s.stage = "waiting_offer" or s.stage = "quiesced") and offer.status = "offered"
        s.plan = SpCopy(offer.plan):s.generationId = offer.generationId:s.url = offer.localMasterUrl
        s.stage = "await_active":s.clock = CreateObject("roTimespan")
        state.engine.seekAck = {action:"accept",requestId:s.requestId,generationId:s.generationId}
    else if s.stage = "await_active" and offer.status = "active"
        if FormatJson(s.plan) <> FormatJson(offer.plan) or offer.generationId <> s.generationId or offer.localMasterUrl <> s.url then return
        if s.initial = true
            if (s.quiesced = true) <> (offer.previousRetired = true) then return
            s.retired = true
            state.phase = "playing":state.localRetired = false:state.playingSent = false:state.reportInFlight = false:state.activeConfirmed = false
            state.pendingProgress = invalid:state.reanchorTarget = invalid
            SiloUICompatStockSeekBindRetired(state)
            plan = {provider:"silo",transport:"silo_compat",sourceId:state.owner.sourceId,itemId:state.intent.itemId,versionId:state.intent.fileId,holderId:state.holderId,attemptId:state.attemptId,planGeneration:1,startPositionMs:state.intent.startPositionMs,timelineOffsetMs:0,subtitleMode:"off"}
            state.durationCache = {durationMs:state.stockDurationMs,owner:SpCopy(state.owner),token:state.token,holderId:state.holderId,attemptId:state.attemptId,planGeneration:state.planGeneration,sourceId:state.owner.sourceId,itemId:state.intent.itemId,fileId:state.intent.fileId,content:state.content}
            PlayerStart(plan,true)
            state.pendingPause = false:state.startupClock = CreateObject("roTimespan")
            SiloUICompatWatch(state)
            if m.compatPlayAttempt <> invalid then m.compatPlayAttempt.phase = "playing"
            return
        end if
        if s.quiesced = true
            if offer.previousRetired <> true then return
            SiloUICompatStockSeekBindRetired(state)
        else
            if offer.previousRetired = true then return
            s.stage = "stopping":s.clock = CreateObject("roTimespan")
            m.video.control = "stop"
        end if
    end if
end sub

' Return true while this coordinator consumes native state transitions.
function SiloUICompatStockSeekState() as Boolean
    state = m.compatPreparation
    if state = invalid then return false
    s = state.stockSeek
    if s = invalid then return false
    if not SiloUICompatStockSeekOwned(state) then return false
    if state.phase = "stock_resuming" then return true
    if m.video.state = "error" or (m.video.state = "finished" and s.stage <> "running")
        SiloUICompatFailure("decoder_failure")
        return true
    end if
    if s.stage = "quiescing" and m.video.state = "stopped"
        s.retired = true:s.quiesced = true
        state.content.HttpHeaders = []:state.content.url = ""
        s.stage = "quiesced":s.clock = CreateObject("roTimespan")
        state.engine.seekAck = {action:"quiesced",requestId:s.requestId,generationId:s.generationId,previousGenerationId:s.previousGenerationId}
    else if s.stage = "stopping" and m.video.state = "stopped"
        ' The old decoder is retired only at this observed stop boundary.
        s.retired = true
        state.content.HttpHeaders = []:state.content.url = ""
        SiloUICompatStockSeekBindRetired(state)
    else if s.stage = "loading" and m.video.state = "playing"
        s.stage = "qualifying":s.clock = CreateObject("roTimespan")
        s.firstPosition = invalid
    end if
    if s.stage = "running" then return false
    return true
end function

' Bind only after this coordinator has observed retirement of the owned decoder.
sub SiloUICompatStockSeekBindRetired(state as Object)
    s = state.stockSeek
    if s.retired <> true then return
    payload = {url:s.url,streamFormat:"hls",headers:{},startPositionMs:s.plan.offsetUs/1000#,transport:"silo_compat",holderId:state.holderId,attemptId:state.attemptId,planGeneration:state.planGeneration}
    m.video.content = invalid
    PlayerBind(payload,TextOr(m.playItem.title))
    state.content = m.video.content:s.content = state.content
    m.video.observeField("bufferingStatus","onSiloUICompatStockSeekBuffer")
    if state.durationCache <> invalid then state.durationCache.content = state.content
    epoch = 1
    if state.stockContentEpoch <> invalid then epoch = state.stockContentEpoch+1
    state.stockContentEpoch = epoch:s.epoch = epoch
    s.stage = "loading":s.clock = CreateObject("roTimespan")
    state.landed = false:state.landingClock = invalid
    m.video.mute = s.paused:m.video.control = "play"
end sub

sub SiloUICompatStockSeekPosition()
    state = m.compatPreparation
    if state = invalid or not SiloUICompatStockSeekOwned(state) then return
    s = state.stockSeek
    if s.stage <> "qualifying" and s.stage <> "running" then return
    if m.video.state <> "playing" and m.video.state <> "paused" then return
    info = m.video.positionInfo
    if type(info) <> "roAssociativeArray" then return
    ' C208X OS16 evidence establishes this local zero-start mapping only.
    ' Neither epoch zero nor the requested PlayStart establishes decoder ownership.
    if info.epoch <> 0 or s.actualStart = invalid then return
    if s.actualStart <> 0 then return
    position = m.video.position
    if not SpNumber(position,604800) then return
    if s.stage = "qualifying"
        if s.firstPosition = invalid
            if position > 1 then return
            s.firstPosition = position
            return
        end if
        if position <= s.firstPosition or position > 2 then return
        s.stage = "running":s.sequence = 0:s.lastPosition = position
        state.stockGeneration = s.generationId
        state.engine.seekAck = {action:"bind_clock",requestId:s.requestId,generationId:s.generationId,epoch:s.epoch,nativeOriginUs:0&}
        state.landed = true
        if s.paused
            state.pendingPause = true:state.startPaused = true:state.pauseClock = CreateObject("roTimespan")
            m.video.control = "pause"
        end if
    else
        if position < s.lastPosition then return
        s.lastPosition = position
        if s.retired = true and s.released <> true
            state.engine.seekAck = {action:"release_previous",requestId:s.requestId,generationId:s.generationId,previousGenerationId:s.previousGenerationId}
            s.released = true
        end if
    end if
    nativeUs& = position*1000000#
    titleUs& = s.plan.titleOriginUs+nativeUs&
    s.positionMs = titleUs&/1000#:state.stockPositionMs = s.positionMs
    s.sequence++
    state.engine.playbackUpdate = {requestId:s.requestId,generationId:s.generationId,epoch:s.epoch,sequence:s.sequence,nativeUs:nativeUs&}
    if s.initial = true and state.playingSent <> true
        m.playLastPositionMs = Int(s.positionMs)
        m.nativeSeenPlaying = true
        SiloUICompatPlaying()
    end if
end sub


sub onSiloUICompatStockSeekBuffer(event as Object)
    state = m.compatPreparation
    if state = invalid or not SiloUICompatStockSeekOwned(state) then return
    if not m.video.isSameNode(event.getRoSGNode()) then return
    s = state.stockSeek
    if s.stage <> "loading" and s.stage <> "qualifying" then return
    data = event.getData()
    if type(data) <> "roAssociativeArray" then return
    if not SpNumber(data.actualStart,604800) then return
    s.actualStart = data.actualStart
end sub

function SiloUICompatExplicitAudioCurrent(intent as Object, detail as Dynamic) as Boolean
    if not SiloObject(detail) or not SiloObject(m.playAudioChoice) then return false
    choice = m.playAudioChoice
    if choice.sourceId <> m.sourceId or choice.profileId <> m.profileId or choice.generation <> m.generation or choice.visit <> m.detailToken then return false
    selected = SiloUIDetailAudioMatch(m.playAudioChoice,intent.itemId,intent.fileId,detail.versions)
    if selected = invalid then return false
    if SiloUIDetailAudioMatch(m.playAudioChoice,intent.itemId,intent.fileId,m.playVersions) = invalid then return false
    return selected.sourceOrdinal = intent.audioTrackIndex and intent.audioTrackId = "file:"+intent.fileId+":audio:"+Int(selected.sourceOrdinal).ToStr()
end function

function SiloUICompatCaptionBinding(caption as Dynamic, state as Object) as Boolean
    if not SpFields(caption,["disposition"],["uri","track"]) then return false
    file = SiloPlaybackFile(state.detail,state.owner.sourceId,state.intent.itemId,state.intent.fileId,state.intent.startPositionMs)
    if file = invalid then return false
    if caption.disposition = "unavailable" then return file.version.subtitleTracks.Count() = 0 and caption.Count() = 1
    if caption.disposition <> "ready" or not SiloUISubtitleLocalUri(caption.uri,"srt") then return false
    matches = 0
    for each track in file.version.subtitleTracks
        if FormatJson(track) = FormatJson(caption.track) then matches++
    end for
    return matches = 1
end function
