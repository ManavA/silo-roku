' Keep credentials inside a Task. Scene state receives only these display-safe fields.
function SessionText(session as Object, key as String) as String
    if session = invalid then return ""
    if not session.DoesExist(key) then return ""
    value = session[key]
    if value = invalid then return ""
    if type(value) <> "roString" and type(value) <> "String" then return ""
    return value
end function

function PublicSessionStatus(provider as String, session as Object) as Object
    status = {connected: false, state: "sign_in", sourceId: SessionText(session, "sourceId"), profileId: SessionText(session, "profileId"), serverName: SessionText(session, "serverName"), accountName: SessionText(session, "accountName"), profileName: SessionText(session, "profileName")}
    if provider = "plex"
        if SessionText(session, "accountToken") <> ""
            status.state = "choose_server"
            if SessionText(session, "token") <> "" and SessionText(session, "baseUrl") <> "" and status.sourceId <> "" then status.state = "connected"
        end if
    else if provider = "silo"
        status.state = "enter_server"
        if SessionText(session, "baseUrl") <> ""
            status.state = "sign_in"
            if SessionText(session, "accessToken") <> ""
                status.state = "choose_profile"
                if status.profileId <> "" then status.state = "connected"
            end if
        end if
    end if
    status.connected = status.state = "connected"
    return status
end function

function MergeSessionPatch(current as Object, patch as Object) as Object
    merged = {}
    if current <> invalid
        for each key in current
            merged[key] = current[key]
        end for
    end if
    if patch <> invalid
        for each key in patch
            merged[key] = patch[key]
        end for
    end if
    return merged
end function

function PublicPlexServers(servers as Object) as Object
    choices = []
    if servers = invalid then return choices
    for each server in servers
        if choices.Count() >= 24 then exit for
        if server <> invalid
            machineId = SessionText(server, "machineId")
            sourceId = SessionText(server, "sourceId")
            if machineId <> "" and sourceId <> ""
                choices.Push({machineId: machineId, sourceId: sourceId, name: Left(SessionText(server, "name"), 128)})
            end if
        end if
    end for
    return choices
end function
