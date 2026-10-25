' HTTP runs only on the Task thread. Provider requests are constructed in adapters.
function HttpErrorCode(status as Integer) as String
    if status <= 0 then return "network_error"
    if status = 401 then return "auth_required"
    if status = 403 then return "forbidden"
    if status = 404 then return "not_found"
    if status = 408 then return "network_timeout"
    if status = 425 then return "server_error"
    if status = 429 then return "rate_limited"
    if status >= 500 then return "server_error"
    return "http_error"
end function

function HttpErrorBodyLimit(request as Object) as Integer
    if not request.DoesExist("errorBodyLimit") then return 0
    value = request.errorBodyLimit
    kind = type(value)
    if kind = "Integer" or kind = "LongInteger" or kind = "roInt" or kind = "roInteger" or kind = "roLongInteger"
        if value > 0 and value <= 8192 then return Int(value)
    end if
    return 0
end function

function HttpErrorBodyWithinLimit(body as String, limit as Integer) as Boolean
    if limit <= 0 or limit > 8192 then return false
    if Len(body) > limit then return false
    bytes = CreateObject("roByteArray")
    bytes.FromAsciiString(body)
    return bytes.Count() <= limit
end function

function HttpResponseBodyLimit(request as Object) as Integer
    if not request.DoesExist("responseBodyLimit") then return 2097152
    value = request.responseBodyLimit
    kind = type(value)
    if kind = "Integer" or kind = "LongInteger" or kind = "roInt" or kind = "roInteger" or kind = "roLongInteger"
        if value > 0 and value <= 2097152 then return Int(value)
    end if
    return 2097152
end function

' Error bodies are opt-in, bounded, and private to the Task's decoder.
function HttpResponseBody(request as Object, status as Integer, body as Dynamic) as Object
    if type(body) <> "String" and type(body) <> "roString" then body = ""
    if status < 200 or status >= 300
        result = {ok: false, errorCode: HttpErrorCode(status), statusCode: status}
        limit = HttpErrorBodyLimit(request)
        if HttpErrorBodyWithinLimit(body, limit) then result["body"] = body
        return result
    end if
    limit = HttpResponseBodyLimit(request)
    if Len(body) > limit then return {ok: false, errorCode: "response_too_large", statusCode: status}
    ' This bounds the decoded response after receipt. AsyncGetToString may
    ' allocate a larger wire body; this is not a streaming allocation ceiling.
    if request.DoesExist("responseBodyLimit")
        bytes = CreateObject("roByteArray")
        bytes.FromAsciiString(body)
        if bytes.Count() > limit then return {ok: false, errorCode: "response_too_large", statusCode: status}
    end if
    return {ok: true, statusCode: status, body: body}
end function


' Opt-in diagnostics retain only documented numeric Plex pagination headers.
' Duplicate headers are observable through roUrlEvent.GetResponseHeadersArray.
function HttpCapturePlexContainerHeaders(request as Object) as Boolean
    if not request.DoesExist("capturePlexContainerHeaders") then return false
    value = request.capturePlexContainerHeaders
    kind = type(value)
    if kind <> "Boolean" and kind <> "roBoolean" then return false
    return value
end function

function HttpPlexContainerHeaders(headers as Dynamic) as Object
    failed = {valid:false,totalSize:-1,offset:-1}
    if type(headers) <> "roArray" then return failed
    if headers.Count() > 64 then return failed
    result = {valid:true,totalSize:-1,offset:-1}
    seen = {}
    for each entry in headers
        if type(entry) <> "roAssociativeArray" then return failed
        count = 0
        for each name in entry
            count++
            if count > 1 then return failed
            if Len(name) <= 128
                folded = LCase(name)
                target = ""
                if folded = "x-plex-container-total-size" then target = "totalSize"
                if folded = "x-plex-container-start" then target = "offset"
                if target <> ""
                    if seen.DoesExist(target) then return failed
                    seen[target] = true
                    value = entry[name]
                    kind = type(value)
                    if kind <> "String" and kind <> "roString" then return failed
                    if Len(value) > 12 then return failed
                    value = value.Trim()
                    if not CreateObject("roRegex","^(0|[1-9][0-9]{0,9})$","").IsMatch(value) then return failed
                    if Len(value) = 10 and value > "2147483647" then return failed
                    result[target] = value.ToInt()
                end if
            end if
        end for
        if count <> 1 then return failed
    end for
    return result
end function

function HttpResponse(request as Object, status as Integer, body as Dynamic, headers = invalid as Dynamic) as Object
    result = HttpResponseBody(request,status,body)
    if HttpCapturePlexContainerHeaders(request) then result["plexContainerHeaders"] = HttpPlexContainerHeaders(headers)
    if request.DoesExist("captureETag") and request.captureETag = true then result.etag = HttpStrongETag(headers)
    return result
end function

function HttpTimeoutMs(request as Object, overrideMs as Integer) as Integer
    timeoutMs = overrideMs
    if timeoutMs <= 0
        timeoutMs = 9000
        if type(request) = "roAssociativeArray" and request.DoesExist("timeoutMs")
            value = request["timeoutMs"]
            kind = type(value)
            if kind = "Integer" or kind = "LongInteger" or kind = "roInt" or kind = "roInteger" or kind = "roLongInteger"
                if value >= 1000 then timeoutMs = value
            end if
        end if
    end if
    if timeoutMs < 1000 then timeoutMs = 1000
    maximumMs = 30000
    ' Only Silo start/replan opt in; callers still choose the actual budget.
    if request.DoesExist("siloPlaybackPreparation")
        if request.siloPlaybackPreparation = true then maximumMs = 90000
    end if
    if timeoutMs > maximumMs then timeoutMs = maximumMs
    return timeoutMs
end function


' Only opted-in JSON string requests negotiate native gzip. Explicit transport
' headers/validators retain their caller's wire semantics; media agents bypass this.
function HttpNativeGzip(request as Object) as Boolean
    if not request.DoesExist("enableGzip") then return false
    kind = type(request.enableGzip)
    if kind <> "Boolean" and kind <> "roBoolean" then return false
    if request.enableGzip <> true then return false
    method = UCase(request.method)
    if method <> "GET" and method <> "POST" and method <> "PUT" and method <> "PATCH" and method <> "DELETE" then return false
    if request.DoesExist("captureETag") and request.captureETag = true then return false
    if type(request.headers) <> "roAssociativeArray" then return false
    if request.headers.Count() > 64 then return false
    acceptsJson = false
    for each name in request.headers
        folded = LCase(name)
        if folded = "accept-encoding" or folded = "range" or folded = "if-range" or folded = "if-match" or folded = "if-none-match" then return false
        if folded = "accept"
            value = request.headers[name]
            kind = type(value)
            if kind <> "String" and kind <> "roString" then return false
            acceptsJson = LCase(value.Trim()) = "application/json"
        end if
    end for
    return acceptsJson
end function

function HttpRequest(request as Object, timeoutMs = 0 as Integer) as Object
    if request = invalid or request.ok <> true then return {ok: false, errorCode: "invalid_request"}
    if request.url = invalid or request.method = invalid then return {ok: false, errorCode: "invalid_request"}
    if Left(request.url, 8) <> "https://" and Left(request.url, 7) <> "http://" then return {ok: false, errorCode: "invalid_request"}
    if request.DoesExist("requireVerifiedTls") and request.requireVerifiedTls = true and Left(request.url,8) <> "https://" then return {ok:false,errorCode:"tls_setup_failed"}
    timeoutMs = HttpTimeoutMs(request, timeoutMs)

    transfer = CreateObject("roUrlTransfer")
    port = CreateObject("roMessagePort")
    if transfer = invalid or port = invalid then return {ok: false, errorCode: "network_unavailable"}
    transfer.SetMessagePort(port)
    transfer.SetUrl(request.url)
    transfer.RetainBodyOnError(HttpErrorBodyLimit(request) > 0)
    ' Native negotiation/decompression is optional. Failure keeps the ordinary
    ' string transfer; never add a raw encoding header or retry a mutation.
    if HttpNativeGzip(request) then transfer.EnableEncodings(true)
    if Left(request.url, 8) = "https://"
        if request.DoesExist("requireVerifiedTls") and request.requireVerifiedTls = true
            tls = transfer.SetCertificatesFile("common:/certs/ca-bundle.crt")
            tls = transfer.EnablePeerVerification(true) and tls
            tls = transfer.EnableHostVerification(true) and tls
            if tls <> true then return {ok:false,errorCode:"tls_setup_failed"}
        else
            transfer.SetCertificatesFile("common:/certs/ca-bundle.crt")
            transfer.EnablePeerVerification(true)
            transfer.EnableHostVerification(true)
        end if
    end if
    if request.DoesExist("headers") and request.headers <> invalid
        for each name in request.headers
            transfer.AddHeader(name, request.headers[name])
        end for
    end if

    method = UCase(request.method)
    started = false
    if method = "GET"
        started = transfer.AsyncGetToString()
    else if method = "POST" or method = "DELETE" or method = "PUT" or method = "PATCH"
        body = ""
        if request.DoesExist("body") and request.body <> invalid then body = request.body
        if method <> "POST" then transfer.SetRequest(method)
        started = transfer.AsyncPostFromString(body)
    end if
    if not started then return {ok: false, errorCode: "network_error"}

    clock = CreateObject("roTimespan")
    clock.Mark()
    while clock.TotalMilliseconds() < timeoutMs
        event = wait(250, port)
        if type(event) = "roUrlEvent" and event.GetSourceIdentity() = transfer.GetIdentity()
            status = event.GetResponseCode()
            body = event.GetString()
            headers = invalid
            if HttpCapturePlexContainerHeaders(request) or (request.DoesExist("captureETag") and request.captureETag = true) then headers = event.GetResponseHeadersArray()
            return HttpResponse(request, status, body, headers)
        end if
    end while
    transfer.AsyncCancel()
    return {ok: false, errorCode: "network_timeout"}
end function

' Deliberately retain only one strong validator; never return other headers.
function HttpStrongETag(headers as Dynamic) as String
    if type(headers) <> "roArray" or headers.Count() > 64 then return ""
    tag = ""
    for each entry in headers
        if type(entry) <> "roAssociativeArray" then return ""
        for each name in entry
            if LCase(name) = "etag"
                if tag <> "" then return ""
                value = entry[name]
                if type(value) <> "String" and type(value) <> "roString" then return ""
                if Len(value) < 3 or Len(value) > 256 then return ""
                if Left(value,1) <> Chr(34) or Right(value,1) <> Chr(34) then return ""
                for index = 2 to Len(value) - 1
                    character = Asc(Mid(value,index,1))
                    if character < 33 or character > 126 or character = 34 then return ""
                end for
                tag = value
            end if
        end for
    end for
    return tag
end function
