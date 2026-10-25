' A separate read-only Task verifies episode adjacency without blocking playback
' startup or allocating a playback route. Session tokens and response bodies stay
' on this thread; only compact scoped items and policy proof reach SceneGraph.
sub init()
    m.top.functionName = "runNeighborJob"
end sub

sub runNeighborJob()
    job = m.top.job
    if type(job) <> "roAssociativeArray" then job = {}
    ' Catchable failures still publish the same scope. Exception text can
    ' contain credentials or private URLs and never enters logs or SceneGraph.
    try
        outcome = EpisodeNeighborExecute(job)
        result = EpisodeNeighborEnvelope(job, outcome)
    catch exception
        result = EpisodeNeighborEnvelope(job, EpisodeNeighborError("task_failed"))
    end try
    m.top.result = result
end sub

function EpisodeNeighborValue(data as Dynamic, key as String, fallback as Dynamic) as Dynamic
    if type(data) <> "roAssociativeArray" then return fallback
    if not data.DoesExist(key) then return fallback
    if data[key] = invalid then return fallback
    return data[key]
end function

function EpisodeNeighborText(data as Dynamic, key as String) as String
    value = EpisodeNeighborValue(data, key, "")
    if type(value) = "String" or type(value) = "roString" then return value
    return ""
end function

function EpisodeNeighborError(code as String, status = "retryable" as String) as Object
    return {status: status, errorCode: EpisodeNeighborSafeError(code)}
end function

function EpisodeNeighborSafeError(code as String) as String
    if code = "task_failed" then return code
    for each allowed in ["invalid_anchor", "missing_season", "missing_context", "identity_mismatch", "unavailable_candidate", "invalid_inventory", "incomplete_inventory", "inventory_budget", "duplicate_identity", "empty_adjacent", "missing_anchor", "duplicate_season"]
        if code = allowed then return code
    end for
    for each allowed in ["invalid_job", "invalid_provider", "invalid_request", "invalid_response", "unsupported_action", "auth_required", "profile_required", "session_changed", "anchor_changed", "lookup_budget", "client_identity_missing", "invalid_server", "invalid_server_url", "item_required", "season_required", "decode_error", "page_mismatch", "network_error", "network_unavailable", "network_timeout", "timeout", "forbidden", "not_found", "rate_limited", "server_error", "http_error", "response_too_large", "ambiguous", "unplayable", "incomplete"]
        if code = allowed then return code
    end for
    return "invalid_response"
end function

function EpisodeNeighborEnvelope(job as Object, outcome as Object) as Object
    status = EpisodeNeighborText(outcome, "status")
    if status <> "known" and status <> "verified_end" and status <> "retryable" and status <> "ambiguous" then status = "ambiguous"
    result = {
        status: status, provider: EpisodeNeighborText(job, "provider")
        sourceId: EpisodeNeighborText(job, "sourceId"), profileId: EpisodeNeighborText(job, "profileId")
        generation: EpisodeNeighborValue(job, "generation", -1), lookupId: EpisodeNeighborValue(job, "lookupId", "")
        anchorItemId: EpisodeNeighborText(job, "anchorItemId"), playbackSessionId: EpisodeNeighborText(job, "playbackSessionId")
    }
    direction = EpisodeNeighborValue(EpisodeNeighborValue(job,"params",{}),"direction","next")
    if direction = "previous" then result["direction"] = "previous"
    if status = "known"
        if direction = "previous" then result["detail"] = EpisodeNeighborValue(outcome,"detail",invalid)
        result["candidate"] = EpisodeNeighborValue(outcome, "candidate", invalid)
        result["proof"] = EpisodeNeighborValue(outcome, "proof", invalid)
    end if
    errorCode = EpisodeNeighborText(outcome, "errorCode")
    if errorCode <> "" then result["errorCode"] = EpisodeNeighborSafeError(errorCode)
    return result
end function

function EpisodeNeighborDeviceSession(provider as String, session as Object) as Object
    device = CreateObject("roDeviceInfo")
    session["deviceId"] = device.GetChannelClientId()
    session["model"] = device.GetModel()
    os = device.GetOSVersion()
    session["osVersion"] = os.major + "." + os.minor + "." + os.revision
    session["appVersion"] = RuntimeAppVersion()
    if provider = "plex" then session["clientId"] = session.deviceId
    return session
end function

function EpisodeNeighborElapsedMs() as Integer
    return m.neighborClock.TotalMilliseconds()
end function

' HttpRequest has a 1000 ms minimum and polls in 250 ms increments. Reserve
' that final polling interval instead of starting a request past the deadline.
function EpisodeNeighborAdmission(calls as Integer, elapsedMs as Integer) as Object
    remainingMs = 20000 - elapsedMs
    if calls >= 12 or remainingMs < 1250 then return {allowed: false, timeoutMs: 0, errorCode: "lookup_budget"}
    timeoutMs = remainingMs - 250
    if timeoutMs > 4000 then timeoutMs = 4000
    return {allowed: true, timeoutMs: timeoutMs}
end function

function EpisodeNeighborSessionMatches(provider as String, session as Object, scope as Object) as Boolean
    sourceId = EpisodeNeighborText(scope, "sourceId")
    if sourceId = "" or Left(sourceId, Len(provider) + 1) <> provider + ":" then return false
    profileId = EpisodeNeighborValue(scope, "profileId", invalid)
    if type(profileId) <> "String" and type(profileId) <> "roString" then return false
    return sourceId = SessionText(session, "sourceId") and profileId = SessionText(session, "profileId")
end function

function EpisodeNeighborAllowedAction(provider as String, action as String) as Boolean
    if action = "detail" then return true
    if provider = "plex" then return action = "children"
    return action = "seasons" or action = "episodes"
end function

' Preserve legacy endpoint normalization; previous reads reject contradictory
' explicit wire context and malformed pagination before that normalization.
function EpisodeNeighborPreviousSiloInventory(descriptor as Object, body as String) as Boolean
    action=EpisodeNeighborText(descriptor,"action")
    if action<>"episodes" and action<>"seasons" then return true
    decoded=ParseJson(body)
    if type(decoded)<>"roAssociativeArray" then return false
    items=EpisodeNeighborValue(decoded,"items",invalid)
    if type(items)<>"roArray" then return false
    maximum=192
    kind="episode"
    if action="seasons"
        maximum=96
        kind="season"
    end if
    if items.Count()>maximum then return false
    params=EpisodeNeighborValue(descriptor,"params",{})
    series=EpisodeNeighborText(params,"seriesId")
    for each item in items
        if type(item)<>"roAssociativeArray" then return false
        if item.DoesExist("type") and EpisodeNeighborText(item,"type")<>kind then return false
        if item.DoesExist("series_id") and EpisodeNeighborText(item,"series_id")<>series then return false
    end for
    page=EpisodeNeighborValue(decoded,"page",invalid)
    if page=invalid then return true
    if type(page)<>"roAssociativeArray" then return false
    if page.DoesExist("has_more")
        value=page.has_more
        if type(value)<>"Boolean" and type(value)<>"roBoolean" then return false
        if value then return false
    end if
    cursor=EpisodeNeighborValue(page,"next_cursor",invalid)
    if cursor<>invalid
        if type(cursor)<>"String" and type(cursor)<>"roString" then return false
        if cursor<>"" then return false
    end if
    return true
end function

function EpisodeNeighborDecode(provider as String, descriptor as Object, response as Object, sourceId as String) as Object
    action = EpisodeNeighborText(descriptor, "action")
    params = MergeSessionPatch(EpisodeNeighborValue(descriptor, "params", {}), {sourceId: sourceId})
    if provider = "plex"
        decoded = DecodePlexResponse(action, EpisodeNeighborText(response, "body"), params)
    else
        decoded = DecodeSiloResponse(action, EpisodeNeighborText(response, "body"), params)
    end if
    if decoded.ok <> true then return {ok: false, errorCode: EpisodeNeighborSafeError(EpisodeNeighborText(decoded, "errorCode"))}
    data = EpisodeNeighborValue(decoded, "data", {})
    ' Do not call ScopeCatalogData: it truncates items at 100 while retaining
    ' hasMore=false. Preserve completeness or reject an oversized inventory.
    items = EpisodeNeighborValue(data, "items", invalid)
    if items <> invalid
        if type(items) <> "roArray" then return {ok: false, errorCode: "invalid_response"}
        limit = 192
        if action = "seasons" then limit = 96
        if items.Count() > limit then return {ok: false, errorCode: "lookup_budget"}
        scopedItems = []
        for each item in items
            scoped = ScopedMediaItem(item, sourceId)
            scoped["provider"] = provider
            scopedItems.Push(scoped)
        end for
        data["items"] = scopedItems
    end if
    if data.DoesExist("item")
        data["item"] = ScopedMediaItem(data.item, sourceId)
        data.item["provider"] = provider
    end if
    if data.DoesExist("versions") then data["versions"] = ScopedMediaArray(data.versions, sourceId, 20)
    return {ok: true, data: data}
end function

function EpisodeNeighborExecute(job as Object) as Object
    m.neighborClock = CreateObject("roTimespan")
    m.neighborClock.Mark()
    provider = EpisodeNeighborText(job, "provider")
    if provider <> "plex" and provider <> "silo" then return EpisodeNeighborError("invalid_provider", "ambiguous")
    params = EpisodeNeighborValue(job, "params", {})
    direction = EpisodeNeighborValue(params,"direction","next")
    if type(direction) <> "String" and type(direction) <> "roString" then return EpisodeNeighborError("invalid_job","ambiguous")
    if direction <> "next" and direction <> "previous" then return EpisodeNeighborError("invalid_job","ambiguous")
    anchor = EpisodeNeighborValue(params, "anchor", invalid)
    if type(anchor) <> "roAssociativeArray" then return EpisodeNeighborError("invalid_job", "ambiguous")
    if EpisodeNeighborText(job, "anchorItemId") = "" or EpisodeNeighborText(job, "anchorItemId") <> EpisodeNeighborText(anchor, "itemId") then return EpisodeNeighborError("anchor_changed", "ambiguous")
    revision = SessionRevision(provider)
    session = LoadSession(provider)
    if not EpisodeNeighborSessionMatches(provider, session, job) then return EpisodeNeighborError("session_changed")
    if not PublicSessionStatus(provider, session).connected then return EpisodeNeighborError("auth_required")
    session = EpisodeNeighborDeviceSession(provider, session)
    state = EpisodeNeighborsStart(anchor, job, direction)
    calls = 0
    while true
        descriptor = EpisodeNeighborsRequest(state)
        if descriptor = invalid then exit while
        action = EpisodeNeighborText(descriptor, "action")
        if not EpisodeNeighborAllowedAction(provider, action) then return EpisodeNeighborError("unsupported_action", "ambiguous")
        if SessionRevision(provider) <> revision then return EpisodeNeighborError("session_changed")
        if not EpisodeNeighborSessionMatches(provider, LoadSession(provider), job) then return EpisodeNeighborError("session_changed")
        admission = EpisodeNeighborAdmission(calls, EpisodeNeighborElapsedMs())
        if not admission.allowed then return EpisodeNeighborError("lookup_budget")
        requestParams = EpisodeNeighborValue(descriptor, "params", {})
        if provider = "plex"
            request = BuildPlexRequest(action, session, requestParams)
        else
            request = BuildSiloRequest(action, session, requestParams)
        end if
        if request.ok <> true then return EpisodeNeighborError(EpisodeNeighborText(request, "errorCode"))
        calls += 1
        response = HttpRequest(request, admission.timeoutMs)
        if SessionRevision(provider) <> revision then return EpisodeNeighborError("session_changed")
        if not EpisodeNeighborSessionMatches(provider, LoadSession(provider), job) then return EpisodeNeighborError("session_changed")
        if EpisodeNeighborElapsedMs() >= 20000 then return EpisodeNeighborError("lookup_budget")
        if response.ok <> true then return EpisodeNeighborError(EpisodeNeighborText(response, "errorCode"))
        if provider="silo" and direction="previous"
            if not EpisodeNeighborPreviousSiloInventory(descriptor,EpisodeNeighborText(response,"body")) then return EpisodeNeighborError("incomplete_inventory","ambiguous")
        end if
        decoded = EpisodeNeighborDecode(provider, descriptor, response, EpisodeNeighborText(job, "sourceId"))
        state = EpisodeNeighborsResult(state, descriptor, decoded)
    end while
    if SessionRevision(provider) <> revision then return EpisodeNeighborError("session_changed")
    if not EpisodeNeighborSessionMatches(provider, LoadSession(provider), job) then return EpisodeNeighborError("session_changed")
    if EpisodeNeighborElapsedMs() >= 20000 then return EpisodeNeighborError("lookup_budget")
    return EpisodeNeighborsOutcome(state)
end function
