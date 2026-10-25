' Public decision settings only. Install credentials never belong to this DTO.
function DpField(raw as Dynamic, key as String, fallback = invalid as Dynamic) as Dynamic
    if type(raw) <> "roAssociativeArray" then return fallback
    if raw.DoesExist(key) then return raw[key]
    folded = LCase(key)
    for each name in raw.Keys()
        if LCase(name) = folded then return raw[name]
    end for
    return fallback
end function

' Single aliases survive our own case-insensitive registry JSON round trip;
' ambiguous aliases and unknown fields never become an accepted record.
function DpKeys(raw as Dynamic, fields as Object) as Boolean
    if type(raw) <> "roAssociativeArray" then return false
    if raw.Count() <> fields.Count() then return false
    allowed = {}
    for each field in fields
        allowed[LCase(field)] = true
    end for
    seen = {}
    for each name in raw.Keys()
        folded = LCase(name)
        if not allowed.DoesExist(folded) or seen.DoesExist(folded) then return false
        seen[folded] = true
    end for
    return true
end function

function DpText(raw as Dynamic, maximum as Integer, empty = false as Boolean) as Boolean
    if type(raw) <> "String" and type(raw) <> "roString" then return false
    if Len(raw) > maximum or (not empty and raw = "") then return false
    return not CreateObject("roRegex","[\x00-\x1f\x7f]","").IsMatch(raw)
end function

function DpBool(raw as Dynamic) as Boolean
    return type(raw) = "Boolean" or type(raw) = "roBoolean"
end function

function DpNumber(raw as Dynamic, maximum as Double, whole = false as Boolean) as Boolean
    kind = type(raw)
    if kind <> "Integer" and kind <> "roInt" and kind <> "roInteger" and kind <> "LongInteger" and kind <> "roLongInteger" and kind <> "Float" and kind <> "roFloat" and kind <> "Double" and kind <> "roDouble" then return false
    if raw <> raw or raw < 0 or raw > maximum then return false
    if whole
        ' Int/Fix are 32-bit on Roku. Both intermediates remain small here.
        remainder = raw - Int(raw / 1000000#) * 1000000#
        if remainder <> Int(remainder) then return false
    end if
    return true
end function

function DecisionEpochMs(raw as Dynamic) as Boolean
    return DpNumber(raw,9000000000000#,true)
end function

function DpScope(raw as Dynamic) as Dynamic
    source = DpField(raw,"sourceId")
    profile = DpField(raw,"profileId")
    if not DpText(source,512) or not DpText(profile,128,true) then return invalid
    prefix = Left(source,5)
    if (prefix <> "plex:" and prefix <> "silo:") or Len(source) <= 5 then return invalid
    provider = DpField(raw,"provider")
    if provider <> invalid
        if not DpText(provider,4) or provider + ":" <> prefix then return invalid
    end if
    return {sourceId:source,profileId:profile}
end function

' Explicit empty disables the gateway; malformed is invalid, never a default.
function DecisionGatewayOrigin(raw as Dynamic) as Dynamic
    if not DpText(raw,256,true) then return invalid
    if raw = "" then return ""
    if raw <> raw.Trim() or LCase(Left(raw,8)) <> "https://" then return invalid
    if not CreateObject("roRegex","^https://[^/?#@]+/?$","i").IsMatch(raw) then return invalid
    normalized = NormalizeServerUrl(raw)
    if normalized.ok <> true then return invalid
    authority = Mid(normalized.url,9)
    portAt = Instr(1,authority,":")
    if Left(authority,1) = "["
        closing = Instr(1,authority,"]")
        portAt = 0
        if Len(authority) > closing then portAt = closing + 1
    end if
    if portAt > 0
        port = Int(Val(Mid(authority,portAt+1)))
        authority = Left(authority,portAt-1)
        if port <> 443 then authority += ":" + port.ToStr()
    end if
    return "https://" + authority
end function

function DecisionPreferenceDefaults(scope as Dynamic) as Dynamic
    active = DpScope(scope)
    if active = invalid then return invalid
    return {"schemaVersion":1,"sourceId":active.sourceId,"profileId":active.profileId,
        "personalized":false,"cloudDecisions":false,"stillWatchingCheck":false,"gatewayOrigin":""}
end function

function DecisionPreferenceNormalize(raw as Dynamic, scope as Dynamic) as Dynamic
    active = DpScope(scope)
    if active = invalid then return invalid
    if not DpKeys(raw,["schemaVersion","sourceId","profileId","personalized","cloudDecisions","stillWatchingCheck","gatewayOrigin"]) then return invalid
    if not DpNumber(DpField(raw,"schemaVersion"),1,true) or DpField(raw,"schemaVersion") <> 1 then return invalid
    if DpField(raw,"sourceId") <> active.sourceId or DpField(raw,"profileId") <> active.profileId then return invalid
    for each flag in ["personalized","cloudDecisions","stillWatchingCheck"]
        if not DpBool(DpField(raw,flag)) then return invalid
    end for
    origin = DecisionGatewayOrigin(DpField(raw,"gatewayOrigin"))
    if origin = invalid then return invalid
    return {"schemaVersion":1,"sourceId":active.sourceId,"profileId":active.profileId,
        "personalized":DpField(raw,"personalized"),"cloudDecisions":DpField(raw,"cloudDecisions"),
        "stillWatchingCheck":DpField(raw,"stillWatchingCheck"),"gatewayOrigin":origin}
end function
