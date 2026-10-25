' All audio HTTP and native capability probes run inside ApiTask.
function TaskAudioFetch(session as Object, action as String, params as Object, revision as Integer) as Object
    if SessionRevision("silo") <> revision then return TaskError("session_changed")
    request = BuildSiloAudioRequest(action,session,params)
    if not request.ok then return request
    response = HttpRequest(request,6000)
    if response.ok <> true and TaskString(response,"errorCode") = "auth_required"
        fresh = TaskRefreshSilo(session,revision)
        if fresh <> invalid
            session = fresh
            request = BuildSiloAudioRequest(action,session,params)
            if request.ok then response = HttpRequest(request,6000)
        end if
    end if
    if SessionRevision("silo") <> revision then return TaskError("session_changed")
    if response.ok <> true then return TaskSiloHttpError(response)
    raw = ParseJson(response.body)
    if not SiloObject(raw) then return TaskError("invalid_response")
    return {ok:true,raw:raw,session:session}
end function

function TaskAudioAction(session as Object, action as String, params as Object, scope as Object, revision as Integer) as Object
    if TaskString(scope,"sourceId") <> TaskString(session,"sourceId") or TaskString(scope,"profileId") <> TaskString(session,"profileId") then return TaskError("session_changed")
    if action = "audio_start" then return TaskAudioStart(session,params,revision)
    if action = "audio_libraries"
        cap = TaskAudioFetch(session,"audio_cap",{},revision)
        if cap.ok <> true then return cap
        if cap.raw.state <> "available" or cap.raw.allowed <> true or not SiloArray(cap.raw.protocol_versions) then return TaskError("audio_unavailable")
        if not SiloContains(cap.raw.protocol_versions,3) then return TaskError("audio_unavailable")
        session = cap.session
    end if
    result = TaskAudioFetch(session,action,params,revision)
    if result.ok <> true then return result
    raw = result.raw
    if action = "audio_detail" then return TaskAudioDetail(raw,TaskString(session,"sourceId"),TaskString(params,"itemId"),CreateObject("roDeviceInfo"))
    if action = "audio_sync"
        if not SiloAudioSyncReceipt(raw,TaskString(params,"itemId")) then return TaskError("progress_unconfirmed")
        return {ok:true,data:{saved:true}}
    end if
    if not SiloArray(raw.items) then return TaskError("invalid_response")
    if raw.items.Count() > 100 then return TaskError("invalid_response")
    entries = []
    for each item in raw.items
        if not SiloObject(item) then return TaskError("invalid_response")
        if action = "audio_libraries" and item.type = "audiobooks"
            if SiloText(item.id) <> "" then entries.Push({id:SiloText(item.id),title:Left(SiloText(item.name),120)})
        else if action = "audio_catalog" and item.type = "audiobook"
            projected = SiloItem(item)
            if projected.ok <> true then return TaskError("invalid_response")
            entries.Push({id:SiloText(item.content_id),title:Left(SiloText(item.title),160),item:projected.item})
        end if
    end for
    cursor = ""
    if SiloObject(raw.page) and raw.page.has_more = true then cursor = SiloText(raw.page.next_cursor)
    if Len(cursor) > 1024 then return TaskError("invalid_response")
    return {ok:true,data:{entries:entries,nextCursor:cursor}}
end function

function TaskAudioStart(session as Object, params as Object, revision as Integer) as Object
    if not TaskPlaybackOpaqueId(TaskString(params,"fileId")) or not SpOpaque(TaskString(params,"itemId")) then return TaskError("invalid_request")
    target = TaskValue(params,"startPositionMs",0)
    if not SiloUIAudioNumber(target,604800000) then return TaskError("invalid_request")
    detail = TaskAudioFetch(session,"audio_detail",{itemId:params.itemId},revision)
    if detail.ok <> true then return detail
    session = detail.session
    device = CreateObject("roDeviceInfo")
    decoded = TaskAudioDetail(detail.raw,TaskString(session,"sourceId"),params.itemId,device,params.fileId)
    if decoded.ok <> true then return decoded
    part = invalid
    for each row in decoded.data.queue
        if row.fileId = params.fileId then part = row
    end for
    if part = invalid then return TaskError("invalid_request")
    if target >= part.durationMs or SiloAudioFormat(part.codec,part.container) = "" then return TaskError("unsupported_audio")
    if not TaskDecoderResult(device.CanDecodeAudio({codec:part.codec,container:part.container,passthru:0})) then return TaskError("unsupported_audio")
    capability = TaskAudioFetch(session,"audio_cap",{},revision)
    if capability.ok <> true then return capability
    session = capability.session:cap = capability.raw
    if cap.state <> "available" or cap.allowed <> true or not SiloArray(cap.protocol_versions) then return TaskError("audio_unavailable")
    if not SiloContains(cap.protocol_versions,3) or not SiloArray(cap.deliveries) then return TaskError("audio_unavailable")
    if not SiloContains(cap.deliveries,"original_http") or not TaskPlaybackOpaqueId(SiloText(cap.installation_id)) then return TaskError("audio_unavailable")
    caps = {video_evidence:"declared",audio_evidence:"platform_attested",codecs_video:[],codecs_video_hardware:[],codecs_audio:[part.codec],containers:[part.container],hdr:false}
    noSubs = {embedded_text:false,sidecar_text:false,ass_styling:false,embedded_bitmap:false,sidecar_bitmap:false,font_attachments:false}
    delivery = {enabled:true,supported_on_device:true,containers:[part.container],video_codecs:[],audio_decode_codecs:[part.codec],audio_passthrough_codecs:[],subtitles:noSubs,features:[],auth_header_refresh:false,validated_claims:[],transformations:[]}
    disabled = {enabled:false,supported_on_device:false,containers:[],video_codecs:[],audio_decode_codecs:[],audio_passthrough_codecs:[],subtitles:noSubs,features:[],auth_header_refresh:false,validated_claims:[],transformations:[]}
    context = {protocol_version:3,form_factor:"tv",app_version:TaskString(session,"appVersion"),device:{platform:"roku",model:device.GetModel()},output:{},deliveries:{original_http:delivery,progressive:disabled,hls:disabled}}
    start = {fileId:part.fileId,installationId:cap.installation_id,playbackAttemptId:TaskUniqueId(),startPositionMs:target,progressPersistence:"client",clientCapabilities:caps,clientPlaybackContext:context,allowAlternateVersions:false}
    fetched = TaskSiloFetch(session,"playback_start",start,revision,12000)
    if fetched.ok <> true then return fetched
    session = fetched.session
    raw = ParseJson(fetched.response.body)
    if not SiloObject(raw) then return TaskError("invalid_response")
    cleanup = TaskSiloCleanupPlan(raw,cap.installation_id)
    try
        plan = SiloAudioPlan(raw,session,part,target)
    catch exception
        return TaskRejectSiloPlayback(session,cleanup,"invalid_response",revision)
    end try
    if plan.ok <> true then return TaskRejectSiloPlayback(session,cleanup,TaskString(plan,"errorCode"),revision)
    if SessionRevision("silo") <> revision then return TaskRejectSiloPlayback(session,cleanup,"session_changed",revision)
    plan.installationId = cap.installation_id
    plan.sourceId = TaskString(session,"sourceId")
    plan.itemId = params.itemId
    return {ok:true,plan:plan,data:{}}
end function

' Admit a whole presentation before exposing its queue to the scene.
function TaskAudioDetail(raw as Dynamic, sourceId as String, itemId as String, device as Object, pinnedFileId = "" as String) as Object
    baseline = SiloAudioDetail(raw,sourceId,itemId)
    if not SiloObject(raw) then return baseline
    resume = SiloNumber(raw.position_seconds,0)
    if SiloObject(raw.user_data) then resume = SiloNumber(raw.user_data.position_seconds,resume)
    variants = []
    if SiloArray(raw.playback_variants)
        if raw.playback_variants.Count() > 16 then return TaskError("invalid_parts")
        variants = raw.playback_variants
    end if
    if variants.Count() = 0
        if baseline.ok <> true then return baseline
        if TaskAudioQueueSupported(baseline.data.queue,device) then return baseline
        return TaskError("unsupported_audio")
    end if
    for i = 0 to variants.Count()-1
        variant = variants[i]
        if SiloObject(variant)
            candidateRaw = {content_id:raw.content_id,type:raw.type,title:raw.title,user_data:raw.user_data,position_seconds:raw.position_seconds,playback_variants:[variant]}
            candidate = SiloAudioDetail(candidateRaw,sourceId,itemId)
            if candidate.ok = true
                ' Whole-item resume has no edition identity. Never infer narration
                ' equivalence from equal durations across different presentations.
                ' Start pins a file from the scene's already admitted queue, allowing
                ' later parts to continue after whole-book progress is saved.
                pinnedVariant = false
                if pinnedFileId <> ""
                    for each part in variant.parts
                        for each version in part.versions
                            if SiloText(version.file_id) = pinnedFileId then pinnedVariant = true
                        end for
                    end for
                end if
                permitted = (pinnedFileId = "" and (i = 0 or resume = 0)) or pinnedVariant
                if permitted
                    if TaskAudioQueueSupported(candidate.data.queue,device) then return candidate
                    replacement = TaskAudioCompatibleVariant(candidateRaw,candidate,device)
                    if replacement.ok = true then return replacement
                end if
            end if
        end if
    end for
    return TaskError("unsupported_audio")
end function

function TaskAudioQueueSupported(queue as Object, device as Object) as Boolean
    for each part in queue
        if SiloAudioFormat(part.codec,part.container) = "" then return false
        if not TaskDecoderResult(device.CanDecodeAudio({codec:part.codec,container:part.container,passthru:0})) then return false
    end for
    return true
end function

' Alternatives inside one server presentation are interchangeable per part. Keep
' the default whenever it is admitted; never borrow a part from another variant.
' Keep the same part timeline from the first start so later saved progress and
' requested local offsets remain valid on every revalidation.
function TaskAudioCompatibleVariant(raw as Object, original as Object, device as Object) as Object
    variant = raw.playback_variants[0]
    parts = []
    for i = 0 to variant.parts.Count()-1
        part = variant.parts[i]
        selected = original.data.queue[i]
        if not TaskAudioQueueSupported([selected],device)
            selected = invalid
            for each version in part.versions
                codec = LCase(SiloText(version.codec_audio)):container = LCase(SiloText(version.container))
                duration = SiloNumber(version.duration,0)*1000#
                sameTimeline = duration = original.data.queue[i].durationMs
                if SiloText(version.codec_video) = "" and sameTimeline
                    if SiloAudioFormat(codec,container) <> ""
                        if TaskDecoderResult(device.CanDecodeAudio({codec:codec,container:container,passthru:0}))
                            selected = {fileId:SiloText(version.file_id)}
                            exit for
                        end if
                    end if
                end if
            end for
        end if
        if selected = invalid then return TaskError("unsupported_audio")
        parts.Push({part_index:part.part_index,default_file_id:selected.fileId,versions:part.versions})
    end for
    replacement = {variant_id:variant.variant_id,part_count:variant.part_count,parts:parts}
    projected = {content_id:raw.content_id,type:raw.type,title:raw.title,user_data:raw.user_data,position_seconds:raw.position_seconds,playback_variants:[replacement]}
    return SiloAudioDetail(projected,original.data.sourceId,original.data.itemId)
end function
