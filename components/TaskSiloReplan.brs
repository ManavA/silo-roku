' Quality changes replace a transport inside the captured logical Silo lease.
' This worker never DELETEs a session, including malformed or late responses.
function TaskSiloDecisionTracks(raw as Dynamic) as Dynamic
    if not SiloObject(raw) then return invalid
    for each key in raw
        if key <> "audio" and key <> "subtitle" then return invalid
        track = raw[key]
        if not SiloObject(track) then return invalid
        for each field in track
            if field <> "id" and field <> "index" then return invalid
        end for
    end for
    return SiloPlaybackTracks(raw)
end function

function TaskSiloDecisionQualities(raw as Dynamic) as Dynamic
    if not SiloArray(raw) then return invalid
    if raw.Count() > 16 then return invalid
    rows = []
    for each entry in raw
        if not SiloObject(entry) then return invalid
        row = {label:entry.label,preservesSource:entry.preserves_source}
        for each pair in [["height","height"],["bitrate_kbps","bitrateKbps"],["display_name","displayName"]]
            if entry.DoesExist(pair[0]) then row[pair[1]] = entry[pair[0]]
        end for
        rows.Push(row)
    end for
    return SiloPlaybackQualities(rows)
end function

function TaskSiloDecisionIdentity(decision as Object, fileId as String, knownSessionId = "" as String, allowedFileIds = invalid as Dynamic) as Boolean
    raw = decision.playback_plan
    if not SiloObject(raw) or not SiloObject(raw.source) then return false
    effective = raw.effective_media_file_id
    if not SpOpaque(effective) then return false
    allowed = effective = fileId
    if type(allowedFileIds) = "roArray"
        allowed = false
        for each id in allowedFileIds
            if id = effective then allowed = true
        end for
    end if
    if not allowed then return false
    if not SpOpaque(raw.source.media_file_id) or raw.source.media_file_id <> effective then return false
    if not SpOpaque(raw.requested_media_file_id) then return false
    if raw.requested_media_file_id <> fileId then return false
    if knownSessionId <> ""
        for each object in [decision,raw]
            value = object.session_id
            if value <> invalid
                if not SpOpaque(value) then return false
                if value <> knownSessionId then return false
            end if
        end for
    end if
    return true
end function

function TaskSiloPlanContext(plan as Object, decision as Object, session as Object, params as Object, revision as Integer, attemptId as String) as Dynamic
    raw = decision.playback_plan
    tracks = TaskSiloDecisionTracks(raw.selected_tracks)
    qualities = TaskSiloDecisionQualities(raw.available_qualities)
    if tracks = invalid or qualities = invalid then return invalid
    quality = TaskString(params,"qualityPreference")
    if quality = "" then quality = "original"
    context = {schemaVersion:1,sourceId:plan.sourceId,profileId:TaskString(session,"profileId"),itemId:plan.itemId,fileId:plan.versionId,sessionRevision:revision,
        installationId:plan.installationId,sessionId:plan.sessionId,playbackAttemptId:attemptId,planId:TaskString(plan,"planId"),planAttemptId:TaskUniqueId(),planAttemptKey:TaskString(plan,"planAttemptKey"),
        attemptedPlanKeys:[],attemptCount:0,allowAlternateVersions:false,qualityPreference:quality,selectedTracks:tracks,availableQualities:qualities}
    if params.DoesExist("bandwidthCapKbps") then context["bandwidthCapKbps"] = params.bandwidthCapKbps
    if params.DoesExist("mediaAuthMode") then context["mediaAuthMode"] = params.mediaAuthMode
    proof = {provider:"silo",sourceId:plan.sourceId,itemId:plan.itemId,versionId:plan.versionId,sessionId:plan.sessionId,installationId:plan.installationId,siloPlayback:context}
    scope = {provider:"silo",sourceId:plan.sourceId,profileId:context.profileId,generation:0}
    return SiloPlaybackContext(proof,scope)
end function

' A returned route may align earlier. Only a seekable route can restore target.
function TaskSiloSetTarget(plan as Object, decision as Object, targetMs as Dynamic) as Boolean
    raw = decision.playback_plan
    if not SiloObject(raw.timeline) or not SpNumber(targetMs,604800000) then return false
    player = raw.timeline.player_start_seconds:offset = raw.timeline.timeline_offset_seconds
    if not SpNumber(player,604800) or not SpNumber(offset,604800) or not SpBool(raw.timeline.can_seek_anywhere) then return false
    playerMs = player*1000#:offsetMs = offset*1000#
    target = targetMs-offsetMs
    if not SpNumber(target,604800000) then return false
    if raw.timeline.can_seek_anywhere
        plan["startPositionMs"] = target
    else
        delta = playerMs+offsetMs-targetMs
        if Abs(delta) > 1 then return false
        plan["startPositionMs"] = playerMs
    end if
    ' Wire seconds can carry sub-millisecond origins or native Float noise.
    ' Keep raw restoration checks/positions; canonical owner timing moves <=0.5ms.
    plan["timelineOffsetMs"] = Int(offsetMs + 0.5#)
    plan["originalResumeMs"] = targetMs
    return true
end function

function TaskSiloReplanCurrent(scope as Object, revision as Integer) as Boolean
    if SpScope(scope) = invalid then return false
    if SessionRevision("silo") <> revision then return false
    current = LoadSession("silo")
    if SessionRevision("silo") <> revision then return false
    return TaskString(current,"sourceId") = scope.sourceId and TaskString(current,"profileId") = scope.profileId
end function

' A playable receipt advances server ownership even when its media is refused.
' Validate the control plane independently before any subsequent replan.
function TaskSiloReplanReceipt(current as Object, decision as Object, context as Object, scope as Object) as Dynamic
    if not TaskSiloDecisionIdentity(decision,current.fileId,current.sessionId) then return invalid
    tracks = TaskSiloDecisionTracks(decision.playback_plan.selected_tracks)
    qualities = TaskSiloDecisionQualities(decision.playback_plan.available_qualities)
    if tracks = invalid or qualities = invalid then return invalid
    if FormatJson(tracks) <> FormatJson(context.selectedTracks) then return invalid
    receipt = SpCopy(context)
    receipt["planId"] = TaskString(decision.playback_plan,"plan_id")
    receipt["planAttemptKey"] = TaskString(decision.playback_plan,"plan_attempt_key")
    receipt["selectedTracks"] = tracks:receipt["availableQualities"] = qualities
    proof = {provider:"silo",sourceId:current.sourceId,itemId:current.itemId,versionId:current.fileId,sessionId:current.sessionId,installationId:current.installationId,siloPlayback:receipt}
    return SiloPlaybackContext(proof,scope)
end function

function TaskSiloRefusedReplan(code as String, current as Object, decision as Dynamic, context as Object, scope as Object) as Object
    failure = SiloPlaybackFailureDetails(TaskError(code),decision,"replan")
    if SiloContains(["playback_terminal","unsupported_stream"],code)
        failure["report"] = {installationId:current.installationId,playbackAttemptId:current.playbackAttemptId,sessionId:current.sessionId}
    end if
    failure["leaseUncertain"] = true
    if SiloObject(decision)
        receipt = TaskSiloReplanReceipt(current,decision,context,scope)
        if receipt <> invalid then failure["controlReceipt"] = receipt
    end if
    return failure
end function

' Refusal is not a playable plan. Validate the downstream metadata that the
' native HLS admission gate intentionally never reaches before skipping it.
function TaskSiloSkippableHLS(decision as Object, session as Object, current as Object, receipt as Dynamic, positionMs as Dynamic, requireOff as Boolean) as Boolean
    if receipt = invalid then return false
    raw = decision.playback_plan
    if not SiloObject(raw) or not SiloObject(raw.stream) then return false
    if raw.stream.protocol <> "hls" then return false
    if not SiloContains(["server_remux_hls","server_transcode_hls"],raw.delivery) then return false
    recipe = raw.effective_recipe
    if not SpFields(recipe,["video_codec","audio_codec","dynamic_range","width","height"],["video_sample_entry","frame_rate","bitrate_kbps","audio_channels","audio_layout"]) then return false
    for each field in ["video_codec","audio_codec","dynamic_range","video_sample_entry","audio_layout"]
        if recipe.DoesExist(field)
            if not SpText(recipe[field],64) then return false
        end if
    end for
    if not SpNumber(recipe.width,16384,true) or not SpNumber(recipe.height,16384,true) then return false
    if recipe.width = 0 or recipe.height = 0 then return false
    for each field in ["frame_rate","bitrate_kbps","audio_channels"]
        if recipe.DoesExist(field)
            if not SpNumber(recipe[field],1000000) then return false
        end if
    end for
    transforms = raw.transformations
    if not SiloArray(transforms) then return false
    if transforms.Count() > 16 then return false
    for each transform in transforms
        if not SpFields(transform,["name","executor","recipe_version"],["validated_claims"]) then return false
        for each field in ["name","executor","recipe_version"]
            if not SpText(transform[field],64) then return false
        end for
        if transform.DoesExist("validated_claims")
            if not SiloArray(transform.validated_claims) then return false
            if transform.validated_claims.Count() > 16 then return false
            for each claim in transform.validated_claims
                if not SpText(claim,64) then return false
            end for
        end if
    end for
    url = SiloResolveUrl(TaskString(raw.stream,"url"),TaskString(session,"baseUrl"))
    ' Even legacy skips must name the known API-owned same-lease route.
    if not SiloHeaderMediaUrlAllowed(url,TaskString(session,"baseUrl"),current.sessionId,current.fileId) then return false
    candidate = {url:url,sessionId:current.sessionId,versionId:current.fileId}
    if not TaskSiloApplyMediaAuth(candidate,session,TaskValue(current,"mediaAuthMode",invalid),SpField(raw.stream,"url")) then return false
    if not TaskSiloSetTarget(candidate,decision,positionMs) then return false
    if requireOff and not SiloSubtitleOffReceipt(raw) then return false
    subtitle = SiloSelectedSubtitleReceipt(raw,session.baseUrl,TaskString(decision,"session_id"))
    if subtitle.ok <> true or not SiloObject(subtitle.public) then return false
    requested = SpField(current.selectedTracks,"subtitle")
    if requested = invalid then return subtitle.public.kind = "off"
    chosen = subtitle.public
    if chosen.kind = "off" or chosen.kind = "unsupported" then return false
    return chosen.trackId = requested.id and chosen.combinedIndex = requested.index
end function

' Recovery routing shares one elapsed budget across discovery, POSTs and refresh.
' The remaining 11 seconds belong to the existing 10-second artifact worker
' and final publication. This state contains only control identities and a clock.
function TaskSiloRecoveryElapsedMs(budget as Object) as Integer
    return budget.clock.TotalMilliseconds()
end function

function TaskSiloRecoveryState(budget as Dynamic) as String
    if budget = invalid then return ""
    if m.top <> invalid
        if m.top.cancelled = true then return "cancelled"
    end if
    if not TaskSiloReplanCurrent(budget.scope,budget.revision) then return "session_changed"
    limit = 109000
    if SpField(budget,"kind") = "seek" then limit = 44000
    if TaskSiloRecoveryElapsedMs(budget) >= limit then return "network_timeout"
    return ""
end function

function TaskSiloRecoveryHttp(budget as Object, request as Object, ceiling as Integer) as Object
    state = TaskSiloRecoveryState(budget)
    budget["httpRefusal"] = state
    if state <> "" then return TaskError(state)
    limit = 109000
    if SpField(budget,"kind") = "seek" then limit = 44000
    remaining = limit - TaskSiloRecoveryElapsedMs(budget)
    if remaining < 1250
        budget["httpRefusal"] = "network_timeout"
        return TaskError("network_timeout")
    end if
    timeout = Int(remaining - 250)
    if timeout > ceiling then timeout = ceiling
    if SpField(budget,"kind") = "seek" and request.method = "POST" and Instr(1,request.url,"/replan") > 0 then budget["issued"] = true
    return HttpRequest(request,timeout)
end function

 ' The planner reserves the existing10s artifact stage plus1s publication.
' A cancelled/late worker returns only cleanup authority, never playable media.
function TaskSiloRecoveryPublication(outcome as Object, final as Boolean) as Object
    budget = m.siloRecoveryBudget
    if budget = invalid then return outcome
    if outcome.ok = true
        elapsed = TaskSiloRecoveryElapsedMs(budget)
        state = ""
        deadline = 109000
        if final then deadline = 120000
        if SpField(budget,"kind") = "seek"
            deadline = 44000
            if final then deadline = 55000
        end if
        if elapsed >= deadline then state = "network_timeout"
        if not TaskSiloReplanCurrent(budget.scope,budget.revision) then state = "session_changed"
        if SpField(budget,"kind") = "seek" then if not TaskSiloApprovalIdentityCurrent(budget.identity,budget.revision) then state = "session_changed"
        if m.top.cancelled = true then state = "cancelled"
        if state <> ""
            outcome["ok"] = false
            outcome["errorCode"] = state
        end if
    end if
    if outcome.ok <> true
        owned = m.siloRecoveryArtifact
        if type(owned) = "roAssociativeArray" then SiloSubtitleDelete(owned.uri)
        m.siloRecoveryArtifact = invalid
        m.siloSubtitlePending = invalid
        outcome.Delete("plan")
        if budget.latestReceipt <> invalid
            outcome["leaseUncertain"] = true
            outcome["controlReceipt"] = budget.latestReceipt
        end if
        if SpField(budget,"kind") = "seek" and budget.issued
            outcome["leaseUncertain"] = true:outcome["knownLease"] = SpCopy(budget.knownLease)
        end if
    else if final
        ' Ownership transfers to the returned plan only after the final fence.
        m.siloRecoveryArtifact = invalid
    end if
    return outcome
end function

function TaskReplanSiloPlayback(session as Object, params as Object, scope as Object, revision as Integer, audioDetail = invalid as Dynamic, originalWire = invalid as Dynamic, selectionKind = "" as String, seekAuthority = invalid as Dynamic) as Object
    if SiloObject(SpField(SpField(params,"plan"),"privateLegacyHdr10")) then return TaskError("invalid_request")
    checkedScope = SpScope(scope)
    if checkedScope = invalid then return TaskError("invalid_request")
    if params.DoesExist("failureClassification") and m.siloRecoveryBudget = invalid
        clock = CreateObject("roTimespan")
        clock.Mark()
        m.siloRecoveryBudget = {clock:clock,scope:checkedScope,revision:revision,refreshUsed:false,latestReceipt:invalid}
    end if
    if seekAuthority = invalid then seekAuthority = SiloSeekDescriptor(params.plan,scope)
    result = TaskReplanSiloPlaybackWorker(session,params,scope,revision,audioDetail,originalWire,selectionKind,seekAuthority)
    budget = m.siloRecoveryBudget
    if budget <> invalid and result.ok <> true
        if budget.latestReceipt <> invalid
            result["leaseUncertain"] = true
            result["controlReceipt"] = budget.latestReceipt
        end if
    end if
    return result
end function

function TaskReplanSiloPlaybackWorker(session as Object, params as Object, scope as Object, revision as Integer, audioDetail = invalid as Dynamic, originalWire = invalid as Dynamic, selectionKind = "" as String, seekAuthority = invalid as Dynamic) as Object
    if SiloObject(SpField(SpField(params,"plan"),"privateLegacyHdr10")) then return TaskError("invalid_request")
    if SpField(SpField(params,"plan"),"experimentalOriginal") = true then return TaskError("invalid_request")
    if not SpFields(params,["sessionId","plan","qualityPreference","positionMs","replanRequestId"],["selectedTracks","failureClassification"]) then return TaskError("invalid_request")
    if selectionKind <> "" and selectionKind <> "audio" and selectionKind <> "subtitle_off" and selectionKind <> "subtitle" then return TaskError("invalid_request")
    if selectionKind <> "" and params.DoesExist("failureClassification") then return TaskError("invalid_request")
    trackChange = selectionKind = "audio" or selectionKind = "subtitle_off" or selectionKind = "subtitle"
    current = SiloPlaybackContext(params.plan,scope)
    if current = invalid then return TaskError("invalid_request")
    if m.siloRecoveryBudget <> invalid
        used = m.siloRecoveryBudget.attemptCount
        if used <> invalid
            if used >= 8 then return TaskError("no_new_playback_route")
            if used > current.attemptCount then current["attemptCount"] = used
        end if
    end if
    if TaskString(params,"sessionId") <> current.sessionId then return TaskError("invalid_request")
    if current.sessionRevision <> revision or not TaskSiloReplanCurrent(scope,revision) then return TaskError("session_changed")
    audioFile = invalid
    if audioDetail <> invalid
        audioFile = SiloPlaybackFile(audioDetail,current.sourceId,current.itemId,current.fileId,params.positionMs)
        if audioFile = invalid then return TaskError("invalid_request")
        trackChange = true
    end if
    ' Only the validated explicit On ingress may clear sticky provider Off.
    if selectionKind = "subtitle" then current.Delete("subtitleOffRequired")
    preflight = SiloPlaybackReplanBody(current,params,{},{},trackChange)
    if preflight.ok <> true then return TaskError("invalid_request")
    requireSubtitleOff = selectionKind = "subtitle_off" or SpField(current,"subtitleOffRequired") = true
    if not params.DoesExist("failureClassification") and SpField(current.selectedTracks,"subtitle") <> invalid and SpField(preflight.context.selectedTracks,"subtitle") = invalid then requireSubtitleOff = true
    cached = invalid
    if m.siloRecoveryBudget <> invalid then cached = m.siloRecoveryBudget.discovery
    device = CreateObject("roDeviceInfo")
    if cached = invalid
        capabilityResult = TaskSiloFetch(session,"playback_capabilities",{},revision,6000,m.siloRecoveryBudget)
        if not TaskSiloReplanCurrent(scope,revision) then return TaskError("session_changed")
        if capabilityResult.ok <> true then return capabilityResult
        session = capabilityResult.session
        capability = DecodeSiloResponse("playback_capabilities",capabilityResult.response.body,{})
        if capability.ok <> true then return TaskError(TaskString(capability,"errorCode"))
        if TaskString(capability.data,"installationId") <> current.installationId then return TaskError("session_changed")
        if not SiloContains(capability.data.protocolVersions,3) then return SiloPlaybackFailureDetails(TaskError("unsupported_playback_protocol"),invalid,"replan")
        if current.DoesExist("mediaAuthMode")
            if not SiloContains(capability.data.features,"header_authenticated_media_v1") then return SiloPlaybackFailureDetails(TaskError("unsupported_playback_protocol"),invalid,"replan")
        end if
        decoderEvidence = {}
        capabilities = TaskRokuSiloCapabilities(device,decoderEvidence)
        context = TaskRokuSiloContext(device,capabilities)
        context = TaskNegotiateSiloHLS(context,device,capability.data,capabilities)
        if m.siloRecoveryBudget <> invalid then m.siloRecoveryBudget["discovery"] = {capability:capability,capabilities:capabilities,context:context,decoderEvidence:decoderEvidence}
    else
        capability = cached.capability:capabilities = cached.capabilities:context = cached.context:decoderEvidence = cached.decoderEvidence
    end if
    level50 = invalid:level50Capabilities = SpCopy(capabilities):level50Context = SpCopy(context)
    level50Hint = SpField(params.plan,"sourceHDR10Projection")
    if SiloObject(level50Hint) and params.qualityPreference = "original"
        if SpField(level50Hint,"fileId") <> current.fileId then return TaskError("invalid_request")
        level50Identity = {sourceId:TaskString(session,"sourceId"),profileId:TaskString(session,"profileId"),profileToken:TaskString(session,"profileToken"),baseUrl:TaskString(session,"baseUrl")}
        fresh = TaskSiloFetch(session,"detail",{itemId:current.itemId},revision,4000,m.siloRecoveryBudget,level50Identity)
        if not TaskSiloReplanCurrent(scope,revision) then return TaskError("session_changed")
        if fresh.ok <> true then return fresh
        session = fresh.session:level50Wire = ParseJson(fresh.response.body)
        decoded = DecodeSiloResponse("detail",fresh.response.body,{sourceId:current.sourceId,itemId:current.itemId})
        if decoded.ok <> true then return TaskError("invalid_response")
        level50Detail = ScopeCatalogData(decoded.data,current.sourceId)
        level50Intent = {qualityPreference:"original"}
        if current.DoesExist("bandwidthCapKbps") then level50Intent["bandwidthCapKbps"] = current.bandwidthCapKbps
        level50 = TaskSiloLevel50HDR10(level50Wire,level50Detail,current.sourceId,current.itemId,current.fileId,params.positionMs,level50Intent,device,capabilities,context,decoderEvidence)
        if level50 = invalid then return TaskError("unsupported_stream")
        if not SiloSeekEqual(level50.proof,level50Hint) then return TaskError("unsupported_stream")
        capabilities = level50.capabilities:context = level50.context
    end if
    mp4 = invalid:lastStereo = invalid
    originalDelivery = context.deliveries.original_http:hlsDelivery = context.deliveries.hls
    if (originalDelivery.enabled <> true or originalDelivery.supported_on_device <> true) and (hlsDelivery.enabled <> true or hlsDelivery.supported_on_device <> true)
        if params.qualityPreference = "original" and requireSubtitleOff and not trackChange
            identity = {sourceId:TaskString(session,"sourceId"),profileId:TaskString(session,"profileId"),profileToken:TaskString(session,"profileToken"),baseUrl:TaskString(session,"baseUrl")}
            fresh = TaskSiloFetch(session,"detail",{itemId:current.itemId},revision,4000,m.siloRecoveryBudget,identity)
            if not TaskSiloReplanCurrent(scope,revision) then return TaskError("session_changed")
            if fresh.ok <> true then return fresh
            session = fresh.session
            decoded = DecodeSiloResponse("detail",fresh.response.body,{sourceId:current.sourceId,itemId:current.itemId})
            if decoded.ok <> true then return TaskError("invalid_response")
            detail = ScopeCatalogData(decoded.data,current.sourceId)
            selectedAudio = SpField(current.selectedTracks,"audio")
            if SiloObject(selectedAudio)
                intent = {qualityPreference:"original",subtitleMode:"off",audioTrackId:SpField(selectedAudio,"id"),audioTrackIndex:SpField(selectedAudio,"index")}
                if current.DoesExist("bandwidthCapKbps") then intent["bandwidthCapKbps"] = current.bandwidthCapKbps
                mp4 = TaskSiloMp4Original(ParseJson(fresh.response.body),detail,current.sourceId,current.itemId,current.fileId,params.positionMs,intent,device,capabilities,context)
            end if
            if mp4 <> invalid
                capabilities = mp4.capabilities:context = mp4.context
                mp4["identity"] = identity
            end if
        end if
        if mp4 = invalid
            lastStereo = TaskSiloLastStereoHLS(device,capability.data,capabilities,context)
            if lastStereo = invalid then return TaskError("unsupported_device")
            capabilities = lastStereo.capabilities:context = lastStereo.context
            lastStereo["identity"] = {sourceId:TaskString(session,"sourceId"),profileId:TaskString(session,"profileId"),profileToken:TaskString(session,"profileToken"),baseUrl:TaskString(session,"baseUrl")}
        end if
    end if
    if audioDetail <> invalid
        audio = TaskSiloCompatibleAudio(audioFile.version,current.selectedTracks.audio,device,context)
        if audio = invalid then return TaskError("invalid_request")
        current = SiloPlaybackAudioContext(current,audioDetail,audio)
        if current = invalid then return TaskError("invalid_request")
    end if
    audioProjection = invalid:audioWire = originalWire:audioIdentity = invalid
    projectionSelected = SpField(preflight.context.selectedTracks,"audio")
    if audioDetail <> invalid then projectionSelected = SpField(current.selectedTracks,"audio")
    ' The retained URL-free hint only avoids probing every legacy request.
    ' It grants no authority: fresh owned inventory and SDK checks still follow.
    hint = SpField(params.plan,"sourceAudioProjection"):projectionHint = false
    if SpFields(hint,["fileId","container","audio"],[]) and SiloObject(projectionSelected)
        if SpFields(hint.audio,["id","index","codec","channels"],[])
            boundedHint = SpText(hint.fileId,256) and SpText(hint.container,16) and SpText(hint.audio.id,512) and SpText(hint.audio.codec,16)
            boundedHint = boundedHint and SpNumber(hint.audio.index,31,true) and SpNumber(hint.audio.channels,8,true)
            if boundedHint then projectionHint = hint.fileId = current.fileId and hint.audio.id = SpField(projectionSelected,"id") and hint.audio.index = SpField(projectionSelected,"index")
        end if
    end if
    if lastStereo = invalid and (projectionHint or originalWire <> invalid) and SiloContains(["original","4k","1080p","720p","480p"],params.qualityPreference) and context.deliveries.hls.enabled = true and context.deliveries.hls.supported_on_device = true
        if SiloObject(projectionSelected)
            identity = {sourceId:TaskString(session,"sourceId"),profileId:TaskString(session,"profileId"),profileToken:TaskString(session,"profileToken"),baseUrl:TaskString(session,"baseUrl")}
            audioIdentity = identity
            if audioWire = invalid
                fresh = TaskSiloFetch(session,"detail",{itemId:current.itemId},revision,4000,m.siloRecoveryBudget,identity)
                if not TaskSiloReplanCurrent(scope,revision) then return TaskError("session_changed")
                if fresh.ok <> true then return fresh
                session = fresh.session
                audioWire = ParseJson(fresh.response.body)
            end if
            decodedAudio = DecodeSiloResponse("detail",FormatJson(audioWire),{sourceId:current.sourceId,itemId:current.itemId})
            if decodedAudio.ok <> true then return TaskError("invalid_response")
            audioInventory = ScopeCatalogData(decodedAudio.data,current.sourceId)
            if SiloPlaybackFile(audioInventory,current.sourceId,current.itemId,current.fileId,params.positionMs) = invalid then return TaskError("invalid_response")
            audioProjection = TaskSiloAudioProjection(audioWire,current.fileId,projectionSelected,params.qualityPreference,device,capabilities,context)
            if audioProjection <> invalid
                capabilities = audioProjection.capabilities:context = audioProjection.context
                audioProjection["identity"] = identity
            end if
        end if
    end if
    originalCandidate = invalid
    guarded = SiloObject(params.plan.originalPlayback)
    if guarded and params.DoesExist("failureClassification") then current["originalDisabled"] = true
    qualifyOriginal = (SiloOriginalActivationEnabled() or SiloP8OriginalActivationEnabled()) and current.originalDisabled <> true and not params.DoesExist("failureClassification")
    if not guarded and (params.qualityPreference <> "original" or audioDetail <> invalid) then qualifyOriginal = false
    if lastStereo = invalid and qualifyOriginal and audioProjection = invalid
        ' A user audio ingress has already fetched this raw same-file detail.
        ' Its private argument never comes from the external request schema.
        freshWire = originalWire
        candidateReady = true
        if freshWire = invalid
            fresh = TaskSiloFetch(session,"detail",{itemId:current.itemId},revision,4000)
            if not TaskSiloReplanCurrent(scope,revision) then return TaskError("session_changed")
            if fresh.ok <> true
                if guarded then return fresh
                candidateReady = false
            else
                session = fresh.session
                freshWire = ParseJson(fresh.response.body)
            end if
        end if
        if candidateReady
            decoded = DecodeSiloResponse("detail",FormatJson(freshWire),{sourceId:current.sourceId,itemId:current.itemId})
            if decoded.ok <> true
                if guarded then return TaskError("invalid_response")
                candidateReady = false
            else
                detail = ScopeCatalogData(decoded.data,current.sourceId)
                if SiloPlaybackFile(detail,current.sourceId,current.itemId,current.fileId,params.positionMs) = invalid
                    if guarded then return TaskError("invalid_response")
                    candidateReady = false
                end if
            end if
        end if
        if candidateReady
            intent = {itemId:current.itemId,qualityPreference:params.qualityPreference}
            audio = SpField(current.selectedTracks,"audio")
            if audio <> invalid
                intent["audioTrackIndex"] = audio.index
                if audio.DoesExist("id") then intent["audioTrackId"] = audio.id
            end if
            if current.DoesExist("bandwidthCapKbps") then intent["bandwidthCapKbps"] = current.bandwidthCapKbps
            ' The accepted receipt's absent subtitle selector is authoritative None.
            ' A currently requested source subtitle must use the normal planner.
            subtitle = SpField(preflight.context.selectedTracks,"subtitle")
            if subtitle = invalid
                intent["subtitleMode"] = "off"
            else
                intent["subtitleTrackId"] = subtitle.id
                if subtitle.DoesExist("index") then intent["subtitleTrackIndex"] = subtitle.index
            end if
            originalCandidate = TaskSiloOriginalCandidate(freshWire,session,current.fileId,intent,device,current.playbackAttemptId,scope,context)
            if originalCandidate <> invalid then context.deliveries.original_http.validated_claims = originalCandidate.claims
        end if
    end if
    routeParams = {qualityPreference:params.qualityPreference,positionMs:params.positionMs,replanRequestId:params.replanRequestId}
    for each field in ["failureClassification","selectedTracks"]
        if params.DoesExist(field) then routeParams[field] = SpCopy(params[field])
    end for
    while true
    built = SiloPlaybackReplanBody(current,routeParams,capabilities,context,trackChange)
    if built.ok <> true
        failure = TaskError("no_new_playback_route")
        failure["leaseUncertain"] = true
        failure["controlReceipt"] = current
        return failure
    end if
    built.body.client_features = SiloClientPlaybackFeatures(context,TaskValue(current,"mediaAuthMode",invalid))
    if built.body.client_features = invalid then return TaskError("invalid_request")
    ' Discovery cannot upgrade an attempt that did not negotiate seek at Start.
    retainedSeek = seekAuthority
    if retainedSeek <> invalid and SiloSeekFeatures(capability.data.features) <> invalid then built.body.client_features.Push("seek_reanchor_v1")
    if not TaskSiloReplanCurrent(scope,revision) then return TaskError("session_changed")
    replanTimeout = 12000
    if SiloNativeDeliveryFeatures(context).Count() > 0 then replanTimeout = 90000
    if m.siloRecoveryBudget <> invalid then m.siloRecoveryBudget["attemptCount"] = built.context.attemptCount
    if level50 <> invalid
        fetched = TaskSiloFetch(session,"playback_replan",{sessionId:current.sessionId,body:built.body},revision,replanTimeout,m.siloRecoveryBudget,level50Identity,true)
    else if lastStereo <> invalid
        fetched = TaskSiloFetch(session,"playback_replan",{sessionId:current.sessionId,body:built.body},revision,replanTimeout,m.siloRecoveryBudget,lastStereo.identity,true)
    else if audioIdentity <> invalid
        fetched = TaskSiloFetch(session,"playback_replan",{sessionId:current.sessionId,body:built.body},revision,replanTimeout,m.siloRecoveryBudget,audioIdentity,true)
    else if mp4 = invalid
        fetched = TaskSiloFetch(session,"playback_replan",{sessionId:current.sessionId,body:built.body},revision,replanTimeout,m.siloRecoveryBudget)
    else
        fetched = TaskSiloFetch(session,"playback_replan",{sessionId:current.sessionId,body:built.body},revision,replanTimeout,m.siloRecoveryBudget,mp4.identity,true)
    end if
    if fetched.ok <> true then fetched["leaseUncertain"] = true : return fetched
    session = fetched.session
    decision = ParseJson(fetched.response.body)
    if not SiloObject(decision) then return TaskSiloRefusedReplan("invalid_response",current,decision,built.context,scope)
    ' A late allocated response still transfers cleanup authority. Parse its
    ' control receipt before checking cancellation, scope or elapsed time.
    returnedReceipt = TaskSiloReplanReceipt(current,decision,built.context,scope)
    if returnedReceipt <> invalid and m.siloRecoveryBudget <> invalid then m.siloRecoveryBudget.latestReceipt = returnedReceipt
    if lastStereo <> invalid
        if not TaskSiloApprovalIdentityCurrent(lastStereo.identity,revision) then return TaskSiloRefusedReplan("session_changed",current,decision,built.context,scope)
        if m.top.cancelled = true then return TaskSiloRefusedReplan("cancelled",current,decision,built.context,scope)
    end if
    if audioIdentity <> invalid
        if not TaskSiloApprovalIdentityCurrent(audioIdentity,revision) then return TaskSiloRefusedReplan("session_changed",current,decision,built.context,scope)
        if m.top.cancelled = true then return TaskSiloRefusedReplan("cancelled",current,decision,built.context,scope)
    end if
    if level50 <> invalid
        if not TaskSiloApprovalIdentityCurrent(level50Identity,revision) then return TaskSiloRefusedReplan("session_changed",current,decision,built.context,scope)
        if m.top.cancelled = true then return TaskSiloRefusedReplan("cancelled",current,decision,built.context,scope)
    end if
    if mp4 <> invalid
        if not TaskSiloApprovalIdentityCurrent(mp4.identity,revision) then return TaskSiloRefusedReplan("session_changed",current,decision,built.context,scope)
        if m.top.cancelled = true then return TaskSiloRefusedReplan("cancelled",current,decision,built.context,scope)
    end if
    state = TaskSiloRecoveryState(m.siloRecoveryBudget)
    if state <> "" then return TaskSiloRefusedReplan(state,current,decision,built.context,scope)
    if not TaskSiloReplanCurrent(scope,revision) then return TaskSiloRefusedReplan("session_changed",current,decision,built.context,scope)
    if level50 <> invalid and SpField(decision,"playback_plan") <> invalid
        if not TaskSiloLevel50HDR10Receipt(decision,level50.proof) then return TaskSiloRefusedReplan("invalid_response",current,decision,built.context,scope)
        checkedLevel50 = TaskSiloLevel50HDR10(level50Wire,level50Detail,current.sourceId,current.itemId,current.fileId,params.positionMs,level50Intent,device,level50Capabilities,level50Context,decoderEvidence)
        if checkedLevel50 = invalid then return TaskSiloRefusedReplan("session_changed",current,decision,built.context,scope)
        if not SiloSeekEqual(checkedLevel50.proof,level50.proof) then return TaskSiloRefusedReplan("session_changed",current,decision,built.context,scope)
    end if
    try
        receiptContext = context
        ' A fresh gated Original candidate still requires its exact receipt below.
        if originalCandidate <> invalid and TaskString(decision.playback_plan,"delivery") = "original_http" then receiptContext = invalid
        plan = SiloPlaybackPlan(decision,session,SiloNativeDeliveryFeatures(context),invalid,receiptContext)
    catch exception
        return TaskSiloRefusedReplan("invalid_response",current,decision,built.context,scope)
    end try
    if plan.ok = true
        if not TaskSiloDeliveredHLSSupported(decision.playback_plan,device) then return TaskSiloRefusedReplan("unsupported_stream",current,decision,built.context,scope)
    end if
    if lastStereo <> invalid and plan.ok = true then if not TaskSiloLastStereoReceipt(decision) then return TaskSiloRefusedReplan("invalid_response",current,decision,built.context,scope)
    if audioProjection <> invalid and plan.ok = true then if not TaskSiloAudioProjectionReceipt(decision,audioProjection) then return TaskSiloRefusedReplan("invalid_response",current,decision,built.context,scope)
    if mp4 <> invalid and plan.ok = true then if not TaskSiloMp4Receipt(decision,mp4.proof) then return TaskSiloRefusedReplan("invalid_response",current,decision,built.context,scope)
    skipped = false
    if plan.ok <> true
        oversizedAVC = plan.errorCode = "unsupported_stream" and SiloNativeH264Oversized(decision.playback_plan)
        unsupportedHLS = plan.errorCode = "unsupported_stream" and SpField(SpField(decision.playback_plan,"stream"),"protocol") = "hls"
        if unsupportedHLS and params.DoesExist("failureClassification")
            receipt = TaskSiloReplanReceipt(current,decision,built.context,scope)
            if SiloContains(built.body.attempted_plan_keys,TaskString(decision.playback_plan,"plan_attempt_key")) then return TaskSiloRefusedReplan("no_new_playback_route",current,decision,built.context,scope)
            if TaskSiloSkippableHLS(decision,session,current,receipt,params.positionMs,requireSubtitleOff)
                current = receipt
                routeParams.replanRequestId = TaskUniqueId()
                ' Retain only the URL-free validated control receipt in the loop.
                skipped = true
            end if
        end if
        if not skipped
        if (TaskString(plan,"errorCode") = "playback_terminal" or oversizedAVC or unsupportedHLS) and params.DoesExist("failureClassification") and params.plan.allowQualityFallback = true
            fallbackQuality = SiloFallbackQuality(params.qualityPreference,TaskString(capabilities,"max_resolution"),current.availableQualities)
            if fallbackQuality <> "" and SiloContains(SiloList(context.deliveries.hls.video_codecs),"h264")
                retry = SpCopy(params)
                retry.qualityPreference = fallbackQuality
                retry.replanRequestId = TaskUniqueId()
                ' Terminal decisions have no new media receipt; carry the
                ' current control identity, including earlier skipped routes.
                retry.plan["planId"] = current.planId
                retry.plan["planAttemptKey"] = current.planAttemptKey
                retry.plan["siloPlayback"] = SpCopy(current)
                if oversizedAVC or unsupportedHLS
                    receipt = TaskSiloReplanReceipt(current,decision,built.context,scope)
                    if receipt = invalid then return TaskError("invalid_response")
                    retry.plan["planId"] = receipt.planId
                    retry.plan["planAttemptKey"] = receipt.planAttemptKey
                    retry.plan["siloPlayback"] = receipt
                end if
                return TaskReplanSiloPlayback(session,retry,scope,revision,audioDetail,audioWire,selectionKind,seekAuthority)
            end if
        end if
        return TaskSiloRefusedReplan(TaskString(plan,"errorCode"),current,decision,built.context,scope)
        end if
    end if
    if not skipped
    subtitleReceipt = SiloSelectedSubtitleReceipt(decision.playback_plan,session.baseUrl,TaskString(decision,"session_id"))
    if subtitleReceipt.ok <> true
        plan["selectedSubtitle"] = {kind:"unsupported",renderingReady:false}
    else if subtitleReceipt.public <> invalid
        plan["selectedSubtitle"] = subtitleReceipt.public
    end if
    if params.DoesExist("failureClassification")
        if SiloContains(built.body.attempted_plan_keys,TaskString(plan,"planAttemptKey")) then return TaskSiloRefusedReplan("no_new_playback_route",current,decision,built.context,scope)
    end if
    if requireSubtitleOff
        if not SiloSubtitleOffReceipt(decision.playback_plan) then return TaskSiloRefusedReplan("invalid_response",current,decision,built.context,scope)
    end if
    receipt = TaskSiloReplanReceipt(current,decision,built.context,scope)
    if receipt = invalid
        if requireSubtitleOff or selectionKind = "subtitle" then return TaskSiloRefusedReplan("invalid_response",current,decision,built.context,scope)
        return TaskError("invalid_response")
    end if
    plan["provider"] = "silo":plan["sourceId"] = current.sourceId:plan["itemId"] = current.itemId:plan["versionId"] = current.fileId
    plan["sessionId"] = current.sessionId:plan["installationId"] = current.installationId:plan["relativeTimeline"] = true
    if not TaskSiloApplyMediaAuth(plan,session,TaskValue(current,"mediaAuthMode",invalid),SpField(SpField(decision.playback_plan,"stream"),"url")) then return TaskSiloRefusedReplan("invalid_response",current,decision,built.context,scope)
    if not TaskSiloSetTarget(plan,decision,params.positionMs) then return TaskSiloRefusedReplan("invalid_response",current,decision,built.context,scope)
    if guarded and params.DoesExist("failureClassification") and TaskString(decision.playback_plan,"delivery") = "original_http" then return TaskSiloRefusedReplan("no_new_playback_route",current,decision,built.context,scope)
    if TaskString(decision.playback_plan,"decision_reason") = "client_managed_dynamic_range" and originalCandidate = invalid then return TaskSiloRefusedReplan("invalid_original_receipt",current,decision,built.context,scope)
    if TaskString(decision.playback_plan,"delivery") = "original_http" and originalCandidate <> invalid
        checkedOriginal = TaskSiloOriginalDescriptor(originalCandidate,decision,plan,scope)
        if checkedOriginal.ok <> true then return TaskSiloRefusedReplan("invalid_original_receipt",current,decision,built.context,scope)
        plan["originalPlayback"] = checkedOriginal.descriptor
    else if guarded and TaskString(decision.playback_plan,"delivery") = "original_http"
        return TaskSiloRefusedReplan("invalid_original_receipt",current,decision,built.context,scope)
    end if
    if audioProjection <> invalid then plan["sourceAudioProjection"] = SpCopy(audioProjection.proof)
    if level50 <> invalid then plan["sourceHDR10Projection"] = SpCopy(level50.proof)
    plan["playbackDiagnostics"] = TaskSiloPlaybackDiagnostics(decision.playback_plan)
    if requireSubtitleOff then receipt["subtitleOffRequired"] = true
    plan["siloPlayback"] = receipt
    TaskSiloRetainSeek(plan,decision,SpField(fetched,"requestBody"),capability.data.features,scope)
    if SiloObject(params.plan.autoVersionRequest)
        plan["autoVersionRequest"] = SpCopy(params.plan.autoVersionRequest)
        if selectionKind = "subtitle"
            ' Source ordinals belong only to this exact file, never alternates.
            for each key in ["subtitleOffRequired","subtitleMode","subtitleTrackId","subtitleTrackIndex"]
                plan.autoVersionRequest.Delete(key)
            end for
        end if
    end if
    if selectionKind = "subtitle"
        requestedSubtitle = SpField(built.context.selectedTracks,"subtitle")
        freshInventory = SiloSourceSubtitleInventory(decision.playback_plan,plan,scope)
        if freshInventory = invalid or subtitleReceipt.ok <> true then return TaskSiloRefusedReplan("invalid_response",current,decision,built.context,scope)
        chosen = subtitleReceipt.public
        if not SiloObject(chosen) then return TaskSiloRefusedReplan("invalid_response",current,decision,built.context,scope)
        if chosen.kind = "off" or chosen.kind = "unsupported" or chosen.trackId <> requestedSubtitle.id or chosen.combinedIndex <> requestedSubtitle.index then return TaskSiloRefusedReplan("invalid_response",current,decision,built.context,scope)
        checkedPlan = SpCopy(plan):checkedPlan["sourceSubtitleInventory"] = freshInventory
        if SiloUserSubtitleSelection(checkedPlan,scope,requestedSubtitle.id,requestedSubtitle.index) = invalid then return TaskSiloRefusedReplan("invalid_response",current,decision,built.context,scope)
    end if
    plan["allowQualityFallback"] = params.plan.allowQualityFallback = true
    if not TaskSiloReplanCurrent(scope,revision) then return TaskError("session_changed")
    TaskSiloRememberSelectedSubtitle(plan,subtitleReceipt,session,revision,decision.playback_plan)
    return {ok:true,data:{outcome:"plan",sessionId:current.sessionId},plan:plan}
    end if
    end while
end function

' Dedicated user-selection ingress. The caller supplies only an index and an
' owned plan; fresh catalog identity and native channel/codec proof authorize a
' new lane internally. Generic quality/recovery requests retain their allowlist.
function TaskSelectSiloAudio(session as Object, params as Object, scope as Object, revision as Integer) as Object
    if SiloObject(SpField(SpField(params,"plan"),"privateLegacyHdr10")) then return TaskError("invalid_request")
    if SpField(SpField(params,"plan"),"experimentalOriginal") = true then return TaskError("invalid_request")
    if not SpFields(params,["sessionId","plan","positionMs","replanRequestId","audioTrackIndex"],[]) then return TaskError("invalid_request")
    current = SiloPlaybackContext(params.plan,scope)
    if current = invalid then return TaskError("invalid_request")
    if params.sessionId <> current.sessionId or not SpNumber(params.audioTrackIndex,4095,true) or not SpNumber(params.positionMs,604800000) or not SpOpaque(params.replanRequestId,128,8) then return TaskError("invalid_request")
    if current.sessionRevision <> revision or not TaskSiloReplanCurrent(scope,revision) then return TaskError("session_changed")
    fresh = TaskSiloFetch(session,"detail",{itemId:current.itemId},revision,4000)
    if not TaskSiloReplanCurrent(scope,revision) then return TaskError("session_changed")
    if fresh.ok <> true then return fresh
    session = fresh.session
    wire = ParseJson(fresh.response.body)
    decoded = DecodeSiloResponse("detail",fresh.response.body,{sourceId:current.sourceId,itemId:current.itemId})
    if decoded.ok <> true then return TaskError("invalid_response")
    detail = ScopeCatalogData(decoded.data,current.sourceId)
    selected = SiloUserAudioSelection(current,detail,wire,params.audioTrackIndex)
    if selected = invalid then return TaskError("invalid_audio_selection")
    device = CreateObject("roDeviceInfo")
    if not TaskSiloAudioTrackPlayable(selected,device) then return TaskError("unsupported_audio_selection")
    authorized = SiloPlaybackAudioContext(current,detail,selected)
    if authorized = invalid then return TaskError("invalid_audio_selection")
    seekAuthority = SiloSeekDescriptor(params.plan,scope)
    ownedPlan = SpCopy(params.plan)
    ownedPlan["siloPlayback"] = authorized
    replan = {sessionId:current.sessionId,plan:ownedPlan,qualityPreference:current.qualityPreference,positionMs:params.positionMs,replanRequestId:params.replanRequestId}
    if not TaskSiloReplanCurrent(scope,revision) then return TaskError("session_changed")
    result = TaskReplanSiloPlayback(session,replan,scope,revision,invalid,wire,"audio",seekAuthority)
    if result.ok = true and SiloObject(result.plan)
        ' A source stream index does not establish a native Video Track ID.
        ' Until direct-file mapping is proven, only the validated server HLS
        ' recipe may bind an explicit catalog lane.
        if result.plan.streamFormat <> "hls" and not SiloObject(result.plan.originalPlayback)
            failure = TaskError("unsupported_direct_audio_mapping")
            failure["leaseUncertain"] = true
            failure["controlReceipt"] = result.plan.siloPlayback
            return failure
        end if
    end if
    if result.ok = true and SiloObject(result.plan)
        result["audioPreference"] = SiloAudioPreference(detail.item,current.fileId,selected.sourceOrdinal,detail.versions)
    end if
    return result
end function

' Off is a same-lease track mutation, never a synthetic quality or native hide.
function TaskSelectSiloSubtitleOff(session as Object, params as Object, scope as Object, revision as Integer) as Object
    if not SpFields(params,["sessionId","plan","positionMs","replanRequestId"],[]) then return TaskError("invalid_request")
    current = SiloPlaybackContext(params.plan,scope)
    if current = invalid then return TaskError("invalid_request")
    if params.sessionId <> current.sessionId or not SpNumber(params.positionMs,604800000) or not SpOpaque(params.replanRequestId,128,8) then return TaskError("invalid_request")
    if current.sessionRevision <> revision or not TaskSiloReplanCurrent(scope,revision) then return TaskError("session_changed")
    tracks = SpCopy(current.selectedTracks)
    tracks.Delete("subtitle")
    replan = {sessionId:current.sessionId,plan:params.plan,qualityPreference:current.qualityPreference,positionMs:params.positionMs,replanRequestId:params.replanRequestId,selectedTracks:tracks}
    return TaskReplanSiloPlayback(session,replan,scope,revision,invalid,invalid,"subtitle_off")
end function

' Exact owned source inventory authorizes only this same-file subtitle mutation.
function TaskSelectSiloSubtitle(session as Object, params as Object, scope as Object, revision as Integer) as Object
    if SiloObject(SpField(SpField(params,"plan"),"privateLegacyHdr10")) then return TaskError("invalid_request")
    if SpField(SpField(params,"plan"),"experimentalOriginal") = true then return TaskError("invalid_request")
    if not SpFields(params,["sessionId","plan","positionMs","replanRequestId","subtitleTrackId","subtitleTrackIndex"],[]) then return TaskError("invalid_request")
    current = SiloPlaybackContext(params.plan,scope)
    if current = invalid then return TaskError("invalid_request")
    if params.sessionId <> current.sessionId or not SpNumber(params.positionMs,604800000) or not SpOpaque(params.replanRequestId,128,8) then return TaskError("invalid_request")
    if current.sessionRevision <> revision or not TaskSiloReplanCurrent(scope,revision) then return TaskError("session_changed")
    selected = SiloUserSubtitleSelection(params.plan,scope,params.subtitleTrackId,params.subtitleTrackIndex)
    if selected = invalid then return TaskError("invalid_subtitle_selection")
    authorized = SpCopy(current)
    authorized.selectedTracks["subtitle"] = selected
    authorized.Delete("subtitleOffRequired")
    seekAuthority = SiloSeekDescriptor(params.plan,scope)
    ownedPlan = SpCopy(params.plan):ownedPlan["siloPlayback"] = authorized
    replan = {sessionId:current.sessionId,plan:ownedPlan,qualityPreference:current.qualityPreference,positionMs:params.positionMs,replanRequestId:params.replanRequestId}
    return TaskReplanSiloPlayback(session,replan,scope,revision,invalid,invalid,"subtitle",seekAuthority)
end function

' Exact built HTTP request facts, never a regenerated capability/menu snapshot.
sub TaskSiloRetainSeek(plan as Object, decision as Dynamic, wire as Dynamic, discovered as Dynamic, scope as Dynamic)
    plan.Delete("seekReanchor")
    if SiloSeekFeatures(discovered) = invalid or SiloSeekFeatures(SpField(decision,"server_features")) = invalid then return
    if not SiloObject(wire) then return
    if SiloSeekFeatures(SpField(wire,"client_features")) = invalid then return
    current = SiloPlaybackContext(plan,scope)
    if current = invalid then return
    route = SiloSeekRoute(SpField(decision,"playback_plan"))
    timeline = SiloSeekTimeline(SpField(SpField(decision,"playback_plan"),"timeline"))
    if route = invalid or timeline = invalid then return
    request = {}
    for each key in ["client_capabilities","client_playback_context","client_features","quality_preference","metered","bandwidth_cap_kbps","bandwidth_estimate_kbps"]
        if wire.DoesExist(key) then request[key] = SpCopy(wire[key])
    end for
    descriptor = {schemaVersion:1,owner:SpScope(scope),control:current,request:request,route:route,timeline:timeline,discoveryFeatures:SpCopy(discovered),serverFeatures:SpCopy(decision.server_features)}
    plan["seekReanchor"] = descriptor
    if SiloSeekDescriptor(plan,scope) = invalid then plan.Delete("seekReanchor")
end sub

' No discovery, projection, failure blacklist, fallback loop or second lease.
function TaskSeekSiloPlayback(session as Object, params as Object, scope as Object, revision as Integer) as Object
    if not SpFields(params,["sessionId","plan","positionMs","replanRequestId"],[]) then return TaskError("invalid_request")
    if not SpNumber(params.positionMs,604800000) or not SiloSeekUuid(params.replanRequestId) then return TaskError("invalid_request")
    descriptor = SiloSeekDescriptor(params.plan,scope)
    current = SiloPlaybackContext(params.plan,scope)
    if descriptor = invalid or current = invalid then return TaskError("seek_unavailable")
    if params.sessionId <> current.sessionId then return TaskError("invalid_request")
    if current.sessionRevision <> revision or not TaskSiloReplanCurrent(scope,revision) then return TaskError("session_changed")
    runtime = SpField(descriptor.route.source,"duration_seconds")
    if runtime <> invalid then if params.positionMs >= runtime*1000# then return TaskError("invalid_request")
    clock = CreateObject("roTimespan"):clock.Mark()
    ' Scene reserves at most5s for stop. This Task owns the remaining55s;
    ' HTTP/refresh ends by44s, leaving10s artifact plus1s final publication.
    budget = {clock:clock,scope:SpScope(scope),revision:revision,refreshUsed:false,latestReceipt:invalid,kind:"seek",issued:false,knownLease:SpCopy(current)}
    m.siloRecoveryBudget = budget
    body = SpCopy(descriptor.request)
    body["operation"] = "seek_reanchor":body["installation_id"] = current.installationId:body["protocol_version"] = 3
    body["playback_attempt_id"] = current.playbackAttemptId:body["replan_request_id"] = params.replanRequestId
    body["failed_plan_id"] = current.planId:body["plan_attempt_id"] = LCase(CreateObject("roDeviceInfo").GetRandomUUID()):body["plan_attempt_key"] = current.planAttemptKey
    body["attempt_count"] = 1:body["attempted_plan_keys"] = [current.planAttemptKey]
    body["selected_tracks"] = SpCopy(current.selectedTracks):body["position_seconds"] = params.positionMs/1000#
    if not SiloSeekUuid(body.plan_attempt_id) or not SiloReplanBodyValid(body) then return TaskError("invalid_request")
    identity = {sourceId:TaskString(session,"sourceId"),profileId:TaskString(session,"profileId"),profileToken:TaskString(session,"profileToken"),baseUrl:TaskString(session,"baseUrl")}
    budget["identity"] = identity
    try
        fetched = TaskSiloFetch(session,"playback_replan",{sessionId:current.sessionId,body:body},revision,45000,budget,identity,true)
        if fetched.ok <> true then return TaskSiloSeekFailure(fetched,current,budget)
        session = fetched.session:decision = ParseJson(fetched.response.body)
        receipt = TaskSiloReplanReceipt(current,decision,current,scope)
        if receipt <> invalid then budget.latestReceipt = receipt
        if not TaskSiloApprovalIdentityCurrent(identity,revision) then return TaskSiloSeekFailure(TaskError("session_changed"),current,budget)
        state = TaskSiloRecoveryState(budget)
        if state <> "" then return TaskSiloSeekFailure(TaskError(state),current,budget)
        if receipt = invalid then return TaskSiloSeekFailure(TaskError("invalid_response"),current,budget)
        if receipt.planId <> current.planId or receipt.planAttemptKey <> current.planAttemptKey then return TaskSiloSeekFailure(TaskError("invalid_response"),current,budget)
        route = SiloSeekRoute(SpField(decision,"playback_plan"))
        if route = invalid or not SiloSeekEqual(route,descriptor.route) then return TaskSiloSeekFailure(TaskError("invalid_response"),current,budget)
        if SiloSeekFeatures(SpField(decision,"server_features")) = invalid then return TaskSiloSeekFailure(TaskError("invalid_response"),current,budget)
        raw = decision.playback_plan:timeline = SiloSeekTimeline(raw.timeline)
        if timeline = invalid then return TaskSiloSeekFailure(TaskError("invalid_response"),current,budget)
        if Abs(timeline.source_start_seconds*1000#-params.positionMs) > 1 then return TaskSiloSeekFailure(TaskError("invalid_response"),current,budget)
        if timeline.stream_origin_seconds <> timeline.timeline_offset_seconds then return TaskSiloSeekFailure(TaskError("invalid_response"),current,budget)
        if timeline.can_seek_anywhere = false
            if SpField(timeline,"seek_window_start_seconds") <> timeline.stream_origin_seconds or timeline.seek_restoration <> "source_position" then return TaskSiloSeekFailure(TaskError("invalid_response"),current,budget)
            if timeline.stream_origin_seconds*1000# > params.positionMs then return TaskSiloSeekFailure(TaskError("invalid_response"),current,budget)
        end if
        if timeline.DoesExist("seek_window_end_seconds") then if timeline.seek_window_end_seconds*1000# < params.positionMs then return TaskSiloSeekFailure(TaskError("invalid_response"),current,budget)
        plan = SiloPlaybackPlan(decision,session,SiloNativeDeliveryFeatures(descriptor.request.client_playback_context),invalid,descriptor.request.client_playback_context)
        if plan.ok <> true then return TaskSiloSeekFailure(plan,current,budget)
        if not TaskSiloDeliveredHLSSupported(raw,CreateObject("roDeviceInfo")) then return TaskSiloSeekFailure(TaskError("unsupported_stream"),current,budget)
        plan["provider"] = "silo":plan["sourceId"] = current.sourceId:plan["itemId"] = current.itemId:plan["versionId"] = current.fileId
        plan["installationId"] = current.installationId:plan["relativeTimeline"] = true
        if not TaskSiloApplyMediaAuth(plan,session,SpField(current,"mediaAuthMode"),raw.stream.url) then return TaskSiloSeekFailure(TaskError("invalid_response"),current,budget)
        if not TaskSiloSetTarget(plan,decision,params.positionMs) then return TaskSiloSeekFailure(TaskError("invalid_response"),current,budget)
        subtitle = SiloSelectedSubtitleReceipt(raw,session.baseUrl,current.sessionId)
        if subtitle.ok <> true then return TaskSiloSeekFailure(TaskError("invalid_response"),current,budget)
        if subtitle.public <> invalid then plan["selectedSubtitle"] = subtitle.public
        if SpField(current,"subtitleOffRequired") = true then if not SiloSubtitleOffReceipt(raw) then return TaskSiloSeekFailure(TaskError("invalid_response"),current,budget)
        plan["siloPlayback"] = receipt
        for each key in ["autoVersionRequest","allowQualityFallback","sourceAudioProjection","sourceHDR10Projection"]
            if params.plan.DoesExist(key) then plan[key] = SpCopy(params.plan[key])
        end for
        plan["playbackDiagnostics"] = TaskSiloPlaybackDiagnostics(raw)
        TaskSiloRetainSeek(plan,decision,fetched.requestBody,descriptor.discoveryFeatures,scope)
        if not plan.DoesExist("seekReanchor") then return TaskSiloSeekFailure(TaskError("invalid_response"),current,budget)
        TaskSiloRememberSelectedSubtitle(plan,subtitle,session,revision,raw)
        return {ok:true,data:{outcome:"plan",sessionId:current.sessionId},plan:plan}
    catch exception
        return TaskSiloSeekFailure(TaskError("task_failed"),current,budget)
    end try
end function

function TaskSiloSeekFailure(failure as Object, current as Object, budget as Object) as Object
    failure.Delete("plan")
    if budget.issued
        failure["leaseUncertain"] = true:failure["knownLease"] = SpCopy(current)
        if budget.latestReceipt <> invalid then failure["controlReceipt"] = SpCopy(budget.latestReceipt)
    end if
    return failure
end function
