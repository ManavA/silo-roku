' Value access used by retained, non-shipping pure policy tests.
' This fixture supplies no scene, navigation, rendering, or worker behavior.
function UiField(value as Dynamic, field as String, fallback as Dynamic) as Dynamic
    if type(value) <> "roAssociativeArray" then return fallback
    if not value.DoesExist(field) then return fallback
    if value[field] = invalid then return fallback
    return value[field]
end function

function UiNumber(value as Dynamic, fallback as Double) as Double
    kind = type(value)
    if kind = "Integer" or kind = "roInt" or kind = "roInteger" or kind = "LongInteger" or kind = "roLongInteger" or kind = "Float" or kind = "roFloat" or kind = "Double" or kind = "roDouble" then return value
    return fallback
end function

function UiResultMatches(active as Dynamic, incoming as Dynamic) as Boolean
    if type(active) <> "roAssociativeArray" or type(incoming) <> "roAssociativeArray" then return false
    for each field in ["provider", "sourceId", "profileId", "generation"]
        if not active.DoesExist(field) or not incoming.DoesExist(field) then return false
        if active[field] <> incoming[field] then return false
    end for
    return true
end function

' Numeric timeline boundary for retained ProviderAudio/SiloChange policy tests.
function UiPositionMs(positionSeconds as Double, offsetMs as Double, relative as Boolean) as Double
    position = positionSeconds * 1000
    if relative then position = position + offsetMs
    if position < 0 then return 0
    return position
end function


function UiPlanPositionMs(positionSeconds as Dynamic, plan as Object, started = true as Dynamic) as Double
    offsetMs = UiNumber(UiField(plan,"timelineOffsetMs",0),0)
    relative = UiField(plan,"relativeTimeline",false)
    seconds = UiNumber(positionSeconds,-1)
    if started = invalid then started = true
    if started and seconds >= 0 then return UiPositionMs(seconds,offsetMs,relative)
    startMs = UiNumber(UiField(plan,"startPositionMs",0),0)
    if relative then startMs = startMs + offsetMs
    if startMs < 0 then return 0
    return startMs
end function
