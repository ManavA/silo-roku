' Source timeline preview. Unknown duration disables speculative seeking.
function SiloUITransportSeek(positionMs as Double, durationMs as Double, offsetMs as Double, deltaMs as Double, repeats as Integer) as Double
    if durationMs <= offsetMs or positionMs < 0 or offsetMs < 0 then return positionMs
    multiplier = 1
    if repeats >= 5 then multiplier = 3
    if repeats >= 12 then multiplier = 6
    target = positionMs + deltaMs * multiplier
    last = durationMs - 1000
    if last < offsetMs then last = offsetMs
    if target < offsetMs then target = offsetMs
    if target > last then target = last
    return target
end function

' Chapter data is bounded and ordered. Signed thumbnail URLs are unnecessary
' for a readable list and never enter this transport policy.
function SiloUITransportChapters(raw as Dynamic, durationMs as Double) as Object
    out = []
    if type(raw) <> "roArray" then return out
    last = -1
    examined = 0
    for each chapter in raw
        examined++
        if examined > 128 then exit for
        if type(chapter) = "roAssociativeArray"
            start = chapter.start_seconds
            finish = chapter.end_seconds
            if SiloUITransportNumber(start) and SiloUITransportNumber(finish)
                position = start * 1000#
                if position >= 0 and position > last and finish > start and (durationMs <= 0 or position < durationMs)
                    title = chapter.title
                    if type(title) <> "String" and type(title) <> "roString" then title = ""
                    title = Left(title.Trim(), 80)
                    if title = "" then title = "Chapter " + (out.Count() + 1).ToStr()
                    out.Push({positionMs:position,title:title})
                    last = position
                end if
            end if
        end if
    end for
    return out
end function

function SiloUITransportNumber(value as Dynamic) as Boolean
    kind = type(value)
    if kind <> "Integer" and kind <> "roInt" and kind <> "roInteger" and kind <> "LongInteger" and kind <> "roLongInteger" and kind <> "Float" and kind <> "roFloat" and kind <> "Double" and kind <> "roDouble" then return false
    return value = value and value >= 0 and value <= 604800000
end function

function SiloUITransportTime(positionMs as Double) as String
    total = Int(positionMs / 1000)
    if total < 0 then total = 0
    seconds = (total mod 60).ToStr()
    if Len(seconds) < 2 then seconds = "0" + seconds
    minutes = Int(total / 60)
    return minutes.ToStr() + ":" + seconds
end function

' Manual skip is available independently of automatic skip preferences.
function SiloUITransportSkipCue(markers as Dynamic, positionMs as Double, introMode as String) as Dynamic
    if type(markers) <> "roArray" then return invalid
    count = 0
    for each marker in markers
        count++
        if count > 128 then exit for
        if type(marker) = "roAssociativeArray"
            kind = marker.kind
            allowed = kind = "intro" or kind = "recap" or kind = "credits"
            if kind = "intro" and introMode = "never" then allowed = false
            if allowed and SiloUITransportNumber(marker.startMs) and SiloUITransportNumber(marker.endMs)
                if marker.endMs > marker.startMs and positionMs >= marker.startMs and positionMs < marker.endMs then return {endMs:marker.endMs,label:"skip " + kind}
            end if
        end if
    end for
    return invalid
end function
