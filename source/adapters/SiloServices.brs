' Optional server surfaces. Pure transport/normalization; no credentials in UI data.
function BuildSiloServicesRequest(action as String, session as Object, params as Object) as Object
    seed = BuildSiloRequest("libraries", session, {})
    if seed.ok <> true then return seed
    base = SiloBaseUrl(SiloText(session.baseUrl)) + "/api/v2"
    request = {ok:true,method:"GET",headers:seed.headers,body:"",errorBodyLimit:8192}
    path = ""
    body = invalid
    routes = {service_requests_cap:"/requests/status",service_notification_cap:"/notifications/capabilities",service_moderation_cap:"/admin/requests/capabilities",service_subtitle_provider_cap:"/subtitles/providers/status",service_subtitle_ai_cap:"/subtitles/ai/status",service_subtitle_sync_cap:"/subtitles/sync/status"}
    if routes.DoesExist(action)
        path = routes[action]
    else if action = "service_request_search" or action = "service_discover"
        page = Int(SiloNumber(params.page,1))
        if page < 1 then page = 1
        if page > 20 then page = 20
        path = "/requests/search?q=" + SiloEscape(Left(SiloText(params.query),200)) + "&media_type=all&page=" + page.ToStr()
        if action = "service_discover"
            section = "trending_movies"
            if params.mediaType = "series" then section = "trending_series"
            path = "/requests/discover/" + section + "?page=" + page.ToStr()
        end if
    else if action = "service_request_mine" or action = "service_moderation_list"
        path = "/requests/mine?limit=30"
        if action = "service_moderation_list" then path = "/admin/requests?limit=30"
        if SiloText(params.cursor) <> "" then path = path + "&cursor=" + SiloEscape(Left(SiloText(params.cursor),2048))
    else if action = "service_request_detail"
        mediaType = SiloText(params.mediaType)
        if (mediaType <> "movie" and mediaType <> "series") or SiloNumber(params.tmdbId,0) < 1 then return SiloError("invalid_request", "Select a title.")
        path = "/requests/detail/" + mediaType + "/" + Int(params.tmdbId).ToStr()
    else if action = "service_request_status"
        if SiloText(params.id) = "" then return SiloError("invalid_request", "Select a request.")
        path = "/requests/" + SiloEscape(SiloText(params.id))
    else if action = "service_request_cancel" or action = "service_moderation_approve" or action = "service_moderation_decline" or action = "service_moderation_cancel"
        if SiloText(params.id) = "" then return SiloError("invalid_request", "Select a request.")
        request.method = "POST"
        path = "/requests/" + SiloEscape(SiloText(params.id)) + "/cancel"
        if Left(action,19) = "service_moderation_" then path = "/admin/requests/" + SiloEscape(SiloText(params.id)) + "/" + Mid(action,20)
        body = {}
    else if action = "service_notifications"
        status = "all"
        if params.unread = true then status = "unread"
        path = "/notifications?limit=30&status=" + status
        if SiloText(params.cursor) <> "" then path = path + "&cursor=" + SiloEscape(Left(SiloText(params.cursor),2048))
    else if action = "service_notifications_count"
        path = "/notifications/unread-count"
    else if action = "service_notifications_read" or action = "service_notifications_read_all"
        request.method = "POST"
        if action = "service_notifications_read"
            if SiloText(params.id) = "" then return SiloError("invalid_request", "Select a notification.")
            path = "/notifications/" + SiloEscape(SiloText(params.id)) + "/read"
        else
            if SiloText(params.through) = "" then return SiloError("invalid_request", "Load the inbox before marking it read.")
            path = "/notifications/read-all"
            body = {through:Left(SiloText(params.through),2048)}
        end if
    else if action = "service_calendar"
        startDate = SiloText(params.start)
        endDate = SiloText(params.end)
        zone = SiloText(params.timezone)
        datePattern = CreateObject("roRegex", "^[0-9]{4}-[0-9]{2}-[0-9]{2}$", "")
        if not datePattern.IsMatch(startDate) or not datePattern.IsMatch(endDate) or zone = "" or Len(zone) > 100 then return SiloError("invalid_request", "Choose a calendar week and timezone.")
        filter = SiloText(params.filter)
        if not SiloContains(["all","everything","following","favorites","watchlist","popular","trending"],filter) then filter = "all"
        path = "/calendar?start=" + startDate + "&end=" + endDate + "&timezone=" + SiloEscape(zone) + "&filter=" + filter
    else if Left(action,17) = "service_subtitle_"
        fileId = SiloText(params.fileId)
        if action = "service_subtitle_quota"
            path = "/subtitles/ai/quota"
        else if action = "service_subtitle_jobs"
            if fileId = "" then return SiloError("invalid_request", "Select a video version.")
            path = "/subtitles/ai/jobs?media_file_id=" + SiloEscape(fileId)
        else if action = "service_subtitle_job_cancel"
            if SiloText(params.id) = "" then return SiloError("invalid_request", "Select a subtitle job.")
            path = "/subtitles/ai/jobs/" + SiloEscape(SiloText(params.id)) + "/cancel"
            request.method = "POST"
        else
            if fileId = "" then return SiloError("invalid_request", "Select a video version.")
            if action = "service_subtitle_search"
                language = Left(SiloText(params.language),64)
                if language = "" then return SiloError("invalid_request", "Select a language.")
                path = "/subtitles/search"
                request.method = "POST"
                body = {media_file_id:fileId,languages:[language]}
            else if action = "service_subtitle_download"
                result = params.result
                if not SiloObject(result) then return SiloError("invalid_request", "Select a subtitle result.")
                if SiloText(result.id) = "" or SiloText(result.provider) = "" or SiloText(result.language) = "" then return SiloError("invalid_request", "Select a subtitle result.")
                path = "/subtitles/download"
                request.method = "POST"
                body = {media_file_id:fileId,provider:SiloText(result.provider),subtitle_id:SiloText(result.id),language:SiloText(result.language),release_name:Left(SiloText(result.releaseName),4096),score:SiloNumber(result.score,0),hearing_impaired:result.hearingImpaired = true}
            else if action = "service_subtitle_ai_create"
                kind = SiloText(params.kind)
                if not SiloContains(["translate","transcribe","transcribe_translate"],kind) then return SiloError("invalid_request", "Select a subtitle job type.")
                index = SiloNumber(params.sourceIndex,-2)
                if index < -1 or index <> Int(index) or SiloText(params.targetLanguage) = "" then return SiloError("invalid_request", "Select source and target languages.")
                path = "/subtitles/ai/translate"
                request.method = "POST"
                body = {media_file_id:fileId,kind:kind,source_index:index,source_language:Left(SiloText(params.sourceLanguage),64),target_language:Left(SiloText(params.targetLanguage),64),start_position:0}
            else if action = "service_subtitle_list"
                path = "/subtitles/" + SiloEscape(fileId) + "/sync"
            else if action = "service_subtitle_sync_read" or action = "service_subtitle_sync_start" or action = "service_subtitle_timing"
                key = SiloText(params.key)
                if not CreateObject("roRegex","^(stored-[1-9][0-9]*|external-[0-9a-f]{64})$", "").IsMatch(key) then return SiloError("invalid_request", "Refresh subtitle inventory.")
                path = "/subtitles/" + SiloEscape(fileId) + "/sync/" + key
                request.captureETag = true
                if action = "service_subtitle_sync_start" then request.method = "POST"
                if action = "service_subtitle_timing"
                    tag = SiloText(params.etag)
                    if Len(tag) < 3 or Len(tag) > 256 or Left(tag,1) <> Chr(34) or Right(tag,1) <> Chr(34) or Instr(1,tag,Chr(13)) > 0 or Instr(1,tag,Chr(10)) > 0 then return SiloError("precondition_required", "Refresh subtitle timing before changing it.")
                    offset = SiloNumber(params.offsetMs,600001)
                    scale = SiloNumber(params.scale,0)
                    if offset < -600000 or offset > 600000 or offset <> Int(offset) or scale < 0.9 or scale > 1.1 then return SiloError("invalid_request", "Subtitle timing is outside the supported range.")
                    path = path + "/timing"
                    request.method = "PUT"
                    request.headers["If-Match"] = tag
                    body = {offset_ms:offset,scale:scale}
                end if
            else
                return SiloError("unsupported_action", "This operation is unavailable.")
            end if
        end if
    else if action = "service_request_create"
        mediaType = SiloText(params.mediaType)
        tmdbId = SiloNumber(params.tmdbId, 0)
        title = Left(SiloText(params.title), 300)
        if (mediaType <> "movie" and mediaType <> "series") or tmdbId < 1 or tmdbId <> Int(tmdbId) or title = "" then return SiloError("invalid_request", "Select a requestable title.")
        request.method = "POST"
        path = "/requests"
        body = {media_type:mediaType,tmdb_id:tmdbId,title:title}
    else
        return SiloError("unsupported_action", "This operation is unavailable.")
    end if
    request.url = base + path
    if body <> invalid then request.body = FormatJson(body) : request.headers["Content-Type"] = "application/json"
    return request
end function

function DecodeSiloServicesResponse(action as String, body as String, params as Object) as Object
    if action = "service_subtitle_job_cancel" or action = "service_notifications_read" or action = "service_notifications_read_all" then return {ok:true,data:{confirmed:true}}
    decoded = ParseJson(body)
    if not SiloObject(decoded) then return SiloError("invalid_response", "The response is unavailable.")
    if Right(action, 4) = "_cap"
        available = decoded.allowed = true and decoded.state = "available"
        if action = "service_requests_cap" then available = available and decoded.requests_enabled = true
        if action = "service_notification_cap"
            available = available and SiloObject(decoded.in_app)
            if available then available = decoded.in_app.enabled = true
        end if
        if action = "service_subtitle_provider_cap" or action = "service_subtitle_ai_cap" then available = available and decoded.enabled = true
        if action = "service_moderation_cap" then available = available and decoded.available = true
        return {ok:true,data:{available:available,revision:Left(SiloText(decoded.revision),128),transcribeEnabled:decoded.transcribe_enabled = true,external:decoded.external = true}}
    end if
    if action = "service_subtitle_search" or action = "service_subtitle_list" or action = "service_subtitle_jobs"
        raw = decoded.results
        if action = "service_subtitle_list" then raw = decoded.subtitles
        if action = "service_subtitle_jobs" then raw = decoded.jobs
        if not SiloArray(raw) then return SiloError("invalid_response", "Subtitle results are unavailable.")
        entries = []
        for each entry in raw
            if entries.Count() >= 30 then exit for
            if not SiloObject(entry) then return SiloError("invalid_response", "Subtitle results are unavailable.")
            entries.Push(ServicesSubtitleEntry(entry))
        end for
        return {ok:true,data:{entries:entries,hasMore:false}}
    end if
    if action = "service_subtitle_quota" then return {ok:true,data:{limited:decoded.limited = true,remaining:SiloNumber(decoded.remaining,0),used:SiloNumber(decoded.used,0),period:SiloText(decoded.period)}}
    if SiloContains(["service_subtitle_sync_read","service_subtitle_sync_start","service_subtitle_timing","service_subtitle_download","service_subtitle_ai_create"],action)
        raw = decoded.subtitle
        if action = "service_subtitle_ai_create" then raw = decoded.job
        if action = "service_subtitle_sync_start" then raw = decoded.subtitle
        if not SiloObject(raw) then return SiloError("invalid_response", "The subtitle change was not confirmed.")
        return {ok:true,data:{entry:ServicesSubtitleEntry(raw),etag:SiloText(params.etag)}}
    end if
    if action = "service_notifications_count" then return {ok:true,data:{unreadCount:SiloNumber(decoded.count,0)}}
    if action = "service_calendar"
        if not SiloArray(decoded.events) then return SiloError("invalid_response", "The calendar is unavailable.")
        entries = []
        for each day in decoded.events
            if not SiloObject(day) or not SiloArray(day.items) then return SiloError("invalid_response", "The calendar is unavailable.")
            for each event in day.items
                if entries.Count() >= 100 then exit for
                if not SiloObject(event) then return SiloError("invalid_response", "The calendar is unavailable.")
                entries.Push({title:Left(SiloText(event.title),200),date:SiloText(day.date),itemId:SiloText(event.content_id),type:SiloText(event.type),summary:Left(SiloText(event.episode_title),300),airTime:SiloText(event.air_time)})
            end for
        end for
        return {ok:true,data:{entries:entries,hasMore:false}}
    end if
    if action = "service_notifications"
        if not SiloArray(decoded.items) or SiloText(decoded.read_cutoff) = "" then return SiloError("invalid_response", "The inbox is unavailable.")
        entries = []
        for each entry in decoded.items
            if entries.Count() >= 30 then exit for
            if not SiloObject(entry) then return SiloError("invalid_response", "The inbox is unavailable.")
            entries.Push({id:SiloText(entry.id),title:Left(SiloText(entry.series_title),200),summary:Left(SiloText(entry.episode_title),300),kind:SiloText(entry.type),date:SiloText(entry.created_at),unread:SiloText(entry.read_at) = "",itemId:SiloText(entry.episode_id)})
        end for
        cursor = ""
        more = false
        if SiloObject(decoded.page) then cursor = SiloText(decoded.page.next_cursor) : more = decoded.page.has_more = true and cursor <> "" and cursor <> SiloText(params.cursor)
        return {ok:true,data:{entries:entries,nextCursor:cursor,hasMore:more,cutoff:SiloText(decoded.read_cutoff)}}
    end if
    if action = "service_request_search" or action = "service_discover" or action = "service_request_mine" or action = "service_moderation_list"
        raw = decoded.results
        if action = "service_request_mine" or action = "service_moderation_list" then raw = decoded.items
        if not SiloArray(raw) then return SiloError("invalid_response", "The list is unavailable.")
        entries = []
        for each entry in raw
            if entries.Count() >= 30 then exit for
            if not SiloObject(entry) then return SiloError("invalid_response", "The list is unavailable.")
            entries.Push(ServicesRequestEntry(entry))
        end for
        page = SiloNumber(decoded.page,1)
        cursor = ""
        more = page < SiloNumber(decoded.total_pages,1) and page < 20
        if SiloObject(decoded.page)
            cursor = SiloText(decoded.page.next_cursor)
            more = decoded.page.has_more = true and cursor <> "" and cursor <> SiloText(params.cursor)
        end if
        return {ok:true,data:{entries:entries,page:page,nextCursor:cursor,hasMore:more}}
    end if
    if SiloContains(["service_request_create","service_request_cancel","service_request_status","service_request_detail","service_moderation_approve","service_moderation_decline","service_moderation_cancel"],action)
        if SiloText(decoded.id) = "" and action <> "service_request_detail" then return SiloError("invalid_response", "The change was not confirmed.")
        return {ok:true,data:{entry:ServicesRequestEntry(decoded)}}
    end if
    return SiloError("unsupported_action", "This operation is unavailable.")
end function

function ServicesRequestEntry(entry as Object) as Object
    request = entry.request
    if not SiloObject(request) then request = {}
    download = entry.download
    if not SiloObject(download) then download = request.download
    downloadSummary = ""
    if SiloObject(download)
        phase = SiloText(download.phase)
        known = SiloContains(["queued","downloading","paused","stalled","importing","import_blocked"],phase)
        if not known then phase = "downloading"
        downloadSummary = phase
        percent = SiloNumber(download.percent,-1)
        if known and percent >= 0 and percent <= 100 then downloadSummary = downloadSummary + " • " + Int(percent).ToStr() + "%"
        if SiloText(download.updated_at) <> "" then downloadSummary = downloadSummary + " • Reported " + SiloText(download.updated_at)
    end if
    state = SiloText(entry.state)
    if state = "" then state = SiloText(request.state)
    return {id:SiloText(entry.id),title:Left(SiloText(entry.title),300),mediaType:SiloText(entry.media_type),tmdbId:SiloNumber(entry.tmdb_id,0),state:state,status:SiloText(entry.status),outcome:SiloText(entry.outcome),summary:Left(SiloText(entry.overview),1600),downloadSummary:downloadSummary,requestable:request.requestable = true,requestId:SiloText(request.request_id),itemId:SiloText(entry.library_content_id)}
end function

function ServicesSubtitleEntry(entry as Object) as Object
    timing = entry.timing
    if not SiloObject(timing) then timing = {}
    sync = entry.sync
    if not SiloObject(sync) then sync = {}
    return {id:SiloText(entry.id),key:SiloText(entry.key),title:Left(SiloText(entry.label),200),releaseName:Left(SiloText(entry.release_name),300),provider:SiloText(entry.provider),language:SiloText(entry.language),score:SiloNumber(entry.score,0),hearingImpaired:entry.hearing_impaired = true,status:SiloText(entry.status),kind:SiloText(entry.kind),progress:SiloNumber(entry.progress,0),syncStatus:SiloText(sync.status),offsetMs:SiloNumber(timing.offset_ms,0),scale:SiloNumber(timing.scale,1)}
end function
