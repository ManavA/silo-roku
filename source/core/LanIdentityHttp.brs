' Fixed-endpoint HTTP framing. No URLs, redirect handling, or credentials enter here.
function LanIdentityHttpCreate() as Object
    return {done:false,errorCode:"",phase:"headers",line:"",cr:false,headerBytes:0,wire:0,body:CreateObject("roByteArray"),remaining:0,length:-1,chunked:false,encoding:false,status:false,chunks:0,trailerBytes:0}
end function

function LanIdentityHttpFail(state as Object, code = "invalid_response" as String) as Object
    state.done = true
    state.errorCode = code
    state.body.Clear()
    return state
end function

function LanIdentityHttpFeed(state as Object, packet as Object) as Object
    for each byte in packet
        if state.done then return state
        state.wire = state.wire + 1
        if state.wire > 32768 then return LanIdentityHttpFail(state,"response_too_large")
        if state.phase = "body"
            ' ToAsciiString truncates at NUL; JSON permits no raw NUL byte.
            if byte = 0 then return LanIdentityHttpFail(state)
            if state.body.Count() >= 16384 then return LanIdentityHttpFail(state,"response_too_large")
            state.body.Push(byte)
            state.remaining = state.remaining - 1
            if state.remaining = 0
                if state.chunked
                    state.phase = "chunkEnd"
                else
                    state.done = true
                end if
            end if
        else
            if state.phase = "chunkEnd" and not state.cr and byte <> 13 then return LanIdentityHttpFail(state)
            if state.phase = "headers"
                state.headerBytes = state.headerBytes + 1
                if state.headerBytes > 4096 then return LanIdentityHttpFail(state,"response_too_large")
            end if
            if state.phase = "trailers"
                state.trailerBytes = state.trailerBytes + 1
                if state.trailerBytes > 1024 then return LanIdentityHttpFail(state,"response_too_large")
            end if
            if state.phase = "chunkSize" and Len(state.line) >= 128 and byte <> 13 and byte <> 10 then return LanIdentityHttpFail(state,"response_too_large")
            if state.cr
                if byte <> 10 then return LanIdentityHttpFail(state)
                state.cr = false
                state = LanIdentityHttpLine(state)
                state.line = ""
            else if byte = 13
                state.cr = true
            else
                if byte < 32 or byte > 126 then return LanIdentityHttpFail(state)
                state.line = state.line + Chr(byte)
            end if
        end if
    end for
    return state
end function

function LanIdentityHttpLine(state as Object) as Object
    line = state.line
    if state.phase = "chunkEnd"
        if line <> "" then return LanIdentityHttpFail(state)
        state.phase = "chunkSize"
        return state
    end if
    if state.phase = "chunkSize"
        if Len(line) < 1 or Len(line) > 128 then return LanIdentityHttpFail(state)
        ' Extensions are unnecessary for this endpoint and are rejected.
        if not CreateObject("roRegex","^[0-9a-fA-F]{1,8}$","").IsMatch(line) then return LanIdentityHttpFail(state)
        count = 0
        for index = 1 to Len(line)
            digit = Instr(1,"0123456789abcdef",LCase(Mid(line,index,1))) - 1
            count = count * 16 + digit
            if count > 16384 - state.body.Count() then return LanIdentityHttpFail(state,"response_too_large")
        end for
        state.chunks = state.chunks + 1
        if state.chunks > 128 then return LanIdentityHttpFail(state,"response_too_large")
        if count = 0
            state.phase = "trailers"
        else
            state.remaining = count
            state.phase = "body"
        end if
        return state
    end if
    if state.phase = "trailers" and line = ""
        state.done = true
        return state
    end if
    if not state.status
        if not CreateObject("roRegex","^HTTP/1\.[01] 200( [ -~]*)?$","").IsMatch(line) then return LanIdentityHttpFail(state,"http_status")
        state.status = true
        return state
    end if
    if line = ""
        if state.chunked
            if state.length >= 0 then return LanIdentityHttpFail(state)
            state.phase = "chunkSize"
            return state
        end if
        if state.length < 0 then return LanIdentityHttpFail(state)
        state.remaining = state.length
        state.phase = "body"
        if state.remaining = 0 then state.done = true
        return state
    end if
    colon = Instr(1,line,":")
    if colon < 2 then return LanIdentityHttpFail(state)
    name = LCase(Left(line,colon-1))
    if not CreateObject("roRegex","^[!#$%&'*+.^_`|~0-9a-z-]+$","").IsMatch(name) then return LanIdentityHttpFail(state)
    value = Mid(line,colon+1).Trim()
    if state.phase = "trailers"
        if name = "content-length" or name = "transfer-encoding" or name = "content-encoding" then return LanIdentityHttpFail(state)
        return state
    end if
    if name = "content-encoding"
        if state.encoding or LCase(value) <> "identity" then return LanIdentityHttpFail(state)
        state.encoding = true
    end if
    if name = "transfer-encoding"
        if state.chunked or LCase(value) <> "chunked" or state.length >= 0 then return LanIdentityHttpFail(state)
        state.chunked = true
    end if
    if name = "content-length"
        if state.chunked then return LanIdentityHttpFail(state)
        if state.length >= 0 then return LanIdentityHttpFail(state)
        if not CreateObject("roRegex","^(0|[1-9][0-9]{0,4})$","").IsMatch(value) then return LanIdentityHttpFail(state)
        state.length = value.ToInt()
        if state.length > 16384 then return LanIdentityHttpFail(state,"response_too_large")
    end if
    return state
end function
