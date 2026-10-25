' Settings requests inherit Api's source/profile/generation fence. An additional
' epoch rejects reads superseded by a local edit, without delaying home/playback.
sub SiloUISettingsLoad()
    m.settingsEpoch = 0
    m.settingsRevision = 0
    m.settingsKeys = []
    m.settingsManifest = {}
    m.settingsScopes = []
    m.settingsReady = false
    m.settingsWriteBusy = false
    m.settingsScope = "profile"
    section = AppRegistrySection("preferences")
    ' Scope cache by source and profile; never reuse another profile's settings.
    m.preferences = SiloUISettingsPreferences(invalid)
    m.qualityExplicit = false
    cached = SiloUISettingsCacheGet(ParseJson(section.Read("playbackScopes"), "i"), m.sourceId, m.profileId)
    if type(cached) = "roAssociativeArray"
        m.preferences = SiloUISettingsPreferences(cached)
        m.qualityExplicit = cached.qualityExplicit = true
    end if
    m.localPreferences = SiloUISettingsPreferences(m.preferences)
    ' Restore cache before Home. EnterSource starts discovery immediately after
    ' dispatching Home, without waiting for its response or changing Play timing.
    m.settingsPending = true
end sub

sub SiloUISettingsStart()
    if m.settingsPending <> true then return
    m.settingsPending = false
    Api("settings_capabilities", {}, "settings_caps", m.settingsEpoch)
end sub

sub SiloUISettingsResult(purpose as String, result as Object, data as Object, epoch as Dynamic)
    if purpose = "settings_reset" then SiloUISettingsResetResult(result,data,epoch) : return
    if epoch <> m.settingsEpoch and purpose <> "settings_caps" and purpose <> "settings_manifest" then return
    if result.ok <> true
        if purpose = "settings_write"
            m.settingsWriteBusy = false
            Toast("Saved on this Roku. Server sync unavailable.")
        end if
        return
    end if
    if purpose = "settings_caps"
        if data.api_version <> 1 or data.allowed <> true or data.state <> "available" then return
        if type(data.manifest_revision) <> "Integer" and type(data.manifest_revision) <> "roInt" and type(data.manifest_revision) <> "roInteger" and type(data.manifest_revision) <> "LongInteger" and type(data.manifest_revision) <> "roLongInteger" then return
        m.settingsRevision = data.manifest_revision
        if type(data.scopes) = "roArray" then m.settingsScopes = data.scopes
        Api("settings_contract", {}, "settings_manifest", m.settingsEpoch)
    else if purpose = "settings_manifest"
        if data.revision <> m.settingsRevision then return
        m.settingsManifest = data
        destinations = SiloUISettingsScopeChoices()
        currentSupported = false
        for each destination in destinations
            if destination.scope = m.settingsScope then currentSupported = true
        end for
        if not currentSupported and destinations.Count() > 1 then m.settingsScope = destinations[0].scope
        m.settingsKeys = SiloUISettingsKeys(data, m.settingsRevision)
        if m.settingsKeys.Count() > 0 then Api("settings_effective", {keys:m.settingsKeys}, "settings_values", m.settingsEpoch)
    else if purpose = "settings_values"
        if data.revision <> m.settingsRevision then return
        m.preferences = SiloUISettingsEffective(m.localPreferences, data)
        m.settingsReady = true
        if type(data.items) = "roArray"
            for each row in data.items
                if type(row) = "roAssociativeArray"
                    if row.key = "playback.preferred_quality" then m.qualityExplicit = SiloUISettingsAuthoredQuality(row)
                end if
            end for
        end if
    else if purpose = "settings_write"
        m.settingsWriteBusy = false
        ' A stored row can still be constrained or shadowed by another scope.
        ' Read effective values before presenting the server's resolved behavior.
        Api("settings_effective", {keys:m.settingsKeys}, "settings_values", m.settingsEpoch)
        Toast("Setting saved to " + m.settingsScope + ".")
    end if
end sub

sub SiloUISettingsPersist()
    section = AppRegistrySection("preferences")
    rows = ParseJson(section.Read("playbackScopes"), "i")
    rows = SiloUISettingsCachePut(rows, m.sourceId, m.profileId, m.localPreferences, m.qualityExplicit = true)
    section.Write("playbackScopes", FormatJson(rows))
    section.Flush()
end sub

sub SiloUISettingsChange(setting as String, value as Dynamic)
    if m.settingsWriteBusy = true then Toast("Wait for the current setting to save.") : return
    if m.localPreferences = invalid then m.localPreferences = SiloUISettingsPreferences(m.preferences)
    if setting = "quality" then m.qualityExplicit = true
    m.localPreferences[setting] = value
    m.localPreferences = SiloUISettingsPreferences(m.localPreferences)
    m.preferences[setting] = value
    m.preferences = SiloUISettingsPreferences(m.preferences)
    if m.settingsEpoch = invalid then m.settingsEpoch = 0
    m.settingsEpoch++
    SiloUISettingsPersist()
    remote = SiloUISettingsRemote()
    if not remote.DoesExist(setting) then return
    if m.provider <> "silo" or m.settingsReady <> true then return
    if not SiloUISettingsCanWrite(m.settingsManifest, m.settingsRevision, remote[setting], m.settingsScope) then return
    allowedScope = false
    for each scope in m.settingsScopes
        if scope = m.settingsScope then allowedScope = true
    end for
    if not allowedScope then return
    m.settingsWriteBusy = true
    wireValue = value
    if setting = "subtitleLanguage" and value = "" then wireValue = invalid
    Api("settings_write", {key:remote[setting],scope:m.settingsScope,value:wireValue}, "settings_write", m.settingsEpoch)
end sub

function SiloUISettingsChoices(setting as String) as Object
    values = []
    if setting = "quality" then values = ["original", "1080p", "720p"]
    if setting = "subtitles" then values = ["off", "auto", "always"]
    if setting = "subtitleLanguage" then values = ["", "en", "es", "fr", "de", "it", "ja", "ko", "zh", "pt"]
    if setting = "introSkipMode" then values = ["never", "ask", "always"]
    if setting = "autoPlayNext" or setting = "showForced" or setting = "preferSdh" or setting = "autoSkipRecap" or setting = "autoSkipCredits" then values = [true, false]
    if setting = "promptSeconds" then values = [0, 10, 15, 30, 60, 120]
    if setting = "stillWatching" then values = [0, 2, 3, 4, 5, 10, 20]
    choices = []
    for each value in values
        label = "No preference"
        if type(value) = "String" or type(value) = "roString"
            if value <> "" then label = UCase(Left(value,1)) + Mid(value,2)
            languages = {en:"English",es:"Spanish",fr:"French",de:"German",it:"Italian",ja:"Japanese",ko:"Korean",zh:"Chinese",pt:"Portuguese"}
            if setting = "subtitleLanguage" and languages.DoesExist(value) then label = languages[value]
        else
            label = value.ToStr()
            if type(value) = "Boolean" or type(value) = "roBoolean"
                if value then label = "On" else label = "Off"
            end if
        end if
        choices.Push({label:label,action:"preference",setting:setting,value:value})
    end for
    if SiloUISettingsResetAllowed(setting)
        choices.Push({label:"Use inherited value",action:"settings_inherit",setting:setting,scope:m.settingsScope,epoch:m.settingsEpoch,owner:SiloUIOwner()})
    end if
    choices.Push({label:"Back to Settings",action:"settings"})
    return choices
end function

function SiloUISettingsScopeChoices() as Object
    choices = []
    labels = {profile:"This profile on all devices",profile_device:"Only this Roku",profile_client:"All TVs for this profile"}
    if type(m.settingsScopes) = "roArray"
        known = SiloUISettingsRemote()
        for each scope in ["profile","profile_device","profile_client"]
            capability = false
            for each allowed in m.settingsScopes
                if allowed = scope then capability = true
            end for
            supported = false
            if capability
                for each setting in known
                    if SiloUISettingsCanWrite(m.settingsManifest,m.settingsRevision,known[setting],scope) then supported = true
                end for
            end if
            if supported then choices.Push({label:labels[scope],action:"settings_scope_set",scope:scope})
        end for
    end if
    choices.Push({label:"Back to Settings",action:"settings"})
    return choices
end function

' Sign-out retires all profile snapshots for this source, since a later account
' can reuse a profile ID. Display/navigation remain independent device choices.
sub SiloUISettingsClearSignout()
    section = AppRegistrySection("preferences")
    rows = ParseJson(section.Read("playbackScopes"), "i")
    retained = []
    if type(rows) = "roArray"
        inspected = 0
        for each row in rows
            inspected++
            if inspected > 4 then exit for
            if type(row) = "roAssociativeArray"
                if row.sourceId <> m.sourceId then retained.Push(row)
            end if
        end for
    end if
    section.Write("playbackScopes",FormatJson(retained))
    section.Delete(m.provider)
    section.Delete(m.provider + ".qualityExplicit")
    for each key in section.GetKeyList()
        if Left(key,9) = "playback." then section.Delete(key)
    end for
    section.Flush()
    m.preferences = SiloUISettingsPreferences(invalid)
    m.localPreferences = SiloUISettingsPreferences(invalid)
    m.qualityExplicit = false
    m.settingsReady = false
end sub

' Reset only a remote key advertised for the explicitly selected destination.
function SiloUISettingsResetAllowed(setting as String) as Boolean
    if m.provider <> "silo" or m.settingsReady <> true or m.settingsWriteBusy = true then return false
    remote = SiloUISettingsRemote()
    if not remote.DoesExist(setting) then return false
    if not SiloUISettingsCanWrite(m.settingsManifest,m.settingsRevision,remote[setting],m.settingsScope) then return false
    if type(m.settingsScopes) <> "roArray" then return false
    for each scope in m.settingsScopes
        if scope = m.settingsScope then return true
    end for
    return false
end function

function SiloUISettingsResetCurrent(choice as Dynamic) as Boolean
    if type(choice) <> "roAssociativeArray" then return false
    if type(choice.owner) <> "roAssociativeArray" then return false
    owner = SiloUIOwner()
    if choice.owner.provider <> owner.provider or choice.owner.sourceId <> owner.sourceId or choice.owner.profileId <> owner.profileId or choice.owner.generation <> owner.generation then return false
    return choice.epoch = m.settingsEpoch and choice.scope = m.settingsScope
end function

sub SiloUISettingsResetConfirm(choice as Object)
    if not SiloUISettingsResetCurrent(choice) then return
    if not SiloUISettingsResetAllowed(choice.setting) then return
    labels = {profile:"This profile on all devices",profile_device:"Only this Roku",profile_client:"All TVs for this profile"}
    node = CreateObject("roSGNode", "Dialog")
    node.title = "Use inherited value?"
    node.maxHeight = 700
    node.message = "Remove only this setting's override from: " + labels[choice.scope] + ". Other scopes and settings stay saved. The server will resolve the inherited value."
    node.buttons = ["Use inherited value", "Cancel"]
    node.observeField("buttonSelected","onSiloUISettingsResetConfirm")
    m.settingsResetConfirm = {choice:choice,ticket:BrowseEventTicket(node,"onSiloUISettingsResetConfirm")}
    m.top.dialog = node
end sub

sub onSiloUISettingsResetConfirm(event = invalid as Dynamic)
    pending = m.settingsResetConfirm
    if pending = invalid then return
    if not BrowseTakeEventTicket(pending.ticket,event) then return
    m.settingsResetConfirm = invalid
    m.top.dialog = invalid
    if pending.ticket.node.buttonSelected <> 0 then return
    choice = pending.choice
    if not SiloUISettingsResetCurrent(choice) then return
    if not SiloUISettingsResetAllowed(choice.setting) then return
    m.settingsEpoch++
    m.settingsWriteBusy = true
    remote = SiloUISettingsRemote()
    extra = {setting:choice.setting,key:remote[choice.setting],scope:choice.scope,epoch:m.settingsEpoch,owner:choice.owner,context:pending.ticket.context}
    ApiOwned("settings_reset",{key:extra.key,scope:extra.scope},"settings_reset",extra,extra.owner)
end sub

sub SiloUISettingsResetResult(result as Object, data as Object, extra as Dynamic)
    if not SiloUISettingsResetCurrent(extra) then return
    m.settingsWriteBusy = false
    confirmed = result.ok = true and data.reset = true and data.key = extra.key and data.scope = extra.scope
    if not confirmed
        if BrowseContextCurrent(extra.context) then Toast("Override removal was not confirmed. Your saved value is unchanged.")
        return
    end if
    ' Remove only this key's offline override after the server receipt. Local
    ' appearance/navigation live elsewhere and other playback keys are retained.
    m.localPreferences.Delete(extra.setting)
    m.localPreferences = SiloUISettingsPreferences(m.localPreferences)
    m.preferences.Delete(extra.setting)
    m.preferences = SiloUISettingsPreferences(m.preferences)
    if extra.setting = "quality" then m.qualityExplicit = false
    SiloUISettingsPersist()
    m.settingsReady = false
    ApiOwned("settings_effective",{keys:m.settingsKeys},"settings_values",m.settingsEpoch,extra.owner)
    if BrowseContextCurrent(extra.context) then Toast("Override removed. Refreshing the inherited value.")
end sub
