sub init()
    m.top.functionName = "runLanDiscovery"
end sub

sub runLanDiscovery()
    job = m.top.job
    if job = invalid then return
    token = job.token
    generation = job.generation
    m.lanClock = CreateObject("roTimespan")
    m.lanClock.Mark()
    result = {token: token, generation: generation, status: "unavailable", candidates: [], received: 0, sent: 0, oversized: 0}
    socket = invalid
    if not LanTaskCancelled(token, generation) then socket = LanTaskOpen()
    if socket <> invalid
        state = LanDiscoveryCreate(0)
        schedule = [0, 1000, 3000]
        result.status = "complete"
        while true
            now = LanTaskElapsed()
            if LanTaskCancelled(token, generation) then exit while
            state = LanDiscoveryAdvance(state, now)
            if now >= 5000 or result.received >= 64 then exit while
            if result.sent < 3
                if now >= schedule[result.sent]
                    if not LanTaskSend(socket)
                        result.status = "unavailable"
                        exit while
                    end if
                    result.sent = result.sent + 1
                end if
            end if
            event = LanTaskReceive(socket)
            now = LanTaskElapsed()
            if LanTaskCancelled(token, generation) then exit while
            if now >= 5000 then exit while
            if event <> invalid
                if event.size < 0
                    result.status = "unavailable"
                    exit while
                end if
                result.received = result.received + 1
                if event.size > 9000
                    result.oversized = result.oversized + 1
                else
                    state = LanDiscoveryReduce(state, event.packet, event.sender, event.port, now)
                end if
            else
                delay = 25
                if 5000 - now < delay then delay = 5000 - now
                LanTaskPause(delay)
            end if
        end while
        state = LanDiscoveryAdvance(state, LanTaskElapsed())
        if result.status = "complete" then result.candidates = state.candidates
        LanTaskClose(socket)
    end if
    ' A cancelled or replaced job never publishes its prior generation.
    if LanTaskCancelled(token, generation) then return
    m.top.result = result
end sub

function LanTaskCancelled(token as Dynamic, generation as Dynamic) as Boolean
    if m.top.cancelled then return true
    job = m.top.job
    if job = invalid then return true
    return job.token <> token or job.generation <> generation
end function

function LanTaskElapsed() as Integer
    return m.lanClock.TotalMilliseconds()
end function

sub LanTaskPause(delay as Integer)
    event = wait(delay, m.lanPort)
end sub

function LanTaskOpen() as Dynamic
    socket = CreateObject("roDataGramSocket")
    if socket = invalid then return invalid
    m.lanPort = CreateObject("roMessagePort")
    socket.SetMessagePort(m.lanPort)
    socket.SetReuseAddr(true)
    address = CreateObject("roSocketAddress")
    group = CreateObject("roSocketAddress")
    ready = socket.GetReuseAddr()
    if ready then ready = address.SetAddress("0.0.0.0:5353")
    if ready then ready = socket.SetAddress(address)
    if ready
        actual = socket.GetAddress()
        ready = actual <> invalid
        if ready then ready = actual.GetPort() = 5353
    end if
    if ready then ready = group.SetAddress("224.0.0.251:5353")
    if ready then ready = socket.JoinGroup(group)
    if ready then ready = socket.SetMulticastTTL(255)
    if ready then ready = socket.GetMulticastTTL() = 255
    if ready then ready = socket.SetSendToAddress(group)
    if not ready
        socket.Close()
        return invalid
    end if
    socket.NotifyReadable(true)
    return socket
end function

function LanTaskSend(socket as Object) as Boolean
    query = CreateObject("roByteArray")
    query.FromHexString("000000000001000000000000055F73696C6F045F746370056C6F63616C00000C0001")
    return socket.Send(query, 0, query.Count()) = query.Count()
end function

function LanTaskReceive(socket as Object) as Dynamic
    if not socket.IsReadable() then return invalid
    buffer = CreateObject("roByteArray")
    buffer.SetResize(9001, false)
    ' SetResize reserves capacity; indexed assignment establishes readable length.
    buffer[9000] = 0
    count = socket.Receive(buffer, 0, 9001)
    result = {size: count, packet: [], sender: "", port: 0}
    if count < 0 or count > 9000 then return result
    peer = socket.GetReceivedFromAddress()
    if peer <> invalid
        literal = peer.GetAddress()
        parts = literal.Split(":")
        if parts.Count() = 2
            result.sender = parts[0]
            result.port = peer.GetPort()
        end if
    end if
    for index = 0 to count - 1
        result.packet.Push(buffer[index])
    end for
    return result
end function

sub LanTaskClose(socket as Object)
    socket.NotifyReadable(false)
    socket.Close()
end sub
