' Pure Quick Connect authentication descriptors, official48ae/cce contract.
' Caller supplies account-discovered compatConnectInfo and keeps privateAuth,
' request bodies and credential headers inside its private Task memory.
' No native credential, storage, transport, playback owner or logging here.
function BuildSiloCompatRequest(action as String, session as Object, params as Object) as Object
    refused = SiloError("invalid_compat_request","Compatibility authentication is unavailable.")
    if not SiloContains(["initiate","collect","logout","system_info","item_metadata","playback_info","revocation_probe","playing","progress","stopped","sessions","delete_encodings"],action) then return refused
    info = session.compatConnectInfo
    if not SiloObject(info) then return refused
    if info.enabled <> true or info.available <> true then return refused
    checked = SiloCompatConnectInfo({jellyfin:{enabled:info.enabled,public_url:info.publicUrl,server_name:""}},{baseUrl:session.baseUrl})
    if checked.ok <> true then return refused
    if checked.data.available <> true then return refused
    headers = {Accept:"application/json","Content-Type":"application/json"}
    identity = []
    for each key in ["model","deviceId","appVersion"]
        value = session[key]
        if not SiloCompatIdentity(value) then return refused
        identity.Push(value)
    end for
    headers["X-Emby-Authorization"] = "MediaBrowser Client="+Chr(34)+"Silo Roku"+Chr(34)+", Device="+Chr(34)+identity[0]+Chr(34)+", DeviceId="+Chr(34)+identity[1]+Chr(34)+", Version="+Chr(34)+identity[2]+Chr(34)
    body = {}
    method = "POST"
    path = "/QuickConnect/Initiate"
    if action = "system_info"
        method = "GET":path = "/System/Info/Public"
    else if SiloContains(["playing","progress","stopped","sessions","delete_encodings"],action)
        if not SiloCompatPattern(session.compatToken,"^[!-~]+$",4096) then return refused
        if session.compatToken = session.accessToken or session.compatToken = session.refreshToken then return refused
        headers["Authorization"] = "Bearer "+session.compatToken
        if action = "sessions"
            method = "GET":path = "/Sessions"
        else
            if not SiloCompatPattern(params.playSessionId,"^[A-Za-z0-9_-]+$",128) then return refused
            if action = "delete_encodings"
                method = "DELETE":path = "/Videos/ActiveEncodings?PlaySessionId="+params.playSessionId
            else
                if not SiloCompatPattern(params.mediaSourceId,"^03000000-0000-0000-[0-9a-f]{4}-[0-9a-f]{12}$",36) then return refused
                if not SpNumber(params.positionMs,2147483646,true) or not SpBool(params.isPaused) or not SpNumber(params.audioStreamIndex,4095,true) then return refused
                ticks = SiloCompatPositionTicks(params.positionMs/1000#)
                if ticks = invalid then return refused
                path = "/Sessions/Playing"
                if action = "progress" then path += "/Progress"
                if action = "stopped" then path += "/Stopped"
                body = {ItemId:params.mediaSourceId,MediaSourceId:params.mediaSourceId,PlaySessionId:params.playSessionId,PositionTicks:ticks,IsPaused:params.isPaused,AudioStreamIndex:params.audioStreamIndex,SubtitleStreamIndex:-1}
            end if
        end if
    else if action = "item_metadata" or action = "playback_info" or action = "revocation_probe"
        if not SiloCompatPattern(session.compatToken,"^[!-~]+$",4096) then return refused
        if session.compatToken = session.accessToken or session.compatToken = session.refreshToken then return refused
        headers["Authorization"] = "Bearer "+session.compatToken
        method = "GET":path = "/Sessions"
        if action <> "revocation_probe"
            if not SiloCompatPattern(params.mediaSourceId,"^03000000-0000-0000-[0-9a-f]{4}-[0-9a-f]{12}$",36) then return refused
            path = "/Items/"+params.mediaSourceId
            if action = "playback_info"
                method = "POST":path += "/PlaybackInfo"
                if not SpNumber(params.audioStreamIndex,4095,true) or not SiloObject(params.deviceProfile) or params.startTicks = invalid then return refused
                allowAudioCopy = true
                if SpField(params,"eligibilityKind") = "experimental_query_p7_hdr10_aac_fmp4_v1"
                    maxAudioChannels = SpField(params,"maxAudioChannels")
                    if not SpNumber(maxAudioChannels,2,true) or maxAudioChannels <> 2 then return refused
                    allowAudioCopy = false
                end if
                body = {MediaSourceId:params.mediaSourceId,AudioStreamIndex:params.audioStreamIndex,SubtitleStreamIndex:-1,EnableDirectPlay:false,EnableDirectStream:true,EnableTranscoding:true,AllowVideoStreamCopy:true,AllowAudioStreamCopy:allowAudioCopy,StartTimeTicks:params.startTicks,SiloSeekReanchor:true,DeviceProfile:params.deviceProfile}
                if allowAudioCopy = false then body["MaxAudioChannels"] = maxAudioChannels
                headers["User-Agent"] = "Silo Roku (Web0S compatibility negotiation)"
            end if
        end if
    else if action = "collect"
        if not SiloCompatPattern(params.secret,"^[!-~]+$",1024) then return refused
        path = "/Users/AuthenticateWithQuickConnect"
        body = {Secret:params.secret}
    else if action = "logout"
        if not SiloCompatPattern(session.compatToken,"^[!-~]+$",4096) then return refused
        if session.compatToken = session.accessToken or session.compatToken = session.refreshToken then return refused
        path = "/Sessions/Logout"
        headers["Authorization"] = "Bearer "+session.compatToken
    end if
    return {ok:true,method:method,url:checked.data.publicUrl+path,headers:headers,body:FormatJson(body)}
end function

function DecodeSiloCompatResponse(action as String, body as String, params as Object) as Object
    refused = SiloError("invalid_compat_response","Compatibility authentication was not confirmed.")
    if SiloContains(["playing","progress","stopped","delete_encodings"],action)
        if params.statusCode <> 204 or body <> "" then return refused
        return {ok:true,data:{reportAcknowledged:true}}
    end if
    if action = "sessions"
        if params.statusCode <> 200 or Len(body) > 262144 then return refused
        decoded = ParseJson(body)
        if not SiloArray(decoded) or decoded.Count() > 128 then return refused
        ids = []
        for each row in decoded
            if not SiloObject(row) or not SiloCompatPattern(row.Id,"^[A-Za-z0-9_-]+$",128) then return refused
            for each known in ids
                if row.Id = known then return refused
            end for
            ids.Push(row.Id)
        end for
        return {ok:true,data:{sessionIds:ids}}
    end if
    if action = "logout"
        if params.statusCode <> 204 or body <> "" then return refused
        return {ok:true,data:{logoutAcknowledged:true}}
    end if
    if not SiloContains(["initiate","collect"],action) then return refused
    if params.statusCode <> 200 or Len(body) > 32768 then return refused
    decoded = ParseJson(body)
    if not SiloObject(decoded) then return refused
    if action = "initiate"
        if type(decoded.Authenticated) <> "Boolean" and type(decoded.Authenticated) <> "roBoolean" then return refused
        if decoded.Authenticated <> false then return refused
        if not SiloCompatPattern(decoded.Secret,"^[!-~]+$",1024) then return refused
        if not SiloCompatPattern(decoded.Code,"^[0-9]{6}$",6) then return refused
        return {ok:true,data:{pending:true},privateAuth:{secret:decoded.Secret,code:decoded.Code}}
    end if
    if not SiloCompatPattern(decoded.AccessToken,"^[!-~]+$",4096) then return refused
    if not SiloCompatIdentity(decoded.ServerId) then return refused
    if not SiloObject(decoded.User) then return refused
    if not SiloCompatPattern(decoded.User.Id,"^[!-~]+$",256) then return refused
    return {ok:true,data:{authenticated:true},privateAuth:{compatToken:decoded.AccessToken,serverId:decoded.ServerId,compatUserId:decoded.User.Id}}
end function

function SiloCompatPattern(value as Dynamic, pattern as String, maximum as Integer) as Boolean
    if type(value) <> "String" and type(value) <> "roString" then return false
    if Len(value) > maximum then return false
    return CreateObject("roRegex",pattern,"").IsMatch(value)
end function

function SiloCompatIdentity(value as Dynamic) as Boolean
    if type(value) <> "String" and type(value) <> "roString" then return false
    if Len(value) < 1 or Len(value) > 128 or value <> value.Trim() then return false
    return not CreateObject("roRegex","[\x00-\x1f\x7f"+Chr(34)+Chr(92)+Chr(92)+"]","").IsMatch(value)
end function
