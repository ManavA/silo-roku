function QaAdmitSocket(active as Integer, cap as Integer) as Boolean
    if active < 0 or cap < 1 or cap > 8 then return false
    return active < cap
end function
function QaAcceptReady(active as Integer, cap as Integer, readable as Boolean, cancelled as Boolean) as Boolean
    if cancelled or not readable then return false
    return QaAdmitSocket(active,cap)
end function
