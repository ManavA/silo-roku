' Private artwork descriptors are consumed only by ArtworkTask. Never place
' request URLs, response bodies, or headers into a SceneGraph field.
' Silo image tier/detail contract inspected at Android e6fda246323e2eb1f52d197be0bed5d71194f32b.
function ArtworkField(value as Dynamic, key as String, fallback as Dynamic) as Dynamic
    if type(value) <> "roAssociativeArray" then return fallback
    if not value.DoesExist(key) then return fallback
    if value[key] = invalid then return fallback
    return value[key]
end function

function ArtworkText(value as Dynamic, key as String) as String
    result = ArtworkField(value, key, "")
    if type(result) = "String" or type(result) = "roString" then return result
    return ""
end function

function ArtworkInteger(value as Dynamic) as Boolean
    kind = type(value)
    if kind <> "Integer" and kind <> "roInt" and kind <> "roInteger" and kind <> "LongInteger" and kind <> "roLongInteger" then return false
    return value >= 0 and value <= 2147483647
end function

function ArtworkRequestKey(value as Dynamic) as String
    if ArtworkInteger(value) then return value.ToStr()
    if type(value) <> "String" and type(value) <> "roString" then return ""
    if not CreateObject("roRegex", "^[A-Za-z0-9_-]{1,32}$", "").IsMatch(value) then return ""
    return value
end function

function ArtworkValidJob(job as Dynamic) as Boolean
    if type(job) <> "roAssociativeArray" then return false
    allowed = ["provider", "sourceId", "profileId", "generation", "route", "itemId", "kind", "requestId", "thumbKey"]
    for each key in job
        found = false
        for each name in allowed
            if LCase(key) = LCase(name) then found = true
        end for
        if not found then return false
    end for
    provider = ArtworkText(job, "provider")
    if provider <> "plex" and provider <> "silo" then return false
    sourceId = ArtworkText(job, "sourceId")
    if Len(sourceId) < Len(provider) + 2 or Len(sourceId) > 1024 then return false
    if Left(sourceId, Len(provider) + 1) <> provider + ":" then return false
    profileId = ArtworkField(job, "profileId", invalid)
    if type(profileId) <> "String" and type(profileId) <> "roString" then return false
    if not CreateObject("roRegex", "^[A-Za-z0-9_.:-]{0,128}$", "").IsMatch(profileId) then return false
    if provider = "silo" and profileId = "" then return false
    if not ArtworkInteger(ArtworkField(job, "generation", invalid)) then return false
    if ArtworkRequestKey(ArtworkField(job, "requestId", invalid)) = "" then return false
    if not CreateObject("roRegex", "^[a-z_]{1,32}$", "").IsMatch(ArtworkText(job, "route")) then return false
    itemId = ArtworkText(job, "itemId")
    if not CreateObject("roRegex", "^[A-Za-z0-9_.:-]{1,256}$", "").IsMatch(itemId) then return false
    if itemId = "." or itemId = ".." then return false
    kind = ArtworkText(job, "kind")
    if kind <> "poster" and kind <> "backdrop" then return false
    if job.DoesExist("thumbKey")
        if provider <> "plex" then return false
        if not CreateObject("roRegex", "^[0-9]{1,32}$", "").IsMatch(itemId) then return false
        thumb = ArtworkText(job, "thumbKey")
        artKind = "thumb"
        if kind = "backdrop" then artKind = "art"
        pattern = "^/library/metadata/" + itemId + "/" + artKind + "(/[0-9]{1,32})?$"
        if not CreateObject("roRegex", pattern, "").IsMatch(thumb) then return false
    end if
    return true
end function

function ArtworkSessionMatches(job as Dynamic, captured as Dynamic, current as Dynamic, capturedRevision as Integer, currentRevision as Integer) as Boolean
    if not ArtworkValidJob(job) then return false
    if type(captured) <> "roAssociativeArray" or type(current) <> "roAssociativeArray" then return false
    if capturedRevision <> currentRevision then return false
    for each key in ["sourceId", "profileId"]
        if ArtworkText(job, key) <> ArtworkText(current, key) then return false
    end for
    ' Credential refresh also retires a suspended result even if SaveSession
    ' retained the registry revision. These values remain within the Task.
    for each key in ["sourceId", "profileId", "baseUrl", "accountId", "accessToken", "refreshToken", "profileToken", "token", "accountToken"]
        if ArtworkText(captured, key) <> ArtworkText(current, key) then return false
    end for
    return true
end function

function ArtworkFailure(code as String, status = "unavailable" as String) as Object
    return {ok: false, status: status, errorCode: ArtworkSafeError(code)}
end function

function ArtworkSafeError(code as String) as String
    for each allowed in ["", "invalid_job", "session_changed", "auth_required", "profile_required", "invalid_server_url", "network_error", "network_unavailable", "network_timeout", "image_missing", "invalid_response", "image_too_large", "image_format", "storage_error", "cancelled", "unsupported_redirect_safety"]
        if code = allowed then return code
    end for
    return "invalid_response"
end function

function ArtworkDetailRequest(job as Dynamic, session as Dynamic) as Object
    if not ArtworkValidJob(job) then return ArtworkFailure("invalid_job")
    if not ArtworkSessionMatches(job, session, session, 0, 0) then return ArtworkFailure("session_changed")
    ' roUrlTransfer documents no redirect control that can prove a Plex token
    ' header cannot be forwarded to another origin. Do not issue a Plex request.
    if ArtworkText(job, "provider") = "plex" then return ArtworkFailure("unsupported_redirect_safety")
    request = BuildSiloRequest("detail", session, {itemId: ArtworkText(job, "itemId")})
    if request.ok <> true then return ArtworkFailure(ArtworkText(request, "errorCode"))
    ' Detail has only the adapter's image-size query. Replace its default
    ' rather than appending a second query delimiter.
    queryStart = Instr(1, request.url, "?")
    if queryStart > 0 then request.url = Left(request.url, queryStart - 1)
    request.url = request.url + "?image_size=small"
    return request
end function

function ArtworkSafeSignedUrl(candidate as String) as Boolean
    if Len(candidate) < 12 or Len(candidate) > 4096 then return false
    pattern = "^https://[A-Za-z0-9][A-Za-z0-9.-]*(:443)?/[^#]*$"
    if not CreateObject("roRegex", pattern, "").IsMatch(candidate) then return false
    for i = 0 to Len(candidate) - 1
        charCode = Asc(Mid(candidate, i + 1, 1))
        if charCode <= 32 or charCode = 92 or charCode = 127 then return false
    end for
    return true
end function

function ArtworkSiloImageRequest(job as Dynamic, body as String) as Object
    if not ArtworkValidJob(job) or ArtworkText(job, "provider") <> "silo" then return ArtworkFailure("invalid_job")
    if Len(body) > 98304 then return ArtworkFailure("image_too_large")
    decoded = ParseJson(body)
    if type(decoded) <> "roAssociativeArray" then return ArtworkFailure("invalid_response")
    if ArtworkText(decoded, "content_id") <> ArtworkText(job, "itemId") then return ArtworkFailure("invalid_response")
    key = "poster_url"
    if ArtworkText(job, "kind") = "backdrop" then key = "backdrop_url"
    candidate = ArtworkText(decoded, key)
    if candidate = "" then return ArtworkFailure("image_missing")
    if not ArtworkSafeSignedUrl(candidate) then return ArtworkFailure("invalid_response")
    ' A fresh download descriptor contains no application headers at all.
    return {ok: true, method: "GET", url: candidate, headers: {}}
end function

function ArtworkFileStem(job as Dynamic) as String
    if not ArtworkValidJob(job) then return ""
    generation = ArtworkField(job, "generation", 0)
    return "tmp:/artwork-" + generation.ToStr() + "-" + ArtworkRequestKey(ArtworkField(job, "requestId", invalid))
end function

function ArtworkFilePlan(job as Dynamic, contentType as String, firstBytesHex as String, encodedBytes as Integer) as Object
    stem = ArtworkFileStem(job)
    if stem = "" then return ArtworkFailure("invalid_job")
    if encodedBytes < 12 or encodedBytes > 262144 then return ArtworkFailure("image_too_large")
    mime = LCase(contentType.Trim())
    separator = Instr(1, mime, ";")
    if separator > 0 then mime = Left(mime, separator - 1).Trim()
    magic = LCase(firstBytesHex)
    extension = ""
    if Len(magic) < 24 then return ArtworkFailure("image_format")
    if mime = "image/jpeg" and Left(magic, 6) = "ffd8ff" then extension = "jpg"
    if mime = "image/png" and Left(magic, 16) = "89504e470d0a1a0a" then extension = "png"
    if mime = "image/webp" and Left(magic, 8) = "52494646" and Mid(magic, 17, 8) = "57454250" then extension = "webp"
    if extension = "" then return ArtworkFailure("image_format")
    return {ok: true, uri: stem + "." + extension}
end function

function ArtworkEnvelope(job as Dynamic, outcome as Dynamic) as Object
    scope = {}
    if ArtworkValidJob(job) then scope = job
    result = {provider: ArtworkText(scope, "provider"), sourceId: ArtworkText(scope, "sourceId"), profileId: ArtworkText(scope, "profileId"), generation: ArtworkField(scope, "generation", -1), route: ArtworkText(scope, "route"), itemId: ArtworkText(scope, "itemId"), kind: ArtworkText(scope, "kind"), requestId: ArtworkField(scope, "requestId", -1), status: "unavailable", uri: "", errorCode: ArtworkSafeError(ArtworkText(outcome, "errorCode"))}
    status = ArtworkText(outcome, "status")
    if status = "cancelled" then result.status = "cancelled"
    if status = "ready"
        stem = ArtworkFileStem(scope)
        uri = ArtworkText(outcome, "uri")
        if stem <> "" and (uri = stem + ".jpg" or uri = stem + ".png" or uri = stem + ".webp")
            result.status = "ready"
            result.uri = uri
            result["errorCode"] = ""
        else
            result["errorCode"] = "invalid_response"
        end if
    end if
    return result
end function
