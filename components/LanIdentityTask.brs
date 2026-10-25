sub init()
    m.top.functionName = "runLanIdentity"
end sub

sub runLanIdentity()
    job = m.top.job
    if type(job) <> "roAssociativeArray" then return
    token = job.token
    generation = job.generation
    m.identityClock = CreateObject("roTimespan")
    m.identityClock.Mark()
    request = LanIdentityRequest(job.candidates,job.selected)
    result = request
    socket = invalid
    if request.ok and not IdentityTaskCancelled(token,generation)
        socket = IdentityTaskOpen(request)
        result = {ok:false,errorCode:"network_unavailable"}
        if socket <> invalid
            bytes = CreateObject("roByteArray")
            crlf = Chr(13) + Chr(10)
            bytes.FromAsciiString("GET /api/v2/system/identity HTTP/1.1" + crlf + "Host: " + request.address + ":" + StrI(request.port).Trim() + crlf + "Accept: application/json" + crlf + "Accept-Encoding: identity" + crlf + "Connection: close" + crlf + crlf)
            offset = 0
            state = LanIdentityHttpCreate()
            result = {ok:false,errorCode:"network_timeout"}
            connected = false
            while IdentityTaskElapsed() < 5000
                if IdentityTaskCancelled(token,generation) then exit while
                ready = 1
                if not connected then ready = IdentityTaskReady(socket)
                if ready < 0
                    result = {ok:false,errorCode:"network_error"}
                    exit while
                end if
                if ready = 1
                    ' A closed peer may still have response bytes waiting to be read.
                    connected = true
                    if offset < bytes.Count()
                        count = IdentityTaskSend(socket,bytes,offset)
                        if count < 0 or count > bytes.Count() - offset
                            result = {ok:false,errorCode:"network_error"}
                            exit while
                        end if
                        offset = offset + count
                    else
                        event = IdentityTaskReceive(socket,1024)
                        if IdentityTaskCancelled(token,generation) or IdentityTaskElapsed() >= 5000 then exit while
                        if event <> invalid
                            if event.DoesExist("error") or event.DoesExist("eof")
                                result = {ok:false,errorCode:"network_error"}
                                exit while
                            end if
                            state = LanIdentityHttpFeed(state,event.packet)
                            if state.done
                                if state.errorCode <> ""
                                    result = {ok:false,errorCode:state.errorCode}
                                else
                                    body = state.body.ToAsciiString()
                                    state.body.Clear()
                                    result = LanIdentityDecode(job.candidates[job.selected],body)
                                    if IdentityTaskElapsed() >= 5000 then result = {ok:false,errorCode:"network_timeout"}
                                end if
                                exit while
                            end if
                        end if
                    end if
                end if
                delay = 25
                if 5000 - IdentityTaskElapsed() < delay then delay = 5000 - IdentityTaskElapsed()
                if delay > 0 then IdentityTaskPause(delay)
            end while
            IdentityTaskClose(socket)
        end if
    end if
    if IdentityTaskCancelled(token,generation) then return
    result.token = token
    result.generation = generation
    m.top.result = result
end sub

function IdentityTaskCancelled(token as Dynamic, generation as Dynamic) as Boolean
    if m.top.cancelled then return true
    job = m.top.job
    if job = invalid then return true
    return job.token <> token or job.generation <> generation
end function

function IdentityTaskElapsed() as Integer
    return m.identityClock.TotalMilliseconds()
end function

sub IdentityTaskPause(delay as Integer)
    event = wait(delay,m.identityPort)
end sub

function IdentityTaskOpen(request as Object) as Dynamic
    socket = CreateObject("roStreamSocket")
    if socket = invalid then return invalid
    m.identityPort = CreateObject("roMessagePort")
    address = CreateObject("roSocketAddress")
    if m.identityPort = invalid or address = invalid
        socket.Close()
        return invalid
    end if
    socket.SetMessagePort(m.identityPort)
    ready = address.SetAddress(request.address + ":" + StrI(request.port).Trim())
    if ready then ready = socket.SetSendToAddress(address)
    if not ready
        socket.Close()
        return invalid
    end if
    connected = socket.Connect()
    if not connected and not socket.eOK()
        socket.Close()
        return invalid
    end if
    return socket
end function

function IdentityTaskReady(socket as Object) as Integer
    if not socket.eOK() then return -1
    if socket.IsConnected() or socket.IsWritable() then return 1
    return 0
end function

function IdentityTaskSend(socket as Object, bytes as Object, offset as Integer) as Integer
    if not socket.IsWritable() then return 0
    count = socket.Send(bytes,offset,bytes.Count()-offset)
    if count < 0 and socket.eOK() then return 0
    return count
end function

function IdentityTaskReceive(socket as Object, limit as Integer) as Dynamic
    if not socket.IsReadable() then return invalid
    buffer = CreateObject("roByteArray")
    buffer[limit-1] = 0
    count = socket.Receive(buffer,0,limit)
    if count < 0
        if socket.eOK() then return invalid
        return {error:true}
    end if
    if count = 0 then return {eof:true}
    if count > limit then return {error:true}
    while buffer.Count() > count
        buffer.Pop()
    end while
    return {packet:buffer}
end function

sub IdentityTaskClose(socket as Object)
    socket.NotifyReadable(false)
    socket.NotifyWritable(false)
    socket.Close()
end sub
