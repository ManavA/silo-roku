' Purge jobs carry only a scene generation counter. Filenames, credentials and
' account/session identity never enter the SceneGraph job or result.
function OwnedIndexPurgeValidJob(job as Dynamic) as Boolean
    if type(job) <> "roAssociativeArray" then return false
    if job.Keys().Count() <> 1 or not job.DoesExist("requestId") then return false
    value = job.requestId
    kind = type(value)
    numeric = kind = "Integer" or kind = "LongInteger" or kind = "Float" or kind = "Double"
    numeric = numeric or kind = "roInt" or kind = "roInteger" or kind = "roLongInteger" or kind = "roFloat" or kind = "roDouble"
    if not numeric then return false
    if value < 0 or value > 2147483647 then return false
    return Int(value) = value
end function

function OwnedIndexPurgeNamePattern() as String
    return "^(owned-[A-Za-z0-9_-]{1,64}-[A-Za-z0-9_-]{1,64}-[0-9]{1,10}|owned-manifest-[A-Za-z0-9_-]{1,64}|silo-owned-pointer-v1)[.]json([.]part)?$"
end function

' Native Find returns relative names. Never accept an absolute path from that
' list, a subdirectory, a wildcard, a control character or an unrelated prefix.
function OwnedIndexPurgePath(name as Dynamic) as String
    if type(name) <> "String" and type(name) <> "roString" then return ""
    if Len(name) = 0 or Len(name) > 156 then return ""
    if CreateObject("roRegex", "[^A-Za-z0-9_.-]", "").IsMatch(name) then return ""
    if not CreateObject("roRegex", OwnedIndexPurgeNamePattern(), "").IsMatch(name) then return ""
    return "cachefs:/" + name
end function

function OwnedIndexPurgePathAllowed(path as String) as Boolean
    if Left(path, 9) <> "cachefs:/" then return false
    return OwnedIndexPurgePath(Mid(path, 10)) = path
end function

function OwnedIndexPurgeIsFile(stat as Dynamic) as Boolean
    if type(stat) <> "roAssociativeArray" then return false
    if not stat.DoesExist("type") then return false
    kind = stat.type
    if type(kind) <> "String" and type(kind) <> "roString" then return false
    return kind = "file"
end function
