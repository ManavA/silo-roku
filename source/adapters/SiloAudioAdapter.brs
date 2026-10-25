' Audio-only projection of the actual v2 catalog/variants contract. No AGPL code.
function SiloAudioDetail(raw as Dynamic, sourceId as String, itemId as String) as Object
    if not SiloObject(raw) then return SiloError("invalid_response", "Audio details are unavailable.")
    if SiloText(raw.content_id) <> itemId or raw.type <> "audiobook" then return SiloError("unsupported_audio", "This audio item is unavailable.")
    parts = []:variant = invalid
    if SiloArray(raw.playback_variants) and raw.playback_variants.Count() > 0
        variant = raw.playback_variants[0]
        if not SiloObject(variant) or not SiloArray(variant.parts) then return SiloError("invalid_parts", "Audio parts are incomplete.")
        if variant.part_count <> variant.parts.Count() then return SiloError("invalid_parts", "Audio parts are incomplete.")
        parts = variant.parts
    else if SiloArray(raw.versions)
        if raw.versions.Count() = 1 then parts = [{part_index:SiloNumber(raw.versions[0].presentation_part_index,0),versions:raw.versions,default_file_id:raw.versions[0].file_id}]
    end if
    if parts.Count() = 0 or parts.Count() > 64 then return SiloError("invalid_parts", "Audio parts are incomplete.")
    queue = []:offsetMs = 0#:seen = {}:lastIndex = -1
    for each part in parts
        if not SiloObject(part) or not SiloArray(part.versions) then return SiloError("invalid_parts", "Audio parts are incomplete.")
        index = SiloNumber(part.part_index,-1)
        if index < 0 or index <> Int(index) or (lastIndex = -1 and index > 1) or (lastIndex >= 0 and index <> lastIndex+1) then return SiloError("invalid_parts", "Audio parts are unordered.")
        lastIndex = index
        if part.versions.Count() = 0 or part.versions.Count() > 16 then return SiloError("invalid_parts", "Audio parts are incomplete.")
        selected = invalid
        id = SiloText(part.default_file_id)
        if id = "" and part.versions.Count() = 1 then id = SiloText(part.versions[0].file_id)
        for each version in part.versions
            if not SiloObject(version) then return SiloError("invalid_parts", "Audio parts are incomplete.")
            if SiloText(version.file_id) = id then selected = version
        end for
        if selected = invalid or id = "" or Len(id) > 256 or seen.DoesExist(id) then return SiloError("invalid_parts", "Audio parts are incomplete.")
        declaredTotal = SiloNumber(selected.presentation_part_total,0)
        if declaredTotal <> 0 and declaredTotal <> parts.Count() then return SiloError("invalid_parts", "Audio parts are incomplete.")
        declaredIndex = SiloNumber(selected.presentation_part_index,index)
        if declaredIndex <> 0 and declaredIndex <> index then return SiloError("invalid_parts", "Audio parts are unordered.")
        seen[id] = true
        duration = SiloNumber(selected.duration,0)*1000#
        if not SiloUIAudioNumber(duration,604800000) or duration < 1000 or offsetMs+duration > 604800000 then return SiloError("invalid_parts", "Audio duration is unavailable.")
        if SiloText(selected.codec_video) <> "" then return SiloError("unsupported_audio", "A video source cannot use Audio.")
        chapters = []
        for each chapter in SiloVersionChapters(selected.chapters)
            if chapters.Count() >= 64 then exit for
            if chapter.end_seconds*1000 <= duration then chapters.Push(chapter)
        end for
        queue.Push({fileId:id,offsetMs:offsetMs,durationMs:duration,codec:LCase(SiloText(selected.codec_audio)),container:LCase(SiloText(selected.container)),chapters:chapters})
        offsetMs = offsetMs+duration
    end for
    resume = SiloNumber(raw.position_seconds,0)*1000#
    if SiloObject(raw.user_data) then resume = SiloNumber(raw.user_data.position_seconds,resume/1000)*1000#
    if not SiloUIAudioNumber(resume,offsetMs) then resume = 0
    variantId = ""
    if SiloObject(variant) then variantId = SiloText(variant.variant_id)
    return {ok:true,data:{variantId:variantId,itemId:itemId,sourceId:sourceId,title:Left(SiloText(raw.title),200),queue:queue,durationMs:offsetMs,resumeMs:resume}}
end function

function SiloAudioFormat(codec as String, container as String) as String
    if codec = "mp3" and container = "mp3" then return "mp3"
    if codec = "aac" and (container = "mp4" or container = "m4a" or container = "m4b") then return "mp4"
    if codec = "aac" and container = "aac" then return "es.aac-adts"
    if codec = "flac" and container = "flac" then return "flac"
    return ""
end function

function BuildSiloAudioRequest(action as String, session as Object, params as Object) as Object
    if action = "audio_libraries" then return BuildSiloRequest("libraries",session,{})
    if action = "audio_cap" then return BuildSiloRequest("playback_capabilities",session,{})
    if action = "audio_detail" then return BuildSiloRequest("detail",session,params)
    if action = "audio_catalog"
        query = {type:"audiobook",libraryId:SiloText(params.libraryId),limit:36}
        if SiloText(params.cursor) <> ""
            if Len(params.cursor) > 1024 then return SiloError("invalid_request", "Audio page is unavailable.")
            query.cursor = params.cursor
        end if
        return BuildSiloRequest("catalog_query",session,query)
    end if
    request = BuildSiloRequest("libraries",session,{})
    if not request.ok then return request
    if action = "audio_sync_cap"
        request.url = SiloBaseUrl(SiloText(session.baseUrl)) + "/api/v2/sync/progress/capabilities"
        return request
    end if
    if action <> "audio_sync" then return SiloError("unsupported_action", "Audio operation is unavailable.")
    if SiloText(params.itemId) = "" or Len(SiloText(params.itemId)) > 256 then return SiloError("invalid_request", "Audio item is unavailable.")
    if not SiloUIAudioNumber(params.positionMs,604800000) or not SiloUIAudioNumber(params.durationMs,604800000) then return SiloError("invalid_request", "Audio position is unavailable.")
    if params.durationMs < 1000 or params.positionMs > params.durationMs then return SiloError("invalid_request", "Audio position is unavailable.")
    request.method = "POST"
    request.url = SiloBaseUrl(SiloText(session.baseUrl)) + "/api/v2/sync/progress"
    request.headers["Content-Type"] = "application/json"
    request.body = FormatJson({items:[{media_item_id:params.itemId,position_ms:Int(params.positionMs),duration_ms:Int(params.durationMs)}]})
    return request
end function

function SiloAudioSyncReceipt(raw as Dynamic, itemId as String) as Boolean
    if not SiloObject(raw) or not SiloArray(raw.items) then return false
    if raw.items.Count() <> 1 or not SiloObject(raw.items[0]) then return false
    receipt = raw.items[0]
    return receipt.index = 0 and receipt.media_item_id = itemId and receipt.status = "success"
end function

function SiloAudioPlan(raw as Dynamic, session as Object, part as Object, targetMs as Dynamic) as Object
    failure = SiloError("unsupported_audio_plan", "This source has no validated native Audio route.")
    if not SiloObject(raw) or raw.protocol_version <> 3 or not SiloObject(raw.playback_plan) then return failure
    if raw.outcome <> "plan" and raw.outcome <> "playable" then return failure
    plan = raw.playback_plan
    if plan.delivery <> "original_http" then return failure
    if plan.requested_media_file_id <> part.fileId or plan.effective_media_file_id <> part.fileId then return failure
    if not SiloObject(plan.source) or not SiloObject(plan.stream) or not SiloObject(plan.timeline) then return failure
    if plan.source.media_file_id <> part.fileId or SiloText(plan.source.video_codec) <> "" or plan.source.audio_codec <> part.codec then return failure
    stream = plan.stream:timeline = plan.timeline
    if stream.protocol <> "http_progressive" or stream.header_refresh <> "none" or stream.container <> part.container then return failure
    format = SiloAudioFormat(part.codec,part.container)
    if format = "" or timeline.can_seek_anywhere <> true or timeline.timeline_offset_seconds <> 0 then return failure
    if not SiloUIAudioNumber(timeline.player_start_seconds,part.durationMs/1000) then return failure
    if Abs(timeline.player_start_seconds*1000-targetMs) > 1000 then return failure
    for each key in ["session_id","plan_id","plan_attempt_key"]
        if SiloText(plan[key]) = "" or Len(SiloText(plan[key])) > 256 then return failure
    end for
    url = SiloResolveUrl(SiloText(stream.url),SiloText(session.baseUrl))
    origin = SiloUrlParts(url):base = SiloUrlParts(SiloText(session.baseUrl))
    if not origin.ok or not base.ok or Len(url) > 4096 then return failure
    headers = {}
    if SiloObject(stream.headers)
        if stream.headers.Count() > 16 then return failure
        for each key in stream.headers
            lower = LCase(key)
            if lower <> "authorization" and lower <> "x-profile-token" and lower <> "x-profile-id" and lower <> "cookie" and lower <> "x-plex-token"
                if not SiloSafeHeader(key,true) or not SiloSafeHeader(SiloText(stream.headers[key]),false) then return failure
                headers[key] = SiloText(stream.headers[key])
            end if
        end for
    end if
    if origin.origin = base.origin
        headers["Authorization"] = "Bearer " + SiloText(session.accessToken)
        headers["X-Profile-Id"] = SiloText(session.profileId)
        if SiloText(session.profileToken) <> "" then headers["X-Profile-Token"] = SiloText(session.profileToken)
    end if
    return {ok:true,provider:"silo",sessionId:plan.session_id,versionId:part.fileId,url:url,headers:headers,streamFormat:format,startPositionMs:timeline.player_start_seconds*1000,timelineOffsetMs:0}
end function
