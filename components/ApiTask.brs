' A Task handles exactly one job. Its result excludes credentials, except the
' short-lived playback plan passed directly to Video without logging or storage.
sub init()
    m.top.functionName = "runJob"
end sub

sub runJob()
    m.siloPrivateLegacyStartPending = false
    m.siloPrivateLegacyAllocation = invalid
    m.siloPrivateLegacyStartIssued = false
    m.siloPrivateLegacyNonAllocating = false
    m.siloNativeStartIssued = false
    m.siloCompatContinuationIssued = false
    m.siloSubtitlePending = invalid
    m.siloRecoveryBudget = invalid
    m.siloRecoveryArtifact = invalid
    job = m.top.job
    if job = invalid then
        m.top.result = {ok: false, errorCode: "invalid_job"}
        return
    end if
    provider = TaskString(job, "provider")
    action = TaskString(job, "action")
    envelope = {provider: provider, action: action, sourceId: TaskString(job, "sourceId"), profileId: TaskString(job, "profileId"), generation: TaskValue(job, "generation", 0), requestId: TaskValue(job, "requestId", 0)}
    params = TaskValue(job, "params", {})
    if type(params) <> "roAssociativeArray" then params = {}
    ' Always finish a catchable worker failure through the same scoped result.
    ' Exception text may contain private values; only its numeric code is logged.
    try
        outcome = ExecuteApiAction(provider, action, params, job)
        if provider = "silo"
            outcome = TaskSiloRecoveryPublication(outcome,false)
            outcome = TaskSiloPrepareSelectedSubtitle(outcome,job)
        end if
        for each key in outcome
            envelope[key] = outcome[key]
        end for
    catch exception
        print "Silo API worker failed number="; exception.number
        envelope["ok"] = false
        envelope["errorCode"] = "task_failed"
        if provider = "plex" and (action = "pin_start" or action = "pin_poll") then envelope["authPhase"] = "worker"
    end try
    if m.apiSessionRevision <> invalid then envelope["sessionRevision"] = m.apiSessionRevision
    if provider = "silo" then envelope = TaskSiloRecoveryPublication(envelope,true)
    if m.siloPrivateLegacyStartIssued = true and envelope.ok <> true
        if SpField(envelope,"cleanupLeaseClosed") <> true and not SiloObject(SpField(envelope,"plan")) and m.siloPrivateLegacyNonAllocating <> true then envelope["leaseUncertain"] = true
    end if
    m.top.result = envelope
end sub

' Preview target reads never allocate playback. Candidate and leaf identities
' remain distinct, and every read is fenced by the captured source/profile.
function TaskPreviewScopeMatches(provider as String, session as Object, scope as Object, revision as Integer) as Boolean
    sourceId = TaskString(scope,"sourceId")
    profileId = TaskValue(scope,"profileId",invalid)
    if sourceId = "" or Left(sourceId,Len(provider)+1) <> provider + ":" then return false
    if type(profileId) <> "String" and type(profileId) <> "roString" then return false
    return SessionRevision(provider) = revision and sourceId = TaskString(session,"sourceId") and profileId = TaskString(session,"profileId")
end function

function TaskPreviewElapsedMs(context as Object) as Integer
    return context.clock.TotalMilliseconds()
end function

' Count actual HTTP calls, including refresh and retry, under one wall budget.
function TaskPreviewHttp(context as Object, request as Object) as Object
    provider = context.provider
    if not TaskPreviewScopeMatches(provider,LoadSession(provider),context.scope,context.revision) then return TaskError("session_changed")
    if request.ok <> true then return TaskError(TaskString(request,"errorCode"))
    remaining = 20000 - TaskPreviewElapsedMs(context)
    if context.calls >= 12 or remaining < 1250 then return TaskError("lookup_budget")
    timeout = Int(remaining - 250)
    if timeout > 4000 then timeout = 4000
    context.calls = context.calls + 1
    response = HttpRequest(request,timeout)
    if not TaskPreviewScopeMatches(provider,LoadSession(provider),context.scope,context.revision) then return TaskError("session_changed")
    if TaskPreviewElapsedMs(context) >= 20000 then return TaskError("lookup_budget")
    return response
end function

function TaskPreviewRead(context as Object, action as String, params as Object) as Object
    provider = context.provider
    response = TaskPreviewHttp(context,TaskBuildRequest(provider,action,context.session,params))
    if provider = "silo" and TaskString(response,"errorCode") = "auth_required" and TaskString(context.session,"refreshToken") <> ""
        refreshed = TaskPreviewHttp(context,BuildSiloRequest("refresh",context.session,{}))
        if refreshed.ok <> true then return refreshed
        decodedRefresh = DecodeSiloResponse("refresh",refreshed.body,{})
        if decodedRefresh.ok <> true or not decodedRefresh.DoesExist("session") then return TaskError("auth_required")
        updated = TaskSavePatch("silo",context.session,decodedRefresh.session,context.revision)
        if updated = invalid then return TaskError("session_changed")
        context.session = updated
        response = TaskPreviewHttp(context,BuildSiloRequest(action,context.session,params))
    end if
    if response.ok <> true
        if provider = "silo" then return TaskSiloHttpError(response)
        return TaskError(TaskString(response,"errorCode"))
    end if
    ' The collection decoder supplies omitted parent/type fields from its
    ' endpoint context. Reject explicit contradictions before that projection.
    if provider = "silo" and (action = "seasons" or action = "episodes")
        raw = ParseJson(response.body)
        if not SiloObject(raw) or not SiloArray(raw.items) then return TaskError("invalid_inventory")
        expectedKind = "season"
        if action = "episodes" then expectedKind = "episode"
        for each child in raw.items
            if not SiloObject(child) then return TaskError("invalid_inventory")
            if SiloText(child.series_id) <> "" and SiloText(child.series_id) <> TaskString(params,"seriesId") then return TaskError("invalid_inventory")
            if SiloText(child.type) <> "" and SiloText(child.type) <> expectedKind then return TaskError("invalid_inventory")
            if action = "episodes" and SiloNumber(child.season_number,-1) <> TaskValue(params,"seasonNumber",-1) then return TaskError("invalid_inventory")
        end for
    end if
    decoded = TaskDecode(provider,action,response.body,MergeSessionPatch(params,{sourceId:TaskString(context.scope,"sourceId")}))
    if decoded.ok <> true then return TaskError(TaskString(decoded,"errorCode"))
    return {ok:true,data:decoded.data,body:response.body}
end function

' Only the first declared Plex OnDeck reference may become the native target.
function TaskPreviewPlexDeclared(body as String) as Object
    raw = ParseJson(body)
    metadata = PlexArray(PlexField(PlexField(raw,"MediaContainer"),"Metadata"))
    if metadata.Count() = 0 then return {declared:false,itemId:""}
    current = PlexField(metadata[0],"OnDeck")
    for depth = 0 to 5
        if current = invalid then return {declared:false,itemId:""}
        if type(current) = "roArray"
            if current.Count() = 0 then return {declared:false,itemId:""}
            current = current[0]
        else if type(current) = "roAssociativeArray"
            if current.DoesExist("Metadata")
                current = current.Metadata
            else
                itemId = PlexText(PlexField(current,"ratingKey"))
                if not PlexIdentifier(itemId) then return {declared:true,itemId:""}
                return {declared:true,itemId:itemId}
            end if
        else
            return {declared:true,itemId:""}
        end if
    end for
    return {declared:true,itemId:""}
end function

function TaskPreviewSeriesId(provider as String, item as Object) as String
    if provider = "plex" then return TaskString(item,"seriesItemId")
    return TaskString(item,"seriesId")
end function

function TaskPreviewNormalEpisode(provider as String, item as Object, showId as String) as Boolean
    season = TaskValue(item,"seasonNumber",-1)
    episode = TaskValue(item,"episodeNumber",-1)
    return TaskString(item,"type") = "episode" and TaskPreviewSeriesId(provider,item) = showId and season > 0 and season = Int(season) and episode > 0 and episode = Int(episode)
end function

function TaskPreviewFreshTarget(context as Object, itemId as String, kind as String, candidateId as String, seed = invalid as Dynamic) as Object
    fresh = TaskPreviewRead(context,"detail",{itemId:itemId})
    if fresh.ok <> true then return fresh
    data = TaskValue(fresh,"data",{})
    item = TaskValue(data,"item",{})
    if TaskString(item,"itemId") <> itemId or TaskString(item,"type") <> kind then return TaskError("preview_unavailable")
    if TaskValue(data,"versions",[]).Count() = 0 and TaskValue(context,"allowEmptyTarget",false) <> true then return TaskError("preview_unavailable")
    if candidateId <> itemId and not TaskPreviewNormalEpisode(context.provider,item,candidateId) then return TaskError("preview_unavailable")
    if seed <> invalid
        if TaskValue(item,"seasonNumber",-1) <> TaskValue(seed,"seasonNumber",-1) or TaskValue(item,"episodeNumber",-1) <> TaskValue(seed,"episodeNumber",-1) then return TaskError("preview_unavailable")
        if context.provider = "plex" and TaskString(item,"seasonItemId") <> TaskString(seed,"seasonItemId") then return TaskError("preview_unavailable")
    end if
    data = ScopeCatalogData(data,TaskString(context.scope,"sourceId"))
    data["candidateItemId"] = candidateId
    return {ok:true,data:data}
end function

' Complete bounded native directories are required before selecting a fallback.
' Silo has no proven paging parameter here; Plex advances by raw consumed slots.
function TaskPreviewInventory(context as Object, action as String, params as Object) as Object
    items = []
    seen = {}
    params = MergeSessionPatch(params,{offset:0,limit:48})
    while true
        page = TaskPreviewRead(context,action,params)
        if page.ok <> true then return page
        data = TaskValue(page,"data",{})
        for each item in TaskValue(data,"items",[])
            itemId = TaskString(item,"itemId")
            if itemId = "" or seen.DoesExist(itemId) then return TaskError("invalid_inventory")
            seen[itemId] = true
            if items.Count() >= 192 then return TaskError("lookup_budget")
            items.Push(item)
        end for
        if context.provider = "silo"
            if TaskValue(data,"hasMore",false) or TaskString(data,"nextCursor") <> "" then return TaskError("incomplete_inventory")
            return {ok:true,items:items}
        end if
        if TaskValue(data,"rawCount",0) <> TaskValue(data,"items",[]).Count() then return TaskError("invalid_inventory")
        if TaskValue(data,"totalKnown",false) and params.offset + TaskValue(data,"rawCount",0) < TaskValue(data,"totalSize",0) and TaskValue(data,"hasMore",false) <> true then return TaskError("incomplete_inventory")
        if TaskValue(data,"hasMore",false) <> true then return {ok:true,items:items}
        nextOffset = TaskValue(data,"nextOffset",-1)
        if TaskValue(data,"rawCount",0) <= 0 or nextOffset <> params.offset + data.rawCount then return TaskError("incomplete_inventory")
        params.offset = nextOffset
    end while
end function

function TaskPreviewBefore(left as Object, right as Object) as Boolean
    if left.seasonNumber <> right.seasonNumber then return left.seasonNumber < right.seasonNumber
    return TaskValue(left,"episodeNumber",0) < TaskValue(right,"episodeNumber",0)
end function

function TaskPreviewOrdered(items as Object) as Object
    ordered = []
    for each item in items
        inserted = false
        nextItems = []
        for each current in ordered
            if not inserted and TaskPreviewBefore(item,current)
                nextItems.Push(item)
                inserted = true
            end if
            nextItems.Push(current)
        end for
        if not inserted then nextItems.Push(item)
        ordered = nextItems
    end for
    return ordered
end function

function TaskPreviewDetail(provider as String, session as Object, params as Object, scope as Object, revision as Integer, allowEmptyTarget = false as Boolean) as Object
    if not TaskPreviewScopeMatches(provider,session,scope,revision) then return TaskError("session_changed")
    kind = TaskString(params,"type")
    if provider = "silo" and kind = "series" then kind = "show"
    itemId = TaskString(params,"itemId")
    if kind <> "movie" and kind <> "episode" and kind <> "show" then return TaskError("preview_unavailable")
    if itemId = "" then return TaskError("item_required")
    context = {provider:provider,session:session,scope:scope,revision:revision,clock:CreateObject("roTimespan"),calls:0,allowEmptyTarget:allowEmptyTarget}
    context.clock.Mark()
    if kind <> "show" then return TaskPreviewFreshTarget(context,itemId,kind,itemId)
    show = TaskPreviewRead(context,"detail",{itemId:itemId})
    if show.ok <> true then return show
    showItem = TaskValue(show.data,"item",{})
    showKind = TaskString(showItem,"type")
    if provider = "silo" and showKind = "series" then showKind = "show"
    if TaskString(showItem,"itemId") <> itemId or showKind <> "show" then return TaskError("preview_unavailable")
    declared = {declared:TaskString(showItem,"playItemId") <> "",itemId:TaskString(showItem,"playItemId")}
    if provider = "plex" then declared = TaskPreviewPlexDeclared(show.body)
    if declared.declared
        if declared.itemId = "" or declared.itemId = itemId then return TaskError("preview_unavailable")
        return TaskPreviewFreshTarget(context,declared.itemId,"episode",itemId)
    end if
    action = "children"
    seasonParams = {itemId:itemId}
    if provider = "silo"
        action = "seasons"
        seasonParams = {seriesId:itemId}
    end if
    inventory = TaskPreviewInventory(context,action,seasonParams)
    if inventory.ok <> true then return inventory
    seasons = []
    seenNumbers = {}
    for each season in inventory.items
        number = TaskValue(season,"seasonNumber",-1)
        if TaskString(season,"type") <> "season" or TaskPreviewSeriesId(provider,season) <> itemId then return TaskError("invalid_inventory")
        if number < 0 or number <> Int(number) then return TaskError("invalid_inventory")
        if number > 0
            if seenNumbers.DoesExist(number.ToStr()) then return TaskError("invalid_inventory")
            seenNumbers[number.ToStr()] = true
            seasons.Push(season)
        end if
    end for
    episodes = []
    seenEpisodes = {}
    seenEpisodeIds = {}
    for each season in TaskPreviewOrdered(seasons)
        action = "children"
        episodeParams = {itemId:TaskString(season,"itemId")}
        if provider = "silo"
            action = "episodes"
            episodeParams = {seriesId:itemId,seasonNumber:season.seasonNumber}
        end if
        inventory = TaskPreviewInventory(context,action,episodeParams)
        if inventory.ok <> true then return inventory
        for each episode in inventory.items
            if not TaskPreviewNormalEpisode(provider,episode,itemId) or episode.seasonNumber <> season.seasonNumber then return TaskError("invalid_inventory")
            if provider = "plex" and TaskString(episode,"seasonItemId") <> TaskString(season,"itemId") then return TaskError("invalid_inventory")
            identity = episode.seasonNumber.ToStr() + ":" + episode.episodeNumber.ToStr()
            if seenEpisodes.DoesExist(identity) or seenEpisodeIds.DoesExist(TaskString(episode,"itemId")) or episodes.Count() >= 192 then return TaskError("invalid_inventory")
            seenEpisodes[identity] = true
            seenEpisodeIds[TaskString(episode,"itemId")] = true
            episodes.Push(episode)
        end for
        ' Earlier normal seasons are complete. A known resume in this complete
        ' season is authoritative without loading unrelated later directories.
        for each episode in TaskPreviewOrdered(inventory.items)
            if TaskValue(episode,"resumeMs",0) > 0 and TaskValue(episode,"watched",false) <> true then return TaskPreviewFreshTarget(context,TaskString(episode,"itemId"),"episode",itemId,episode)
        end for
    end for
    episodes = TaskPreviewOrdered(episodes)
    chosen = invalid
    for each episode in episodes
        if TaskValue(episode,"watched",false) <> true
            chosen = episode
            exit for
        end if
    end for
    if chosen = invalid then return TaskError("preview_unavailable")
    return TaskPreviewFreshTarget(context,TaskString(chosen,"itemId"),"episode",itemId,chosen)
end function

function TaskValue(data as Object, key as String, fallback as Dynamic) as Dynamic
    if data <> invalid and data.DoesExist(key) and data[key] <> invalid then return data[key]
    return fallback
end function

function TaskString(data as Object, key as String) as String
    value = TaskValue(data, key, "")
    if type(value) = "roString" or type(value) = "String" then return value
    return ""
end function

function TaskError(code as String) as Object
    return {ok: false, errorCode: code}
end function

' Only a bounded numeric transport status leaves the worker during linking.
' Native failure text and response bodies can contain private URLs or tokens.
function TaskAuthTransportFailure(provider as String, action as String, response as Object, code as String, phase = "http" as String) as Object
    failure = TaskError(code)
    authAction = (provider = "plex" and (action = "pin_start" or action = "pin_poll")) or (provider = "silo" and (action = "device_capability" or action = "device_start" or action = "device_poll"))
    if not authAction then return failure
    if provider = "plex"
        if phase = "build" or phase = "http" or phase = "decode" then failure["authPhase"] = phase
    end if
    status = TaskValue(response, "statusCode", invalid)
    kind = type(status)
    if kind = "Integer" or kind = "roInt" or kind = "roInteger" or kind = "LongInteger" or kind = "roLongInteger"
        if (status < 0 and status >= -999) or (status >= 100 and status <= 599) then failure["transportStatus"] = status
    end if
    return failure
end function

' Plex final progress and transcode release are independent required deliveries.
' Retain the failed phase and bounded status without forwarding native text.
function TaskPlexDeliveryFailure(phase as String, response as Object) as Object
    failure = TaskError(TaskString(response,"errorCode"))
    if phase <> "timeline" and phase <> "transcode_stop" then return failure
    failure["deliveryPhase"] = phase
    status = TaskValue(response,"statusCode",invalid)
    kind = type(status)
    if kind = "Integer" or kind = "roInt" or kind = "roInteger" or kind = "LongInteger" or kind = "roLongInteger"
        if (status < 0 and status >= -999) or (status >= 100 and status <= 599)
            failure["transportStatus"] = status
            failure["statusCode"] = status
        end if
    end if
    return failure
end function

' HTTP status controls refresh/retry. Only whitelisted problem types leave
' this Task; title, detail, instance and the raw body never enter scene state.
function TaskSiloHttpError(response as Object) as Object
    status = TaskValue(response, "statusCode", 0)
    fallback = TaskString(response, "errorCode")
    if status = 401 or status = 408 or status = 425 or status = 429 or status >= 500 then return TaskError(HttpErrorCode(status))
    if status < 400 then return TaskError(fallback)
    body = TaskString(response, "body")
    if not HttpErrorBodyWithinLimit(body, 8192) then return TaskError(fallback)
    problem = ParseJson(body)
    if not SiloObject(problem) then return TaskError(fallback)
    if SiloNumber(problem.status, -1) <> status or SiloText(problem.type) = "" then return TaskError(fallback)
    decoded = DecodeSiloResponse("http_error", body, {})
    return TaskError(TaskString(decoded, "errorCode"))
end function

function TaskNowMs() as Double
    date = CreateObject("roDateTime")
    return date.AsSeconds() * 1000#
end function

function TaskUniqueId() as String
    device = CreateObject("roDeviceInfo")
    return "roku-" + device.GetRandomUUID()
end function

function TaskDeviceSession(provider as String, session as Object) as Object
    device = CreateObject("roDeviceInfo")
    session["deviceId"] = device.GetChannelClientId()
    session["model"] = device.GetModel()
    os = device.GetOSVersion()
    session["osVersion"] = os.major + "." + os.minor + "." + os.revision
    session["appVersion"] = RuntimeAppVersion()
    if provider = "plex" then session["clientId"] = session["deviceId"]
    return session
end function

function TaskSavePatch(provider as String, session as Object, patch as Object, revision as Integer) as Object
    updated = MergeSessionPatch(session, patch)
    if not SaveSession(provider, updated, revision) then return invalid
    return updated
end function


' Development-only inventory evidence. No result here acknowledges a lease.
function TaskPlexProbeInteger(value as Dynamic, maximum as Integer) as Integer
    kind = type(value)
    if kind <> "Integer" and kind <> "roInt" and kind <> "roInteger" and kind <> "LongInteger" and kind <> "roLongInteger" and kind <> "Double" and kind <> "roDouble" and kind <> "Float" and kind <> "roFloat" then return -1
    if value <> value or value < 0 or value > maximum then return -1
    if value <> Int(value) then return -1
    return Int(value)
end function

function TaskPlexProbeKind(value as Dynamic) as String
    kind = type(value)
    if kind = "roAssociativeArray" then return "object"
    if kind = "roArray" then return "array"
    if kind = "String" or kind = "roString" then return "string"
    if kind = "Boolean" or kind = "roBoolean" then return "boolean"
    if value = invalid then return "invalid"
    if kind = "Integer" or kind = "roInt" or kind = "roInteger" or kind = "LongInteger" or kind = "roLongInteger" then return "integer"
    if kind = "Double" or kind = "roDouble" or kind = "Float" or kind = "roFloat" then return "number"
    return "other"
end function

' Names are local literals; unknown wire names are counted and never copied.
function TaskPlexProbeFields(value as Dynamic, names as Object, maximum as Integer) as Object
    result = {values:{},keys:[],unknown:0,overflow:false,collision:false}
    if type(value) <> "roAssociativeArray" then return result
    allowed = {}
    for each name in names
        allowed[LCase(name)] = name
    end for
    count = 0
    for each name in value
        count++
        if count > maximum
            result.overflow = true
            return result
        end if
        canonical = invalid
        if Len(name) <= 128 then canonical = allowed[LCase(name)]
        if canonical = invalid
            result.unknown++
        else if result.values.DoesExist(canonical)
            result.collision = true
        else
            result.values[canonical] = value[name]
            result.keys.Push({name:canonical,kind:TaskPlexProbeKind(value[name])})
        end if
    end for
    return result
end function

function TaskPlexInventoryDiagnostic(response as Object, expected as String, stage as String, scopeValid as Boolean) as Object
    if stage <> "transcode_stop" then stage = "rendered"
    status = TaskValue(response,"statusCode",invalid)
    httpStatus = -1
    kind = type(status)
    if kind = "Integer" or kind = "roInt" or kind = "roInteger" or kind = "LongInteger" or kind = "roLongInteger"
        if (status >= 100 and status <= 599) or (status <= -1 and status >= -999) then httpStatus = Int(status)
    end if
    out = {stage:stage,httpStatus:httpStatus,scopeValid:scopeValid,format:"none",rootKind:"invalid",containerKind:"invalid",rootKeys:[],containerKeys:[],entryKeys:[],unknownRootKeys:0,unknownContainerKeys:0,unknownEntryKeys:0,recordsKind:"absent",recordsCount:0,invalidIdentityRows:0,conflictingIdentityRows:0,size:-1,totalSize:-1,offset:-1,headerTotalSize:-1,headerOffset:-1,headerValid:false,countMatches:false,fullnessKnown:false,completeShape:false,expectedIdMatch:false,expectedKeyMatch:false,absenceTrusted:false}
    if not scopeValid then return out
    headers = TaskValue(response,"plexContainerHeaders",invalid)
    if type(headers) = "roAssociativeArray"
        if TaskValue(headers,"valid",false) = true
            out["headerValid"] = true
            out["headerTotalSize"] = TaskPlexProbeInteger(TaskValue(headers,"totalSize",invalid),2147483647)
            out["headerOffset"] = TaskPlexProbeInteger(TaskValue(headers,"offset",invalid),2147483647)
        end if
    end if
    body = TaskString(response,"body")
    if Len(body) > 32768
        out["format"] = "body_budget"
        return out
    end if
    if body = "" then return out
    if Left(body.Trim(),1) = "<"
        out["format"] = "xml"
        return out
    end if
    root = ParseJson(body)
    if root = invalid
        out["format"] = "invalid_json"
        return out
    end if
    out["format"] = "json"
    out["rootKind"] = TaskPlexProbeKind(root)
    rootFields = TaskPlexProbeFields(root,["MediaContainer"],8)
    out["rootKeys"] = rootFields.keys
    out["unknownRootKeys"] = rootFields.unknown
    container = rootFields.values.MediaContainer
    out["containerKind"] = TaskPlexProbeKind(container)
    containerFields = TaskPlexProbeFields(container,["size","totalSize","offset","TranscodeSession","identifier","Metadata","TranscodeJob"],48)
    out["containerKeys"] = containerFields.keys
    out["unknownContainerKeys"] = containerFields.unknown
    fields = containerFields.values
    out["size"] = TaskPlexProbeInteger(fields.size,2147483647)
    out["totalSize"] = TaskPlexProbeInteger(fields.totalSize,2147483647)
    out["offset"] = TaskPlexProbeInteger(fields.offset,2147483647)
    rows = fields.TranscodeSession
    out["recordsKind"] = TaskPlexProbeKind(rows)
    if rows = invalid then out["recordsKind"] = "absent"
    recordBudget = false
    rowCollision = false
    schemaKinds = {}
    if type(rows) = "roArray"
        out["recordsCount"] = rows.Count()
        if rows.Count() > 64
            recordBudget = true
        else
            names = ["id","key","throttled","complete","progress","size","speed","error","duration","remaining","context","protocol","container","videoDecision","audioDecision","sourceVideoCodec","sourceAudioCodec","videoCodec","audioCodec","audioChannels","transcodeHwRequested","transcodeHwDecoding","transcodeHwEncoding","transcodeHwFullPipeline","timeStamp","minOffsetAvailable","maxOffsetAvailable"]
            for each row in rows
                projected = TaskPlexProbeFields(row,names,64)
                out["unknownEntryKeys"] += projected.unknown
                if projected.collision or projected.overflow then rowCollision = true
                for each key in projected.keys
                    previous = TaskString(schemaKinds,key.name)
                    if previous = "" then schemaKinds[key.name] = key.kind
                    if previous <> "" and previous <> key.kind then schemaKinds[key.name] = "mixed"
                end for
                id = TaskString(projected.values,"id")
                key = TaskString(projected.values,"key")
                keyId = ""
                prefix = "/transcode/sessions/"
                if Len(key) <= 128 and PlexIdentifier(key) then keyId = key
                if Left(key,Len(prefix)) = prefix
                    suffix = Mid(key,Len(prefix)+1)
                    if Len(suffix) <= 128 and PlexIdentifier(suffix) then keyId = suffix
                end if
                validId = Len(id) <= 128 and PlexIdentifier(id)
                if type(row) <> "roAssociativeArray" or (not validId and keyId = "") then out["invalidIdentityRows"]++
                if validId and keyId <> "" and id <> keyId then out["conflictingIdentityRows"]++
                if not projected.collision and not projected.overflow
                    if validId and id = expected then out["expectedIdMatch"] = true
                    if keyId <> "" and keyId = expected then out["expectedKeyMatch"] = true
                end if
            end for
        end if
    else if rows <> invalid
        out["invalidIdentityRows"] = 1
    end if
    for each name in schemaKinds
        out.entryKeys.Push({name:name,kind:schemaKinds[name]})
    end for
    out["countMatches"] = out.size >= 0 and out["size"] = out.recordsCount and (out["recordsKind"] = "array" or out["recordsKind"] = "absent")
    out["completeShape"] = out["rootKind"] = "object" and out["containerKind"] = "object" and out["unknownRootKeys"] = 0 and out.unknownContainerKeys = 0 and out.unknownEntryKeys = 0 and not rootFields.overflow and not rootFields.collision and not containerFields.overflow and not containerFields.collision and not rowCollision and not recordBudget and out["invalidIdentityRows"] = 0 and out["conflictingIdentityRows"] = 0 and fields.Metadata = invalid and fields.TranscodeJob = invalid and out.countMatches
    total = out.totalSize
    offset = out.offset
    consistent = headers = invalid or out.headerValid
    if out.headerTotalSize >= 0
        if total >= 0 and total <> out.headerTotalSize then consistent = false
        total = out.headerTotalSize
    end if
    if out.headerOffset >= 0
        if offset >= 0 and offset <> out.headerOffset then consistent = false
        offset = out.headerOffset
    end if
    out["fullnessKnown"] = httpStatus = 200 and out.completeShape and consistent and total >= 0 and total = out.recordsCount and offset = 0
    return out
end function

function TaskPlexProbeOwnerValid(owner as Dynamic, params as Object, scope as Object, revision as Integer) as Boolean
    if type(owner) <> "roAssociativeArray" then return false
    ownerScope = TaskValue(owner,"scope",invalid)
    if type(ownerScope) <> "roAssociativeArray" then return false
    if TaskString(scope,"provider") <> "plex" then return false
    if TaskPlexProbeInteger(TaskValue(scope,"generation",invalid),2147483646) < 0 then return false
    for each name in ["provider","sourceId","profileId","generation"]
        if TaskValue(ownerScope,name,invalid) <> TaskValue(scope,name,invalid) then return false
    end for
    id = TaskString(params,"transcodeSessionId")
    if Len(id) > 128 or not PlexIdentifier(id) or TaskString(owner,"transcodeSessionId") <> id then return false
    if TaskPlexProbeInteger(TaskValue(params,"sessionRevision",invalid),2147483646) <> revision then return false
    if TaskPlexProbeInteger(TaskValue(owner,"sessionRevision",invalid),2147483646) <> revision then return false
    if TaskPlexProbeInteger(TaskValue(owner,"clipId",invalid),2147483646) < 0 then return false
    for each name in ["attemptId","versionId"]
        value = TaskString(owner,name)
        if value = "" or Len(value) > 512 or Instr(1,value,"://") > 0 then return false
        if CreateObject("roRegex","[\x00-\x1f\x7f]","").IsMatch(value) then return false
    end for
    return true
end function

function TaskPlexProbeSessionMatches(captured as Object, scope as Object, revision as Integer) as Boolean
    current = LoadSession("plex")
    if not TaskPreviewScopeMatches("plex",current,scope,revision) then return false
    for each name in ["sourceId","profileId","accountId","baseUrl","token","accountToken"]
        if TaskString(captured,name) <> TaskString(current,name) then return false
    end for
    return true
end function

function TaskPlexInventoryProbe(session as Object, params as Object, scope as Object, revision as Integer, stage as String, owner as Dynamic) as Object
    captured = MergeSessionPatch({},session)
    invalidDiagnostic = TaskPlexInventoryDiagnostic({},TaskString(params,"transcodeSessionId"),stage,false)
    if not TaskPlexProbeOwnerValid(owner,params,scope,revision) then return {ok:false,errorCode:"invalid_request",inventoryDiagnostic:invalidDiagnostic}
    if not TaskPlexProbeSessionMatches(captured,scope,revision) then return {ok:false,errorCode:"session_changed",inventoryDiagnostic:invalidDiagnostic}
    request = BuildPlexRequest("transcode_inventory",captured,{})
    if request.ok <> true then return {ok:false,errorCode:TaskString(request,"errorCode"),inventoryDiagnostic:invalidDiagnostic}
    response = HttpRequest(request,2000)
    if not TaskPlexProbeSessionMatches(captured,scope,revision)
        return {ok:false,errorCode:"session_changed",inventoryDiagnostic:TaskPlexInventoryDiagnostic(response,TaskString(params,"transcodeSessionId"),stage,false)}
    end if
    diagnostic = TaskPlexInventoryDiagnostic(response,TaskString(params,"transcodeSessionId"),stage,true)
    if response.ok <> true then return {ok:false,errorCode:TaskString(response,"errorCode"),inventoryDiagnostic:diagnostic}
    return {ok:true,inventoryDiagnostic:diagnostic}
end function

function ExecuteApiAction(provider as String, action as String, params as Object, scope as Object) as Object
    if provider <> "plex" and provider <> "silo" then return TaskError("invalid_provider")
    revision = SessionRevision(provider)
    m.apiSessionRevision = revision
    if TaskValue(scope,"sessionRevision",revision) <> revision then return TaskError("session_changed")
    session = LoadSession(provider)
    if action = "decision_pref_get" or action = "decision_pref_set" or action = "still_watching" then return TaskRunDecisionGateway(provider,action,session,params,scope,revision)
    if action = "track_pref_get" or action = "track_pref_set" then return TaskRunTrackPreference(provider,action,session,params,scope,revision)
    if TaskIsMetadataAction(action) then return TaskRunMetadata(provider, action, session, params, scope, revision)
    session = TaskDeviceSession(provider, session)

    if action <> "session_status"
        expectedSource = TaskString(scope, "sourceId")
        expectedProfile = TaskString(scope, "profileId")
        if expectedSource <> "" and expectedSource <> TaskString(session, "sourceId") then return TaskError("session_changed")
        if expectedProfile <> "" and expectedProfile <> TaskString(session, "profileId") then return TaskError("session_changed")
    end if

    if provider = "silo" and action = "compat_handoff_approve"
        approvalScope = SpScope(scope)
        if approvalScope = invalid then return TaskError("session_changed")
        if not TaskPreviewScopeMatches("silo",session,approvalScope,revision) then return TaskError("session_changed")
    end if

    if provider = "silo" and action = "playback_error_report" then return TaskSiloPlaybackErrorReport(session,params,scope,revision)
    if action = "transcode_probe"
        if provider <> "plex" then return TaskError("invalid_provider")
        if TaskString(params,"stage") <> "rendered" then return TaskError("invalid_request")
        return TaskPlexInventoryProbe(session,params,scope,revision,"rendered",TaskValue(scope,"inventoryOwner",invalid))
    end if
    if provider = "plex" and action = "image_context" then return TaskPlexImageContext(session, revision)
    if action = "session_status" then return {ok: true, data: PublicSessionStatus(provider, session)}
    if action = "sign_out"
        if not ClearSession(provider) then return TaskError("storage_error")
        return {ok: true, data: PublicSessionStatus(provider, {})}
    end if
    if provider = "silo" and action = "set_server" then return TaskSetSiloServer(session, params, revision)
    if provider = "silo" and action = "select_profile" then return TaskSelectSiloProfile(session, params, revision)
    if provider = "plex" and action = "select_server" then return TaskSelectPlexServer(session, params, revision)
    if provider = "plex" and action = "watchlist_resolve" then return TaskResolvePlexWatchlist(session, params, revision)
    if action = "experimental_playback_probe"
        if provider <> "silo" then return TaskError("invalid_provider")
        return TaskSiloExperimentalProbe(session,params,revision)
    end if
    if action = "playback_audio_select"
        if provider <> "silo" then return TaskError("invalid_provider")
        return TaskSelectSiloAudio(session,params,scope,revision)
    end if
    if action = "playback_seek_reanchor"
        if provider <> "silo" then return TaskError("invalid_provider")
        return TaskSeekSiloPlayback(session,params,scope,revision)
    end if
    if action = "playback_subtitle_select"
        if provider <> "silo" then return TaskError("invalid_provider")
        return TaskSelectSiloSubtitle(session,params,scope,revision)
    end if
    if action = "playback_subtitle_off"
        if provider <> "silo" then return TaskError("invalid_provider")
        return TaskSelectSiloSubtitleOff(session,params,scope,revision)
    end if
    if action = "playback_replan"
        if provider <> "silo" then return TaskError("invalid_provider")
        return TaskReplanSiloPlayback(session,params,scope,revision)
    end if
    if provider = "silo" and Left(action,6) = "audio_" and action <> "audio_pref_set" then return TaskAudioAction(session,action,params,scope,revision)
    if provider = "silo" and Left(action,6) = "ebook_" then return TaskEbookAction(session,action,params,scope,revision)
    if action = "preview_detail" then return TaskPreviewDetail(provider, session, params, scope, revision)
    if action = "playback_detail" and provider = "silo" then return TaskPreviewDetail(provider, session, params, scope, revision, true)
    if action = "playback_start" then return TaskStartPlayback(provider, session, params, revision)
    if action = "playback_stop" or action = "playback_progress" then return TaskPlaybackEvent(provider, session, action, params, revision, scope)
    if provider = "plex" and TaskIsPlexWatchlistAction(action)
        account = TaskEnsurePlexWatchlistAccount(session, revision)
        if account.ok <> true then return account
        session = account.session
    end if
    if provider = "silo" and action = "device_poll" and TaskString(params, "deviceCode") = "" then params["deviceCode"] = TaskString(session, "deviceCode")

    discoveryIdentity = invalid
    if provider = "silo" and (action = "compat_connect_info" or action = "compat_handoff_approve")
        discoveryIdentity = {sourceId:TaskString(session,"sourceId"),baseUrl:TaskString(session,"baseUrl"),accessToken:TaskString(session,"accessToken")}
        if action = "compat_handoff_approve"
            discoveryIdentity["profileId"] = TaskString(session,"profileId")
            discoveryIdentity["profileToken"] = TaskString(session,"profileToken")
        end if
    end if
    refreshIdentity = invalid
    if provider = "silo" then refreshIdentity = {sourceId:TaskString(session,"sourceId"),profileId:TaskString(session,"profileId"),profileToken:TaskString(session,"profileToken"),baseUrl:TaskString(session,"baseUrl")}
    request = TaskBuildRequest(provider, action, session, params)
    if request.ok <> true then return TaskAuthTransportFailure(provider, action, {}, TaskString(request, "errorCode"), "build")
    response = HttpRequest(request)
    if response.ok <> true and provider = "silo" and response.errorCode = "auth_required" and action <> "refresh" and action <> "home_sections_save" and action <> "home_sections_reset"
        if not TaskSiloApprovalIdentityCurrent(refreshIdentity,revision) then return TaskError("session_changed")
        if m.top <> invalid then if m.top.cancelled = true then return TaskError("cancelled")
        approvalIdentity = refreshIdentity
        if action = "compat_handoff_approve" then approvalIdentity = discoveryIdentity
        refreshed = TaskRefreshSilo(session, revision, invalid, approvalIdentity)
        ' A refused stale refresh must not expire the newer profile in Scene.
        if not TaskSiloApprovalIdentityCurrent(refreshIdentity,revision) then return TaskError("session_changed")
        if refreshed = invalid
            if not TaskSiloApprovalIdentityCurrent(approvalIdentity,revision) then return TaskError("session_changed")
        end if
        if m.top <> invalid then if m.top.cancelled = true then return TaskError("cancelled")
        if refreshed <> invalid
            session = refreshed
            if discoveryIdentity <> invalid
                if action = "compat_handoff_approve"
                    discoveryIdentity["accessToken"] = TaskString(session,"accessToken")
                else
                    discoveryIdentity.accessToken = TaskString(session,"accessToken")
                end if
            end if
            request = TaskBuildRequest(provider, action, session, params)
            if request.ok then response = HttpRequest(request)
        end if
    end if
    if provider = "silo" and Left(action,14) = "home_sections_"
        if not TaskPreviewScopeMatches(provider,LoadSession(provider),scope,revision) then return TaskError("session_changed")
    end if
    if response.ok <> true
        ' Plex removes expired PINs server-side before the local deadline.
        if provider = "plex" and action = "pin_poll" and TaskValue(response, "statusCode", 0) = 404 then return {ok: true, data: {state: "expired"}}
        ' A missing pairing capability route can mean an older Silo API or a
        ' wrong base address. Keep this distinct from a missing catalog item.
        if provider = "silo" and action = "device_capability" and TaskValue(response, "statusCode", 0) = 404 then return TaskAuthTransportFailure(provider, action, response, "silo_api_unavailable")
        if provider = "silo" then return TaskAuthTransportFailure(provider, action, response, TaskString(TaskSiloHttpError(response), "errorCode"))
        return TaskAuthTransportFailure(provider, action, response, TaskString(response, "errorCode"))
    end if

    decodeParams = MergeSessionPatch(params, {sourceId: TaskString(session, "sourceId"), accountId: TaskString(session, "accountId"), nowMs: TaskNowMs()})
    if provider = "silo" and action = "compat_connect_info" then decodeParams.baseUrl = TaskString(session,"baseUrl")
    if provider = "silo" and Left(action,8) = "service_" then decodeParams.etag = TaskString(response,"etag")
    if provider = "silo" and (action = "home_sections_save" or action = "home_sections_reset" or action = "settings_reset" or action = "compat_handoff_approve" or action = "collection_add" or action = "collection_remove" or action = "collection_create") then decodeParams.statusCode = TaskValue(response,"statusCode",0)
    if provider = "silo" and action = "collection_create" then decodeParams.profileId = TaskString(session,"profileId")
    decoded = TaskDecode(provider, action, response.body, decodeParams)
    if decoded.ok <> true
        if provider = "plex" and (action = "pin_start" or action = "pin_poll") then return TaskAuthTransportFailure(provider, action, response, TaskString(decoded, "errorCode"), "decode")
        return TaskError(TaskString(decoded, "errorCode"))
    end if

    ' PIN verification changes the active profile atomically. A follow-up
    ' select_profile request would carry the former profile scope and fail.
    if provider = "silo" and action = "profile_verify"
        if TaskValue(TaskValue(decoded, "data", {}), "valid", false) <> true then return TaskError("profile_pin_invalid")
        verified = TaskValue(decoded, "session", {})
        profileId = TaskString(params, "profileId")
        if profileId = "" or TaskString(verified, "profileId") <> profileId or TaskString(verified, "profileToken") = "" then return TaskError("invalid_response")
        updated = MergeSessionPatch(session, {profileId: profileId, profileName: TaskString(params, "profileName"), profileToken: TaskString(verified, "profileToken")})
        if profileId = TaskString(session, "profileId")
            saved = SaveSession("silo", updated, revision)
        else
            saved = ReplaceSession("silo", updated, revision)
        end if
        if not saved then return TaskError("session_changed")
        return {ok: true, data: PublicSessionStatus("silo", updated)}
    end if

    if provider = "silo" and action = "device_poll" and TaskString(TaskValue(decoded, "data", {}), "status") = "approved"
        ' Replace credentials and identity together. A full login can return
        ' blank profile fields, so discard the previous profile's display name.
        approved = TaskValue(decoded, "data", {})
        patch = MergeSessionPatch(TaskValue(decoded, "session", {}), {accountId: TaskString(approved, "accountId"), accountName: TaskString(approved, "accountName"), profileName: "", deviceCode: ""})
        updated = MergeSessionPatch(session, patch)
        if not ReplaceSession("silo", updated, revision)
            if SessionRevision("silo") <> revision then return TaskError("session_changed")
            return TaskError("storage_error")
        end if
        data = MergeSessionPatch(approved, PublicSessionStatus("silo", updated))
        data["state"] = "approved"
        return {ok: true, data: data}
    end if

    if decoded.DoesExist("session") and decoded.session <> invalid
        if provider = "plex" and action = "pin_poll" and TaskString(decoded.session, "accountToken") <> ""
            ' A new token can belong to another account. Clear the old account
            ' and profile identity before account lookup or restart recovery.
            decoded["session"] = MergeSessionPatch(decoded.session, {accountId: "", accountName: "", profileId: "", profileName: "", profileToken: "", token: "", baseUrl: "", sourceId: "", serverName: "", machineId: "", local: false, candidateServers: []})
        end if
        session = TaskSavePatch(provider, session, decoded.session, revision)
        if session = invalid
            if SessionRevision(provider) <> revision then return TaskError("session_changed")
            return TaskError("storage_error")
        end if
    end if
    if discoveryIdentity <> invalid
        current = LoadSession("silo")
        if SessionRevision("silo") <> revision then return TaskError("session_changed")
        for each key in discoveryIdentity
            if TaskString(current,key) <> discoveryIdentity[key] then return TaskError("session_changed")
        end for
    end if
    if provider = "plex" then return TaskFinishPlex(action, decoded, session, revision)
    return TaskFinishSilo(action, decoded, session, revision)
end function

' These local actions precede device queries and provider HTTP. Only a sanitized
' source/profile preference returns to SceneGraph; the session's tokens stay here.
function TaskRunTrackPreference(provider as String, action as String, session as Object, params as Object, scope as Object, revision as Integer) as Object
    active = TrackPreferenceScope(scope)
    if active = invalid then return TaskError("session_changed")
    if Left(active.sourceId,5) <> provider + ":" then return TaskError("session_changed")
    if active.sourceId <> TaskString(session,"sourceId") or active.profileId <> TaskString(session,"profileId") then return TaskError("session_changed")
    if SessionRevision(provider) <> revision then return TaskError("session_changed")
    if action = "track_pref_get"
        if params.Count() <> 0 then return TaskError("invalid_request")
        preference = TrackPreferenceNormalize(TaskValue(session,"trackPreference",invalid),active)
        return {ok:true,data:{preference:preference}}
    end if
    if action <> "track_pref_set" or params.Count() <> 1 or not params.DoesExist("preference") then return TaskError("invalid_request")
    raw = TaskValue(params,"preference",invalid)
    if not TaskTrackPreferenceRecordValid(raw) then return TaskError("invalid_request")
    if TaskString(raw,"sourceId") <> active.sourceId or TaskString(raw,"profileId") <> active.profileId then return TaskError("session_changed")
    preference = TrackPreferenceNormalize(raw,active)
    if preference = invalid or Len(FormatJson(preference)) > 1024 then return TaskError("invalid_request")
    updated = MergeSessionPatch(session,{trackPreference:preference})
    if not SaveSession(provider,updated,revision)
        if SessionRevision(provider) <> revision then return TaskError("session_changed")
        return TaskError("storage_error")
    end if
    if SessionRevision(provider) <> revision then return TaskError("session_changed")
    return {ok:true,data:{preference:preference}}
end function

' A full compact snapshot is required. Reject unknown/secret fields rather than
' silently storing a partial update; language aliases are normalized by policy.
function TaskTrackPreferenceRecordValid(raw as Dynamic) as Boolean
    if type(raw) <> "roAssociativeArray" then return false
    allowed = {schemaversion:true,sourceid:true,profileid:true,subtitlemode:true,subtitlelanguage:true,subtitlename:true,audiolanguage:true,audioname:true}
    if raw.Count() <> allowed.Count() then return false
    for each key in raw
        if not allowed.DoesExist(LCase(key)) then return false
    end for
    version = TrackPreferenceField(raw,"schemaVersion",invalid)
    if type(version) <> "Integer" and type(version) <> "roInt" and type(version) <> "roInteger" then return false
    if version <> 1 then return false
    if TrackPreferenceScope(raw) = invalid then return false
    for each key in ["subtitleMode","subtitleLanguage","subtitleName","audioLanguage","audioName"]
        value = TrackPreferenceField(raw,key,invalid)
        if type(value) <> "String" and type(value) <> "roString" then return false
        if key = "subtitleMode"
            if value <> "auto" and value <> "off" and value <> "on" then return false
        else if key = "subtitleLanguage" or key = "audioLanguage"
            if value <> "" and TrackPreferenceLanguage(value) = "" then return false
        else
            if value <> "" and TrackPreferenceName(value) = "" then return false
        end if
    end for
    return true
end function

function TaskBuildRequest(provider as String, action as String, session as Object, params as Object) as Object
    if TaskIsMetadataAction(action)
        if action = "ava_recommend"
            status = PublicSessionStatus(provider, session)
            if not status.connected then return TaskError("auth_required")
        end if
        ' The metadata origin and headers are independent of the provider session.
        publicParams = MergeSessionPatch(params, {"sourceId": TaskString(session, "sourceId")})
        return BuildMetadataRequest(action, MetadataRequestConfig(RuntimeAppVersion()), publicParams)
    end if
    if provider = "plex"
        if TaskIsPlexWatchlistAction(action) then return BuildPlexWatchlistRequest(action, session, params)
        return BuildPlexRequest(action, session, params)
    end if
    return BuildSiloRequest(action, session, params)
end function

function TaskDecode(provider as String, action as String, body as String, params as Object) as Object
    if TaskIsMetadataAction(action) then return DecodeMetadataResponse(action, body, params)
    if provider = "plex"
        if TaskIsPlexWatchlistAction(action) then return DecodePlexWatchlistResponse(action, body, params)
        return DecodePlexResponse(action, body, params)
    end if
    decoded = DecodeSiloResponse(action, body, params)
    if action = "detail" and decoded.ok = true and SiloCompatPreparationEnabled() and SiloP7CompatPreparationEnabled() then decoded = TaskSiloAutoAudioDetail(decoded,body)
    return decoded
end function

' Only ApiTask owns the raw detail and this gated request-local projection.
' Other SiloAdapter consumers keep their existing dependency and output shape.
function TaskSiloAutoAudioDetail(decoded as Object, body as String) as Object
    raw = ParseJson(body)
    if not SiloObject(raw) or not SiloObject(SpField(decoded,"data")) then return decoded
    versions = SpField(raw,"versions"):mapped = SpField(decoded.data,"versions")
    if not SiloArray(versions) or not SiloArray(mapped) then return decoded
    if decoded.data.versionsComplete <> true or versions.Count() = 0 or versions.Count() > 16 or versions.Count() <> mapped.Count() then return decoded
    roots = 0
    for each name in raw
        if LCase(name) = "versions" then roots++
    end for
    if roots <> 1 then return decoded
    for index = 0 to versions.Count()-1
        if SpField(versions[index],"file_id") <> SpField(mapped[index],"versionId") then return decoded
    end for
    for index = 0 to versions.Count()-1
        facts = SiloAutoAudioFacts(versions[index])
        if facts <> invalid then mapped[index]["autoAudioFacts"] = facts
    end for
    return decoded
end function

function TaskIsMetadataAction(action as String) as Boolean
    return action = "home_rows" or action = "service_catalog" or action = "ava_recommend" or action = "discover_trending" or action = "metadata_artwork"
end function

' Public metadata still belongs to a specific UI source/profile generation.
' Never scope global catalog seeds as if they were native provider items.
function TaskRunMetadata(provider as String, action as String, session as Object, params as Object, scope as Object, revision as Integer) as Object
    sourceId = TaskString(scope, "sourceId")
    if sourceId = "" then return TaskError("source_required")
    if sourceId <> TaskString(session, "sourceId") then return TaskError("session_changed")
    if not scope.DoesExist("profileId") then return TaskError("session_changed")
    profileId = TaskValue(scope, "profileId", invalid)
    if type(profileId) <> "String" and type(profileId) <> "roString" then return TaskError("session_changed")
    if profileId <> TaskString(session, "profileId") then return TaskError("session_changed")
    metadataConfig = MetadataRequestConfig(RuntimeAppVersion())
    metadataBase = TaskValue(metadataConfig,"baseUrl",invalid)
    if metadataBase = invalid or metadataBase = "" then return TaskError("metadata_disabled")
    if type(metadataBase) <> "String" and type(metadataBase) <> "roString" then return TaskError("invalid_server")
    if Len(metadataBase) > 1024 or HmBaseUrl(metadataBase) = "" then return TaskError("invalid_server")
    if provider = "silo" and action = "metadata_artwork"
        if params.DoesExist("itemId") or params.DoesExist("itemType") then return TaskRunSiloArtwork(session,params,scope,revision)
    end if
    if provider = "plex" and action = "metadata_artwork"
        if params.DoesExist("itemId") or params.DoesExist("itemType") then return TaskRunPlexArtwork(session,params,scope,revision)
    end if
    request = TaskBuildRequest(provider, action, session, params)
    if request.ok <> true then return TaskError(TaskString(request, "errorCode"))
    ' HttpRequest applies the adapter's bounded 10/12/30 second timeout.
    response = HttpRequest(request)
    if SessionRevision(provider) <> revision then return TaskError("session_changed")
    if response.ok <> true then return TaskError(TaskString(response, "errorCode"))
    if action = "home_rows" and TaskString(params, "mode") = "refresh" and Instr(1, TaskString(request, "url"), "&format=compact") > 0 and TaskValue(response, "statusCode", 0) = 204 then return {ok: true, data: {refreshQueued: true}}
    return TaskDecode(provider, action, TaskString(response, "body"), params)
end function

function TaskArtworkTrue(value as Dynamic) as Boolean
    if type(value) <> "Boolean" and type(value) <> "roBoolean" then return false
    return value
end function

' Exact private Plex identity is admitted only for the mapped artwork owner.
function TaskPlexArtworkOwnerValid(params as Object, scope as Object) as Boolean
    if params.Count() <> 3 then return false
    for each key in ["type","itemId","itemType"]
        if not params.DoesExist(key) then return false
    end for
    itemId = TaskString(params,"itemId")
    if not CreateObject("roRegex","^[0-9]{1,20}$","").IsMatch(itemId) then return false
    nativeType = TaskString(params,"itemType")
    if nativeType <> "movie" and nativeType <> "show" and nativeType <> "episode" then return false
    publicType = "movie"
    if nativeType <> "movie" then publicType = "tv"
    if TaskString(params,"type") <> publicType or TaskString(scope,"provider") <> "plex" then return false
    generation = TaskPlexProbeInteger(TaskValue(scope,"generation",invalid),2147483647)
    if generation < 0 then return false
    owner = TaskValue(scope,"artworkOwner",invalid)
    if type(owner) <> "roAssociativeArray" then return false
    if not TaskArtworkTrue(TaskValue(owner,"identityRequired",invalid)) then return false
    ownerScope = TaskValue(owner,"scope",invalid)
    if type(ownerScope) <> "roAssociativeArray" then return false
    for each key in ["provider","sourceId","profileId","generation"]
        if TaskValue(ownerScope,key,invalid) <> TaskValue(scope,key,invalid) then return false
    end for
    if TaskPlexProbeInteger(TaskValue(ownerScope,"generation",invalid),2147483647) <> generation then return false
    if TaskString(owner,"itemId") <> itemId or TaskString(owner,"nativeType") <> nativeType or TaskString(owner,"type") <> publicType then return false
    tmdbId = TaskValue(owner,"tmdbId",invalid)
    if type(tmdbId) <> "String" and type(tmdbId) <> "roString" then return false
    if tmdbId <> "" then return false
    if TaskString(owner,"scopeKey") <> "route-" + generation.ToStr() then return false
    if not CreateObject("roRegex","^[A-Za-z0-9_.:-]{1,256}$","").IsMatch(TaskString(owner,"key")) then return false
    return TaskPlexProbeInteger(TaskValue(owner,"artId",invalid),2147483646) > 0
end function

' Default ParseJson preserves simultaneous PMS scalar guid and array Guid.
function TaskPlexArtworkRow(body as String, itemId as String, nativeType as String) as Dynamic
    root = ParseJson(body)
    container = PlexExactField(root,"MediaContainer")
    rows = PlexExactField(container,"Metadata")
    if type(rows) <> "roArray" then return invalid
    if rows.Count() <> 1 then return invalid
    row = rows[0]
    if type(row) <> "roAssociativeArray" then return invalid
    for each key in row
        lower = LCase(key)
        if lower = "ratingkey" and key <> "ratingKey" then return invalid
        if lower = "type" and key <> "type" then return invalid
        if lower = "grandparentratingkey" and key <> "grandparentRatingKey" then return invalid
    end for
    rawId = PlexExactField(row,"ratingKey")
    kind = PlexExactField(row,"type")
    if type(rawId) <> "String" and type(rawId) <> "roString" then return invalid
    if type(kind) <> "String" and type(kind) <> "roString" then return invalid
    if rawId <> itemId or kind <> nativeType then return invalid
    return row
end function

function TaskPlexArtworkGuidText(value as Dynamic) as String
    if type(value) <> "String" and type(value) <> "roString" then return ""
    if Len(value) = 0 or Len(value) > 256 or value.Trim() <> value then return ""
    if CreateObject("roRegex","[\x00-\x1f\x7f]","").IsMatch(value) then return ""
    return value
end function

' Validate every bounded raw GUID before PlexGuids can filter or truncate it.
' An invalid TMDB claim must not disappear beside a different valid claim.
function TaskPlexArtworkTmdb(row as Object) as String
    for each key in row
        if LCase(key) = "guid" and key <> "guid" and key <> "Guid" then return ""
    end for
    candidates = []
    legacy = PlexExactField(row,"guid")
    if legacy <> invalid
        if type(legacy) <> "String" and type(legacy) <> "roString" then return ""
        if legacy <> ""
            text = TaskPlexArtworkGuidText(legacy)
            if text = "" then return ""
            candidates.Push(text)
        end if
    end if
    entries = PlexExactField(row,"Guid")
    if entries <> invalid
        if type(entries) <> "roArray" then return ""
        if entries.Count() + candidates.Count() > 16 then return ""
        for each entry in entries
            if type(entry) <> "roAssociativeArray" then return ""
            for each key in entry
                if LCase(key) = "id" and key <> "id" then return ""
            end for
            text = TaskPlexArtworkGuidText(PlexExactField(entry,"id"))
            if text = "" then return ""
            candidates.Push(text)
        end for
    end if
    wanted = ""
    for each guid in candidates
        lower = LCase(guid)
        if Left(lower,4) = "tmdb"
            if Left(lower,7) <> "tmdb://" then return ""
            rawId = Mid(guid,8)
            if not CreateObject("roRegex","^[0-9]{1,12}$","").IsMatch(rawId) then return ""
            identifier = HmNumericId(rawId)
            if identifier = "" or (wanted <> "" and wanted <> identifier) then return ""
            wanted = identifier
        end if
    end for
    proven = ""
    for each guid in PlexGuids(row)
        if Left(LCase(guid),7) = "tmdb://"
            identifier = HmNumericId(Mid(guid,8))
            if identifier = "" or identifier <> wanted then return ""
            proven = identifier
        end if
    end for
    return proven
end function

' Credential/base identity is persisted; generated device fields are not fences.
' All private and public reads share one four-second clock and byte cap.
function TaskPlexArtworkHttp(context as Object, request as Object) as Object
    if not TaskPlexProbeSessionMatches(context.session,context.scope,context.revision) then return TaskError("session_changed")
    if not TaskArtworkTrue(TaskValue(request,"ok",false)) then return TaskError(TaskString(request,"errorCode"))
    remaining = 4000 - context.clock.TotalMilliseconds()
    if remaining < 1250 then return TaskError("lookup_budget")
    request["timeoutMs"] = Int(remaining - 250)
    request["responseBodyLimit"] = 98304
    response = HttpRequest(request,request.timeoutMs)
    if not TaskPlexProbeSessionMatches(context.session,context.scope,context.revision) then return TaskError("session_changed")
    if context.clock.TotalMilliseconds() >= 4000 then return TaskError("lookup_budget")
    if not TaskArtworkTrue(TaskValue(response,"ok",false)) then return TaskError(TaskString(response,"errorCode"))
    return response
end function

function TaskRunPlexArtwork(session as Object, params as Object, scope as Object, revision as Integer) as Object
    if not TaskPlexArtworkOwnerValid(params,scope) then return TaskError("invalid_request")
    captured = MergeSessionPatch({},session)
    if not TaskPlexProbeSessionMatches(captured,scope,revision) then return TaskError("session_changed")
    context = {session:captured,scope:scope,revision:revision,clock:CreateObject("roTimespan")}
    context.clock.Mark()
    context.session = TaskDeviceSession("plex",captured)
    response = TaskPlexArtworkHttp(context,BuildPlexRequest("artwork_detail",context.session,{itemId:params.itemId}))
    if not TaskArtworkTrue(TaskValue(response,"ok",false)) then return response
    detail = TaskPlexArtworkRow(TaskString(response,"body"),params.itemId,params.itemType)
    if detail = invalid then return TaskError("artwork_unavailable")
    if params.itemType = "episode"
        ' Leaf GUIDs identify the episode, never the TV metadata namespace.
        parentId = TaskPlexArtworkGuidText(PlexExactField(detail,"grandparentRatingKey"))
        if not CreateObject("roRegex","^[0-9]{1,20}$","").IsMatch(parentId) or parentId = params.itemId then return TaskError("artwork_unavailable")
        response = TaskPlexArtworkHttp(context,BuildPlexRequest("artwork_detail",context.session,{itemId:parentId}))
        if not TaskArtworkTrue(TaskValue(response,"ok",false)) then return response
        detail = TaskPlexArtworkRow(TaskString(response,"body"),parentId,"show")
        if detail = invalid then return TaskError("artwork_unavailable")
    end if
    identifier = TaskPlexArtworkTmdb(detail)
    if identifier = "" then return TaskError("artwork_unavailable")
    publicParams = {type:params.type,tmdbId:identifier}
    request = BuildMetadataRequest("metadata_artwork",MetadataRequestConfig(TaskString(context.session,"appVersion")),publicParams)
    response = TaskPlexArtworkHttp(context,request)
    if not TaskArtworkTrue(TaskValue(response,"ok",false)) then return response
    output = DecodeMetadataResponse("metadata_artwork",TaskString(response,"body"),publicParams)
    if not TaskPlexProbeSessionMatches(context.session,scope,revision) then return TaskError("session_changed")
    if context.clock.TotalMilliseconds() >= 4000 then return TaskError("lookup_budget")
    return output
end function

' The private candidate belongs to one current card and one mapped queue job.
function TaskSiloArtworkOwnerValid(params as Object, scope as Object) as Boolean
    if params.Count() <> 3 then return false
    for each key in ["type","itemId","itemType"]
        if not params.DoesExist(key) then return false
    end for
    itemId = TaskString(params,"itemId")
    if itemId = "." or itemId = ".." then return false
    if not CreateObject("roRegex","^[A-Za-z0-9_.:-]{1,256}$","").IsMatch(itemId) then return false
    wireKind = TaskString(params,"itemType")
    publicKind = "movie"
    if wireKind = "series" or wireKind = "episode" then publicKind = "tv"
    if wireKind <> "movie" and wireKind <> "series" and wireKind <> "episode" then return false
    if TaskString(params,"type") <> publicKind or TaskString(scope,"provider") <> "silo" then return false
    generation = TaskPlexProbeInteger(TaskValue(scope,"generation",invalid),2147483647)
    if generation < 0 then return false
    owner = TaskValue(scope,"artworkOwner",invalid)
    if type(owner) <> "roAssociativeArray" then return false
    if not TaskArtworkTrue(TaskValue(owner,"identityRequired",invalid)) then return false
    ownerScope = TaskValue(owner,"scope",invalid)
    if type(ownerScope) <> "roAssociativeArray" then return false
    for each key in ["provider","sourceId","profileId","generation"]
        if TaskValue(ownerScope,key,invalid) <> TaskValue(scope,key,invalid) then return false
    end for
    if TaskString(owner,"itemId") <> itemId or TaskString(owner,"nativeType") <> wireKind or TaskString(owner,"type") <> publicKind then return false
    if TaskValue(owner,"tmdbId",invalid) <> "" then return false
    if TaskString(owner,"scopeKey") <> "route-" + generation.ToStr() then return false
    if not CreateObject("roRegex","^[A-Za-z0-9_.:-]{1,256}$","").IsMatch(TaskString(owner,"key")) then return false
    return TaskPlexProbeInteger(TaskValue(owner,"artId",invalid),2147483646) > 0
end function

' One optional Task has one four-second budget for all reads and projection.
function TaskSiloArtworkHttp(context as Object, request as Object) as Object
    if not TaskPreviewScopeMatches("silo",LoadSession("silo"),context.scope,context.revision) then return TaskError("session_changed")
    if not TaskArtworkTrue(TaskValue(request,"ok",false)) then return TaskError(TaskString(request,"errorCode"))
    remaining = 4000 - context.clock.TotalMilliseconds()
    if remaining < 1250 then return TaskError("lookup_budget")
    request["timeoutMs"] = Int(remaining - 250)
    request["responseBodyLimit"] = 98304
    response = HttpRequest(request,request.timeoutMs)
    if not TaskPreviewScopeMatches("silo",LoadSession("silo"),context.scope,context.revision) then return TaskError("session_changed")
    if context.clock.TotalMilliseconds() >= 4000 then return TaskError("lookup_budget")
    if not TaskArtworkTrue(TaskValue(response,"ok",false)) then return TaskError(TaskString(response,"errorCode"))
    return response
end function

function TaskRunSiloArtwork(session as Object, params as Object, scope as Object, revision as Integer) as Object
    if not TaskSiloArtworkOwnerValid(params,scope) then return TaskError("invalid_request")
    if not TaskPreviewScopeMatches("silo",LoadSession("silo"),scope,revision) then return TaskError("session_changed")
    context = {scope:scope,revision:revision,clock:CreateObject("roTimespan")}
    context.clock.Mark()
    session = TaskDeviceSession("silo",session)
    request = BuildSiloRequest("detail",session,{itemId:params.itemId})
    response = TaskSiloArtworkHttp(context,request)
    if not TaskArtworkTrue(TaskValue(response,"ok",false)) then return response
    detail = ParseJson(TaskString(response,"body"),"i")
    if type(detail) <> "roAssociativeArray" then return TaskError("invalid_response")
    if TaskString(detail,"content_id") <> params.itemId or TaskString(detail,"type") <> params.itemType then return TaskError("artwork_unavailable")
    if params.itemType = "episode"
        ' An episode's TMDB ID is not its series ID. Only fresh typed Detail owns this relation.
        seriesId = TaskString(detail,"series_id")
        if seriesId = "." or seriesId = ".." then return TaskError("artwork_unavailable")
        if not CreateObject("roRegex","^[A-Za-z0-9_.:-]{1,256}$","").IsMatch(seriesId) then return TaskError("artwork_unavailable")
        seriesRequest = BuildSiloRequest("detail",session,{itemId:seriesId})
        seriesResponse = TaskSiloArtworkHttp(context,seriesRequest)
        if not TaskArtworkTrue(TaskValue(seriesResponse,"ok",false)) then return seriesResponse
        detail = ParseJson(TaskString(seriesResponse,"body"),"i")
        if type(detail) <> "roAssociativeArray" then return TaskError("invalid_response")
        if TaskString(detail,"content_id") <> seriesId or TaskString(detail,"type") <> "series" then return TaskError("artwork_unavailable")
    end if
    rawId = TaskString(detail,"tmdb_id")
    if not CreateObject("roRegex","^[0-9]{1,12}$","").IsMatch(rawId) then return TaskError("artwork_unavailable")
    identifier = HmNumericId(rawId)
    if identifier = "" then return TaskError("artwork_unavailable")
    publicParams = {type:params.type,tmdbId:identifier}
    publicRequest = BuildMetadataRequest("metadata_artwork",MetadataRequestConfig(TaskString(session,"appVersion")),publicParams)
    publicResponse = TaskSiloArtworkHttp(context,publicRequest)
    if not TaskArtworkTrue(TaskValue(publicResponse,"ok",false)) then return publicResponse
    output = DecodeMetadataResponse("metadata_artwork",TaskString(publicResponse,"body"),publicParams)
    if not TaskPreviewScopeMatches("silo",LoadSession("silo"),scope,revision) then return TaskError("session_changed")
    if context.clock.TotalMilliseconds() >= 4000 then return TaskError("lookup_budget")
    return output
end function

function TaskIsPlexWatchlistAction(action as String) as Boolean
    return action = "watchlist" or action = "watchlist_add" or action = "watchlist_remove"
end function

function TaskEnsurePlexWatchlistAccount(session as Object, revision as Integer) as Object
    if not PlexWatchlistNeedsAccountLookup(session) then return {ok: true, session: session}
    request = BuildPlexRequest("user", session, {})
    if request.ok <> true then return TaskError(TaskString(request, "errorCode"))
    response = HttpRequest(request, 7000)
    if response.ok <> true then return TaskError(TaskString(response, "errorCode"))
    decoded = DecodePlexResponse("user", response.body, {})
    if decoded.ok <> true then return TaskError(TaskString(decoded, "errorCode"))
    data = TaskValue(decoded, "data", {})
    accountId = TaskString(data, "accountId")
    if accountId = "" then return TaskError("account_identity_required")
    updated = TaskSavePatch("plex", session, {accountId: accountId, accountName: TaskString(data, "accountName")}, revision)
    if updated = invalid
        if SessionRevision("plex") <> revision then return TaskError("session_changed")
        return TaskError("storage_error")
    end if
    return {ok: true, session: updated}
end function

function TaskFinishPlex(action as String, decoded as Object, session as Object, revision as Integer) as Object
    data = TaskValue(decoded, "data", {})
    if action = "resources"
        servers = TaskValue(data, "servers", [])
        servers = TaskPlexEligibleServers(session, servers)
        if servers.Count() = 0 and TaskValue(data, "servers", []).Count() > 0 then return TaskError("resource_storage_full")
        budgeted = TaskPlexResourceSession(session, servers)
        if budgeted.ok <> true then return budgeted
        session = budgeted.session
        if not SaveSession("plex", session, revision)
            if SessionRevision("plex") <> revision then return TaskError("session_changed")
            return TaskError("storage_error")
        end if
        ' Public choices have no credentials or routes. Keep the complete
        ' bounded list visible even when only ten route-rich candidates fit
        ' the encrypted registry; an uncached choice is fetched on selection.
        return {ok: true, data: {servers: PublicPlexServers(servers)}}
    end if
    if action = "user"
        patch = {accountId: TaskString(data, "accountId"), accountName: TaskString(data, "accountName")}
        session = TaskSavePatch("plex", session, patch, revision)
        if session = invalid
            if SessionRevision("plex") <> revision then return TaskError("session_changed")
            return TaskError("storage_error")
        end if
    end if
    if action = "sections" or action = "home_continue" or action = "home_on_deck" or action = "section_hubs" or action = "library_items" or action = "search" or action = "detail" or action = "children" or action = "related"
        data = ScopeCatalogData(data, TaskString(session, "sourceId"))
    end if
    return {ok: true, data: data}
end function

' A public server choice must be selectable after a fresh resource fetch.
' Project the compact connected record, which has no discovery candidates.
function TaskPlexEligibleServers(session as Object, servers as Object) as Object
    eligible = []
    for each server in servers
        token = TaskString(server, "token")
        if token = "" then token = TaskString(session, "accountToken")
        for each connection in TaskValue(server, "connections", [])
            patch = {baseUrl:TaskString(connection,"baseUrl"), local:TaskValue(connection,"local",false), token:token, sourceId:TaskString(server,"sourceId"), serverName:Left(TaskString(server,"name"),128), machineId:TaskString(server,"machineId"), candidateServers:[]}
            if patch.baseUrl <> "" and patch.machineId <> "" and Len(FormatJson(MergeSessionPatch(session,patch))) <= 14000
                eligible.Push(server)
                exit for
            end if
        end for
    end for
    return eligible
end function

' Use the same connection preference for cached and freshly resolved servers.
' A relay can appear before a reachable local route in Plex resources.
function TaskPlexOrderedConnections(connections as Object) as Object
    ordered = []
    for priority = 0 to 5
        for each connection in connections
            base = TaskString(connection, "baseUrl")
            rank = 2
            if TaskValue(connection, "local", false) then rank = 0
            if TaskValue(connection, "relay", false) then rank = 4
            if Left(base, 8) <> "https://" then rank = rank + 1
            if base <> "" and rank = priority
                ordered.Push({"baseUrl": base, local: TaskValue(connection, "local", false), relay: TaskValue(connection, "relay", false)})
            end if
        end for
    end for
    return ordered
end function

' Reserve a usable route for each server before spending registry space on
' alternatives. This measures the same complete JSON record as SaveSession.
' Candidate access tokens and connection URLs never enter the public result.
function TaskPlexResourceSession(session as Object, servers as Object) as Object
    candidates = []
    updated = MergeSessionPatch(session, {"candidateServers": candidates})
    if Len(FormatJson(updated)) > 14000 then return TaskError("resource_storage_full")
    alternatives = []
    ' Shared servers can precede an account's own server in Plex resources.
    ' Reserve bounded registry slots for owned servers before shared choices.
    for ownerPass = 0 to 1
        for each server in servers
            if candidates.Count() >= 10 then exit for
            owned = TaskValue(server, "owned", false)
            if (ownerPass = 0 and owned) or (ownerPass = 1 and not owned)
                ordered = TaskPlexOrderedConnections(TaskValue(server, "connections", []))
                candidate = {"sourceId": TaskString(server, "sourceId"), "machineId": TaskString(server, "machineId"), name: Left(TaskString(server, "name"), 128), token: TaskString(server, "token"), owned: owned, connections: []}
                for each connection in ordered
                    candidate.connections = [connection]
                    candidates.Push(candidate)
                    if Len(FormatJson(updated)) <= 14000
                        alternatives.Push({server: candidate, connections: ordered})
                        exit for
                    end if
                    candidates.Pop()
                end for
            end if
        end for
        if candidates.Count() >= 10 then exit for
    end for
    ' Uncached public choices are resolved from Plex only if selected.
    for each entry in alternatives
        candidate = entry.server
        for each connection in entry.connections
            duplicate = false
            for each kept in candidate.connections
                if kept["baseUrl"] = connection["baseUrl"] then duplicate = true
            end for
            if not duplicate
                candidate.connections.Push(connection)
                if Len(FormatJson(updated)) > 14000 then candidate.connections.Pop()
            end if
        end for
    end for
    return {ok: true, session: updated}
end function

function TaskFinishSilo(action as String, decoded as Object, session as Object, revision as Integer) as Object
    data = TaskValue(decoded, "data", {})
    if action = "catalog_resolve"
        for each match in data.matches
            match.item = ScopedMediaItem(match.item,TaskString(session,"sourceId"))
        end for
    end if
    if Left(action,8) = "shuffle_"
        for each key in ["current","next"]
            if data.DoesExist(key) then data[key] = ScopedMediaItem(data[key],TaskString(session,"sourceId"))
        end for
    end if
    if action = "home" or action = "libraries" or action = "catalog_query" or action = "detail" or action = "seasons" or action = "episodes" or action = "similar" or action = "person_items" or action = "person"
        data = ScopeCatalogData(data, TaskString(session, "sourceId"))
    end if
    return {ok: true, data: data}
end function

function TaskSetSiloServer(session as Object, params as Object, revision as Integer) as Object
    normalized = NormalizeServerUrl(TaskString(params, "baseUrl"))
    if normalized.ok <> true then return TaskError(TaskString(normalized, "errorCode"))
    if TaskString(session, "baseUrl") = normalized.url
        return {ok: true, data: PublicSessionStatus("silo", session)}
    end if
    fresh = TaskDeviceSession("silo", {baseUrl: normalized.url, sourceId: "silo:" + normalized.url})
    if not ReplaceSession("silo", fresh, revision) then return TaskError("storage_error")
    return {ok: true, data: PublicSessionStatus("silo", fresh)}
end function

function TaskSelectSiloProfile(session as Object, params as Object, revision as Integer) as Object
    profileId = TaskString(params, "profileId")
    if profileId = "" or TaskString(session, "accessToken") = "" then return TaskError("profile_required")
    patch = {profileId: profileId, profileName: TaskString(params, "profileName")}
    if profileId <> TaskString(session, "profileId") then patch["profileToken"] = ""
    updated = MergeSessionPatch(session, patch)
    if profileId = TaskString(session, "profileId")
        saved = SaveSession("silo", updated, revision)
    else
        saved = ReplaceSession("silo", updated, revision)
    end if
    if not saved then return TaskError("session_changed")
    return {ok: true, data: PublicSessionStatus("silo", updated)}
end function

function TaskSelectPlexServer(session as Object, params as Object, revision as Integer) as Object
    machineId = TaskString(params, "machineId")
    if machineId = "" then return TaskError("server_not_found")
    candidates = TaskValue(session, "candidateServers", [])
    found = false
    for each server in candidates
        if TaskString(server, "machineId") = machineId then found = true
    end for
    if not found
        ' The UI may show more choices than the registry can hold routes for.
        ' Resolve only the selected server inside this Task; never send a
        ' resource token or connection URL through SceneGraph.
        request = BuildPlexRequest("resources", session, {})
        if request.ok <> true then return TaskError(TaskString(request, "errorCode"))
        response = HttpRequest(request, 9000)
        if response.ok <> true then return TaskError(TaskString(response, "errorCode"))
        decoded = PlexDecodeResources(ParseJson(response.body), machineId)
        if decoded.ok <> true then return TaskError(TaskString(decoded, "errorCode"))
        candidates = []
        for each server in TaskValue(TaskValue(decoded, "data", {}), "servers", [])
            if TaskString(server, "machineId") = machineId
                candidates.Push(server)
                exit for
            end if
        end for
    end if
    for each server in candidates
        if TaskString(server, "machineId") = machineId
            ' Keep the credential used by PlexHeaders for the connection probe.
            ' If a resource omits its access token, account-token fallback
            ' must survive selection and restart just as it does in requests.
            serverToken = TaskString(server, "token")
            if serverToken = "" then serverToken = TaskString(session, "accountToken")
            for each connection in TaskPlexOrderedConnections(TaskValue(server, "connections", []))
                baseUrl = TaskString(connection, "baseUrl")
                candidate = MergeSessionPatch(session, {baseUrl: baseUrl, local: TaskValue(connection, "local", false), token: serverToken, sourceId: TaskString(server, "sourceId")})
                request = BuildPlexRequest("identity", candidate, {})
                if request.ok
                    response = HttpRequest(request, 5000)
                    if response.ok
                        decoded = DecodePlexResponse("identity", response.body, {machineId: machineId})
                        if decoded.ok
                            ' Discovery candidates are temporary. Release their credentials
                            ' before adding the selected server to the compact session.
                            patch = {baseUrl: baseUrl, local: TaskValue(connection, "local", false), token: serverToken, sourceId: TaskString(server, "sourceId"), serverName: Left(TaskString(server, "name"), 128), machineId: machineId, "candidateServers": []}
                            updated = MergeSessionPatch(session, patch)
                            if not ReplaceSession("plex", updated, revision)
                                if SessionRevision("plex") <> revision then return TaskError("session_changed")
                                return TaskError("storage_error")
                            end if
                            return {ok: true, data: PublicSessionStatus("plex", updated)}
                        end if
                    end if
                end if
            end for
            return TaskError("server_unreachable")
        end if
    end for
    return TaskError("server_not_found")
end function

function TaskSiloApprovalIdentityCurrent(identity as Dynamic, revision as Integer) as Boolean
    if identity = invalid then return true
    if type(identity) <> "roAssociativeArray" then return false
    if SessionRevision("silo") <> revision then return false
    current = LoadSession("silo")
    for each key in identity
        if TaskString(current,key) <> identity[key] then return false
    end for
    return true
end function

function TaskRefreshSilo(session as Object, revision as Integer, budget = invalid as Dynamic, approvalIdentity = invalid as Dynamic) as Object
    if not TaskSiloApprovalIdentityCurrent(approvalIdentity,revision) then return invalid
    if TaskString(session, "refreshToken") = "" then return invalid
    request = BuildSiloRequest("refresh", session, {})
    if request.ok <> true then return invalid
    if budget = invalid
        response = HttpRequest(request)
    else
        response = TaskSiloRecoveryHttp(budget,request,9000)
    end if
    if budget <> invalid
        state = TaskSiloRecoveryState(budget)
        if state <> "" then budget["httpRefusal"] = state
        if TaskString(budget,"httpRefusal") <> "" then return invalid
    end if
    if response.ok <> true then return invalid
    if not TaskSiloApprovalIdentityCurrent(approvalIdentity,revision) then return invalid
    decoded = DecodeSiloResponse("refresh", response.body, {})
    if decoded.ok <> true or not decoded.DoesExist("session") then return invalid
    return TaskSavePatch("silo", session, decoded.session, revision)
end function

function TaskResolvePlexWatchlist(session as Object, params as Object, revision as Integer) as Object
    if not PublicSessionStatus("plex", session).connected then return TaskError("auth_required")
    seed = TaskValue(params, "item", invalid)
    if type(seed) <> "roAssociativeArray" then return TaskError("invalid_request")
    accountId = TaskString(session, "accountId")
    if accountId = "" or TaskString(seed, "sourceId") <> "plex-watchlist:" + accountId then return TaskError("source_mismatch")
    title = TaskString(seed, "title")
    if title = "" or Len(title) > 256 then return TaskError("invalid_request")
    request = BuildPlexRequest("search", session, {query: title, limit: 48})
    if request.ok <> true then return TaskError(TaskString(request, "errorCode"))
    response = HttpRequest(request, 7000)
    if response.ok <> true then return TaskError(TaskString(response, "errorCode"))
    if SessionRevision("plex") <> revision then return TaskError("session_changed")
    decoded = DecodePlexResponse("search", response.body, {sourceId: TaskString(session, "sourceId")})
    if decoded.ok <> true then return TaskError(TaskString(decoded, "errorCode"))
    owned = MatchOwnedWatchlistItem(seed, TaskValue(TaskValue(decoded, "data", {}), "items", []), TaskString(session, "sourceId"))
    if owned = invalid then return {ok: true, data: {availability: "not_in_library"}}
    return {ok: true, data: {availability: "owned", item: owned}}
end function

' Silo playback requests share the same one-time token refresh as browse.
function TaskSiloFetch(session as Object, action as String, params as Object, revision as Integer, timeoutMs as Integer, budget = invalid as Dynamic, capturedIdentity = invalid as Dynamic, retainAllocatedResponse = false as Boolean) as Object
    ' Cleanup may send its captured old owner, but refresh must not restore it
    ' over a newer selection while the HTTP request is in flight.
    refreshIdentity = capturedIdentity
    if refreshIdentity = invalid then refreshIdentity = {sourceId:TaskString(session,"sourceId"),profileId:TaskString(session,"profileId"),profileToken:TaskString(session,"profileToken"),baseUrl:TaskString(session,"baseUrl")}
    if capturedIdentity <> invalid
        if not TaskSiloApprovalIdentityCurrent(capturedIdentity,revision) then return TaskError("session_changed")
        if m.top.cancelled = true then return TaskError("cancelled")
    end if
    request = BuildSiloRequest(action, session, params)
    if request.ok <> true then return TaskError(TaskString(request, "errorCode"))
    if action = "playback_start"
        m.siloNativeStartIssued = true
        if m.siloPrivateLegacyStartPending = true then m.siloPrivateLegacyStartIssued = true
    end if
    if budget = invalid
        response = HttpRequest(request,timeoutMs)
    else
        response = TaskSiloRecoveryHttp(budget,request,timeoutMs)
    end if
    if capturedIdentity <> invalid and not (retainAllocatedResponse and response.ok = true and (action = "playback_start" or action = "playback_replan"))
        if not TaskSiloApprovalIdentityCurrent(capturedIdentity,revision) then return TaskError("session_changed")
        if m.top.cancelled = true then return TaskError("cancelled")
    end if
    if action = "playback_start" and m.siloPrivateLegacyStartIssued = true and response.ok <> true then return TaskSiloHttpError(response)
    if response.ok <> true and TaskString(response, "errorCode") = "auth_required"
        if budget <> invalid
            if budget.refreshUsed then return TaskSiloHttpError(response)
            state = TaskSiloRecoveryState(budget)
            if state <> "" then return TaskError(state)
            budget.refreshUsed = true
        end if
        refreshed = TaskRefreshSilo(session,revision,budget,refreshIdentity)
        if budget <> invalid
            if TaskString(budget,"httpRefusal") <> "" then return TaskError(budget.httpRefusal)
        end if
        if capturedIdentity <> invalid
            if not TaskSiloApprovalIdentityCurrent(capturedIdentity,revision) then return TaskError("session_changed")
            if m.top.cancelled = true then return TaskError("cancelled")
        end if
        if refreshed <> invalid
            session = refreshed
            request = BuildSiloRequest(action, session, params)
            if request.ok <> true then return TaskError(TaskString(request, "errorCode"))
            if budget = invalid
                response = HttpRequest(request,timeoutMs)
            else
                response = TaskSiloRecoveryHttp(budget,request,timeoutMs)
            end if
        end if
    end if
    if capturedIdentity <> invalid and not (retainAllocatedResponse and response.ok = true and (action = "playback_start" or action = "playback_replan"))
        if not TaskSiloApprovalIdentityCurrent(capturedIdentity,revision) then return TaskError("session_changed")
        if m.top.cancelled = true then return TaskError("cancelled")
    end if
    if response.ok <> true then return TaskSiloHttpError(response)
    output = {ok: true, response: response, session: session}
    if action = "playback_start" or action = "playback_replan" then output["requestBody"] = ParseJson(request.body)
    return output
end function

function TaskPlaybackEvent(provider as String, session as Object, action as String, params as Object, revision as Integer, scope = invalid as Dynamic) as Object
    requestAction = action
    failure = invalid
    cleanupOnly = action = "playback_stop" and TaskValue(params,"persistProgress",true) = false
    if provider = "plex"
        requestAction = "timeline"
        if action = "playback_stop" then params["state"] = "stopped"
    end if
    if provider = "silo"
        if not params.DoesExist("installationId") then params["installationId"] = TaskString(session, "deviceId")
        if not params.DoesExist("sequence") then params["sequence"] = 1
        if action = "playback_stop" and not params.DoesExist("stopId") then params["stopId"] = LCase(CreateObject("roDeviceInfo").GetRandomUUID())
    end if
    if provider = "silo"
        fetched = TaskSiloFetch(session, requestAction, params, revision, 5000)
        if fetched.ok <> true then return fetched
        receipt = TaskSiloPlaybackReceipt(requestAction, TaskValue(fetched,"response",{}))
        if receipt.ok <> true then return receipt
    else if not cleanupOnly
        request = BuildPlexRequest(requestAction, session, params)
        if request.ok <> true
            failure = TaskPlexDeliveryFailure("timeline",request)
        else
            response = HttpRequest(request, 5000)
            if response.ok <> true then failure = TaskPlexDeliveryFailure("timeline",response)
        end if
    end if
    if provider = "plex" and action = "playback_stop" and TaskString(params, "transcodeSessionId") <> ""
        ' Release the transcode even when the final progress update failed.
        stopRequest = BuildPlexRequest("transcode_stop", session, params)
        if stopRequest.ok
            stopped = HttpRequest(stopRequest, 5000)
            if stopped.ok <> true and failure = invalid then failure = TaskPlexDeliveryFailure("transcode_stop",stopped)
            if TaskValue(stopped,"statusCode",0) = 404 and TaskString(stopped,"errorCode") = "not_found" and type(scope) = "roAssociativeArray"
                owner = TaskValue(scope,"inventoryProbeOwner",invalid)
                if type(owner) = "roAssociativeArray"
                    probeParams = {transcodeSessionId:TaskString(params,"transcodeSessionId"),sessionRevision:TaskValue(owner,"sessionRevision",invalid)}
                    probe = TaskPlexInventoryProbe(session,probeParams,scope,revision,"transcode_stop",owner)
                    if failure <> invalid then failure["inventoryDiagnostic"] = probe.inventoryDiagnostic
                end if
            end if
        else if failure = invalid
            failure = TaskPlexDeliveryFailure("transcode_stop",stopRequest)
        end if
    end if
    if failure <> invalid then return failure
    return {ok: true, data: {state: "saved"}}
end function

' The v2 schema inspected at Android 78d2df93 documents HTTP 200 with a required
' PlaybackMutation.outcome, not a bodyless 204. A generic transport success does
' not establish saved progress. Keep receipt text and optional history/stop IDs
' inside the Task; only evidenced action-specific outcomes acknowledge delivery.
' Server cce24de StopPlaybackV2 returns replayed with the durable stop receipt
' for every later stop of that session, including a different stop ID.
function TaskSiloPlaybackReceipt(action as String, response as Object) as Object
    if TaskValue(response,"statusCode",0) <> 200 then return TaskError("invalid_response")
    decoded = DecodeSiloResponse(action,TaskString(response,"body"),{})
    if decoded.ok <> true then return TaskError("invalid_response")
    outcome = TaskString(TaskValue(decoded,"data",{}),"outcome")
    if action = "playback_progress" and (outcome = "accepted" or outcome = "updated" or outcome = "applied") then return {ok:true}
    if action = "playback_stop" and (outcome = "stopped" or outcome = "applied" or outcome = "replayed") then return {ok:true}
    return TaskError("invalid_response")
end function

function TaskStartPlayback(provider as String, session as Object, params as Object, revision as Integer) as Object
    status = PublicSessionStatus(provider, session)
    if not status.connected then return TaskError("auth_required")
    if provider = "plex" then return TaskStartPlexPlayback(session, params, revision)
    return TaskStartSiloPlayback(session, params, revision)
end function

function TaskDirectPlexSupported(plan as Object) as Boolean
    ' Production eligibility remains MP4; this helper does not approve MKV.
    if PdcText(plan,"streamFormat") <> "mp4" or PdcText(plan,"container") <> "mp4" then return false
    queries = PlexDirectCapabilityQueries(plan)
    if not queries.ok then return false
    device = CreateObject("roDeviceInfo")
    if not PlexDirectMp4DimensionsAllowed(queries,device.GetVideoMode()) then return false
    ' Native C208X rejects width/height query keys. The independent dimension
    ' ceiling above still rejects unknown or oversized selected-file metadata.
    support = device.CanDecodeVideo(queries.video)
    if not PdcResultTrue(support) then return false
    audio = device.CanDecodeAudio(queries.audio)
    return PlexDirectCapabilityAccepted(queries,support,audio)
end function

function TaskStartPlexPlayback(session as Object, params as Object, revision as Integer) as Object
    if not TaskPlaybackOptionsValid("plex", params) then return TaskError("invalid_request")
    detail = TaskValue(params, "detail", invalid)
    if params.DoesExist("replacementFile")
        expected=PrIdentity(params.replacementFile)
        if expected=invalid then return TaskError("version_required")
        if TaskString(params,"versionId")<>expected.versionId then return TaskError("version_required")
        if expected.sourceId<>TaskString(session,"sourceId") or expected.itemId<>TaskString(params,"itemId") then return TaskError("version_required")
        freshRequest=BuildPlexRequest("detail",session,{itemId:expected.itemId,sourceId:expected.sourceId})
        if not freshRequest.ok then return TaskError("version_required")
        freshResponse=HttpRequest(freshRequest,7000)
        if not freshResponse.ok then return TaskError(TaskString(freshResponse,"errorCode"))
        fresh=DecodePlexResponse("detail",freshResponse.body,{sourceId:expected.sourceId})
        if not fresh.ok then return TaskError(TaskString(fresh,"errorCode"))
        detail=fresh.data
        selectedFile=PrFile(detail,expected.versionId,TaskValue(params,"startPositionMs",invalid))
        if not PrSameFile(selectedFile,expected) then return TaskError("version_required")
        params=PrCopy(params)
        params["detail"]=detail:params["versionIndex"]=selectedFile.versionIndex:params["partIndex"]=selectedFile.partIndex:params["versionId"]=selectedFile.versionId
        if SessionRevision("plex")<>revision then return TaskError("session_changed")
    end if
    if detail = invalid then return TaskError("detail_required")
    versionIndex = TaskValue(params, "versionIndex", 0)
    versions = TaskValue(detail, "versions", [])
    if versionIndex < 0 or versionIndex >= versions.Count() then return TaskError("version_required")
    version = versions[versionIndex]
    if params.DoesExist("versionId")
        expectedVersionId = TaskString(params, "versionId")
        if expectedVersionId = "" or expectedVersionId <> TaskString(version, "versionId") then return TaskError("version_required")
    end if
    mediaIndex = TaskValue(version, "mediaIndex", versionIndex)
    partIndex = TaskValue(version, "partIndex", TaskValue(params, "partIndex", 0))
    direct = PlexDirectPlan(detail, mediaIndex, partIndex, session)
    if direct.ok <> true then return TaskError(TaskString(direct, "errorCode"))
    client=PrIngress(params,direct,detail)
    if params.DoesExist("replacementFile") and client=invalid then return TaskError("invalid_request")
    direct["startPositionMs"] = TaskValue(params, "startPositionMs", TaskValue(direct, "startPositionMs", 0))
    directSupported = false
    ' A decoder capability result cannot prove that a particular MP4 will start.
    ' The error-screen action may explicitly retry this same version over HLS.
    directEligible = TaskValue(params, "forceTranscode", false) <> true
    ' Explicit server lane/quality intent must keep its existing HLS handling;
    ' the direct file branch does not apply these provider transformations.
    for each name in ["audioStreamId","maxVideoBitrate","videoResolution"]
        if params.DoesExist(name) then directEligible = false
    end for
    if directEligible then directSupported = TaskDirectPlexSupported(direct)
    if directSupported
        if SessionRevision("plex") <> revision then return TaskError("session_changed")
        direct["relativeTimeline"] = false
        direct["delivery"] = "direct"
        if client<>invalid then direct["clientIntent"]=client
        data={delivery:"direct"}
        if params.DoesExist("replacementFile") then data["playbackDetail"]=detail
        return {ok: true, data: data, plan: direct}
    end if

    requestParams = {itemId: TaskString(TaskValue(detail, "item", {}), "itemId"), mediaIndex: mediaIndex, partIndex: partIndex, transcodeSessionId: TaskUniqueId(), maxVideoBitrate: 8000, videoResolution: "1920x1080", profileExtra: "add-transcode-target(type=videoProfile&context=streaming&protocol=hls&container=mpegts&videoCodec=h264&audioCodec=aac)", startPositionMs: TaskValue(params, "startPositionMs", TaskValue(direct, "startPositionMs", 0))}
    for each name in ["maxVideoBitrate", "videoResolution"]
        if params.DoesExist(name) then requestParams[name] = params[name]
    end for
    if params.DoesExist("audioStreamId") then requestParams["audioStreamId"] = params.audioStreamId
    decisionRequest = BuildPlexRequest("transcode_decision", session, requestParams)
    if decisionRequest.ok <> true then return TaskError(TaskString(decisionRequest, "errorCode"))
    decisionResponse = HttpRequest(decisionRequest, 7000)
    if decisionResponse.ok <> true then return TaskError(TaskString(decisionResponse, "errorCode"))
    decision = DecodePlexResponse("transcode_decision", decisionResponse.body, {})
    if decision.ok <> true then return TaskError(TaskString(decision, "errorCode"))
    startRequest = BuildPlexRequest("transcode_start", session, requestParams)
    if startRequest.ok <> true then return TaskError(TaskString(startRequest, "errorCode"))
    plan = PlexTranscodePlan(startRequest, session, detail, mediaIndex, partIndex)
    if plan.ok <> true then return TaskError(TaskString(plan, "errorCode"))
    ' SiloUIScene forwards this absolute position to ContentNode.PlayStart.
    ' Preserve explicit Beginning (zero) instead of the cached detail resume.
    plan["startPositionMs"] = direct["startPositionMs"]
    plan["originalResumeMs"] = direct["startPositionMs"]
    plan["sessionId"] = TaskString(requestParams, "transcodeSessionId")
    decisionData = TaskValue(decision, "data", {})
    if TaskString(decisionData, "videoCodec") <> "" then plan["videoCodec"] = TaskString(decisionData, "videoCodec")
    if TaskString(decisionData, "audioCodec") <> "" then plan["audioCodec"] = TaskString(decisionData, "audioCodec")
    if SessionRevision("plex") <> revision
        stopRequest = BuildPlexRequest("transcode_stop", session, requestParams)
        if stopRequest.ok then HttpRequest(stopRequest, 5000)
        return TaskError("session_changed")
    end if
    plan["relativeTimeline"] = false
    plan["delivery"] = "transcode"
    plan["probeSessionRevision"] = revision
    if client<>invalid then plan["clientIntent"]=client
    data={delivery:"transcode"}
    if params.DoesExist("replacementFile") then data["playbackDetail"]=detail
    return {ok: true, data:data, plan: plan}
end function

function TaskRokuSiloAudio(device as Object, containers as Object) as Object
    decode = []:passthrough = []
    for each name in ["aac","ac3","eac3","mp3","flac","dts","opus"]
        for each mode in [0,1]
            supported = true
            for each container in containers
                result = TaskSiloCanDecodeAudio(device,{codec:name,container:container,passthru:mode})
                if not TaskDecoderResult(result) then supported = false
            end for
            if supported
                if mode = 0 then decode.Push(name) else passthrough.Push(name)
            end if
        end for
    end for
    ' Codec support does not establish a channel count or active passthrough.
    return {decode:decode,passthrough:passthrough}
end function

function TaskRokuSiloCapabilities(device as Object, decoderEvidence = invalid as Dynamic) as Object
    avc = TaskDecoderResult(TaskSiloCanDecodeVideo(device,{codec: "mpeg4 avc"}))
    hevcResult = TaskSiloCanDecodeVideo(device,{codec: "hevc"})
    if SiloObject(decoderEvidence)
        decoderEvidence["genericHevcKnown"] = SpBool(SpField(hevcResult,"result"))
        decoderEvidence["genericHevcSupported"] = TaskDecoderResult(hevcResult)
    end if
    mainResult = TaskSiloCanDecodeVideo(device,{codec:"hevc",profile:"main",level:"5.1"})
    hevcMain10 = TaskDecoderResult(TaskSiloCanDecodeVideo(device,{codec:"hevc",profile:"main 10",level:"5.1"}))
    hevc = TaskDecoderResult(hevcResult)
    hevc4k = TaskDecoderResult(mainResult)
    ' Specific positive evidence can fill an unknown broad answer. A typed
    ' negative remains authoritative; suggestions never establish support.
    if not SpBool(SpField(hevcResult,"result")) then hevc = hevc4k or hevcMain10
    if not SpBool(SpField(mainResult,"result")) then hevc4k = hevcMain10
    audio = TaskRokuSiloAudio(device,["mp4","mkv"])
    caps = RokuSiloCapabilities(avc, audio.decode.Count()>0 or audio.passthrough.Count()>0, hevc)
    caps.codecs_audio = audio.decode
    mode = LCase(TaskSiloVideoMode(device))
    if hevc4k and Left(mode,5) = "2160p" then caps["max_resolution"] = "2160p"
    if Left(mode,5) = "1080p" or Left(mode,5) = "1080i" then caps["max_resolution"] = "1080p"
    if Left(mode,4) = "720p" or Left(mode,4) = "480p" or Left(mode,4) = "480i" then caps["max_resolution"] = "720p"
    if caps.containers.Count() > 0 then caps.containers = ["mp4", "m4v", "mov", "mkv"]
    display = TaskSiloDisplayProperties(device)
    details = {hdr10:false,hdr10_plus:false,hlg:false,dolby_vision_profiles:[]}
    knownHdr = false
    if type(display) = "roAssociativeArray"
        knownHdr = SpBool(display.hdr10) or SpBool(display.hdr10Plus) or SpBool(display.hlg)
        details.hdr10 = display.hdr10 = true and hevcMain10
        details.hdr10_plus = display.hdr10Plus = true and hevcMain10
        details.hlg = display.hlg = true and hevcMain10
    end if
    ' Display flags do not establish Dolby Vision decoder profiles or active HDR.
    if knownHdr then caps["hdr_details"] = details
    caps.hdr = knownHdr and (details.hdr10 or details.hdr10_plus or details.hlg)
    return caps
end function


' Request-local proven AAC output adaptation. Generic codec support cannot prove the
' selected surround layout. Positive source routes change only when the
' requested plain height already requires video encoding.
function TaskSiloAudioProjection(wire as Dynamic, fileId as String, selected as Dynamic, quality as String, device as Object, capabilities as Object, context as Object) as Dynamic
    if not SiloContains(["original","4k","1080p","720p","480p"],quality) then return invalid
    hls = SpField(SpField(context,"deliveries"),"hls")
    if SpField(hls,"enabled") <> true or SpField(hls,"supported_on_device") <> true then return invalid
    if not SiloObject(wire) or not SiloArray(SpField(wire,"versions")) then return invalid
    if wire.versions.Count() > 16 then return invalid
    file = invalid
    for each version in wire.versions
        if SiloObject(version) and SiloText(SpField(version,"file_id")) = fileId
            if file <> invalid then return invalid
            file = version
        end if
    end for
    if file = invalid then return invalid
    container = LCase(TaskString(file,"container"))
    if container = "m4v" or container = "mov" then container = "mp4"
    if not SiloContains(["mkv","mp4","ts"],container) then return invalid
    tracks = SpField(file,"audio_tracks")
    if not SiloArray(tracks) then return invalid
    if tracks.Count() = 0 or tracks.Count() > 32 then return invalid
    ordinal = 0
    if selected = invalid
        if tracks.Count() <> 1 then return invalid
    else
        if not SpFields(selected,["id","index"],[]) then return invalid
        ordinal = selected.index
        if not SpNumber(ordinal,tracks.Count()-1,true) then return invalid
        if selected.id <> "file:"+fileId+":audio:"+Int(ordinal).ToStr() then return invalid
    end if
    for each track in tracks
        if not SiloObject(track) then return invalid
    end for
    track = tracks[ordinal]
    codec = LCase(TaskString(track,"codec")):channels = SpField(track,"channels")
    ' Bounded known FFmpeg source codecs; no unknown/empty scanner fallback.
    if not SiloContains(["aac","ac3","eac3","dts","truehd","flac","opus","mp3"],codec) then return invalid
    if not SpNumber(channels,8,true) then return invalid
    if channels < 2 then return invalid
    encodingRequired = false:sourceHeight = 0
    targets = {"4k":2160,"1080p":1080,"720p":720,"480p":480}
    videos = SpField(file,"video_tracks")
    if targets.DoesExist(quality) and SiloArray(videos)
        if videos.Count() = 1
            height = SpField(videos[0],"height"):width = SpField(videos[0],"width")
            ' The server replaces both dimensions if either is unknown/zero.
            if SpNumber(height,16384,true) and SpNumber(width,16384,true)
                if width > 0 and height > targets[quality] then encodingRequired = true:sourceHeight = height
            end if
        end if
    end if
    original = SpField(SpField(context,"deliveries"),"original_http")
    originalUsable = SpField(original,"enabled") = true and SpField(original,"supported_on_device") = true
    for each sourceContainer in [container,"ts"]
        ' Source-container support matters only while Original is available.
        ' Native HLS still needs its own exact TS audio support.
        if sourceContainer = "ts" or originalUsable
            for each mode in [0,1]
                if TaskDecoderResult(TaskSiloCanDecodeAudio(device,{codec:codec,container:sourceContainer,chcnt:Int(channels),passthru:mode})) and not encodingRequired then return invalid
            end for
        end if
    end for
    allowedOutputs = []:ceiling = 0
    if TaskDecoderResult(TaskSiloCanDecodeAudio(device,{codec:"aac",container:"ts",chcnt:2,passthru:0})) then allowedOutputs.Push(2):ceiling = 2
    if channels >= 6
        if TaskDecoderResult(TaskSiloCanDecodeAudio(device,{codec:"aac",container:"ts",chcnt:6,passthru:0})) then allowedOutputs.Push(6):ceiling = 6
    end if
    if ceiling = 0 then return invalid
    projected = SpCopy(capabilities):projected.codecs_audio = ["aac"]
    output = SpCopy(context)
    output.deliveries.original_http.enabled = false:output.deliveries.original_http.supported_on_device = false
    lane = output.deliveries.hls
    lane.audio_decode_codecs = ["aac"]:lane.audio_passthrough_codecs = []:lane["max_channels"] = ceiling
    return {capabilities:projected,context:output,allowedOutputs:allowedOutputs,encodingRequired:encodingRequired,sourceHeight:sourceHeight,proof:{fileId:fileId,container:LCase(TaskString(file,"container")),audio:{id:"file:"+fileId+":audio:"+Int(ordinal).ToStr(),index:ordinal,codec:codec,channels:channels}}}
end function

function TaskSiloAudioProjectionReceipt(decision as Object, projection as Object) as Boolean
    proof = projection.proof
    raw = SpField(decision,"playback_plan")
    if not SiloObject(raw) then return false
    if raw.requested_media_file_id <> proof.fileId or raw.effective_media_file_id <> proof.fileId then return false
    if not SiloContains(["server_remux_hls","server_transcode_hls"],SpField(raw,"delivery")) then return false
    source = SpField(raw,"source"):audio = SpField(SpField(raw,"selected_tracks"),"audio"):recipe = SpField(raw,"effective_recipe")
    if SpField(source,"media_file_id") <> proof.fileId or SpField(source,"container") <> proof.container then return false
    if SpField(source,"audio_codec") <> proof.audio.codec or SpField(source,"audio_channels") <> proof.audio.channels then return false
    if projection.encodingRequired
        if raw.delivery <> "server_transcode_hls" or SpField(source,"height") <> projection.sourceHeight then return false
    end if
    if SpField(audio,"id") <> proof.audio.id or SpField(audio,"index") <> proof.audio.index then return false
    channels = SpField(recipe,"audio_channels")
    if SpField(recipe,"audio_codec") <> "aac" or not SiloContains(projection.allowedOutputs,channels) then return false
    layout = "stereo"
    if channels = 6 then layout = "5.1"
    if SiloObject(recipe) then if recipe.DoesExist("audio_layout") then if recipe.audio_layout <> layout then return false
    transforms = SpField(raw,"transformations")
    if not SiloArray(transforms) then return false
    conversions = 0
    for each transform in transforms
        if SpField(transform,"name") = "audio_to_aac"
            if SpField(transform,"executor") <> "server" or not SiloContains(["2","4"],SpField(transform,"recipe_version")) then return false
            conversions++
        end if
    end for
    return conversions = 1
end function

' Last available delivery only. This proves output stereo, never source audio.
function TaskSiloLastStereoHLS(device as Object, server as Object, capabilities as Object, context as Object) as Dynamic
    for each name in ["original_http","hls"]
        lane = context.deliveries[name]
        if lane.enabled = true and lane.supported_on_device = true then return invalid
    end for
    if not TaskDecoderResult(TaskSiloCanDecodeAudio(device,{codec:"aac",container:"ts",chcnt:2,passthru:0})) then return invalid
    projected = SpCopy(capabilities):output = SpCopy(context)
    output = TaskNegotiateSiloHLS(output,device,server,projected,{decode:["aac"],passthrough:[]})
    if output.deliveries.hls.enabled <> true or output.deliveries.hls.supported_on_device <> true then return invalid
    projected.codecs_audio = ["aac"]:projected.containers = ["hls"]
    for each name in ["original_http","progressive"]
        output.deliveries[name].enabled = false:output.deliveries[name].supported_on_device = false
    end for
    output.deliveries.hls["max_channels"] = 2
    return {capabilities:projected,context:output}
end function

function TaskSiloLastStereoReceipt(decision as Object) as Boolean
    raw = SpField(decision,"playback_plan")
    if not SiloContains(["server_remux_hls","server_transcode_hls"],SpField(raw,"delivery")) then return false
    recipe = SpField(raw,"effective_recipe")
    if SpField(recipe,"audio_codec") <> "aac" or SpField(recipe,"audio_channels") <> 2 then return false
    if SiloObject(recipe) then if recipe.DoesExist("audio_layout") then if recipe.audio_layout <> "stereo" then return false
    tracks = TaskSiloDecisionTracks(SpField(raw,"selected_tracks"))
    return SiloObject(SpField(tracks,"audio"))
end function

 ' A 4K30 file can be supported when the aggregate 4K60 Main10 probe is not.
' This evidence belongs only to one fresh selected source and Original request.
function TaskSiloLevel50HDR10(wire as Dynamic, detail as Dynamic, sourceId as String, itemId as String, fileId as String, targetMs as Double, intent as Dynamic, device as Object, capabilities as Object, context as Object, decoderEvidence = invalid as Dynamic) as Dynamic
    if SpField(SpField(capabilities,"hdr_details"),"hdr10") = true then return invalid
    missingHevc = not SiloContains(SiloList(SpField(capabilities,"codecs_video")),"hevc")
    if missingHevc
        ' Only the same request's unknown generic answer may reach exact 5.0 proof.
        if not SiloObject(decoderEvidence) then return invalid
        if not SpBool(SpField(decoderEvidence,"genericHevcKnown")) or not SpBool(SpField(decoderEvidence,"genericHevcSupported")) then return invalid
        if decoderEvidence.genericHevcKnown <> false or decoderEvidence.genericHevcSupported <> false then return invalid
    end if
    if TaskString(intent,"qualityPreference") <> "original" then return invalid
    if Left(LCase(TaskSiloVideoMode(device)),5) <> "2160p" then return invalid
    if not SiloObject(wire) or not SiloArray(SpField(wire,"versions")) then return invalid
    raw = invalid
    for each candidate in wire.versions
        if SiloObject(candidate) and SiloText(SpField(candidate,"file_id")) = fileId
            if raw <> invalid then return invalid
            raw = candidate
        end if
    end for
    if raw = invalid then return invalid
    if not SpBool(SpField(raw,"hdr")) or raw.hdr <> true then return invalid
    videos = SpField(raw,"video_tracks")
    if not SiloArray(videos) then return invalid
    if videos.Count() <> 1 then return invalid
    video = videos[0]
    if not SiloObject(video) then return invalid
    if LCase(TaskString(video,"codec")) <> "hevc" then return invalid
    profile = LCase(TaskString(video,"profile"))
    if profile <> "main 10" and profile <> "main10" then return invalid
    if not SpNumber(SpField(video,"level"),1000,true) or not SpNumber(SpField(video,"bit_depth"),16,true) then return invalid
    if not SpBool(SpField(video,"interlaced")) or not SpBool(SpField(video,"hdr10_plus")) then return invalid
    if SpField(video,"level") <> 150 or SpField(video,"bit_depth") <> 10 or SpField(video,"interlaced") <> false then return invalid
    width = SpField(video,"width"):height = SpField(video,"height")
    if not SpNumber(width,3840,true) or not SpNumber(height,2160,true) then return invalid
    if width <= 0 or height <= 0 then return invalid
    rate = TaskString(video,"frame_rate")
    if not TaskSiloFrameRateKnown(rate) then return invalid
    if SoFrameRate(rate) > 30 then return invalid
    if SpField(video,"hdr10_plus") <> false then return invalid
    rangeType = LCase(TaskString(video,"video_range_type")):range = LCase(TaskString(video,"video_range")):transfer = LCase(TaskString(video,"color_transfer"))
    if rangeType <> "" and rangeType <> "hdr10" then return invalid
    if range <> "" and range <> "hdr10" then return invalid
    if transfer <> "" and transfer <> "smpte2084" then return invalid
    if rangeType <> "hdr10" and range <> "hdr10" and transfer <> "smpte2084" then return invalid
    if TaskString(video,"dolby_vision") <> "" or TaskString(video,"dv_enhancement_layer") <> "" then return invalid
    for each key in ["dv_profile","dv_level","dv_bl_compat_id"]
        if video.DoesExist(key) then if not SpNumber(video[key],1000,true) then return invalid
        if TaskValue(video,key,0) <> 0 then return invalid
    end for
    for each key in ["dv_config_present","dv_bl_compat_id_present","dv_bl_present","dv_rpu_present","dv_el_present","video_copy_unsafe"]
        if video.DoesExist(key) then if not SpBool(video[key]) then return invalid
        if SpField(video,key) = true then return invalid
    end for
    bitrate = SpField(raw,"bitrate"):cap = SpField(intent,"bandwidthCapKbps",0)
    if not SpNumber(bitrate,2147483646) or not SpNumber(cap,2147483646,true) then return invalid
    if bitrate <= 0 then return invalid
    if cap > 0 and bitrate > cap then return invalid
    sourceBitrate = SoSourceBitrate(raw)
    if not SpNumber(sourceBitrate,2147483646) or sourceBitrate <= 0 then return invalid
    if cap > 0 and sourceBitrate > cap then return invalid
    display = TaskSiloDisplayProperties(device)
    if not SpBool(SpField(display,"hdr10")) or SpField(display,"hdr10") <> true then return invalid
    file = SiloPlaybackFile(detail,sourceId,itemId,fileId,targetMs)
    if file = invalid then return invalid
    projected = SpCopy(capabilities):output = SpCopy(context)
    hdr = {hdr10:true,hdr10_plus:false,hlg:false,dolby_vision_profiles:[],hdr10_max_width:width,hdr10_max_height:height,hdr10_max_frame_rate:30,hdr10_max_bitrate_kbps:sourceBitrate}
    projected.hdr = true:projected["hdr_details"] = SpCopy(hdr):projected["max_resolution"] = "2160p"
    output.output["hdr_details"] = SpCopy(hdr)
    output.output.display = {hdr_evidence:"exact",hdr_types:SpCopy(hdr)}
    for each name in ["original_http","progressive","hls"]
        output.deliveries[name]["hdr_details"] = SpCopy(hdr)
    end for
    ' The real source proof supplies the actual-container exact decoder query,
    ' output bounds and existing audio constraints; aggregate evidence is untouched.
    score = TaskSiloVersionProof(file.version,device,projected,output,intent)
    if score = invalid then return invalid
    if missingHevc
        usable = false:originalProven = false:hlsProven = false:hlsFeatures = []
        lane = output.deliveries.original_http
        if lane.enabled = true and lane.supported_on_device = true and SiloContains(lane.containers,TaskString(file.version,"container"))
            if not SiloContains(lane.video_codecs,"hevc") then lane.video_codecs.Push("hevc")
            usable = true:originalProven = true
        end if
        lane = output.deliveries.hls
        if lane.enabled = true and lane.supported_on_device = true
            containers = []
            if SiloContains(lane.features,"hls_copy_mpegts_v1") then containers.Push("ts"):hlsFeatures.Push("hls_copy_mpegts_v1")
            if SiloContains(lane.features,"native_hls_mpegts_v1") then containers.Push("ts"):hlsFeatures.Push("native_hls_mpegts_v1")
            if SiloContains(lane.features,"native_hls_separate_audio_v1") then containers.Push("mp4"):hlsFeatures.Push("native_hls_separate_audio_v1")
            proven = containers.Count() > 0
            for each container in containers
                if not TaskDecoderResult(TaskSiloCanDecodeVideo(device,{codec:"hevc",container:container,profile:"main 10",level:"5.0"})) then proven = false
            end for
            if proven
                if not SiloContains(lane.video_codecs,"hevc") then lane.video_codecs.Push("hevc")
                usable = true:hlsProven = true
            end if
        end if
        if not usable then return invalid
        projected.codecs_video.Push("hevc")
    end if
    proof = {fileId:fileId,container:TaskString(file.version,"container"),video:SpCopy(file.version.videoTracks[0]),bitrate:sourceBitrate}
    if missingHevc
        proof["deliveries"] = {original_http:originalProven,hls:hlsProven}
        proof["hlsFeatures"] = hlsFeatures
    end if
    return {capabilities:projected,context:output,score:score,proof:proof}
end function

function TaskSiloLevel50HDR10Receipt(decision as Object, proof as Object) as Boolean
    raw = SpField(decision,"playback_plan")
    if not SiloObject(raw) then return false
    if raw.requested_media_file_id <> proof.fileId or raw.effective_media_file_id <> proof.fileId then return false
    if not SiloContains(["original_http","server_remux_hls"],SpField(raw,"delivery")) then return false
    if proof.DoesExist("deliveries")
        lane = "original_http"
        if raw.delivery = "server_remux_hls" then lane = "hls"
        if not SpBool(SpField(SpField(proof,"deliveries"),lane)) then return false
        if proof.deliveries[lane] <> true then return false
        if lane = "hls"
            feature = "native_hls_separate_audio_v1"
            if SpField(SpField(raw,"effective_recipe"),"segment_container") = "mpegts" then feature = "hls_copy_mpegts_v1"
            if not SiloContains(SiloList(SpField(proof,"hlsFeatures")),feature) then return false
        end if
    end if
    source = SpField(raw,"source")
    if not SiloObject(source) then return false
    if source.media_file_id <> proof.fileId or source.container <> proof.container then return false
    if source.video_codec <> "hevc" or source.video_level <> 150 or source.bit_depth <> 10 then return false
    profile = LCase(TaskString(source,"video_profile"))
    if profile <> "main 10" and profile <> "main10" then return false
    if source.dynamic_range <> "hdr10" or source.hdr10_plus <> false then return false
    if TaskValue(source,"dolby_vision_profile",0) <> 0 or TaskValue(source,"dolby_vision_level",0) <> 0 then return false
    if TaskValue(source,"dv_bl_compat_id",0) <> 0 or SpField(source,"dv_base_layer_proven") = true then return false
    enhancement = TaskString(source,"dv_enhancement_layer")
    if enhancement <> "" and enhancement <> "none" then return false
    if SpField(source,"video_copy_unsafe") = true then return false
    if source.width <> proof.video.width or source.height <> proof.video.height then return false
    if not SoNear(source.frame_rate,SoFrameRate(proof.video.frame_rate)) or source.bitrate_kbps <> proof.bitrate then return false
    recipe = SpField(raw,"effective_recipe")
    if raw.delivery = "server_remux_hls" and not SiloObject(recipe) then return false
    if SiloObject(recipe)
        if recipe.video_codec <> "hevc" or recipe.dynamic_range <> "hdr10" then return false
        if recipe.width <> proof.video.width or recipe.height <> proof.video.height then return false
        if not SoNear(recipe.frame_rate,SoFrameRate(proof.video.frame_rate)) or recipe.bitrate_kbps <> proof.bitrate then return false
    end if
    for each transform in SiloList(SpField(raw,"transformations"))
        if not SiloContains(["hls_separate_audio","audio_to_aac"],TaskString(transform,"name")) then return false
        if TaskString(transform,"executor") <> "server" then return false
    end for
    return true
end function

' A fresh single-lane MP4 source can prove Original independently of MKV/TS.
' This request projection never broadens the global container/audio product.
function TaskSiloMp4Original(wire as Dynamic, detail as Dynamic, sourceId as String, itemId as String, fileId as String, targetMs as Double, intent as Object, device as Object, capabilities as Object, context as Object) as Dynamic
    if TaskString(intent,"qualityPreference") <> "original" then return invalid
    if not SiloObject(wire) or not SiloArray(wire.versions) then return invalid
    raw = invalid
    for each candidate in wire.versions
        if SiloObject(candidate) and SiloText(SpField(candidate,"file_id")) = fileId
            if raw <> invalid then return invalid
            raw = candidate
        end if
    end for
    if raw = invalid then return invalid
    if not SpBool(SpField(raw,"hdr")) or raw.hdr <> false then return invalid
    if not SiloArray(SpField(raw,"audio_tracks")) or not SiloArray(SpField(raw,"video_tracks")) then return invalid
    if raw.audio_tracks.Count() <> 1 or raw.video_tracks.Count() <> 1 then return invalid
    if not SiloObject(raw.audio_tracks[0]) or not SiloObject(raw.video_tracks[0]) then return invalid
    if intent.DoesExist("subtitleTrackId") or intent.DoesExist("subtitleTrackIndex") then return invalid
    file = SiloPlaybackFile(detail,sourceId,itemId,fileId,targetMs)
    if file = invalid then return invalid
    version = file.version
    if TaskString(version,"container") <> "mp4" or TaskString(version,"videoCodec") <> "h264" or version.hdr <> false then return invalid
    tracks = SpField(version,"audioTracks")
    if not SiloArray(tracks) or tracks.Count() <> 1 then return invalid
    audio = tracks[0]
    if TaskString(audio,"codec") <> "aac" or SpField(audio,"channels") <> 2 or SpField(audio,"sourceOrdinal") <> 0 then return invalid
    if TaskString(version,"audioCodec") <> "aac" then return invalid
    if intent.DoesExist("audioTrackIndex") then if intent.audioTrackIndex <> 0 then return invalid
    if intent.DoesExist("audioTrackId") then if intent.audioTrackId <> "file:"+fileId+":audio:0" then return invalid
    if intent.DoesExist("subtitleMode")
        if intent.subtitleMode <> "off" then return invalid
    else if SiloList(SpField(version,"subtitleTracks")).Count() > 0
        return invalid
    end if
    cap = SpField(intent,"bandwidthCapKbps",0)
    if not SpNumber(cap,2147483646,true) then return invalid
    if cap > 0
        if not SpNumber(version.bitrateKbps,2147483646) then return invalid
        if version.bitrateKbps <= 0 or version.bitrateKbps > cap then return invalid
    end if
    if TaskSiloVersionProof(version,device,capabilities,context,intent) = invalid then return invalid
    if not TaskDecoderResult(TaskSiloCanDecodeAudio(device,{codec:"aac",container:"mp4",chcnt:2,passthru:0})) then return invalid
    projected = SpCopy(capabilities)
    projected.containers = ["mp4"]:projected.codecs_video = ["h264"]:projected.codecs_video_hardware = []:projected.codecs_audio = ["aac"]:projected.hdr = false
    if TaskString(projected,"max_resolution") <> "720p" then projected["max_resolution"] = "1080p"
    projected.Delete("hdr_details")
    output = SpCopy(context)
    lane = output.deliveries.original_http
    lane.enabled = true:lane.supported_on_device = true:lane.containers = ["mp4"]:lane.video_codecs = ["h264"]:lane.audio_decode_codecs = ["aac"]:lane.audio_passthrough_codecs = []:lane["max_channels"] = 2
    lane.Delete("hdr_details")
    return {capabilities:projected,context:output,proof:{fileId:fileId,video:SpCopy(version.videoTracks[0]),audio:{id:"file:"+fileId+":audio:0",index:0}}}
end function

function TaskSiloMp4Receipt(decision as Object, proof as Object) as Boolean
    raw = SpField(decision,"playback_plan")
    if not SiloObject(raw) then return false
    if SpField(raw,"delivery") <> "original_http" then return false
    if SpField(SpField(raw,"stream"),"container") <> "mp4" then return false
    source = SpField(raw,"source")
    if not SiloObject(source) then return false
    if SpField(source,"media_file_id") <> proof.fileId then return false
    if SpField(source,"video_codec") <> "h264" or SpField(source,"audio_codec") <> "aac" or SpField(source,"audio_channels") <> 2 then return false
    if SpField(source,"width") <> proof.video.width or SpField(source,"height") <> proof.video.height then return false
    if source.DoesExist("video_profile") then if LCase(TaskString(source,"video_profile")) <> LCase(TaskString(proof.video,"profile")) then return false
    if source.DoesExist("video_level") then if source.video_level <> proof.video.level then return false
    if SpField(source,"hdr10_plus") = true or TaskValue(source,"dolby_vision_profile",0) <> 0 then return false
    if source.DoesExist("bit_depth") then if source.bit_depth <> 8 then return false
    if source.DoesExist("dynamic_range") then if source.dynamic_range <> "sdr" then return false
    if source.DoesExist("container") then if source.container <> "mp4" then return false
    if source.DoesExist("frame_rate") then if not SoNear(source.frame_rate,SoFrameRate(proof.video.frame_rate)) then return false
    if source.DoesExist("dv_enhancement_layer") then if not SpText(source.dv_enhancement_layer,16,true) then return false
    enhancement = TaskString(source,"dv_enhancement_layer")
    if enhancement <> "" and enhancement <> "none" then return false
    audio = SpField(SpField(raw,"selected_tracks"),"audio")
    if SpField(audio,"id") <> proof.audio.id or SpField(audio,"index") <> proof.audio.index then return false
    if raw.DoesExist("effective_recipe")
        recipe = raw.effective_recipe
        if not SiloObject(recipe) then return false
        expected = {video_codec:"h264",audio_codec:"aac",dynamic_range:"sdr",width:proof.video.width,height:proof.video.height,audio_channels:2}
        for each key in expected
            if recipe.DoesExist(key) then if recipe[key] <> expected[key] then return false
        end for
        if recipe.DoesExist("frame_rate") then if not SoNear(recipe.frame_rate,SoFrameRate(proof.video.frame_rate)) then return false
    end if
    if SiloList(SpField(raw,"transformations")).Count() > 0 then return false
    return SiloSubtitleOffReceipt(raw)
end function

' Canonical TS must prove the copied source profile within a supported level.
function TaskSiloDeliveredHLSSupported(raw as Object, device as Object) as Boolean
    recipe = SpField(raw,"effective_recipe")
    if SpField(recipe,"segment_container") = "mpegts"
        source = SpField(raw,"source")
        if not SiloObject(source) then return false
        if not SpText(SpField(source,"video_codec"),16) then return false
        if source.video_codec <> recipe.video_codec or SpField(source,"video_copy_unsafe") = true then return false
        codec = SpField(recipe,"video_codec"):profile = LCase(TaskString(source,"video_profile"))
        if profile = "main10" then profile = "main 10"
        if codec = "hevc"
            if not SiloContains(["main","main 10"],profile) then return false
            levels = {"90":"3.0","93":"3.1","120":"4.0","123":"4.1","150":"5.0","153":"5.1","156":"5.2","180":"6.0","183":"6.1","186":"6.2"}
        else if codec = "h264"
            codec = "mpeg4 avc"
            if not SiloContains(["baseline","main","high"],profile) then return false
            levels = {"30":"3.0","31":"3.1","32":"3.2","40":"4.0","41":"4.1","42":"4.2","50":"5.0","51":"5.1","52":"5.2"}
        else
            return false
        end if
        level = SpField(source,"video_level")
        if not SpNumber(level,1000,true) then return false
        key = Int(level).ToStr()
        if not levels.DoesExist(key) then return false
        if not TaskSiloSourceVideoSupported(device,{codec:codec,container:"ts",profile:profile,level:levels[key]}) then return false
    end if
    return TaskSiloDeliveredHLSAudioSupported(raw,device)
end function

' Split HLS also delivers TS audio; prove the actual codec and channel count.
function TaskSiloDeliveredHLSAudioSupported(raw as Object, device as Object) as Boolean
    if LCase(SiloText(SpField(SpField(raw,"stream"),"protocol"))) <> "hls" then return true
    if not SiloContains(["server_remux_hls","server_transcode_hls"],SpField(raw,"delivery")) then return false
    recipe = SpField(raw,"effective_recipe")
    codec = SpField(recipe,"audio_codec"):channels = SpField(recipe,"audio_channels")
    if not SpText(codec,16) or not SiloContains(["aac","ac3","eac3"],codec) then return false
    if not SpNumber(channels,8,true) or channels = 0 then return false
    decode = TaskSiloCanDecodeAudio(device,{codec:codec,chcnt:channels,container:"ts",passthru:0})
    passthrough = TaskSiloCanDecodeAudio(device,{codec:codec,chcnt:channels,container:"ts",passthru:1})
    if TaskDecoderResult(decode) or TaskDecoderResult(passthrough) then return true
    ' AAC stereo is the documented decode baseline. Older SDKs may leave the
    ' exact-channel answer unknown; a fresh same-TS generic decode must prove it.
    ' An explicit exact negative, surround, or passthrough is never inferred.
    if codec = "aac" and channels = 2 and not SpBool(SpField(decode,"result"))
        return TaskDecoderResult(TaskSiloCanDecodeAudio(device,{codec:"aac",container:"ts",passthru:0}))
    end if
    return false
end function

function TaskSiloSourceVideoSupported(device as Object, query as Object) as Boolean
    answer = TaskSiloCanDecodeVideo(device,query)
    if TaskDecoderResult(answer) then return true
    if query.codec <> "mpeg4 avc" then return false
    if not SpBool(SpField(answer,"result")) then return false
    if not SpText(SpField(answer,"updated"),5) then return false
    if answer.result <> false or answer.updated <> "level" then return false
    for each field in ["codec","container","profile"]
        if SiloObject(answer) and answer.DoesExist(field)
            if not SpText(answer[field],32) then return false
            if answer[field] <> query[field] then return false
        end if
    end for
    levels = ["3.0","3.1","3.2","4.0","4.1","4.2","5.0","5.1","5.2"]
    suggestions = SpField(answer,"level")
    if type(suggestions) <> "roArray" then return false
    if suggestions.Count() = 0 or suggestions.Count() > levels.Count() then return false
    if not SiloContains(levels,query.level) then return false
    ceiling = ""
    for each level in suggestions
        if not SpText(level,3) then return false
        if not SiloContains(levels,level) then return false
        if level > query.level
            if ceiling = "" or level < ceiling then ceiling = level
        end if
    end for
    if ceiling = "" then return false
    ' A level hint is only a ceiling candidate; prove it with the same format.
    compatible = SpCopy(query)
    compatible.level = ceiling
    return TaskDecoderResult(TaskSiloCanDecodeVideo(device,compatible))
end function

function TaskSiloCanDecodeVideo(device as Object, query as Object) as Dynamic
    try
        return device.CanDecodeVideo(query)
    catch exception
        return invalid
    end try
end function

function TaskSiloCanDecodeAudio(device as Object, query as Object) as Dynamic
    try
        return device.CanDecodeAudio(query)
    catch exception
        return invalid
    end try
end function

function TaskSiloVideoMode(device as Object) as String
    try
        mode = device.GetVideoMode()
        if type(mode) = "String" or type(mode) = "roString" then return mode
    catch exception
        return ""
    end try
    return ""
end function

function TaskSiloDisplayProperties(device as Object) as Object
    try
        display = device.GetDisplayProperties()
        if type(display) = "roAssociativeArray" then return display
    catch exception
        return {}
    end try
    return {}
end function

function TaskDecoderResult(result as Dynamic) as Boolean
    if type(result) <> "roAssociativeArray" then return false
    if not result.DoesExist("result") then return false
    if not SpBool(result.result) then return false
    return result.result = true
end function

function TaskRokuSiloContext(device as Object, capabilities as Object) as Object
    enabled = capabilities.containers.Count() > 0
    deliveries = {}
    output = {display:{hdr_evidence:"unknown"}}
    if capabilities.DoesExist("hdr_details")
        output["hdr_details"] = capabilities.hdr_details
        output.display = {hdr_evidence:"exact",hdr_types:capabilities.hdr_details}
    end if
    for each name in ["original_http","progressive","hls"]
        containers = ["mp4","m4v","mov","mkv"]
        probes = ["mp4","mkv"]
        embedded = true
        if name = "hls" then containers = []:embedded = false
        audio = TaskRokuSiloAudio(device,probes)
        subs = {embedded_text:embedded,sidecar_text:true,ass_styling:false,embedded_bitmap:false,sidecar_bitmap:false,font_attachments:false}
        deliveries[name] = {enabled:enabled,supported_on_device:enabled,containers:containers,video_codecs:capabilities.codecs_video,audio_decode_codecs:audio.decode,audio_passthrough_codecs:audio.passthrough,subtitles:subs,features:[],auth_header_refresh:false,validated_claims:[],transformations:[]}
        if name = "progressive"
            ' Silo pipes generated MP4 as chunked HTTP 200. Roku's progressive
            ' reader requests byte ranges that this generated stream cannot
            ' serve. Original files have real range support; remuxes use HLS.
            deliveries[name].enabled = false
            deliveries[name].supported_on_device = false
            deliveries[name]["failure_reason"] = "native_http_range_unavailable"
        end if
        if name = "hls"
            deliveries[name].enabled = false
            deliveries[name].supported_on_device = false
            deliveries[name].video_codecs = []
            deliveries[name].audio_decode_codecs = []
            deliveries[name].audio_passthrough_codecs = []
            deliveries[name]["failure_reason"] = "native_audio_unverified"
        end if
        if capabilities.DoesExist("hdr_details") then deliveries[name]["hdr_details"] = capabilities.hdr_details
    end for
    return {protocol_version:3,form_factor:"tv",app_version:RuntimeAppVersion(),device:{platform:"roku",model:device.GetModel()},output:output,deliveries:deliveries}
end function

' Format support is negotiated per request and per output. A server feature
' means it understands the recipe, not that every worker has its toolchain.
function TaskNegotiateSiloHLS(context as Object, device as Object, server as Object, capabilities as Object, audioEvidence = invalid as Dynamic) as Object
    if not SiloObject(server) then return context
    serverFeatures = SiloList(server.features):serverDeliveries = SiloList(server.deliveries)
    nativeCopy = SiloContains(serverDeliveries,"server_remux_hls") and (SiloContains(serverFeatures,"hls_copy_mpegts_v1") or SiloContains(serverFeatures,"native_hls_mpegts_v1") or SiloContains(serverFeatures,"native_hls_separate_audio_v1"))
    legacyEncode = SiloContains(serverDeliveries,"server_transcode_hls")
    if not nativeCopy and not legacyEncode then return context
    probedAudio = audioEvidence
    if probedAudio = invalid then probedAudio = TaskRokuSiloAudio(device,["ts"])
    audio = {decode:[],passthrough:[]}
    for each codec in ["aac","ac3","eac3"]
        if SiloContains(probedAudio.decode,codec) then audio.decode.Push(codec)
        if SiloContains(probedAudio.passthrough,codec) then audio.passthrough.Push(codec)
    end for
    video = []
    for each codec in capabilities.codecs_video
        if codec = "h264" or (nativeCopy and codec = "hevc") then video.Push(codec)
    end for
    if video.Count() = 0 or audio.decode.Count()+audio.passthrough.Count() = 0 then return context
    if not nativeCopy and not SiloContains(audio.decode,"aac") then return context
    details = invalid
    if capabilities.DoesExist("hdr_details") then details = SpCopy(capabilities.hdr_details)
    display = TaskSiloDisplayProperties(device)
    allowDV = false
    if nativeCopy and (SiloContains(serverFeatures,"hls_copy_mpegts_v1") or SiloContains(serverFeatures,"native_hls_separate_audio_v1")) and SpField(display,"DolbyVision") = true
        maxDVLevel = 0
        for each bound in [{level:"5.1",dvLevel:9},{level:"5.0",dvLevel:7},{level:"4.1",dvLevel:5},{level:"4.0",dvLevel:4}]
            if maxDVLevel = 0 and TaskDecoderResult(TaskSiloCanDecodeVideo(device,{codec:"hevc",profile:"main 10",level:bound.level})) then maxDVLevel = bound.dvLevel
        end for
        bounds = []
        if Left(LCase(TaskSiloVideoMode(device)),5) = "2160p" and maxDVLevel > 0
            ' Optional DV identity cannot invalidate independently proven SDR/HLS.
            try
                bounds = RokuSiloDVProfileBounds(device.GetModel(),device.GetModelType(),TaskString(device.GetModelDetails(),"ModelNumber"),device.GetOSVersion(),maxDVLevel)
            catch optionalDVIdentityError
                bounds = []
            end try
        end if
        if bounds.Count() > 0
            if details = invalid then details = {hdr10:false,hdr10_plus:false,hlg:false,dolby_vision_profiles:[]}
            details.dolby_vision_profiles = []
            for each bound in bounds
                details.dolby_vision_profiles.Push(bound.profile)
                if bound.profile = 8 then allowDV = true
            end for
            details["dolby_vision_profile_levels"] = bounds
            capabilities["hdr_details"] = SpCopy(details)
            capabilities.hdr = true
            context.output["hdr_details"] = SpCopy(details)
            context.output["display"] = {hdr_evidence:"exact",hdr_types:SpCopy(details)}
        end if
    end if
    features = ["native_hls_playback_v1"]
    if nativeCopy
        for each name in SiloNegotiatedNativeFeatures(serverFeatures,allowDV)
            features.Push(name)
        end for
    end if
    hls = {enabled:true,supported_on_device:true,containers:["hls"],video_codecs:video,audio_decode_codecs:audio.decode,audio_passthrough_codecs:audio.passthrough,
        subtitles:{embedded_text:false,sidecar_text:true,ass_styling:false,embedded_bitmap:false,sidecar_bitmap:false,font_attachments:false},features:features,auth_header_refresh:false,validated_claims:[],transformations:[]}
    if details <> invalid and nativeCopy then hls["hdr_details"] = SpCopy(details)
    context.deliveries.hls = hls
    return context
end function

function TaskSiloFrameRateKnown(rate as String) as Boolean
    if not CreateObject("roRegex","^[0-9]+([.][0-9]+)?(/[0-9]+([.][0-9]+)?)?$","").IsMatch(rate) then return false
    parts = rate.Tokenize("/")
    numerator = Val(parts[0]):denominator = 1
    if parts.Count() = 2 then denominator = Val(parts[1])
    if not SpNumber(numerator,1000000000) or not SpNumber(denominator,1000000000) then return false
    if numerator <= 0 or denominator <= 0 then return false
    return numerator / denominator <= 60
end function

' An upgrade needs complete source signal facts and fresh native checks. A
' generic HEVC flag, a 4K output, or a DV display badge cannot prove a file.
function TaskSiloVersionProof(version as Object, device as Object, capabilities as Object, context = invalid as Dynamic, requestIntent = invalid as Dynamic) as Dynamic
    tracks = SpField(version,"videoTracks")
    if type(tracks) <> "roArray" or tracks.Count() <> 1 then return invalid
    track = tracks[0]
    codec = LCase(TaskString(version,"videoCodec"))
    if codec <> "h264" and codec <> "hevc" then return invalid
    if LCase(TaskString(track,"codec")) <> codec then return invalid
    container = LCase(TaskString(version,"container"))
    if container = "m4v" or container = "mov" then container = "mp4"
    if container <> "mp4" and container <> "mkv" then return invalid
    width = SpField(track,"width"):height = SpField(track,"height")
    if not SpNumber(width,7680,true) or not SpNumber(height,4320,true) then return invalid
    if width = 0 or height = 0 or SpField(track,"interlaced") <> false then return invalid
    if codec = "h264" and (width > 1920 or height > 1080) then return invalid
    if not TaskSiloFrameRateKnown(TaskString(track,"frame_rate")) then return invalid
    mode = LCase(TaskSiloVideoMode(device)):maximumWidth = 0:maximumHeight = 0
    if Left(mode,5) = "2160p" then maximumWidth = 3840:maximumHeight = 2160
    if Left(mode,5) = "1080p" or Left(mode,5) = "1080i" then maximumWidth = 1920:maximumHeight = 1080
    if Left(mode,4) = "720p" then maximumWidth = 1280:maximumHeight = 720
    if maximumWidth = 0 or width > maximumWidth or height > maximumHeight then return invalid
    profile = LCase(TaskString(track,"profile"))
    if profile = "main10" then profile = "main 10"
    if codec = "hevc"
        if profile <> "main" and profile <> "main 10" then return invalid
        levels = {"90":"3.0","93":"3.1","120":"4.0","123":"4.1","150":"5.0","153":"5.1","156":"5.2","180":"6.0","183":"6.1","186":"6.2"}
        queryCodec = "hevc"
    else
        if profile <> "main" and profile <> "high" and profile <> "baseline" then return invalid
        levels = {"30":"3.0","31":"3.1","32":"3.2","40":"4.0","41":"4.1","42":"4.2","50":"5.0","51":"5.1","52":"5.2"}
        queryCodec = "mpeg4 avc"
    end if
    level = SpField(track,"level")
    if not SpNumber(level,1000,true) then return invalid
    key = Int(level).ToStr()
    if not levels.DoesExist(key) then return invalid
    depth = SpField(track,"bit_depth")
    if depth <> 8 and depth <> 10 then return invalid
    if depth = 10 and (codec <> "hevc" or profile <> "main 10") then return invalid
    rangeType = LCase(TaskString(track,"video_range_type"))
    range = LCase(TaskString(track,"video_range"))
    dv = Instr(1,rangeType,"dovi") > 0 or Instr(1,range,"dolby") > 0 or Instr(1,range,"dovi") > 0
    enhancement = LCase(TaskString(track,"dv_enhancement_layer"))
    dv = dv or TaskString(track,"dolby_vision") <> "" or (enhancement <> "" and enhancement <> "none")
    dv = dv or SpField(track,"dv_config_present") = true or SpField(track,"dv_el_present") = true or SpField(track,"dv_rpu_present") = true or TaskValue(track,"dv_profile",0) <> 0
    features = SiloNativeDeliveryFeatures(context)
    dvScore = invalid
    if dv
        if codec <> "hevc" or profile <> "main 10" then return invalid
        p8HDR10Intent = false
        if SiloObject(requestIntent) and SpField(requestIntent,"qualityPreference") = "original"
            cap = SpField(requestIntent,"bandwidthCapKbps",0)
            if SpNumber(cap,2147483646,true)
                p8HDR10Intent = cap = 0
                sourceBitrate = SpField(version,"bitrateKbps")
                if cap > 0 and SpNumber(sourceBitrate,2147483646,true)
                    p8HDR10Intent = sourceBitrate > 0 and sourceBitrate <= cap
                end if
            end if
        end if
        dvScore = TaskSiloDVVersionScore(track,SpField(capabilities,"hdr_details"),features,p8HDR10Intent)
        if dvScore = invalid then return invalid
    end if
    hdr = SpField(version,"hdr")
    if not SpBool(hdr) then return invalid
    hdrScore = 0
    transfer = LCase(TaskString(track,"color_transfer"))
    if dv and not hdr then return invalid
    if not hdr
        if transfer = "smpte2084" or transfer = "arib-std-b67" or SpField(track,"hdr10_plus") = true then return invalid
        if rangeType <> "" and rangeType <> "sdr" then return invalid
        if range <> "" and range <> "sdr" then return invalid
    end if
    if dv
        hdrScore = dvScore
    else if hdr
        details = SpField(capabilities,"hdr_details")
        if type(details) <> "roAssociativeArray" or codec <> "hevc" or profile <> "main 10" then return invalid
        if SpField(track,"hdr10_plus") = true
            if SpField(details,"hdr10_plus") <> true then return invalid
            hdrScore = 2
        else if rangeType = "hlg" or range = "hlg" or transfer = "arib-std-b67"
            if SpField(details,"hlg") <> true then return invalid
            hdrScore = 1
        else if rangeType = "hdr10" or range = "hdr10" or transfer = "smpte2084"
            if SpField(details,"hdr10") <> true then return invalid
            hdrScore = 1
        else
            return invalid
        end if
    end if
    audio = LCase(TaskString(version,"audioCodec"))
    audioProven = false
    if SiloContains(["aac","ac3","eac3","mp3","flac","opus"],audio)
        decoded = TaskDecoderResult(TaskSiloCanDecodeAudio(device,{codec:audio,container:container,passthru:0}))
        passed = TaskDecoderResult(TaskSiloCanDecodeAudio(device,{codec:audio,container:container,passthru:1}))
        audioProven = decoded or passed
    end if
    ' A negotiated native copy recipe may convert an unsupported source lane.
    ' The server still validates its actual executor and selected track.
    if not audioProven and (SiloContains(features,"hls_copy_mpegts_v1") or SiloContains(features,"native_hls_mpegts_v1") or SiloContains(features,"native_hls_separate_audio_v1")) and SiloContains(["truehd","dts","dca","aac","ac3","eac3","flac","opus"],audio)
        hls = SpField(SpField(context,"deliveries"),"hls")
        audioProven = SiloContains(SiloList(SpField(hls,"audio_decode_codecs")),"aac")
    end if
    if not audioProven then return invalid
    if not TaskSiloSourceVideoSupported(device,{codec:queryCodec,container:container,profile:profile,level:levels[key]}) then return invalid
    if SiloContains(features,"hls_copy_mpegts_v1") and not SiloContains(features,"native_hls_separate_audio_v1")
        if not TaskSiloSourceVideoSupported(device,{codec:queryCodec,container:"ts",profile:profile,level:levels[key]}) then return invalid
    end if
    bitrate = SpField(version,"bitrateKbps")
    if not SpNumber(bitrate,2147483646) then return invalid
    return {pixels:width*height,hdrScore:hdrScore,bitrate:bitrate}
end function

' Check the actual channel layout. A codec-only answer can overstate surround
' support, particularly for lossless formats reported through MAT.
function TaskSiloAudioTrackPlayable(track as Object, device as Object) as Boolean
    codec = LCase(TaskString(track,"codec")):channels = SpField(track,"channels")
    if not SiloContains(["aac","ac3","eac3"],codec) or not SpNumber(channels,8,true) then return false
    if channels = 0 then return false
    for each mode in [0,1]
        if TaskDecoderResult(TaskSiloCanDecodeAudio(device,{codec:codec,container:"ts",chcnt:Int(channels),passthru:mode})) then return true
    end for
    return false
end function

' A terminal decision has no selected lane. Retry a native alternate only
' when the entire file has one known language and no alternate program.
function TaskSiloUnambiguousAudio(version as Object, device as Object, context as Object) as Dynamic
    tracks = SiloList(version.audioTracks)
    if tracks.Count() < 2 or tracks.Count() > 32 then return invalid
    language = LCase(TaskString(tracks[0],"language"))
    if language = "" or language = "und" then return invalid
    current = tracks[0]
    for each track in tracks
        if LCase(TaskString(track,"language")) <> language or track.hearingImpaired = true then return invalid
        title = LCase(TaskString(track,"title"))
        if Instr(1,title,"commentary") > 0 or Instr(1,title,"description") > 0 or Instr(1,title,"descriptive") > 0 then return invalid
        if track.isDefault = true then current = track
    end for
    return TaskSiloCompatibleAudio(version,{index:current.index},device,context)
end function

' Retain the server's language/program selection. Only replace an unsupported
' lane with a freshly proven equivalent; explicit user selectors bypass this.
function TaskSiloCompatibleAudio(version as Object, selected as Dynamic, device as Object, context as Object) as Dynamic
    if SiloNativeDeliveryFeatures(context).Count() = 0 or not SiloObject(selected) then return invalid
    tracks = SiloList(version.audioTracks):current = invalid
    for each track in tracks
        if track.index = selected.index then current = track
    end for
    if current = invalid then return invalid
    if TaskSiloAudioTrackPlayable(current,device) then return invalid
    language = LCase(TaskString(current,"language"))
    if language = "" or language = "und" then return invalid
    best = invalid:bestScore = -1
    for each track in tracks
        if LCase(TaskString(track,"language")) = language and (track.hearingImpaired = true) = (current.hearingImpaired = true)
            title = LCase(TaskString(track,"title"))
            commentary = Instr(1,title,"commentary") > 0 or Instr(1,title,"description") > 0 or Instr(1,title,"descriptive") > 0
            originalTitle = LCase(TaskString(current,"title"))
            originalCommentary = Instr(1,originalTitle,"commentary") > 0 or Instr(1,originalTitle,"description") > 0 or Instr(1,originalTitle,"descriptive") > 0
            if commentary = originalCommentary and TaskSiloAudioTrackPlayable(track,device)
                score = track.channels * 10
                codec = LCase(TaskString(track,"codec"))
                if codec = "eac3" then score = score + 2
                if codec = "ac3" then score = score + 1
                if score > bestScore then best = track:bestScore = score
            end if
        end if
    end for
    return best
end function

' A profile-7 file is a server conversion candidate only with a proven HDR10
' base. Original profile 7 is never advertised as a native decoder capability.
function TaskSiloDVVersionScore(track as Object, details as Dynamic, features as Object, p8HDR10Intent = false as Boolean) as Dynamic
    if not SiloObject(details) then return invalid
    if not SiloContains(features,"hls_copy_mpegts_v1") and not SiloContains(features,"native_hls_separate_audio_v1") then return invalid
    if track.dv_config_present <> true or track.dv_bl_present <> true or track.dv_rpu_present <> true or track.dv_bl_compat_id_present <> true then return invalid
    sourceProfile = track.dv_profile:targetProfile = sourceProfile
    if not SpNumber(track.dv_level,13,true) or track.dv_level = 0 then return invalid
    if sourceProfile = 7
        if track.dv_bl_compat_id <> 6 then return invalid
        targetProfile = 8
        if not SiloContains(features,"server_dv7_to_dv81_v1")
            if details.hdr10 = true then return 1
            return invalid
        end if
    else if sourceProfile = 5
        if track.dv_el_present <> false or track.dv_bl_compat_id <> 0 then return invalid
    else if sourceProfile = 8
        if track.dv_el_present <> false or track.dv_bl_compat_id <> 1 then return invalid
    else
        return invalid
    end if
    for each bound in SiloList(details.dolby_vision_profile_levels)
        if bound.profile = targetProfile and SpNumber(bound.max_level,13,true)
            if track.dv_level <= bound.max_level then return 3
        end if
    end for
    if sourceProfile = 7 and details.hdr10 = true then return 1
    ' A narrow HDR10-base planning attempt, never a new native DV bound.
    if p8HDR10Intent and sourceProfile = 8 and details.hdr10 = true and SoVideoGate(track) = ""
        if track.width = 3840
            if SoFrameRate(track.frame_rate) <= 24 then return 1
        end if
    end if
    return invalid
end function

 ' Bounded tester routing; caller parameters cannot alter release gates.
function SiloCompatPreparationEnabled() as Boolean
    return true
end function

 ' P7 audio selection and native-audio mutation await separate qualification.
function SiloP7CompatPreparationEnabled() as Boolean
    return false
end function

 ' AAC conversion remains isolated even when copied P7 audio is opted in.
function SiloP7AACPreparationEnabled() as Boolean
    return false
end function

 ' QA output selection is local to this producer; caller fields cannot enable it.
function SiloP8HDR10CompatPreparationEnabled() as Boolean
    return false
end function

 ' Automatic HDR10 fallback is independent of the QA output preference.
function SiloP8HDR10AutomaticPreparationEnabled() as Boolean
    return true
end function

' Only the gated producer may select an experimental proof kind. Caller
' parameters are intentionally absent: ordinary legacy proof always wins first.
function TaskSiloCompatProof(detail as Object, owner as Object, intent as Object, device as Object, audio as Object, version as Object) as Dynamic
    if not SiloCompatPreparationEnabled() then return invalid
    video = invalid:tracks = SpField(version,"videoTracks")
    if SiloArray(tracks) then if tracks.Count() = 1 then video = tracks[0]
    if SiloP8HDR10CompatPreparationEnabled()
        kind = "experimental_query_p8_hdr10_fmp4_v1"
        return SiloCompatCandidate(detail,owner,intent,SiloCompatSnapshotForKind(device,audio,kind,video),kind)
    end if
    proof = SiloCompatCandidate(detail,owner,intent,SiloCompatSnapshotForKind(device,audio,invalid,video))
    if proof <> invalid then return proof
    kind = "experimental_query_p8_ts_v1"
    proof = SiloCompatCandidate(detail,owner,intent,SiloCompatSnapshotForKind(device,audio,kind,video),kind)
    if proof <> invalid then return proof
    if not SiloP8HDR10AutomaticPreparationEnabled() then return invalid
    kind = "experimental_query_p8_hdr10_fmp4_v1"
    return SiloCompatP8HDR10AutomaticCandidate(detail,owner,intent,SiloCompatSnapshotForKind(device,audio,kind,video))
end function

 ' An explicit audio choice pins the real UI job without claiming an explicit
' version choice. Scene independently checks that original local provenance.
function TaskSiloP7NativeAudioProven(audio as Object, device as Object, context as Object) as Boolean
    ' Native split HLS has TS audio, unlike the proven compatibility MP4.
    ' Prefer only the admitted selected lane with exact source channel count.
    hls = SpField(SpField(context,"deliveries"),"hls")
    if SpField(hls,"enabled") <> true or SpField(hls,"supported_on_device") <> true then return false
    admitted = SiloContains(SiloList(SpField(hls,"audio_decode_codecs")),audio.codec) or SiloContains(SiloList(SpField(hls,"audio_passthrough_codecs")),audio.codec)
    ceiling = SpField(hls,"max_channels",8)
    if not admitted or not SpNumber(ceiling,8,true) then return false
    if ceiling < audio.channels then return false
    if SiloContains(SiloList(SpField(hls,"audio_decode_codecs")),audio.codec)
        if TaskDecoderResult(TaskSiloCanDecodeAudio(device,{codec:audio.codec,chcnt:audio.channels,container:"ts",passthru:0})) then return true
    end if
    if SiloContains(SiloList(SpField(hls,"audio_passthrough_codecs")),audio.codec)
        if TaskDecoderResult(TaskSiloCanDecodeAudio(device,{codec:audio.codec,chcnt:audio.channels,container:"ts",passthru:1})) then return true
    end if
    return false
end function

' AAC conversion requires explicit negative evidence for both native TS audio
' modes and a fresh instance qualification. It never derives trust from Version.
function TaskSiloP7AACNativeUnsupported(audio as Object, device as Object) as Boolean
    decode = SpField(TaskSiloCanDecodeAudio(device,{codec:audio.codec,chcnt:audio.channels,container:"ts",passthru:0}),"result")
    passthrough = SpField(TaskSiloCanDecodeAudio(device,{codec:audio.codec,chcnt:audio.channels,container:"ts",passthru:1}),"result")
    if not SpBool(decode) or not SpBool(passthrough) then return false
    return decode = false and passthrough = false
end function

function TaskSiloP7AACConversionContinuation(detail as Object, session as Object, params as Object, device as Object, capabilities as Object, context as Object, revision as Integer, ordinal as Integer, autoChoice = invalid as Dynamic) as Dynamic
    if not SiloCompatPreparationEnabled() or not SiloP7AACPreparationEnabled() or m.siloNativeStartIssued = true or m.siloCompatContinuationIssued = true then return invalid
    if params.speculativePrebuffer = true or params.experimentalOriginal = true or params.privateLegacyHdr10 = true then return invalid
    if params.qualityPreference <> "original" or params.subtitleMode <> "off" then return invalid
    job = m.top.job:scope = SpScope(job)
    if scope = invalid or SpField(job,"action") <> "playback_start" then return invalid
    if scope.sourceId <> session.sourceId or scope.profileId <> session.profileId or scope.profileId = "" then return invalid
    if not SpNumber(SpField(job,"requestId"),2147483646,true) or job.requestId = 0 then return invalid
    if SessionRevision("silo") <> revision then return invalid
    current = LoadSession("silo")
    for each name in ["sourceId","baseUrl","profileId","profileToken","accessToken"]
        if SpField(current,name) <> SpField(session,name) then return invalid
    end for
    target = TaskValue(params,"startPositionMs",0)
    file = SiloPlaybackFile(detail,scope.sourceId,params.itemId,params.fileId,target)
    if file = invalid or not SiloArray(SpField(file.version,"audioTracks")) then return invalid
    if not SpNumber(ordinal,file.version.audioTracks.Count()-1,true) then return invalid
    audio = file.version.audioTracks[ordinal]
    if not TaskSiloP7AACNativeUnsupported(audio,device) then return invalid
    owner = SpCopy(scope):owner["sessionRevision"] = revision
    qualification = SiloCompatP7AACQualification(owner,SpField(params,"instanceQualification"))
    if qualification = invalid then return invalid
    kind = "experimental_query_p7_hdr10_aac_fmp4_v1"
    intent = {itemId:params.itemId,fileId:file.versionId,audioTrackIndex:ordinal,audioTrackId:"file:"+file.versionId+":audio:"+Int(ordinal).ToStr(),startPositionMs:target,qualityPreference:"original",subtitleMode:"off",instanceQualification:qualification}
    if SpField(params,"autoVersion") = true
        if not SpFields(autoChoice,["mode","selection","file_id","audio_track_id","audio_track_index","preferred_ordinal","equivalence","basis","queries"],[]) then return invalid
        facts = SpField(file.version,"autoAudioFacts")
        checked = SiloAutoAudioAACConversion(facts,SpField(autoChoice,"queries"))
        if checked = invalid or FormatJson(checked) <> FormatJson(autoChoice) then return invalid
        if autoChoice.file_id <> file.versionId or autoChoice.audio_track_index <> ordinal or autoChoice.audio_track_id <> intent.audioTrackId then return invalid
        intent["autoVersion"] = true:intent["autoAudioSelection"] = SpCopy(autoChoice)
    else if SpField(params,"autoVersion") <> false or autoChoice <> invalid
        return invalid
    end if
    if SpField(params,"audioTrackIndex") <> invalid
        if params.audioTrackIndex <> ordinal or SpField(params,"audioTrackId") <> intent.audioTrackId then return invalid
    end if
    if params.DoesExist("bandwidthCapKbps") then intent["bandwidthCapKbps"] = params.bandwidthCapKbps
    hasBandwidthCap = false
    for each name in params
        if LCase(name) = "bandwidthcapkbps" then hasBandwidthCap = true
    end for
    video = invalid:videos = SpField(file.version,"videoTracks")
    if SiloArray(videos) then if videos.Count() = 1 then video = videos[0]
    proof = SiloCompatCandidate(detail,owner,intent,SiloCompatSnapshotForKind(device,audio,kind,video),kind,qualification)
    if proof = invalid then return invalid
    nativeView = SpCopy(file.version):nativeView.audioCodec = proof.audio.codec
    nativeProof = TaskSiloVersionProof(nativeView,device,capabilities,context,params)
    if nativeProof <> invalid and TaskSiloP7NativeAudioProven(audio,device,context) then return invalid
    if SessionRevision("silo") <> revision or m.top.cancelled = true then return invalid
    current = LoadSession("silo")
    for each name in ["sourceId","baseUrl","profileId","profileToken","accessToken"]
        if SpField(current,name) <> SpField(session,name) then return invalid
    end for
    attempt = TaskUniqueId()
    if not TaskPlaybackOpaqueId(attempt) then return invalid
    result = {schemaVersion:1,reason:"native_source_unproven",owner:owner,requestId:job.requestId,playbackAttemptId:attempt,itemId:params.itemId,fileId:file.versionId,requestedFileId:params.fileId,nativeSelectedFileId:file.versionId,audioTrackId:intent.audioTrackId,audioTrackIndex:ordinal,startPositionMs:target,startPaused:false,qualityPreference:"original",qualityExplicit:SpField(params,"qualityExplicit")=true,subtitleMode:"off",autoVersion:SpField(params,"autoVersion")=true,nativeClosure:{state:"not_allocated"},eligibilityKind:kind,instanceQualification:qualification}
    if hasBandwidthCap then result["bandwidthCapKbps"] = params.bandwidthCapKbps
    if SpField(params,"autoVersion") = true then result["autoAudioSelection"] = SpCopy(autoChoice)
    m.siloCompatContinuationIssued = true
    return result
end function

function TaskSiloP8AC3Continuation(detail as Object, inventory as Object, session as Object, params as Object, device as Object, revision as Integer) as Dynamic
    if SiloContains(SiloList(SpField(params,"compatExcludedFileIds")),params.fileId) then return invalid
    if not SiloCompatPreparationEnabled() or not TaskSiloExperimentalIntent(params) then return invalid
    if m.siloNativeStartIssued = true or m.siloCompatContinuationIssued = true or params.speculativePrebuffer = true then return invalid
    if params.privateLegacyHdr10 = true then return invalid
    present = {}
    for each name in params
        key = LCase(name)
        if present.DoesExist(key) then return invalid
        present[key] = true
    end for
    if not SpBool(SpField(params,"autoVersion")) or params.autoVersion <> false then return invalid
    if params.qualityPreference <> "original" or params.subtitleMode <> "off" then return invalid
    if present.DoesExist("qualityexplicit") then if not SpBool(SpField(params,"qualityExplicit")) then return invalid
    for each name in ["subtitleTrackId","subtitleTrackIndex","excludedVersionIds"]
        if present.DoesExist(LCase(name)) then return invalid
    end for
    if not SiloArray(SpField(detail,"versions")) or not SiloArray(SpField(inventory,"allowedFileIds")) then return invalid
    if inventory.allowedFileIds.Count() <> 1 then return invalid
    if inventory.fileId <> params.fileId or inventory.allowedFileIds[0] <> params.fileId then return invalid
    if m.top = invalid or m.top.cancelled = true then return invalid
    job = m.top.job:owner = SpScope(job)
    if owner = invalid or SpField(job,"action") <> "playback_start" then return invalid
    if owner.sourceId <> session.sourceId or owner.profileId <> session.profileId or owner.profileId = "" then return invalid
    if not SpNumber(SpField(job,"requestId"),2147483646,true) or job.requestId = 0 then return invalid
    if SessionRevision("silo") <> revision then return invalid
    current = LoadSession("silo")
    for each name in ["sourceId","baseUrl","profileId","profileToken","accessToken"]
        if SpField(current,name) <> SpField(session,name) then return invalid
    end for
    target = TaskValue(params,"startPositionMs",0)
    file = SiloPlaybackFile(detail,owner.sourceId,params.itemId,params.fileId,target)
    if file = invalid then return invalid
    ordinal = SpField(params,"audioTrackIndex")
    if not SiloArray(SpField(file.version,"audioTracks")) then return invalid
    if not SpNumber(ordinal,file.version.audioTracks.Count()-1,true) then return invalid
    if SpField(params,"audioTrackId") <> "file:"+file.versionId+":audio:"+Int(ordinal).ToStr() then return invalid
    freshAudio = TaskSiloFreshAudioIntent(params.detail,detail,owner.sourceId,params.itemId,file.versionId,params)
    if freshAudio = invalid then return invalid
    if freshAudio.preserve = true or freshAudio.index <> ordinal or freshAudio.id <> params.audioTrackId then return invalid
    owner["sessionRevision"] = revision
    kind = "experimental_query_p8_hdr10_ac3_fmp4_v1"
    proof = TaskSiloP8AC3Proof(detail,owner,params,device)
    if proof = invalid then return invalid
    if SessionRevision("silo") <> revision or m.top.cancelled = true then return invalid
    current = LoadSession("silo")
    for each name in ["sourceId","baseUrl","profileId","profileToken","accessToken"]
        if SpField(current,name) <> SpField(session,name) then return invalid
    end for
    attempt = TaskUniqueId()
    if not TaskPlaybackOpaqueId(attempt) then return invalid
    result = {schemaVersion:1,reason:"native_source_unproven",owner:owner,requestId:job.requestId,playbackAttemptId:attempt,itemId:params.itemId,fileId:file.versionId,requestedFileId:params.fileId,nativeSelectedFileId:file.versionId,audioTrackId:params.audioTrackId,audioTrackIndex:ordinal,startPositionMs:target,startPaused:false,qualityPreference:"original",qualityExplicit:params.qualityExplicit=true,subtitleMode:"off",autoVersion:false,nativeClosure:{state:"not_allocated"},eligibilityKind:kind}
    if present.DoesExist("bandwidthcapkbps") then result["bandwidthCapKbps"] = params.bandwidthCapKbps
    m.siloCompatContinuationIssued = true
    return result
end function

function TaskSiloP7CompatSelectionContinuation(detail as Object, inventory as Object, session as Object, params as Object, device as Object, capabilities as Object, context as Object, revision as Integer) as Dynamic
    if SiloContains(SiloList(SpField(params,"compatExcludedFileIds")),params.fileId) then return invalid
    if not SiloCompatPreparationEnabled() or not SiloP7CompatPreparationEnabled() then return invalid
    if m.siloNativeStartIssued = true or m.siloCompatContinuationIssued = true or params.speculativePrebuffer = true then return invalid
    if params.experimentalOriginal = true or params.privateLegacyHdr10 = true then return invalid
    present = {}
    for each name in params
        key = LCase(name)
        if present.DoesExist(key) then return invalid
        present[key] = true
    end for
    if not SpBool(SpField(params,"autoVersion")) or params.autoVersion <> false then return invalid
    if params.qualityPreference <> "original" or params.subtitleMode <> "off" then return invalid
    if present.DoesExist("qualityexplicit") then if not SpBool(SpField(params,"qualityExplicit")) then return invalid
    for each name in ["subtitleTrackId","subtitleTrackIndex","excludedVersionIds"]
        if present.DoesExist(LCase(name)) then return invalid
    end for
    if not SiloArray(SpField(detail,"versions")) or not SiloArray(SpField(inventory,"allowedFileIds")) then return invalid
    if detail.versions.Count() <> 1 or inventory.allowedFileIds.Count() <> 1 then return invalid
    if inventory.fileId <> params.fileId or inventory.allowedFileIds[0] <> params.fileId then return invalid
    if m.top = invalid or m.top.cancelled = true then return invalid
    job = m.top.job:owner = SpScope(job)
    if owner = invalid or SpField(job,"action") <> "playback_start" then return invalid
    if owner.sourceId <> session.sourceId or owner.profileId <> session.profileId or owner.profileId = "" then return invalid
    if not SpNumber(SpField(job,"requestId"),2147483646,true) or job.requestId = 0 then return invalid
    if SessionRevision("silo") <> revision then return invalid
    current = LoadSession("silo")
    for each name in ["sourceId","baseUrl","profileId","profileToken","accessToken"]
        if SpField(current,name) <> SpField(session,name) then return invalid
    end for
    target = TaskValue(params,"startPositionMs",0)
    file = SiloPlaybackFile(detail,owner.sourceId,params.itemId,params.fileId,target)
    if file = invalid then return invalid
    ordinal = SpField(params,"audioTrackIndex")
    if not SiloArray(SpField(file.version,"audioTracks")) then return invalid
    if not SpNumber(ordinal,file.version.audioTracks.Count()-1,true) then return invalid
    if SpField(params,"audioTrackId") <> "file:"+file.versionId+":audio:"+Int(ordinal).ToStr() then return invalid
    freshAudio = TaskSiloFreshAudioIntent(params.detail,detail,owner.sourceId,params.itemId,file.versionId,params)
    if freshAudio = invalid then return invalid
    if freshAudio.preserve = true or freshAudio.index <> ordinal or freshAudio.id <> params.audioTrackId then return invalid
    owner["sessionRevision"] = revision
    intent = {itemId:params.itemId,fileId:file.versionId,audioTrackIndex:ordinal,audioTrackId:params.audioTrackId,startPositionMs:target,qualityPreference:"original",subtitleMode:"off"}
    if present.DoesExist("bandwidthcapkbps") then intent["bandwidthCapKbps"] = params.bandwidthCapKbps
    kind = "experimental_query_p7_hdr10_fmp4_v1"
    video = invalid:videos = SpField(file.version,"videoTracks")
    if SiloArray(videos) then if videos.Count() = 1 then video = videos[0]
    audio = file.version.audioTracks[ordinal]
    proof = SiloCompatCandidate(detail,owner,intent,SiloCompatSnapshotForKind(device,audio,kind,video),kind)
    if proof = invalid then return TaskSiloP7AACConversionContinuation(detail,session,params,device,capabilities,context,revision,ordinal)
    ' Native priority follows the chosen lane, never the default TrueHD summary.
    nativeView = SpCopy(file.version):nativeView.audioCodec = proof.audio.codec
    if TaskSiloVersionProof(nativeView,device,capabilities,context,params) <> invalid
        if TaskSiloP7NativeAudioProven(audio,device,context) then return invalid
    end if
    if SessionRevision("silo") <> revision or m.top.cancelled = true then return invalid
    current = LoadSession("silo")
    for each name in ["sourceId","baseUrl","profileId","profileToken","accessToken"]
        if SpField(current,name) <> SpField(session,name) then return invalid
    end for
    attempt = TaskUniqueId()
    if not TaskPlaybackOpaqueId(attempt) then return invalid
    result = {schemaVersion:1,reason:"native_source_unproven",owner:owner,requestId:job.requestId,playbackAttemptId:attempt,itemId:params.itemId,fileId:file.versionId,requestedFileId:params.fileId,nativeSelectedFileId:file.versionId,audioTrackId:params.audioTrackId,audioTrackIndex:ordinal,startPositionMs:target,startPaused:false,qualityPreference:"original",qualityExplicit:params.qualityExplicit=true,subtitleMode:"off",autoVersion:false,nativeClosure:{state:"not_allocated"},eligibilityKind:kind}
    if present.DoesExist("bandwidthcapkbps") then result["bandwidthCapKbps"] = params.bandwidthCapKbps
    m.siloCompatContinuationIssued = true
    return result
end function

' Request-local Auto selection retains the real no-choice UI intent.
function TaskSiloP7AutoSelection(detail as Object, inventory as Object, session as Object, params as Object, device as Object, capabilities as Object, context as Object, revision as Integer) as Dynamic
    if SiloContains(SiloList(SpField(params,"compatExcludedFileIds")),params.fileId) then return invalid
    if not SiloCompatPreparationEnabled() or not SiloP7CompatPreparationEnabled() then return invalid
    if m.siloNativeStartIssued = true or m.siloCompatContinuationIssued = true or params.speculativePrebuffer = true then return invalid
    if params.experimentalOriginal = true or params.privateLegacyHdr10 = true then return invalid
    present = {}
    for each name in params
        key = LCase(name)
        if present.DoesExist(key) then return invalid
        present[key] = true
    end for
    if not SpBool(SpField(params,"autoVersion")) or params.autoVersion <> true then return invalid
    if params.qualityPreference <> "original" or params.subtitleMode <> "off" then return invalid
    if present.DoesExist("qualityexplicit") then if not SpBool(SpField(params,"qualityExplicit")) then return invalid
    for each name in ["audioTrackId","audioTrackIndex","subtitleTrackId","subtitleTrackIndex","excludedVersionIds"]
        if present.DoesExist(LCase(name)) then return invalid
    end for
    if not SiloArray(SpField(detail,"versions")) or not SiloArray(SpField(inventory,"allowedFileIds")) then return invalid
    if detail.versions.Count() <> 1 or inventory.allowedFileIds.Count() <> 1 then return invalid
    if inventory.fileId <> params.fileId or inventory.allowedFileIds[0] <> params.fileId then return invalid
    if m.top = invalid or m.top.cancelled = true then return invalid
    job = m.top.job:owner = SpScope(job)
    if owner = invalid or SpField(job,"action") <> "playback_start" then return invalid
    if owner.sourceId <> session.sourceId or owner.profileId <> session.profileId or owner.profileId = "" then return invalid
    if not SpNumber(SpField(job,"requestId"),2147483646,true) or job.requestId = 0 then return invalid
    if SessionRevision("silo") <> revision then return invalid
    current = LoadSession("silo")
    for each name in ["sourceId","baseUrl","profileId","profileToken","accessToken"]
        if SpField(current,name) <> SpField(session,name) then return invalid
    end for
    target = TaskValue(params,"startPositionMs",0)
    file = SiloPlaybackFile(detail,owner.sourceId,params.itemId,params.fileId,target)
    if file = invalid then return invalid
    ' Read only fresh source-bound facts; the caller cannot nominate Auto facts.
    facts = SpField(file.version,"autoAudioFacts")
    before = SiloPlaybackFile(params.detail,owner.sourceId,params.itemId,file.versionId,target)
    if before = invalid or not SiloObject(facts) then return invalid
    if FormatJson(SpField(before.version,"autoAudioFacts")) <> FormatJson(facts) then return invalid
    videos = SpField(file.version,"videoTracks")
    if not SiloArray(videos) then return invalid
    if videos.Count() <> 1 then return invalid
    if SpField(videos[0],"dv_profile") <> 7 then return invalid
    tracks = SpField(facts,"tracks")
    if not SiloArray(tracks) then return invalid
    queries = []
    for each track in tracks
        query = {codec:track.codec,chcnt:track.channels,container:"mp4",passthru:0}
        decoded = SpField(TaskSiloCanDecodeAudio(device,query),"result")
        if not SpBool(decoded) then decoded = invalid
        query.passthru = 1
        passed = SpField(TaskSiloCanDecodeAudio(device,query),"result")
        if not SpBool(passed) then passed = invalid
        queries.Push({source_ordinal:track.source_ordinal,codec:track.codec,channels:track.channels,container:"mp4",decode:decoded,passthrough:passed})
    end for
    choice = SiloAutoAudioChoose(facts,queries)
    if choice = invalid
        conversion = SiloAutoAudioAACConversion(facts,queries)
        if conversion = invalid then return invalid
        continuation = TaskSiloP7AACConversionContinuation(detail,session,params,device,capabilities,context,revision,conversion.audio_track_index,conversion)
        if continuation = invalid then return invalid
        return {selection:conversion,continuation:continuation}
    end if
    ordinal = choice.audio_track_index
    audioId = choice.audio_track_id
    owner["sessionRevision"] = revision
    intent = {itemId:params.itemId,fileId:file.versionId,audioTrackIndex:ordinal,audioTrackId:audioId,startPositionMs:target,qualityPreference:"original",subtitleMode:"off"}
    if present.DoesExist("bandwidthcapkbps") then intent["bandwidthCapKbps"] = params.bandwidthCapKbps
    kind = "experimental_query_p7_hdr10_fmp4_v1"
    video = invalid:videos = SpField(file.version,"videoTracks")
    if SiloArray(videos) then if videos.Count() = 1 then video = videos[0]
    audio = file.version.audioTracks[ordinal]
    proof = SiloCompatCandidate(detail,owner,intent,SiloCompatSnapshotForKind(device,audio,kind,video),kind)
    if proof = invalid then return invalid
    ' Native priority follows the chosen lane, never the default TrueHD summary.
    nativeView = SpCopy(file.version):nativeView.audioCodec = proof.audio.codec
    nativeProof = TaskSiloVersionProof(nativeView,device,capabilities,context,params)
    if nativeProof <> invalid
        if not TaskSiloP7NativeAudioProven(audio,device,context) then nativeProof = invalid
    end if
    if SessionRevision("silo") <> revision or m.top.cancelled = true then return invalid
    current = LoadSession("silo")
    for each name in ["sourceId","baseUrl","profileId","profileToken","accessToken"]
        if SpField(current,name) <> SpField(session,name) then return invalid
    end for
    if nativeProof <> invalid then return {selection:choice}
    attempt = TaskUniqueId()
    if not TaskPlaybackOpaqueId(attempt) then return invalid
    result = {schemaVersion:1,reason:"native_source_unproven",owner:owner,requestId:job.requestId,playbackAttemptId:attempt,itemId:params.itemId,fileId:file.versionId,requestedFileId:params.fileId,nativeSelectedFileId:file.versionId,audioTrackId:audioId,audioTrackIndex:ordinal,startPositionMs:target,startPaused:false,qualityPreference:"original",qualityExplicit:params.qualityExplicit=true,subtitleMode:"off",autoVersion:true,nativeClosure:{state:"not_allocated"},eligibilityKind:kind}
    if present.DoesExist("bandwidthcapkbps") then result["bandwidthCapKbps"] = params.bandwidthCapKbps
    m.siloCompatContinuationIssued = true
    result["autoAudioSelection"] = choice
    return {selection:choice,continuation:result}
end function

' Before the first native allocation only. The ordinary native comparator
' remains authoritative for equal/higher-resolution proven native routes.
function TaskSiloCompatSelectionContinuation(detail as Object, inventory as Object, native as Object, session as Object, params as Object, device as Object, capabilities as Object, context as Object, revision as Integer, wire = invalid as Dynamic, decoderEvidence = invalid as Dynamic) as Dynamic
    if m.siloNativeStartIssued = true or params.speculativePrebuffer = true or params.experimentalOriginal = true then return invalid
    manual = SpBool(SpField(params,"autoVersion")) and SpField(params,"autoVersion") = false
    explicitAudio = invalid
    if manual
        if inventory.allowAlternateVersions <> false or inventory.fileId <> params.fileId or native.fileId <> params.fileId then return invalid
        if not SiloArray(inventory.allowedFileIds) then return invalid
        if inventory.allowedFileIds.Count() <> 1 or inventory.allowedFileIds[0] <> params.fileId then return invalid
        if params.DoesExist("audioTrackId") or params.DoesExist("audioTrackIndex")
            explicitAudio = TaskSiloFreshAudioIntent(detail,detail,session.sourceId,params.itemId,params.fileId,params)
            if explicitAudio = invalid then return invalid
            if explicitAudio.preserve = true then return invalid
        end if
        for each name in ["subtitleTrackId","subtitleTrackIndex"]
            if params.DoesExist(name) then return invalid
        end for
    else if inventory.allowAlternateVersions <> true
        return invalid
    end if
    if m.top = invalid then return invalid
    job = m.top.job
    scope = SpScope(job)
    if scope = invalid or SpField(job,"action") <> "playback_start" then return invalid
    if not SpNumber(job.requestId,2147483646,true) or job.requestId = 0 then return invalid
    if scope.sourceId <> session.sourceId or scope.profileId <> session.profileId or scope.profileId = "" then return invalid
    if params.qualityPreference <> "original" or (params.subtitleMode <> "off" and params.subtitleMode <> "on") then return invalid
    if params.DoesExist("qualityExplicit") and not SpBool(params.qualityExplicit) then return invalid
    if SessionRevision("silo") <> revision then return invalid
    current = LoadSession("silo")
    for each key in ["sourceId","baseUrl","profileId","profileToken","accessToken"]
        if SpField(current,key) <> SpField(session,key) then return invalid
    end for
    owner = SpCopy(scope):owner["sessionRevision"] = revision
    target = TaskValue(params,"startPositionMs",0)
    nativeFile = SiloPlaybackFile(detail,scope.sourceId,params.itemId,native.fileId,target)
    if nativeFile = invalid then return invalid
    nativeView = SpCopy(nativeFile.version)
    if explicitAudio <> invalid then nativeView.audioCodec = nativeFile.version.audioTracks[explicitAudio.index].codec
    nativeProof = TaskSiloVersionProof(nativeView,device,capabilities,context,params)
    if explicitAudio <> invalid and nativeProof <> invalid
        if not TaskSiloP7NativeAudioProven(nativeFile.version.audioTracks[explicitAudio.index],device,context) then nativeProof = invalid
    end if
    reason = "native_selection_lower_resolution":nativePixels = 0
    if nativeProof = invalid
        ' Only one fresh, correlated source may use the no-native-proof branch.
        if m.siloCompatContinuationIssued = true then return invalid
        if not manual and params.autoVersion <> true then return invalid
        if not SiloArray(detail.versions) or not SiloArray(inventory.allowedFileIds) then return invalid
        if not manual and detail.versions.Count() <> 1 then return invalid
        if inventory.allowedFileIds.Count() <> 1 then return invalid
        if inventory.allowedFileIds[0] <> native.fileId or inventory.fileId <> native.fileId or params.fileId <> native.fileId then return invalid
        for each name in ["audioTrackId","audioTrackIndex","subtitleTrackId","subtitleTrackIndex"]
            if params.DoesExist(name) and explicitAudio = invalid then return invalid
        end for
        ' A source-bound level5.0 HDR10 projection is still proven native.
        projection = TaskSiloLevel50HDR10(wire,detail,scope.sourceId,params.itemId,native.fileId,target,params,device,capabilities,context,decoderEvidence)
        if projection <> invalid then return invalid
        reason = "native_source_unproven"
    else
        if manual then return invalid
        nativePixels = nativeProof.pixels
    end if
    ordered = [inventory.fileId]
    for each id in inventory.allowedFileIds
        if id <> inventory.fileId then ordered.Push(id)
    end for
    best = invalid:bestPixels = 0
    for each id in ordered
        file = invalid
        if not SiloContains(SiloList(SpField(params,"compatExcludedFileIds")),id) then file = SiloPlaybackFile(detail,scope.sourceId,params.itemId,id,target)
        if file <> invalid
            tracks = file.version.audioTracks:ordinal = invalid
            for index = 0 to tracks.Count()-1
                if tracks[index].isDefault = true
                    if ordinal <> invalid then ordinal = -1:exit for
                    ordinal = index
                end if
            end for
            if explicitAudio <> invalid then ordinal = explicitAudio.index
            if SpNumber(ordinal,tracks.Count()-1,true)
                intent = {itemId:params.itemId,fileId:id,audioTrackIndex:ordinal,audioTrackId:"file:"+id+":audio:"+ordinal.ToStr(),qualityPreference:"original",subtitleMode:"off",startPositionMs:target}
                if params.DoesExist("bandwidthCapKbps") then intent["bandwidthCapKbps"] = params.bandwidthCapKbps
                proof = TaskSiloCompatProof(detail,owner,intent,device,tracks[ordinal],file.version)
                if (manual or params.subtitleMode = "on") and SpField(proof,"eligibilityKind") <> "experimental_query_p8_ts_v1" then proof = invalid
                if proof <> invalid
                    pixels = proof.video.width*proof.video.height
                    if pixels > nativePixels and pixels > bestPixels then best = proof:bestPixels = pixels
                end if
            end if
        end if
    end for
    if best = invalid or SessionRevision("silo") <> revision or m.top.cancelled = true then return invalid
    current = LoadSession("silo")
    for each key in ["sourceId","baseUrl","profileId","profileToken","accessToken"]
        if SpField(current,key) <> SpField(session,key) then return invalid
    end for
    attempt = TaskUniqueId()
    if not TaskPlaybackOpaqueId(attempt) then return invalid
    result = {schemaVersion:1,reason:reason,owner:owner,requestId:job.requestId,playbackAttemptId:attempt,itemId:params.itemId,fileId:best.fileId,requestedFileId:params.fileId,nativeSelectedFileId:native.fileId,audioTrackId:"file:"+best.fileId+":audio:"+best.audioOrdinal.ToStr(),audioTrackIndex:best.audioOrdinal,startPositionMs:target,startPaused:false,qualityPreference:"original",qualityExplicit:params.qualityExplicit=true,subtitleMode:params.subtitleMode,autoVersion:true,nativeClosure:{state:"not_allocated"}}
    if manual
        result["autoVersion"] = false:result["manualVersionSelection"] = {requestedFileId:params.fileId}
        if explicitAudio <> invalid
            selectedAudio = SpCopy(explicitAudio):selectedAudio["track"] = SpCopy(nativeFile.version.audioTracks[explicitAudio.index])
            result.manualVersionSelection["explicitAudioSelection"] = selectedAudio
        end if
        m.siloCompatContinuationIssued = true
    end if
    if params.DoesExist("bandwidthCapKbps") then result["bandwidthCapKbps"] = params.bandwidthCapKbps
    if params.DoesExist("excludedVersionIds") then result["excludedVersionIds"] = SpCopy(params.excludedVersionIds)
    if best.DoesExist("eligibilityKind") then result["eligibilityKind"] = best.eligibilityKind
    return result
end function

 ' Eligibility is fresh source/intent only. It cannot authorize closure.
function TaskSiloCompatRefusalSource(detail as Object, session as Object, params as Object, device as Object, revision as Integer, fileId as String) as Dynamic
    if SiloContains(SiloList(SpField(params,"compatExcludedFileIds")),fileId) then return invalid
    if m.siloCompatContinuationIssued = true or params.speculativePrebuffer = true or params.experimentalOriginal = true then return invalid
    if params.autoVersion <> true or params.qualityPreference <> "original" or params.subtitleMode <> "off" then return invalid
    for each name in ["audioTrackId","audioTrackIndex","subtitleTrackId","subtitleTrackIndex"]
        if params.DoesExist(name) then return invalid
    end for
    job = m.top.job:owner = SpScope(job)
    if owner = invalid or job.action <> "playback_start" then return invalid
    if not SpNumber(job.requestId,2147483646,true) or job.requestId = 0 then return invalid
    if owner.sourceId <> session.sourceId or owner.profileId <> session.profileId then return invalid
    if fileId <> params.fileId or SpField(job.params,"fileId") <> fileId then return invalid
    if not SpNumber(params.startPositionMs,604800000) then return invalid
    owner["sessionRevision"] = revision
    file = SiloPlaybackFile(detail,owner.sourceId,params.itemId,fileId,params.startPositionMs)
    if file = invalid then return invalid
    ordinal = invalid:tracks = file.version.audioTracks
    for index = 0 to tracks.Count()-1
        if tracks[index].isDefault = true
            if ordinal <> invalid then return invalid
            ordinal = index
        end if
    end for
    if not SpNumber(ordinal,tracks.Count()-1,true) then return invalid
    intent = {itemId:params.itemId,fileId:fileId,audioTrackIndex:ordinal,audioTrackId:"file:"+fileId+":audio:"+ordinal.ToStr(),qualityPreference:"original",subtitleMode:"off",startPositionMs:params.startPositionMs}
    if params.DoesExist("bandwidthCapKbps") then intent["bandwidthCapKbps"] = params.bandwidthCapKbps
    proof = TaskSiloCompatProof(detail,owner,intent,device,tracks[ordinal],file.version)
    if proof = invalid then return invalid
    return {owner:owner,requestId:job.requestId,intent:intent,proof:proof}
end function

' This narrow unused native refusal class has a validated control envelope.
' The ACK record is Task-local output from the actual authenticated DELETE.
function TaskSiloCompatRefusalContinuation(source as Object, decision as Object, ack as Object, session as Object, params as Object, revision as Integer) as Dynamic
    if m.top.cancelled = true or ack.state <> "acknowledged" then return invalid
    owner = source.owner:intent = source.intent:proof = source.proof:fileId = intent.fileId
    if not SoScopeEqual(owner,ack.owner) or ack.owner.sessionRevision <> revision or ack.requestId <> source.requestId then return invalid
    if not TaskPlaybackOpaqueId(ack.playbackAttemptId) then return invalid
    for each name in ["sessionId","installationId","stopId"]
        if not TaskPlaybackOpaqueId(ack[name]) then return invalid
    end for
    if decision.protocol_version <> 3 or (decision.outcome <> "plan" and decision.outcome <> "playable") then return invalid
    raw = decision.playback_plan
    if not SiloObject(raw) or not TaskSiloDecisionIdentity(decision,fileId,ack.sessionId) then return invalid
    if raw.session_id <> ack.sessionId or raw.delivery <> "server_remux_hls" then return invalid
    if not SiloObject(raw.stream) or raw.stream.protocol <> "hls" or raw.stream.container <> "hls" then return invalid
    if not SiloObject(raw.effective_recipe) or not SiloArray(raw.transformations) then return invalid
    if raw.effective_recipe.video_codec <> "hevc" or raw.effective_recipe.audio_codec <> "eac3" or raw.effective_recipe.dynamic_range <> "hdr10" then return invalid
    if raw.transformations.Count() <> 2 then return invalid
    seen = {}
    for each transform in raw.transformations
        if not SpFields(transform,["name","executor","recipe_version","validated_claims"],[]) then return invalid
        if not SiloContains(["server_dv7_to_hdr10","hls_separate_audio"],transform.name) or transform.executor <> "server" then return invalid
        if seen.DoesExist(transform.name) or not SpText(transform.recipe_version,3) then return invalid
        if not CreateObject("roRegex","^[1-9][0-9]{0,2}$","").IsMatch(transform.recipe_version) then return invalid
        claims = transform.validated_claims
        if transform.name = "server_dv7_to_hdr10"
            if not SiloArray(claims) or claims.Count() <> 3 then return invalid
            expected = ["dolby_vision_metadata_removed","hdr10_base_layer_preserved","enhancement_layer_discarded"]
            for each claim in expected
                count = 0
                for each declared in claims
                    if declared = claim then count++
                end for
                if count <> 1 then return invalid
            end for
        else if claims <> invalid
            if not SiloArray(claims) or claims.Count() <> 0 then return invalid
        end if
        seen[transform.name] = true
    end for
    selected = TaskSiloDecisionTracks(raw.selected_tracks)
    if selected = invalid or not SiloSubtitleOffReceipt(raw) then return invalid
    if selected.audio.id <> intent.audioTrackId or selected.audio.index <> proof.audioOrdinal then return invalid
    if raw.source.video_codec <> "hevc" or raw.source.width <> proof.video.width or raw.source.height <> proof.video.height or raw.source.audio_codec <> proof.audio.codec then return invalid
    control = {provider:"silo",sourceId:owner.sourceId,itemId:params.itemId,versionId:fileId,sessionId:ack.sessionId,installationId:ack.installationId,planId:raw.plan_id,planAttemptKey:raw.plan_attempt_key}
    if TaskSiloPlanContext(control,decision,session,params,revision,ack.playbackAttemptId) = invalid then return invalid
    if not TaskSiloSetTarget(control,decision,params.startPositionMs) then return invalid
    if SessionRevision("silo") <> revision or m.top.cancelled = true then return invalid
    current = LoadSession("silo")
    for each name in ["sourceId","baseUrl","profileId","profileToken","accessToken"]
        if SpField(current,name) <> SpField(session,name) then return invalid
    end for
    closure = SpCopy(ack)
    result = {schemaVersion:1,reason:"native_routes_exhausted",owner:owner,requestId:source.requestId,playbackAttemptId:ack.playbackAttemptId,itemId:params.itemId,fileId:fileId,requestedFileId:params.fileId,nativeSelectedFileId:fileId,audioTrackId:intent.audioTrackId,audioTrackIndex:proof.audioOrdinal,startPositionMs:params.startPositionMs,startPaused:false,qualityPreference:"original",qualityExplicit:params.qualityExplicit=true,subtitleMode:"off",autoVersion:true,nativeClosure:closure}
    if params.DoesExist("bandwidthCapKbps") then result["bandwidthCapKbps"] = params.bandwidthCapKbps
    if params.DoesExist("excludedVersionIds") then result["excludedVersionIds"] = SpCopy(params.excludedVersionIds)
    if proof.DoesExist("eligibilityKind") then result["eligibilityKind"] = proof.eligibilityKind
    m.siloCompatContinuationIssued = true
    return result
end function

function TaskSiloBestNativeSelection(detail as Object, selection as Object, device as Object, capabilities as Object, targetMs as Double, context = invalid as Dynamic, requestIntent = invalid as Dynamic, wire = invalid as Dynamic, decoderEvidence = invalid as Dynamic) as Object
    if selection.allowAlternateVersions <> true then return selection
    bestId = selection.fileId:best = invalid
    cap = SpField(requestIntent,"bandwidthCapKbps",0)
    ' Visit the native default first so a score tie preserves server preference.
    ordered = [selection.fileId]
    for each id in selection.allowedFileIds
        if id <> selection.fileId then ordered.Push(id)
    end for
    for each id in ordered
        for each version in detail.versions
            if version.versionId = id
                proof = invalid
                if SiloPlaybackFile(detail,SpField(detail.item,"sourceId"),SpField(detail.item,"itemId"),id,targetMs) <> invalid
                    projection = TaskSiloLevel50HDR10(wire,detail,SpField(detail.item,"sourceId"),SpField(detail.item,"itemId"),id,targetMs,requestIntent,device,capabilities,context,decoderEvidence)
                    if projection <> invalid
                        proof = projection.score
                    else
                        proof = TaskSiloVersionProof(version,device,capabilities,context,requestIntent)
                    end if
                end if
                ' Keep the default anchor for server adaptation if no proven
                ' native candidate fits the requested bandwidth.
                if proof <> invalid and cap > 0
                    if proof.bitrate <= 0 or proof.bitrate > cap then proof = invalid
                end if
                if proof <> invalid
                    better = best = invalid
                    if best <> invalid
                        better = proof.pixels > best.pixels
                        if proof.pixels = best.pixels
                            better = proof.hdrScore > best.hdrScore
                            if proof.hdrScore = best.hdrScore then better = proof.bitrate > best.bitrate
                        end if
                    end if
                    if better then best = proof:bestId = id
                end if
            end if
        end for
    end for
    return {fileId:bestId,allowedFileIds:selection.allowedFileIds,allowAlternateVersions:true}
end function

 ' Fresh raw detail is the authority for audio ordinals; normalized adapter
' tracks may synthesize an index and cannot authorize an original claim.
function TaskSiloExperimentalCapabilityShape(body as String) as Boolean
    raw = ParseJson(body)
    ' Decoder convenience defaults must not turn unknown inventories into
    ' affirmative evidence that this server has no supported copy recipe.
    return SiloObject(raw) and SiloArray(SpField(raw,"features")) and SiloArray(SpField(raw,"deliveries"))
end function

function TaskSiloExperimentalIntent(params as Dynamic) as Boolean
    if not SiloObject(params) then return false
    if not SpBool(SpField(params,"experimentalOriginal")) or SpField(params,"experimentalOriginal") <> true then return false
    if not SpBool(SpField(params,"autoVersion")) or SpField(params,"autoVersion") <> false then return false
    if not SpOpaque(SpField(params,"itemId")) or SoFileId(SpField(params,"fileId")) = "" then return false
    if not SiloObject(SpField(params,"detail")) then return false
    if SpField(params,"qualityPreference") <> "original" or SpField(params,"subtitleMode") <> "off" then return false
    if SpField(params,"speculativePrebuffer") = true or SpField(params,"originalDisabled") = true then return false
    for each key in ["subtitleTrackId","subtitleTrackIndex","excludedVersionIds"]
        if params.DoesExist(key) then return false
    end for
    return true
end function

function TaskSiloP8AC3Proof(detail as Object, owner as Object, params as Object, device as Object) as Dynamic
    if not SiloCompatPreparationEnabled() or not TaskSiloExperimentalIntent(params) then return invalid
    file = SiloPlaybackFile(detail,owner.sourceId,params.itemId,params.fileId,TaskValue(params,"startPositionMs",0))
    if file = invalid then return invalid
    ordinal = SpField(params,"audioTrackIndex")
    if not SiloArray(SpField(file.version,"audioTracks")) then return invalid
    if not SpNumber(ordinal,file.version.audioTracks.Count()-1,true) then return invalid
    videos = SpField(file.version,"videoTracks")
    if not SiloArray(videos) then return invalid
    if videos.Count() <> 1 then return invalid
    kind = "experimental_query_p8_hdr10_ac3_fmp4_v1"
    return SiloCompatCandidate(detail,owner,params,SiloCompatSnapshotForKind(device,file.version.audioTracks[ordinal],kind,videos[0]),kind)
end function

function TaskSiloExperimentalAvailability(available as Boolean, reason as String) as Object
    return {ok:true,data:{available:available,reason:reason}}
end function

' Probe never allocates a session. The eventual start repeats these reads and
' proofs, so this result cannot authorize a stale source or server capability.
function TaskSiloExperimentalProbe(session as Object, params as Object, revision as Integer) as Object
    if not SpFields(params,["itemId","fileId","detail"],["audioTrackId","audioTrackIndex"]) then return TaskSiloExperimentalAvailability(false,"invalid_request")
    params = SpCopy(params)
    params["experimentalOriginal"] = true:params["autoVersion"] = false
    params["qualityPreference"] = "original":params["subtitleMode"] = "off"
    if not TaskSiloExperimentalIntent(params) then return TaskSiloExperimentalAvailability(false,"invalid_request")
    sourceId = TaskString(session,"sourceId"):itemId = TaskString(params,"itemId"):fileId = TaskString(params,"fileId")
    if SiloPlaybackFile(params.detail,sourceId,itemId,fileId,0) = invalid then return TaskSiloExperimentalAvailability(false,"source_changed")
    if SessionRevision("silo") <> revision then return TaskSiloExperimentalAvailability(false,"session_changed")
    fresh = TaskSiloFetch(session,"detail",{itemId:itemId},revision,4000)
    if SessionRevision("silo") <> revision then return TaskSiloExperimentalAvailability(false,"session_changed")
    if fresh.ok <> true then return TaskSiloExperimentalAvailability(false,"unavailable")
    session = fresh.session
    decoded = TaskDecode("silo","detail",fresh.response.body,{sourceId:sourceId,itemId:itemId})
    if decoded.ok <> true then return TaskSiloExperimentalAvailability(false,"source_changed")
    detail = ScopeCatalogData(decoded.data,sourceId)
    if SiloPlaybackFile(detail,sourceId,itemId,fileId,0) = invalid then return TaskSiloExperimentalAvailability(false,"source_changed")
    if params.DoesExist("audioTrackId") or params.DoesExist("audioTrackIndex")
        selected = TaskSiloFreshAudioIntent(params.detail,detail,sourceId,itemId,fileId,params)
        if selected = invalid then return TaskSiloExperimentalAvailability(false,"source_changed")
        if selected.preserve <> true
            params["audioTrackId"] = selected.id:params["audioTrackIndex"] = selected.index
        end if
    end if
    capabilities = TaskSiloFetch(session,"playback_capabilities",{},revision,6000)
    if SessionRevision("silo") <> revision then return TaskSiloExperimentalAvailability(false,"session_changed")
    if capabilities.ok <> true then return TaskSiloExperimentalAvailability(false,"unavailable")
    capability = DecodeSiloResponse("playback_capabilities",capabilities.response.body,{})
    if capability.ok <> true then return TaskSiloExperimentalAvailability(false,"unavailable")
    if not TaskSiloExperimentalCapabilityShape(capabilities.response.body) or not SiloExperimentalServer(capability.data) then return TaskSiloExperimentalAvailability(false,"server_not_eligible")
    scope = {provider:"silo",sourceId:sourceId,profileId:TaskString(session,"profileId"),generation:0}
    device = CreateObject("roDeviceInfo")
    clientCapabilities = TaskRokuSiloCapabilities(device)
    context = TaskRokuSiloContext(device,clientCapabilities)
    context = TaskNegotiateSiloHLS(context,device,capability.data,clientCapabilities)
    candidate = TaskSiloOriginalCandidate(ParseJson(fresh.response.body),capabilities.session,fileId,params,device,TaskUniqueId(),scope,context)
    if candidate = invalid
        owner = SpCopy(scope):owner["sessionRevision"] = revision
        candidate = TaskSiloP8AC3Proof(detail,owner,params,device)
    end if
    if candidate = invalid then return TaskSiloExperimentalAvailability(false,"source_not_eligible")
    return TaskSiloExperimentalAvailability(true,"available")
end function

function TaskSiloOriginalCandidate(wire as Dynamic, session as Object, fileId as String, params as Object, device as Object, attemptId as String, scope as Object, context = invalid as Dynamic, diagnostic = invalid as Dynamic) as Dynamic
    if diagnostic <> invalid then diagnostic["reason"] = "unavailable"
    experimental = SpField(params,"experimentalOriginal") = true
    hls = SpField(SpField(context,"deliveries"),"hls")
    if context <> invalid
        if not SiloObject(context) or not SiloObject(SpField(context,"deliveries")) or not SiloObject(hls) then return invalid
    end if
    if SiloObject(hls)
        for each key in ["enabled","supported_on_device"]
            if not SpBool(SpField(hls,key)) then return invalid
        end for
        for each key in ["features","video_codecs","audio_decode_codecs","audio_passthrough_codecs"]
            entries = SpField(hls,key)
            if not SiloArray(entries) then return invalid
            for each entry in entries
                if not SpText(entry,128) then return invalid
            end for
        end for
    end if
    if experimental and not TaskSiloExperimentalIntent(params) then return invalid
    if not experimental and not SiloOriginalActivationEnabled() and not SiloP8OriginalActivationEnabled()
        if SpField(params,"subtitleMode") <> "off" and SpField(params,"subtitleMode") <> "on" and SpField(params,"subtitleMode") <> "always"
            if diagnostic <> invalid then diagnostic["reason"] = "subtitle_intent"
            return invalid
        end if
    end if
    if not SiloObject(wire) or not SiloArray(wire.versions) then return invalid
    if wire.versions.Count() > 16 then return invalid
    file = invalid
    for each version in wire.versions
        if SoFileId(SpField(version,"file_id")) = fileId
            if file <> invalid then return invalid
            file = version
        end if
    end for
    if file = invalid then return invalid
    ' Official FileVersion omits this optional array when empty. A present
    ' malformed value is not the DTO's empty-inventory representation.
    subtitles = "off"
    if file.DoesExist("subtitle_tracks")
        if not SiloArray(file.subtitle_tracks) then return invalid
        if file.subtitle_tracks.Count() > 0 then subtitles = "unknown"
    end if
    if SpField(params,"subtitleMode") = "off" then subtitles = "off"
    if params.DoesExist("subtitleTrackIndex") then subtitles = "unknown"
    if params.DoesExist("subtitleTrackId") then subtitles = "unknown"
    if not experimental and (SpField(params,"subtitleMode") = "on" or SpField(params,"subtitleMode") = "always") then subtitles = "sidecar"
    selected = invalid
    if params.DoesExist("audioTrackIndex") or params.DoesExist("audioTrackId")
        selected = {index:SpField(params,"audioTrackIndex"),explicit:true}
        if params.DoesExist("audioTrackId") then selected["id"] = params.audioTrackId
    end if
    quality = TaskString(params,"qualityPreference")
    if quality = "" then quality = "original"
    intent = {sourceId:scope.sourceId,itemId:TaskString(params,"itemId"),fileId:fileId,scope:scope,qualityPreference:quality,subtitleMode:subtitles,bandwidthCapKbps:TaskValue(params,"bandwidthCapKbps",0),playbackAttemptId:attemptId}
    if experimental then intent["experimentalOriginal"] = true
    if subtitles = "sidecar"
        for each name in ["subtitleTrackId","subtitleTrackIndex"]
            if params.DoesExist(name) then intent[name] = params[name]
        end for
    end if
    ' Ordinary authority is local to an actual matching Task job. A direct
    ' policy/candidate call or caller parameter cannot synthesize this fence.
    if m.top <> invalid
        if m.top.job <> invalid
            captured = SpScope(m.top.job)
            if captured <> invalid
                if m.top.job.action = "playback_start" and SoScopeEqual(captured,scope) and (SpField(params,"subtitleMode") = "off" or subtitles = "sidecar") then intent["ordinaryRequestScoped"] = true
            end if
        end if
    end if
    if SpField(file,"codec_video") <> "hevc" or SpField(file,"container") <> "mkv" or SpField(file,"hdr") <> true then return invalid
    snapshot = TaskSiloOriginalSnapshot(device,file)
    fresh = {fresh:true,sourceId:scope.sourceId,itemId:intent.itemId,scope:scope,wire:file}
    eligible = SiloOriginalEligibility(fresh,selected,snapshot,intent)
    if diagnostic <> invalid then diagnostic["reason"] = SpField(eligible,"reason","eligible")
    if eligible.ok <> true then return invalid
    ' Prefer copy only when this file and selected audio fit the current delivery.
    if TaskSiloOriginalNativeCopy(wire,fileId,params,device,scope,context,eligible.proof)
        if diagnostic <> invalid then diagnostic["reason"] = "native_copy_preferred"
        return invalid
    end if
    claims = SiloOriginalClaims(eligible.proof)
    if experimental then claims = SpCopy(eligible.proof.claims)
    if claims.Count() = 0
        if diagnostic <> invalid then diagnostic["reason"] = "qualified_route_not_enabled"
        return invalid
    end if
    candidate = {proof:eligible.proof,claims:claims,subtitleBaseUrl:session.baseUrl}
    if subtitles = "sidecar" and not params.DoesExist("subtitleTrackId") and not params.DoesExist("subtitleTrackIndex")
        choice = SiloOriginalDefaultSubtitle(file,SpField(params,"subtitlePreferences"))
        if choice = invalid
            candidate["subtitleSelectionUnsupported"] = true
        else
            candidate.proof["defaultSubtitle"] = choice
            candidate.proof["subtitleTrackId"] = choice.trackId
            candidate.proof["subtitleTrackIndex"] = choice.combinedIndex
        end if
    end if
    return candidate
end function

function TaskSiloOriginalNativeCopy(wire as Object, fileId as String, params as Object, device as Object, scope as Object, context as Dynamic, proof as Object) as Boolean
    features = SiloClientNativeFeatures(context)
    if not SiloContains(features,"hls_copy_mpegts_v1") and not SiloContains(features,"native_hls_mpegts_v1") and not SiloContains(features,"native_hls_separate_audio_v1") then return false
    hls = SpField(SpField(context,"deliveries"),"hls")
    if not SiloContains(SiloList(SpField(hls,"video_codecs")),"hevc") then return false
    decoded = DecodeSiloResponse("detail",FormatJson(wire),{sourceId:scope.sourceId,itemId:TaskString(params,"itemId")})
    if decoded.ok <> true then return false
    detail = ScopeCatalogData(decoded.data,scope.sourceId)
    selected = SiloPlaybackFile(detail,scope.sourceId,TaskString(params,"itemId"),fileId,0)
    if selected = invalid then return false
    version = SpCopy(selected.version)
    version.audioCodec = proof.audioIdentity.codec
    capabilities = {hdr_details:SpField(hls,"hdr_details")}
    if TaskSiloVersionProof(version,device,capabilities,context,params) = invalid then return false
    ' Split HLS carries fMP4 video and TS audio; probe their own containers.
    videoContainer = "ts"
    if SiloContains(features,"native_hls_separate_audio_v1") then videoContainer = "mp4"
    videoLevel = "5.1"
    if proof.videoFacts.level = 150 then videoLevel = "5.0"
    if not TaskDecoderResult(TaskSiloCanDecodeVideo(device,{codec:"hevc",container:videoContainer,profile:"main 10",level:videoLevel})) then return false
    return TaskSiloP7NativeAudioProven(proof.audioIdentity,device,context)
end function

function TaskSiloOriginalSnapshot(device as Object, file as Object) as Object
    mode = TaskSiloVideoMode(device):display = TaskSiloDisplayProperties(device):details = device.GetModelDetails():os = device.GetOSVersion()
    hdr10 = SpField(display,"Hdr10") = true or SpField(display,"hdr10") = true
    fingerprint = device.GetModel()+"/"+TaskString(details,"ModelNumber")+"/"+TaskString(os,"major")+"."+TaskString(os,"minor")+"."+TaskString(os,"revision")+"."+TaskString(os,"build")+"/"+mode
    if hdr10 then fingerprint = fingerprint+"/hdr10"
    query = {codec:"hevc",container:"mkv",profile:"main 10",level:"5.1"}
    videoResult = TaskDecoderResult(TaskSiloCanDecodeVideo(device,query))
    query["result"] = videoResult
    audioQueries = []
    if SiloArray(file.audio_tracks)
        if file.audio_tracks.Count() <= 16
            for each track in file.audio_tracks
                if SiloObject(track)
                    codec = LCase(TaskString(track,"codec")):channels = SpField(track,"channels")
                    if SiloContains(["aac","ac3","eac3"],codec) and SpNumber(channels,8,true) and channels > 0
                        decoded = TaskDecoderResult(TaskSiloCanDecodeAudio(device,{codec:codec,container:"mkv",chcnt:channels,passthru:0}))
                        passed = TaskDecoderResult(TaskSiloCanDecodeAudio(device,{codec:codec,container:"mkv",chcnt:channels,passthru:1}))
                        audioQueries.Push({codec:codec,container:"mkv",chcnt:channels,result:decoded or passed})
                    end if
                end if
            end for
        end if
    end if
    return {fresh:true,model:device.GetModel(),modelType:device.GetModelType(),modelNumber:TaskString(details,"ModelNumber"),os:os,videoMode:mode,hdr10:hdr10,outputFingerprint:fingerprint,videoQuery:query,audioQueries:audioQueries}
end function

function TaskSiloPlaybackDiagnostics(raw as Object) as Object
    safe = {}
    delivery = TaskString(raw,"delivery")
    if SiloContains(["original_http","server_remux_progressive","server_remux_hls","server_transcode_hls"],delivery) then safe["delivery"] = delivery
    range = SpField(SpField(raw,"effective_recipe"),"dynamic_range","")
    if SiloContains(["sdr","hdr10","hdr10_plus","hlg","dolby_vision"],range) then safe["recipeRange"] = range
    return safe
end function

function TaskSiloOriginalDescriptor(candidate as Object, decision as Object, plan as Object, scope as Object) as Object
    proof = candidate.proof
    owner = {baseUrl:SpField(candidate,"subtitleBaseUrl"),sourceId:plan.sourceId,itemId:plan.itemId,fileId:plan.versionId,sessionId:plan.sessionId,planId:plan.planId,playbackAttemptId:proof.playbackAttemptId,outputFingerprint:proof.outputFingerprint,scope:scope}
    return SiloOriginalReceipt(proof,decision.playback_plan,owner)
end function

 ' Explicit pre-play audio is an intent captured from the scene's detail snapshot.
' A second fresh fetch must retain that lane before any allocation is requested.
function TaskSiloFreshAudioIntent(before as Object, fresh as Object, sourceId as String, itemId as String, fileId as String, params as Object) as Dynamic
    oldFile = SiloPlaybackFile(before,sourceId,itemId,fileId,0)
    newFile = SiloPlaybackFile(fresh,sourceId,itemId,fileId,0)
    if oldFile = invalid or newFile = invalid then return invalid
    oldTracks = SpField(oldFile.version,"audioTracks")
    newTracks = SpField(newFile.version,"audioTracks")
    if not SiloArray(oldTracks) or not SiloArray(newTracks) then return invalid
    if oldTracks.Count() > 32 or newTracks.Count() > 32 then return invalid
    ' Public opaque IDs and index-only selectors retain their existing server
    ' interpretation. The Detail UI supplies both an adapter ID and ordinal.
    if not params.DoesExist("audioTrackIndex") or not params.DoesExist("audioTrackId") then return {preserve:true}
    index = params.audioTrackIndex:id = params.audioTrackId
    canonical = "file:"+fileId+":audio:"+Int(index).ToStr()
    numericId = CreateObject("roRegex","^[0-9]+$","").IsMatch(id)
    if id <> canonical and not numericId then return {preserve:true}
    if numericId
        if id <> Int(index).ToStr() then return invalid
        ' A normalized explicit wire index is a legacy selector, not an array
        ' ordinal. Do not convert it into a different V3 lane.
        wireMatches = 0
        for each track in oldTracks
            if SpField(track,"index") = index and SpField(track,"id") = id and SpField(track,"wireIndexPresent") = true then wireMatches++
        end for
        if wireMatches > 1 then return invalid
        if wireMatches = 1 then return {preserve:true}
    end if
    wanted = invalid:matches = 0
    for each track in oldTracks
        ordinal = SpField(track,"sourceOrdinal",SpField(track,"index"))
        if SpNumber(ordinal,4095,true)
            canonical = "file:"+fileId+":audio:"+Int(ordinal).ToStr()
            sameIndex = not params.DoesExist("audioTrackIndex") or SpField(params,"audioTrackIndex") = ordinal
            sameId = not params.DoesExist("audioTrackId") or SpField(params,"audioTrackId") = SpField(track,"id") or SpField(params,"audioTrackId") = canonical
            if sameIndex and sameId then wanted = track:matches++
        end if
    end for
    if matches <> 1 then return invalid
    ordinal = SpField(wanted,"sourceOrdinal",SpField(wanted,"index"))
    matches = 0
    for each track in newTracks
        if SpField(track,"sourceOrdinal",SpField(track,"index")) = ordinal
            same = true
            for each key in ["id","codec","language","channels","layout"]
                if SpField(track,key) <> SpField(wanted,key) then same = false
            end for
            if not same then return invalid
            matches++
        end if
    end for
    if matches <> 1 then return invalid
    return {index:ordinal,id:"file:"+fileId+":audio:"+Int(ordinal).ToStr()}
end function

' Private Task/adapter checkpoint only. No Scene ingress or ordinary admission.
function SiloOfficialLegacyHDR10QualificationEnabled() as Boolean
    return false
end function

function TaskSiloLegacyHDR10Proof(wire as Dynamic, fileId as String, params as Object, device as Object, capabilities as Object, revision as Integer) as Dynamic
    if not SiloOfficialLegacyHDR10QualificationEnabled() then return invalid
    if params.privateLegacyHdr10 <> true or params.autoVersion <> false or params.qualityPreference <> "original" or params.subtitleMode <> "off" or params.startPositionMs <> 0 then return invalid
    if params.speculativePrebuffer = true or params.experimentalOriginal = true then return invalid
    for each key in ["subtitleTrackId","subtitleTrackIndex","excludedVersionIds"]
        if params.DoesExist(key) then return invalid
    end for
    job = m.top.job:scope = SpScope(job)
    if scope = invalid or job.action <> "playback_start" or not SpNumber(job.requestId,2147483646,true) or job.requestId = 0 then return invalid
    if SessionRevision("silo") <> revision or m.top.cancelled = true then return invalid
    currentSession = LoadSession("silo")
    if scope.sourceId <> currentSession.sourceId or scope.profileId <> currentSession.profileId then return invalid
    if not SiloObject(wire) or not SiloArray(wire.versions) then return invalid
    file = invalid
    for each candidate in wire.versions
        if TaskString(candidate,"file_id") = fileId
            if file <> invalid then return invalid
            file = candidate
        end if
    end for
    if SpField(file,"video_copy_unsafe",false) <> false then return invalid
    if file = invalid or not SiloArray(file.video_tracks) or file.video_tracks.Count() <> 1 then return invalid
    video = file.video_tracks[0]
    if SoVideoGate(video) <> "" or video.dv_profile <> 8 or video.width <> 3840 then return invalid
    if SoFrameRate(video.frame_rate) > 24 or SpField(video,"video_copy_unsafe") = true then return invalid
    if not SpNumber(file.duration,604800) or file.duration <= 0 then return invalid
    bitrate = SoSourceBitrate(file)
    if not SpNumber(bitrate,200000) or bitrate <= 0 then return invalid
    if params.DoesExist("bandwidthCapKbps") then if bitrate > params.bandwidthCapKbps then return invalid
    index = SpField(params,"audioTrackIndex")
    if not SiloArray(file.audio_tracks) then return invalid
    if not SpNumber(index,file.audio_tracks.Count()-1,true) then return invalid
    if params.audioTrackId <> "file:"+fileId+":audio:"+Int(index).ToStr() then return invalid
    audio = file.audio_tracks[index]
    if audio.codec <> "eac3" or not SpNumber(audio.channels,8,true) or audio.channels = 0 or not SpText(audio.layout,32) then return invalid
    if not SiloContains(capabilities.codecs_video,"hevc") or SpField(capabilities,"max_resolution") <> "2160p" then return invalid
    if SpField(SpField(capabilities,"hdr_details"),"hdr10") <> true then return invalid
    if SpField(file,"codec_video") <> "hevc" or SpField(file,"container") <> "mkv" or SpField(file,"hdr") <> true then return invalid
    snapshot = TaskSiloOriginalSnapshot(device,file)
    if snapshot.hdr10 <> true or Left(snapshot.videoMode,5) <> "2160p" or snapshot.videoQuery.result <> true then return invalid
    ' These are container-specific facts, never muxed-fMP4 HLS acceptance.
    audioFacts = []
    for each container in ["mp4","ts"]
        decoded = TaskDecoderResult(TaskSiloCanDecodeAudio(device,{codec:"eac3",container:container,chcnt:audio.channels,passthru:0}))
        passed = TaskDecoderResult(TaskSiloCanDecodeAudio(device,{codec:"eac3",container:container,chcnt:audio.channels,passthru:1}))
        if not decoded and not passed then return invalid
        audioFacts.Push({container:container,decode:decoded,passthrough:passed})
    end for
    if not (audioFacts[0].decode and audioFacts[1].decode) and not (audioFacts[0].passthrough and audioFacts[1].passthrough) then return invalid
    return {schemaVersion:1,route:"official_legacy_hdr10_private_v1",fileId:fileId,scope:scope,requestId:job.requestId,revision:revision,video:SpCopy(video),audio:SpCopy(audio),audioIndex:index,audioId:params.audioTrackId,bitrate:bitrate,snapshot:snapshot,audioFacts:audioFacts,audioAcceptance:"unqualified"}
end function

function TaskSiloLegacyHDR10Context(context as Object, proof as Object) as Object
    result = SpCopy(context)
    for each name in ["original_http","progressive"]
        result.deliveries[name].enabled = false
        result.deliveries[name].supported_on_device = false
        result.deliveries[name].validated_claims = []
    end for
    hls = result.deliveries.hls
    hls.enabled = true:hls.supported_on_device = true
    hls.containers = ["hls"]:hls.video_codecs = ["hevc"]
    hls.audio_decode_codecs = []:hls.audio_passthrough_codecs = []
    if proof.audioFacts[0].decode and proof.audioFacts[1].decode then hls.audio_decode_codecs = ["eac3"]
    if proof.audioFacts[0].passthrough and proof.audioFacts[1].passthrough then hls.audio_passthrough_codecs = ["eac3"]
    hls.features = ["native_hls_playback_v1"]
    hls.hdr_details = {hdr10:true,hdr10_plus:false,hlg:false,dolby_vision_profiles:[]}
    result.output.hdr_details = SpCopy(hls.hdr_details)
    result.output.display = {hdr_evidence:"exact",hdr_types:SpCopy(hls.hdr_details)}
    return result
end function

function TaskStartSiloPlayback(session as Object, params as Object, revision as Integer, nativeAudioIndex = invalid as Dynamic, attempts = invalid as Dynamic) as Object
    if attempts = invalid then attempts = []
    result = TaskStartSiloPlaybackAttempt(session,params,revision,nativeAudioIndex,attempts)
    history = SiloStartAttempts(attempts)
    if history.Count() > 0
        result["startAttempts"] = history
        if SiloObject(SpField(result,"plan")) then result.plan["startAttempts"] = history
    end if
    return result
end function

function TaskStartSiloPlaybackAttempt(session as Object, params as Object, revision as Integer, nativeAudioIndex as Dynamic, attempts as Object) as Object
    ' Serialized Scene jobs retain lowercase dot-assigned selectors. Normalize
    ' these known keys locally, preserving invalid values for normal validation.
    canonical = SpCopy(params):seenSelectors = {}
    for each name in params
        for each selector in ["audioTrackId","audioTrackIndex","subtitleTrackId","subtitleTrackIndex"]
            if LCase(name) = LCase(selector)
                if seenSelectors.DoesExist(selector) then return TaskError("invalid_request")
                seenSelectors[selector] = true
                canonical.Delete(name):canonical[selector] = params[name]
            end if
        end for
    end for
    params = canonical
    ' Validate types before fresh-intent Int/regex use; retain numeric and
    ' opaque-ID semantics for legacy selectors rather than dropping values.
    if params.DoesExist("audioTrackIndex")
        kind = type(params.audioTrackIndex)
        if kind <> "Integer" and kind <> "roInt" and kind <> "roInteger" and kind <> "LongInteger" and kind <> "roLongInteger" and kind <> "Float" and kind <> "roFloat" and kind <> "Double" and kind <> "roDouble" then return TaskError("invalid_request")
    end if
    if params.DoesExist("audioTrackId")
        if type(params.audioTrackId) <> "String" and type(params.audioTrackId) <> "roString" then return TaskError("invalid_request")
    end if
    if not TaskPlaybackOptionsValid("silo", params) then return TaskError("invalid_request")
    privateLegacy = SpField(params,"privateLegacyHdr10") = true
    if params.DoesExist("privateLegacyHdr10")
        if not SpBool(params.privateLegacyHdr10) or not privateLegacy or not SiloOfficialLegacyHDR10QualificationEnabled() then return TaskError("invalid_request")
    end if
    if privateLegacy and nativeAudioIndex <> invalid then return TaskError("invalid_request")
    requireSubtitleOff = SpField(params,"subtitleOffRequired") = true
    experimental = SpField(params,"experimentalOriginal") = true
    if experimental and not TaskSiloExperimentalIntent(params) then return TaskError("invalid_request")
    if experimental and nativeAudioIndex <> invalid then return TaskError("invalid_request")
    retryIdentity = {sourceId:TaskString(session,"sourceId"),profileId:TaskString(session,"profileId"),profileToken:TaskString(session,"profileToken"),baseUrl:TaskString(session,"baseUrl")}
    retryOwner = invalid:retryRequestId = invalid
    if m.top <> invalid
        retryOwner = SpScope(m.top.job):retryRequestId = SpField(m.top.job,"requestId")
    end if
    expectedExplicitAudio = invalid
    autoAudioSelection = invalid
    fileId = TaskString(params,"fileId")
    if fileId = "" then fileId = TaskString(params,"versionId")
    if not SpOpaque(fileId) then return TaskError("invalid_request")
    if not SpOpaque(TaskString(params,"itemId")) then return TaskError("invalid_request")
    if params.DoesExist("fileId") and params.DoesExist("versionId")
        if TaskString(params,"fileId") <> TaskString(params,"versionId") then return TaskError("invalid_request")
    end if
    if params.DoesExist("startPositionMs")
        if not SpNumber(params.startPositionMs,604800000) then return TaskError("invalid_request")
    end if
    selection = {fileId:fileId,allowedFileIds:[fileId],allowAlternateVersions:false}
    autoNative = params.autoVersion = true
    for each key in ["audioTrackId","audioTrackIndex","subtitleTrackId","subtitleTrackIndex"]
        if params.DoesExist(key) then autoNative = false
    end for
    if params.DoesExist("detail")
        sourceId = TaskString(session,"sourceId"):itemId = TaskString(params,"itemId")
        target = TaskValue(params,"startPositionMs",0)
        if SiloPlaybackFile(params.detail,sourceId,itemId,fileId,target) = invalid then return TaskError("invalid_request")
        if SessionRevision("silo") <> revision then return TaskError("session_changed")
        fresh = TaskSiloFetch(session,"detail",{itemId:itemId},revision,4000)
        if SessionRevision("silo") <> revision then return TaskError("session_changed")
        if fresh.ok <> true then return fresh
        session = fresh.session
        decodedFile = TaskDecode("silo","detail",fresh.response.body,{sourceId:sourceId,itemId:itemId})
        if decodedFile.ok <> true then print "Silo playback rejected step=1" : return TaskError("invalid_response")
        freshDetail = ScopeCatalogData(decodedFile.data,sourceId)
        freshWire = ParseJson(fresh.response.body)
        if params.DoesExist("audioTrackIndex") or params.DoesExist("audioTrackId")
            explicitAudio = TaskSiloFreshAudioIntent(params.detail,freshDetail,sourceId,itemId,fileId,params)
            if explicitAudio = invalid then return TaskError("invalid_audio_selection")
            if explicitAudio.preserve <> true
                expectedExplicitAudio = explicitAudio
                params = SpCopy(params)
                params["audioTrackIndex"] = explicitAudio.index
                params["audioTrackId"] = explicitAudio.id
            end if
        end if
        if not autoNative
            if SiloPlaybackFile(freshDetail,sourceId,itemId,fileId,target) = invalid then print "Silo playback rejected step=2" : return TaskError("invalid_response")
        end if
        selected = fileId
        if autoNative then selected = ""
        selection = SiloNativeSelection(freshDetail,sourceId,itemId,selected)
        if selection = invalid then return TaskError("invalid_response")
        fileId = selection.fileId
    end if
    excluded = []
    if params.DoesExist("excludedVersionIds")
        if not autoNative or not params.DoesExist("detail") or not SiloArray(params.excludedVersionIds) then return TaskError("invalid_request")
        if params.excludedVersionIds.Count() >= 8 then return TaskError("playback_terminal")
        for each id in params.excludedVersionIds
            if not SpOpaque(id) or SiloContains(excluded,id) then return TaskError("invalid_request")
            excluded.Push(id)
        end for
        remaining = []
        for each id in selection.allowedFileIds
            if not SiloContains(excluded,id) then remaining.Push(id)
        end for
        if remaining.Count() = 0 then return TaskError("playback_terminal")
        if SiloContains(excluded,selection.fileId) then selection.fileId = remaining[0]
        selection.allowedFileIds = remaining
        fileId = selection.fileId
    end if
    if params.DoesExist("compatExcludedFileIds")
        if not autoNative or not params.DoesExist("detail") or not SiloArray(params.compatExcludedFileIds) then return TaskError("invalid_request")
        if params.qualityExplicit <> false or params.subtitleMode <> "off" then return TaskError("invalid_request")
        if params.compatExcludedFileIds.Count() = 0 or params.compatExcludedFileIds.Count() >= 8 then return TaskError("invalid_request")
        compatIds = []
        for each id in params.compatExcludedFileIds
            if not SpOpaque(id) or SiloContains(compatIds,id) then return TaskError("invalid_request")
            if SiloPlaybackFile(freshDetail,TaskString(session,"sourceId"),TaskString(params,"itemId"),id,TaskValue(params,"startPositionMs",0)) = invalid then return TaskError("invalid_request")
            compatIds.Push(id)
        end for
    end if
    capabilityResult = TaskSiloFetch(session, "playback_capabilities", {}, revision, 6000)
    if capabilityResult.ok <> true then return capabilityResult
    capabilityResponse = capabilityResult.response
    session = capabilityResult.session
    capability = DecodeSiloResponse("playback_capabilities", capabilityResponse.body, {})
    if capability.ok <> true then return TaskError(TaskString(capability, "errorCode"))
    if params.DoesExist("mediaAuthMode")
        if not SiloContains(capability.data.features,"header_authenticated_media_v1") then return SiloPlaybackFailureDetails(TaskError("unsupported_playback_protocol"),invalid,"start")
    end if
    if experimental
        if not TaskSiloExperimentalCapabilityShape(capabilityResponse.body) or not SiloExperimentalServer(capability.data) then return TaskError("unsupported_stream")
    end if
    versions = TaskValue(TaskValue(capability, "data", {}), "protocolVersions", [])
    hasV3 = false
    for each version in versions
        if version = 3 then hasV3 = true
    end for
    if not hasV3 then return SiloPlaybackFailureDetails(TaskError("unsupported_playback_protocol"),invalid,"start")

    installationId = TaskString(capability.data, "installationId")
    if not TaskPlaybackOpaqueId(installationId) then return TaskError("invalid_capabilities")
    device = CreateObject("roDeviceInfo")
    decoderEvidence = {}
    clientCapabilities = TaskRokuSiloCapabilities(device,decoderEvidence)
    context = TaskRokuSiloContext(device, clientCapabilities)
    context = TaskNegotiateSiloHLS(context,device,capability.data,clientCapabilities)
    legacyProof = invalid
    if privateLegacy
        legacyProof = TaskSiloLegacyHDR10Proof(freshWire,fileId,params,device,clientCapabilities,revision)
        if legacyProof = invalid then return TaskError("unsupported_stream")
        context = TaskSiloLegacyHDR10Context(context,legacyProof)
    end if
    originalScope = {provider:"silo",sourceId:TaskString(session,"sourceId"),profileId:TaskString(session,"profileId"),generation:0}
    originalScopeValid = true
    if m.top <> invalid
        if m.top.job <> invalid
            originalScopeValid = false
            capturedScope = SpScope(m.top.job)
            if capturedScope <> invalid
                if capturedScope.sourceId = originalScope.sourceId and capturedScope.profileId = originalScope.profileId
                    originalScope = capturedScope
                    originalScopeValid = true
                end if
            end if
        end if
    end if
    originalDiagnostic = {reason:"not_checked"}
    attemptId = invalid:preflightOriginal = invalid:originalPreflightChecked = false
    if not autoNative and not experimental and not privateLegacy and originalScopeValid and params.DoesExist("detail") and nativeAudioIndex = invalid and params.originalDisabled <> true and params.speculativePrebuffer <> true
        attemptId = TaskUniqueId()
        originalPreflightChecked = true
        preflightOriginal = TaskSiloOriginalCandidate(freshWire,session,fileId,params,device,attemptId,originalScope,context,originalDiagnostic)
    end if
    ' TS/HLS audio can be proven even when no codec spans both MP4 and MKV.
    ' Check usable deliveries after their independent capability negotiation.
    if not autoNative and preflightOriginal = invalid and params.DoesExist("detail") and SiloCompatPreparationEnabled() and nativeAudioIndex = invalid
        continuation = TaskSiloP7CompatSelectionContinuation(freshDetail,selection,session,params,device,clientCapabilities,context,revision)
        if continuation = invalid then continuation = TaskSiloCompatSelectionContinuation(freshDetail,selection,selection,session,params,device,clientCapabilities,context,revision,freshWire,decoderEvidence)
        if continuation <> invalid then return {ok:false,errorCode:"compat_prepare_required",compatContinuation:continuation}
    end if
    if autoNative and params.DoesExist("detail")
        inventory = SpCopy(selection)
        selection = TaskSiloBestNativeSelection(freshDetail,selection,device,clientCapabilities,TaskValue(params,"startPositionMs",0),context,params,freshWire,decoderEvidence)
        fileId = selection.fileId
        if SiloCompatPreparationEnabled() and nativeAudioIndex = invalid
            automatic = TaskSiloP7AutoSelection(freshDetail,inventory,session,params,device,clientCapabilities,context,revision)
            if automatic <> invalid
                if SpField(automatic,"continuation") <> invalid then return {ok:false,errorCode:"compat_prepare_required",compatContinuation:automatic.continuation}
                autoAudioSelection = automatic.selection
                expectedExplicitAudio = {id:autoAudioSelection.audio_track_id,index:autoAudioSelection.audio_track_index}
            end if
            continuation = invalid
            if autoAudioSelection = invalid then continuation = TaskSiloCompatSelectionContinuation(freshDetail,inventory,selection,session,params,device,clientCapabilities,context,revision,freshWire,decoderEvidence)
            if continuation <> invalid then return {ok:false,errorCode:"compat_prepare_required",compatContinuation:continuation}
        end if
    end if
    if experimental and params.DoesExist("audioTrackIndex") and params.DoesExist("audioTrackId")
        original = TaskSiloOriginalCandidate(freshWire,session,fileId,params,device,TaskUniqueId(),SpScope(m.top.job),context)
        if original = invalid
            continuation = TaskSiloP8AC3Continuation(freshDetail,selection,session,params,device,revision)
            if continuation <> invalid then return {ok:false,errorCode:"compat_prepare_required",compatContinuation:continuation}
        end if
    end if
    level50 = invalid:level50Capabilities = SpCopy(clientCapabilities):level50Context = SpCopy(context)
    if not experimental and not privateLegacy and params.DoesExist("detail")
        level50 = TaskSiloLevel50HDR10(freshWire,freshDetail,TaskString(session,"sourceId"),TaskString(params,"itemId"),fileId,TaskValue(params,"startPositionMs",0),params,device,clientCapabilities,context,decoderEvidence)
        if level50 <> invalid then clientCapabilities = level50.capabilities:context = level50.context
    end if
    mp4 = invalid
    if context.deliveries.original_http.enabled <> true and context.deliveries.hls.enabled <> true and params.DoesExist("detail")
        mp4 = TaskSiloMp4Original(freshWire,freshDetail,TaskString(session,"sourceId"),TaskString(params,"itemId"),fileId,TaskValue(params,"startPositionMs",0),params,device,clientCapabilities,context)
        if mp4 <> invalid
            clientCapabilities = mp4.capabilities:context = mp4.context
            mp4["identity"] = {sourceId:TaskString(session,"sourceId"),profileId:TaskString(session,"profileId"),profileToken:TaskString(session,"profileToken"),baseUrl:TaskString(session,"baseUrl")}
        end if
    end if
    lastStereo = invalid
    if not experimental and not privateLegacy then lastStereo = TaskSiloLastStereoHLS(device,capability.data,clientCapabilities,context)
    if lastStereo <> invalid
        clientCapabilities = lastStereo.capabilities:context = lastStereo.context
        lastStereo["identity"] = {sourceId:TaskString(session,"sourceId"),profileId:TaskString(session,"profileId"),profileToken:TaskString(session,"profileToken"),baseUrl:TaskString(session,"baseUrl")}
    end if
    originalDelivery = context.deliveries.original_http:hlsDelivery = context.deliveries.hls
    if (originalDelivery.enabled <> true or originalDelivery.supported_on_device <> true) and (hlsDelivery.enabled <> true or hlsDelivery.supported_on_device <> true) then return TaskError("unsupported_device")
    nativeSelection = SpCopy(selection)
    ' Original does not ask Silo to upgrade the native file. After native
    ' inventory selection, pin this proven/default anchor for the whole lease.
    selection = {fileId:fileId,allowedFileIds:[fileId],allowAlternateVersions:false}
    if params.DoesExist("detail")
        if SiloPlaybackFile(freshDetail,TaskString(session,"sourceId"),TaskString(params,"itemId"),fileId,TaskValue(params,"startPositionMs",0)) = invalid then return TaskError("invalid_response")
    end if
    if params.qualityExplicit = false and params.DoesExist("detail") and TaskString(params,"qualityPreference") = "original"
        anchor = SiloPlaybackFile(freshDetail,TaskString(session,"sourceId"),TaskString(params,"itemId"),fileId,0)
        resolution = LCase(TaskString(anchor.version,"resolution"))
        mode = LCase(TaskSiloVideoMode(device))
        if resolution = "2160p" or resolution = "4k" or resolution = "3840x2160"
            if Left(mode,5) = "1080p" or Left(mode,5) = "1080i" or Left(mode,4) = "720p" or Left(mode,4) = "480p" or Left(mode,4) = "480i" then params["qualityPreference"] = SiloFallbackQuality("original",TaskString(clientCapabilities,"max_resolution"))
        end if
    end if
    audioProjection = invalid
    if lastStereo = invalid and not experimental and not privateLegacy and nativeAudioIndex = invalid and params.DoesExist("detail")
        selectedAudio = invalid
        if params.DoesExist("audioTrackId") or params.DoesExist("audioTrackIndex") then selectedAudio = {id:SpField(params,"audioTrackId"),index:SpField(params,"audioTrackIndex")}
        if autoAudioSelection <> invalid then selectedAudio = {id:autoAudioSelection.audio_track_id,index:autoAudioSelection.audio_track_index}
        audioProjection = TaskSiloAudioProjection(freshWire,fileId,selectedAudio,TaskString(params,"qualityPreference"),device,clientCapabilities,context)
        if audioProjection <> invalid
            clientCapabilities = audioProjection.capabilities:context = audioProjection.context
            audioProjection["identity"] = {sourceId:TaskString(session,"sourceId"),profileId:TaskString(session,"profileId"),profileToken:TaskString(session,"profileToken"),baseUrl:TaskString(session,"baseUrl")}
        end if
    end if
    if params.speculativePrebuffer = true
        ' Speculation may preload a freshly proven source, never allocate an
        ' unproven source just to discover a lower server fallback.
        if not params.DoesExist("detail") then return TaskError("unsupported_stream")
        preloadFile = SiloPlaybackFile(freshDetail,TaskString(session,"sourceId"),TaskString(params,"itemId"),fileId,TaskValue(params,"startPositionMs",0))
        if preloadFile = invalid then return TaskError("unsupported_stream")
        preloadProof = TaskSiloVersionProof(preloadFile.version,device,clientCapabilities,context,params)
        if preloadProof = invalid then return TaskError("unsupported_stream")
        preloadCap = TaskValue(params,"bandwidthCapKbps",0)
        if preloadCap > 0
            if preloadProof.bitrate <= 0 or preloadProof.bitrate > preloadCap then return TaskError("unsupported_stream")
        end if
    end if
    if attemptId = invalid then attemptId = TaskUniqueId()
    startParams = {fileId: fileId, installationId: installationId, playbackAttemptId: attemptId, startPositionMs: TaskValue(params, "startPositionMs", 0), clientCapabilities: clientCapabilities, clientPlaybackContext: context}
    startParams["allowAlternateVersions"] = selection.allowAlternateVersions
    startParams["seekReanchorNegotiated"] = SiloSeekFeatures(capability.data.features) <> invalid
    for each name in ["qualityPreference", "bandwidthCapKbps", "audioTrackId", "audioTrackIndex", "subtitleTrackId", "subtitleTrackIndex", "mediaAuthMode"]
        if params.DoesExist(name) then startParams[name] = params[name]
    end for
    if autoAudioSelection <> invalid
        startParams["audioTrackId"] = autoAudioSelection.audio_track_id
        startParams["audioTrackIndex"] = autoAudioSelection.audio_track_index
    end if
    if nativeAudioIndex <> invalid
        if params.DoesExist("audioTrackId") or params.DoesExist("audioTrackIndex") or not params.DoesExist("detail") then return TaskError("invalid_request")
        file = SiloPlaybackFile(freshDetail,TaskString(session,"sourceId"),TaskString(params,"itemId"),fileId,TaskValue(params,"startPositionMs",0))
        if file = invalid then return TaskError("invalid_request")
        alternate = TaskSiloUnambiguousAudio(file.version,device,context)
        if alternate = invalid then return TaskError("invalid_request")
        if alternate.index <> nativeAudioIndex then return TaskError("invalid_request")
        startParams["audioTrackIndex"] = nativeAudioIndex
    end if
    originalCandidate = invalid
    if not privateLegacy and lastStereo = invalid and audioProjection = invalid and originalScopeValid and params.DoesExist("detail") and nativeAudioIndex = invalid and autoAudioSelection = invalid and params.originalDisabled <> true and params.speculativePrebuffer <> true
        if originalPreflightChecked
            originalCandidate = preflightOriginal
        else
            originalCandidate = TaskSiloOriginalCandidate(freshWire,session,fileId,params,device,attemptId,originalScope,context,originalDiagnostic)
        end if
        if originalCandidate <> invalid
            if SpField(originalCandidate,"subtitleSelectionUnsupported") = true then return TaskError("subtitle_selection_unsupported")
            if originalCandidate.proof.DoesExist("defaultSubtitle")
                startParams["subtitleTrackId"] = originalCandidate.proof.subtitleTrackId
                startParams["subtitleTrackIndex"] = originalCandidate.proof.subtitleTrackIndex
            end if
            context.deliveries.original_http.validated_claims = originalCandidate.claims
            startParams["audioTrackIndex"] = originalCandidate.proof.audioIdentity.index
            startParams["audioTrackId"] = originalCandidate.proof.audioIdentity.id
        end if
    end if
    if experimental and originalCandidate = invalid then return TaskError("unsupported_stream")
    compatRefusalEligible = false
    if SiloCompatPreparationEnabled() and not experimental and not privateLegacy and nativeAudioIndex = invalid and params.DoesExist("detail")
        compatRefusalEligible = TaskSiloCompatRefusalSource(freshDetail,session,params,device,revision,fileId) <> invalid
    end if
    if not TaskSiloApprovalIdentityCurrent(retryIdentity,revision) then return TaskError("session_changed")
    if m.top.cancelled = true then return TaskError("cancelled")
    startTimeout = 12000
    if SiloNativeDeliveryFeatures(context).Count() > 0 then startTimeout = 90000
    requestFacts = TaskSiloStartRequestFacts(freshDetail,session,params,fileId,startParams,clientCapabilities,context)
    if privateLegacy then m.siloPrivateLegacyStartPending = true
    if lastStereo <> invalid
        startResult = TaskSiloFetch(session,"playback_start",startParams,revision,startTimeout,invalid,lastStereo.identity,true)
    else if audioProjection <> invalid
        startResult = TaskSiloFetch(session,"playback_start",startParams,revision,startTimeout,invalid,audioProjection.identity,true)
    else if mp4 = invalid
        startResult = TaskSiloFetch(session,"playback_start",startParams,revision,startTimeout,invalid,retryIdentity,true)
    else
        startResult = TaskSiloFetch(session,"playback_start",startParams,revision,startTimeout,invalid,mp4.identity,true)
    end if
    if startResult.ok <> true
        startResult["startRequestFacts"] = requestFacts
        return startResult
    end if
    response = startResult.response
    session = startResult.session
    decision = ParseJson(response.body)
    if not experimental
        summary = {request:requestFacts,httpStatus:response.statusCode,outcome:"invalid",originalReason:originalDiagnostic.reason}
        if SiloObject(decision) then summary.outcome = TaskSiloStartResponseFacts(decision,response.statusCode).outcome
        attempts.Push(summary)
        if attempts.Count() > 8 then attempts.Delete(1)
    end if
    if not SiloObject(decision) then print "Silo playback rejected step=3" : return TaskError("invalid_response")
    if privateLegacy
        m.siloPrivateLegacyAllocation = {decision:decision,owner:retryOwner,requestId:retryRequestId,revision:revision}
        if response.statusCode = 200 or response.statusCode = 201 then m.siloPrivateLegacyNonAllocating = TaskSiloStartTerminal(decision)
    end if
    cleanup = TaskSiloCleanupPlan(decision, installationId)
    if cleanup <> invalid and params.DoesExist("detail")
        ' Ownership is the validated replacement request, never echoed file
        ' identity from the refused server plan. Keep the original stop ID.
        cleanup["provider"] = "silo"
        cleanup["sourceId"] = TaskString(session,"sourceId")
        cleanup["itemId"] = TaskString(params,"itemId")
        cleanup["versionId"] = fileId
    end if
    if privateLegacy and cleanup <> invalid
        if not TaskSiloStartCleanupIdentity(decision,cleanup) then return TaskRejectSiloPlayback(session,cleanup,"invalid_response",revision,decision)
    end if
    ' Retain the allocated response long enough to abandon its captured lease.
    if not TaskSiloApprovalIdentityCurrent(retryIdentity,revision) then return TaskRejectSiloPlayback(session,cleanup,"session_changed",revision)
    if m.top.cancelled = true then return TaskRejectSiloPlayback(session,cleanup,"cancelled",revision)
    if lastStereo <> invalid
        if not TaskSiloApprovalIdentityCurrent(lastStereo.identity,revision) then return TaskRejectSiloPlayback(session,cleanup,"session_changed",revision)
        if m.top.cancelled = true then return TaskRejectSiloPlayback(session,cleanup,"cancelled",revision)
    end if
    if audioProjection <> invalid
        if not TaskSiloApprovalIdentityCurrent(audioProjection.identity,revision) then return TaskRejectSiloPlayback(session,cleanup,"session_changed",revision)
        if m.top.cancelled = true then return TaskRejectSiloPlayback(session,cleanup,"cancelled",revision)
    end if
    if mp4 <> invalid
        if not TaskSiloApprovalIdentityCurrent(mp4.identity,revision) then return TaskRejectSiloPlayback(session,cleanup,"session_changed",revision)
        if m.top.cancelled = true then return TaskRejectSiloPlayback(session,cleanup,"cancelled",revision)
    end if
    if level50 <> invalid and SpField(decision,"playback_plan") <> invalid
        if not TaskSiloLevel50HDR10Receipt(decision,level50.proof) then return TaskRejectSiloPlayback(session,cleanup,"invalid_response",revision)
        checkedLevel50 = TaskSiloLevel50HDR10(freshWire,freshDetail,TaskString(session,"sourceId"),TaskString(params,"itemId"),fileId,TaskValue(params,"startPositionMs",0),params,device,level50Capabilities,level50Context,decoderEvidence)
        if checkedLevel50 = invalid then return TaskRejectSiloPlayback(session,cleanup,"session_changed",revision)
        if not SiloSeekEqual(checkedLevel50.proof,level50.proof) then return TaskRejectSiloPlayback(session,cleanup,"session_changed",revision)
    end if
    try
        receiptContext = context
        ' The separately gated Original proof is verified below; it never grants
        ' ordinary native DV authority or changes the advertised request bounds.
        if originalCandidate <> invalid and TaskString(decision.playback_plan,"delivery") = "original_http" then receiptContext = invalid
        plan = SiloPlaybackPlan(decision, session, SiloNativeDeliveryFeatures(context),legacyProof,receiptContext)
    catch exception
        print "Silo playback rejected step=4" : return TaskRejectSiloPlayback(session, cleanup, "invalid_response", revision)
    end try
    ' A valid HLS plan can still select audio the current Roku cannot decode.
    ' Refuse it through the same owner-acknowledged retry path as other native
    ' route refusals, so Auto can try a supported route after cleanup.
    if plan.ok = true and not privateLegacy
        if not TaskSiloDeliveredHLSSupported(decision.playback_plan,device) then plan = {ok:false,errorCode:"unsupported_stream"}
    end if
    if plan.ok <> true
        if originalCandidate <> invalid then params["originalDisabled"] = true
        acknowledgment = {playbackAttemptId:attemptId}
        rejected = TaskRejectSiloPlayback(session,cleanup,TaskString(plan,"errorCode"),revision,decision,acknowledgment)
        if not experimental then rejected["startRequestFacts"] = requestFacts
        if not experimental then rejected["startResponseFacts"] = TaskSiloStartResponseFacts(decision,SpField(response,"statusCode"))
        ' Internal result fact only: a retained, consistent cleanup lease can
        ' recover through the Scene's existing authenticated stop ticket.
        if SiloObject(SpField(rejected,"plan"))
            if TaskSiloStartCleanupIdentity(decision,rejected.plan) then rejected["cleanupLeaseKnown"] = true
        end if
        if experimental then return rejected
        if privateLegacy
            if cleanup = invalid and not TaskSiloStartTerminal(decision) then rejected["leaseUncertain"] = true
            return rejected
        end if
        if compatRefusalEligible and plan.errorCode = "unsupported_stream"
            source = TaskSiloCompatRefusalSource(freshDetail,session,params,device,revision,fileId)
            if source <> invalid
                continuation = TaskSiloCompatRefusalContinuation(source,decision,acknowledgment,session,params,revision)
                if continuation <> invalid then return {ok:false,errorCode:"compat_prepare_required",compatContinuation:continuation}
            end if
            ' Revalidation may decline handoff; it cannot erase a sent owner.
            if acknowledgment.state <> "acknowledged"
                rejected["leaseUncertain"] = true
            else if not TaskSiloDecisionIdentity(decision,fileId,acknowledgment.sessionId)
                rejected["leaseUncertain"] = true
            end if
            return rejected
        end if
        oversizedAVC = plan.errorCode = "unsupported_stream" and SiloNativeH264Oversized(decision.playback_plan)
        unsupportedHLS = plan.errorCode = "unsupported_stream" and SpField(SpField(decision.playback_plan,"stream"),"protocol") = "hls"
        ' This newly admitted request cannot retry an unowned allocation.
        if lastStereo <> invalid and (unsupportedHLS or oversizedAVC) and cleanup = invalid
            rejected["leaseUncertain"] = true
            return rejected
        end if
        retryableRefusal = plan.errorCode = "playback_terminal" or oversizedAVC or unsupportedHLS
        stoppedOwner = TaskSiloStartStopAcknowledged(decision,cleanup,acknowledgment,revision,retryOwner,retryRequestId)
        ' Closure of this exact owner remains true even if a malformed terminal
        ' cannot authorize the Task's automatic retry.
        if stoppedOwner then rejected["cleanupLeaseClosed"] = true
        if plan.errorCode = "playback_terminal" and not TaskSiloStartTerminal(decision,true) then stoppedOwner = false
        ' Native V2 Start documents 201; retain legacy 200 without widening to all 2xx.
        startStatusSupported = response.statusCode = 200 or response.statusCode = 201
        noClientLease = startStatusSupported and TaskSiloStartTerminal(decision)
        retryAuthority = startStatusSupported and (stoppedOwner or noClientLease)
        if retryableRefusal and not retryAuthority then rejected["leaseUncertain"] = true
        canRetry = params.DoesExist("detail") and retryableRefusal and retryAuthority
        if canRetry
            if retryOwner <> invalid
                if not SoScopeEqual(retryOwner,SpScope(m.top.job)) or SpField(m.top.job,"requestId") <> retryRequestId then rejected["errorCode"] = "session_changed":return rejected
            end if
            if not TaskSiloApprovalIdentityCurrent(retryIdentity,revision) then rejected["errorCode"] = "session_changed":return rejected
            if m.top.cancelled = true then rejected["errorCode"] = "cancelled":return rejected
        end if
        if canRetry and nativeAudioIndex = invalid and not params.DoesExist("audioTrackId") and not params.DoesExist("audioTrackIndex")
            file = SiloPlaybackFile(freshDetail,TaskString(session,"sourceId"),TaskString(params,"itemId"),fileId,TaskValue(params,"startPositionMs",0))
            if file <> invalid
                alternate = TaskSiloUnambiguousAudio(file.version,device,context)
                if alternate <> invalid then return TaskStartSiloPlayback(session,params,revision,alternate.index,attempts)
            end if
        end if
        fallbackMaximum = TaskString(clientCapabilities,"max_resolution")
        ' A rejected HEVC Main probe can omit the global ceiling even when
        ' AVC HLS and the 4K output are known. Select the SDR fallback locally;
        ' this does not grant Main support or widen the advertised context.
        if fallbackMaximum = "" and SiloContains(SiloList(context.deliveries.hls.video_codecs),"h264")
            if Left(LCase(TaskSiloVideoMode(device)),5) = "2160p" then fallbackMaximum = "1080p"
        end if
        fallbackQuality = SiloFallbackQuality(TaskString(params,"qualityPreference"),fallbackMaximum)
        if canRetry and params.qualityExplicit = false and fallbackQuality <> ""
            if nativeSelection.allowedFileIds.Count() <= 1 and SiloContains(SiloList(context.deliveries.hls.video_codecs),"h264")
                retryParams = SpCopy(params)
                retryParams.qualityPreference = fallbackQuality
                return TaskStartSiloPlayback(session,retryParams,revision,nativeAudioIndex,attempts)
            end if
        end if
        if canRetry and autoNative and nativeSelection.allowedFileIds.Count() > 1
            retryParams = SpCopy(params)
            retryParams["excludedVersionIds"] = SpCopy(excluded)
            retryParams.excludedVersionIds.Push(fileId)
            return TaskStartSiloPlayback(session,retryParams,revision,invalid,attempts)
        end if
        if plan.errorCode = "playback_terminal" or plan.errorCode = "unsupported_stream"
            rejected["report"] = {installationId:installationId,playbackAttemptId:attemptId}
        end if
        return rejected
    end if
    if lastStereo <> invalid then if not TaskSiloLastStereoReceipt(decision) then return TaskRejectSiloPlayback(session,cleanup,"invalid_response",revision)
    if audioProjection <> invalid then if not TaskSiloAudioProjectionReceipt(decision,audioProjection) then return TaskRejectSiloPlayback(session,cleanup,"invalid_response",revision)
    if mp4 <> invalid then if not TaskSiloMp4Receipt(decision,mp4.proof) then return TaskRejectSiloPlayback(session,cleanup,"invalid_response",revision)
    subtitleReceipt = SiloSelectedSubtitleReceipt(decision.playback_plan,session.baseUrl,TaskString(decision,"session_id"))
    if subtitleReceipt.ok <> true
        plan["selectedSubtitle"] = {kind:"unsupported",renderingReady:false}
    else if subtitleReceipt.public <> invalid
        plan["selectedSubtitle"] = subtitleReceipt.public
    end if
    if requireSubtitleOff
        if not SiloSubtitleOffReceipt(decision.playback_plan) then return TaskRejectSiloPlayback(session,cleanup,"invalid_response",revision)
    end if
    if experimental and TaskString(decision.playback_plan,"delivery") <> "original_http" then return TaskRejectSiloPlayback(session,cleanup,"invalid_original_receipt",revision)
    if expectedExplicitAudio <> invalid
        returnedAudio = SpField(SpField(decision.playback_plan,"selected_tracks"),"audio")
        if SpField(returnedAudio,"index") <> expectedExplicitAudio.index or SpField(returnedAudio,"id") <> expectedExplicitAudio.id then return TaskSiloRejectStartValidation(session,cleanup,"invalid_response",revision,decision,requestFacts,response.statusCode,summary,"audio_selection","audio_mismatch")
    end if
    if originalCandidate <> invalid
        returnedAudio = SpField(SpField(decision.playback_plan,"selected_tracks"),"audio")
        expectedAudio = originalCandidate.proof.audioIdentity
        if SpField(returnedAudio,"index") <> expectedAudio.index or SpField(returnedAudio,"id") <> expectedAudio.id then return TaskSiloRejectStartValidation(session,cleanup,"invalid_original_receipt",revision,decision,requestFacts,response.statusCode,summary,"audio_selection","audio_mismatch")
    end if
    if not TaskSiloDecisionIdentity(decision,fileId,"",selection.allowedFileIds) then print "Silo playback rejected step=5" : return TaskRejectSiloPlayback(session,cleanup,"invalid_response",revision)
    if not TaskPlaybackOpaqueId(TaskString(plan, "sessionId")) then print "Silo playback rejected step=6" : return TaskRejectSiloPlayback(session, cleanup, "invalid_response", revision)
    if SessionRevision("silo") <> revision then return TaskRejectSiloPlayback(session, cleanup, "session_changed", revision)
    if not TaskSiloApplyMediaAuth(plan,session,TaskValue(params,"mediaAuthMode",invalid),SpField(SpField(decision.playback_plan,"stream"),"url")) then return TaskSiloRejectStartValidation(session,cleanup,"invalid_response",revision,decision,requestFacts,response.statusCode,summary,"media_auth","invalid_media_auth")
    plan["playbackDiagnostics"] = TaskSiloPlaybackDiagnostics(decision.playback_plan)
    plan["installationId"] = installationId
    plan["relativeTimeline"] = true
    plan["sourceId"] = TaskString(session, "sourceId")
    plan["itemId"] = TaskString(params, "itemId")
    target = TaskValue(params,"startPositionMs",plan.startPositionMs+plan.timelineOffsetMs)
    if not TaskSiloSetTarget(plan,decision,target) then print "Silo playback rejected step=7" : return TaskRejectSiloPlayback(session,cleanup,"invalid_response",revision)
    if TaskString(decision.playback_plan,"decision_reason") = "client_managed_dynamic_range" and originalCandidate = invalid then return TaskRejectSiloPlayback(session,cleanup,"invalid_original_receipt",revision)
    if TaskString(decision.playback_plan,"delivery") = "original_http" and originalCandidate <> invalid
        checkedOriginal = TaskSiloOriginalDescriptor(originalCandidate,decision,plan,originalScope)
        if checkedOriginal.ok <> true then return TaskSiloRejectStartValidation(session,cleanup,"invalid_original_receipt",revision,decision,requestFacts,response.statusCode,summary,"original_receipt",SpField(checkedOriginal,"reason"))
        plan["originalPlayback"] = checkedOriginal.descriptor
        if experimental then plan["experimentalOriginal"] = true
    end if
    if privateLegacy
        currentProof = TaskSiloLegacyHDR10Proof(freshWire,fileId,params,device,TaskRokuSiloCapabilities(device),revision)
        if currentProof = invalid then return TaskRejectSiloPlayback(session,cleanup,"session_changed",revision)
        if currentProof.snapshot.outputFingerprint <> legacyProof.snapshot.outputFingerprint then return TaskRejectSiloPlayback(session,cleanup,"session_changed",revision)
        plan["privateLegacyHdr10"] = {route:legacyProof.route,audioAcceptance:"unqualified",outputFingerprint:legacyProof.snapshot.outputFingerprint,scope:legacyProof.scope,requestId:legacyProof.requestId}
    end if
    retained = TaskSiloPlanContext(plan,decision,session,params,revision,attemptId)
    if privateLegacy and retained = invalid then return TaskRejectSiloPlayback(session,cleanup,"invalid_response",revision)
    if (lastStereo <> invalid or params.DoesExist("mediaAuthMode")) and retained = invalid then return TaskSiloRejectStartValidation(session,cleanup,"invalid_response",revision,decision,requestFacts,response.statusCode,summary,"plan_context","invalid_plan_context")
    if requireSubtitleOff
        if retained = invalid then return TaskRejectSiloPlayback(session,cleanup,"invalid_response",revision)
        retained["subtitleOffRequired"] = true
    end if
    if retained <> invalid
        if params.originalDisabled = true then retained["originalDisabled"] = true
        plan["siloPlayback"] = retained
    end if
    TaskSiloRetainSeek(plan,decision,SpField(startResult,"requestBody"),capability.data.features,originalScope)
    decoded = DecodeSiloResponse("playback_start", response.body, {})
    if decoded.ok <> true then return TaskRejectSiloPlayback(session, cleanup, TaskString(decoded, "errorCode"), revision)
    data = TaskValue(decoded, "data", {})
    data["sessionId"] = TaskString(plan, "sessionId")
    if level50 <> invalid then plan["sourceHDR10Projection"] = SpCopy(level50.proof)
    subtitleFromReplan = false
    if params.DoesExist("detail")
        effective = SiloPlaybackFile(freshDetail,plan.sourceId,plan.itemId,plan.versionId,target)
        if effective = invalid then return TaskRejectSiloPlayback(session,cleanup,"invalid_response",revision)
        data["playbackDetail"] = freshDetail
        data["effectiveMarkers"] = effective.version.markers
        if lastStereo = invalid and retained <> invalid and originalCandidate = invalid and not params.DoesExist("audioTrackId") and not params.DoesExist("audioTrackIndex")
            alternateAudio = TaskSiloCompatibleAudio(effective.version,retained.selectedTracks.audio,device,context)
            if alternateAudio <> invalid
                scope = {provider:"silo",sourceId:plan.sourceId,profileId:retained.profileId,generation:0}
                audioParams = {sessionId:plan.sessionId,plan:plan,qualityPreference:retained.qualityPreference,positionMs:target,replanRequestId:TaskUniqueId()}
                adjusted = TaskReplanSiloPlayback(session,audioParams,scope,revision,freshDetail)
                if adjusted.ok <> true then return TaskRejectSiloPlayback(session,cleanup,TaskString(adjusted,"errorCode"),revision)
                plan = adjusted.plan
                subtitleFromReplan = true
            end if
        end if
    end if
    if audioProjection <> invalid then plan["sourceAudioProjection"] = SpCopy(audioProjection.proof)
    if level50 <> invalid then plan["sourceHDR10Projection"] = SpCopy(level50.proof)
    plan["allowQualityFallback"] = params.qualityExplicit = false and not experimental
    if autoNative and params.DoesExist("detail")
        request = {itemId:plan.itemId,fileId:plan.versionId,detail:SpCopy(freshDetail),autoVersion:true,excludedVersionIds:SpCopy(excluded)}
        for each name in ["qualityPreference","qualityExplicit","bandwidthCapKbps","subtitleMode","subtitleOffRequired","mediaAuthMode"]
            if params.DoesExist(name) then request[name] = params[name]
        end for
        plan["autoVersionRequest"] = request
    end if
    if not subtitleFromReplan then TaskSiloRememberSelectedSubtitle(plan,subtitleReceipt,session,revision,decision.playback_plan)
    plan["startRequestFacts"] = requestFacts
    output = {ok: true, data: data, plan: plan}
    if params.DoesExist("audioTrackIndex") and SiloObject(freshDetail)
        output["audioPreference"] = SiloAudioPreference(freshDetail.item,plan.versionId,params.audioTrackIndex,freshDetail.versions)
    end if
    return output
end function

' Header-auth attempts remain on exact API-owned session routes. A future
' authorized-media-origin protocol needs separate admission and is not enabled.
function TaskSiloApplyMediaAuth(plan as Object, session as Object, mode as Dynamic, rawUrl as Dynamic) as Boolean
    if mode = invalid then return true
    if not SpText(mode,32) or mode <> "api_header_v1" then return false
    if not SpText(rawUrl,2048) then return false
    if rawUrl <> rawUrl.Trim() then return false
    url = TaskString(plan,"url")
    if not SpText(url,2048) or Instr(1,url,"#") > 0 then return false
    if SiloResolveUrl(rawUrl,TaskString(session,"baseUrl")) <> url then return false
    if not SiloHeaderMediaUrlAllowed(url,TaskString(session,"baseUrl"),TaskString(plan,"sessionId"),TaskString(plan,"versionId")) then return false
    token = SpField(session,"accessToken")
    if not SpText(token,4096) then return false
    if token <> token.Trim() then return false
    plan["headers"] = {"Authorization":"Bearer " + token}
    return true
end function

' Explicit quality limits are bounded at the worker boundary. Omitted options
' keep the foreground defaults; preview intent never becomes a provider field.
function TaskPlaybackOptionsValid(provider as String, params as Object) as Boolean
    if provider = "plex"
        if params.DoesExist("maxVideoBitrate")
            if not TaskPlaybackBandwidthValid(params.maxVideoBitrate) then return false
        end if
        if params.DoesExist("videoResolution")
            resolution = TaskString(params, "videoResolution")
            if not CreateObject("roRegex", "^[0-9]{1,4}x[0-9]{1,4}$", "").IsMatch(resolution) then return false
            dimensions = resolution.Tokenize("x")
            width = Val(dimensions[0])
            height = Val(dimensions[1])
            if width < 1 or width > 3840 or height < 1 or height > 2160 then return false
        end if
    else
        if params.DoesExist("mediaAuthMode")
            if TaskString(params,"mediaAuthMode") <> "api_header_v1" then return false
        end if
        if params.DoesExist("subtitleOffRequired")
            if not SpBool(params.subtitleOffRequired) then return false
            if params.subtitleOffRequired
                if params.subtitleMode <> "off" or params.DoesExist("subtitleTrackId") or params.DoesExist("subtitleTrackIndex") then return false
            end if
        end if
        if params.DoesExist("experimentalOriginal")
            if not SpBool(params.experimentalOriginal) then return false
        end if
        if params.DoesExist("subtitleTrackIndex")
            if not SpNumber(params.subtitleTrackIndex,10000,true) then return false
        end if
        if params.DoesExist("bandwidthCapKbps")
            if not TaskPlaybackBandwidthValid(params.bandwidthCapKbps) then return false
        end if
        if params.DoesExist("qualityPreference")
            if not SiloContains(["original", "4k", "1080p_high", "1080p", "720p", "480p"], TaskString(params, "qualityPreference")) then return false
        end if
    end if
    return true
end function

function TaskPlaybackBandwidthValid(value as Dynamic) as Boolean
    kind = type(value)
    if kind <> "Integer" and kind <> "roInt" and kind <> "roInteger" and kind <> "LongInteger" and kind <> "roLongInteger" and kind <> "Float" and kind <> "roFloat" and kind <> "Double" and kind <> "roDouble" then return false
    if value < 1 or value > 200000 then return false
    return value = Int(value)
end function

' Only compact opaque identities may cross the Task boundary for a retry.
' Keep the same alphabet/length as the progress delivery session identity.
function TaskPlaybackOpaqueId(value as Dynamic) as Boolean
    if type(value) <> "String" and type(value) <> "roString" then return false
    if value = "" or Len(value) > 256 or Instr(1, value, "://") > 0 then return false
    return CreateObject("roRegex", "^[A-Za-z0-9_.:/-]+$", "").IsMatch(value)
end function

function TaskSiloCleanupPlan(decision as Object, installationId as String) as Dynamic
    sessionId = ""
    if SiloObject(decision.playback_plan) then sessionId = TaskString(decision.playback_plan, "session_id")
    if not TaskPlaybackOpaqueId(sessionId) then sessionId = TaskString(decision, "session_id")
    if not TaskPlaybackOpaqueId(sessionId) or not TaskPlaybackOpaqueId(installationId) then return invalid
    return {sessionId: sessionId, installationId: installationId, stopId: LCase(CreateObject("roDeviceInfo").GetRandomUUID()), persistProgress: false}
end function

' Presentation-only summary of the parsed rejected Start, never retry/cleanup authority.
' No raw response strings or lease values cross this boundary.
function TaskSiloStartResponseFacts(decision as Object, status as Dynamic) as Object
    facts = {httpStatus:"unknown",protocol:"invalid",outcome:"invalid",sessionId:TaskSiloStartIdFact(decision),playbackPlanPresent:decision.DoesExist("playback_plan"),playbackPlanObject:false,planSessionId:"unavailable",terminalShapeValid:TaskSiloStartTerminal(decision)}
    if SpNumber(status,599,true) then if status >= 100 then facts["httpStatus"] = status
    if not decision.DoesExist("protocol_version")
        facts.protocol = "missing"
    else if decision.protocol_version = invalid
        facts.protocol = "null"
    else if SpNumber(decision.protocol_version,2147483647,true)
        facts.protocol = "other"
        if decision.protocol_version = 3 then facts.protocol = "v3"
    end if
    if not decision.DoesExist("outcome")
        facts.outcome = "missing"
    else if decision.outcome = invalid
        facts.outcome = "null"
    else if type(decision.outcome) = "String" or type(decision.outcome) = "roString"
        facts.outcome = "other"
        for each allowed in ["plan","playable","terminal","adaptation_unavailable"]
            if decision.outcome = allowed then facts.outcome = allowed:exit for
        end for
    end if
    rawPlan = SpField(decision,"playback_plan")
    if SiloObject(rawPlan)
        facts["playbackPlanObject"] = true
        facts["planSessionId"] = TaskSiloStartIdFact(rawPlan)
    end if
    return facts
end function

function TaskSiloStartIdFact(parent as Object) as String
    if not parent.DoesExist("session_id") then return "missing"
    raw = parent.session_id
    if raw = invalid then return "null"
    if type(raw) = "String" or type(raw) = "roString"
        if raw = "" then return "empty"
    end if
    if TaskPlaybackOpaqueId(raw) then return "valid"
    return "invalid"
end function

' Current V3 terminals assert no client lease; legacy lease-bearing terminals
' require a real stop ACK instead. Unknown additive features remain harmless.
function TaskSiloStartTerminal(decision as Object, allowLease = false as Boolean) as Boolean
    if not SpNumber(SpField(decision,"protocol_version"),3,true) or decision.protocol_version <> 3 then return false
    if decision.outcome <> "adaptation_unavailable"
        if not allowLease or decision.outcome <> "terminal" then return false
    end if
    if decision.DoesExist("playback_plan") then return false
    if not allowLease and decision.DoesExist("session_id") then return false
    features = SpField(decision,"server_features")
    if not SiloArray(features) then return false
    for each feature in features
        if type(feature) <> "String" and type(feature) <> "roString" then return false
    end for
    terminal = SpField(decision,"terminal")
    if not SiloObject(terminal) then return false
    reason = SpField(terminal,"reason"):message = SpField(terminal,"message")
    if type(reason) <> "String" and type(reason) <> "roString" then return false
    if reason = "" then return false
    if type(message) <> "String" and type(message) <> "roString" then return false
    return SpBool(SpField(terminal,"retryable"))
end function

function TaskSiloStartStopAcknowledged(decision as Object, cleanup as Dynamic, ack as Object, revision as Integer, owner as Dynamic, requestId as Dynamic) as Boolean
    if cleanup = invalid or SpField(ack,"state") <> "acknowledged" then return false
    if owner = invalid or not SoScopeEqual(owner,SpField(ack,"owner")) then return false
    if SpField(ack.owner,"sessionRevision") <> revision or ack.requestId <> requestId then return false
    for each name in ["sessionId","installationId","stopId"]
        if SpField(ack,name) <> SpField(cleanup,name) then return false
    end for
    return TaskSiloStartCleanupIdentity(decision,cleanup)
end function

' Identity consistency alone is not an ACK and never authorizes Start retry.
function TaskSiloStartCleanupIdentity(decision as Object, cleanup as Dynamic) as Boolean
    if not SiloObject(cleanup) then return false
    if not TaskPlaybackOpaqueId(SpField(cleanup,"sessionId")) or not TaskPlaybackOpaqueId(SpField(cleanup,"installationId")) then return false
    if decision.DoesExist("session_id")
        if decision.session_id <> cleanup.sessionId then return false
    end if
    raw = SpField(decision,"playback_plan")
    if SiloObject(raw)
        if raw.DoesExist("session_id") then if raw.session_id <> cleanup.sessionId then return false
    end if
    return true
end function


function TaskSiloRejectStartValidation(session as Object, cleanup as Dynamic, code as String, revision as Integer, decision as Object, requestFacts as Dynamic, status as Dynamic, summary as Dynamic, stage as String, reason as Dynamic) as Object
    validation = SiloStartValidationFacts(stage,reason)
    if validation <> invalid and SiloObject(summary)
        summary["validationStage"] = validation.validationStage
        summary["validationReason"] = validation.validationReason
    end if
    failure = TaskRejectSiloPlayback(session,cleanup,code,revision)
    failure["startRequestFacts"] = SiloStartRequestFacts(requestFacts)
    failure["startResponseFacts"] = TaskSiloStartResponseFacts(decision,status)
    return failure
end function

function TaskRejectSiloPlayback(session as Object, cleanup as Dynamic, code as String, revision as Integer, decision = invalid as Dynamic, acknowledgment = invalid as Dynamic) as Object
    failure = SiloPlaybackFailureDetails(TaskError(code),decision,"start")
    privateAllocation = m.siloPrivateLegacyAllocation
    if SiloObject(privateAllocation) and not SiloObject(acknowledgment) then acknowledgment = {}
    if cleanup = invalid then return failure
    ' Abandon through the same receipt validation as normal stop. No final
    ' sample is authorized for a plan that never reached native playback.
    try
        abandoned = TaskPlaybackEvent("silo", session, "playback_stop", MergeSessionPatch({}, cleanup), revision)
    catch exception
        failure["plan"] = cleanup
        if SiloObject(privateAllocation)
            failure["leaseUncertain"] = true
            if TaskSiloStartCleanupIdentity(privateAllocation.decision,cleanup) and TaskPlaybackOpaqueId(SpField(cleanup,"stopId")) then failure["cleanupLeaseKnown"] = true
        end if
        return failure
    end try
    if abandoned.ok <> true
        failure["plan"] = cleanup
    else if SiloObject(acknowledgment)
        if m.top <> invalid
            job = m.top.job:owner = SpScope(job)
            if owner <> invalid
                owner["sessionRevision"] = revision
                acknowledgment["state"] = "acknowledged"
                acknowledgment["owner"] = owner:acknowledgment["requestId"] = job.requestId
                for each name in ["sessionId","installationId","stopId"]
                    acknowledgment[name] = cleanup[name]
                end for
            end if
        end if
    end if
    if SiloObject(privateAllocation)
        closed = TaskSiloStartStopAcknowledged(privateAllocation.decision,cleanup,acknowledgment,privateAllocation.revision,privateAllocation.owner,privateAllocation.requestId)
        if closed
            failure["cleanupLeaseClosed"] = true
        else
            failure["leaseUncertain"] = true
            if SiloObject(SpField(failure,"plan")) and TaskSiloStartCleanupIdentity(privateAllocation.decision,cleanup) then failure["cleanupLeaseKnown"] = true
        end if
    end if
    return failure
end function


' The public result has only the server image origin. Credentials remain inside
' a native HTTP agent attached to an unattached node, never in an AA field.
function TaskPlexImageContext(session as Object, revision as Integer) as Object
    base = PlexBaseUrl(TaskValue(session, "baseUrl", ""), TaskValue(session, "local", false))
    token = TaskString(session, "token")
    if base = "" or token = "" then return TaskError("auth_required")
    if SessionRevision("plex") <> revision then return TaskError("session_changed")
    holder = TaskPlexImageHolder(token)
    if holder = invalid then return TaskError("image_agent_failed")
    if SessionRevision("plex") <> revision then return TaskError("session_changed")
    m.top.imageHolder = holder
    return {ok: true, data: {imageBaseUrl: base}}
end function

function TaskPlexImageHolder(token as String) as Dynamic
    holder = CreateObject("roSGNode", "Group")
    agent = CreateObject("roHttpAgent")
    agent.SetCertificatesFile("common:/certs/ca-bundle.crt")
    agent.AddHeader("X-Plex-Token", token)
    if not holder.SetHttpAgent(agent) then return invalid
    return holder
end function

' Best-effort telemetry never refreshes authentication or retries a failed POST.
function TaskSiloPlaybackErrorReport(session as Object, params as Object, scope as Object, revision as Integer) as Object
    dropped = {ok:true,data:{reported:false}}
    if not TaskPreviewScopeMatches("silo",LoadSession("silo"),scope,revision) then return TaskError("session_changed")
    for each key in params
        if not SiloContains(["report","supportCode","errorCode","reason"],key) then return TaskError("invalid_request")
    end for
    requestParams = MergeSessionPatch(params,{eventId:LCase(CreateObject("roDeviceInfo").GetRandomUUID())})
    request = BuildSiloRequest("playback_error_report",session,requestParams)
    if request.ok <> true then return TaskError(TaskString(request,"errorCode"))
    try
        response = HttpRequest(request,3000)
    catch exception
        return dropped
    end try
    if not TaskPreviewScopeMatches("silo",LoadSession("silo"),scope,revision) then return TaskError("session_changed")
    if response.ok <> true or TaskValue(response,"statusCode",0) <> 202 then return dropped
    decoded = DecodeSiloResponse("playback_error_report",TaskString(response,"body"),requestParams)
    if decoded.ok <> true then return dropped
    return decoded
end function


' Hold the final receipt on this Task only; automatic audio replans replace it
' before the single optional fetch at the job's publication boundary.
sub TaskSiloRememberSelectedSubtitle(plan as Object, receipt as Object, session as Object, revision as Integer, rawPlan as Object)
    ' Validate before retaining any optional source inventory. Raw rows can
    ' contain arbitrarily large private extensions; never recursively copy them.
    scope = {provider:"silo",sourceId:TaskString(plan,"sourceId"),profileId:TaskString(SpField(plan,"siloPlayback"),"profileId"),generation:0}
    projected = SiloSourceSubtitleInventory(rawPlan,plan,scope)
    inventoryPlan = invalid
    if projected <> invalid
        rows = []
        for each entry in projected.entries
            rows.Push({track_id:entry.trackId,combined_index:entry.combinedIndex,source:entry.source,codec:entry.codec,
                language:entry.language,label:entry.label,forced:entry.forced,default:entry.default,
                hearing_impaired:entry.hearingImpaired,delivery:entry.delivery})
        end for
        owner = projected.owner
        inventoryPlan = {effective_media_file_id:owner.fileId,plan_id:owner.planId,plan_attempt_key:owner.planAttemptKey,
            session_id:owner.sessionId,subtitle:{inventory:rows}}
    end if
    m.siloSubtitlePending = {inventoryPlan:inventoryPlan,receipt:receipt,session:session,revision:revision,
        sessionId:TaskString(plan,"sessionId"),fileId:TaskString(plan,"versionId"),
        planAttemptKey:TaskString(plan,"planAttemptKey")}
end sub

function TaskSiloPrepareSelectedSubtitle(outcome as Object, job as Object) as Object
    if outcome.ok <> true or type(outcome.plan) <> "roAssociativeArray" then return outcome
    pending = m.siloSubtitlePending
    m.siloSubtitlePending = invalid
    if type(pending) <> "roAssociativeArray" then return outcome
    plan = outcome.plan
    if pending.sessionId <> TaskString(plan,"sessionId") or pending.fileId <> TaskString(plan,"versionId") or pending.planAttemptKey <> TaskString(plan,"planAttemptKey") then return outcome
    inventory = SiloSourceSubtitleInventory(pending.inventoryPlan,plan,job)
    if inventory <> invalid then plan["sourceSubtitleInventory"] = inventory
    selected = TaskValue(plan,"selectedSubtitle",invalid)
    if type(selected) <> "roAssociativeArray" then return outcome
    if selected.kind <> "sidecar_pending" then return outcome
    ' Video can be valid without replan context. Do not allocate a file that
    ' the Scene cannot adopt or retire under the same immutable owner.
    if SiloPlaybackContext(plan,job) = invalid
        selected["kind"] = "unsupported"
        selected["renderingReady"] = false
        return outcome
    end if
    owner = {sourceId:TaskString(job,"sourceId"),profileId:TaskString(job,"profileId"),
        generation:TaskValue(job,"generation",invalid),requestId:TaskValue(job,"requestId",invalid),
        sessionRevision:pending.revision,sessionId:pending.sessionId,fileId:pending.fileId,
        planAttemptKey:pending.planAttemptKey,selectedOrdinal:selected.combinedIndex,
        timelineOffsetMs:TaskValue(plan,"timelineOffsetMs",0)}
    try
        if SpField(plan.siloPlayback,"mediaAuthMode") = "api_header_v1" and selected.format = "vtt"
            artifact = {ok:false,errorCode:"cancelled"}
            if SiloSubtitleCurrent(owner,pending.session)
                prepared = SiloSubtitleTransportPlan(pending.receipt,pending.session,owner,plan)
                if not SiloSubtitleCurrent(owner,pending.session) then prepared = {ok:false,errorCode:"cancelled"}
                if prepared.ok = true
                    plan["subtitleTransport"] = prepared.transport
                    return outcome
                end if
                artifact = prepared
            end if
        else
            artifact = TaskSiloSubtitleFetch(pending.receipt,pending.session,owner)
        end if
    catch exception
        artifact = {ok:false,errorCode:"task_failed"}
    end try
    if artifact.ok = true
        ' Record only this Task's actual completed file for pre-publication
        ' retirement. No request-supplied or previous-plan path is adopted.
        if m.siloRecoveryBudget <> invalid then m.siloRecoveryArtifact = {uri:artifact.uri,owner:SpCopy(artifact.owner)}
        plan["subtitleArtifact"] = {uri:artifact.uri,format:artifact.format,mimeType:artifact.mimeType,
            timingOriginSeconds:artifact.timingOriginSeconds,owner:artifact.owner}
        selected["kind"] = "sidecar_ready"
        selected["renderingReady"] = true
    else
        selected["kind"] = "fetch_failed"
        selected["renderingReady"] = false
        selected["errorCode"] = TaskString(artifact,"errorCode")
    end if
    return outcome
end function

' Snapshot the final source and selectors immediately before this attempt's POST.
function TaskSiloStartRequestFacts(detail as Dynamic, session as Object, params as Object, fileId as String, request as Object, capabilities as Object, context as Object) as Dynamic
    facts = {quality:"unknown",selection:"manual",videoCodec:"unknown",audioCodec:"unknown",hdr10:"unknown",dolbyVision:"unknown"}
    if SpField(params,"autoVersion") = true then facts.selection = "auto"
    quality = SpField(request,"qualityPreference")
    if SiloContains(["auto","original","2160p","1080p","720p","480p"],quality) then facts.quality = quality
    file = SiloPlaybackFile(detail,TaskString(session,"sourceId"),TaskString(params,"itemId"),fileId,0)
    if file <> invalid
        version = file.version
        if SiloContains(["h264","hevc","av1","vp9","mpeg2","mpeg4"],SpField(version,"videoCodec")) then facts.videoCodec = version.videoCodec
        videos = SpField(version,"videoTracks")
        if SiloArray(videos)
            if videos.Count() = 1
                video = videos[0]
                for each key in ["width","height"]
                    value = SpField(video,key)
                    if SpNumber(value,16384,true) and value > 0 then facts[key] = value
                end for
                if SpField(video,"dv_config_present") = true
                    if SpNumber(SpField(video,"dv_profile"),15,true) then facts["dvProfile"] = video.dv_profile
                    if SpField(video,"dv_bl_compat_id_present") = true and SpField(video,"dv_bl_present") = true
                        if SpNumber(SpField(video,"dv_bl_compat_id"),15,true) then facts["dvBaseCompatibility"] = video.dv_bl_compat_id
                    end if
                end if
            end if
        end if
        tracks = SpField(version,"audioTracks"):index = SpField(request,"audioTrackIndex")
        if SiloArray(tracks) and SpNumber(index,31,true)
            if index < tracks.Count()
                codec = SpField(tracks[index],"codec")
                if SiloContains(["aac","ac3","eac3","truehd","dts","flac","opus","mp3","pcm"],codec) then facts.audioCodec = codec
            end if
        end if
    end if
    hdr = SpField(capabilities,"hdr_details")
    if SpBool(SpField(hdr,"hdr10"))
        facts.hdr10 = "no"
        if hdr.hdr10 then facts.hdr10 = "yes"
    end if
    profiles = SpField(hdr,"dolby_vision_profiles")
    if SiloArray(profiles)
        facts.dolbyVision = "no"
        if profiles.Count() > 0 then facts.dolbyVision = "yes"
    end if
    features = SiloNativeDeliveryFeatures(context)
    facts["copyMpegts"] = SiloContains(features,"hls_copy_mpegts_v1")
    facts["mpegts"] = SiloContains(features,"native_hls_mpegts_v1")
    facts["separateAudio"] = SiloContains(features,"native_hls_separate_audio_v1")
    facts["dv7To81"] = SiloContains(features,"server_dv7_to_dv81_v1")
    facts["hevcAdmitted"] = SiloContains(SiloList(capabilities.codecs_video),"hevc")
    facts["hlsHevcAdmitted"] = SiloContains(SiloList(context.deliveries.hls.video_codecs),"hevc")
    facts["hlsEnabled"] = context.deliveries.hls.enabled = true
    facts["hlsSupported"] = context.deliveries.hls.supported_on_device = true
    facts["originalEnabled"] = context.deliveries.original_http.enabled = true
    facts["originalSupported"] = context.deliveries.original_http.supported_on_device = true
    return SiloStartRequestFacts(facts)
end function
