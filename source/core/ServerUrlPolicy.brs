function NormalizeServerUrl(raw as String) as Object
    value = raw.Trim()
    lower = LCase(value)
    schemeLength = 0
    secure = false
    if Left(lower, 8) = "https://"
        schemeLength = 8
        secure = true
    else if Left(lower, 7) = "http://"
        schemeLength = 7
    else
        return {ok: false, errorCode: "invalid_server_url"}
    end if

    if Instr(1, value, "?") > 0 or Instr(1, value, "#") > 0 then return {ok: false, errorCode: "invalid_server_url"}
    if Instr(1, value, "\") > 0 or Instr(1, value, " ") > 0 then return {ok: false, errorCode: "invalid_server_url"}
    for position = 1 to Len(value)
        character = Mid(value, position, 1)
        if Asc(character) < 32 or Asc(character) = 127 then return {ok: false, errorCode: "invalid_server_url"}
    end for

    remainder = Mid(value, schemeLength + 1)
    slash = Instr(1, remainder, "/")
    authority = remainder
    if slash > 0 then authority = Left(remainder, slash - 1)
    if authority = "" or Instr(1, authority, "@") > 0 then return {ok: false, errorCode: "invalid_server_url"}

    host = authority
    port = ""
    if Left(authority, 1) = "["
        closing = Instr(1, authority, "]")
        if closing = 0 then return {ok: false, errorCode: "invalid_server_url"}
        host = Left(authority, closing)
        suffix = Mid(authority, closing + 1)
        if suffix <> ""
            if Left(suffix, 1) <> ":" then return {ok: false, errorCode: "invalid_server_url"}
            port = Mid(suffix, 2)
        end if
    else
        colon = Instr(1, authority, ":")
        if colon > 0
            host = Left(authority, colon - 1)
            port = Mid(authority, colon + 1)
        end if
    end if
    if host = "" then return {ok: false, errorCode: "invalid_server_url"}
    if port <> ""
        if Len(port) > 5 then return {ok: false, errorCode: "invalid_server_url"}
        for position = 1 to Len(port)
            if Mid(port, position, 1) < "0" or Mid(port, position, 1) > "9" then return {ok: false, errorCode: "invalid_server_url"}
        end for
        if Val(port) < 1 or Val(port) > 65535 then return {ok: false, errorCode: "invalid_server_url"}
    else if Right(authority, 1) = ":"
        return {ok: false, errorCode: "invalid_server_url"}
    end if
    if Left(host, 1) = "["
        if not IsValidServerIpv6(host) then return {ok: false, errorCode: "invalid_server_url"}
    else
        if Left(host, 1) = "." or Right(host, 1) = "." or Instr(1, host, "..") > 0 then return {ok: false, errorCode: "invalid_server_url"}
        lowerHost = LCase(host)
        for position = 1 to Len(lowerHost)
            character = Mid(lowerHost, position, 1)
            if not ((character >= "a" and character <= "z") or (character >= "0" and character <= "9") or character = "." or character = "-") then return {ok: false, errorCode: "invalid_server_url"}
        end for
        for each label in lowerHost.Split(".")
            if Len(label) > 63 or Left(label, 1) = "-" or Right(label, 1) = "-" then return {ok: false, errorCode: "invalid_server_url"}
        end for
    end if

    if not secure and not IsPrivateServerHost(LCase(host)) then return {ok: false, errorCode: "cleartext_remote_server"}

    value = Left(lower, schemeLength) + LCase(authority) + Mid(remainder, Len(authority) + 1)
    while Len(value) > schemeLength + Len(authority) and Right(value, 1) = "/"
        value = Left(value, Len(value) - 1)
    end while
    return {ok: true, url: value}
end function

function IsValidServerIpv6(host as String) as Boolean
    if Left(host, 1) <> "[" or Right(host, 1) <> "]" then return false
    literal = LCase(Mid(host, 2, Len(host) - 2))
    if Instr(1, literal, ":") = 0 or Instr(1, literal, ":::") > 0 then return false
    compressed = Instr(1, literal, "::")
    if compressed > 0
        if Instr(compressed + 2, literal, "::") > 0 then return false
    end if
    if Left(literal, 1) = ":" and Left(literal, 2) <> "::" then return false
    if Right(literal, 1) = ":" and Right(literal, 2) <> "::" then return false
    count = 0
    for each group in literal.Split(":")
        if group <> ""
            if Len(group) > 4 then return false
            for position = 1 to Len(group)
                digit = Mid(group, position, 1)
                if not ((digit >= "0" and digit <= "9") or (digit >= "a" and digit <= "f")) then return false
            end for
            count = count + 1
        end if
    end for
    if compressed > 0 then return count < 8
    return count = 8
end function

function IsPrivateServerHost(host as String) as Boolean
    if host = "localhost" or host = "127.0.0.1" or host = "[::1]" then return true
    if Right(host, 6) = ".local" then return true
    octets = host.Split(".")
    if octets.Count() <> 4 then return false

    for each octet in octets
        if Len(octet) < 1 or Len(octet) > 3 then return false
        for position = 1 to Len(octet)
            digit = Mid(octet, position, 1)
            if digit < "0" or digit > "9" then return false
        end for
        if Val(octet) > 255 then return false
    end for

    first = Val(octets[0])
    second = Val(octets[1])
    if first = 10 then return true
    if first = 192 and second = 168 then return true
    if first = 172 and second >= 16 and second <= 31 then return true
    return false
end function
