sub init()
    m.top.functionName = "runServer"
end sub
sub runServer()
    m.port = CreateObject("roMessagePort")
    m.fs = CreateObject("roFileSystem")
    if not prepareAudio()
        m.top.failed = true
        return
    end if
    m.listener = CreateObject("roStreamSocket")
    m.listener.SetMessagePort(m.port)
    addr = CreateObject("roSocketAddress")
    addr.SetAddress("127.0.0.1:34831")
    if not m.listener.SetAddress(addr) or not m.listener.Listen(4)
        print "qa_setup error=4"
        m.top.failed = true
        return
    end if
    m.listener.NotifyReadable(true)
    m.clients = {}
    m.top.ready = true
    print "qa_server ready=1 routes=7"
    while not m.top.stopRequested
        event = Wait(1, m.port)
        if m.listener.IsReadable()
            sock = m.listener.Accept()
            if sock <> invalid
                if m.clients.Count() >= 4
                    sock.Close()
                else
                    sock.SetMessagePort(m.port)
                    sock.NotifyReadable(true)
                    sock.NotifyWritable(true)
                    timer = CreateObject("roTimespan")
                    m.clients[sock.GetID().ToStr()] = {socket: sock, request: "", sending: false, offset: 0, left: 0, pending: invalid, sent: 0, timer: timer}
                end if
            end if
        end if
        expired = []
        for each id in m.clients
            client = m.clients[id]
            keep = handleClient(client)
            if not keep or client.timer.TotalMilliseconds() > 30000 then expired.Push(id)
        end for
        for each id in expired
            m.clients[id].socket.Close()
            m.clients.Delete(id)
        end for
    end while
    for each id in m.clients
        m.clients[id].socket.Close()
    end for
    m.listener.Close()
    DeleteFile("tmp:/audio-init.mp4")
    DeleteFile("tmp:/audio.m4s")
    print "qa_server stopped=1"
end sub
function handleClient(c as Object) as Boolean
    sock = c.socket
    if not c.sending
        if not sock.IsReadable() then return true
        buffer = CreateObject("roByteArray")
        buffer[4095] = 0
        got = sock.Receive(buffer, 0, 4096)
        if got = 0 then return false
        if got < 0 then return sock.EOK()
        ' Only the bounded request headers become text. Binary media never does.
        c.request += buffer.Slice(0, got).ToAsciiString()
        if Len(c.request) > 8192 then return false
        if Instr(1, c.request, Chr(13) + Chr(10) + Chr(13) + Chr(10)) = 0 then return true
        parts = c.request.Split(Chr(13)+Chr(10))[0].Split(" ")
        if parts.Count() < 3 then return false
        requestPath = parts[1]
        route = m.routes.Lookup(requestPath)
        if route = invalid then return false
        stat = m.fs.Stat(route.path)
        if stat = invalid then return false
        c.path = route.path
        c.size = stat.size
        c.mime = route.mime
        plan = QaHttpPlan(c.request.Replace(requestPath,"/probe.mp4"), c.size)
        crlf = Chr(13) + Chr(10)
        statusText = "OK"
        if plan.status = 206 then statusText = "Partial Content"
        if plan.status = 416 then statusText = "Range Not Satisfiable"
        if plan.status = 400 then statusText = "Bad Request"
        if plan.status = 404 then statusText = "Not Found"
        if plan.status = 405 then statusText = "Method Not Allowed"
        bodySize = plan.count
        if plan.status <> 200 and plan.status <> 206 then bodySize = 0
        header = "HTTP/1.1 " + plan.status.ToStr() + " " + statusText + crlf
        header += "Content-Type: " + c.mime + crlf + "Accept-Ranges: bytes" + crlf
        header += "Content-Length: " + bodySize.ToStr() + crlf + "Connection: close" + crlf
        if plan.status = 206
            last = plan.start + plan.count - 1
            header += "Content-Range: bytes " + plan.start.ToStr() + "-" + last.ToStr() + "/" + c.size.ToStr() + crlf
        else if plan.status = 416
            header += "Content-Range: bytes */" + c.size.ToStr() + crlf
        end if
        c.pending = CreateObject("roByteArray")
        c.pending.FromAsciiString(header + crlf)
        c.offset = plan.start
        c.left = bodySize
        if plan.head then c.left = 0
        c.sending = true
        c.request = ""
        print "qa_http route="; route.id; " status="; plan.status; " head="; plan.head; " start="; plan.start; " count="; bodySize
    end if
    if not sock.IsWritable() then return true
    if c.pending = invalid
        if c.left = 0 then return false
        amount = c.left
        if amount > 65536 then amount = 65536
        c.pending = CreateObject("roByteArray")
        if not c.pending.ReadFile(c.path, c.offset, amount) then return false
        if c.pending.Count() <> amount then return false
        c.offset += amount
        c.left -= amount
        c.sent = 0
    end if
    sent = sock.Send(c.pending, c.sent, c.pending.Count() - c.sent)
    if sent < 0 then return sock.EOK()
    c.sent += sent
    if sent > 0 then c.timer.Mark()
    if c.sent = c.pending.Count()
        c.pending = invalid
        c.sent = 0
        if c.left = 0 then return false
    end if
    return true
end function

function prepareAudio() as Boolean
    stat = m.fs.Stat("pkg:/images/video.m4s")
    if stat = invalid then return false
    if stat.size < 1 or stat.size > 25165824 then return false
    timer = CreateObject("roTimespan")
    init = CreateObject("roByteArray")
    fragment = CreateObject("roByteArray")
    if not init.ReadFile("pkg:/images/init.mp4") then return false
    audioTrack = QaAudioTrack(init)
    if audioTrack = invalid then return false
    if not fragment.ReadFile("pkg:/images/video.m4s") then return false
    plan = QaAudioSamples(init,fragment)
    if not plan.ok
        print "qa_extract error=1"
        return false
    end if
    parsed = timer.TotalMilliseconds()
    result = QaAudioFmp4(init,fragment,plan)
    if not result.ok
        print "qa_extract error=2"
        return false
    end if
    if not result.init.WriteFile("tmp:/audio-init.mp4") then return false
    if not result.fragment.WriteFile("tmp:/audio.m4s") then return false
    totalDuration = 0
    for each sample in plan.samples
        totalDuration += sample.duration
    end for
    audioSeconds = totalDuration / plan.timescale
    durationText = audioSeconds.ToStr().Trim()
    lf = Chr(10)
    video = "#EXTM3U"+lf+"#EXT-X-VERSION:7"+lf+"#EXT-X-TARGETDURATION:7"+lf+"#EXT-X-MEDIA-SEQUENCE:0"+lf+"#EXT-X-PLAYLIST-TYPE:VOD"+lf+"#EXT-X-MAP:URI="+Chr(34)+"init.mp4"+Chr(34)+lf+"#EXTINF:6.333000,"+lf+"video.m4s"+lf+"#EXT-X-ENDLIST"+lf
    audio = "#EXTM3U"+lf+"#EXT-X-VERSION:7"+lf+"#EXT-X-TARGETDURATION:7"+lf+"#EXT-X-MEDIA-SEQUENCE:0"+lf+"#EXT-X-PLAYLIST-TYPE:VOD"+lf+"#EXT-X-MAP:URI="+Chr(34)+"audio-init.mp4"+Chr(34)+lf+"#EXTINF:"+durationText+","+lf+"audio.m4s"+lf+"#EXT-X-ENDLIST"+lf
    master = "#EXTM3U"+lf+"#EXT-X-VERSION:7"+lf+"#EXT-X-INDEPENDENT-SEGMENTS"+lf+"#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="+Chr(34)+"qa_audio"+Chr(34)+",NAME="+Chr(34)+"qa_audio"+Chr(34)+",DEFAULT=YES,AUTOSELECT=YES,LANGUAGE="+Chr(34)+"en"+Chr(34)+",URI="+Chr(34)+"audio.m3u8"+Chr(34)+lf+"#EXT-X-STREAM-INF:BANDWIDTH=12000000,CODECS="+Chr(34)+"hvc1.2.4.L150.90,"+audioTrack.codec+Chr(34)+",AUDIO="+Chr(34)+"qa_audio"+Chr(34)+",VIDEO-RANGE=PQ"+lf+"video.m3u8"+lf
    if not WriteAsciiFile("tmp:/video.m3u8",video) then return false
    if not WriteAsciiFile("tmp:/audio.m3u8",audio) then return false
    if not WriteAsciiFile("tmp:/master.m3u8",master) then return false
    print "qa_extract error=0 parse_ms="; parsed; " elapsed_ms="; timer.TotalMilliseconds(); " samples="; plan.samples.Count(); " source_bytes="; fragment.Count(); " audio_bytes="; plan.bytes; " init_bytes="; result.init.Count(); " media_bytes="; result.fragment.Count(); " first_pts="; plan.samples[0].pts; " timescale="; plan.timescale
    m.routes = {}
    m.routes["/master.m3u8"] = {id:1,path:"tmp:/master.m3u8",mime:"application/vnd.apple.mpegurl"}
    m.routes["/video.m3u8"] = {id:2,path:"tmp:/video.m3u8",mime:"application/vnd.apple.mpegurl"}
    m.routes["/audio.m3u8"] = {id:3,path:"tmp:/audio.m3u8",mime:"application/vnd.apple.mpegurl"}
    m.routes["/init.mp4"] = {id:4,path:"pkg:/images/init.mp4",mime:"video/mp4"}
    m.routes["/video.m4s"] = {id:5,path:"pkg:/images/video.m4s",mime:"video/mp4"}
    m.routes["/audio-init.mp4"] = {id:6,path:"tmp:/audio-init.mp4",mime:"audio/mp4"}
    m.routes["/audio.m4s"] = {id:7,path:"tmp:/audio.m4s",mime:"audio/mp4"}
    return true
end function
