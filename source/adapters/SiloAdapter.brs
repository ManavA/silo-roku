' Pure Silo v2 transport and v3 playback policy. No I/O or logging here.
' Catalog/person/marker contract inspected at Android reference e9f2ee94ddd625ba41d7634fcf18d1ad7b464608.
' Auth/profile contract inspected at Android reference 45774f8bfe92b0517f42a60e7c8be4ce026f4858.
' Caller must keep request bodies, session, playbackDecision and plans inside Tasks.
function BuildSiloRequest(action as String, session as Object, params as Object) as Object
    if Left(action,8) = "service_" then return BuildSiloServicesRequest(action,session,params)
    base = SiloBaseUrl(SiloText(session.baseUrl))
    if base = "" then return SiloError("invalid_server_url", "Enter a valid server address.")
    headers = SiloClientHeaders(session)
    method = "GET"
    path = ""
    body = invalid
    publicAction = action = "device_capability" or action = "device_start" or action = "device_poll" or action = "refresh"
    accountAction = action = "profiles" or action = "profile_verify" or action = "compat_connect_info"
    supported = ["collection_capabilities", "collection_choices", "collection_add", "collection_remove", "shuffle_capabilities", "shuffle_start", "shuffle_status", "shuffle_advance", "shuffle_skip", "shuffle_stop", "settings_capabilities", "settings_contract", "settings_effective", "settings_write", "settings_reset", "device_capability", "device_start", "device_poll", "refresh", "profiles", "profile_verify", "home", "libraries", "catalog_query", "detail", "markers", "similar", "person", "person_items", "seasons", "episodes", "mark_watched", "mark_unwatched", "playback_capabilities", "playback_error_report", "playback_start", "playback_replan", "playback_stop", "playback_progress", "home_dismiss", "collections", "server_collections", "people", "favorite_add", "favorite_remove", "watchlist_add", "watchlist_remove", "home_section_items"]
    for each homeAction in ["home_sections_list","home_sections_settings","home_sections_save","home_sections_reset"]
        supported.Push(homeAction)
    end for
    supported.Push("trickplay")
    supported.Push("audio_pref_set")
    supported.Push("collection_create")
    supported.Push("catalog_identity_capabilities")
    supported.Push("catalog_resolve")
    supported.Push("catalog_genres")
    supported.Push("compat_connect_info")
    supported.Push("compat_handoff_approve")
    if not SiloContains(supported, action) then return SiloError("unsupported_action", "This operation is unavailable.")
    if not publicAction
        if SiloText(session.accessToken) = "" then return SiloError("auth_required", "Sign in to continue.")
        if not accountAction and SiloText(session.profileId) = "" then return SiloError("profile_required", "Select a profile to continue.")
        headers["Authorization"] = "Bearer " + SiloText(session.accessToken)
        ' Profile selection/unlock must remain available when the previously
        ' selected profile's proof expires. These routes accept bearer auth
        ' without the optional X-Profile headers in the v2 contract.
        if not accountAction and SiloText(session.profileId) <> ""
            headers["X-Profile-Id"] = SiloText(session.profileId)
            if SiloText(session.profileToken) <> "" then headers["X-Profile-Token"] = SiloText(session.profileToken)
        end if
    end if
    if Left(action,14) = "home_sections_"
        for each key in params
            if action <> "home_sections_save" or key <> "overrides" then return SiloError("invalid_request","Home layout is unavailable.")
        end for
        path = "/profile/sections?scope=home"
        if action = "home_sections_settings" then path = "/profile/sections/settings?scope=home"
        if action = "home_sections_reset" then method = "DELETE"
        if action = "home_sections_save"
            if not SiloArray(params.overrides) then return SiloError("invalid_request","Home layout is unavailable.")
            method = "PUT"
            body = {overrides:params.overrides}
        end if
    else if action = "trickplay"
        if not CreateObject("roRegex","^[0-9]{1,18}$","").IsMatch(SiloText(params.fileId)) or SiloText(params.itemId) = "" then return SiloError("invalid_request","Previews are unavailable.")
        path = "/watch/" + SiloEscape(SiloText(params.itemId)) + "/trickplay?file_id=" + SiloEscape(SiloText(params.fileId))
    else if action = "catalog_identity_capabilities"
        path = "/catalog/search/capabilities"
    else if action = "catalog_resolve"
        for each key in params
            if not SiloContains(["seeds","limit","cursor"],key) then return SiloError("invalid_identity_batch","Catalog lookup is unavailable.")
        end for
        if not SiloIdentitySeeds(params.seeds) or params.limit <> 100 then return SiloError("invalid_identity_batch","Catalog lookup is unavailable.")
        method = "POST"
        path = "/catalog/resolve"
        body = {seeds:params.seeds,limit:100}
        if params.cursor <> invalid
            if SiloText(params.cursor) = "" or Len(SiloText(params.cursor)) > 8192 then return SiloError("invalid_identity_batch","Catalog lookup is unavailable.")
            body.cursor = params.cursor
        end if
    else if action = "compat_handoff_approve"
        for each key in params
            if key <> "code" then return SiloError("invalid_handoff","Compatibility approval is unavailable.")
        end for
        if type(params.code) <> "String" and type(params.code) <> "roString" then return SiloError("invalid_handoff","Compatibility approval is unavailable.")
        if not CreateObject("roRegex","^[0-9]{6}$","").IsMatch(params.code) then return SiloError("invalid_handoff","Compatibility approval is unavailable.")
        for each key in ["accessToken","profileId","profileToken"]
            value = session[key]
            if value <> invalid
                if type(value) <> "String" and type(value) <> "roString" then return SiloError("invalid_handoff","Compatibility approval is unavailable.")
                if Len(value) > 8192 or CreateObject("roRegex","[\x00-\x1f\x7f]","").IsMatch(value) then return SiloError("invalid_handoff","Compatibility approval is unavailable.")
            end if
        end for
        method = "POST"
        path = "/auth/device/approve-handoff"
        body = {code:params.code}
    else if action = "compat_connect_info"
        path = "/compat/connect-info"
    else if action = "shuffle_capabilities"
        path = "/shuffles/capabilities"
    else if action = "shuffle_start"
        if not SiloContains(["library","series","season","library_collection","user_collection"], SiloText(params.kind)) or SiloText(params.scopeId) = "" then return SiloError("invalid_shuffle_scope", "Choose a shuffle scope.")
        method = "POST"
        path = "/shuffles"
        body = {scope:{kind:params.kind,id:params.scopeId}}
    else if action = "shuffle_status" or action = "shuffle_advance" or action = "shuffle_skip" or action = "shuffle_stop"
        if SiloText(params.shuffleId) = "" then return SiloError("shuffle_required", "Start a shuffle first.")
        path = "/shuffles/" + SiloEscape(params.shuffleId)
        if action = "shuffle_stop" then method = "DELETE"
        if action = "shuffle_advance" or action = "shuffle_skip"
            if SiloText(params.itemId) = "" then return SiloError("item_required", "Refresh the shuffle first.")
            method = "POST"
            if action = "shuffle_advance" then path = path + "/advance" : body = {from_content_id:params.itemId}
            if action = "shuffle_skip" then path = path + "/skip" : body = {next_content_id:params.itemId}
        end if
    else if action = "settings_capabilities"
        path = "/settings/contract/capabilities"
    else if action = "settings_contract"
        path = "/settings/contract"
    else if action = "audio_pref_set"
        if SiloText(params.seriesId) = "" or not SiloObject(params.preference) then return SiloError("invalid_request", "Audio preference is unavailable.")
        if not SiloAudioPreferenceOrdinal(params.preference.audio_track_index) then return SiloError("invalid_request", "Audio preference is unavailable.")
        method = "PUT"
        path = "/audio-prefs/" + SiloEscape(params.seriesId)
        body = params.preference
    else if action = "settings_effective" or action = "settings_write" or action = "settings_reset"
        allowedKeys = ["playback.auto_skip_intro", "playback.auto_skip_recap", "playback.auto_skip_credits", "playback.intro_skip_mode", "playback.preferred_quality", "playback.subtitle_mode", "playback.subtitle_language", "playback.show_forced_subtitles", "playback.auto_play_next", "playback.next_up_prompt_seconds"]
        if action = "settings_effective"
            if not SiloArray(params.keys) then return SiloError("settings_keys_required", "Settings are unavailable.")
            if params.keys.Count() < 1 or params.keys.Count() > 10 then return SiloError("settings_keys_required", "Settings are unavailable.")
            path = "/settings/values/effective?"
            for each key in params.keys
                if not SiloContains(allowedKeys, key) then return SiloError("settings_key_invalid", "Settings are unavailable.")
                path = path + "keys=" + SiloEscape(key) + "&"
            end for
            path = Left(path, Len(path) - 1)
        else
            if not SiloContains(allowedKeys, SiloText(params.key)) or not SiloContains(["profile", "profile_device", "profile_client"], SiloText(params.scope)) then return SiloError("settings_scope_required", "Select a settings scope.")
            path = "/settings/values/" + SiloEscape(params.key) + "?scope=" + SiloEscape(params.scope)
            if action = "settings_reset"
                for each field in params
                    if field <> "key" and field <> "scope" then return SiloError("invalid_request", "Select one setting to inherit.")
                end for
                method = "DELETE"
            else
                if not params.DoesExist("value") then return SiloError("settings_value_required", "Choose a setting value.")
                method = "PUT"
                body = {value: params.value}
            end if
        end if
    else if action = "device_capability"
        path = "/auth/device/capability"
    else if action = "device_start"
        method = "POST"
        path = "/auth/device/start"
        body = {client_purpose: "device_login", device_name: "Silo (" + SiloText(session.model) + ")", device_platform: "roku", temporary: false}
    else if action = "device_poll"
        if SiloText(params.deviceCode) = "" then return SiloError("device_code_required", "Start sign in again.")
        method = "POST"
        path = "/auth/device/poll"
        body = {device_code: SiloText(params.deviceCode)}
    else if action = "refresh"
        if SiloText(session.refreshToken) = "" then return SiloError("auth_required", "Sign in to continue.")
        method = "POST"
        path = "/auth/refresh"
        body = {refresh_token: SiloText(session.refreshToken)}
    else if action = "profiles"
        path = "/profiles"
    else if action = "profile_verify"
        if SiloText(params.profileId) = "" or SiloText(params.pin) = "" then return SiloError("profile_pin_required", "Enter this profile's PIN.")
        method = "POST"
        path = "/profiles/" + SiloEscape(SiloText(params.profileId)) + "/verify-pin"
        body = {pin: SiloText(params.pin)}
    else if action = "home"
        path = "/home/sections"
    else if action = "home_dismiss"
        if SiloText(params.itemId) = "" then return SiloError("item_required", "Select an item to continue.")
        surface = SiloText(params.surface)
        body = {}
        if surface = "continue_watching"
            if SiloText(params.progressUpdatedAt) = "" then return SiloError("progress_required", "Refresh this card before hiding it.")
            body.progress_updated_at = SiloText(params.progressUpdatedAt)
        else if surface = "next_up"
            if SiloText(params.seriesId) = "" then return SiloError("item_required", "Refresh this card before hiding it.")
            body.series_id = SiloText(params.seriesId)
        else
            return SiloError("unsupported_surface", "This row cannot be hidden.")
        end if
        method = "PUT"
        path = "/home/dismissals/" + surface + "/" + SiloEscape(SiloText(params.itemId))
    else if action = "collection_capabilities"
        path = "/collections/capabilities"
    else if action = "collection_create"
        name = SiloText(params.name).Trim()
        if name = "" or Len(name) > 100 then return SiloError("invalid_name", "Enter a collection name of up to 100 characters.")
        method = "POST"
        path = "/collections"
        body = {name:name,collection_type:"manual",is_shared:false}
    else if action = "collection_choices"
        if SiloText(params.itemId) = "" then return SiloError("item_required", "Select an item to continue.")
        path = "/collections?contains_item=" + SiloEscape(SiloText(params.itemId))
    else if action = "collection_add" or action = "collection_remove"
        if SiloText(params.itemId) = "" or SiloText(params.collectionId) = "" then return SiloError("item_required", "Select a collection and item to continue.")
        method = "DELETE"
        if action = "collection_add" then method = "PUT" : body = {position:0}
        path = "/collections/" + SiloEscape(SiloText(params.collectionId)) + "/items/" + SiloEscape(SiloText(params.itemId))
    else if action = "collections"
        path = "/collections"
    else if action = "server_collections"
        path = "/collections/server"
    else if action = "people"
        path = "/catalog/people?q=" + SiloEscape(Left(SiloText(params.query), 200)) + "&limit=36&media_scope=video"
    else if SiloContains(["favorite_add", "favorite_remove", "watchlist_add", "watchlist_remove"], action)
        if SiloText(params.itemId) = "" then return SiloError("item_required", "Select an item to continue.")
        method = "PUT"
        if Instr(1, action, "remove") > 0 then method = "DELETE"
        path = "/favorites/"
        if Left(action, 9) = "watchlist" then path = "/watchlist/"
        path = path + SiloEscape(SiloText(params.itemId))
    else if action = "home_section_items"
        sectionId = SiloText(params.sectionId)
        if sectionId = "" or Len(sectionId) > 256 then return SiloError("section_required", "Select a section to continue.")
        path = "/home/sections/" + SiloEscape(sectionId) + "/items"
    else if action = "libraries"
        path = "/user/libraries"
    else if action = "catalog_genres"
        source = SiloText(params.source)
        if source = "" then source = "query"
        if not SiloContains(["query","person","library_collection","user_collection","favorites","watchlist","history"],source) then return SiloError("unsupported_scope","Genres are unavailable for this scope.")
        if source = "person" and SiloText(params.personId) = "" then return SiloError("invalid_scope","Select a person.")
        if (source = "library_collection" or source = "user_collection") and SiloText(params.collectionId) = "" then return SiloError("invalid_scope","Select a collection.")
        if source = "library_collection" and SiloText(params.libraryId) = "" then return SiloError("invalid_scope","Select a library.")
        if SiloText(params.sectionId) <> "" then return SiloError("unsupported_scope","Section genres are unavailable.")
        path = "/catalog/filters?skip_technical=true&source=" + SiloEscape(source)
        fields = {libraryId:"library_id",collectionId:"collection_id",personId:"person_id",sectionId:"section_id",scope:"scope",type:"type"}
        for each key in params
            if key <> "source" and not fields.DoesExist(key) then return SiloError("invalid_scope","Genres are unavailable for this scope.")
        end for
        for each key in fields
            if SiloText(params[key]) <> "" then path = path + "&" + fields[key] + "=" + SiloEscape(SiloText(params[key]))
        end for
    else if action = "catalog_query" or action = "person_items"
        method = "POST"
        path = "/catalog/query"
        limit = Int(SiloNumber(params.limit, 50))
        if limit < 1 then limit = 1
        if limit > 100 then limit = 100
        body = {limit: limit}
        fields = {namePrefix: "name_prefix", libraryId: "library_id", query: "q", cursor: "cursor", sort: "sort", order: "order", type: "type", sectionId: "section_id", scope: "scope", source: "source", collectionId: "collection_id"}
        for each key in fields
            if SiloText(params[key]) <> "" then body[fields[key]] = SiloText(params[key])
        end for
        rules = []
        if SiloText(params.genre) <> "" then rules.Push({field:"genre",op:"contains",value:Left(SiloText(params.genre),100)})
        if params.watched = "watched" or params.watched = "unwatched" then rules.Push({field:"watched",op:"eq",value:params.watched = "watched"})
        if params.DoesExist("formatFilter") and params.formatFilter <> invalid and params.formatFilter <> ""
            formatFilter = SiloText(params.formatFilter)
            if formatFilter = "4k" or formatFilter = "4k_hdr" then rules.Push({field:"resolution",op:"is",value:"2160p"})
            if formatFilter = "hdr" or formatFilter = "4k_hdr" then rules.Push({field:"hdr",op:"is",value:true})
            if formatFilter = "dv" then rules.Push({field:"dolby_vision",op:"is",value:true})
            if not SiloContains(["4k","hdr","4k_hdr","dv"],formatFilter) then return SiloError("invalid_format_filter", "Choose a supported video format.")
        end if
        decade = SiloNumber(params.decade,0)
        if decade > 0
            if decade < 1900 or decade > 2090 or decade / 10 <> Int(decade / 10) then return SiloError("invalid_filter", "Choose a release decade.")
            rules.Push({field:"year",op:"between",value:[decade,decade + 9]})
        end if
        minimumRating = SiloNumber(params.minimumRating,0)
        if minimumRating > 0
            if minimumRating > 10 then return SiloError("invalid_filter", "Choose an IMDb rating.")
            rules.Push({field:"rating_imdb",op:"gte",value:minimumRating})
        end if
        if rules.Count() > 0 then body.groups = [{match:"all",rules:rules}]
        if action = "person_items"
            if SiloText(params.personId) = "" then return SiloError("person_required", "Select a person to continue.")
            body.source = "person"
            body.person_id = SiloText(params.personId)
        end if
    else if action = "detail"
        if SiloText(params.itemId) = "" then return SiloError("item_required", "Select an item to continue.")
        path = "/catalog/items/" + SiloEscape(SiloText(params.itemId))
    else if action = "mark_watched" or action = "mark_unwatched"
        itemId = SiloText(params.itemId)
        if not CreateObject("roRegex", "^[A-Za-z0-9_.:-]{1,256}$", "").IsMatch(itemId) then return SiloError("item_required", "Select an item to continue.")
        method = "POST"
        if action = "mark_unwatched" then method = "DELETE"
        path = "/watched/" + SiloEscape(itemId)
    else if action = "markers" or action = "similar"
        if SiloText(params.itemId) = "" then return SiloError("item_required", "Select an item to continue.")
        path = "/markers/items/" + SiloEscape(SiloText(params.itemId))
        if action = "similar"
            limit = Int(SiloNumber(params.limit, 20))
            if limit < 1 then limit = 1
            if limit > 50 then limit = 50
            path = "/recommendations/similar/" + SiloEscape(SiloText(params.itemId)) + "?limit=" + limit.ToStr()
        end if
    else if action = "person"
        if SiloText(params.personId) = "" then return SiloError("person_required", "Select a person to continue.")
        path = "/catalog/people/" + SiloEscape(SiloText(params.personId))
    else if action = "seasons" or action = "episodes"
        if SiloText(params.seriesId) = "" then return SiloError("item_required", "Select a series to continue.")
        path = "/catalog/series/" + SiloEscape(SiloText(params.seriesId)) + "/seasons"
        if action = "episodes"
            season = SiloNumber(params.seasonNumber, -1)
            if season < 0 or season <> Int(season) then return SiloError("season_required", "Select a season to continue.")
            path = path + "/" + Int(season).ToStr() + "/episodes"
        end if
    else if action = "playback_capabilities"
        path = "/playback/capabilities"
    else if action = "playback_error_report"
        built = SiloPlaybackErrorBody(params)
        if not built.ok then return built
        model = SiloText(session.model)
        if CreateObject("roRegex","^[A-Za-z0-9_-]{1,16}$","").IsMatch(model) then built.body.diagnostics["device_model"] = model
        method = "POST"
        path = "/playback/route-events"
        body = built.body
    else if action = "playback_start"
        built = SiloStartBody(session, params)
        if not built.ok then return built
        method = "POST"
        path = "/playback/start"
        body = built.body
    else if action = "playback_replan"
        if not SiloReplanOpaque(params.sessionId,256,1) or not SiloReplanBodyValid(params.body) then return SiloError("invalid_request", "Playback change is unavailable.")
        method = "POST"
        path = "/playback/" + SiloEscape(SiloText(params.sessionId)) + "/replan"
        body = params.body
    else if action = "playback_stop" or action = "playback_progress"
        if SiloText(params.sessionId) = "" or SiloText(params.installationId) = "" then return SiloError("playback_identity_required", "Playback session is unavailable.")
        path = "/playback/" + SiloEscape(SiloText(params.sessionId))
        body = {installation_id: SiloText(params.installationId)}
        if action = "playback_stop"
            if SiloText(params.stopId) = "" then return SiloError("playback_identity_required", "Playback session is unavailable.")
            method = "DELETE"
            body.stop_id = SiloText(params.stopId)
        else
            if params.positionMs = invalid or params.sequence = invalid or params.isPaused = invalid then return SiloError("progress_required", "Playback progress is unavailable.")
            method = "POST"
            path = path + "/progress"
        end if
        persistProgress = true
        if action = "playback_stop" and params.DoesExist("persistProgress") then persistProgress = params.persistProgress <> false
        if params.positionMs <> invalid and persistProgress then body.position = SiloNumber(params.positionMs, 0) / 1000.0
        if persistProgress
            if params.sequence <> invalid then body.sequence = SiloNumber(params.sequence, 0)
            if type(params.isPaused) = "roBoolean" or type(params.isPaused) = "Boolean" then body.is_paused = params.isPaused
        end if
    end if
    ' Ask for TV-sized signed artwork instead of originals (up to 3840 px).
    if SiloContains(["home", "detail", "seasons", "episodes", "catalog_query", "person_items"], action)
        separator = "?"
        if Instr(1, path, "?") > 0 then separator = "&"
        path = path + separator + "image_size=medium"
    end if
    bodyText = ""
    if body <> invalid
        headers["Content-Type"] = "application/json"
        bodyText = FormatJson(body)
    end if
    request = {ok: true, method: method, url: base + "/api/v2" + path, headers: headers, body: bodyText, errorBodyLimit: 8192, enableGzip: true}
    if action = "playback_start" or action = "playback_replan" then request["siloPlaybackPreparation"] = true
    return request
end function

' A compact route event contains fixed codes and opaque attempt identities only.
function SiloPlaybackErrorBody(params as Object) as Object
    for each key in params
        if not SiloContains(["report","supportCode","errorCode","reason","eventId"],key) then return SiloError("invalid_request","Error reporting is unavailable.")
    end for
    report = params.report
    if not SiloObject(report) then return SiloError("invalid_request","Error reporting is unavailable.")
    for each key in report
        if not SiloContains(["installationId","playbackAttemptId","sessionId"],key) then return SiloError("invalid_request","Error reporting is unavailable.")
    end for
    if not SiloReplanOpaque(report.installationId,256,1) or not SiloReplanOpaque(report.playbackAttemptId,128,8) then return SiloError("invalid_request","Error reporting is unavailable.")
    if report.DoesExist("sessionId")
        if not SiloReplanOpaque(report.sessionId,128,1) then return SiloError("invalid_request","Error reporting is unavailable.")
    end if
    codes = ["1001","1002","1003","1004","2001","2002","2003","2004","2005","2006","2007","2008","2009","2010","2011","2012","2013","2014","2015","2016","3001","3002","3003","3004"]
    if not SiloContains(codes,SiloText(params.supportCode)) then return SiloError("invalid_request","Error reporting is unavailable.")
    eventId = SiloText(params.eventId)
    if not CreateObject("roRegex","^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$","").IsMatch(eventId) or eventId = "00000000-0000-0000-0000-000000000000" then return SiloError("invalid_request","Error reporting is unavailable.")
    diagnostics = {error_code:SiloText(params.supportCode)}
    name = SiloText(params.errorCode)
    if SiloContains(["playback_terminal","unsupported_protocol","unsupported_playback_protocol","unsupported_stream","invalid_response","invalid_original_receipt","no_new_playback_route","decoder_failure","network_timeout","task_failed","server_error","native_playback_failed"],name) or CreateObject("roRegex","^roku_native_-?[0-9]{1,4}$","").IsMatch(name) then diagnostics["error_code_name"] = name
    reason = SiloPlaybackTerminalReason(params.reason)
    if reason <> "" then diagnostics["reason"] = reason
    body = {installation_id:report.installationId,event_id:eventId,protocol_version:3,playback_attempt_id:report.playbackAttemptId,event:"terminal",diagnostics:diagnostics}
    if report.DoesExist("sessionId")
        body["session_id"] = report.sessionId
        body.event = "plan_failed"
    end if
    if reason <> "" then body["failure_classification"] = reason
    return {ok:true,body:body}
end function

' Keep this transport ingress standalone for Artwork/Episode Task consumers.
function SiloReplanOpaque(value as Dynamic, maximum as Integer, minimum as Integer) as Boolean
    text = SiloText(value)
    if Len(text) < minimum or Len(text) > maximum or text = "." or text = ".." or Instr(1,text,"://") > 0 then return false
    return CreateObject("roRegex","^[A-Za-z0-9_.:/-]+$","").IsMatch(text)
end function

function SiloReplanNumber(value as Dynamic, maximum as Double, minimum = 0 as Double, whole = false as Boolean) as Boolean
    number = SiloNumber(value,-1)
    if number <> number or number < minimum or number > maximum then return false
    if whole then return number = Int(number)
    return true
end function

function SiloReplanBodyValid(body as Dynamic) as Boolean
    if not SiloObject(body) then return false
    required = ["installation_id","protocol_version","playback_attempt_id","replan_request_id","failed_plan_id","plan_attempt_id","plan_attempt_key","attempted_plan_keys","attempt_count","quality_preference","position_seconds","metered","selected_tracks","client_capabilities","client_playback_context"]
    allowed = {}
    for each key in required
        if not body.DoesExist(key) then return false
        allowed[key] = true
    end for
    for each key in ["operation","client_features","bandwidth_cap_kbps","bandwidth_estimate_kbps","failure"]
        allowed[key] = true
    end for
    for each key in body
        if not allowed.DoesExist(key) then return false
    end for
    if not SiloReplanOpaque(body.installation_id,256,1) then return false
    for each key in ["playback_attempt_id","replan_request_id","failed_plan_id","plan_attempt_id","plan_attempt_key"]
        if not SiloReplanOpaque(body[key],128,8) then return false
    end for
    if not SiloReplanNumber(body.protocol_version,3,3,true) or not SiloReplanNumber(body.attempt_count,8,1,true) or not SiloReplanNumber(body.position_seconds,604800) then return false
    if body.operation <> "quality_change" and body.operation <> "failure_recovery" and body.operation <> "track_change" and body.operation <> "seek_reanchor" then return false
    if body.operation = "failure_recovery"
        if not SiloObject(body.failure) then return false
        if body.failure.Count() <> 1 then return false
        if not SiloContains(["decoder_failure","buffering_timeout"],SiloText(body.failure.classification)) then return false
    else if body.DoesExist("failure")
        return false
    end if
    if not SiloContains(["original","4k","1080p_high","1080p","720p","480p"],SiloText(body.quality_preference)) then return false
    if type(body.metered) <> "Boolean" and type(body.metered) <> "roBoolean" then return false
    if body.metered <> false then return false
    if not SiloArray(body.attempted_plan_keys) then return false
    if body.attempted_plan_keys.Count() > 16 then return false
    for each key in body.attempted_plan_keys
        if not SiloReplanOpaque(key,128,8) then return false
    end for
    if not SiloObject(body.selected_tracks) then return false
    for each name in body.selected_tracks
        if name <> "audio" and name <> "subtitle" then return false
        track = body.selected_tracks[name]
        if not SiloObject(track) then return false
        if not SiloReplanOpaque(track.id,256,1) then return false
        for each key in track
            if key <> "id" and key <> "index" then return false
        end for
        if track.DoesExist("index")
            if not SiloReplanNumber(track.index,4095,0,true) then return false
        end if
    end for
    caps = body.client_capabilities:context = body.client_playback_context
    if not SiloObject(caps) or not SiloObject(context) then return false
    if not SiloObject(context.device) then return false
    if SiloText(context.device.platform) <> "roku" or context.protocol_version <> 3 then return false
    for each key in ["video_evidence","audio_evidence"]
        if not SiloContains(["exact","platform_attested","declared"],SiloText(caps[key])) then return false
    end for
    for each key in ["codecs_video","codecs_video_hardware","codecs_audio","containers"]
        if not SiloArray(caps[key]) then return false
    end for
    if not SiloObject(context.deliveries) or not SiloObject(context.output) then return false
    if body.DoesExist("client_features")
        if not SiloArray(body.client_features) then return false
        if body.client_features.Count() > 5 then return false
        seenFeatures = {}
        for each feature in body.client_features
            if not SiloContains(["native_hls_mpegts_v1","native_hls_separate_audio_v1","server_dv7_to_dv81_v1","header_authenticated_media_v1","seek_reanchor_v1"],SiloText(feature)) then return false
            if seenFeatures.DoesExist(feature) then return false
            seenFeatures[feature] = true
        end for
    end if
    if body.DoesExist("bandwidth_cap_kbps")
        if not SiloReplanNumber(body.bandwidth_cap_kbps,200000,1,true) then return false
    end if
    if body.DoesExist("bandwidth_estimate_kbps")
        if not SiloReplanNumber(body.bandwidth_estimate_kbps,200000,1,true) then return false
    end if
    if body.operation = "seek_reanchor"
        if not SiloSeekUuid(body.replan_request_id) or not SiloSeekUuid(body.plan_attempt_id) then return false
        if body.attempt_count <> 1 or body.attempted_plan_keys.Count() <> 1 then return false
        if body.attempted_plan_keys[0] <> body.plan_attempt_key then return false
        if SiloSeekFeatures(body.client_features) = invalid then return false
    end if
    return true
end function

function SiloStartBody(session as Object, params as Object) as Object
    caps = params.clientCapabilities
    context = params.clientPlaybackContext
    if not SiloObject(caps) or not SiloObject(context) then return SiloError("capabilities_required", "Device capabilities are unavailable.")
    if not SiloObject(context.device) then return SiloError("invalid_capabilities", "Device capabilities are unavailable.")
    if SiloText(context.device.platform) <> "roku" or context.protocol_version <> 3 then return SiloError("invalid_capabilities", "Device capabilities are unavailable.")
    for each name in ["video_evidence", "audio_evidence"]
        if not SiloContains(["exact", "platform_attested", "declared"], SiloText(caps[name])) then return SiloError("invalid_capabilities", "Device capabilities are unavailable.")
    end for
    for each name in ["codecs_video", "codecs_video_hardware", "codecs_audio", "containers"]
        if not SiloArray(caps[name]) then return SiloError("invalid_capabilities", "Device capabilities are unavailable.")
    end for
    if not SiloObject(context.deliveries) or not SiloObject(context.output) then return SiloError("invalid_capabilities", "Device capabilities are unavailable.")
    if SiloText(params.fileId) = "" or SiloText(params.installationId) = "" or SiloText(params.playbackAttemptId) = "" then return SiloError("playback_identity_required", "Playback session is unavailable.")
    quality = SiloText(params.qualityPreference)
    if quality = "" then quality = "original"
    mediaAuthMode = invalid
    if params.DoesExist("mediaAuthMode")
        if SiloText(params.mediaAuthMode) <> "api_header_v1" then return SiloError("invalid_request", "Playback session is unavailable.")
        mediaAuthMode = params.mediaAuthMode
    end if
    features = SiloClientPlaybackFeatures(context,mediaAuthMode)
    if features = invalid then return SiloError("invalid_capabilities", "Device capabilities are unavailable.")
    if params.seekReanchorNegotiated = true then features.Push("seek_reanchor_v1")
    body = {installation_id: SiloText(params.installationId), protocol_version: 3, client_features: features, file_id: SiloText(params.fileId), profile_id: SiloText(session.profileId), playback_attempt_id: SiloText(params.playbackAttemptId), quality_preference: quality, subtitle_fidelity_preference: "preserve", metered: false, client_capabilities: caps, client_playback_context: context, progress_persistence: "server", allow_alternate_versions: false}
    body.allow_alternate_versions = params.allowAlternateVersions = true
    ' No Android engine features are implemented by the Roku native player.
    if params.startPositionMs <> invalid then body.start_position = SiloNumber(params.startPositionMs, 0) / 1000.0
    if params.progressPersistence = "client"
        if params.startPositionMs = invalid then return SiloError("invalid_request", "Audio start position is unavailable.")
        body.progress_persistence = "client"
    end if
    if params.audioTrackIndex <> invalid then body.audio_track_index = Int(SiloNumber(params.audioTrackIndex, 0))
    if params.subtitleTrackIndex <> invalid then body.subtitle_track_index = Int(SiloNumber(params.subtitleTrackIndex, 0))
    if SiloText(params.audioTrackId) <> "" then body.audio_track_id = SiloText(params.audioTrackId)
    if SiloText(params.subtitleTrackId) <> "" then body.subtitle_track_id = SiloText(params.subtitleTrackId)
    if params.bandwidthCapKbps <> invalid then body.bandwidth_cap_kbps = Int(SiloNumber(params.bandwidthCapKbps, 0))
    return {ok: true, body: body}
end function

function DecodeSiloResponse(action as String, body as String, params as Object) as Object
    if Left(action,8) = "service_" then return DecodeSiloServicesResponse(action,body,params)
    if SiloContains(["home_dismiss", "mark_watched", "mark_unwatched", "favorite_add", "favorite_remove", "watchlist_add", "watchlist_remove"], action) then return {ok:true,data:{}}
    if action = "collection_add" or action = "collection_remove"
        if params.statusCode <> 204 or body <> "" then return SiloError("invalid_response", "Collection change was not confirmed.")
        return {ok:true,data:{}}
    end if
    if action = "audio_pref_set" then return {ok:params.statusCode=204 and body="",data:{}}
    if action = "home_sections_save" or action = "home_sections_reset"
        if params.statusCode <> 204 or body <> "" then return SiloError("invalid_response","Home layout save was not confirmed.")
        return {ok:true,data:{acknowledged:true}}
    end if
    if action = "settings_reset"
        if params.statusCode <> 204 or body <> "" then return SiloError("invalid_response", "Override removal was not confirmed.")
        return {ok:true,data:{key:params.key,scope:params.scope,reset:true}}
    end if
    decoded = ParseJson(body)
    if not SiloObject(decoded) then return SiloError("invalid_response", "The server response could not be read.")
    if action = "home_sections_list" or action = "home_sections_settings"
        if not SiloArray(decoded.items) then return SiloError("invalid_response","Home rows could not be read.")
        for each entry in decoded.items
            if not SiloObject(entry) then return SiloError("invalid_response","Home rows could not be read.")
            if action = "home_sections_settings"
                if SiloText(entry.id) = "" then return SiloError("invalid_response","Home rows could not be read.")
            end if
        end for
        return {ok:true,data:{items:decoded.items}}
    end if
    if action = "collection_capabilities" then return {ok:true,data:{supported:decoded.state = "available" and decoded.allowed <> false and decoded.contains_item = true,canCreate:decoded.state = "available" and decoded.allowed = true}}
    if action = "collection_create"
        if params.statusCode <> 201 or SiloText(decoded.id) = "" or decoded.creator_profile_id <> params.profileId or decoded.collection_type <> "manual" or decoded.is_shared <> false then return SiloError("invalid_response", "Collection creation was not confirmed.")
        return {ok:true,data:{collectionId:SiloText(decoded.id)}}
    end if
    if action = "collection_choices"
        if not SiloArray(decoded.items) then return SiloError("invalid_response", "Collections could not be read.")
        entries = []
        for each entry in decoded.items
            if entries.Count() >= 60 then exit for
            if SiloObject(entry)
                if SiloText(entry.id) <> "" and (entry.contains = true or entry.contains = false)
                    entries.Push({id:SiloText(entry.id),title:Left(SiloText(entry.name),120),collectionType:SiloText(entry.collection_type),creatorProfileId:SiloText(entry.creator_profile_id),contains:entry.contains})
                end if
            end if
        end for
        return {ok:true,data:{entries:entries}}
    end if
    if SiloNumber(decoded.status, 0) >= 400 and SiloText(decoded.type) <> ""
        segments = SiloText(decoded.type).Tokenize("/")
        code = "silo_problem"
        if segments.Count() > 0 then code = segments[segments.Count() - 1]
        allowedCodes = ["profile_locked", "profile_required", "profile_pin_required", "unauthorized", "forbidden", "validation_failed", "device_login_disabled", "not_found", "rate_limited", "plan_in_progress", "adaptation_capacity_busy"]
        if not SiloContains(allowedCodes, code) then code = "silo_problem"
        return SiloError(code, "The server could not complete this request.")
    end if
    if action = "catalog_identity_capabilities"
        maximum = SiloNumber(decoded.max_identity_batch,0)
        validMaximum = maximum>0 and maximum=Int(maximum)
        if maximum>48 then maximum=48
        return {ok:true,data:{identityResolution:decoded.state="available" and decoded.identity_resolution=true and validMaximum,maxIdentityBatch:maximum}}
    end if
    if action = "catalog_resolve"
        if not SiloIdentitySeeds(params.seeds) or not SiloArray(decoded.matches) or decoded.matches.Count()>100 then return SiloError("invalid_response","Catalog lookup is unavailable.")
        if type(decoded.complete) <> "Boolean" and type(decoded.complete) <> "roBoolean" then return SiloError("invalid_response","Catalog lookup is unavailable.")
        cursor = SiloText(decoded.next_cursor)
        if Len(cursor)>8192 or (not decoded.complete and cursor="") then return SiloError("invalid_response","Catalog lookup is unavailable.")
        matches = []
        seen = {}
        for each raw in decoded.matches
            if not SiloObject(raw) then return SiloError("invalid_response","Catalog lookup is unavailable.")
            index = raw.seed
            if type(index) <> "Integer" and type(index) <> "roInt" then return SiloError("invalid_response","Catalog lookup is unavailable.")
            if index<0 or index>=params.seeds.Count() then return SiloError("invalid_response","Catalog lookup is unavailable.")
            mapped = SiloItem(raw.item)
            if not mapped.ok then return mapped
            if mapped.item.type <> params.seeds[index].type then return SiloError("invalid_response","Catalog lookup changed type.")
            for each pair in [["tmdb_id","tmdb"],["imdb_id","imdb"],["tvdb_id","tvdb"]]
                stated = SiloText(raw.item[pair[0]])
                expected = SiloText(params.seeds[index][pair[0]])
                if stated <> "" and expected <> "" and SiloExternalId(stated,pair[1]) <> expected then return SiloError("invalid_response","Catalog lookup changed identity.")
            end for
            if seen.DoesExist(mapped.item.itemId) then return SiloError("invalid_response","Catalog lookup repeated identity.")
            seen[mapped.item.itemId] = true
            matches.Push({seed:index,item:mapped.item})
        end for
        return {ok:true,data:{matches:matches,complete:decoded.complete,nextCursor:cursor}}
    end if
    if action = "catalog_genres"
        if not SiloArray(decoded.genres) then return SiloError("invalid_response","Genres could not be read.")
        if decoded.genres.Count() > 1000 then return SiloError("invalid_response","Too many genres.")
        genres = []
        seen = {}
        for each value in decoded.genres
            label = SiloText(value).Trim()
            if label = "" or Len(label) > 100 then return SiloError("invalid_response","Genres could not be read.")
            for index = 1 to Len(label)
                code = Asc(Mid(label,index,1))
                if code < 32 or code = 127 then return SiloError("invalid_response","Genres could not be read.")
            end for
            key = LCase(label)
            if not seen.DoesExist(key) then genres.Push(label) : seen[key] = true
        end for
        return {ok:true,data:{genres:genres}}
    end if
    if action = "compat_handoff_approve"
        if params.statusCode <> 200 or decoded.status <> "approved" then return SiloError("invalid_response","Compatibility approval was not confirmed.")
        return {ok:true,data:{approved:true}}
    end if
    if action = "compat_connect_info" then return SiloCompatConnectInfo(decoded,params)
    if action = "shuffle_capabilities"
        if not SiloArray(decoded.scope_kinds) or (type(decoded.allowed) <> "Boolean" and type(decoded.allowed) <> "roBoolean") then return SiloError("invalid_response", "Shuffle is unavailable.")
        return {ok:true,data:{allowed:decoded.allowed=true and decoded.state="available",kinds:decoded.scope_kinds}}
    else if action = "shuffle_start" or action = "shuffle_status" or action = "shuffle_skip" or action = "shuffle_advance"
        if SiloText(decoded.id) = "" or not SiloObject(decoded.scope) then return SiloError("invalid_response", "Shuffle is unavailable.")
        if action = "shuffle_start"
            if decoded.scope.kind <> params.kind or decoded.scope.id <> params.scopeId then return SiloError("invalid_response", "Shuffle changed scope.")
        else
            if decoded.id <> params.shuffleId then return SiloError("invalid_response", "Shuffle changed identity.")
        end if
        current = SiloItem(decoded.current)
        nextItem = SiloItem(decoded.next)
        if not current.ok or not nextItem.ok then return SiloError("invalid_response", "Shuffle has no playable picks.")
        if not SiloContains(["movie","episode"],current.item.type) or not SiloContains(["movie","episode"],nextItem.item.type) then return SiloError("invalid_response", "Shuffle has no playable picks.")
        return {ok:true,data:{shuffleId:decoded.id,scope:decoded.scope,current:current.item,next:nextItem.item}}
    else if action = "settings_capabilities" or action = "settings_contract" or action = "settings_effective" or action = "settings_write"
        if action = "settings_capabilities"
            if decoded.api_version <> 1 or decoded.allowed <> true or decoded.state <> "available" then return SiloError("settings_unavailable", "Using local settings.")
            if SiloNumber(decoded.manifest_revision, 0) < 1 then return SiloError("invalid_response", "Using local settings.")
        else if action = "settings_contract"
            if SiloNumber(decoded.revision, 0) < 1 then return SiloError("invalid_response", "Using local settings.")
            if not SiloArray(decoded.definitions) then return SiloError("invalid_response", "Using local settings.")
        else if action = "settings_effective"
            if SiloNumber(decoded.revision, 0) < 1 then return SiloError("invalid_response", "Using local settings.")
            if not SiloArray(decoded.items) then return SiloError("invalid_response", "Using local settings.")
            if decoded.items.Count() > 10 then return SiloError("invalid_response", "Using local settings.")
        else
            if decoded.key <> params.key or decoded.scope <> params.scope or not decoded.DoesExist("value") then return SiloError("invalid_response", "Setting was not confirmed.")
            if decoded.value <> params.value or SiloNumber(decoded.revision, 0) < 1 then return SiloError("invalid_response", "Setting was not confirmed.")
        end if
        return {ok:true, data:decoded}
    else if action = "device_capability" or action = "playback_capabilities"
        if not SiloArray(decoded.protocol_versions) or SiloText(decoded.state) = "" then return SiloError("invalid_response", "The server response could not be read.")
        ' Validate wire types before comparing a version with an integer.
        ' A malformed capability document must not crash the worker.
        for each version in decoded.protocol_versions
            kind = type(version)
            if kind <> "Integer" and kind <> "roInt" and kind <> "roInteger" and kind <> "LongInteger" and kind <> "roLongInteger" then return SiloError("invalid_response", "The server response could not be read.")
        end for
        data = {allowed: false, state: SiloText(decoded.state), protocolVersions: decoded.protocol_versions}
        if action = "device_capability"
            ' v2 pairing capability omits/nulls allowed. State and protocol 2
            ' establish device-login support; playback has a separate gate.
            data.allowed = data.state = "available" and SiloContains(decoded.protocol_versions, 2)
        end if
        if action = "playback_capabilities"
            if type(decoded.allowed) <> "Boolean" and type(decoded.allowed) <> "roBoolean" then return SiloError("invalid_response", "The server response could not be read.")
            data.allowed = decoded.allowed
            data["installationId"] = SiloText(decoded.installation_id)
            data.features = SiloList(decoded.features)
            data.deliveries = SiloList(decoded.deliveries)
        end if
        return {ok: true, data: data}
    else if action = "device_start"
        if SiloText(decoded.device_code) = "" or SiloText(decoded.user_code) = "" or SiloText(decoded.verification_uri) = "" then return SiloError("invalid_response", "The server response could not be read.")
        interval = SiloNumber(decoded.interval, 3)
        if interval <= 0 then interval = 3
        return {ok: true, data: {userCode: SiloText(decoded.user_code), matchCode: SiloText(decoded.match_code), verificationUri: SiloText(decoded.verification_uri), verificationUriComplete: SiloText(decoded.verification_uri_complete), expiresInMs: SiloNumber(decoded.expires_in, 0) * 1000, intervalMs: interval * 1000}, session: {deviceCode: SiloText(decoded.device_code)}}
    else if action = "device_poll"
        status = SiloText(decoded.status)
        if status = "pending"
            return {ok: true, data: {status: "pending", pollAfterMs: SiloNumber(decoded.poll_after, 3) * 1000}}
        else if status = "denied" or status = "expired" or status = "consumed"
            if status = "consumed" then status = "expired"
            return {ok: true, data: {status: status}}
        else if status = "approved"
            if not SiloObject(decoded.tokens) then return SiloError("invalid_response", "The server response could not be read.")
            if not SiloObject(decoded.tokens.user) then return SiloError("invalid_response", "The server response could not be read.")
            if SiloText(decoded.tokens.user.id) = "" then return SiloError("invalid_response", "The server response could not be read.")
            result = SiloTokenResult(decoded.tokens)
            if not result.ok then return result
            result.data.status = "approved"
            result.session["profileId"] = SiloText(decoded.profile_id)
            result.session["profileToken"] = SiloText(decoded.profile_token)
            if SiloObject(decoded.tokens.user)
                result.data["accountId"] = SiloText(decoded.tokens.user.id)
                result.data["accountName"] = SiloText(decoded.tokens.user.username)
            end if
            return result
        end if
        return SiloError("invalid_response", "The server response could not be read.")
    else if action = "refresh"
        return SiloTokenResult(decoded)
    else if action = "profile_verify"
        if type(decoded.valid) <> "roBoolean" and type(decoded.valid) <> "Boolean" then return SiloError("invalid_response", "The server response could not be read.")
        if decoded.valid <> true then return {ok: true, data: {valid: false}}
        return {ok: true, data: {valid: true}, session: {profileId: SiloText(params.profileId), profileToken: SiloText(decoded.profile_token)}}
    else if action = "profiles"
        if not SiloArray(decoded.items) then return SiloError("invalid_response", "The server response could not be read.")
        profiles = []
        for each profile in decoded.items
            if not SiloObject(profile) then return SiloError("invalid_response", "The server response could not be read.")
            profiles.Push({profileId: SiloText(profile.id), name: SiloText(profile.name), hasPin: profile.has_pin = true, isChild: profile.is_child = true, isPrimary: profile.is_primary = true})
        end for
        return {ok: true, data: {profiles: profiles}}
    else if action = "home"
        if not SiloArray(decoded.sections) then return SiloError("invalid_response", "The server response could not be read.")
        rows = []
        for each section in decoded.sections
            if not SiloObject(section) then return SiloError("invalid_response", "The server response could not be read.")
            mapped = SiloItems(section.items)
            if not mapped.ok then return mapped
            rows.Push({rowId: SiloText(section.id), sectionType: Left(SiloText(section.section_type), 64), title: SiloText(section.title), items: mapped.items, totalCount: SiloNumber(section.total_count, mapped.items.Count())})
        end for
        return {ok: true, data: {rows: rows}}
    else if action = "collections" or action = "people"
        raw = decoded.items
        if action = "collections" and SiloArray(decoded.collections) then raw = decoded.collections
        if not SiloArray(raw) then return SiloError("invalid_response", "The server response could not be read.")
        entries = []
        inspected = 0
        for each entry in raw
            inspected++
            if inspected > 100 or entries.Count() >= 60 then exit for
            if not SiloObject(entry) then return SiloError("invalid_response", "The server response could not be read.")
            if SiloText(entry.id) <> ""
                mapped = {id:SiloText(entry.id),title:Left(SiloText(entry.name),120)}
                if action = "collections" then mapped.source = "user_collection"
                entries.Push(mapped)
            end if
        end for
        return {ok:true,data:{entries:entries}}
    else if action = "server_collections"
        if not SiloArray(decoded.libraries) then return SiloError("invalid_response", "The server response could not be read.")
        entries = []
        inspected = 0
        for each library in decoded.libraries
            inspected++
            if inspected > 20 or entries.Count() >= 60 then exit for
            if not SiloObject(library) or not SiloArray(library.collections) then return SiloError("invalid_response", "The server response could not be read.")
            libraryId = SiloNumber(library.library_id, 0)
            if libraryId <= 0 or libraryId <> Int(libraryId) then return SiloError("invalid_response", "The server response could not be read.")
            libraryName = Left(SiloText(library.library_name),60)
            inspectedCollections = 0
            for each entry in library.collections
                inspectedCollections++
                if inspectedCollections > 50 or entries.Count() >= 60 then exit for
                if not SiloObject(entry) then return SiloError("invalid_response", "The server response could not be read.")
                id = SiloText(entry.id)
                title = Left(SiloText(entry.title),120)
                if id <> "" and title <> "" then entries.Push({id:id,title:libraryName + " • " + title,source:"library_collection",libraryId:Int(libraryId).ToStr()})
            end for
        end for
        return {ok:true,data:{entries:entries}}
    else if action = "home_section_items"
        mapped = SiloItems(decoded.items)
        if not mapped.ok then return mapped
        return {ok:true,data:{items:mapped.items}}
    else if action = "libraries"
        if not SiloArray(decoded.items) then return SiloError("invalid_response", "The server response could not be read.")
        libraries = []
        for each library in decoded.items
            if not SiloObject(library) then return SiloError("invalid_response", "The server response could not be read.")
            libraries.Push({sourceId: "silo", libraryId: SiloText(library.id), title: SiloText(library.name), type: SiloText(library.type), enabled:library.enabled <> false})
        end for
        return {ok: true, data: {libraries: libraries}}
    else if action = "catalog_query" or action = "seasons" or action = "episodes" or action = "similar" or action = "person_items"
        if action = "seasons" or action = "episodes"
            if not SiloArray(decoded.items) then return SiloError("invalid_response", "The server response could not be read.")
            for each child in decoded.items
                if not SiloObject(child) then return SiloError("invalid_response", "The server response could not be read.")
                child.type = "season"
                if action = "episodes"
                    child.type = "episode"
                end if
                child.series_id = SiloText(params.seriesId)
            end for
        end if
        mapped = SiloItems(decoded.items, action = "episodes")
        if not mapped.ok then return mapped
        nextCursor = ""
        hasMore = false
        if SiloObject(decoded.page)
            nextCursor = SiloText(decoded.page.next_cursor)
            hasMore = decoded.page.has_more = true
        end if
        return {ok: true, data: {items: mapped.items, nextCursor: nextCursor, hasMore: hasMore, total: SiloNumber(decoded.total, mapped.items.Count()), totalExact: decoded.total_exact = true, windowCursor: SiloText(decoded.window_cursor)}}
    else if action = "detail"
        mapped = SiloItem(decoded, true)
        if not mapped.ok then return mapped
        if not SiloArray(decoded.versions) then return SiloError("invalid_response", "The server response could not be read.")
        sharedMarkers = SiloMarkers(decoded, false)
        versions = []
        versionsComplete = decoded.versions.Count() <= 16
        sourceId = SiloText(params.sourceId)
        if sourceId = "" then sourceId = "silo"
        for each version in decoded.versions
            if versions.Count() >= 16 then exit for
            if not SiloObject(version) then return SiloError("invalid_response", "The server response could not be read.")
            fileId = SiloText(version.file_id)
            if fileId = "" then versionsComplete = false
            for each prior in versions
                if prior.versionId = fileId then versionsComplete = false
            end for
            ' Current v2 FileVersion.duration is seconds; bitrate is already kbps.
            versions.Push({sourceId:sourceId,itemId:mapped.item.itemId,versionId:fileId,container:SiloText(version.container),videoCodec:SiloText(version.codec_video),audioCodec:SiloText(version.codec_audio),durationMs:SiloNumber(version.duration,0)*1000#,bitrate:SiloNumber(version.bitrate,0),bitrateKbps:SiloNumber(version.bitrate,0),resolution:SiloText(version.resolution),hdr:version.hdr=true,videoTracks:SiloVideoTracks(version.video_tracks),audioTracks:SiloTracks(version.audio_tracks,true),subtitleTracks:SiloTracks(version.subtitle_tracks),markers:SiloMergeMarkers(SiloMarkers(version,false),sharedMarkers),chapters:SiloVersionChapters(version.chapters)})
        end for
        markers = sharedMarkers
        if versions.Count() > 0 then markers = versions[0].markers
        return {ok: true, data: {item: mapped.item, versions: versions, versionsComplete:versionsComplete, playbackVariants:SiloNativeVariants(decoded.playback_variants), markers: markers, cast: SiloCredits(decoded.cast, true), crew: SiloCredits(decoded.crew, false)}}
    else if action = "markers"
        if SiloText(decoded.file_id) = "" then return SiloError("invalid_response", "The server response could not be read.")
        if decoded.DoesExist("marker_segments")
            if not SiloArray(decoded.marker_segments) then return SiloError("invalid_response", "The server response could not be read.")
        end if
        return {ok: true, data: {itemId: SiloText(params.itemId), versionId: SiloText(decoded.file_id), markers: SiloMarkers(decoded, true)}}
    else if action = "person"
        if SiloText(decoded.id) = "" or SiloText(decoded.name) = "" then return SiloError("invalid_response", "The server response could not be read.")
        ' Provider photos can contain signatures; UI data keeps only identity.
        return {ok: true, data: {person: {sourceId: "silo", personId: SiloText(decoded.id), name: SiloText(decoded.name), thumbKey: "", bio: SiloText(decoded.bio), birthDate: SiloText(decoded.birth_date), deathDate: SiloText(decoded.death_date), birthplace: SiloText(decoded.birthplace), tmdbId: SiloText(decoded.tmdb_id), imdbId: SiloText(decoded.imdb_id), tvdbId: SiloText(decoded.tvdb_id), plexGuid: SiloText(decoded.plex_guid)}}}
    else if action = "playback_start"
        if decoded.protocol_version <> 3 then return SiloError("unsupported_protocol", "This server playback protocol is unavailable.")
        if decoded.outcome <> "plan" and decoded.outcome <> "playable" and decoded.outcome <> "terminal" and decoded.outcome <> "adaptation_unavailable" then return SiloError("invalid_response", "The server response could not be read.")
        return {ok: true, data: {outcome: SiloText(decoded.outcome), protocolVersion: 3, sessionId: SiloText(decoded.session_id)}, playbackDecision: decoded}
    else if action = "playback_error_report"
        if SiloText(decoded.event_id) <> SiloText(params.eventId) or SiloText(decoded.outcome) <> "accepted" then return SiloError("invalid_response","Error report was not acknowledged.")
        return {ok:true,data:{reported:true}}
    else if action = "playback_stop" or action = "playback_progress"
        if SiloText(decoded.outcome) = "" then return SiloError("invalid_response", "The server response could not be read.")
        return {ok: true, data: {outcome: SiloText(decoded.outcome)}}
    end if
    return SiloError("unsupported_action", "This operation is unavailable.")
end function

function SiloTokenResult(tokens as Object) as Object
    if SiloText(tokens.access_token) = "" or SiloText(tokens.refresh_token) = "" then return SiloError("invalid_response", "The server response could not be read.")
    return {ok: true, data: {expiresInMs: SiloNumber(tokens.expires_in, 0) * 1000}, session: {accessToken: SiloText(tokens.access_token), refreshToken: SiloText(tokens.refresh_token), expiresInMs: SiloNumber(tokens.expires_in, 0) * 1000}}
end function

' Account discovery is advisory. The enabled flag describes the running
' listener; restart/password flags never prove a usable authenticated session.
function SiloCompatConnectInfo(decoded as Object, params as Object) as Object
    refused = SiloError("invalid_response", "Compatibility discovery is unavailable.")
    info = decoded.jellyfin
    if not SiloObject(info) then return refused
    if not SiloContains(["Boolean","roBoolean"],type(info.enabled)) then return refused
    pending = false
    if info.DoesExist("pending_restart")
        if not SiloContains(["Boolean","roBoolean"],type(info.pending_restart)) then return refused
        pending = info.pending_restart
    end if
    password = false
    if decoded.DoesExist("account")
        if not SiloObject(decoded.account) then return refused
        if decoded.account.DoesExist("password_login_available")
            if not SiloContains(["Boolean","roBoolean"],type(decoded.account.password_login_available)) then return refused
            password = decoded.account.password_login_available
        end if
    end if
    if not SiloContains(["String","roString"],type(info.public_url)) or not SiloContains(["String","roString"],type(info.server_name)) then return refused
    if Len(info.public_url) > 2048 or Len(info.server_name) > 256 then return refused
    if CreateObject("roRegex","[\x00-\x1f\x7f]","").IsMatch(info.server_name) then return refused
    publicUrl = ""
    if info.public_url <> ""
        native = NormalizeServerUrl(SiloText(params.baseUrl))
        target = NormalizeServerUrl(info.public_url)
        if native.ok <> true or target.ok <> true then return refused
        if Left(native.url,8) = "https://" and Left(target.url,7) = "http://" then return refused
        publicUrl = target.url
    end if
    return {ok:true,data:{enabled:info.enabled,pendingRestart:pending,available:info.enabled and publicUrl<>"",
        publicUrl:publicUrl,serverName:info.server_name,passwordLoginAvailable:password}}
end function

function SiloItems(items as Dynamic, includeExternalIds = false as Boolean) as Object
    if not SiloArray(items) then return SiloError("invalid_response", "The server response could not be read.")
    mapped = []
    for each item in items
        result = SiloItem(item, includeExternalIds)
        if not result.ok then return result
        mapped.Push(result.item)
    end for
    return {ok: true, items: mapped}
end function

function SiloItem(item as Dynamic, includeExternalIds = false as Boolean) as Object
    if not SiloObject(item) then return SiloError("invalid_response", "The server response could not be read.")
    if SiloText(item.content_id) = "" or SiloText(item.title) = "" or SiloText(item.type) = "" then return SiloError("invalid_response", "The server response could not be read.")
    durationMs = SiloNumber(item.duration_seconds, SiloNumber(item.runtime, 0) * 60) * 1000
    resumeMs = SiloNumber(item.position_seconds, 0) * 1000
    watched = false
    if SiloObject(item.user_state) then watched = item.user_state.played = true
    if SiloObject(item.user_data)
        watched = item.user_data.played = true
        resumeMs = SiloNumber(item.user_data.position_seconds, resumeMs / 1000) * 1000
    end if
    normalized = {sourceId: "silo", itemId: SiloText(item.content_id), title: SiloText(item.title), type: SiloText(item.type), summary: SiloText(item.overview), thumbKey: "", backdropKey: "", durationMs: durationMs, resumeMs: resumeMs, progressUpdatedAt:SiloText(item.progress_updated_at), watched: watched, year: SiloNumber(item.year, 0), playItemId: SiloText(item.play_content_id), seriesId: SiloText(item.series_id), seasonNumber: SiloNumber(item.season_number, -1), episodeNumber: SiloNumber(item.episode_number, -1)}
    normalized["genres"] = SiloGenres(item.genres)
    ' Signed artwork URLs are short-lived display data: they live only in
    ' memory on content nodes and are never logged or persisted.
    normalized["art"] = SiloArt(item)
    normalized["badges"] = SiloBadges(item)
    if item.DoesExist("ratings") then normalized["ratings"] = item.ratings
    normalized["seriesTitle"] = SiloText(item.series_title)
    normalized["contentRating"] = Left(SiloText(item.content_rating), 16)
    ' Android d849901c / OpenAPI CatalogItemDetail and Episode define these
    ' fields. CatalogItem summaries and Season do not carry external IDs.
    if includeExternalIds
        normalized["tmdbId"] = SiloExternalId(item.tmdb_id, "tmdb")
        normalized["imdbId"] = SiloExternalId(item.imdb_id, "imdb")
        normalized["tvdbId"] = SiloExternalId(item.tvdb_id, "tvdb")
    end if
    return {ok: true, item: normalized}
end function

function SiloGenres(raw as Dynamic) as Object
    labels = []
    seen = {}
    if not SiloArray(raw) then return labels
    for each value in raw
        label = SiloText(value).Trim()
        if Len(label) > 0 and Len(label) <= 100
            clean = true
            for index = 1 to Len(label)
                code = Asc(Mid(label,index,1))
                if code < 32 or code = 127 then clean = false
            end for
            key = LCase(label)
            if clean and not seen.DoesExist(key)
                labels.Push(label)
                seen[key] = true
                if labels.Count() >= 16 then exit for
            end if
        end if
    end for
    return labels
end function

function SiloArt(item as Object) as Object
    art = {}
    for each name in ["poster", "backdrop", "logo", "still"]
        url = SiloText(item[name + "_url"])
        if Left(url, 8) = "https://" or Left(url, 7) = "http://" or Left(url, 1) = "/" then art[name] = url
    end for
    if type(item.poster_is_episode_still) = "Boolean" or type(item.poster_is_episode_still) = "roBoolean"
        art["posterIsEpisodeStill"] = item.poster_is_episode_still
    end if
    return art
end function

' Display-only quality and rating facts; playback decisions never read these.
function SiloBadges(item as Object) as Object
    badges = {}
    if SiloObject(item.overlay_summary)
        for each name in ["resolution", "hdr", "audio", "audio_channels"]
            value = Left(SiloText(item.overlay_summary[name]), 24)
            if value <> "" then badges[name] = value
        end for
    end if
    if SiloObject(item.overlay_summary)
        codec = Left(SiloText(item.overlay_summary.video_codec),24)
        if codec <> "" then badges["videoCodec"] = codec
    end if
    imdb = SiloNumber(item.rating_imdb, -1)
    if imdb >= 0 and imdb <= 10 then badges["imdb"] = imdb
    tmdb = SiloNumber(item.rating_tmdb, -1)
    if tmdb >= 0 and tmdb <= 10 then badges["tmdb"] = tmdb
    critic = SiloNumber(item.rating_rt_critic, -1)
    if critic >= 0 and critic <= 100 then badges["rtCritic"] = critic
    audience = SiloNumber(item.rating_rt_audience, -1)
    if audience >= 0 and audience <= 100 then badges["rtAudience"] = audience
    return badges
end function

function SiloExternalId(value as Dynamic, namespace as String) as String
    text = SiloText(value)
    if namespace = "imdb"
        text = LCase(text)
        if not CreateObject("roRegex", "^tt[0-9]{1,12}$", "").IsMatch(text) then return ""
        if Val(Mid(text, 3)) <= 0 then return ""
        return text
    end if
    if namespace <> "tmdb" and namespace <> "tvdb" then return ""
    if not CreateObject("roRegex", "^[0-9]{1,12}$", "").IsMatch(text) then return ""
    while Len(text) > 1 and Left(text, 1) = "0"
        text = Mid(text, 2)
    end while
    if text = "0" then return ""
    return text
end function

function SiloTracks(tracks as Dynamic, preserveSourceIdentity = false as Boolean) as Object
    normalized = []
    ordinal = 0
    for each track in SiloList(tracks)
        if SiloObject(track)
            index = SiloNumber(track.index, ordinal)
            title = SiloText(track.title)
            if title = "" then title = SiloText(track.embedded_title)
            row = {id: Int(index).ToStr(), index: Int(index), title: title, codec: SiloText(track.codec), language: SiloText(track.language), channels: SiloNumber(track.channels, 0), isDefault: track.default = true, forced: track.forced = true, external: track.external = true, hearingImpaired: track.hearing_impaired = true}
            if preserveSourceIdentity
                ' Official v2 audio has no wire index; V3 selectors use the
                ' complete audio-array position. Keep both conventions apart.
                row["preferenceSignature"] = {language:SiloText(track.language).Trim(),title:SiloText(track.title).Trim(),embedded_title:SiloText(track.embedded_title).Trim(),codec:SiloText(track.codec).Trim(),layout:SiloText(track.layout).Trim(),channels:SiloNumber(track.channels,0)}
                row["sourceOrdinal"] = ordinal
                row["wireIndexPresent"] = track.DoesExist("index")
                if row.wireIndexPresent then row["wireIndex"] = SiloNumber(track.index,-1)
                row.layout = Left(SiloText(track.layout),32)
            end if
            normalized.Push(row)
        end if
        ordinal = ordinal + 1
    end for
    return normalized
end function

' Detail/file markers use start/end; the standalone endpoint uses source seconds.
function SiloMarkers(source as Object, secondsFields as Boolean) as Object
    markers = []
    kinds = ["intro", "credits", "recap", "preview"]
    if secondsFields and SiloArray(source.marker_segments)
        for each occurrence in source.marker_segments
            if SiloObject(occurrence)
                kind = SiloText(occurrence.kind)
                if SiloContains(kinds, kind)
                    marker = SiloMarker(occurrence, kind, true)
                    if marker <> invalid then markers.Push(marker)
                end if
            end if
        end for
    else
        for each kind in kinds
            marker = SiloMarker(source[kind], kind, secondsFields)
            if marker <> invalid then markers.Push(marker)
        end for
    end if
    return SiloSortMarkers(markers)
end function

function SiloMarker(segment as Dynamic, kind as String, secondsFields as Boolean) as Dynamic
    if not SiloObject(segment) then return invalid
    startSeconds = SiloNumber(segment.start, -1)
    endSeconds = SiloNumber(segment.end, -1)
    if secondsFields
        startSeconds = SiloNumber(segment.start_seconds, -1)
        endSeconds = SiloNumber(segment.end_seconds, -1)
    end if
    if startSeconds < 0 or endSeconds <= startSeconds then return invalid
    return {kind: kind, startMs: startSeconds * 1000, endMs: endSeconds * 1000}
end function

function SiloMergeMarkers(primary as Object, fallback as Object) as Object
    markers = []
    kinds = []
    for each marker in primary
        markers.Push(marker)
        kinds.Push(marker.kind)
    end for
    for each marker in fallback
        if not SiloContains(kinds, marker.kind) then markers.Push(marker)
    end for
    return SiloSortMarkers(markers)
end function

function SiloSortMarkers(markers as Object) as Object
    if markers.Count() < 2 then return markers
    for index = 1 to markers.Count() - 1
        marker = markers[index]
        position = index
        while position > 0
            if markers[position - 1].startMs <= marker.startMs then exit while
            markers[position] = markers[position - 1]
            position = position - 1
        end while
        markers[position] = marker
    end for
    return markers
end function

function SiloCredits(credits as Dynamic, cast as Boolean) as Object
    normalized = []
    for each credit in SiloList(credits)
        if SiloObject(credit)
            if SiloText(credit.name) <> ""
                role = SiloText(credit.job)
                if cast then role = SiloText(credit.character)
                normalized.Push({sourceId: "silo", personId: SiloText(credit.person_id), name: SiloText(credit.name), role: role, thumbKey: "", order: SiloNumber(credit.order, normalized.Count()), tmdbId: SiloText(credit.tmdb_id), imdbId: SiloText(credit.imdb_id), tvdbId: SiloText(credit.tvdb_id), plexGuid: SiloText(credit.plex_guid)})
            end if
        end if
    end for
    return normalized
end function

' New format recipes are optional. Older capability documents retain the
' existing native-only path; media-header authentication is a separate feature.
function SiloNegotiatedNativeFeatures(serverFeatures as Dynamic, allowDolbyVision as Boolean) as Object
    features = []
    if not SiloArray(serverFeatures) then return features
    for each name in ["hls_copy_mpegts_v1", "native_hls_mpegts_v1", "native_hls_separate_audio_v1"]
        if SiloContains(serverFeatures,name) then features.Push(name)
    end for
    if allowDolbyVision and SiloContains(features,"native_hls_separate_audio_v1")
        if SiloContains(serverFeatures,"server_dv7_to_dv81_v1") then features.Push("server_dv7_to_dv81_v1")
    end if
    return features
end function

function SiloNativeDeliveryFeatures(context as Dynamic) as Object
    if not SiloObject(context) or not SiloObject(context.deliveries) then return []
    hls = context.deliveries.hls
    if not SiloObject(hls) then return []
    if hls.enabled <> true or hls.supported_on_device <> true then return []
    return SiloList(hls.features)
end function

function SiloClientNativeFeatures(context as Dynamic) as Object
    known = SiloNativeDeliveryFeatures(context)
    features = []
    for each name in ["hls_copy_mpegts_v1","native_hls_mpegts_v1","native_hls_separate_audio_v1","server_dv7_to_dv81_v1"]
        if SiloContains(known,name) then features.Push(name)
    end for
    return features
end function

' Media authentication is a session transport choice, never an HLS device claim.
function SiloClientPlaybackFeatures(context as Dynamic, mediaAuthMode = invalid as Dynamic) as Dynamic
    features = SiloClientNativeFeatures(context)
    for index = features.Count()-1 to 0 step -1
        if features[index] = "hls_copy_mpegts_v1" then features.Delete(index)
    end for
    if mediaAuthMode = invalid then return features
    if type(mediaAuthMode) <> "String" and type(mediaAuthMode) <> "roString" then return invalid
    if mediaAuthMode <> "api_header_v1" then return invalid
    features.Push("header_authenticated_media_v1")
    return features
end function

' Existing H.264/AAC encoding uses MPEG-TS. This is also available on servers
' without the new copy-HLS recipes; HEVC encoding still uses muxed fMP4.
function SiloNativeH264Oversized(plan as Dynamic) as Boolean
    if not SiloObject(plan) then return false
    if not SiloContains(["server_remux_hls","server_transcode_hls"],SiloText(plan.delivery)) then return false
    recipe = plan.effective_recipe
    if not SiloObject(recipe) or recipe.video_codec <> "h264" then return false
    if not SiloReplanNumber(recipe.width,7680,1,true) or not SiloReplanNumber(recipe.height,4320,1,true) then return false
    return recipe.width > 1920 or recipe.height > 1080
end function

function SiloNativeH264TranscodeSupported(plan as Object, features as Object) as Boolean
    if not SiloContains(features,"native_hls_playback_v1") then return false
    recipe = plan.effective_recipe
    if not SiloObject(recipe) or not SiloArray(plan.transformations) then return false
    if recipe.DoesExist("segment_container") then return false
    if recipe.video_codec <> "h264" or recipe.audio_codec <> "aac" or recipe.dynamic_range <> "sdr" then return false
    if not SiloReplanNumber(recipe.width,1920,1,true) or not SiloReplanNumber(recipe.height,1080,1,true) then return false
    if plan.transformations.Count() > 16 then return false
    seen = {}
    for each transform in plan.transformations
        if not SiloObject(transform) then return false
        name = SiloText(transform.name):version = SiloText(transform.recipe_version)
        if transform.executor <> "server" or seen.DoesExist(name) then return false
        seen[name] = true
        if name = "video_to_h264"
            if version <> "2" then return false
        else if name = "audio_to_aac"
            if version <> "2" and version <> "4" then return false
        else if name = "hdr_to_sdr_tonemap"
            if version <> "1" then return false
        else
            return false
        end if
    end for
    return seen.DoesExist("video_to_h264") and seen.DoesExist("audio_to_aac")
end function

' This validates the negotiated byte recipe. Fresh device/output capabilities
' remain the planner's separate constraint; a 4K badge cannot establish them.
function SiloNativeHLSPlanSupported(plan as Dynamic, features as Dynamic) as Boolean
    if not SiloObject(plan) or not SiloArray(features) then return false
    if SiloText(plan.delivery) = "server_transcode_hls" then return SiloNativeH264TranscodeSupported(plan,features)
    if SiloText(plan.delivery) <> "server_remux_hls" then return false
    recipe = plan.effective_recipe
    if not SiloObject(recipe) or not SiloArray(plan.transformations) then return false
    if plan.transformations.Count() > 16 then return false
    video = SiloText(recipe.video_codec):audio = SiloText(recipe.audio_codec)
    dynamicRange = SiloText(recipe.dynamic_range)
    if not SiloContains(["h264","hevc"],video) or not SiloContains(["aac","ac3","eac3"],audio) then return false
    if not SiloContains(["sdr","hdr10","hdr10_plus","hlg","dolby_vision"],dynamicRange) then return false
    if video = "h264" and dynamicRange <> "sdr" then return false
    if video = "h264" and (not SiloReplanNumber(recipe.width,1920,1,true) or not SiloReplanNumber(recipe.height,1080,1,true)) then return false
    canonicalTS = recipe.DoesExist("segment_container")
    if canonicalTS
        if recipe.segment_container <> "mpegts" or not SiloContains(features,"hls_copy_mpegts_v1") then return false
        if recipe.DoesExist("video_sample_entry") then return false
    end if
    packaging = "":convertedDV = false:seen = {}
    for each transform in plan.transformations
        if not SiloObject(transform) then return false
        name = SiloText(transform.name):version = SiloText(transform.recipe_version)
        if SiloText(transform.executor) <> "server" or seen.DoesExist(name) then return false
        seen[name] = true
        if name = "hls_mpegts" or name = "hls_separate_audio"
            if packaging <> "" or version <> "1" then return false
            packaging = name
        else if name = "server_dv7_to_dv81"
            if version <> "1" or not SiloContains(features,"server_dv7_to_dv81_v1") then return false
            convertedDV = true
        else if name = "audio_to_aac"
            if (version <> "2" and version <> "4") or audio <> "aac" then return false
        else if name = "server_dv7_to_hdr10"
            if version <> "2" or dynamicRange <> "hdr10" then return false
        else
            return false
        end if
    end for
    if canonicalTS
        if packaging <> "" or convertedDV then return false
    else if packaging = "hls_mpegts"
        if not SiloContains(features,"native_hls_mpegts_v1") or dynamicRange = "dolby_vision" or convertedDV then return false
    else if packaging = "hls_separate_audio"
        if not SiloContains(features,"native_hls_separate_audio_v1") then return false
        if video = "hevc" and not SiloContains(["hvc1","dvh1"],SiloText(recipe.video_sample_entry)) then return false
        if dynamicRange = "dolby_vision" and SiloText(recipe.video_sample_entry) <> "dvh1" then return false
    else
        return false
    end if
    if convertedDV and dynamicRange <> "dolby_vision" then return false
    return true
end function

' Copied DV must fit this request's exact output bounds. A P8 source may
' have been selected for HDR10 extraction; that is not permission to return DV.
function SiloNativeDVReceiptSupported(plan as Object, context as Dynamic) as Boolean
    recipe = plan.effective_recipe:source = plan.source
    delivery = ""
    if SiloContains(["server_remux_hls","server_transcode_hls"],SiloText(plan.delivery))
        if SiloObject(plan.stream) then if LCase(SiloText(plan.stream.protocol)) = "hls" then delivery = "hls"
    end if
    isDV = SiloObject(recipe) and SiloText(recipe.dynamic_range) = "dolby_vision"
    if SiloText(plan.delivery) = "original_http"
        delivery = "original_http"
        if SiloObject(source)
            isDV = isDV or SiloText(source.dynamic_range) = "dolby_vision"
            if SiloReplanNumber(source.dolby_vision_profile,8,1,true) then isDV = true
        end if
    end if
    if not isDV then return true
    if delivery = "" then return false
    if not SiloObject(context) or not SiloObject(context.deliveries) then return false
    offered = context.deliveries[delivery]
    if not SiloObject(offered) or offered.enabled <> true or offered.supported_on_device <> true then return false
    details = offered.hdr_details
    if not SiloObject(details) or not SiloObject(source) then return false
    profile = source.dolby_vision_profile:level = source.dolby_vision_level:compat = source.dv_bl_compat_id
    if not SiloReplanNumber(profile,8,1,true) or not SiloReplanNumber(level,13,1,true) then return false
    ' Stock omitempty drops P5's zero compatibility ID. Only a complete positive
    ' P5 source descriptor permits that absent default; present bad values refuse.
    if profile = 5 and not source.DoesExist("dv_bl_compat_id")
        if source.video_codec <> "hevc" or source.bit_depth <> 10 or source.dynamic_range <> "dolby_vision" then return false
        if source.dv_base_layer_proven <> true or source.dv_enhancement_layer <> "none" or source.hdr10_plus <> false then return false
        compat = 0
    end if
    if not SiloReplanNumber(compat,6,0,true) then return false
    converted = false
    if not SiloArray(plan.transformations) then return false
    for each transform in plan.transformations
        if not SiloObject(transform) then return false
        if SiloText(transform.name) = "" or SiloText(transform.executor) = "" or SiloText(transform.recipe_version) = "" then return false
        if transform.name = "server_dv7_to_dv81" then converted = true
    end for
    if converted
        if delivery <> "hls" then return false
        ' Recipe v1 preserves source level while changing P7/compat6 to P8/compat1.
        ' The recipe/feature validator has already checked its typed transform.
        if profile <> 7 or compat <> 6 then return false
        profile = 8:compat = 1
    else
        if profile = 5
            if compat <> 0 then return false
        else if profile = 8
            if compat <> 1 then return false
        else
            return false
        end if
    end if
    if not SiloArray(details.dolby_vision_profiles) or not SiloContains(details.dolby_vision_profiles,profile) then return false
    if not SiloArray(details.dolby_vision_profile_levels) then return false
    for each bound in details.dolby_vision_profile_levels
        if SiloObject(bound)
            if bound.profile = profile and SiloReplanNumber(bound.max_level,13,1,true)
                if level <= bound.max_level and SiloArray(bound.bl_compatibility_ids)
                    if SiloContains(bound.bl_compatibility_ids,compat) then return true
                end if
            end if
        end if
    end for
    return false
end function

' Only public playback enums cross the worker boundary; server text stays local.
function SiloPlaybackTerminalReason(reason as Dynamic) as String
    value = SiloText(reason)
    allowed = ["no_playable_source","no_alternate_version","hdr_transcode_unsupported","subtitle_conversion_unsupported","client_hls_unsupported","adaptation_unavailable","adaptation_exhausted","audio_conversion_unsupported","dv_conversion_unsupported","transcode_start_failed","transcoding_disabled","conversion_tool_unavailable","source_metadata_incomplete","source_unreadable","bitrate_policy_unavailable","subtitle_codec_unsupported","subtitle_burn_in_source_unsupported"]
    if SiloContains(allowed,value) then return value
    return ""
end function

function SiloPlaybackFailureDetails(failure as Object, decision as Dynamic, stage as String) as Object
    code = SiloText(failure.errorCode)
    result = {ok:false,errorCode:code}
    if not SiloContains(["playback_terminal","unsupported_protocol","unsupported_playback_protocol","unsupported_stream"],code) then return result
    if SiloContains(["start","replan"],stage) then result["stage"] = stage
    if code = "playback_terminal" and SiloObject(decision)
        if decision.protocol_version = 3 and (decision.outcome = "terminal" or decision.outcome = "adaptation_unavailable") and SiloObject(decision.terminal)
            reason = SiloPlaybackTerminalReason(decision.terminal.reason)
            if reason <> "" then result["reason"] = reason
        end if
    end if
    return result
end function

' Selection metadata is retained only as an actual protocol enum, never IDs/URLs.
function SiloSubtitleMode(raw as Dynamic) as String
    if not SiloObject(raw) then return "unknown"
    if not SiloObject(raw.subtitle) then return "unknown"
    mode = raw.subtitle.mode
    if type(mode) <> "String" and type(mode) <> "roString" then return "unknown"
    if SiloContains(["off","render","convert","burn_in"],mode) then return mode
    return "unknown"
end function

' Acknowledging Off requires explicit selection evidence. Inventory is independent
' of selection; the QA server also has an embedded selector absent in 55d0578.
function SiloSubtitleOffReceipt(raw as Dynamic) as Boolean
    if SiloSubtitleMode(raw) <> "off" then return false
    if not SiloObject(raw.selected_tracks) then return false
    if raw.selected_tracks.DoesExist("subtitle") then return false
    subtitle = raw.subtitle
    if subtitle.track_id <> invalid
        if type(subtitle.track_id) <> "String" and type(subtitle.track_id) <> "roString" then return false
        if subtitle.track_id <> "" then return false
    end if
    if subtitle.artifact <> invalid or subtitle.embedded <> invalid then return false
    if raw.claims <> invalid
        if not SiloObject(raw.claims) then return false
        claims = raw.claims.subtitles
        if claims <> invalid
            if not SiloObject(claims) then return false
            for each key in ["bitmap_overlay","bitmap_sidecar","ass_styling_preserved"]
                if claims.DoesExist(key)
                    if type(claims[key]) <> "Boolean" and type(claims[key]) <> "roBoolean" then return false
                    if claims[key] <> false then return false
                end if
            end for
            if claims.reason = "server_burn_in_required" then return false
        end if
    end if
    if raw.decision_reason = "subtitle_burn_in_required" then return false
    if raw.degradation_warnings <> invalid
        if not SiloArray(raw.degradation_warnings) then return false
        if raw.degradation_warnings.Count() > 32 then return false
        for each warning in raw.degradation_warnings
            if not SiloObject(warning) then return false
            if warning.code = "subtitle_burn_in" then return false
        end for
    end if
    if raw.transformations <> invalid
        if not SiloArray(raw.transformations) then return false
        if raw.transformations.Count() > 16 then return false
        for each transform in raw.transformations
            if not SiloObject(transform) then return false
            ' Actual known transformations do not select subtitles. Unknown work
            ' cannot prove Off, even though ordinary legacy playback may accept it.
            if not SiloContains(["audio_to_aac","video_to_h264","video_to_hevc","server_dv7_to_hdr10","server_dv7_to_dv81","hls_mpegts","hls_separate_audio","hdr_to_sdr_tonemap"],SiloText(transform.name)) then return false
        end for
    end if
    return true
end function

' A request-local private proof is separate from negotiated public features.
function SiloPrivateLegacyHDR10PlanSupported(plan as Dynamic, proof as Dynamic) as Boolean
    if not SiloObject(proof) or proof.schemaVersion <> 1 or proof.route <> "official_legacy_hdr10_private_v1" or proof.audioAcceptance <> "unqualified" then return false
    if not SiloObject(plan) or plan.delivery <> "server_remux_hls" then return false
    if not SpNumber(SpField(plan,"protocol_version"),3,true) or plan.protocol_version <> 3 then return false
    videoClaims = SpField(SpField(plan,"claims"),"video")
    if not SiloObject(videoClaims) then return false
    if not SpBool(SpField(videoClaims,"hdr10")) or SpField(videoClaims,"hdr10") <> true then return false
    if not SpBool(SpField(videoClaims,"dolby_vision")) or SpField(videoClaims,"dolby_vision") <> false then return false
    for each name in ["hdr10_plus","hlg"]
        if videoClaims.DoesExist(name) then if not SpBool(videoClaims[name]) or videoClaims[name] <> false then return false
    end for
    if plan.requested_media_file_id <> proof.fileId or plan.effective_media_file_id <> proof.fileId then return false
    stream = SpField(plan,"stream"):source = SpField(plan,"source"):recipe = SpField(plan,"effective_recipe")
    if SpField(stream,"protocol") <> "hls" or SpField(stream,"container") <> "hls" or SpField(stream,"mime_type") <> "application/vnd.apple.mpegurl" then return false
    if SpField(source,"media_file_id") <> proof.fileId or SpField(source,"dynamic_range") <> "dolby_vision" then return false
    if source.dolby_vision_profile <> 8 or source.dolby_vision_level <> proof.video.dv_level or source.dv_bl_compat_id <> 1 or source.dv_base_layer_proven <> true or source.dv_enhancement_layer <> "none" then return false
    if SpField(source,"video_copy_unsafe",false) <> false or SpField(source,"hdr10_plus",false) <> false then return false
    if source.video_codec <> "hevc" or LCase(source.video_profile) <> "main 10" or source.video_level <> proof.video.level or source.bit_depth <> 10 then return false
    if not SiloObject(recipe) or recipe.video_codec <> "hevc" or recipe.video_sample_entry <> "hvc1" or recipe.dynamic_range <> "hdr10" then return false
    for each item in [source,recipe]
        if item.width <> proof.video.width or item.height <> proof.video.height or item.bitrate_kbps <> proof.bitrate then return false
        if not SoNear(item.frame_rate,SoFrameRate(proof.video.frame_rate)) then return false
        if item.audio_codec <> "eac3" or item.audio_channels <> proof.audio.channels or item.audio_layout <> proof.audio.layout then return false
    end for
    audio = SpField(SpField(plan,"selected_tracks"),"audio")
    if SpField(audio,"id") <> proof.audioId or SpField(audio,"index") <> proof.audioIndex then return false
    if not SiloSubtitleOffReceipt(plan) then return false
    if not SiloArray(plan.transformations) or plan.transformations.Count() <> 1 then return false
    transform = plan.transformations[0]
    if not SpFields(transform,["name","executor","recipe_version","validated_claims"],[]) then return false
    if transform.name <> "server_dv7_to_hdr10" or transform.executor <> "server" or transform.recipe_version <> "2" then return false
    claims = transform.validated_claims
    if not SiloArray(claims) or claims.Count() <> 3 then return false
    for each expected in ["dolby_vision_metadata_removed","hdr10_base_layer_preserved","enhancement_layer_discarded"]
        count = 0
        for each claim in claims
            if claim = expected then count++
        end for
        if count <> 1 then return false
    end for
    for each name in ["applied_quirks","runtime_corrections"]
        value = SpField(plan,name)
        if value <> invalid then if not SiloArray(value) or value.Count() <> 0 then return false
    end for
    return true
end function

function SiloPlaybackPlan(decision as Object, session as Object, nativeFeatures = invalid as Dynamic, privateProof = invalid as Dynamic, deliveryContext = invalid as Dynamic) as Object
    if decision.protocol_version <> 3 then return SiloError("unsupported_protocol", "This server playback protocol is unavailable.")
    if decision.outcome = "terminal" or decision.outcome = "adaptation_unavailable"
        result = SiloError("playback_terminal", "No playable source is available for this title.")
        if SiloObject(decision.terminal)
            reason = SiloPlaybackTerminalReason(decision.terminal.reason)
            if reason <> "" then result.reason = reason
            result.retryable = decision.terminal.retryable = true
        end if
        return result
    end if
    if (decision.outcome <> "plan" and decision.outcome <> "playable") or not SiloObject(decision.playback_plan) then return SiloError("invalid_response", "The server response could not be read.")
    plan = decision.playback_plan
    if not SiloObject(plan.stream) or not SiloObject(plan.timeline) then return SiloError("invalid_response", "The server response could not be read.")
    stream = plan.stream
    if privateProof <> invalid
        if not SiloPrivateLegacyHDR10PlanSupported(plan,privateProof) then return SiloError("unsupported_stream", "This stream format is unavailable on this player.")
    end if
    if SiloText(stream.header_refresh) <> "none" and SiloText(stream.header_refresh) <> "" then return SiloError("unsupported_header_refresh", "This stream needs an unsupported authentication refresh.")
    url = SiloResolveUrl(SiloText(stream.url), SiloText(session.baseUrl))
    origin = SiloUrlParts(url)
    if not origin.ok then return SiloError("invalid_stream_url", "This stream address is unavailable.")
    protocol = LCase(SiloText(stream.protocol))
    format = ""
    if protocol = "hls"
        if privateProof = invalid then if not SiloNativeHLSPlanSupported(plan,nativeFeatures) then return SiloError("unsupported_stream", "This stream format is unavailable on this player.")
        format = "hls"
    else if protocol = "dash"
        format = "dash"
    else if protocol = "progressive" or protocol = "http_progressive" or protocol = "http" or protocol = "original_http"
        container = LCase(SiloText(stream.container))
        if container = ""
            path = LCase(origin.path)
            if Instr(1, path, "?") > 0 then path = Left(path, Instr(1, path, "?") - 1)
            if Right(path, 4) = ".mp4" then container = "mp4"
            if Right(path, 4) = ".mkv" then container = "mkv"
        end if
        if container = "mp4" or container = "m4v" or container = "mov" then format = "mp4"
        ' The manifest declares requires_mkv=1, so Video plays Matroska natively.
        if container = "mkv" or container = "matroska" then format = "mkv"
    end if
    if deliveryContext <> invalid
        if not SiloNativeDVReceiptSupported(plan,deliveryContext) then return SiloError("unsupported_stream", "This stream format is unavailable on this player.")
    end if
    if format = "" then print "Silo unsupported stream protocol="; protocol; " container="; SiloText(stream.container)
    if format = "" then return SiloError("unsupported_stream", "This stream format is unavailable on this player.")
    headers = {}
    if SiloObject(stream.headers)
        for each key in stream.headers
            lower = LCase(key)
            if lower <> "authorization" and lower <> "x-profile-token" and lower <> "x-profile-id" and lower <> "cookie" and lower <> "x-plex-token"
                if SiloSafeHeader(key, true) and SiloSafeHeader(SiloText(stream.headers[key]), false) then headers[key] = SiloText(stream.headers[key])
            end if
        end for
    end if
    baseOrigin = SiloUrlParts(SiloText(session.baseUrl))
    if baseOrigin.ok
        if origin.origin = baseOrigin.origin
            if SiloText(session.accessToken) <> "" then headers["Authorization"] = "Bearer " + SiloText(session.accessToken)
            if SiloText(session.profileId) <> "" then headers["X-Profile-Id"] = SiloText(session.profileId)
            if SiloText(session.profileToken) <> "" then headers["X-Profile-Token"] = SiloText(session.profileToken)
        end if
    end if
    sessionId = SiloText(plan.session_id)
    if sessionId = "" then sessionId = SiloText(decision.session_id)
    output = {ok: true, provider:"silo", url: url, streamFormat: format, headers: headers, subtitleMode: SiloSubtitleMode(plan), sourceId: "silo", itemId: SiloText(session.itemId), versionId: SiloText(plan.effective_media_file_id), startPositionMs: SiloNumber(plan.timeline.player_start_seconds, 0) * 1000, timelineOffsetMs: SiloNumber(plan.timeline.timeline_offset_seconds, 0) * 1000, canSeekAnywhere: plan.timeline.can_seek_anywhere = true, sessionId: sessionId, planId: SiloText(plan.plan_id), planAttemptKey: SiloText(plan.plan_attempt_key)}
    ' Optional authoritative window; a missing end is never a full-file claim.
    timing = SiloPlaybackTimeline(plan.timeline)
    if timing <> invalid
        output["sourceStartMs"] = timing.source_start_seconds*1000#
        output["streamOriginMs"] = timing.stream_origin_seconds*1000#
        output["seekRestoration"] = timing.seek_restoration
        if timing.DoesExist("seek_window_start_seconds") then output["seekWindowStartMs"] = timing.seek_window_start_seconds*1000#
        if timing.DoesExist("seek_window_end_seconds") then output["seekWindowEndMs"] = timing.seek_window_end_seconds*1000#
    end if
    return output
end function


' Both media admission and selected-caption handoff use this API-owned route
' contract. Scene independently validates the descriptor in its own context.
function SiloHeaderMediaUrlAllowed(url as Dynamic, baseUrl as Dynamic, sessionId as Dynamic, fileId as Dynamic) as Boolean
    if not SpText(url,2048) or not SpText(baseUrl,1024) then return false
    if not SpText(sessionId,128) or not SpText(fileId,32) then return false
    if Instr(1,url,"#") > 0 then return false
    base = SiloUrlParts(baseUrl)
    media = SiloUrlParts(url)
    if not base.ok or not media.ok then return false
    if media.origin <> base.origin then return false
    if not CreateObject("roRegex","^[A-Za-z0-9_.-]{1,128}$","").IsMatch(sessionId) or sessionId = "." or sessionId = ".." then return false
    path = media.path
    question = Instr(1,path,"?")
    query = ""
    if question > 0
        query = Mid(path,question+1)
        path = Left(path,question-1)
        if query = "" or Left(query,1) = "&" or Right(query,1) = "&" or Instr(1,query,"&&") > 0 then return false
    end if
    stream = path = "/api/v2/stream/" + sessionId
    hls = path = "/api/v2/playback/transcode/" + sessionId + "/master.m3u8"
    if not stream and not hls then return false
    if query <> ""
        fields = query.Tokenize("&")
        if fields.Count() > 2 then return false
        seen = {}
        for each field in fields
            equals = Instr(1,field,"=")
            if equals < 2 then return false
            name = Left(field,equals-1):value = Mid(field,equals+1)
            if seen.DoesExist(name) then return false
            seen[name] = true
            if name = "file_id"
                if value <> fileId then return false
            else if name = "seek" and stream
                if Len(value) > 16 or not CreateObject("roRegex","^[0-9]{1,6}([.][0-9]{1,9})?$","").IsMatch(value) then return false
                if not SpNumber(Val(value),604800) then return false
            else
                return false
            end if
        end for
    end if
    return true
end function

function SiloClientHeaders(session as Object) as Object
    headers = {"Accept": "application/json", "X-Device-ID": SiloText(session.deviceId), "X-Client-Name": "Silo", "X-Client-Version": SiloText(session.appVersion), "X-Client-Build": SiloText(session.appBuild), "X-Client-Channel": "development", "X-Client-Model": SiloText(session.model), "X-Client-Platform": "roku", "X-Client-OS-Version": SiloText(session.osVersion)}
    headers["X-Silo-Device-Id"] = SiloText(session.deviceId)
    headers["X-Silo-Device-Name"] = "Silo (" + SiloText(session.model) + ")"
    headers["X-Silo-Device-Platform"] = "roku"
    headers["X-Silo-Client-Family"] = "tv"
    headers["X-Silo-Client"] = "Silo Roku"
    headers["X-Silo-Client-Version"] = SiloText(session.appVersion)
    headers["X-Silo-Client-Build"] = SiloText(session.appBuild)
    headers["X-Silo-Client-Channel"] = "development"
    return headers
end function

function SiloUrlParts(url as String) as Object
    invalidUrl = {ok: false}
    if Instr(1, url, Chr(10)) > 0 or Instr(1, url, Chr(13)) > 0 or Instr(1, url, Chr(92)) > 0 then return invalidUrl
    expression = CreateObject("roRegex", "^(https?)://([^/?#]+)(.*)$", "i")
    parts = expression.Match(url)
    if parts.Count() <> 4 then return invalidUrl
    scheme = LCase(parts[1])
    authority = LCase(parts[2])
    if Instr(1, authority, "@") > 0 or Instr(1, authority, " ") > 0 then return invalidUrl
    hostExpression = CreateObject("roRegex", "^(\[[0-9a-f:]+\]|[a-z0-9.-]+)(:[0-9]+)?$", "i")
    hostParts = hostExpression.Match(authority)
    if hostParts.Count() < 2 then return invalidUrl
    host = hostParts[1]
    port = "80"
    if scheme = "https" then port = "443"
    if hostParts.Count() > 2
        if hostParts[2] <> "" then port = Mid(hostParts[2], 2)
    end if
    portNumber = Val(port)
    if portNumber < 1 or portNumber > 65535 then return invalidUrl
    return {ok: true, origin: scheme + "://" + host + ":" + portNumber.ToStr(), authority: scheme + "://" + authority, path: parts[3]}
end function

function SiloBaseUrl(url as String) as String
    parts = SiloUrlParts(url)
    if not parts.ok then return ""
    if Instr(1, parts.path, "?") > 0 or Instr(1, parts.path, "#") > 0 then return ""
    url = parts.authority + parts.path
    while Right(url, 1) = "/"
        url = Left(url, Len(url) - 1)
    end while
    return url
end function

function SiloResolveUrl(url as String, baseUrl as String) as String
    if Left(url, 2) = "//" then return ""
    if Left(url, 1) = "/"
        base = SiloUrlParts(baseUrl)
        if not base.ok then return ""
        return base.authority + url
    end if
    return url
end function

function SiloEscape(value as String) as String
    bytes = CreateObject("roByteArray")
    bytes.FromAsciiString(value)
    digits = "0123456789ABCDEF"
    encoded = ""
    for each code in bytes
        if (code >= 65 and code <= 90) or (code >= 97 and code <= 122) or (code >= 48 and code <= 57) or code = 45 or code = 46 or code = 95 or code = 126
            encoded = encoded + Chr(code)
        else
            encoded = encoded + "%" + Mid(digits, Int(code / 16) + 1, 1) + Mid(digits, (code mod 16) + 1, 1)
        end if
    end for
    return encoded
end function

function SiloSafeHeader(value as String, isName as Boolean) as Boolean
    if Instr(1, value, Chr(10)) > 0 or Instr(1, value, Chr(13)) > 0 then return false
    if isName
        expression = CreateObject("roRegex", "^[!#$%&'*+.^_`|~0-9A-Za-z-]+$", "")
        return expression.IsMatch(value)
    end if
    return true
end function

function SiloText(value as Dynamic) as String
    if type(value) = "String" or type(value) = "roString" then return value.Trim()
    return ""
end function

function SiloNumber(value as Dynamic, fallback as Dynamic) as Dynamic
    if type(value) = "Integer" or type(value) = "roInt" or type(value) = "roInteger" or type(value) = "LongInteger" or type(value) = "roLongInteger" or type(value) = "Float" or type(value) = "roFloat" or type(value) = "Double" or type(value) = "roDouble" then return value
    return fallback
end function

function SiloObject(value as Dynamic) as Boolean
    return type(value) = "roAssociativeArray"
end function

function SiloArray(value as Dynamic) as Boolean
    return type(value) = "roArray"
end function

function SiloList(value as Dynamic) as Object
    if SiloArray(value) then return value
    return []
end function

function SiloContains(values as Object, value as Dynamic) as Boolean
    for each candidate in values
        if candidate = value then return true
    end for
    return false
end function

function SiloError(code as String, message as String) as Object
    return {ok: false, errorCode: code, message: message}
end function

' Retain native grouping as bounded identifiers, never media URLs or names.
function SiloNativeVariants(raw as Dynamic) as Object
    output = []
    if not SiloArray(raw) then return output
    if raw.Count() > 16 then return output
    for each variant in raw
        if not SiloObject(variant) then return []
        if not SiloArray(variant.parts) then return []
        if variant.parts.Count() > 16 then return []
        row = {variantId:SiloText(variant.variant_id),partCount:SiloNumber(variant.part_count,0),defaultFileId:SiloText(variant.default_file_id),presentationGroupKey:SiloText(variant.presentation_group_key),presentationKind:SiloText(variant.presentation_kind),editionKey:SiloText(variant.edition_key),parts:[]}
        for each part in variant.parts
            if not SiloObject(part) then return []
            if not SiloArray(part.versions) then return []
            if part.versions.Count() > 16 then return []
            ids = []
            for each version in part.versions
                if not SiloObject(version) then return []
                ids.Push(SiloText(version.file_id))
            end for
            row.parts.Push({partIndex:SiloNumber(part.part_index,0),defaultFileId:SiloText(part.default_file_id),fileIds:ids})
        end for
        output.Push(row)
    end for
    return output
end function

' Silo VideoTrack signal facts only. File paths and free-form titles stay out.
function SiloVideoTracks(raw as Dynamic) as Object
    output = []
    if not SiloArray(raw) then return output
    for each track in raw
        if output.Count() >= 4 then exit for
        if SiloObject(track)
            row = {}
            for each key in ["codec","profile","frame_rate","color_primaries","color_range","color_space","color_transfer","pixel_format","video_range","video_range_type","dolby_vision","dv_enhancement_layer"]
                value = track[key]
                if type(value) = "String" or type(value) = "roString"
                    if Len(value) <= 64 and not CreateObject("roRegex","[\x00-\x1f\x7f]","").IsMatch(value) then row[key] = value
                end if
            end for
            for each key in ["level","width","height","bit_depth","bitrate","reference_frames","dv_profile","dv_level","dv_bl_compat_id"]
                value = track[key]:kind = type(value)
                if kind = "Integer" or kind = "roInt" or kind = "roInteger" or kind = "LongInteger" or kind = "roLongInteger"
                    if value >= 0 and value <= 2147483646 then row[key] = value
                end if
            end for
            for each key in ["dv_config_present","dv_bl_compat_id_present","dv_bl_present","dv_el_present","dv_rpu_present","hdr10_plus","interlaced"]
                value = track[key]
                if type(value) = "Boolean" or type(value) = "roBoolean" then row[key] = value
            end for
            ' Official omit-empty metadata drops P5 compatibility zero and EL false.
            ' Restore only absent fields from a complete single-layer P5 signal.
            if row.dv_profile = 5 and row.dv_config_present = true and row.dv_bl_compat_id_present = true and row.dv_bl_present = true and row.dv_rpu_present = true and row.dv_enhancement_layer = "none"
                if not track.DoesExist("dv_bl_compat_id") or row.dv_bl_compat_id = 0
                    if not track.DoesExist("dv_el_present") or row.dv_el_present = false
                        if not track.DoesExist("dv_bl_compat_id") then row["dv_bl_compat_id"] = 0
                        if not track.DoesExist("dv_el_present") then row["dv_el_present"] = false
                    end if
                end if
            end if
            ' Official DVELPresent omits false. Infer it only from a complete
            ' single-layer P8.1 signal; a present malformed field is not omission.
            if not track.DoesExist("dv_el_present") and row.dv_profile = 8 and row.dv_bl_compat_id = 1
                if row.dv_config_present = true and row.dv_bl_compat_id_present = true and row.dv_bl_present = true and row.dv_rpu_present = true
                    if row.dv_enhancement_layer = "none" then row["dv_el_present"] = false
                end if
            end if
            output.Push(row)
        end if
    end for
    return output
end function

' Text-only chapters keep the transport bounded and avoid retaining signed art.
function SiloVersionChapters(raw as Dynamic) as Object
    out = []
    if not SiloArray(raw) then return out
    count = 0
    for each entry in raw
        count++
        if count > 128 then exit for
        if SiloObject(entry)
            start = SiloNumber(entry.start_seconds,-1)
            finish = SiloNumber(entry.end_seconds,-1)
            if start >= 0 and finish > start and finish <= 604800
                out.Push({start_seconds:start,end_seconds:finish,title:Left(SiloText(entry.title),80)})
            end if
        end if
    end for
    return out
end function


' Preserve only finite native timeline facts; absent window end stays absent.
function SiloPlaybackTimeline(raw as Dynamic) as Dynamic
    if not SiloObject(raw) then return invalid
    for each key in ["source_start_seconds","stream_origin_seconds","player_start_seconds","timeline_offset_seconds"]
        if not SiloReplanNumber(raw[key],604800) then return invalid
    end for
    if type(raw.can_seek_anywhere) <> "Boolean" and type(raw.can_seek_anywhere) <> "roBoolean" then return invalid
    if SiloText(raw.seek_restoration) = "" or Len(SiloText(raw.seek_restoration)) > 32 then return invalid
    out = {source_start_seconds:raw.source_start_seconds,stream_origin_seconds:raw.stream_origin_seconds,seek_restoration:raw.seek_restoration}
    for each key in ["seek_window_start_seconds","seek_window_end_seconds"]
        if raw.DoesExist(key)
            if not SiloReplanNumber(raw[key],604800) then return invalid
            out[key] = raw[key]
        end if
    end for
    if out.DoesExist("seek_window_end_seconds")
        if not out.DoesExist("seek_window_start_seconds") then return invalid
        if out.seek_window_end_seconds < out.seek_window_start_seconds then return invalid
    end if
    return out
end function

function SiloIdentitySeeds(seeds as Dynamic) as Boolean
    if not SiloArray(seeds) then return false
    if seeds.Count()<1 or seeds.Count()>48 then return false
    for each seed in seeds
        if not SiloObject(seed) then return false
        if not SiloContains(["movie","series"],SiloText(seed.type)) then return false
        found = false
        for each key in seed
            if not SiloContains(["type","tmdb_id","imdb_id","tvdb_id"],key) then return false
            if key <> "type"
                namespace = Left(key,4)
                if SiloExternalId(seed[key],namespace)="" then return false
                found = true
            end if
        end for
        if not found then return false
    end for
    return true
end function

function SiloAudioPreferenceOrdinal(value as Dynamic) as Boolean
    kind = type(value)
    if kind <> "Integer" and kind <> "roInt" and kind <> "Float" and kind <> "roFloat" and kind <> "Double" and kind <> "roDouble" then return false
    return value >= 0 and value <= 4095 and value = Int(value)
end function

' Preferences use complete catalog ordinals, even when playback uses a wire index.
function SiloAudioPreference(item as Dynamic, fileId as String, ordinal as Dynamic, versions as Dynamic) as Dynamic
    if not SiloObject(item) or not SiloAudioPreferenceOrdinal(ordinal) then return invalid
    key = SiloText(item.itemId)
    if item.type = "episode"
        key = SiloText(item.seriesId)
    else if item.type <> "movie"
        return invalid
    end if
    if key = "" or fileId = "" then return invalid
    selected = invalid:matches = 0
    for each version in SiloList(versions)
        if SiloObject(version)
            if version.versionId = fileId
                matches++
                for each track in SiloList(version.audioTracks)
                    if SiloObject(track)
                        if track.sourceOrdinal = ordinal
                            if selected <> invalid then return invalid
                            selected = track
                        end if
                    end if
                end for
            end if
        end if
    end for
    if matches <> 1 or selected = invalid then return invalid
    signature = selected.preferenceSignature
    if not SiloObject(signature) then return invalid
    body = {audio_track_index:Int(ordinal),track_signature:signature}
    language = SiloText(signature.language)
    if language <> "" and CreateObject("roRegex","^(?:[a-z]{2,3}(?:-[0-9A-Za-z]{1,8})*|x(?:-[0-9A-Za-z]{1,8})+)$","").IsMatch(language) then body["audio_language"] = language
    return {seriesId:key,preference:body}
end function
