function QaStopEvent(previous as Boolean, eventType as String, fieldName as String, value as Dynamic) as Boolean
    if previous then return true
    if eventType <> "roSGNodeEvent" or LCase(fieldName) <> "stoprequested" then return false
    kind = Type(value)
    if kind <> "Boolean" and kind <> "roBoolean" then return false
    return value
end function
