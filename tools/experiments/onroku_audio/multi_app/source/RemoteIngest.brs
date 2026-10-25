' Deliberately narrow owned-server contract: no credentials, queries or redirects.
function QaRemoteReference(base as String, reference as String) as Dynamic
    pattern = CreateObject("roRegex","^(https?://[A-Za-z0-9.-]+(:[0-9]{1,5})?)(/[A-Za-z0-9_./-]+)$","")
    parts = pattern.Match(base)
    if parts.Count() = 0 then return invalid
    for each segment in parts[3].Split("/")
        if segment = "." or segment = ".." then return invalid
    end for
    if Instr(1,parts[3],"//") > 0 then return invalid
    origin = parts[1]
    if Left(reference,Len(origin)+1) = origin+"/" then reference = Mid(reference,Len(origin)+1)
    if not CreateObject("roRegex","^/?[A-Za-z0-9_./-]+$","").IsMatch(reference) then return invalid
    if Instr(1,reference,"//") > 0 then return invalid
    for each segment in reference.Split("/")
        if segment = ".." or segment = "." then return invalid
    end for
    if Left(reference,1) = "/" then return origin+reference
    path = parts[3]
    slash = 0
    for i = 1 to Len(path)
        if Mid(path,i,1) = "/" then slash = i
    end for
    return origin+Left(path,slash)+reference
end function

function QaRemotePlaylist(text as String, base as String, rolling = false as Boolean) as Dynamic
    if QaRemoteReference(base,base) <> base then return invalid
    textCap=32768:entryCap=16
    if rolling then textCap=1048576:entryCap=8192
    if Len(text) < 1 or Len(text) > textCap then return invalid
    lines = text.Replace(Chr(13),"").Split(Chr(10))
    if lines[0] <> "#EXTM3U" then return invalid
    init = invalid
    durations = []
    durationMicros = []
    sequence = 0
    targetDuration = 0
    inferredTarget = 0
    fragments = []
    duration = invalid
    ended = false
    seen = {}
    for index = 1 to lines.Count()-1
        line = lines[index]
        if line <> ""
            if ended then return invalid
            if Left(line,11) = "#EXT-X-MAP:"
                if init <> invalid or fragments.Count() > 0 or duration <> invalid then return invalid
                match = CreateObject("roRegex","^#EXT-X-MAP:URI="+Chr(34)+"([^"+Chr(34)+"]+)"+Chr(34)+"$","").Match(line)
                if match.Count() = 0 then return invalid
                init = QaRemoteReference(base,match[1])
                if init = invalid then return invalid
            else if Left(line,8) = "#EXTINF:"
                if init = invalid or duration <> invalid then return invalid
                match = CreateObject("roRegex","^#EXTINF:([0-9]{1,2}([.][0-9]{1,6})?),$","").Match(line)
                if match.Count() = 0 then return invalid
                duration = Val(match[1])
                ' Parse decimal digits directly: Float seconds lose microseconds.
                decimal = match[1].Split(".")
                micros = Int(Val(decimal[0]))*1000000
                if decimal.Count() = 2 then micros += Int(Val(Left(decimal[1]+"000000",6)))
                if micros <= 0 or micros > 60000000 then return invalid
                ceiling = Int(micros/1000000)
                if micros > ceiling*1000000 then ceiling += 1
                if ceiling > inferredTarget then inferredTarget = ceiling
            else if line = "#EXT-X-ENDLIST"
                if duration <> invalid then return invalid
                ended = true
            else if Left(line,1) = "#"
                ' No unrecognized metadata: byte ranges, encryption, masters,
                ' discontinuities and alternate renditions all fail closed.
                match = CreateObject("roRegex","^#EXT-X-(VERSION:[1-7]|TARGETDURATION:([1-9]|[1-5][0-9]|60)|MEDIA-SEQUENCE:[0-9]{1,9}|PLAYLIST-TYPE:VOD|INDEPENDENT-SEGMENTS)$","").Match(line)
                if match.Count() = 0 then return invalid
                name = line.Split(":")[0]
                if seen.DoesExist(name) then return invalid
                seen[name] = true
                if name = "#EXT-X-TARGETDURATION" then targetDuration = Val(line.Split(":")[1])
                ' Accumulate integer digits; Val rounds nine-digit sequences.
                if name = "#EXT-X-MEDIA-SEQUENCE"
                    for each digit in line.Split(":")[1].Split("")
                        sequence = sequence*10+Asc(digit)-48
                    end for
                end if
            else
                if duration = invalid or fragments.Count() >= entryCap then return invalid
                url = QaRemoteReference(base,line)
                if url = invalid then return invalid
                fragments.Push(url)
                durations.Push(duration)
                durationMicros.Push(micros)
                duration = invalid
            end if
        end if
    end for
    if not ended or init = invalid or fragments.Count() < 3 then return invalid
    ' Older owned fixtures omit optional metadata; preserve that admission.
    if targetDuration = 0 then targetDuration = inferredTarget
    return {init:init,fragments:fragments,durations:durations,durationMicros:durationMicros,binding:base,sequence:sequence,targetDuration:targetDuration,ended:ended}
end function

function QaRemoteTransfer() as Dynamic
    return CreateObject("roUrlTransfer")
end function
function QaRemotePort() as Dynamic
    return CreateObject("roMessagePort")
end function
function QaRemoteWait(port as Object) as Dynamic
    return Wait(50,port)
end function
function QaRemoteEventType(event as Dynamic) as String
    return Type(event)
end function
function QaRemoteTimer() as Object
    return CreateObject("roTimespan")
end function
function QaRemoteSize(path as String) as Integer
    stat = m.fs.Stat(path)
    if stat = invalid then return 0
    if not stat.DoesExist("size") then return 0
    return stat.size
end function
function QaRemoteWithin(path as String, cap as Integer) as Boolean
    return QaRemoteSize(path)+QaRemoteSize(path+".tmp") <= cap
end function
sub QaRemoteCancel()
    if m.remoteActive <> invalid
        try
            m.remoteActive.AsyncCancel()
        catch cancelError
        end try
        m.remoteActive = invalid
    end if
end sub
function QaRemoteFetch(url as String, path as String, cap as Integer) as Boolean
    ' Both paths are owned before any asynchronous write can begin.
    m.audioPaths.Push(path)
    m.audioPaths.Push(path+".tmp")
    success = false
    try
        drainStopEvents()
        if not m.stopLocal and cap > 0 and m.clock.TotalMilliseconds()-m.remoteStarted < 120000
            transfer = QaRemoteTransfer()
            port = QaRemotePort()
            m.remoteActive = transfer
            transfer.SetMessagePort(port)
            transfer.SetUrl(url)
            transfer.RetainBodyOnError(false)
            tls = true
            if Left(url,8) = "https://"
                tls = transfer.SetCertificatesFile("common:/certs/ca-bundle.crt")
                tls = transfer.EnablePeerVerification(true) and tls
                tls = transfer.EnableHostVerification(true) and tls
            end if
            timer = QaRemoteTimer()
            if tls and transfer.AsyncGetToFile(path)
                while timer.TotalMilliseconds() < 10000 and m.clock.TotalMilliseconds()-m.remoteStarted < 120000
                    drainStopEvents()
                    if m.stopLocal or not QaRemoteWithin(path,cap) then exit while
                    event = QaRemoteWait(port)
                    if QaRemoteEventType(event) = "roUrlEvent"
                        if event.GetSourceIdentity() = transfer.GetIdentity()
                            drainStopEvents()
                            success = event.GetResponseCode() = 200 and not m.stopLocal
                            success = success and QaRemoteWithin(path,cap) and QaRemoteSize(path) > 0 and QaRemoteSize(path+".tmp") = 0
                            success = success and timer.TotalMilliseconds() < 10000 and m.clock.TotalMilliseconds()-m.remoteStarted < 120000
                            exit while
                        end if
                    end if
                end while
            end if
        end if
    catch fetchError
        success = false
    end try
    if not success then QaRemoteCancel()
    m.remoteActive = invalid
    return success
end function

function QaRemoteIngest(url as String) as Dynamic
    ' Only explicit no-auth controlled origin configurations reach this seam.
    if QaRemoteReference(url,"probe") = invalid then return invalid
    m.remoteStarted = m.clock.TotalMilliseconds()
    playlistPath = "tmp:/g1-upstream.m3u8"
    if not QaRemoteFetch(url,playlistPath,32768) then return invalid
    if not QaRemoteWithin(playlistPath,32768) then return invalid
    plan = QaRemotePlaylist(ReadAsciiFile(playlistPath),url)
    if plan = invalid then return invalid
    initPath = "tmp:/g1-source-init.mp4"
    if not QaRemoteFetch(plan.init,initPath,1048576) then return invalid
    bytes = QaRemoteSize(initPath)
    paths = []
    for index = 0 to plan.fragments.Count()-1
        path = "tmp:/g1-source-"+Right("0000"+index.ToStr(),4)+".m4s"
        if not QaRemoteFetch(plan.fragments[index],path,25165824-bytes) then return invalid
        bytes += QaRemoteSize(path)
        paths.Push(path)
    end for
    return {init:initPath,fragments:paths,durations:plan.durations,sourceBytes:bytes}
end function
