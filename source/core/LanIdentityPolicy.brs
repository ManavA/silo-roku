' Identity equality checks discovery consistency; it does not authenticate a server.
function LanIdentityDecode(candidate as Object, body as String) as Object
    selection = LanIdentityRequest([candidate], 0)
    if not selection.ok then return selection
    failed = {ok:false, errorCode:"invalid_identity"}
    if Len(body) > 16384 then return {ok:false,errorCode:"response_too_large"}
    bytes = CreateObject("roByteArray")
    bytes.FromAsciiString(body)
    if bytes.Count() > 16384 then return {ok:false,errorCode:"response_too_large"}
    if not LanIdentityJsonDepth(body) then return failed
    identity = ParseJson(body)
    if type(identity) <> "roAssociativeArray" then return failed
    if type(identity.server_id) <> "String" and type(identity.server_id) <> "roString" then return failed
    if identity.server_id <> candidate.serverId then return {ok:false,errorCode:"identity_mismatch"}
    return {ok:true,serverId:identity.server_id,trusted:false}
end function

' The caller passes the policy's current candidates and the explicit selection.
function LanIdentityRequest(candidates as Dynamic, selected as Dynamic) as Object
    failed = {ok:false,errorCode:"invalid_selection"}
    if type(candidates) <> "roArray" then return failed
    if type(selected) <> "Integer" and type(selected) <> "roInt" and type(selected) <> "roInteger" then return failed
    if selected < 0 or selected >= candidates.Count() or candidates.Count() > 16 then return failed
    candidate = candidates[selected]
    if type(candidate) <> "roAssociativeArray" then return failed
    if type(candidate.address) <> "String" and type(candidate.address) <> "roString" then return failed
    if not LanDiscoveryPrivate(candidate.address) then return failed
    if type(candidate.port) <> "Integer" and type(candidate.port) <> "roInt" and type(candidate.port) <> "roInteger" then return failed
    if candidate.port < 1 or candidate.port > 65535 then return failed
    if candidate.goodbye <> false then return failed
    if type(candidate.serverId) <> "String" and type(candidate.serverId) <> "roString" then return failed
    if Len(candidate.serverId) < 1 or Len(candidate.serverId) > 128 then return failed
    if CreateObject("roRegex","[^a-zA-Z0-9_-]","").IsMatch(candidate.serverId) then return failed
    return {ok:true,address:candidate.address,port:candidate.port,serverId:candidate.serverId,path:"/api/v2/system/identity"}
end function

' Reject deep untrusted documents before invoking the native JSON decoder.
function LanIdentityJsonDepth(body as String) as Boolean
    depth = 0
    quoted = false
    escaped = false
    for index = 1 to Len(body)
        value = Asc(Mid(body,index,1))
        if quoted
            if escaped
                escaped = false
            else if value = 92
                escaped = true
            else if value = 34
                quoted = false
            end if
        else if value = 34
            quoted = true
        else if value = 123 or value = 91
            depth = depth + 1
            if depth > 16 then return false
        else if value = 125 or value = 93
            depth = depth - 1
            if depth < 0 then return false
        end if
    end for
    return depth = 0 and not quoted
end function
