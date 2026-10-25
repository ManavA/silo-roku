' Roku OS15.0+ provides an atomic UTC epoch-millisecond snapshot.
' https://developer.roku.com/dev/docs/ifdatetime#asmillisecondslong-as-long
function DecisionNowMs() as Double
    date = CreateObject("roDateTime")
    return date.AsMillisecondsLong() * 1#
end function

function DgBytesWithin(raw as Dynamic, maximum as Integer) as Boolean
    if type(raw) <> "String" and type(raw) <> "roString" then return false
    if Len(raw) > maximum then return false
    bytes = CreateObject("roByteArray")
    bytes.FromAsciiString(raw)
    return bytes.Count() <= maximum
end function

function DecisionGatewayViewer(raw as Dynamic) as Dynamic
    if not DpKeys(raw,["daypart","weekend","device","session"]) then return invalid
    daypart = DpField(raw,"daypart")
    if daypart <> "morning" and daypart <> "day" and daypart <> "evening" and daypart <> "late" then return invalid
    if not DpBool(DpField(raw,"weekend")) or DpField(raw,"device") <> "tv" then return invalid
    session = DpField(raw,"session")
    if not DpKeys(session,["minutes","episodes_in_row"]) then return invalid
    minutes = DpField(session,"minutes")
    episodes = DpField(session,"episodes_in_row")
    if not DpNumber(minutes,10080,true) or not DpNumber(episodes,1000,true) then return invalid
    if episodes < 3 then return invalid
    return {"daypart":daypart,"weekend":DpField(raw,"weekend"),"device":"tv",
        "session":{"minutes":minutes,"episodes_in_row":episodes}}
end function

function DgToken(raw as Dynamic) as Boolean
    if not DpText(raw,512) then return false
    return CreateObject("roRegex","^[A-Za-z0-9._~-]+$","").IsMatch(raw)
end function

function BuildDecisionGatewayRequest(action as String, origin as Dynamic, token as Dynamic, viewer as Dynamic) as Object
    failed = {ok:false,errorCode:"decision_unavailable"}
    canonical = DecisionGatewayOrigin(origin)
    if canonical = invalid then return failed
    if canonical = "" or canonical <> origin then return failed
    if not DpText(token,512,true) then return failed
    headers = {"Accept":"application/json","Content-Type":"application/json"}
    body = "{}"
    if token <> ""
        if not DgToken(token) then return failed
        headers["Authorization"] = "Bearer " + token
    end if
    if action = "decide"
        projected = DecisionGatewayViewer(viewer)
        if projected = invalid or token = "" then return failed
        body = FormatJson({"kind":"upnext","version":1,"state":{"viewer":projected}})
    else if action <> "install"
        return failed
    end if
    if not DgBytesWithin(body,4096) then return failed
    return {ok:true,method:"POST",url:canonical+"/"+action,headers:headers,body:body,responseBodyLimit:8192}
end function

' Provider JSON remains case-sensitive, including the exact answer name/type.
function DgWireField(raw as Dynamic, key as String) as Dynamic
    if type(raw) <> "roAssociativeArray" then return invalid
    found = invalid
    for each name in raw.Keys()
        if LCase(name) = LCase(key)
            if name <> key or found <> invalid then return invalid
            found = raw[name]
        end if
    end for
    return found
end function

function DecodeDecisionGatewayAnswer(body as Dynamic) as Dynamic
    if not DgBytesWithin(body,8192) then return invalid
    raw = ParseJson(body)
    answers = DgWireField(raw,"answers")
    if type(answers) <> "roAssociativeArray" then return invalid
    if answers.Count() <> 1 then return invalid
    answer = DgWireField(answers,"still_watching")
    if type(answer) <> "roAssociativeArray" then return invalid
    if answer.Count() < 2 or answer.Count() > 8 then return invalid
    if DgWireField(answer,"type") <> "noul" then return invalid
    probability = DgWireField(answer,"noul")
    if not DpNumber(probability,1) then return invalid
    return {"probability":probability}
end function

function DecodeDecisionGatewayInstall(body as Dynamic, origin as String, nowMs as Double, revision as Integer) as Dynamic
    if not DgBytesWithin(body,8192) then return invalid
    raw = ParseJson(body)
    install = DgWireField(raw,"installId")
    token = DgWireField(raw,"token")
    expiry = DgWireField(raw,"exp")
    if not DpText(install,128) or not DgToken(token) then return invalid
    if not CreateObject("roRegex","^[A-Za-z0-9_-]+$","").IsMatch(install) then return invalid
    if not DpNumber(expiry,9000000000#,true) or expiry*1000# <= nowMs then return invalid
    return {"origin":origin,"token":token,"exp":expiry,"sessionRevision":revision}
end function

' Even the dedicated transport forwards only this adapter's narrow request.
function DecisionGatewayRequestValid(request as Dynamic) as Boolean
    if not DpKeys(request,["ok","method","url","headers","body","responseBodyLimit"]) then return false
    if not DpBool(DpField(request,"ok")) or DpField(request,"ok") <> true then return false
    if DpField(request,"method") <> "POST" or DpField(request,"responseBodyLimit") <> 8192 then return false
    url = DpField(request,"url")
    if not DpText(url,264) then return false
    action = ""
    if Right(url,8) = "/install" then action = "install"
    if Right(url,7) = "/decide" then action = "decide"
    if action = "" then return false
    origin = Left(url,Len(url)-Len(action)-1)
    canonical = DecisionGatewayOrigin(origin)
    if canonical = invalid then return false
    if canonical = "" or canonical <> origin then return false
    headers = DpField(request,"headers")
    fields = ["Accept","Content-Type"]
    authorization = DpField(headers,"Authorization")
    if authorization <> invalid then fields.Push("Authorization")
    if not DpKeys(headers,fields) then return false
    if DpField(headers,"Accept") <> "application/json" or DpField(headers,"Content-Type") <> "application/json" then return false
    bearer = ""
    if authorization <> invalid
        if not DpText(authorization,519) then return false
        if Left(authorization,7) <> "Bearer " then return false
        bearer = Mid(authorization,8)
        if not DgToken(bearer) then return false
    end if
    body = DpField(request,"body")
    if not DgBytesWithin(body,4096) then return false
    if action = "install" then return body = "{}"
    if bearer = "" then return false
    raw = ParseJson(body)
    if not DpKeys(raw,["kind","version","state"]) then return false
    if DgWireField(raw,"kind") <> "upnext" or DgWireField(raw,"version") <> 1 then return false
    state = DgWireField(raw,"state")
    if not DpKeys(state,["viewer"]) then return false
    return DecisionGatewayViewer(DgWireField(state,"viewer")) <> invalid
end function
