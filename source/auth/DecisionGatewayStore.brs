' A separate compact key prevents optional inference from overwriting provider
' refresh/session JSON. ClearSession purges this key along with the session.
function DecisionGatewayTokenRead(provider as String, origin as String, revision as Integer) as Dynamic
    if SessionRevision(provider) <> revision then return invalid
    section = SessionSection(provider)
    if section = invalid then return invalid
    if not section.Exists("decisionGatewayToken") then return invalid
    raw = section.Read("decisionGatewayToken")
    if SessionRevision(provider) <> revision then return invalid
    if not DgBytesWithin(raw,1024) then return invalid
    value = ParseJson(raw,"i")
    if not DpKeys(value,["origin","token","exp","sessionRevision"]) then return invalid
    if DpField(value,"origin") <> origin or DecisionGatewayOrigin(origin) <> origin then return invalid
    if not DgToken(DpField(value,"token")) then return invalid
    if not DpNumber(DpField(value,"exp"),9000000000#,true) then return invalid
    if not DpNumber(DpField(value,"sessionRevision"),2147483647,true) then return invalid
    if DpField(value,"sessionRevision") <> revision then return invalid
    return {"origin":origin,"token":DpField(value,"token"),"exp":DpField(value,"exp"),"sessionRevision":revision}
end function

function DecisionGatewayTokenWrite(provider as String, token as Object, revision as Integer) as Boolean
    if SessionRevision(provider) <> revision then return false
    if not DpKeys(token,["origin","token","exp","sessionRevision"]) then return false
    origin = DpField(token,"origin")
    canonical = DecisionGatewayOrigin(origin)
    if canonical = invalid then return false
    if canonical = "" or canonical <> origin then return false
    if not DgToken(DpField(token,"token")) or not DpNumber(DpField(token,"exp"),9000000000#,true) then return false
    if DpField(token,"sessionRevision") <> revision then return false
    raw = FormatJson(token)
    if not DgBytesWithin(raw,1024) then return false
    section = SessionSection(provider)
    if section = invalid then return false
    if SessionRevision(provider) <> revision then return false
    if not section.Write("decisionGatewayToken",raw) then return false
    saved = section.Flush()
    if SessionRevision(provider) <> revision
        ' A stale write is never reusable after sign-out/profile replacement.
        if section.Read("decisionGatewayToken") = raw
            section.Delete("decisionGatewayToken")
            section.Flush()
        end if
        return false
    end if
    return saved
end function

function DecisionGatewayTokenForget(provider as String, token as Object, revision as Integer) as Boolean
    if SessionRevision(provider) <> revision then return false
    section = SessionSection(provider)
    if section = invalid then return false
    current = DecisionGatewayTokenRead(provider,token.origin,revision)
    if current = invalid then return true
    if current.token <> token.token then return true
    if SessionRevision(provider) <> revision then return false
    section.Delete("decisionGatewayToken")
    saved = section.Flush()
    return saved and SessionRevision(provider) = revision
end function
