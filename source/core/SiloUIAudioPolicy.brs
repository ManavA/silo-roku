' Public timeline policy. Server playback positions are part-local; sync is whole-book.
function SiloUIAudioTarget(queue as Object, globalMs as Dynamic) as Dynamic
    if queue.Count() = 0 then return invalid
    if not SiloUIAudioNumber(globalMs,604800000) then globalMs = 0
    for i = 0 to queue.Count()-1
        part = queue[i]
        if globalMs < part.offsetMs + part.durationMs or i = queue.Count()-1
            localMs = globalMs-part.offsetMs
            if localMs < 0 then localMs = 0
            if localMs >= part.durationMs then localMs = part.durationMs-1000
            if localMs < 0 then localMs = 0
            return {index:i,localMs:localMs,globalMs:part.offsetMs+localMs}
        end if
    end for
    return invalid
end function

function SiloUIAudioGlobal(queue as Object, index as Integer, localMs as Dynamic) as Dynamic
    if index < 0 or index >= queue.Count() then return 0
    if not SiloUIAudioNumber(localMs,604800000) then localMs = 0
    if localMs > queue[index].durationMs then localMs = queue[index].durationMs
    return queue[index].offsetMs + localMs
end function

function SiloUIAudioNumber(value as Dynamic, maximum as Double) as Boolean
    kind = type(value)
    if kind <> "Integer" and kind <> "roInt" and kind <> "roInteger" and kind <> "LongInteger" and kind <> "roLongInteger" and kind <> "Float" and kind <> "roFloat" and kind <> "Double" and kind <> "roDouble" then return false
    return value = value and value >= 0 and value <= maximum
end function

function SiloUIAudioTime(ms as Dynamic) as String
    if not SiloUIAudioNumber(ms,604800000) then ms = 0
    seconds = Int(ms/1000)
    minutes = Int(seconds/60)
    tail = Right("0"+(seconds mod 60).ToStr(),2)
    if minutes < 60 then return minutes.ToStr()+":"+tail
    return Int(minutes/60).ToStr()+":"+Right("0"+(minutes mod 60).ToStr(),2)+":"+tail
end function

' Parts without chapter metadata still expose their start as a boundary.
function SiloUIAudioChapterTarget(queue as Object, index as Integer, localMs as Dynamic, direction as Integer) as Dynamic
    if index < 0 or index >= queue.Count() then return invalid
    if not SiloUIAudioNumber(localMs,queue[index].durationMs) then return invalid
    positionMs = queue[index].offsetMs+localMs
    latestMs = -1#
    previousMs = -1#
    followingMs = 604800001#
    previous = invalid
    latest = invalid
    following = invalid
    for i = 0 to queue.Count()-1
        starts = [0#]
        if queue[i].chapters <> invalid
            for each chapter in queue[i].chapters
                startMs = chapter.start_seconds*1000#
                if startMs > 0 and startMs < queue[i].durationMs then starts.Push(startMs)
            end for
        end if
        for each startMs in starts
            target = {index:i,localMs:startMs}
            boundaryMs = queue[i].offsetMs+startMs
            if i < index or (i = index and startMs <= localMs)
                if boundaryMs > latestMs
                    previous = latest : previousMs = latestMs
                    latest = target : latestMs = boundaryMs
                else if boundaryMs < latestMs and boundaryMs > previousMs
                    previous = target : previousMs = boundaryMs
                end if
            else if boundaryMs < followingMs
                following = target : followingMs = boundaryMs
            end if
        end for
    end for
    if direction > 0 then return following
    if positionMs-latestMs > 3000 then return latest
    return previous
end function
