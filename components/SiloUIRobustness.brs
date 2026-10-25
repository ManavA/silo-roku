' Cleanup tickets contain only lease identifiers and immutable credential-free
' ownership. The worker reads credentials only while that registry scope matches.
function SiloUIOwner() as Object
    return {provider:m.provider,sourceId:m.sourceId,profileId:m.profileId,generation:m.generation}
end function

' Signal Task work to stop without dropping the result observer. Its final
' result still needs lease and local artifact cleanup under the captured owner.
sub SiloUICancelPendingPlayback()
    if m.seekReanchor <> invalid and m.view = "player" then PlayerClose(false,false)
    if m.compatPreparation <> invalid then SiloUICompatCancel()
    if m.pending = invalid then return
    for each key in m.pending
        purpose = m.pending[key].purpose
        if purpose = "audio_start" or purpose = "play_start" or purpose = "play_prebuf" or purpose = "play_recover" or purpose = "play_recover_version" or purpose = "seek_reanchor" or purpose = "subtitle_off" or purpose = "subtitle_select" or purpose = "audio_select"
            task = m.pending[key].task
            if task <> invalid then task.cancelled = true
        end if
    end for
end sub

function SiloUICleanupUuid() as String
    return LCase(CreateObject("roDeviceInfo").GetRandomUUID())
end function

function SiloUIAllocationResult(entry as Object, result as Object) as Boolean
    if entry.purpose <> "audio_start" and entry.purpose <> "play_start" and entry.purpose <> "play_prebuf" and entry.purpose <> "play_recover_version" then return false
    knownCleanup = SpBool(SpField(result,"cleanupLeaseKnown")) and SpField(result,"cleanupLeaseKnown") = true
    plan = SpField(result,"plan")
    closedCleanup = SpBool(SpField(result,"cleanupLeaseClosed")) and SpField(result,"cleanupLeaseClosed") = true and plan = invalid
    if knownCleanup or closedCleanup
        scoped = SiloUIAllocationCleanupFactMatches(entry,result)
        knownCleanup = knownCleanup and scoped
        closedCleanup = closedCleanup and scoped
    end if
    knownCleanup = knownCleanup and SpOpaque(SpField(plan,"sessionId")) and SpOpaque(SpField(plan,"installationId")) and SpOpaque(SpField(plan,"stopId"))
    if SpBool(SpField(result,"leaseUncertain")) and SpField(result,"leaseUncertain") = true and not knownCleanup and not closedCleanup
        if m.unresolvedAllocation = invalid
            revision = invalid:requestId = invalid
            if SpNumber(SpField(result,"sessionRevision"),2147483647,true) then revision = result.sessionRevision
            if entry.task <> invalid
                capturedId = SpField(entry.task.job,"requestId")
                if SpNumber(capturedId,2147483647,true) then requestId = capturedId
            end if
            m.unresolvedAllocation = {provider:entry.owner.provider,sourceId:entry.owner.sourceId,profileId:entry.owner.profileId,generation:entry.generation,requestId:requestId,sessionRevision:revision,reason:"allocation_identity_unknown"}
            ' Keep the first barrier's presentation separate from cleanup authority.
            m.unresolvedStartResponse = invalid
            if SiloUIAllocationCleanupFactMatches(entry,result) and SiloUIStartResponsePresentationCurrent(entry)
                facts = PlayerStartResponseFacts(SpField(result,"startResponseFacts"))
                if facts <> invalid then m.unresolvedStartResponse = {requestFacts:SiloStartRequestFacts(SpField(result,"startRequestFacts")),facts:facts,provider:entry.owner.provider,sourceId:entry.owner.sourceId,profileId:entry.owner.profileId,generation:entry.generation,purpose:entry.purpose}
            end if
        end if
        m.speculationDisabled = true
        SiloUICancelPendingPlayback()
        PlayerDiscardPrebuffer()
        m.audioNext = invalid
        m.audioLoading = false
    end if
    cancelled = entry.generation <> m.generation or m.transitionIntent <> invalid or entry.owner.provider <> m.provider or entry.owner.sourceId <> m.sourceId or entry.owner.profileId <> m.profileId
    if entry.purpose = "play_start" or entry.purpose = "play_recover_version" then cancelled = cancelled or entry.extra <> m.playToken
    if entry.purpose = "play_prebuf"
        if m.prebuf = invalid then cancelled = true else cancelled = cancelled or entry.extra <> m.prebuf.token
    end if
    if entry.purpose = "audio_start" then cancelled = cancelled or entry.extra <> m.audioToken or m.view <> "audio"
    owner = entry.owner
    if result.sessionRevision <> invalid then owner["sessionRevision"] = result.sessionRevision
    if type(result.plan) = "roAssociativeArray"
        if cancelled or result.ok <> true or m.unresolvedAllocation <> invalid
            SiloUIQueueCleanup(result.plan, owner)
        else
            result.plan.cleanupOwner = owner
        end if
    end if
    if m.unresolvedAllocation <> invalid
        if not cancelled and entry.purpose <> "play_prebuf"
            m.playLoading = false
            m.audioLoading = false
            SiloUIShowPlaybackAdmissionFailure()
        end if
        return true
    end if
    return cancelled
end function

 ' Same-lease recovery can advance server control without producing playable
' media. Its captured context survives Back until the final result is drained.
function SiloUIRecoveryResult(entry as Object, result as Object) as Boolean
    if entry.purpose <> "play_recover" then return false
    original = entry.recoveryContext
    if type(original) <> "roAssociativeArray" then return false
    owner = entry.owner
    cancelled = entry.generation <> m.generation or m.transitionIntent <> invalid or entry.extra <> m.playToken or m.view <> "player" or m.playPlan = invalid
    receipt = result.controlReceipt
    if result.ok = true and type(result.plan) = "roAssociativeArray" then receipt = result.plan.siloPlayback
    checked = invalid
    if type(receipt) = "roAssociativeArray"
        proof = {provider:"silo",sourceId:original.sourceId,itemId:original.itemId,versionId:original.fileId,sessionId:original.sessionId,installationId:original.installationId,siloPlayback:receipt}
        checked = SiloPlaybackContext(proof,owner)
        if checked <> invalid
            for each field in ["sourceId","profileId","sessionRevision","itemId","fileId","installationId","sessionId","playbackAttemptId","planAttemptId","qualityPreference"]
                if SpField(checked,field) <> SpField(original,field) then checked = invalid:exit for
            end for
        end if
        if checked <> invalid
            if FormatJson(checked.selectedTracks) <> FormatJson(original.selectedTracks) or checked.attemptCount < original.attemptCount then checked = invalid
        end if
    end if
    if cancelled
        live = SiloPlaybackContext(m.playPlan,SiloUIOwner())
        if m.view = "player" and entry.extra <> m.playToken and live <> invalid
            if live.sessionId = original.sessionId and live.sourceId = original.sourceId and live.profileId = original.profileId and live.installationId = original.installationId
                if live.planAttemptKey <> original.planAttemptKey or live.playbackAttemptId <> original.playbackAttemptId or live.attemptCount > original.attemptCount then return true
            end if
        end if
        ' Never stop an unproved returned lease; the request itself owns only
        ' this captured same-session lease, even when returned metadata is bad.
        SiloUIQueueCleanup({sessionId:original.sessionId,installationId:original.installationId},owner)
        return true
    end if
    if result.ok <> true and checked <> invalid
        current = SiloPlaybackContext(m.playPlan,SiloUIOwner())
        if current <> invalid
            if current.sessionId = original.sessionId and current.playbackAttemptId = original.playbackAttemptId and current.planAttemptKey = original.planAttemptKey
                m.playPlan["siloPlayback"] = checked
                m.playPlan["planId"] = checked.planId
                m.playPlan["planAttemptKey"] = checked.planAttemptKey
            end if
        end if
    end if
    return false
end function

sub SiloUIQueueCleanup(plan as Object, owner as Object, finalSample = invalid as Dynamic)
    if type(owner) <> "roAssociativeArray" then m.cleanupUnconfirmed = true : return
    if owner.sessionRevision = invalid then m.cleanupUnconfirmed = true : return
    if owner.generation <> invalid and m.expiredGeneration <> invalid
        if owner.generation <= m.expiredGeneration then m.cleanupUnconfirmed = true : return
    end if
    if m.cleanupTickets = invalid then m.cleanupTickets = {}
    lease = TextOr(plan.sessionId)
    if owner.provider = "plex" then lease = TextOr(plan.transcodeSessionId)
    ' Direct Plex plans have no server allocation to stop.
    if lease = "" then return
    key = owner.provider + ":" + owner.sourceId + ":" + owner.profileId + ":" + lease
    if m.cleanupTickets.DoesExist(key) then return
    params = {sessionId:TextOr(plan.sessionId),installationId:TextOr(plan.installationId),persistProgress:false,stopId:TextOr(plan.stopId)}
    if finalSample <> invalid
        if not SpFields(finalSample,["positionMs","sequence","isPaused"],[]) then m.cleanupUnconfirmed = true:return
        if not SpNumber(finalSample.positionMs,315576000000#,false) or not SpNumber(finalSample.sequence,2147483647,true) or not SpBool(finalSample.isPaused) then m.cleanupUnconfirmed = true:return
        params["persistProgress"] = true
        params["positionMs"] = finalSample.positionMs
        params["sequence"] = finalSample.sequence
        params["isPaused"] = finalSample.isPaused
    end if
    if params.stopId = "" then params["stopId"] = SiloUICleanupUuid()
    if owner.provider = "plex" then params.transcodeSessionId = lease
    ticket = {params:params,owner:owner,busy:false}
    if finalSample <> invalid
        ticket["seekFinal"] = true
        m.seekCleanupUnconfirmed = true
    end if
    m.cleanupTickets[key] = ticket
    SiloUISendCleanup(key)
end sub

sub SiloUISendCleanup(key as String)
    ticket = m.cleanupTickets[key]
    if ticket = invalid or ticket.busy = true then return
    ticket.busy = true
    ApiOwned("playback_stop",ticket.params,"cleanup_stop",key,ticket.owner)
end sub

sub SiloUICleanupResult(result as Object, key as String)
    ticket = m.cleanupTickets[key]
    if ticket = invalid then return
    ticket.busy = false
    if result.ok = true
        m.cleanupTickets.Delete(key)
        if ticket.seekFinal = true
            remainingSeek = false
            for each pendingKey in m.cleanupTickets
                if m.cleanupTickets[pendingKey].seekFinal = true then remainingSeek = true
            end for
            if not remainingSeek then m.seekCleanupUnconfirmed = false
        end if
        if m.cleanupTickets.Count() = 0
            m.cleanupFailed = false
            m.speculationDisabled = m.memoryHigh = true
            if m.unresolvedAllocation <> invalid then m.speculationDisabled = true
        end if
        SiloUIDrainMaybeDone()
    else
        m.obBusy = false
        m.cleanupFailed = true
        m.speculationDisabled = true
        if m.prebufferForeground <> invalid then PlayerDrainPrebufferForeground()
        if m.transitionIntent <> invalid
            ObScreen("SESSION CLEANUP", "Couldn't release the previous session", "Retry before switching, or cancel to keep this source.", "", [{label:"Retry",action:"cleanup_retry"},{label:"Cancel switch",action:"cleanup_cancel"}])
        else
            Toast("Session cleanup pending. Retry in Settings.")
        end if
    end if
end sub

sub SiloUIRetryCleanup()
    m.cleanupFailed = false
    if m.compatPreparation <> invalid then SiloUICompatRetry()
    keys = m.cleanupTickets.Keys()
    for each key in keys
        SiloUISendCleanup(key)
    end for
    SiloUIDrainMaybeDone()
    if m.unresolvedAllocation <> invalid and m.transitionIntent = invalid then SiloUIShowPlaybackAdmissionFailure()
end sub

function SiloUIBeginTransition(choice as Object) as Boolean
    if m.transitionReplaying = true then return false
    if m.transitionIntent <> invalid then return true
    m.obBusy = true
    m.transitionIntent = choice
    if m.audioNode <> invalid then SiloUIAudioRelease()
    m.playLoading = false
    ' ObScreen changes the view. Retire the captured player while its native
    ' content and final source sample are still owned by the player view.
    SiloUICancelPendingPlayback()
    ObScreen("SESSION CLEANUP","Releasing the previous session…","Please wait before switching.","",[])
    m.playToken = m.playToken + 1
    m.speculationDisabled = true
    PlayerDiscardPrebuffer()
    SiloUIDrainMaybeDone()
    return true
end function

sub SiloUIDrainMaybeDone()
    if m.prebufferForeground <> invalid then PlayerDrainPrebufferForeground()
    if m.transitionIntent = invalid then return
    if SiloUIPlaybackAdmissionBlocked() and m.unresolvedAllocation <> invalid
        m.obBusy = false
        ObScreen("SESSION CLEANUP","Playback session identity is unknown","The server returned no usable session identifier; new playback is paused. End the session on your server before restarting the app. Restart alone does not confirm cleanup.","",[{label:"Cancel switch",action:"cleanup_cancel"}])
        return
    end if
    if m.cleanupFailed = true
        m.obBusy = false
        ObScreen("SESSION CLEANUP","Cleanup remains unconfirmed","Retry before switching, or keep this source.","",[{label:"Retry",action:"cleanup_retry"},{label:"Cancel switch",action:"cleanup_cancel"}])
        return
    end if
    if m.seekCleanupUnconfirmed = true then return
    if m.compatPreparation <> invalid then return
    if m.cleanupTickets <> invalid
        if m.cleanupTickets.Count() > 0 then return
    end if
    if m.audioSyncFlight <> invalid or m.audioSyncPending <> invalid then return
    for each key in m.pending
        purpose = m.pending[key].purpose
        if purpose = "audio_start" or purpose = "play_start" or purpose = "play_prebuf" or purpose = "play_recover" or purpose = "play_recover_version" or purpose = "seek_reanchor" or purpose = "subtitle_off" or purpose = "subtitle_select" then return
    end for
    intent = m.transitionIntent
    m.transitionIntent = invalid
    m.obBusy = false
    m.speculationDisabled = m.memoryHigh = true
    m.transitionReplaying = true
    ObChoose(intent)
    m.transitionReplaying = false
end sub

function SiloUIOwnedJob(job as Object, revision as Integer) as Object
    job["sessionRevision"] = revision
    return job
end function

' Capture ownership before expiry discards the player and pending work.
' Credential rejection alone is not evidence that a playback lease exists.
function SiloUIAuthCleanupUncertain() as Boolean
    if m.cleanupUnconfirmed = true or m.cleanupFailed = true then return true
    if SiloUIPlaybackAdmissionBlocked() then return true
    if m.playPlan <> invalid or m.prebuf <> invalid or m.prebufferForeground <> invalid then return true
    if m.audioPlan <> invalid or m.audioNext <> invalid or m.audioSyncFlight <> invalid or m.audioSyncPending <> invalid then return true
    if m.compatPreparation <> invalid or SpScope(m.compatNativeStopFailure) <> invalid then return true
    if m.video.content <> invalid then return true
    if m.pending <> invalid
        for each key in m.pending
            entry = m.pending[key]
            purpose = entry.purpose
            if purpose = "audio_start" or purpose = "play_start" or purpose = "play_prebuf" or purpose = "play_recover" or purpose = "play_recover_version" or purpose = "audio_select" or purpose = "subtitle_off" or purpose = "subtitle_select" then return true
            task = entry.task
            if task <> invalid
                job = task.job
                if type(job) = "roAssociativeArray"
                    if job.action = "playback_stop" then return true
                end if
            end if
        end for
    end if
    return false
end function

' Expired credentials may prevent authenticated cleanup. Fence the old UI,
' retain seek final-stop tickets and their admission fence across reauthentication.
sub SiloUIAuthExpired(entry as Object)
    if entry.generation <> m.generation then return
    owner = entry.owner
    if owner.provider <> m.provider or owner.sourceId <> m.sourceId or owner.profileId <> m.profileId then return
    scope = owner.provider + ":" + owner.sourceId + ":" + owner.profileId
    if m.authExpiredScope = scope then return
    m.cleanupUnconfirmed = SiloUIAuthCleanupUncertain()
    ' Capture a pending seek's final sample before expiring this generation.
    if m.seekReanchor <> invalid then SiloUICancelPendingPlayback()
    if m.authExpiredProviders = invalid then m.authExpiredProviders = {}
    m.authExpiredProviders[owner.provider] = true
    m.authExpiredScope = scope
    m.expiredGeneration = m.generation
    m.transitionIntent = invalid
    seekTickets = {}
    if m.cleanupTickets <> invalid
        for each key in m.cleanupTickets
            ticket = m.cleanupTickets[key]
            if ticket.seekFinal = true then seekTickets[key] = ticket
        end for
    end if
    m.cleanupTickets = seekTickets
    m.cleanupFailed = false
    m.speculationDisabled = true
    m.playLoading = false
    m.playToken = m.playToken + 1
    SiloUICancelPendingPlayback()
    SiloUISubtitleRetireBound()
    m.video.control = "stop"
    m.video.content = invalid
    m.video.visible = false
    m.playPlan = invalid
    m.recoveringNative = false
    m.playWaitClock = invalid
    PlayerResetChrome()
    if m.savedCaptionMode <> invalid then m.video.globalCaptionMode = m.savedCaptionMode
    m.progressTimer.control = "stop"
    m.upNextTimer.control = "stop"
    m.prebuf = invalid
    ObResetScope()
    m.obBusy = false
    m.obMode = ""
    m.pollTimer.control = "stop"
    body = "Sign in to reconnect your library."
    if m.cleanupUnconfirmed = true then body = "Cleanup of the previous server session remains unconfirmed."
    ObScreen("SESSION EXPIRED", "Please sign in again", body, "", [{label:"Sign in",action:"retry"},{label:"Choose source",action:"sources"}])
    m.obPage = "expired"
    m.obLast = owner.provider
end sub

sub SiloUIMemoryPressure()
    m.memoryHigh = m.top.memoryPressure >= 80
    if not m.memoryHigh then return
    TransportTrickplayClear()
    if m.publicArtwork <> invalid then SiloUIArtworkRetire()
    if m.streamingGrid <> invalid then StreamingRetire()
    if m.navigationMode <> invalid then m.navigationReturn = invalid
    DetailPhotosClear()
    PlayerDiscardPrebuffer()
    for each name in ["heroTimer","backdropTimer","backdropFade","searchTimer"]
        if m[name] <> invalid then m[name].control = "stop"
    end for
    m.pendingBackdrop = ""
    m.backdrop.uri = ""
    m.backdropOld.uri = ""
    if m.view <> "home"
        m.homeToken = NumberOr(m.homeToken,0) + 1
        m.homeReload = true
        m.rows.content = invalid
        m.homeRows = []
        m.heroItem = invalid
        m.plexRows = {}
        m.plexRecent = {}
        m.plexSections = []
        m.heroLogo.uri = ""
    end if
    if m.view <> "library"
        m.libraryToken = NumberOr(m.libraryToken,0) + 1
        m.libraryReload = true
        m.grid.content = invalid
    end if
    if m.view <> "search"
        m.searchReload = true
        m.searchToken = NumberOr(m.searchToken,0) + 1
        m.searchGrid.content = invalid
    end if
    if m.view <> "detail"
        m.detailVisit = NumberOr(m.detailVisit,0) + 1
        m.detailToken = m.detailVisit
        if m.detailItem <> invalid then m.detailReloadItem = {itemId:m.detailItem.itemId,type:m.detailItem.type,title:m.detailItem.title}
        m.detailItem = invalid
        m.detailData = invalid
        m.detailEpisodes = []
        m.detailVersions = []
        m.detailSimilarItems = []
        m.detailSeasons = []
        m.detailPlexSeasons = []
        m.detailFocusEpisode = invalid
        for each name in ["episodes","detailSimilar","detailCast"]
            if m[name] <> invalid then m[name].content = invalid
        end for
        if m.detailLogo <> invalid then m.detailLogo.uri = ""
    end if
end sub

' A missing allocation identity cannot be cleared by an unrelated stop receipt.
' Admission follows unresolved allocations and outstanding cleanup tickets.
function SiloUIPlaybackAdmissionBlocked() as Boolean
    if m.seekCleanupUnconfirmed = true then return true
    if m.seekReanchor <> invalid then return true
    if m.pending <> invalid
        for each key in m.pending
            if m.pending[key].purpose = "seek_reanchor" then return true
        end for
    end if
    if m.unresolvedAllocation <> invalid then return true
    if m.cleanupTickets <> invalid then return m.cleanupTickets.Count() > 0
    return false
end function

sub SiloUIShowPlaybackAdmissionFailure()
    code = "cleanup_pending"
    if m.unresolvedAllocation <> invalid then code = "allocation_identity_unknown"
    failure = {errorCode:code}
    snapshot = m.unresolvedStartResponse
    if m.unresolvedAllocation <> invalid and type(snapshot) = "roAssociativeArray"
        if snapshot.provider = m.provider and snapshot.sourceId = m.sourceId and snapshot.profileId = m.profileId and snapshot.generation = m.generation
            failure["startRequestFacts"] = SiloStartRequestFacts(snapshot.requestFacts)
            failure["startResponseFacts"] = PlayerStartResponseFacts(snapshot.facts)
            failure["startResponsePurpose"] = snapshot.purpose
        end if
    end if
    PlayerShowFailure("session",failure)
end sub

' Presentation eligibility is sampled before uncertainty cancellation discards
' a still-current preload. This never grants cleanup or admission authority.
function SiloUIStartResponsePresentationCurrent(entry as Object) as Boolean
    if entry.generation <> m.generation or m.transitionIntent <> invalid then return false
    if entry.owner.provider <> m.provider or entry.owner.sourceId <> m.sourceId or entry.owner.profileId <> m.profileId then return false
    if entry.task <> invalid then if entry.task.cancelled = true then return false
    if entry.purpose = "play_start" or entry.purpose = "play_recover_version" then return entry.extra = m.playToken
    if entry.purpose = "play_prebuf"
        if m.prebuf = invalid then return false
        return entry.extra = m.prebuf.token
    end if
    if entry.purpose = "audio_start" then return entry.extra = m.audioToken and m.view = "audio"
    return false
end function

' These internal Task facts are meaningful only for the captured allocating job;
' current UI scope may already have changed while its result was in flight.
function SiloUIAllocationCleanupFactMatches(entry as Object, result as Object) as Boolean
    if entry.task = invalid then return false
    job = entry.task.job
    if type(job) <> "roAssociativeArray" or job.provider <> "silo" then return false
    for each field in ["provider","action","sourceId","profileId","generation","requestId"]
        if SpField(result,field) <> SpField(job,field) then return false
    end for
    if entry.owner.provider <> job.provider or entry.owner.sourceId <> job.sourceId or entry.owner.profileId <> job.profileId or entry.generation <> job.generation then return false
    if not SpNumber(SpField(result,"sessionRevision"),2147483647,true) then return false
    if entry.owner.sessionRevision <> invalid and entry.owner.sessionRevision <> result.sessionRevision then return false
    return true
end function
