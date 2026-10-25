' Local preferences and optional gateway inference. No allocator/native commands.
function TaskRunDecisionGateway(provider as String, action as String, session as Object, params as Object, scope as Object, revision as Integer) as Object
    try
        return TaskDecisionRun(provider,action,params,scope,revision)
    catch exception
        if action = "still_watching" then return TaskDecisionUnavailable()
        return TaskError("storage_error")
    end try
end function

function TaskDecisionUnavailable() as Object
    return {ok:false,errorCode:"decision_unavailable"}
end function

function TaskDecisionScope(provider as String, scope as Dynamic, revision as Integer) as Boolean
    active = DpScope(scope)
    if active = invalid then return false
    if DpField(scope,"provider") <> provider or Left(active.sourceId,5) <> provider+":" then return false
    return DpNumber(DpField(scope,"generation"),2147483647,true) and revision >= 0
end function

function TaskDecisionSession(provider as String, scope as Object, revision as Integer) as Dynamic
    if not TaskDecisionScope(provider,scope,revision) then return invalid
    if SessionRevision(provider) <> revision then return invalid
    current = LoadSession(provider)
    if SessionRevision(provider) <> revision then return invalid
    if DpField(current,"sourceId") <> scope.sourceId or DpField(current,"profileId") <> scope.profileId then return invalid
    return current
end function

function TaskDecisionPreference(session as Object, scope as Object) as Object
    fallback = DecisionPreferenceDefaults(scope)
    records = DpField(session,"decisionPreferences")
    if type(records) <> "roArray" then return fallback
    if records.Count() > 8 then return fallback
    found = invalid
    matched = false
    for each record in records
        if DpField(record,"sourceId") = scope.sourceId and DpField(record,"profileId") = scope.profileId
            if matched then return fallback
            matched = true
            found = DecisionPreferenceNormalize(record,scope)
        end if
    end for
    if found = invalid then return fallback
    return found
end function

function TaskDecisionRecords(session as Object, preference as Object, provider as String) as Object
    records = DpField(session,"decisionPreferences")
    output = []
    seen = {}
    if type(records) = "roArray"
        inspected = 0
        for each raw in records
            inspected++
            if inspected > 8 then exit for
            owner = DpScope(raw)
            if owner <> invalid
                if Left(owner.sourceId,5) = provider+":"
                    row = DecisionPreferenceNormalize(raw,owner)
                    if row <> invalid
                        key = FormatJson([row.sourceId,row.profileId])
                        same = row.sourceId = preference.sourceId and row.profileId = preference.profileId
                        if not same and not seen.DoesExist(key)
                            seen[key] = true
                            output.Push(row)
                        end if
                    end if
                end if
            end if
        end for
    end if
    while output.Count() >= 8
        output.Shift()
    end while
    output.Push(preference)
    while output.Count() > 1 and not DgBytesWithin(FormatJson(output),8192)
        output.Shift()
    end while
    return output
end function

function TaskDecisionRun(provider as String, action as String, params as Object, scope as Object, revision as Integer) as Object
    current = TaskDecisionSession(provider,scope,revision)
    if current = invalid
        if action = "still_watching" then return TaskDecisionUnavailable()
        return TaskError("session_changed")
    end if
    if action = "decision_pref_get"
        if params.Count() <> 0 then return TaskError("invalid_request")
        preference = TaskDecisionPreference(current,scope)
        if TaskDecisionSession(provider,scope,revision) = invalid then return TaskError("session_changed")
        return {ok:true,data:{preference:preference}}
    end if
    if action = "decision_pref_set"
        if not DpKeys(params,["preference"]) then return TaskError("invalid_request")
        preference = DecisionPreferenceNormalize(DpField(params,"preference"),scope)
        if preference = invalid then return TaskError("invalid_request")
        ' SET is queue-exclusive; merge into a fresh session rather than the
        ' dispatch snapshot, preserving every unrelated credential/setting.
        current = TaskDecisionSession(provider,scope,revision)
        if current = invalid then return TaskError("session_changed")
        records = TaskDecisionRecords(current,preference,provider)
        updated = MergeSessionPatch(current,{"decisionPreferences":records})
        if not SaveSession(provider,updated,revision)
            if SessionRevision(provider) <> revision then return TaskError("session_changed")
            return TaskError("storage_error")
        end if
        current = TaskDecisionSession(provider,scope,revision)
        if current = invalid then return TaskError("session_changed")
        if FormatJson(TaskDecisionPreference(current,scope)) <> FormatJson(preference) then return TaskError("storage_error")
        return {ok:true,data:{preference:preference}}
    end if
    if action <> "still_watching" then return TaskError("invalid_request")
    if not DpKeys(params,["requestedAtMs","deadlineMs","viewer"]) then return TaskDecisionUnavailable()
    requested = DpField(params,"requestedAtMs")
    deadline = DpField(params,"deadlineMs")
    if not DecisionEpochMs(requested) or not DecisionEpochMs(deadline) then return TaskDecisionUnavailable()
    if requested <= 0 or deadline-requested <> 800 then return TaskDecisionUnavailable()
    viewer = DecisionGatewayViewer(DpField(params,"viewer"))
    if viewer = invalid then return TaskDecisionUnavailable()
    context = {provider:provider,scope:scope,revision:revision,requestedAtMs:requested,deadlineMs:deadline,
        preference:TaskDecisionPreference(current,scope),calls:0}
    if not TaskDecisionReady(context) then return TaskDecisionUnavailable()
    token = DecisionGatewayTokenRead(provider,context.preference.gatewayOrigin,revision)
    if not TaskDecisionReady(context) then return TaskDecisionUnavailable()
    nowMs = DecisionNowMs()
    needsInstall = token = invalid
    if token <> invalid then needsInstall = token.exp*1000# - 86400000# <= nowMs
    if needsInstall
        fresh = TaskDecisionInstall(context,token)
        if fresh <> invalid
            token = fresh
        else
            if token = invalid then return TaskDecisionUnavailable()
            if not TaskDecisionReady(context) or token.exp*1000# <= DecisionNowMs() then return TaskDecisionUnavailable()
        end if
    end if
    response = TaskDecisionCall(context,BuildDecisionGatewayRequest("decide",context.preference.gatewayOrigin,token.token,viewer))
    if DpField(response,"statusCode") = 401
        if not TaskDecisionReady(context) then return TaskDecisionUnavailable()
        if not DecisionGatewayTokenForget(provider,token,revision) then return TaskDecisionUnavailable()
        if not TaskDecisionReady(context) then return TaskDecisionUnavailable()
        token = TaskDecisionInstall(context,token)
        if token = invalid then return TaskDecisionUnavailable()
        response = TaskDecisionCall(context,BuildDecisionGatewayRequest("decide",context.preference.gatewayOrigin,token.token,viewer))
    end if
    if not DpBool(DpField(response,"ok")) or DpField(response,"ok") <> true then return TaskDecisionUnavailable()
    answer = DecodeDecisionGatewayAnswer(DpField(response,"body"))
    if answer = invalid or not TaskDecisionReady(context) then return TaskDecisionUnavailable()
    return {ok:true,data:answer}
end function

function TaskDecisionReady(context as Object) as Boolean
    nowMs = DecisionNowMs()
    if not DecisionEpochMs(nowMs) then return false
    if nowMs < context.requestedAtMs or nowMs >= context.deadlineMs then return false
    current = TaskDecisionSession(context.provider,context.scope,context.revision)
    if current = invalid then return false
    actual = TaskDecisionPreference(current,context.scope)
    if FormatJson(actual) <> FormatJson(context.preference) then return false
    if not actual.personalized or not actual.cloudDecisions or not actual.stillWatchingCheck or actual.gatewayOrigin = "" then return false
    nowMs = DecisionNowMs()
    return DecisionEpochMs(nowMs) and nowMs >= context.requestedAtMs and nowMs < context.deadlineMs
end function

function TaskDecisionCall(context as Object, request as Object) as Object
    if not TaskDecisionReady(context) or not DpBool(DpField(request,"ok")) or DpField(request,"ok") <> true then return TaskDecisionUnavailable()
    if context.calls >= 4 then return TaskDecisionUnavailable()
    context.calls++
    response = DecisionGatewayHttpRequest(request,context.deadlineMs)
    if not TaskDecisionReady(context) then return TaskDecisionUnavailable()
    return response
end function

function TaskDecisionInstall(context as Object, previous as Dynamic) as Dynamic
    bearer = ""
    if previous <> invalid then bearer = previous.token
    response = TaskDecisionCall(context,BuildDecisionGatewayRequest("install",context.preference.gatewayOrigin,bearer,invalid))
    if not DpBool(DpField(response,"ok")) or DpField(response,"ok") <> true then return invalid
    token = DecodeDecisionGatewayInstall(DpField(response,"body"),context.preference.gatewayOrigin,DecisionNowMs(),context.revision)
    if token = invalid or not TaskDecisionReady(context) then return invalid
    if not DecisionGatewayTokenWrite(context.provider,token,context.revision) then return invalid
    if not TaskDecisionReady(context) then return invalid
    return token
end function

' These factories isolate only the native transport boundary in fixtures.
function DecisionGatewayTransfer() as Dynamic
    return CreateObject("roUrlTransfer")
end function
function DecisionGatewayPort() as Dynamic
    return CreateObject("roMessagePort")
end function
function DecisionGatewayWait(milliseconds as Integer, port as Object) as Dynamic
    return wait(milliseconds,port)
end function

' Dedicated optional transport: the general HttpRequest timeout floor is intact.
function DecisionGatewayHttpRequest(request as Object, deadlineMs as Double) as Object
    failed = {ok:false,errorCode:"decision_unavailable"}
    if not DecisionEpochMs(deadlineMs) then return failed
    startedAt = DecisionNowMs()
    if not DecisionEpochMs(startedAt) then return failed
    budget = deadlineMs-startedAt
    if budget <= 0 or budget > 800 then return failed
    if not DecisionGatewayRequestValid(request) then return failed
    timer = CreateObject("roTimespan")
    timer.Mark()
    transfer = DecisionGatewayTransfer()
    port = DecisionGatewayPort()
    if transfer = invalid or port = invalid then return failed
    transfer.SetMessagePort(port)
    transfer.SetUrl(request.url)
    transfer.RetainBodyOnError(false)
    transfer.SetCertificatesFile("common:/certs/ca-bundle.crt")
    transfer.EnablePeerVerification(true)
    transfer.EnableHostVerification(true)
    for each name in request.headers
        transfer.AddHeader(name,request.headers[name])
    end for
    nowMs = DecisionNowMs()
    if nowMs < startedAt or nowMs >= deadlineMs or timer.TotalMilliseconds() >= budget then return failed
    if not transfer.AsyncPostFromString(request.body) then return failed
    while true
        nowMs = DecisionNowMs()
        remaining = deadlineMs-nowMs
        localRemaining = budget-timer.TotalMilliseconds()
        if localRemaining < remaining then remaining = localRemaining
        if not DecisionEpochMs(nowMs) or nowMs < startedAt or remaining <= 0 then exit while
        waitMs = 100
        if remaining < waitMs then waitMs = Int(remaining)
        if waitMs <= 0 then exit while
        event = DecisionGatewayWait(waitMs,port)
        if type(event) = "roUrlEvent"
            if event.GetSourceIdentity() = transfer.GetIdentity()
                nowMs = DecisionNowMs()
                if nowMs < startedAt or nowMs >= deadlineMs or timer.TotalMilliseconds() >= budget then exit while
                response = HttpResponseBody(request,event.GetResponseCode(),event.GetString())
                nowMs = DecisionNowMs()
                if nowMs < startedAt or nowMs >= deadlineMs or timer.TotalMilliseconds() >= budget then exit while
                return response
            end if
        end if
    end while
    transfer.AsyncCancel()
    return failed
end function
