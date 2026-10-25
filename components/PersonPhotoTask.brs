sub init()
    m.top.functionName = "runPersonPhoto"
end sub

sub runPersonPhoto()
    m.photoOwner = {}
    m.photoUri = ""
    m.photoPartial = ""
    m.photoFinal = ""
    m.photoRevision = -1
    try
        cleanup = m.top.cleanupPaths
        if type(cleanup) = "roArray" and cleanup.Count() > 0
            ' Token-free cleanup is independent of current view/session/memory.
            for index = 0 to cleanup.Count() - 1
                if index >= 8 then exit for
                path = cleanup[index]
                if type(path) = "String" or type(path) = "roString"
                    if CreateObject("roRegex", "^tmp:/personphoto-[0-9]+-[0-9]+[.](jpg|png|webp)$", "").IsMatch(path) then PersonPhotoSafeDelete(path)
                end if
            end for
        else
            ExecutePersonPhoto()
        end if
    catch exception
        m.photoUri = ""
    end try
    ' Cleanup failures must never prevent the finite worker's terminal result.
    PersonPhotoSafeDelete(m.photoPartial)
    if m.photoUri = "" then PersonPhotoSafeDelete(m.photoFinal)
    m.photoSession = invalid
    m.top.result = {owner:m.photoOwner,uri:m.photoUri,sessionRevision:m.photoRevision}
end sub

sub PersonPhotoSafeDelete(path as String)
    try
        PersonPhotoDeleteFile(path)
    catch exception
        ' Do not expose platform errors or private request information.
    end try
end sub

sub ExecutePersonPhoto()
    job = m.top.job
    if not PersonPhotoJobValid(job)
        return
    end if
    m.photoOwner = {sourceId:job.sourceId,profileId:job.profileId,generation:job.generation,visit:job.visit,itemId:job.itemId,personId:job.personId,index:job.index,requestId:job.requestId}
    m.photoJob = m.photoOwner
    m.photoSession = LoadSession("silo")
    m.photoRevision = SessionRevision("silo")
    m.artworkClock = CreateObject("roTimespan")
    m.artworkClock.Mark()
    uri = ""
    path = "tmp:/personphoto-" + job.generation.ToStr() + "-" + job.requestId.ToStr() + ".part"
    m.photoPartial = path
    if PersonPhotoTaskCurrent()
        request = BuildSiloRequest("person", m.photoSession, {personId:job.personId})
        request["responseBodyLimit"] = 32768
        response = {ok:false}
        if request.ok = true then response = HttpRequest(request, 3000)
        if response.ok = true and PersonPhotoTaskCurrent()
            image = PersonPhotoRequest(job.personId, response.body)
            response = invalid
            if image.ok = true
                downloaded = PersonPhotoFetch(image, 5000, path)
                image = invalid
                if downloaded.ok = true and PersonPhotoTaskCurrent()
                    info = PersonPhotoInspectFile(path)
                    if info.ok = true
                        privateJob = {provider:"silo",sourceId:job.sourceId,profileId:job.profileId,generation:job.generation,route:"detail",itemId:job.itemId,kind:"poster",requestId:job.requestId}
                        plan = ArtworkFilePlan(privateJob, downloaded.contentType, info.firstBytesHex, info.encodedBytes)
                        if plan.ok = true
                            candidate = plan.uri.Replace("tmp:/artwork-", "tmp:/personphoto-")
                            m.photoFinal = candidate
                            if PersonPhotoRenameFile(path,candidate) then uri = candidate
                        end if
                    end if
                end if
            end if
        end if
    end if
    PersonPhotoDeleteFile(path)
    if not PersonPhotoTaskCurrent()
        PersonPhotoDeleteFile(uri)
        uri = ""
    end if
    m.photoUri = uri
end sub

function PersonPhotoElapsedMs() as Integer
    return m.artworkClock.TotalMilliseconds()
end function

function PersonPhotoTaskCurrent() as Boolean
    if m.top.cancelled then return false
    if m.photoRevision <> SessionRevision("silo") then return false
    current = LoadSession("silo")
    for each key in ["sourceId","profileId"]
        if ArtworkText(current,key) <> ArtworkText(m.photoJob,key) then return false
    end for
    for each key in ["accessToken","profileToken","refreshToken","baseUrl"]
        if ArtworkText(current,key) <> ArtworkText(m.photoSession,key) then return false
    end for
    return true
end function

function PersonPhotoInterruption() as Object
    return {ok:false}
end function

function PersonPhotoFetch(request as Object, timeoutMs as Integer, path as String) as Object
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
    if not PersonPhotoTaskCurrent() then return PersonPhotoInterruption()
    if path = ""
        started = transfer.AsyncGetToString()
    else
        PersonPhotoDeleteFile(path)
        started = transfer.AsyncGetToFile(path)
    end if
    if not started then return ArtworkFailure("network_error")
    startedMs = PersonPhotoElapsedMs()
    while PersonPhotoElapsedMs() - startedMs < timeoutMs and PersonPhotoElapsedMs() < 8000
        if not PersonPhotoTaskCurrent()
            transfer.AsyncCancel()
            PersonPhotoDeleteFile(path)
            return PersonPhotoInterruption()
        end if
        if path <> "" and PersonPhotoFileTooLarge(path)
            transfer.AsyncCancel()
            PersonPhotoDeleteFile(path)
            return ArtworkFailure("image_too_large")
        end if
        event = wait(100, port)
        if type(event) = "roUrlEvent" and event.GetSourceIdentity() = transfer.GetIdentity()
            status = event.GetResponseCode()
            if status < 200 or status >= 300
                PersonPhotoDeleteFile(path)
                if status = 401 or status = 403 then return ArtworkFailure("auth_required")
                return ArtworkFailure("network_error")
            end if
            if path = ""
                body = event.GetString()
                if Len(body) > 98304 then return ArtworkFailure("image_too_large")
                return {ok: true, body: body}
            end if
            if PersonPhotoFileTooLarge(path)
                PersonPhotoDeleteFile(path)
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
    PersonPhotoDeleteFile(path)
    return ArtworkFailure("network_timeout")
end function

function PersonPhotoFileTooLarge(path as String) as Boolean
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

function PersonPhotoInspectFile(path as String) as Object
    fs = CreateObject("roFileSystem")
    stat = fs.Stat(path)
    if type(stat) <> "roAssociativeArray" then return ArtworkFailure("storage_error")
    size = ArtworkField(stat, "size", 0)
    if size < 12 or size > 262144 then return ArtworkFailure("image_too_large")
    header = CreateObject("roByteArray")
    if not header.ReadFile(path, 0, 12) then return ArtworkFailure("storage_error")
    return {ok: true, encodedBytes: size, firstBytesHex: header.ToHexString()}
end function

function PersonPhotoRenameFile(fromPath as String, toPath as String) as Boolean
    return CreateObject("roFileSystem").Rename(fromPath, toPath)
end function

sub PersonPhotoDeleteFile(path as String)
    if path = "" then return
    ' Only this Task's validated generated paths may be deleted.
    if not CreateObject("roRegex", "^tmp:/personphoto-[0-9]+-[A-Za-z0-9_-]{1,32}[.](part|jpg|png|webp)$", "").IsMatch(path) then return
    fs = CreateObject("roFileSystem")
    fs.Delete(path)
    fs.Delete(path + ".tmp")
end sub
