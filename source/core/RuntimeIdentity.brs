' Installed package identity, independent of saved account/profile state.
' ifAppInfo.GetVersion returns manifest major.minor.build:
' https://developer.roku.com/dev/docs/ifappinfo#getversion-as-string
function RuntimeAppVersion() as String
    try
        app = CreateObject("roAppInfo")
        if app = invalid then return "unknown"
        version = app.GetVersion()
        if type(version) <> "String" and type(version) <> "roString" then return "unknown"
        if Len(version) > 40 then return "unknown"
        if CreateObject("roRegex", "^[0-9]+[.][0-9]+[.][0-9]+$", "").IsMatch(version) then return version
    catch exception
        ' An unavailable native identity must never become a stale release claim.
    end try
    return "unknown"
end function
