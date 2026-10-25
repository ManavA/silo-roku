' One finite, read-only private artwork job. Only a verified local file and
' public scope leave this Task; registry credentials and signed URLs stay here.
sub init()
    m.top.functionName = "runArtworkJob"
end sub

sub runArtworkJob()
    m.artworkJob = m.top.job
    m.artworkPartial = ""
    m.artworkFinal = ""
    m.artworkClock = CreateObject("roTimespan")
    m.artworkClock.Mark()
    outcome = ArtworkExecute(m.artworkJob)
    if ArtworkText(outcome, "status") = "ready"
        if not ArtworkTaskCurrent() then outcome = ArtworkInterruption()
    end if
    if ArtworkText(outcome, "status") <> "ready"
        ArtworkDeleteFile(m.artworkPartial)
        ArtworkDeleteFile(m.artworkFinal)
    end if
    m.top.result = ArtworkEnvelope(m.artworkJob, outcome)
    ' Successful files become Scene-owned. It clears the Poster before deletion.
    m.artworkSession = invalid
end sub

function ArtworkDeviceSession(session as Object) as Object
    device = CreateObject("roDeviceInfo")
    return MergeSessionPatch(session, {deviceId: device.GetChannelClientId()})
end function

function ArtworkElapsedMs() as Integer
    return m.artworkClock.TotalMilliseconds()
end function

function ArtworkTransportCapabilities() as Object
    ' Current official ifUrlTransfer/ifHttpAgent APIs provide no documented
    ' origin-scoped custom headers or redirect disabling. This applies to
    ' Silo bearer/profile headers as well as Plex tokens. A future safe
    ' transport must supply that guarantee before private artwork can run.
    return {authenticated: false}
end function

function ArtworkTaskCurrent() as Boolean
    if m.top.cancelled then return false
    provider = ArtworkText(m.artworkJob, "provider")
    currentRevision = SessionRevision(provider)
    current = LoadSession(provider)
    return ArtworkSessionMatches(m.artworkJob, m.artworkSession, current, m.artworkRevision, currentRevision)
end function

function ArtworkInterruption() as Object
    if m.top.cancelled then return ArtworkFailure("cancelled", "cancelled")
    return ArtworkFailure("session_changed", "cancelled")
end function

function ArtworkExecute(job as Dynamic) as Object
    if not ArtworkValidJob(job) then return ArtworkFailure("invalid_job")
    if m.top.cancelled then return ArtworkFailure("cancelled", "cancelled")
    provider = ArtworkText(job, "provider")
    m.artworkRevision = SessionRevision(provider)
    m.artworkSession = LoadSession(provider)
    if not ArtworkSessionMatches(job, m.artworkSession, m.artworkSession, m.artworkRevision, SessionRevision(provider)) then return ArtworkFailure("session_changed")
    if provider = "plex" then return ArtworkFailure("unsupported_redirect_safety")
    if ArtworkText(m.artworkSession, "accessToken") = "" then return ArtworkFailure("auth_required")
    capabilities = ArtworkTransportCapabilities()
    if ArtworkField(capabilities, "authenticated", false) <> true then return ArtworkFailure("unsupported_redirect_safety")
    request = ArtworkDetailRequest(job, ArtworkDeviceSession(m.artworkSession))
    if request.ok <> true then return request
    if not ArtworkTaskCurrent() then return ArtworkInterruption()
    detail = ArtworkFetch(request, 3000, "")
    if not ArtworkTaskCurrent() then return ArtworkInterruption()
    if ArtworkElapsedMs() >= 8000 then return ArtworkFailure("network_timeout")
    if ArtworkField(detail, "ok", false) <> true then return ArtworkFailure(ArtworkText(detail, "errorCode"))
    imageRequest = ArtworkSiloImageRequest(job, ArtworkText(detail, "body"))
    ' Release the detail response, including its short-lived signed URLs.
    detail = invalid
    if imageRequest.ok <> true then return imageRequest
    if not ArtworkTaskCurrent() then return ArtworkInterruption()
    remainingMs = 8000 - ArtworkElapsedMs()
    if remainingMs < 100 then return ArtworkFailure("network_timeout")
    if remainingMs > 5000 then remainingMs = 5000
    m.artworkPartial = ArtworkFileStem(job) + ".part"
    downloaded = ArtworkFetch(imageRequest, remainingMs, m.artworkPartial)
    imageRequest = invalid
    if not ArtworkTaskCurrent() then return ArtworkInterruption()
    if ArtworkElapsedMs() >= 8000 then return ArtworkFailure("network_timeout")
    if ArtworkField(downloaded, "ok", false) <> true then return ArtworkFailure(ArtworkText(downloaded, "errorCode"))
    info = ArtworkInspectFile(m.artworkPartial)
    if ArtworkField(info, "ok", false) <> true then return ArtworkFailure(ArtworkText(info, "errorCode"))
    plan = ArtworkFilePlan(job, ArtworkText(downloaded, "contentType"), ArtworkText(info, "firstBytesHex"), ArtworkField(info, "encodedBytes", 0))
    if plan.ok <> true then return plan
    if not ArtworkTaskCurrent() then return ArtworkInterruption()
    if not ArtworkRenameFile(m.artworkPartial, plan.uri) then return ArtworkFailure("storage_error")
    m.artworkFinal = plan.uri
    return {status: "ready", uri: plan.uri}
end function

' Each stage creates its own agent. The image descriptor has an empty header
' map, so bearer/profile/device/Plex headers cannot reach its CDN or redirects.
function ArtworkFetch(request as Object, timeoutMs as Integer, path as String) as Object
    headers = ArtworkField(request, "headers", {})
    ' Defense at the I/O boundary: current native agents only fetch images
    ' with empty headers. Do not send authenticated detail until the agent
    ' itself has been replaced with a documented origin-scoped transport.
    if headers.Count() <> 0 then return ArtworkFailure("unsupported_redirect_safety")
    port = CreateObject("roMessagePort")
    transfer = CreateObject("roUrlTransfer")
    if transfer = invalid then return ArtworkFailure("network_unavailable")
    transfer.SetMessagePort(port)
    transfer.SetUrl(request.url)
    transfer.RetainBodyOnError(false)
    if Left(request.url, 8) = "https://"
        transfer.SetCertificatesFile("common:/certs/ca-bundle.crt")
        transfer.EnablePeerVerification(true)
        transfer.EnableHostVerification(true)
    end if
    if not ArtworkTaskCurrent() then return ArtworkInterruption()
    if path = ""
        started = transfer.AsyncGetToString()
    else
        ArtworkDeleteFile(path)
        started = transfer.AsyncGetToFile(path)
    end if
    if not started then return ArtworkFailure("network_error")
    startedMs = ArtworkElapsedMs()
    while ArtworkElapsedMs() - startedMs < timeoutMs and ArtworkElapsedMs() < 8000
        if not ArtworkTaskCurrent()
            transfer.AsyncCancel()
            ArtworkDeleteFile(path)
            return ArtworkInterruption()
        end if
        if path <> "" and ArtworkFileTooLarge(path)
            transfer.AsyncCancel()
            ArtworkDeleteFile(path)
            return ArtworkFailure("image_too_large")
        end if
        event = wait(100, port)
        if type(event) = "roUrlEvent" and event.GetSourceIdentity() = transfer.GetIdentity()
            status = event.GetResponseCode()
            if status < 200 or status >= 300
                ArtworkDeleteFile(path)
                if status = 401 or status = 403 then return ArtworkFailure("auth_required")
                return ArtworkFailure("network_error")
            end if
            if path = ""
                body = event.GetString()
                if Len(body) > 98304 then return ArtworkFailure("image_too_large")
                return {ok: true, body: body}
            end if
            if ArtworkFileTooLarge(path)
                ArtworkDeleteFile(path)
                return ArtworkFailure("image_too_large")
            end if
            responseHeaders = event.GetResponseHeaders()
            mime = ""
            if type(responseHeaders) = "roAssociativeArray"
                for each name in responseHeaders
                    if LCase(name) = "content-type" then mime = ArtworkText(responseHeaders, name)
                end for
            end if
            return {ok: true, contentType: mime}
        end if
    end while
    transfer.AsyncCancel()
    ArtworkDeleteFile(path)
    return ArtworkFailure("network_timeout")
end function

function ArtworkFileTooLarge(path as String) as Boolean
    fs = CreateObject("roFileSystem")
    ' Some OS versions write the outstanding response into a .tmp sibling.
    for each candidate in [path, path + ".tmp"]
        stat = fs.Stat(candidate)
        if type(stat) = "roAssociativeArray"
            if ArtworkField(stat, "size", 0) > 262144 then return true
        end if
    end for
    return false
end function

function ArtworkInspectFile(path as String) as Object
    fs = CreateObject("roFileSystem")
    stat = fs.Stat(path)
    if type(stat) <> "roAssociativeArray" then return ArtworkFailure("storage_error")
    size = ArtworkField(stat, "size", 0)
    if size < 12 or size > 262144 then return ArtworkFailure("image_too_large")
    header = CreateObject("roByteArray")
    if not header.ReadFile(path, 0, 12) then return ArtworkFailure("storage_error")
    return {ok: true, encodedBytes: size, firstBytesHex: header.ToHexString()}
end function

function ArtworkRenameFile(fromPath as String, toPath as String) as Boolean
    return CreateObject("roFileSystem").Rename(fromPath, toPath)
end function

sub ArtworkDeleteFile(path as String)
    if path = "" then return
    ' Only this Task's validated generated paths may be deleted.
    if not CreateObject("roRegex", "^tmp:/artwork-[0-9]+-[A-Za-z0-9_-]{1,32}[.](part|jpg|png|webp)$", "").IsMatch(path) then return
    fs = CreateObject("roFileSystem")
    fs.Delete(path)
    fs.Delete(path + ".tmp")
end sub
