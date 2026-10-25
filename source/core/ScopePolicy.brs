' Only results from the current source, profile, and request generation may paint.
function ScopeMatches(active as Object, incoming as Object) as Boolean
    if active = invalid or incoming = invalid then return false

    for each key in ["sourceId", "profileId", "generation"]
        if not active.DoesExist(key) or not incoming.DoesExist(key) then return false
        if active[key] = invalid or incoming[key] = invalid then return false
        if active[key] <> incoming[key] then return false
    end for
    return true
end function
