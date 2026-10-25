' Default-off private compatibility holder. Credentials stay in this Task;
' a one-use binding payload is retired before owned media and session cleanup.
sub init()
    m.top.functionName = "runCompat"
end sub

sub runCompat()
    m.compatPort = CreateObject("roMessagePort")
    m.top.observeField("command",m.compatPort)
    m.top.observeField("cancelled",m.compatPort)
    m.compatToken = "":m.compatSecret = "":m.compatMediaRequests = 0
    m.compatPlaySession = "":m.compatBinding = invalid:m.compatChild = invalid
    m.compatReceipt = invalid:m.compatAudioIndex = invalid
    m.compatGeneration = 1:m.compatBindingReleased = false:m.compatStartUncertain = false:m.compatEverReleased = false:m.compatMediaRetired = false:m.compatLogoutAcknowledged = false
    m.compatApprovalSent = false:m.compatCollectAttempted = false:m.compatCollectUncertain = false:m.compatPrepared = false:m.compatCancelledHandled = false
    m.compatCaption = invalid
    m.compatAutoSelection = invalid
    m.compatOwner = invalid:m.compatSession = invalid:m.compatLastCommand = "":m.compatChildId = 0
    while true
        command = m.top.command
        if m.top.cancelled = true and m.compatPrepared and not m.compatCancelledHandled
            m.compatCancelledHandled = true
            closed = CompatClose()
            ' A Scene close queued before this terminal publication is the
            ' same unused close, not a new retry after a failed logout.
            queued = m.top.command
            if SiloObject(queued)
                if queued.action = "close" and CompatCommandMatches(queued)
                    if m.compatBindingReleased and closed.ok <> true then closed = CompatClose(queued)
                    command = queued:m.compatLastCommand = queued.commandId
                end if
            end if
            closed["cancelled"] = true
            CompatPublish(command,closed)
            if closed.ok then return
        end if
        if SiloObject(command) and command.commandId <> m.compatLastCommand
            m.compatLastCommand = command.commandId
            if m.compatOwner = invalid
                m.compatOwner = command.owner:m.compatHolder = command.holderId:m.compatAttempt = command.attemptId
            end if
            if not CompatCommandMatches(command)
                CompatPublish(command,{ok:false,phase:"refused",errorCode:"invalid_command",cleanupUnconfirmed:m.compatToken<>"" or m.compatCollectUncertain or m.compatChild<>invalid})
            else if command.action = "prepare" and not m.compatPrepared and m.compatSession = invalid
                try
                    outcome = CompatPrepare(command.params)
                catch exception
                    outcome = {ok:false,errorCode:"preparation_failed"}
                end try
                if outcome.ok = true and m.top.cancelled <> true
                    m.compatPrepared = true
                    CompatPublish(command,{ok:true,phase:"prepared",class:SiloCompatClassForKind(SpField(m.compatProof,"eligibilityKind")),fileMatched:true,audioMatched:true,mediaNeverRequested:true,planGeneration:1})
                else
                    if m.compatApprovalSent and not m.compatCollectAttempted and m.compatSecret <> "" then CompatCollect(true)
                    closed = CompatClose()
                    if m.top.cancelled = true and closed.ok
                        closed["cancelled"] = true
                        CompatPublish(command,closed)
                    else
                        closed["ok"] = false:closed["phase"] = "refused":closed["errorCode"] = SiloText(outcome.errorCode)
                        CompatPublish(command,closed)
                    end if
                    if closed.cleanupUnconfirmed <> true then return
                end if
            else if command.action = "prepare_stock_context" and m.compatPrepared and not m.compatBindingReleased
                outcome = CompatPrepareStockContext(command)
                CompatPublish(command,outcome)
            else if command.action = "bind" and m.compatPrepared and not m.compatBindingReleased
                if command.planGeneration <> m.compatGeneration or not SpOpaque(command.bindingNonce) or not CompatOwnerCurrent() or m.top.cancelled = true or not CompatEligibilityCurrent(command) or SpField(m.compatProof,"requestedStartPositionMs",0) > 0
                    CompatPublish(command,{ok:false,phase:"binding_refused",errorCode:"binding_changed"})
                else
                    fresh = SiloCompatSnapshotForKind(CreateObject("roDeviceInfo"),m.compatProof.audio,SpField(m.compatProof,"eligibilityKind"),m.compatProof.video)
                    if FormatJson(fresh) <> FormatJson(m.compatProof.snapshot)
                        CompatPublish(command,{ok:false,phase:"binding_refused",errorCode:"output_changed"})
                    else
                        ' Releasing a URL authorizes a potentially delayed native request.
                        ' Publish authority BEFORE the payload; unused-close no longer applies.
                        m.compatBindingReleased = true:m.compatStartUncertain = true:m.compatEverReleased = true:m.compatMediaRetired = false
                        privateBinding = {transport:"silo_compat",bindingNonce:command.bindingNonce,holderId:m.compatHolder,attemptId:m.compatAttempt,planGeneration:m.compatGeneration,owner:m.compatOwner,url:m.compatBinding.url,headers:{Authorization:"Bearer "+m.compatToken},streamFormat:"hls",startPositionMs:m.compatProof.startTicks/10000#,timelineOffsetMs:0}
                        if SpField(m.compatProof,"captionMode") = "on" then privateBinding["compatCaption"] = SpCopy(m.compatCaption)
                        m.top.privateBinding = privateBinding
                        CompatPublish(command,{ok:true,phase:"binding",bindingNonce:command.bindingNonce,planGeneration:m.compatGeneration})
                    end if
                end if
            else if command.action = "close"
                closed = CompatClose(command)
                CompatPublish(command,closed)
                if closed.ok then return
            else if command.action = "playing" and m.compatBindingReleased and command.planGeneration = m.compatGeneration
                outcome = CompatReport("playing",command)
                outcome["compatFailurePhase"] = "playing_ack"
                if outcome.ok
                    listed = CompatSessions(false)
                    if listed.ok and SiloContains(listed.data.sessionIds,m.compatPlaySession)
                        m.compatActiveObserved = true:m.compatStartUncertain = false
                        outcome["activeConfirmed"] = true
                    else
                        outcome = listed
                        if outcome.ok then outcome = {ok:false,errorCode:"active_unconfirmed"}
                        outcome["compatFailurePhase"] = "active_session"
                    end if
                end if
                outcome["phase"] = "playing":outcome["planGeneration"] = m.compatGeneration
                CompatPublish(command,outcome)
            else if command.action = "progress" and m.compatBindingReleased and command.planGeneration = m.compatGeneration
                outcome = CompatReport("progress",command)
                outcome["phase"] = "progress":outcome["planGeneration"] = m.compatGeneration
                CompatPublish(command,outcome)
            else if command.action = "seek" and m.compatBindingReleased and command.planGeneration = m.compatGeneration
                outcome = CompatReanchor(command)
                if outcome.ok
                    outcome["phase"] = "prepared":outcome["class"] = SiloCompatClassForKind(SpField(m.compatProof,"eligibilityKind"))
                    outcome["fileMatched"] = true:outcome["audioMatched"] = true
                    outcome["mediaNeverRequested"] = false:outcome["planGeneration"] = m.compatGeneration
                else
                    outcome["phase"] = "seek_refused"
                end if
                CompatPublish(command,outcome)
            else
                CompatPublish(command,{ok:false,phase:"refused",errorCode:"unsupported_command",cleanupUnconfirmed:m.compatToken<>"" or m.compatCollectUncertain or m.compatChild<>invalid})
            end if
        end if
        wait(250,m.compatPort)
    end while
end sub

function CompatCommandMatches(command as Object) as Boolean
    if not SpOpaque(command.commandId) or not SpOpaque(command.holderId) or not SpOpaque(command.attemptId) then return false
    if command.holderId <> m.compatHolder or command.attemptId <> m.compatAttempt then return false
    if not SoScopeEqual(command.owner,m.compatOwner) then return false
    return SpField(command.owner,"sessionRevision") = SpField(m.compatOwner,"sessionRevision")
end function

function CompatStockTransportQualified(baseUrl as Dynamic) as Boolean
    return SiloNativeBearerTransportQualified(baseUrl,CreateObject("roDeviceInfo"))
end function

' Derive authority only from this authenticated holder's canonical preparation.
function CompatStockQualification() as Dynamic
    if m.compatGeneration <> 1 or m.top.cancelled = true or not CompatOwnerCurrent() then return invalid
    if not SiloCompatP7Proof(m.compatProof) or not SpNumber(SpField(m.compatProof,"startTicks"),0,true) or m.compatProof.startTicks <> 0 then return invalid
    bookmark = SpField(m.compatProof,"requestedStartPositionMs",0)
    if not SpNumber(bookmark,2147483646,true) or bookmark >= m.compatProof.sourceDurationMs then return invalid
    if m.compatReceipt = invalid or m.compatBinding = invalid or m.compatAudioIndex = invalid then return invalid
    fresh = SiloCompatSnapshotForKind(CreateObject("roDeviceInfo"),m.compatProof.audio,SpField(m.compatProof,"eligibilityKind"),m.compatProof.video)
    if FormatJson(fresh) <> FormatJson(m.compatProof.snapshot) then return invalid
    owner = SpCopy(m.compatOwner)
    owner["holderId"] = m.compatHolder:owner["attemptId"] = m.compatAttempt:owner["planGeneration"] = m.compatGeneration
    binding = SpField(m.compatProof,"ownerBinding")
    if not SpFields(binding,["provider","sourceId","profileId","generation","sessionRevision"],[]) then return invalid
    for each name in ["provider","sourceId","profileId","generation","sessionRevision"]
        if binding[name] <> owner[name] then return invalid
    end for
    baseUrl = m.compatSession.compatConnectInfo.publicUrl
    base = SiloUrlParts(baseUrl)
    if base.ok <> true or base.path <> "" or base.authority <> baseUrl then return invalid
    if not CompatStockTransportQualified(baseUrl) then return invalid
    if not SiloCompatPattern(m.compatToken,"^[A-Za-z0-9._~-]+$",4096) then return invalid
    ' Validate the canonical owned receipt before any network side effect.
    receipt = SiloCompatPlaybackReceipt(m.compatReceipt,m.compatProof,baseUrl,m.compatAudioIndex)
    if receipt = invalid or receipt.url <> m.compatBinding.url or receipt.class <> "copied_p7_hdr10_fmp4" then return invalid
    expected = baseUrl+"/Videos/"+m.compatProof.mediaSourceId+"/remux-dv-v1/master.m3u8?PlaySessionId="+receipt.playSessionId+"&MediaSourceId="+m.compatProof.mediaSourceId
    if receipt.url <> expected then return invalid
    return {schemaVersion:1,kind:"stock-p7-ac3-root-v1",approved:true,sourceId:owner.sourceId,profileId:owner.profileId,generation:owner.generation,sessionRevision:owner.sessionRevision,holderId:owner.holderId,attemptId:owner.attemptId,planGeneration:owner.planGeneration,origin:baseUrl,transportPolicy:"native-bearer-origin-scope-v1",transportEvidence:"c208x-16.0.4-842-redirect-chains-v1",rootListenerRequired:true,fileId:m.compatProof.fileId,mediaSourceId:m.compatProof.mediaSourceId,audioOrdinal:m.compatProof.audioOrdinal,audioStreamIndex:m.compatAudioIndex,requestedStartPositionMs:SpField(m.compatProof,"requestedStartPositionMs",0)}
end function

' Revalidate holder authority before the first master request can start a worker.
function CompatPrepareStockContext(command as Object) as Object
    refused = {ok:false,phase:"stock_context_refused",errorCode:"stock_context_unavailable"}
    if command.planGeneration <> m.compatGeneration then return refused
    qualification = CompatStockQualification()
    if qualification = invalid or FormatJson(qualification) <> FormatJson(SpField(command,"qualification")) then return refused
    owner = SpCopy(m.compatOwner)
    owner["holderId"] = m.compatHolder:owner["attemptId"] = m.compatAttempt:owner["planGeneration"] = m.compatGeneration
    baseUrl = m.compatSession.compatConnectInfo.publicUrl
    receipt = SiloCompatPlaybackReceipt(m.compatReceipt,m.compatProof,baseUrl,m.compatAudioIndex)
    m.compatBindingReleased = true:m.compatEverReleased = true:m.compatStartUncertain = true:m.compatMediaRetired = false
    refused["mediaNeverRequested"] = false:refused["cleanupUnconfirmed"] = true
    request = {ok:true,method:"GET",url:receipt.url,headers:{Accept:"application/vnd.apple.mpegurl",Authorization:"Bearer "+m.compatToken},responseBodyLimit:65536,requireVerifiedTls:qualification.transportPolicy="native-bearer-origin-scope-v1"}
    try
        response = HttpRequest(request,9000)
    catch exception
        return refused
    end try
    if response.ok <> true or SpField(response,"statusCode") <> 200 or m.top.cancelled = true or not CompatOwnerCurrent() then return refused
    if FormatJson(CompatStockQualification()) <> FormatJson(qualification) then return refused
    child = SiloCompatStockMasterChild(SpField(response,"body"),receipt.url)
    if child = invalid then return refused
    handoff = SiloCompatStockContext(m.compatReceipt,m.compatProof,baseUrl,child,m.compatAudioIndex,m.compatToken,owner,qualification)
    if handoff = invalid or m.top.cancelled = true or not CompatOwnerCurrent() then return refused
    m.top.privateStockContext = handoff
    return {ok:true,phase:"stock_context_prepared",planGeneration:m.compatGeneration,mediaNeverRequested:false}
end function

function CompatReport(action as String, command as Object) as Object
    params = {playSessionId:m.compatPlaySession,mediaSourceId:m.compatProof.mediaSourceId,audioStreamIndex:m.compatBinding.audioStreamIndex,positionMs:command.positionMs,isPaused:command.isPaused}
    cleanup = action = "stopped"
    response = CompatFetch(action,params,cleanup)
    if not cleanup and (response.scopeChanged = true or m.top.cancelled = true) then return {ok:false,errorCode:"session_changed"}
    return CompatReportResponse(action,response)
end function

function CompatSessions(cleanup = true as Boolean) as Object
    response = CompatFetch("sessions",{},cleanup)
    if not cleanup and (response.scopeChanged = true or m.top.cancelled = true) then return {ok:false,errorCode:"session_changed"}
    return CompatReportResponse("sessions",response)
end function

function CompatReportResponse(action as String, response as Object) as Object
    status = SpField(response,"statusCode",0)
    code = SpField(response,"errorCode")
    if response.ok = false and (status <= 0 or (status >= 200 and status < 300)) and SiloContains(["network_timeout","network_error","network_unavailable","tls_setup_failed","transport_failed","response_too_large","session_changed","cancelled","cleanup_deadline"],code)
        outcome = {ok:false,errorCode:code}
    else
        outcome = DecodeSiloCompatResponse(action,SiloText(response.body),{statusCode:status})
    end if
    if SpNumber(status,599,true) and status >= 100 then outcome["compatHttpStatus"] = status
    return outcome
end function

sub CompatPublish(command as Object, outcome as Object)
    result = {commandId:command.commandId,holderId:m.compatHolder,attemptId:m.compatAttempt,owner:m.compatOwner}
    for each key in outcome
        result[key] = outcome[key]
    end for
    if outcome.phase = "prepared" and outcome.ok = true
        qualification = CompatStockQualification()
        if qualification <> invalid then result["stockQualification"] = qualification
    end if
    m.top.result = result
end sub

function CompatOwnerCurrent() as Boolean
    if SpScope(m.compatOwner) = invalid then return false
    if SessionRevision("silo") <> SpField(m.compatOwner,"sessionRevision") then return false
    current = LoadSession("silo")
    if current.sourceId <> m.compatOwner.sourceId or current.profileId <> m.compatOwner.profileId then return false
    if m.compatSession <> invalid
        for each key in ["sourceId","baseUrl","profileId","profileToken"]
            if SiloText(current[key]) <> SiloText(m.compatSession[key]) then return false
        end for
    end if
    return true
end function

' The child owns native credentials and068's approval/refresh/PIN fence.
' Cancellation never kills an approval child; its terminal result is consumed.
function CompatNative(action as String, params as Object) as Object
    if not CompatOwnerCurrent() then return {ok:false,errorCode:"session_changed"}
    child = CreateObject("roSGNode","ApiTask")
    if child = invalid then return {ok:false,errorCode:"native_unavailable"}
    m.compatChild = child:m.compatChildId++
    child.observeField("result",m.compatPort)
    job = {provider:"silo",action:action,sourceId:m.compatOwner.sourceId,profileId:m.compatOwner.profileId,generation:m.compatOwner.generation,sessionRevision:m.compatOwner.sessionRevision,requestId:m.compatChildId,params:params}
    child.job = job:child.cancelled = false
    child.control = "RUN"
    while child.result = invalid
        wait(250,m.compatPort)
    end while
    result = child.result
    m.compatChild = invalid
    for each key in ["provider","action","sourceId","profileId","generation","requestId","sessionRevision"]
        if result[key] <> job[key] then return {ok:false,errorCode:"native_identity"}
    end for
    if not CompatOwnerCurrent() then return {ok:false,errorCode:"session_changed"}
    return result
end function

function CompatFetch(action as String, params as Object, cleanup = false as Boolean) as Object
    if not cleanup
        if m.top.cancelled = true then return {ok:false,errorCode:"cancelled"}
        if not CompatOwnerCurrent() then return {ok:false,errorCode:"session_changed"}
    end if
    request = BuildSiloCompatRequest(action,m.compatSession,params)
    if request.ok <> true then return request
    timeoutMs = 9000
    if cleanup and m.compatCloseClock <> invalid
        remaining = 60000-m.compatCloseClock.TotalMilliseconds()
        if remaining <= 0 or m.compatCloseRequests >= 8 then return {ok:false,errorCode:"cleanup_deadline"}
        m.compatCloseRequests++
        if remaining < timeoutMs then timeoutMs = Int(remaining)
    end if
    try
        response = HttpRequest(request,timeoutMs)
    catch exception
        return {ok:false,errorCode:"transport_failed"}
    end try
    if not cleanup and not CompatOwnerCurrent() then response["scopeChanged"] = true
    return response
end function



 ' Presence is separate from value: a serialized null marker is not legacy.
function CompatHasField(raw as Dynamic, name as String) as Boolean
    if not SiloObject(raw) then return false
    for each key in raw
        if LCase(key) = LCase(name) then return true
    end for
    return false
end function

 ' Retained proof, initial params and each mutation command must agree. A
' missing modern marker never downgrades this holder to the legacy branch.
function CompatAutoCommandCurrent(command as Object) as Boolean
    if not CompatAutoModeValid(m.compatParams) or not CompatAutoModeValid(command) then return false
    if CompatFieldCount(m.compatParams,"manualVersionSelection") <> CompatFieldCount(command,"manualVersionSelection") then return false
    if CompatFieldCount(m.compatParams,"manualVersionSelection") = 1
        if not SiloCompatManualVersionValid(command,m.compatParams.fileId) then return false
        if FormatJson(m.compatParams.manualVersionSelection) <> FormatJson(command.manualVersionSelection) then return false
    end if
    if m.compatAutoSelection = invalid
        return CompatFieldCount(m.compatParams,"autoAudioSelection") = 0 and CompatFieldCount(command,"autoAudioSelection") = 0
    end if
    if CompatFieldCount(m.compatParams,"autoAudioSelection") <> 1 or CompatFieldCount(command,"autoAudioSelection") <> 1 then return false
    return FormatJson(SpField(m.compatParams,"autoAudioSelection")) = FormatJson(m.compatAutoSelection) and FormatJson(SpField(command,"autoAudioSelection")) = FormatJson(m.compatAutoSelection)
end function

function CompatEligibilityCurrent(command as Object) as Boolean
    if not CompatAutoCommandCurrent(command) then return false
    kind = SpField(m.compatProof,"eligibilityKind")
    if kind = invalid
        return not CompatHasField(m.compatParams,"eligibilityKind") and not CompatHasField(command,"eligibilityKind") and not CompatHasField(m.compatProof.snapshot,"videoQuery")
    end if
    if not SpText(kind,64) then return false
    if SiloCompatClassForKind(kind) = invalid then return false
    if SpField(m.compatParams,"eligibilityKind") <> kind or SpField(command,"eligibilityKind") <> kind then return false
    if kind = "experimental_query_p7_hdr10_aac_fmp4_v1" then return CompatAACQualificationCurrent(command)
    return true
end function

function CompatAACQualificationCurrent(command as Object) as Boolean
    if SiloCompatClassForKind(SpField(m.compatProof,"eligibilityKind")) <> "converted_p7_hdr10_aac_fmp4" then return false
    if not SiloCompatP7AACProof(m.compatProof) then return false
    binding = SpField(m.compatProof,"ownerBinding")
    if not SpFields(binding,["provider","sourceId","profileId","generation","sessionRevision"],[]) then return false
    if binding.provider <> "silo" or binding.sourceId <> m.compatOwner.sourceId or binding.profileId <> m.compatOwner.profileId then return false
    if not SpNumber(binding.generation,2147483646,true) or binding.generation <> m.compatOwner.generation then return false
    if not SpNumber(binding.sessionRevision,2147483646,true) or binding.sessionRevision <> m.compatOwner.sessionRevision then return false
    proofQualification = SiloCompatP7AACQualification(m.compatOwner,SpField(m.compatProof,"instanceQualification"))
    savedQualification = SiloCompatP7AACQualification(m.compatOwner,SpField(m.compatParams,"instanceQualification"))
    commandQualification = SiloCompatP7AACQualification(m.compatOwner,SpField(command,"instanceQualification"))
    if proofQualification = invalid or savedQualification = invalid or commandQualification = invalid then return false
    if FormatJson(proofQualification) <> FormatJson(savedQualification) then return false
    return FormatJson(proofQualification) = FormatJson(commandQualification)
end function

function CompatFieldCount(raw as Dynamic, name as String) as Integer
    if not SiloObject(raw) then return 0
    count = 0
    for each key in raw
        if LCase(key) = LCase(name) then count++
    end for
    return count
end function

function CompatAutoModeValid(raw as Object) as Boolean
    modes = CompatFieldCount(raw,"autoVersion"):choices = CompatFieldCount(raw,"autoAudioSelection")
    kind = SpField(raw,"eligibilityKind")
    if CompatFieldCount(raw,"eligibilityKind") > 0
        if not SpText(kind,64) then return false
    end if
    if kind = "experimental_query_p8_hdr10_ac3_fmp4_v1"
        return modes = 1 and choices = 0 and SpBool(SpField(raw,"autoVersion")) and SpField(raw,"autoVersion") = false
    end if
    manuals = CompatFieldCount(raw,"manualVersionSelection")
    if manuals > 0
        if manuals <> 1 or modes <> 1 or choices <> 0 then return false
        marker = SpField(raw,"manualVersionSelection")
        return SiloCompatManualVersionValid(raw,SpField(marker,"requestedFileId"))
    end if
    if modes = 0 and choices = 0 then return true
    if modes <> 1 or choices <> 1 then return false
    if not SpBool(SpField(raw,"autoVersion")) or SpField(raw,"autoVersion") <> true then return false
    if not SpText(kind,64) then return false
    if kind <> "experimental_query_p7_hdr10_fmp4_v1" and kind <> "experimental_query_p7_hdr10_aac_fmp4_v1" then return false
    choice = SpField(raw,"autoAudioSelection")
    if not SiloObject(choice) then return false
    mode = SpField(choice,"mode")
    if not SpText(mode,8) then return false
    return mode = "auto"
end function

function CompatAutoQuery(device as Object, query as Object) as Dynamic
    try
        return SiloCompatDecodeEvidence(device.CanDecodeAudio(query))
    catch autoQueryError
        return invalid
    end try
end function

' Recompute only at allocation boundaries. The immutable source basis includes
' preference, every title/default/role and the schema-unpublished HI evidence.
function CompatAutoSelectionCurrent(params as Object, file as Object, device as Object) as Boolean
    if not CompatAutoModeValid(params) then return false
    if CompatFieldCount(params,"autoAudioSelection") = 0 then return m.compatAutoSelection = invalid
    selection = SpField(params,"autoAudioSelection")
    if m.compatAutoSelection <> invalid
        if FormatJson(selection) <> FormatJson(m.compatAutoSelection) then return false
    end if
    facts = SpField(file.version,"autoAudioFacts")
    if FormatJson(facts) <> FormatJson(SpField(selection,"basis")) then return false
    expected = SiloAutoAudioChoose(facts,SpField(selection,"queries"))
    if SpField(params,"eligibilityKind") = "experimental_query_p7_hdr10_aac_fmp4_v1"
        expected = SiloAutoAudioAACConversion(facts,SpField(selection,"queries"))
    end if
    if expected = invalid then return false
    if FormatJson(expected) <> FormatJson(selection) then return false
    if SpField(params,"audioTrackId") <> expected.audio_track_id then return false
    if not SpNumber(SpField(params,"audioTrackIndex"),31,true) then return false
    if params.audioTrackIndex <> expected.audio_track_index or file.versionId <> expected.file_id then return false
    queries = []
    for each track in facts.tracks
        decoded = CompatAutoQuery(device,{codec:track.codec,chcnt:track.channels,container:"mp4",passthru:0})
        passed = CompatAutoQuery(device,{codec:track.codec,chcnt:track.channels,container:"mp4",passthru:1})
        queries.Push({source_ordinal:track.source_ordinal,codec:track.codec,channels:track.channels,container:"mp4",decode:decoded,passthrough:passed})
    end for
    fresh = SiloAutoAudioChoose(facts,queries)
    if SpField(params,"eligibilityKind") = "experimental_query_p7_hdr10_aac_fmp4_v1"
        fresh = SiloAutoAudioAACConversion(facts,queries)
    end if
    return fresh <> invalid and FormatJson(fresh) = FormatJson(selection)
end function

function CompatPrepare(params as Object) as Object
    if not CompatAutoModeValid(params) then return {ok:false,errorCode:"unsupported_source"}
    if not CompatOwnerCurrent() then return {ok:false,errorCode:"session_changed"}
    m.compatSession = LoadSession("silo")
    device = CreateObject("roDeviceInfo")
    m.compatSession["model"] = device.GetModel()
    m.compatSession["deviceId"] = device.GetChannelClientId()
    m.compatSession["appVersion"] = RuntimeAppVersion()
    detail = CompatNative("detail",{itemId:params.itemId})
    if detail.ok <> true then return detail
    file = SiloPlaybackFile(detail.data,m.compatOwner.sourceId,params.itemId,params.fileId,SpField(params,"startPositionMs",0))
    if file = invalid then return {ok:false,errorCode:"source_changed"}
    tracks = file.version.audioTracks
    ordinal = SpField(params,"audioTrackIndex")
    if ordinal = invalid
        for index = 0 to tracks.Count()-1
            if tracks[index].isDefault = true
                if ordinal <> invalid then return {ok:false,errorCode:"audio_ambiguous"}
                ordinal = index
            end if
        end for
    end if
    if not SpNumber(ordinal,tracks.Count()-1,true) then return {ok:false,errorCode:"audio_required"}
    kind = SpField(params,"eligibilityKind")
    if CompatHasField(params,"eligibilityKind")
        if not SpText(kind,64) then return {ok:false,errorCode:"unsupported_source"}
        if SiloCompatClassForKind(kind) = invalid then return {ok:false,errorCode:"unsupported_source"}
    end if
    video = invalid:videos = SpField(file.version,"videoTracks")
    if SiloArray(videos) then if videos.Count() = 1 then video = videos[0]
    proof = SiloCompatCandidate(detail.data,m.compatOwner,params,SiloCompatSnapshotForKind(CreateObject("roDeviceInfo"),tracks[ordinal],kind,video),kind,SpField(params,"instanceQualification"))
    if proof = invalid then return {ok:false,errorCode:"unsupported_source"}
    if not CompatAutoSelectionCurrent(params,file,device) then return {ok:false,errorCode:"source_changed"}
    m.compatAutoSelection = SpCopy(SpField(params,"autoAudioSelection"))
    m.compatProof = proof
    discovery = CompatNative("compat_connect_info",{})
    if discovery.ok <> true then return discovery
    m.compatSession["compatConnectInfo"] = discovery.data
    ' Only this device/origin-qualified lane may prepare title zero for a bookmark.
    proof = SiloCompatStockPreparation(proof,CompatStockTransportQualified(discovery.data.publicUrl),SpField(params,"startPositionMs",0))
    m.compatProof = proof
    system = CompatFetch("system_info",{})
    if system.ok <> true then return system
    identity = ParseJson(system.body)
    if not SiloObject(identity) then return {ok:false,errorCode:"unsupported_listener"}
    if not SiloCompatPattern(identity.Id,"^[!-~]+$",256) or identity.ProductName <> "Jellyfin Server" or identity.StartupWizardCompleted <> true then return {ok:false,errorCode:"unsupported_listener"}
    m.compatServerId = identity.Id
    initiated = CompatFetch("initiate",{})
    if initiated.ok <> true then return initiated
    start = DecodeSiloCompatResponse("initiate",initiated.body,{statusCode:initiated.statusCode})
    if start.ok <> true then return start
    m.compatSecret = start.privateAuth.secret
    if m.top.cancelled = true then return {ok:false,errorCode:"cancelled"}
    m.compatApprovalSent = true
    approval = CompatNative("compat_handoff_approve",{code:start.privateAuth.code})
    if approval.ok <> true then return approval
    collected = CompatCollect(m.top.cancelled=true)
    if collected.ok <> true then return collected
    if m.top.cancelled = true or not CompatOwnerCurrent() then return {ok:false,errorCode:"cancelled"}
    metadataResponse = CompatFetch("item_metadata",{mediaSourceId:proof.mediaSourceId})
    if metadataResponse.ok <> true then return metadataResponse
    metadata = SiloCompatSourceMetadata(ParseJson(metadataResponse.body),proof)
    if metadata = invalid then return {ok:false,errorCode:"source_mismatch"}
    captionSelection = invalid
    if SpField(proof,"captionMode") = "on"
        captionSelection = CompatSubtitleSelection(metadata,proof)
        if captionSelection = invalid then return {ok:false,errorCode:"subtitle_selection_unsupported"}
    end if
    playbackParams = CompatPlaybackRequestParams(proof,metadata)
    if playbackParams = invalid then return {ok:false,errorCode:"source_changed"}
    response = CompatFetch("playback_info",playbackParams)
    if response.ok <> true then return response
    decoded = ParseJson(response.body)
    ' Retain allocated negotiation identity before every remaining receipt check.
    if SiloObject(decoded) and SiloCompatPattern(decoded.PlaySessionId,"^[A-Za-z0-9_-]+$",128) then m.compatPlaySession = decoded.PlaySessionId
    receipt = SiloCompatPlaybackReceipt(decoded,proof,m.compatSession.compatConnectInfo.publicUrl,metadata.audioStreamIndex)
    if receipt = invalid then return {ok:false,errorCode:"unsafe_recipe"}
    if m.top.cancelled = true or not CompatOwnerCurrent() then return {ok:false,errorCode:"cancelled"}
    if captionSelection <> invalid
        caption = CompatSubtitlePrepare(captionSelection,proof)
        if caption.ok <> true
            if caption.errorCode = "cancelled" then return caption
            return {ok:false,errorCode:"subtitle_fetch_failed"}
        end if
        m.compatCaption = caption.caption
    end if
    m.compatBinding = receipt
    m.compatReceipt = decoded:m.compatAudioIndex = metadata.audioStreamIndex
    m.compatParams = SpCopy(params)
    return {ok:true}
end function

function CompatPlaybackRequestParams(proof as Object, metadata as Object) as Dynamic
    params = {mediaSourceId:proof.mediaSourceId,audioStreamIndex:metadata.audioStreamIndex,startTicks:proof.startTicks,deviceProfile:SiloCompatDeviceProfile(proof)}
    if SpField(proof,"eligibilityKind") = "experimental_query_p7_hdr10_aac_fmp4_v1"
        if SiloCompatClassForKind(SpField(proof,"eligibilityKind")) <> "converted_p7_hdr10_aac_fmp4" or not SiloCompatP7AACProof(proof) then return invalid
        target = SpField(proof,"targetAudio")
        if not SpFields(target,["codec","channels"],[]) or target.codec <> "aac" or not SpNumber(target.channels,2,true) or target.channels <> 2 then return invalid
        params["eligibilityKind"] = "experimental_query_p7_hdr10_aac_fmp4_v1"
        params["maxAudioChannels"] = target.channels
    end if
    return params
end function

function CompatReanchor(command as Object) as Object
    m.top.privateStockContext = invalid
    if not SpNumber(command.targetPositionMs,2147483646,true) or not SpBool(command.startPaused) then return {ok:false,errorCode:"invalid_seek"}
    if not CompatOwnerCurrent() or m.top.cancelled = true then return {ok:false,errorCode:"session_changed"}
    if not CompatEligibilityCurrent(command) then return {ok:false,errorCode:"source_changed"}
    m.compatCloseClock = CreateObject("roTimespan"):m.compatCloseRequests = 0
    if not CompatRetireMedia(command) then return {ok:false,errorCode:"cleanup_unconfirmed"}
    m.compatBindingReleased = false:m.compatBinding = invalid:m.compatReceipt = invalid:m.compatAudioIndex = invalid:m.top.privateStockContext = invalid
    params = SpCopy(m.compatParams):params.startPositionMs = command.targetPositionMs
    detail = CompatNative("detail",{itemId:params.itemId})
    if detail.ok <> true then return detail
    file = SiloPlaybackFile(detail.data,m.compatOwner.sourceId,params.itemId,params.fileId,params.startPositionMs)
    if file = invalid then return {ok:false,errorCode:"source_changed"}
    if not CompatAutoSelectionCurrent(params,file,CreateObject("roDeviceInfo")) then return {ok:false,errorCode:"source_changed"}
    ordinal = m.compatProof.audioOrdinal
    if not SpNumber(ordinal,file.version.audioTracks.Count()-1,true) then return {ok:false,errorCode:"audio_changed"}
    kind = SpField(m.compatProof,"eligibilityKind")
    video = invalid:videos = SpField(file.version,"videoTracks")
    if SiloArray(videos) then if videos.Count() = 1 then video = videos[0]
    proof = SiloCompatCandidate(detail.data,m.compatOwner,params,SiloCompatSnapshotForKind(CreateObject("roDeviceInfo"),file.version.audioTracks[ordinal],kind,video),kind,SpField(params,"instanceQualification"))
    if proof = invalid then return {ok:false,errorCode:"source_changed"}
    if proof.mediaSourceId <> m.compatProof.mediaSourceId or FormatJson(proof.audio) <> FormatJson(m.compatProof.audio) then return {ok:false,errorCode:"source_changed"}
    if kind <> invalid
        if SpField(proof,"eligibilityKind") <> kind or FormatJson(proof.video) <> FormatJson(m.compatProof.video) or FormatJson(proof.snapshot) <> FormatJson(m.compatProof.snapshot) then return {ok:false,errorCode:"source_changed"}
    end if
    if kind = "experimental_query_p7_hdr10_fmp4_v1" or kind = "experimental_query_p8_hdr10_fmp4_v1" or kind = "experimental_query_p8_hdr10_ac3_fmp4_v1"
        for each key in ["audioInventory","subtitleInventory","sourceBitrateKbps","sourceDurationMs"]
            if FormatJson(SpField(proof,key)) <> FormatJson(SpField(m.compatProof,key)) then return {ok:false,errorCode:"source_changed"}
        end for
    else if kind = "experimental_query_p7_hdr10_aac_fmp4_v1"
        for each key in ["audioInventory","subtitleInventory","sourceBitrateKbps","sourceDurationMs","targetAudio","instanceQualification","ownerBinding"]
            if FormatJson(SpField(proof,key)) <> FormatJson(SpField(m.compatProof,key)) then return {ok:false,errorCode:"source_changed"}
        end for
    end if
    metadataResponse = CompatFetch("item_metadata",{mediaSourceId:proof.mediaSourceId})
    if metadataResponse.ok <> true then return metadataResponse
    metadata = SiloCompatSourceMetadata(ParseJson(metadataResponse.body),proof)
    if metadata = invalid then return {ok:false,errorCode:"source_changed"}
    if SpField(proof,"captionMode") = "on"
        if FormatJson(proof.subtitleInventory) <> FormatJson(m.compatProof.subtitleInventory) then return {ok:false,errorCode:"subtitle_changed"}
        selection = CompatSubtitleSelection(metadata,proof)
        if selection = invalid then return {ok:false,errorCode:"subtitle_changed"}
        if selection.disposition = "unavailable"
            if SpField(m.compatCaption,"disposition") <> "unavailable" then return {ok:false,errorCode:"subtitle_changed"}
        else
            if FormatJson(selection.track) <> FormatJson(SpField(m.compatCaption,"track")) then return {ok:false,errorCode:"subtitle_changed"}
        end if
    end if
    playbackParams = CompatPlaybackRequestParams(proof,metadata)
    if playbackParams = invalid then return {ok:false,errorCode:"source_changed"}
    response = CompatFetch("playback_info",playbackParams)
    if response.ok <> true then return response
    decoded = ParseJson(response.body)
    previousSession = m.compatPlaySession
    if SiloObject(decoded) and SiloCompatPattern(decoded.PlaySessionId,"^[A-Za-z0-9_-]+$",128) then m.compatPlaySession = decoded.PlaySessionId
    if m.compatPlaySession = previousSession then return {ok:false,errorCode:"session_not_fresh"}
    receipt = SiloCompatPlaybackReceipt(decoded,proof,m.compatSession.compatConnectInfo.publicUrl,metadata.audioStreamIndex)
    if receipt = invalid then return {ok:false,errorCode:"unsafe_recipe"}
    if m.top.cancelled = true or not CompatOwnerCurrent() then return {ok:false,errorCode:"session_changed"}
    m.compatGeneration++:m.compatProof = proof:m.compatBinding = receipt:m.compatParams = params:m.compatReceipt = decoded:m.compatAudioIndex = metadata.audioStreamIndex
    m.compatActiveObserved = false:m.compatStartUncertain = false:m.compatCloseClock = invalid
    return {ok:true}
end function

' Capture only a bounded compatibility credential before full envelope checks.
' A rejected allocated envelope must retain enough authority for owned logout.
function CompatCollect(cleanup as Boolean) as Object
    m.compatCollectAttempted = true:m.compatCollectUncertain = true
    response = CompatFetch("collect",{secret:m.compatSecret},cleanup)
    if SpField(response,"statusCode") = 404
        m.compatCollectUncertain = false
        return {ok:false,errorCode:"not_authorized"}
    end if
    if response.ok <> true then return response
    raw = ParseJson(response.body)
    if SiloObject(raw) and SiloCompatPattern(raw.AccessToken,"^[!-~]+$",4096)
        current = LoadSession("silo")
        if raw.AccessToken <> current.accessToken and raw.AccessToken <> current.refreshToken and raw.AccessToken <> m.compatSession.accessToken and raw.AccessToken <> m.compatSession.refreshToken then m.compatToken = raw.AccessToken
    end if
    if m.compatToken <> "" then m.compatSession["compatToken"] = m.compatToken
    result = DecodeSiloCompatResponse("collect",response.body,{statusCode:response.statusCode})
    if result.ok <> true then return result
    if result.privateAuth.serverId <> m.compatServerId or m.compatToken = "" then return {ok:false,errorCode:"server_mismatch"}
    m.compatUserId = result.privateAuth.compatUserId
    m.compatCollectUncertain = false
    return {ok:true}
end function

function CompatClose(command = invalid as Dynamic) as Object
    m.top.privateStockContext = invalid
    facts = {ok:false,phase:"closed",credentialRevoked:false,mediaNeverRequested:not m.compatEverReleased,pendingNegotiationDeleted:false,cleanupUnconfirmed:true}
    m.compatCloseClock = CreateObject("roTimespan"):m.compatCloseRequests = 0
    if m.compatBindingReleased and not m.compatMediaRetired
        if not CompatRetireMedia(command) then return facts
    end if
    if m.compatMediaRetired = true then facts["mediaClosed"] = true
    if m.compatToken <> ""
        if not m.compatLogoutAcknowledged
            logout = CompatFetch("logout",{},true)
            acknowledged = DecodeSiloCompatResponse("logout",SiloText(logout.body),{statusCode:SpField(logout,"statusCode")})
            if acknowledged.ok <> true then return facts
            m.compatLogoutAcknowledged = true
        end if
        revoked = CompatFetch("revocation_probe",{},true)
        if revoked.statusCode = 200 then m.compatLogoutAcknowledged = false
        if revoked.statusCode <> 401 then return facts
        facts["credentialRevoked"] = true
    else if m.compatCollectUncertain
        return facts
    end if
    CompatSubtitleDelete()
    m.compatToken = "":m.compatSecret = "":m.compatBinding = invalid:m.compatPlaySession = "":m.compatUserId = "":m.compatReceipt = invalid:m.compatAudioIndex = invalid
    m.compatSession = invalid:m.compatProof = invalid:m.compatServerId = ""
    m.top.privateBinding = invalid
    m.top.privateStockContext = invalid
    facts.ok = true:facts["cleanupUnconfirmed"] = false
    return facts
end function

' A report/DELETE 204 is not activation or drain evidence. Keep the credential
' if a released manifest may still attach after an empty inventory response.
function CompatRetireMedia(command as Dynamic) as Boolean
    if not SiloObject(command) then return false
    if command.localRetired <> true or command.planGeneration <> m.compatGeneration then return false
    if m.compatActiveObserved <> true
        for poll = 0 to 2
            listed = CompatSessions()
            if listed.ok <> true then return false
            if SiloContains(listed.data.sessionIds,m.compatPlaySession)
                m.compatActiveObserved = true:m.compatStartUncertain = false
                exit for
            end if
        end for
        if m.compatActiveObserved <> true then return false
    end if
    stopped = CompatReport("stopped",command)
    if stopped.ok <> true then return false
    deleted = CompatFetch("delete_encodings",{playSessionId:m.compatPlaySession},true)
    acknowledged = DecodeSiloCompatResponse("delete_encodings",SiloText(deleted.body),{statusCode:SpField(deleted,"statusCode")})
    if acknowledged.ok <> true then return false
    listed = CompatSessions()
    if listed.ok <> true then return false
    if SiloContains(listed.data.sessionIds,m.compatPlaySession) then return false
    m.compatStartUncertain = false
    m.compatMediaRetired = true
    return true
end function
