' Evidence covers native string/file transfers on this exact SDK identity only.
' The trusted initial server may delegate responses, including HTTP downgrades.
' This policy scopes Authorization to the initial origin; it does not prove the
' final response origin or encrypted media at every hop.
function SiloNativeBearerTransportQualified(origin as Dynamic, device as Dynamic) as Boolean
    if type(origin) <> "String" and type(origin) <> "roString" then return false
    if not CreateObject("roRegex","^https://[A-Za-z0-9.-]+(:[0-9]{1,5})?$","").IsMatch(origin) then return false
    colon = Instr(9,origin,":")
    if colon > 0
        port = Mid(origin,colon+1)
        if port.ToInt() < 1 or port.ToInt() > 65535 then return false
    end if
    try
        details = device.GetModelDetails():os = device.GetOSVersion()
        if type(details) <> "roAssociativeArray" or type(os) <> "roAssociativeArray" then return false
        if details.ModelNumber <> "C208X" then return false
        for each name in ["major","minor","revision","build"]
            kind = type(os[name])
            if kind <> "String" and kind <> "roString" and kind <> "Integer" and kind <> "roInt" and kind <> "roInteger" and kind <> "LongInteger" and kind <> "roLongInteger" then return false
            os[name] = os[name].ToStr()
        end for
        return os.major = "16" and os.minor = "0" and os.revision = "4" and os.build = "842"
    catch exception
        return false
    end try
end function

function SiloStockTransportPolicyValid(policy as Dynamic, evidence as Dynamic, origin as Dynamic) as Boolean
    if type(policy) <> "String" and type(policy) <> "roString" then return false
    if type(evidence) <> "String" and type(evidence) <> "roString" then return false
    if type(origin) <> "String" and type(origin) <> "roString" then return false
    if policy = "native-bearer-origin-scope-v1"
        return evidence = "c208x-16.0.4-842-redirect-chains-v1" and Left(origin,8) = "https://"
    end if
    ' Only private QA builders issue this distinct fixture assertion.
    return policy = "controlled-fixture-v1" and evidence = "private-controlled-fixture"
end function
