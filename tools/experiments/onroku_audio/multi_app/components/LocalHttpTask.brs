sub init()
    m.top.functionName = "runServer"
end sub
sub runServer()
    if m.top.stockOnly = true then m.top.drainState = "pending"
    m.rolling = invalid
    m.audioPaths = []
    m.clients = {}
    m.remoteActive = invalid
    m.listener = invalid
    m.stopObserved = false
    try
        runServerWork()
    catch taskError
        print "qa_server error=1"
        m.top.failed = true
    end try
    cleanupServer()
    if m.acceptCount <> invalid
        print "qa_http_pressure episodes="; m.deferEpisodes; " loops="; m.deferLoops
        print "qa_server stopped=1 accepted="; m.acceptCount; " rejected="; m.rejectCount; " peak="; m.peakClients; " cap="; m.clientCap
    end if
end sub
sub runServerWork()
    m.port = CreateObject("roMessagePort")
    m.fs = CreateObject("roFileSystem")
    m.clock = CreateObject("roTimespan")
    m.memory = CreateObject("roAppMemoryMonitor")
    m.minAvailable = -1
    m.maxUsage = -1
    m.stopPollMs = 0
    m.loopCount = 0
    m.lastMemory = 0
    m.stopLocal = false
    if not m.top.ObserveField("stopRequested",m.port)
        print "qa_stop observer=0"
        m.top.failed = true
        return
    end if
    m.stopObserved = true
    for each controlField in ["playbackPosition","seekRequest","seekAck","playbackUpdate"]
        m.top.ObserveField(controlField,m.port)
    end for
    QaSeekInit()
    ' Subscribe first, then read once so neither an existing stop nor a
    ' transition during startup can be lost. Cancellation is monotonic.
    m.stopLocal = m.top.stopRequested
    drainStopEvents()
    if m.stopLocal then return
    if m.top.stockOnly = true and not StockEngineContextValid()
        m.top.failed = true
        return
    end if
    config = invalid
    if m.top.stockOnly <> true then config = ParseJson(ReadAsciiFile("pkg:/images/config.json"))
    m.rollingTelemetryEnabled=false
    if config<>invalid then m.rollingTelemetryEnabled=config.rollingTelemetry=true
    rolling = false
    if config <> invalid then rolling = config.rolling = true and config.remoteOwnedNoAuth = true
    stock=m.top.stockContext
    if stock<>invalid
        rolling=true
        if not QaStockContextValid(stock)
            m.top.failed=true
            return
        end if
        ' The auth adapter/caller supplies the complete bound descriptor URL.
        if Type(stock.playlist)<>"roString" and Type(stock.playlist)<>"String"
            m.top.failed=true
            return
        end if
        QaRollingStart(stock.playlist,stock)
    else if rolling
        QaRollingStart(config.remotePlaylist)
    else if not prepareAudio()
        if not m.stopLocal then m.top.failed = true
        return
    end if
    for each controlField in ["playbackPosition","seekRequest","seekAck","playbackUpdate"]
        QaSeekHandleField(controlField,m.top[controlField])
    end for
    drainStopEvents()
    if m.stopLocal
        print "qa_server stopped_before_ready=1"
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
    m.clientCap = 4
    m.acceptCount = 0
    m.rejectCount = 0
    m.peakClients = 0
    m.deferEpisodes = 0
    m.deferLoops = 0
    m.wasDeferred = false
    if not rolling then m.top.ready = true
    print "qa_server ready=1 routes="; m.routes.Count(); " wall_ms="; m.clock.TotalMilliseconds()
    while true
        m.loopCount += 1
        drainStopEvents()
        if m.stopLocal then exit while
        if rolling then QaRollingTick()
        if m.clock.TotalMilliseconds()-m.lastMemory >= 1000
            observeMemory(3)
            m.lastMemory = m.clock.TotalMilliseconds()
        end if
        event = Wait(1,m.port)
        acceptStopEvent(event)
        drainStopEvents()
        if m.stopLocal then exit while
        readable = m.listener.IsReadable()
        readyToAccept = QaAcceptReady(m.clients.Count(),m.clientCap,readable,m.stopLocal)
        deferred = readable and not readyToAccept
        if deferred
            m.deferLoops += 1
            if not m.wasDeferred
                m.deferEpisodes += 1
                print "qa_http_defer episode="; m.deferEpisodes; " active="; m.clients.Count(); " cap="; m.clientCap; " loops="; m.deferLoops; " wall_ms="; m.clock.TotalMilliseconds()
            end if
        else if m.wasDeferred
            print "qa_http_defer_end episode="; m.deferEpisodes; " active="; m.clients.Count(); " loops="; m.deferLoops; " wall_ms="; m.clock.TotalMilliseconds()
        end if
        m.wasDeferred = deferred
        ' Never accept-and-close for saturation: retain pending connections in
        ' the existing bounded TCP backlog while servicing active sockets.
        if readyToAccept
            sock = m.listener.Accept()
            if sock <> invalid
                m.acceptCount += 1
                sock.SetMessagePort(m.port)
                sock.NotifyReadable(true)
                sock.NotifyWritable(true)
                timer = CreateObject("roTimespan")
                m.clients[sock.GetID().ToStr()] = {socket: sock, request: "", sending: false, offset: 0, left: 0, pending: invalid, sent: 0, timer: timer, acceptMs: m.clock.TotalMilliseconds(), headerMs: -1, firstMs: -1, lastMs: -1, wireBytes: 0, expected: 0, calls: 0, retries: 0, partials: 0, maxIdle: 0, routeId: 0, readMs: 0, readCalls: 0, sendMs: 0, writableWaits: 0}
                if m.clients.Count() > m.peakClients then m.peakClients = m.clients.Count()
                print "qa_http_accept id="; m.acceptCount; " active="; m.clients.Count(); " peak="; m.peakClients; " rejected="; m.rejectCount; " wall_ms="; m.clock.TotalMilliseconds()
            end if
        end if
        expired = []
        for each id in m.clients
            client = m.clients[id]
            keep = handleClient(client)
            if not keep or client.timer.TotalMilliseconds() > 30000 then expired.Push(id)
        end for
        for each id in expired
            done = m.clients[id]
            closeStart = m.clock.TotalMilliseconds()
            closeClient(done)
            print "qa_http_done route="; done.routeId; " accept_ms="; done.acceptMs; " header_ms="; done.headerMs; " first_ms="; done.firstMs; " last_ms="; done.lastMs; " close_ms="; m.clock.TotalMilliseconds()
            print "qa_http_bytes route="; done.routeId; " wire="; done.wireBytes; " expected="; done.expected; " calls="; done.calls; " partials="; done.partials; " retries="; done.retries
            print "qa_http_loop route="; done.routeId; " max_idle_ms="; done.maxIdle; " stop_poll_ms="; m.stopPollMs; " loops="; m.loopCount
            print "qa_http_io route="; done.routeId; " read_ms="; done.readMs; " read_calls="; done.readCalls; " send_ms="; done.sendMs; " writable_waits="; done.writableWaits
            m.clients.Delete(id)
        end for
    end while
end sub
function StockEngineContextValid() as Boolean
    stock = m.top.stockContext
    if stock = invalid then return false
    if not QaStockContextValid(stock) then return false
    if Type(stock.playlist) <> "roString" and Type(stock.playlist) <> "String" then return false
    bound = QaStockMediaReference(stock.playlist,stock.playlist,stock.origin,stock.routeItemId,stock.mediaSourceId,stock.sessionId)
    if bound = invalid or bound <> stock.playlist then return false
    return Instr(1,stock.playlist,"/hls/"+stock.sessionId+"/stream.m3u8?") > 0
end function
function handleClient(c as Object) as Boolean
    sock = c.socket
    idle = c.timer.TotalMilliseconds()
    if idle > c.maxIdle then c.maxIdle = idle
    if not c.sending
        if not c.DoesExist("parsed")
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
            c.parsed=true
        end if
        if not c.DoesExist("requestPath")
            parts = c.request.Split(Chr(13)+Chr(10))[0].Split(" ")
            if parts.Count() < 3 then return false
            c.requestPath=parts[1]
        end if
        requestPath=c.requestPath
        route = m.routes.Lookup(requestPath)
        ' Once accepted, a response owns its immutable route across publications.
        if c.DoesExist("route") then route=c.route
        unavailable = route = invalid
        if unavailable then route = {id:0,path:"",mime:"application/octet-stream"}
        recovery=false
        if unavailable then recovery=QaRollingRetiredPath(requestPath)
        if m.rolling<>invalid and not unavailable
            if not c.DoesExist("route")
                QaRoutePin(route):c.route=route
                c.waitAt=m.clock.TotalMilliseconds()
            end if
            owner=m.rolling
            if route.DoesExist("owner") then owner=route.owner
            if owner.DoesExist("lifecycle")
                if owner.lifecycle="retired" then recovery=true
            end if
            if route.DoesExist("entry") and not recovery
                entry=owner.entries[route.entry]
                if not entry.resident
                    if not owner.failed and m.clock.TotalMilliseconds()-c.waitAt<owner.recoveryMs
                        if QaRollingDemand(owner,route.entry)
                            ' Poll peer close without blocking any other socket.
                            if sock.IsReadable()
                                discard=CreateObject("roByteArray"):discard[0]=0
                                received=sock.Receive(discard,0,1)
                                if received=0 then return false
                            end if
                            return true
                        end if
                    end if
                    recovery=true
                end if
            end if
        end if
        stat=m.fs.Stat(route.path)
        if stat=invalid then stat={}
        if not stat.DoesExist("size")
            if m.rolling<>invalid and not unavailable
                recovery=true
            else
                unavailable=true
            end if
            stat={size:0}
        end if
        c.headerMs = m.clock.TotalMilliseconds()
        c.routeId = route.id
        c.path = route.path
        c.size = stat.size
        c.mime = route.mime
        plan = QaHttpPlan(c.request.Replace(requestPath,"/probe.mp4"), c.size)
        if unavailable then plan.status = 404
        if recovery then plan.status=503
        crlf = Chr(13) + Chr(10)
        statusText = "OK"
        if plan.status = 206 then statusText = "Partial Content"
        if plan.status = 416 then statusText = "Range Not Satisfiable"
        if plan.status = 400 then statusText = "Bad Request"
        if plan.status = 404 then statusText = "Not Found"
        if plan.status = 405 then statusText = "Method Not Allowed"
        if plan.status = 503 then statusText = "Service Unavailable"
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
        c.expected = c.pending.Count()
        if not plan.head then c.expected += bodySize
        c.offset = plan.start
        c.left = bodySize
        if plan.head then c.left = 0
        c.sending = true
        c.Delete("parsed")
        c.Delete("requestPath")
        c.request = ""
        print "qa_http route="; route.id; " status="; plan.status; " head="; plan.head; " start="; plan.start; " count="; bodySize
    end if
    if not sock.IsWritable()
        c.writableWaits += 1
        return true
    end if
    if c.pending = invalid
        if c.left = 0 then return false
        amount = c.left
        if amount > 65536 then amount = 65536
        c.pending = CreateObject("roByteArray")
        readStart = m.clock.TotalMilliseconds()
        readOk = c.pending.ReadFile(c.path, c.offset, amount)
        c.readMs += m.clock.TotalMilliseconds()-readStart
        c.readCalls += 1
        if not readOk then return false
        if c.pending.Count() <> amount then return false
        c.offset += amount
        c.left -= amount
        c.sent = 0
    end if
    remaining = c.pending.Count()-c.sent
    sendStart = m.clock.TotalMilliseconds()
    sent = sock.Send(c.pending,c.sent,remaining)
    c.sendMs += m.clock.TotalMilliseconds()-sendStart
    c.calls += 1
    if sent <= 0 then c.retries += 1
    if sent < 0 then return sock.EOK()
    c.wireBytes += sent
    if sent > 0
        if c.firstMs < 0 then c.firstMs = m.clock.TotalMilliseconds()
        c.lastMs = m.clock.TotalMilliseconds()
        if sent < remaining then c.partials += 1
    end if
    c.sent += sent
    if sent > 0 then c.timer.Mark()
    if c.sent = c.pending.Count()
        c.pending = invalid
        c.sent = 0
        if c.left = 0 then return false
    end if
    return true
end function

' A released generation has no per-fragment tombstones. Session high-water is
' monotonic; live generations remain in the session until their pins drain.
function QaRollingRetiredPath(requestPath as String) as Boolean
    if m.rollingSession=invalid then return false
    if m.rollingSession.maxGeneration=invalid then return false
    if Left(requestPath,2)<>"/g" then return false
    slash=Instr(3,requestPath,"/")
    if slash<4 or slash>19 then return false
    digits=Mid(requestPath,3,slash-3)
    generation=0#
    for i=1 to Len(digits)
        ch=Asc(Mid(digits,i,1))
        if ch<48 or ch>57 then return false
        generation=generation*10#+ch-48
        if generation>m.rollingSession.maxGeneration then return false
    end for
    if generation<1 then return false
    for each live in m.rollingSession.generations
        if live.generation=generation then return false
    end for
    return true
end function

sub observeMemory(stage as Integer)
    if m.memory = invalid then return
    try
        available = m.memory.GetChannelAvailableMemory()
        usage = m.memory.GetMemoryLimitPercent()
        if available >= 0
            if m.minAvailable < 0 or available < m.minAvailable then m.minAvailable = available
        end if
        if usage > m.maxUsage then m.maxUsage = usage
        print "qa_memory stage="; stage; " available_kb="; available; " min_available_kb="; m.minAvailable; " usage_pct="; usage; " max_usage_pct="; m.maxUsage
    catch memoryError
        print "qa_memory supported=0"
        m.memory = invalid
    end try
end sub
function prepareAudio() as Boolean
    config = ParseJson(ReadAsciiFile("pkg:/images/config.json"))
    if config = invalid then return false
    sourceInit = "pkg:/images/init.mp4"
    sourcePaths = []
    remote = config.remoteOwnedNoAuth = true
    if remote
        descriptor = QaRemoteIngest(config.remotePlaylist)
        if descriptor = invalid then return false
        sourceInit = descriptor.init
        sourcePaths = descriptor.fragments
        config.videoDurations = descriptor.durations
        config.cacheVideo = false
    else
        for index = 0 to config.videoDurations.Count()-1
            sourcePaths.Push("pkg:/images/video-"+Right("0000"+index.ToStr(),4)+".m4s")
        end for
    end if
    count = config.videoDurations.Count()
    if count < 3 or count > 16 then return false
    if config.generation <> 1 then return false
    prefix = "/g1/"
    totalSource = 0
    m.cacheBytes = 0
    for index = 0 to count-1
        drainStopEvents()
        if m.stopLocal then return false
        suffix = Right("0000"+index.ToStr(),4)
        stat = m.fs.Stat(sourcePaths[index])
        if stat = invalid then return false
        if stat.size < 1 then return false
        totalSource += stat.size
        if totalSource > 25165824 then return false
    end for
    stat = m.fs.Stat(sourceInit)
    if stat = invalid then return false
    if stat.size < 1 or stat.size > 1048576 then return false
    if totalSource+stat.size > 25165824 then return false
    observeMemory(0)
    timer = CreateObject("roTimespan")
    init = CreateObject("roByteArray")
    if not init.ReadFile(sourceInit) then return false
    audioTrack = QaAudioTrack(init)
    if audioTrack = invalid then return false
    window = {ok:true,count:0,sourceBytes:init.Count(),audioBytes:0,nextPts:-1,timescale:0,trackid:0}
    m.routes = {}
    m.routes[prefix+"master.m3u8"] = {id:1,path:"tmp:/g1-master.m3u8",mime:"application/vnd.apple.mpegurl"}
    m.routes[prefix+"video.m3u8"] = {id:2,path:"tmp:/g1-video.m3u8",mime:"application/vnd.apple.mpegurl"}
    m.routes[prefix+"audio.m3u8"] = {id:3,path:"tmp:/g1-audio.m3u8",mime:"application/vnd.apple.mpegurl"}
    m.routes[prefix+"init.mp4"] = {id:4,path:sourceInit,mime:"video/mp4"}
    m.routes[prefix+"audio-init.mp4"] = {id:6,path:"tmp:/g1-audio-init.mp4",mime:"audio/mp4"}
    lf = Chr(10)
    videoLines = ""
    audioLines = ""
    maxDuration = 0
    totalSamples = 0
    for index = 0 to count-1
        drainStopEvents()
        if m.stopLocal then return false
        stepClock = CreateObject("roTimespan")
        suffix = Right("0000"+index.ToStr(),4)
        sourcePath = sourcePaths[index]
        stat = m.fs.Stat(sourcePath)
        if stat = invalid then return false
        if stat.size < 1 or stat.size > 25165824 then return false
        if remote
            if m.clock.TotalMilliseconds()-m.remoteStarted >= 120000 then return false
        end if
        fragment = CreateObject("roByteArray")
        if not fragment.ReadFile(sourcePath) then return false
        plan = QaAudioSamples(init,fragment)
        if not plan.ok
            print "qa_extract error=1 index="; index
            return false
        end if
        parseMs = stepClock.TotalMilliseconds()
        result = QaAudioFmp4(init,fragment,plan)
        if not result.ok then return false
        outputBytes = result.fragment.Count()
        if index = 0 then outputBytes += result.init.Count()
        nextWindow = QaMultiAccept(window,plan,fragment.Count(),outputBytes)
        if not nextWindow.ok
            print "qa_extract error=3 index="; index
            return false
        end if
        ' mfhd sequence is derived from this immutable fragment index.
        moof = QaFind(result.fragment,0,result.fragment.Count(),"moof")
        mfhd = QaFind(result.fragment,moof.body,moof.finish,"mfhd")
        QaSet32(result.fragment,mfhd.body+4,index+1)
        if index = 0
            m.audioPaths.Push("tmp:/g1-audio-init.mp4")
            if not result.init.WriteFile("tmp:/g1-audio-init.mp4") then return false
        end if
        audioPath = "tmp:/g1-audio-"+suffix+".m4s"
        m.audioPaths.Push(audioPath)
        if not result.fragment.WriteFile(audioPath) then return false
        videoPath = cacheVideoPath(fragment,sourcePath,suffix,config.cacheVideo = true)
        if videoPath = invalid then return false
        if config.cacheVideo = true then m.cacheBytes += fragment.Count()
        print "qa_cache index="; index; " enabled="; config.cacheVideo = true; " bytes="; m.cacheBytes; " live_source_bytes="; fragment.Count(); " live_derived_bytes="; result.fragment.Count()
        m.routes[prefix+"video-"+suffix+".m4s"] = {id:100+index,path:videoPath,mime:"video/mp4"}
        m.routes[prefix+"audio-"+suffix+".m4s"] = {id:200+index,path:audioPath,mime:"audio/mp4"}
        audioDuration = (nextWindow.nextPts-plan.samples[0].pts)/plan.timescale
        videoDuration = config.videoDurations[index]
        if audioDuration > maxDuration then maxDuration = audioDuration
        if videoDuration > maxDuration then maxDuration = videoDuration
        videoLines += "#EXTINF:"+videoDuration.ToStr().Trim()+","+lf+"video-"+suffix+".m4s"+lf
        audioLines += "#EXTINF:"+audioDuration.ToStr().Trim()+","+lf+"audio-"+suffix+".m4s"+lf
        totalSamples += plan.samples.Count()
        print "qa_extract error=0 index="; index; " parse_ms="; parseMs; " elapsed_ms="; stepClock.TotalMilliseconds(); " samples="; plan.samples.Count(); " source_bytes="; fragment.Count(); " audio_bytes="; plan.bytes; " media_bytes="; result.fragment.Count(); " first_pts="; plan.samples[0].pts; " end_pts="; nextWindow.nextPts; " timescale="; plan.timescale
        observeMemory(1)
        window = nextWindow
        fragment = invalid
        result = invalid
        plan = invalid
        observeMemory(2)
    end for
    drainStopEvents()
    if m.stopLocal then return false
    if remote
        if m.clock.TotalMilliseconds()-m.remoteStarted >= 120000 then return false
    end if
    target = Int(maxDuration)
    if target < maxDuration then target += 1
    header = "#EXTM3U"+lf+"#EXT-X-VERSION:7"+lf+"#EXT-X-TARGETDURATION:"+target.ToStr()+lf+"#EXT-X-MEDIA-SEQUENCE:0"+lf+"#EXT-X-PLAYLIST-TYPE:VOD"+lf
    video = header+"#EXT-X-MAP:URI="+Chr(34)+"init.mp4"+Chr(34)+lf+videoLines+"#EXT-X-ENDLIST"+lf
    audio = header+"#EXT-X-MAP:URI="+Chr(34)+"audio-init.mp4"+Chr(34)+lf+audioLines+"#EXT-X-ENDLIST"+lf
    master = "#EXTM3U"+lf+"#EXT-X-VERSION:7"+lf+"#EXT-X-INDEPENDENT-SEGMENTS"+lf+"#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="+Chr(34)+"qa_audio"+Chr(34)+",NAME="+Chr(34)+"qa_audio"+Chr(34)+",DEFAULT=YES,AUTOSELECT=YES,LANGUAGE="+Chr(34)+"en"+Chr(34)+",URI="+Chr(34)+"audio.m3u8"+Chr(34)+lf+"#EXT-X-STREAM-INF:BANDWIDTH=12000000,CODECS="+Chr(34)+"hvc1.2.4.L150.90,"+audioTrack.codec+Chr(34)+",AUDIO="+Chr(34)+"qa_audio"+Chr(34)+",VIDEO-RANGE=PQ"+lf+"video.m3u8"+lf
    m.audioPaths.Push("tmp:/g1-video.m3u8")
    if not WriteAsciiFile("tmp:/g1-video.m3u8",video) then return false
    m.audioPaths.Push("tmp:/g1-audio.m3u8")
    if not WriteAsciiFile("tmp:/g1-audio.m3u8",audio) then return false
    m.audioPaths.Push("tmp:/g1-master.m3u8")
    if not WriteAsciiFile("tmp:/g1-master.m3u8",master) then return false
    print "qa_extract_total count="; window.count; " elapsed_ms="; timer.TotalMilliseconds(); " samples="; totalSamples; " source_bytes="; window.sourceBytes; " derived_bytes="; window.audioBytes; " min_available_kb="; m.minAvailable; " max_usage_pct="; m.maxUsage
    return true
end function

sub acceptStopEvent(event as Dynamic)
    if Type(event) = "roSGNodeEvent"
        if m.rollingTelemetryEnabled=true
            if LCase(event.GetField())="seekrequest"
                canonical=0
                if event.GetField()="seekRequest" then canonical=1
                print "qa_seek_dispatch field=1 canonical="; canonical
            end if
        end if
        QaSeekHandleField(event.GetField(),event.GetData())
        m.stopLocal = QaStopEvent(m.stopLocal,"roSGNodeEvent",event.GetField(),event.GetData())
    end if
end sub
sub drainStopEvents()
    event = m.port.GetMessage()
    while event <> invalid
        acceptStopEvent(event)
        event = m.port.GetMessage()
    end while
end sub
sub cleanupGenerated()
    for each path in m.audioPaths
        m.fs.Delete(path)
    end for
end sub

' This is an IO census, not an inference from the Task state or route count.
function StockEngineFilePresent(path as String) as Boolean
    stat = m.fs.Stat(path)
    return stat <> invalid and stat.DoesExist("size")
end function
function StockEngineDrainComplete() as Boolean
    if m.clients.Count() <> 0 or m.listener <> invalid then return false
    if m.top.stockContext <> invalid then return false
    for each path in m.audioPaths
        if StockEngineFilePresent(path) then return false
    end for
    generations = QaRollingCleanupOwners()
    for each generation in generations
        if generation.transfer <> invalid or generation.cancelledIdentity <> invalid or generation.pendingCleanup = true then return false
        if generation.job <> invalid or generation.hashJob <> invalid then return false
        if generation.stock <> invalid
            if generation.stock.token <> invalid and generation.stock.token <> "" then return false
        end if
        for each path in generation.owned
            if StockEngineFilePresent(path) then return false
        end for
    end for
    return true
end function

sub cleanupServer()
    m.top.ready = false
    clean = true
    try
        QaRemoteCancel()
    catch cancelError
        clean = false
    end try
    for each id in m.clients
        try
            closeClient(m.clients[id])
        catch closeError
            clean = false
        end try
    end for
    m.clients = {}
    if m.listener <> invalid
        try
            m.listener.Close()
            m.listener = invalid
        catch listenerError
            clean = false
        end try
    end if
    if m.rolling = invalid
        try
            cleanupGenerated()
        catch generatedError
            clean = false
        end try
    else
        try
            QaRollingCleanupSession()
        catch rollingError
            clean = false
        end try
        for each generation in QaRollingCleanupOwners()
            try
                QaRollingClearContext(generation)
                if m.top.stockOnly = true then generation.stock = invalid
            catch clearError
                clean = false
            end try
        end for
    end if
    m.top.stockContext=invalid
    drained = false
    if clean and m.top.stockOnly = true
        try
            drained = StockEngineDrainComplete()
        catch censusError
            drained = false
        end try
    end if
    if m.top.stockOnly = true
        if drained
            m.top.drainState = "drained"
        else
            m.top.drainState = "uncertain"
            m.top.failed = true
        end if
    end if
    if drained and m.top.stockOnly = true
        m.rolling = invalid
        m.rollingSession = invalid
        m.preparing = invalid
    end if
    if m.stopObserved then m.top.UnobserveField("stopRequested")
    m.top.ready = false
end sub

' Only the already bounded immutable fragment is written, without a second copy.
' Register before writing so failed/partial writes share normal cleanup.
function cacheVideoPath(fragment as Object, sourcePath as String, suffix as String, enabled as Boolean) as Dynamic
    if m.stopLocal then return invalid
    if Left(sourcePath,15) = "tmp:/g1-source-" then return sourcePath
    if not enabled then return sourcePath
    path = "tmp:/g1-video-"+suffix+".m4s"
    m.audioPaths.Push(path)
    if not fragment.WriteFile(path) then return invalid
    return path
end function

sub closeClient(c as Object)
    c.socket.Close()
    if c.DoesExist("route")
        QaRouteUnpin(c.route)
        c.Delete("route")
    end if
end sub
sub QaRoutePin(route as Object)
    if not route.DoesExist("pins") then route.pins=0
    route.pins+=1
    if route.DoesExist("members")
        for each member in route.members
            member.pins+=1
        end for
    end if
end sub
sub QaRouteUnpin(route as Object)
    route.pins-=1
    if route.DoesExist("members")
        for each member in route.members
            member.pins-=1
        end for
    end if
end sub
