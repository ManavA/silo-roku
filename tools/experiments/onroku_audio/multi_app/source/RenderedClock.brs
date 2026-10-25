' Private diagnostic. Last-rendered sample timestamps do not measure speakers/panel.
function QaClockNumber(value as Dynamic) as Boolean
    kind = Type(value)
    return kind = "Integer" or kind = "roInt" or kind = "roInteger" or kind = "LongInteger" or kind = "roLongInteger" or kind = "Float" or kind = "roFloat" or kind = "Double" or kind = "roDouble"
end function
function QaRenderedClock(info as Dynamic, previous as Dynamic, state as String) as Object
    result = {ok:false, eligible:false, stale:false, epoch:-1, clipId:-1, audioSeconds:0#, videoSeconds:0#, deltaMs:0#}
    if Type(info) <> "roAssociativeArray" then return result
    if not QaClockNumber(info.audio) then return result
    if not QaClockNumber(info.video) then return result
    if not QaClockNumber(info.epoch) then return result
    if info.epoch <> 0 and info.epoch <> 1 then return result
    result.ok = true
    result.epoch = info.epoch
    if QaClockNumber(info.clip_id) then result.clipId = info.clip_id
    result.audioSeconds = info.audio
    result.videoSeconds = info.video
    result.deltaMs = (info.audio-info.video)*1000#
    if Type(previous) = "roAssociativeArray"
        if previous.ok = true
            result.stale = previous.epoch = result.epoch and previous.clipId = result.clipId and previous.audioSeconds = result.audioSeconds and previous.videoSeconds = result.videoSeconds
        end if
    end if
    result.eligible = state = "playing" and not result.stale
    return result
end function
