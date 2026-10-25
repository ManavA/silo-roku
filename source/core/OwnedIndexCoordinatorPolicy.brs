' Keep account/session scope, manifests and shards in Task memory; only finite
' OwnedIndexTask page jobs cross the worker interface. The caller owns discovery,
' unique run IDs, execution, readback, cancellation and orphan cleanup.
' Terminal covers supplied section windows; it never proves authoritative absence.
function OwnedIndexCoordinatorStart(rawScope as Dynamic, discovery as Dynamic, now as Integer) as Dynamic
    scope = OwnedIndexCoordinatorScope(rawScope)
    if scope = invalid then return invalid
    if type(discovery) <> "roAssociativeArray" then return invalid
    rawSections = OwnedIndexField(discovery, "sections")
    if type(rawSections) <> "roArray" then return invalid
    truncated = OwnedIndexField(discovery, "truncated")
    if not OwnedIndexCoordinatorBoolean(truncated) then return invalid
    sections = []
    seen = {}
    for each raw in rawSections
        if sections.Count() >= 24 then exit for
        if type(raw) <> "roAssociativeArray" then return invalid
        libraryId = OwnedIndexText(raw, "libraryId")
        sectionId = OwnedIndexText(raw, "sectionId")
        if libraryId = "" then libraryId = sectionId
        if sectionId <> "" and libraryId <> sectionId then return invalid
        if not CreateObject("roRegex", "^[A-Za-z0-9_-]{1,64}$", "").IsMatch(libraryId) then return invalid
        kind = OwnedIndexText(raw, "type")
        if kind <> "movie" and kind <> "show" then return invalid
        if OwnedIndexHasField(raw, "sourceId")
            if OwnedIndexText(raw, "sourceId") <> scope.sourceId then return invalid
        end if
        if seen.DoesExist(libraryId) then return invalid
        seen[libraryId] = true
        sections.Push({libraryId: libraryId, type: kind, status: "pending", nextOffset: 0, pages: 0, errorCode: ""})
    end for
    ' Plex's existing section adapter stops at 24 without proving discovery ended.
    truncated = truncated or rawSections.Count() >= 24
    created = OwnedIndexManifestCreate(scope, now)
    if OwnedIndexField(created, "ok", false) <> true then return invalid
    state = {schema: 1, scope: scope, manifest: created.manifest, sections: sections, sectionIndex: 0, inFlight: invalid, dispatchedPages: 0, nextRequestId: 1, partial: truncated, sectionTruncated: truncated, finished: false, status: "ready", errorCode: "", authoritativeAbsence: false, sourceInventoryComplete: false}
    if sections.Count() = 0 then state = OwnedIndexCoordinatorFinish(state, "")
    return state
end function

function OwnedIndexCoordinatorTake(state as Dynamic, currentScope as Dynamic, activity as Dynamic, now as Integer) as Object
    empty = {state: state, job: invalid, cancelRequestId: invalid}
    if not OwnedIndexCoordinatorValidState(state) then return empty
    if not OwnedIndexCoordinatorScopeMatches(state.scope, currentScope)
        stopped = OwnedIndexCoordinatorCancel(state, "session_changed")
        return {state: stopped.state, job: invalid, cancelRequestId: stopped.cancelRequestId}
    end if
    if state.finished then return empty
    if not OwnedIndexCoordinatorIdle(activity)
        paused = ParseJson(FormatJson(state))
        cancelId = invalid
        if type(paused.inFlight) = "roAssociativeArray" then cancelId = paused.inFlight.requestId
        paused["inFlight"] = invalid
        paused.status = "paused"
        return {state: paused, job: invalid, cancelRequestId: cancelId}
    end if
    if type(state.inFlight) = "roAssociativeArray" then return empty
    valid = OwnedIndexManifestValidate(state.manifest, state.scope, now)
    if OwnedIndexField(valid, "ok", false) <> true
        return {state: OwnedIndexCoordinatorFinish(state, "invalid_manifest"), job: invalid, cancelRequestId: invalid}
    end if
    quota = OwnedIndexManifestQuota(state.manifest, 65536)
    if OwnedIndexField(quota, "ok", false) <> true or OwnedIndexField(quota, "canWrite", false) <> true
        return {state: OwnedIndexCoordinatorFinish(state, "manifest_budget"), job: invalid, cancelRequestId: invalid}
    end if
    if state.dispatchedPages >= 200
        return {state: OwnedIndexCoordinatorFinish(state, "page_budget"), job: invalid, cancelRequestId: invalid}
    end if
    if state.sectionIndex >= state.sections.Count()
        return {state: OwnedIndexCoordinatorFinish(state, ""), job: invalid, cancelRequestId: invalid}
    end if
    nextState = ParseJson(FormatJson(state))
    section = nextState.sections[nextState.sectionIndex]
    job = {provider: "plex", sourceId: state.scope.sourceId, profileId: state.scope.profileId, inventoryRunId: state.scope.inventoryRunId, libraryId: section.libraryId, offset: section.nextOffset, limit: 48, requestId: state.nextRequestId, writeShard: true}
    if not OwnedIndexValidJob(job)
        return {state: OwnedIndexCoordinatorFinish(state, "page_budget"), job: invalid, cancelRequestId: invalid}
    end if
    nextState["inFlight"] = job
    nextState["nextRequestId"] += 1
    nextState["dispatchedPages"] += 1
    nextState.status = "running"
    nextState.sections[nextState.sectionIndex].status = "scanning"
    return {state: nextState, job: job, cancelRequestId: invalid}
end function

function OwnedIndexCoordinatorComplete(state as Dynamic, currentScope as Dynamic, result as Dynamic, shardBody as Dynamic, now as Integer) as Object
    empty = {state: state, accepted: false, cancelRequestId: invalid}
    if not OwnedIndexCoordinatorValidState(state) then return empty
    if not OwnedIndexCoordinatorScopeMatches(state.scope, currentScope)
        stopped = OwnedIndexCoordinatorCancel(state, "session_changed")
        return {state: stopped.state, accepted: false, cancelRequestId: stopped.cancelRequestId}
    end if
    if state.finished then return empty
    if type(state.inFlight) <> "roAssociativeArray" then return empty
    job = state.inFlight
    if not OwnedIndexCoordinatorCorrelated(job, result) then return empty
    nextState = ParseJson(FormatJson(state))
    nextState["inFlight"] = invalid
    nextState.status = "ready"
    failure = ""
    if not OwnedIndexKeys(result, ["provider", "sourceId", "profileId", "inventoryRunId", "libraryId", "offset", "requestId", "status", "persistent", "page", "shardUri", "shardBytes", "errorCode"])
        failure = "invalid_response"
    else if OwnedIndexText(result, "status") <> "page"
        failure = OwnedIndexCoordinatorError(OwnedIndexText(result, "errorCode"), "invalid_response")
    else if not OwnedIndexCoordinatorBoolean(OwnedIndexField(result, "persistent"))
        failure = "invalid_response"
    else if result.persistent <> true
        failure = "storage_error"
    else
        page = OwnedIndexField(result, "page")
        if not OwnedIndexValidPage(page, job)
            failure = "invalid_response"
        else if not OwnedIndexCoordinatorPageBodyMatches(page, shardBody)
            failure = "invalid_shard"
        else
            appended = OwnedIndexManifestAppend(state.manifest, job, shardBody, OwnedIndexText(result, "shardUri"), OwnedIndexInteger(OwnedIndexField(result, "shardBytes")), now)
            if OwnedIndexField(appended, "ok", false) <> true
                failure = OwnedIndexCoordinatorError(OwnedIndexText(appended, "errorCode"), "invalid_shard")
            else
                nextState.manifest = appended.manifest
                section = nextState.sections[nextState.sectionIndex]
                section.pages += 1
                section["nextOffset"] = page.offset + page.rawCount
                if page.pageTerminal
                    section.status = "terminal"
                    nextState["sectionIndex"] += 1
                end if
            end if
        end if
    end if
    if failure = "session_changed"
        stopped = OwnedIndexCoordinatorCancel(nextState, "session_changed")
        return {state: stopped.state, accepted: true, cancelRequestId: invalid}
    end if
    if failure <> ""
        section = nextState.sections[nextState.sectionIndex]
        section.status = "partial"
        section["errorCode"] = failure
        nextState.partial = true
        nextState["errorCode"] = failure
        nextState["sectionIndex"] += 1
    end if
    if nextState.sectionIndex >= nextState.sections.Count() then nextState = OwnedIndexCoordinatorFinish(nextState, "")
    return {state: nextState, accepted: true, cancelRequestId: invalid}
end function

function OwnedIndexCoordinatorCancel(state as Dynamic, reason as String) as Object
    if not OwnedIndexCoordinatorValidState(state) then return {state: state, cancelRequestId: invalid}
    nextState = ParseJson(FormatJson(state))
    cancelId = invalid
    if type(nextState.inFlight) = "roAssociativeArray" then cancelId = nextState.inFlight.requestId
    nextState["inFlight"] = invalid
    nextState.finished = true
    nextState.partial = true
    nextState.status = "cancelled"
    nextState["errorCode"] = OwnedIndexCoordinatorError(reason, "cancelled")
    return {state: nextState, cancelRequestId: cancelId}
end function

function OwnedIndexCoordinatorFinish(state as Object, reason as String) as Object
    nextState = ParseJson(FormatJson(state))
    nextState["inFlight"] = invalid
    nextState.finished = true
    if reason <> ""
        nextState.partial = true
        nextState["errorCode"] = OwnedIndexCoordinatorError(reason, "invalid_response")
        for each section in nextState.sections
            if section.status = "pending" or section.status = "scanning"
                section.status = "partial"
                section["errorCode"] = nextState.errorCode
            end if
        end for
    end if
    nextState.status = "terminal"
    if nextState.partial then nextState.status = "partial"
    return nextState
end function

function OwnedIndexCoordinatorScope(raw as Dynamic) as Dynamic
    if type(raw) <> "roAssociativeArray" then return invalid
    scope = {}
    for each name in ["provider", "sourceId", "profileId", "accountId", "sessionRevision", "inventoryRunId"]
        scope[name] = OwnedIndexField(raw, name)
    end for
    job = {provider: scope.provider, sourceId: scope.sourceId, profileId: scope.profileId, inventoryRunId: scope.inventoryRunId, libraryId: "0", offset: 0, limit: 48, requestId: 1, writeShard: true}
    if not OwnedIndexValidJob(job) then return invalid
    if not OwnedIndexIdentifier(OwnedIndexText(scope, "accountId")) then return invalid
    if OwnedIndexCoordinatorInteger(scope.sessionRevision, 2147483647) < 0 then return invalid
    return scope
end function

function OwnedIndexCoordinatorScopeMatches(scope as Object, currentScope as Dynamic) as Boolean
    current = OwnedIndexCoordinatorScope(currentScope)
    if current = invalid then return false
    for each name in ["provider", "sourceId", "profileId", "accountId", "sessionRevision", "inventoryRunId"]
        if scope[name] <> current[name] then return false
    end for
    return true
end function

function OwnedIndexCoordinatorCorrelated(job as Object, result as Dynamic) as Boolean
    if type(result) <> "roAssociativeArray" then return false
    for each name in ["provider", "sourceId", "profileId", "inventoryRunId", "libraryId", "offset", "requestId"]
        if OwnedIndexField(result, name) <> job[name] then return false
    end for
    return true
end function

function OwnedIndexCoordinatorPageBodyMatches(page as Object, body as Dynamic) as Boolean
    if type(body) <> "String" and type(body) <> "roString" then return false
    if Len(body) > 65536 then return false
    if OwnedIndexByteCount(body) > 65536 then return false
    decoded = ParseJson(body)
    if type(decoded) <> "roAssociativeArray" then return false
    for each name in page.Keys()
        if FormatJson(page[name]) <> FormatJson(OwnedIndexField(decoded, name)) then return false
    end for
    return true
end function

function OwnedIndexCoordinatorIdle(activity as Dynamic) as Boolean
    if type(activity) <> "roAssociativeArray" then return false
    for each name in ["playbackActive", "apiBusy", "memoryPressure"]
        flag = OwnedIndexField(activity, name)
        if not OwnedIndexCoordinatorBoolean(flag) then return false
        if flag then return false
    end for
    return true
end function


' A fresh bounded view for this validation call; first folded key wins exactly
' as OwnedIndexField. Keep the original AA and its nested values unmodified.
function OwnedIndexCoordinatorFields(value as Dynamic, allowed as Object, count as Integer) as Dynamic
    if type(value) <> "roAssociativeArray" then return invalid
    keys = value.Keys()
    if keys.Count() <> count then return invalid
    fields = {}
    for each key in keys
        folded = LCase(key)
        if not allowed.DoesExist(folded) then return invalid
        if not fields.DoesExist(folded) then fields[folded] = value[key]
    end for
    return fields
end function

function OwnedIndexCoordinatorValidState(state as Dynamic) as Boolean
    allowed = {schema:true,scope:true,manifest:true,sections:true,sectionindex:true,inflight:true,dispatchedpages:true,nextrequestid:true,partial:true,sectiontruncated:true,finished:true,status:true,errorcode:true,authoritativeabsence:true,sourceinventorycomplete:true}
    fields = OwnedIndexCoordinatorFields(state, allowed, 15)
    if fields = invalid then return false
    if fields.schema <> 1 then return false
    scope = fields.scope
    if OwnedIndexCoordinatorScope(scope) = invalid then return false
    if scope.Count() <> 6 then return false
    for each name in ["partial", "sectiontruncated", "finished", "authoritativeabsence", "sourceinventorycomplete"]
        if not OwnedIndexCoordinatorBoolean(fields[name]) then return false
    end for
    if state.authoritativeAbsence or state.sourceInventoryComplete then return false
    sections = fields.sections
    if type(sections) <> "roArray" then return false
    if sections.Count() > 24 then return false
    index = OwnedIndexCoordinatorInteger(fields.sectionindex, sections.Count())
    if index < 0 then return false
    pages = OwnedIndexCoordinatorInteger(fields.dispatchedpages, 200)
    if pages < 0 then return false
    if OwnedIndexCoordinatorInteger(fields.nextrequestid, 201) <> pages + 1 then return false
    seen = {}
    committed = 0
    sectionAllowed = {libraryid:true,type:true,status:true,nextoffset:true,pages:true,errorcode:true}
    for each section in sections
        sectionFields = OwnedIndexCoordinatorFields(section, sectionAllowed, 6)
        if sectionFields = invalid then return false
        id = sectionFields.libraryid
        idKind = type(id)
        if idKind <> "String" and idKind <> "roString" then return false
        if not CreateObject("roRegex", "^[A-Za-z0-9_-]{1,64}$", "").IsMatch(id) then return false
        if seen.DoesExist(id) then return false
        seen[id] = true
        kind = sectionFields.type
        kindType = type(kind)
        if kindType <> "String" and kindType <> "roString" then return false
        if kind <> "movie" and kind <> "show" then return false
        status = sectionFields.status
        statusKind = type(status)
        if statusKind <> "String" and statusKind <> "roString" then return false
        if status <> "pending" and status <> "scanning" and status <> "terminal" and status <> "partial" then return false
        count = OwnedIndexCoordinatorInteger(sectionFields.pages, 200)
        if count < 0 then return false
        committed += count
        if OwnedIndexCoordinatorInteger(sectionFields.nextoffset, 2147483647) < 0 then return false
    end for
    if committed > pages then return false
    flight = fields.inflight
    if flight <> invalid
        if not OwnedIndexValidJob(flight) then return false
        if index >= sections.Count() then return false
        if flight.libraryId <> sections[index].libraryId or flight.offset <> sections[index].nextOffset then return false
        if flight.requestId <> pages then return false
        for each name in ["provider", "sourceId", "profileId", "inventoryRunId"]
            if OwnedIndexField(flight, name) <> scope[name] then return false
        end for
    end if
    return type(fields.manifest) = "roAssociativeArray"
end function

function OwnedIndexCoordinatorBoolean(value as Dynamic) as Boolean
    return type(value) = "Boolean" or type(value) = "roBoolean"
end function

function OwnedIndexCoordinatorInteger(value as Dynamic, maximum as Integer) as Integer
    kind = type(value)
    if kind <> "Integer" and kind <> "LongInteger" and kind <> "Float" and kind <> "Double" and kind <> "roInt" and kind <> "roInteger" and kind <> "roLongInteger" and kind <> "roFloat" and kind <> "roDouble" then return -1
    number = OwnedIndexInteger(value)
    if number < 0 or number > maximum then return -1
    return number
end function

function OwnedIndexCoordinatorError(code as String, fallback as String) as String
    if code = "invalid_manifest" or code = "manifest_budget" or code = "section_truncated" then return code
    safe = OwnedIndexFailure(code)
    if safe.errorCode = "invalid_response" and code <> "invalid_response" then return fallback
    return safe.errorCode
end function
