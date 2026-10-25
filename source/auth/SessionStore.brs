' Registry identity is independent of UI names and signing identity.
function AppRegistrySection(suffix as String) as Object
    if suffix = "metadata" then return CreateObject("roRegistrySection", "silo.metadata")
    control = CreateObject("roRegistrySection", "silo.registry")
    prefix = control.Read("namespace")
    if not RegistryNamespaceValid(prefix)
        prefix = RegistryExistingNamespace()
        if prefix = "" then prefix = "silo"
        ' A full registry must not make existing login/settings unreadable.
        if control.Write("namespace",prefix) then control.Flush()
    end if
    return CreateObject("roRegistrySection", prefix + "." + suffix)
end function

function RegistryNamespaceValid(value as Dynamic) as Boolean
    if type(value) <> "String" and type(value) <> "roString" then return false
    return CreateObject("roRegex","^[A-Za-z0-9_-]{1,64}$","").IsMatch(value)
end function

function RegistryExistingNamespace() as String
    registry = CreateObject("roRegistry")
    candidates = {}
    for each name in registry.GetSectionList()
        dot = Instr(1,name,".")
        if dot > 1
            prefix = Left(name,dot-1)
            suffix = Mid(name,dot+1)
            if RegistryNamespaceValid(prefix) and (suffix = "silo" or suffix = "plex")
                section = CreateObject("roRegistrySection",name)
                if section.Exists("session")
                    raw = section.Read("session")
                    if Len(raw) <= 14000
                        session = DecodeStoredSession(raw)
                        if RegistrySessionValid(suffix,session) then candidates[prefix] = true
                    end if
                else
                    preferences = CreateObject("roRegistrySection",prefix + ".preferences")
                    if RegistryPreferencesValid(preferences)
                        candidates[prefix] = true
                    else
                        servers = CreateObject("roRegistrySection",prefix + ".servers")
                        if RegistrySavedServersValid(servers.Read("silo")) then candidates[prefix] = true
                    end if
                end if
            end if
        end if
    end for
    if candidates.Count() <> 1 then return ""
    return candidates.Keys()[0]
end function

function RegistryPreferencesValid(section as Object) as Boolean
    appearance = section.Read("appearance")
    navigation = section.Read("navigation")
    if appearance = "oled" or appearance = "glass" or appearance = "silo_blue" or appearance = "light_blue" then return true
    if navigation = "top" or navigation = "left" then return true
    raw = section.Read("playbackScopes")
    if Len(raw) > 14000 then return false
    rows = ParseJson(raw,"i")
    if type(rows) <> "roArray" then return false
    if rows.Count() < 1 or rows.Count() > 4 then return false
    for each row in rows
        if type(row) <> "roAssociativeArray" then return false
        if type(row.sourceId) <> "String" and type(row.sourceId) <> "roString" then return false
        if Left(row.sourceId,5) <> "silo:" and Left(row.sourceId,5) <> "plex:" then return false
        if type(row.profileId) <> "String" and type(row.profileId) <> "roString" then return false
    end for
    return true
end function

function RegistrySavedServersValid(raw as String) as Boolean
    if Len(raw) > 8192 then return false
    addresses = ParseJson(raw)
    if type(addresses) <> "roArray" then return false
    if addresses.Count() < 1 or addresses.Count() > 8 then return false
    for each address in addresses
        if type(address) <> "String" and type(address) <> "roString" then return false
        if Len(address) > 1024 then return false
        if not CreateObject("roRegex","^https?://[A-Za-z0-9][A-Za-z0-9.:-]*(/[A-Za-z0-9_/-]*)?$","").IsMatch(address) then return false
    end for
    return true
end function

function RegistrySessionValid(provider as String, session as Object) as Boolean
    source = session.sourceId
    if type(source) <> "String" and type(source) <> "roString" then return false
    if source <> ""
        if Left(source,Len(provider)+1) <> provider + ":" or Len(source) <= Len(provider)+1 then return false
    else if provider <> "plex"
        return false
    end if
    if provider = "silo"
        token = session.accessToken
        base = session.baseUrl
        if type(base) <> "String" and type(base) <> "roString" then return false
        if Left(base,8) <> "https://" and Left(base,7) <> "http://" then return false
    else
        token = session.accountToken
    end if
    if type(token) <> "String" and type(token) <> "roString" then return false
    return token <> "" and Len(token) <= 12000
end function

' Registry contains only compact credentials and choices. Never print these values.
function SessionSection(provider as String) as Object
    if provider <> "plex" and provider <> "silo" then return invalid
    return AppRegistrySection(provider)
end function

function LoadSession(provider as String) as Object
    section = SessionSection(provider)
    if section = invalid then return {}
    if not section.Exists("session") then return {}
    raw = section.Read("session")
    if raw = invalid or raw = "" then return {}
    return DecodeStoredSession(raw)
end function

function DecodeStoredSession(raw as String) as Object
    ' BrightScript lowercases bare AA literal keys when writing JSON. Parse
    ' our own registry record case-insensitively so a new Task can recover
    ' accountToken/sourceId after each request. Provider JSON stays strict.
    value = ParseJson(raw, "i")
    if type(value) <> "roAssociativeArray" then return {}
    return value
end function

function SessionRevision(provider as String) as Integer
    section = SessionSection(provider)
    if section = invalid then return -1
    if not section.Exists("revision") then return 0
    return Val(section.Read("revision"))
end function

function SaveSession(provider as String, session as Object, expectedRevision as Integer) as Boolean
    section = SessionSection(provider)
    if section = invalid or session = invalid then return false
    if SessionRevision(provider) <> expectedRevision then return false
    raw = FormatJson(session)
    if Len(raw) > 14000 then return false
    if not section.Write("session", raw) then return false
    return section.Flush()
end function

' Server/profile replacement creates a new scope for in-flight worker jobs.
function ReplaceSession(provider as String, session as Object, expectedRevision as Integer) as Boolean
    section = SessionSection(provider)
    if section = invalid or session = invalid then return false
    if SessionRevision(provider) <> expectedRevision then return false
    raw = FormatJson(session)
    if Len(raw) > 14000 then return false
    if not section.Write("session", raw) then return false
    if not section.Write("revision", (expectedRevision + 1).ToStr()) then return false
    return section.Flush()
end function

function ClearSession(provider as String) as Boolean
    section = SessionSection(provider)
    if section = invalid then return false
    revision = SessionRevision(provider) + 1
    section.Delete("session")
    section.Delete("decisionGatewayToken")
    section.Delete("recentSearches")
    section.Write("revision", revision.ToStr())
    return section.Flush()
end function
