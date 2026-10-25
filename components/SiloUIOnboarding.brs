' Source choice, Silo device-code / Plex PIN sign-in, profile and server choice,
' and the settings sheet. Credentials stay on the approval page; server entry is local.

sub OnboardingInit()
    m.ob = m.top.findNode("onboarding")
    m.obEyebrow = m.top.findNode("obEyebrow")
    m.obEyebrow.font = SiloUIFont(18, true)
    m.obTitle = m.top.findNode("obTitle")
    m.obTitle.font = SiloUIFont(40, true)
    m.obBody = m.top.findNode("obBody")
    m.obBody.font = SiloUIFont(22, false)
    m.obCode = m.top.findNode("obCode")
    m.obCode.font = SiloUIFont(64, true)
    m.obButtons = m.top.findNode("obButtons")
    m.pollTimer = m.top.findNode("pollTimer")
    m.pollTimer.observeField("fire", "onPollTimer")
    m.obButtons.observeField("itemSelected", "onObSelected")
    m.top.findNode("obEntryTimer").observeField("fire", "onObEntryTimer")
    m.preferences = SiloUISettingsPreferences(invalid)
    m.obStatus = {}
    m.obMode = ""
    m.obChoices = []
    SiloUISignInInit()
end sub

sub ObScreen(eyebrow as String, title as String, body as String, code as String, choices as Object)
    if m.lanRendering <> true then SiloUILanRetire()
    if m.obQr <> invalid then SiloUISignInClearQr()
    if m.view <> "onboarding"
        ' Keep the opening Select on the manual peer. Native focus is handed
        ' off on the next event-loop turn after release, never during its key event.
        if m.selectKeyDown = true
            m.obDeferredFocus = true
            timer = m.top.findNode("obEntryTimer")
            timer.duration = 1
            timer.control = "start"
        end if
        ShowView("onboarding")
        SetBackdrop("")
    end if
    if m.launchInitialized = true then SiloUILaunchDialog(choices.Count() > 0)
    m.obEyebrow.text = eyebrow
    m.obTitle.text = title
    m.obBody.text = body
    m.obCode.text = code
    m.obChoices = choices
    content = CreateObject("roSGNode", "ContentNode")
    for each c in choices
        node = content.createChild("ContentNode")
        node.title = c.label
    end for
    m.obButtons.content = content
    m.obButtons.jumpToItem = 0
    bodyHeight = m.obBody.boundingRect().height
    y = 250 + bodyHeight + 30
    m.obCode.translation = [96, y]
    if code <> "" then y = y + 100
    available = 640 - y - 10
    m.obButtons.numRows = Int(available / 46)
    if m.obButtons.numRows < 1 then m.obButtons.numRows = 1
    viewport = m.top.findNode("obChoiceViewport")
    viewport.translation = [96, y + 10]
    viewport.clippingRect = [0,0,1088,m.obButtons.numRows * 46]
    m.obButtons.translation = [0,0]
    m.top.findNode("obMore").visible = choices.Count() > m.obButtons.numRows
    m.zone = ""
    SetZone("obButtons")
end sub

sub OnboardingResult(purpose as String, result as Object, data as Object, extra as Dynamic)
    if purpose = "ob_source_status"
        if extra <> "silo" then return
        m.obStatus.silo = data
        m.obBusy = false
        if ObNeedsFreshLogin(extra)
            if extra = "plex" then ObStartPlex() else ObStartSilo()
        else if result.ok = true and data.connected = true
            EnterSource(extra, data)
        else if extra = "plex"
            ObStartPlex()
        else
            ObStartSilo()
        end if
        return
    end if
    if purpose = "ob_status"
        if extra <> "silo" then return
        m.obStatus.silo = data
        if m.obStatus.silo.connected = true
            EnterSource("silo", m.obStatus.silo)
        else
            ObChooseSource()
        end if
        return
    end if
    if purpose = "ob_server"
        if result.ok <> true then ObError("Couldn't reach the Silo server.") : return
        if type(m.savedServers) = "roArray" then SiloUISignInRemember()
        Api("device_start", {}, "ob_device_start")
    else if purpose = "ob_device_start"
        if result.ok <> true then ObError("Couldn't create a sign-in code.") : return
        approvalUri = SiloUISignInApprovalUri(TextOr(data.verificationUri),TextOr(data.userCode),TextOr(data.verificationUriComplete))
        body = "On your phone, open " + TextOr(data.verificationUri) + ", enter the code and approve."
        if approvalUri <> TextOr(data.verificationUri) then body = "Scan the QR, tap Open in the Silo app, then approve. Or visit " + TextOr(data.verificationUri) + " and enter the code below."
        m.obPollMs = NumberOr(data.intervalMs, 5000)
        if m.obPollMs < 2000 then m.obPollMs = 2000
        ObScreen("Sign in to Silo", "Connect your Silo account", body, TextOr(data.userCode), [{label: "Get a new code", action: "silo_code"}, {label: "Change server", action: "silo_servers"}, {label: "Back", action: "sources"}])
        if m.obQr <> invalid then SiloUISignInShowQr(approvalUri)
        ObSchedulePoll()
    else if purpose = "ob_device_poll"
        if m.obMode <> "silo" then return
        state = TextOr(data.status)
        if state = "" then state = TextOr(data.state)
        if result.ok <> true
            ObSchedulePoll()
        else if state = "approved"
            m.obFreshProvider = "silo"
            m.obMode = ""
            Api("profiles", {}, "ob_profiles")
        else if state = "denied"
            ObError("Sign-in was denied on the Silo page.")
        else if state = "expired"
            ObError("The sign-in code expired.")
        else
            ObSchedulePoll()
        end if
    else if purpose = "ob_profiles"
        m.obBusy = false
        if result.ok <> true or type(data.profiles) <> "roArray" then ObError("Couldn't load profiles.") : return
        choices = []
        for each p in data.profiles
            choices.Push({label: TextOr(p.name), action: "profile", profile: p})
        end for
        if choices.Count() = 1 and data.profiles[0].hasPin <> true and m.obSwitching <> true
            m.obBusy = true
            Api("select_profile", {profileId: data.profiles[0].profileId, profileName: data.profiles[0].name}, "ob_profile_set", "silo", "silo")
            return
        end if
        if m.obSwitching = true then choices.Push({label: "Back to Settings", action: "settings"})
        ObScreen("Silo", "Who's watching?", "Choose a profile.", "", choices)
    else if purpose = "ob_profile_set"
        m.obBusy = false
        if result.ok <> true
            Toast("Couldn't switch profile. Check the PIN and try again.")
            return
        end if
        ObFreshLoginComplete("silo")
        EnterSource("silo", data)
    else if purpose = "ob_pin_start"
        if result.ok <> true then ObError("Couldn't create a Plex code.") : return
        m.obPin = data
        ObScreen("SIGN IN TO PLEX", "Link your Plex account", "On your phone or computer, open plex.tv/link and enter this code.", TextOr(data.code), [{label: "Get a new code", action: "plex"}, {label: "Back", action: "sources"}])
        m.obPollMs = 2000
        ObSchedulePoll()
    else if purpose = "ob_pin_poll"
        if m.obMode <> "plex" then return
        state = TextOr(data.state)
        if result.ok = true and state = "linked"
            m.obFreshProvider = "plex"
            m.obMode = ""
            Api("resources", {}, "ob_servers", invalid, "plex")
        else if state = "expired"
            ObError("The Plex code expired.")
        else
            ObSchedulePoll()
        end if
    else if purpose = "ob_servers"
        if result.ok <> true or type(data.servers) <> "roArray" or data.servers.Count() = 0 then ObError("No Plex servers are available to this account.") : return
        if data.servers.Count() = 1
            Api("select_server", {machineId: data.servers[0].machineId}, "ob_server_set", invalid, "plex")
            return
        end if
        choices = []
        for each s in data.servers
            choices.Push({label: TextOr(s.name), action: "server", server: s})
        end for
        ObScreen("PLEX", "Choose a server", "Pick the Plex Media Server to browse.", "", choices)
    else if purpose = "ob_server_set"
        if result.ok <> true then ObError("Couldn't connect to that server.") : return
        ObFreshLoginComplete("plex")
        EnterSource("plex", data)
    else if purpose = "ob_signout"
        m.obBusy = false
        if result.ok <> true then Toast("Couldn't sign out. Try again.") : OnboardingSettings() : return
        SiloUISettingsClearSignout()
        m.provider = "" : m.sourceId = "" : m.profileId = ""
        ObChooseSource()
    end if
end sub

sub ObSchedulePoll()
    m.pollTimer.control = "stop"
    m.pollTimer.duration = m.obPollMs / 1000
    m.pollTimer.control = "start"
end sub

sub onPollTimer()
    if m.view <> "onboarding" then return
    if m.obMode = "silo" then Api("device_poll", {}, "ob_device_poll", invalid, "silo")
    if m.obMode = "plex" then Api("pin_poll", {pinId: m.obPin.pinId, expiresAtMs: m.obPin.expiresAtMs}, "ob_pin_poll", invalid, "plex")
end sub

sub ObError(message as String)
    m.obMode = ""
    m.pollTimer.control = "stop"
    choices = [{label: "Try again", action: "retry"}]
    if m.obLast = "silo" then choices.Push({label: "Change server", action: "silo_servers"})
    choices.Push({label: "Back", action: "sources"})
    ObScreen("SOMETHING WENT WRONG", message, "Try again, or choose another source.", "", choices)
end sub

sub ObChooseSource()
    ObResetScope()
    m.obImagesCleared = true
    m.obPage = "sources"
    m.obSwitching = false
    m.obMode = ""
    m.pollTimer.control = "stop"
    body = "Connect Silo to watch your movies and shows."
    ObScreen("Welcome", "Start with your library", body, "", [{label: "Silo", action: "silo"}])
end sub

sub ObStartSilo()
    m.obMode = ""
    m.pollTimer.control = "stop"
    if type(m.savedServers) = "roArray" and m.savedServers.Count() = 0
        if type(m.obStatus) = "roAssociativeArray" and type(m.obStatus.silo) = "roAssociativeArray"
            sourceId = TextOr(m.obStatus.silo.sourceId)
            if Left(sourceId, 5) = "silo:"
                address = SiloUISavedServerAddress(Mid(sourceId, 6))
                if address <> "" then m.savedServers = SiloUISavedServers(m.savedServers,address)
            end if
        end if
    end if
    ObShowSiloServers()
end sub

sub ObShowSiloServers()
    m.obMode = ""
    m.pollTimer.control = "stop"
    ObScreen("Sign in to Silo", "Connect your server", "Enter the address of your Silo server, including http:// or https://.", "", [{label: "Enter server address", action: "silo_address"}, {label: "Find servers on this network", action: "silo_find"}, {label: "Back", action: "sources"}])
    if type(m.savedServers) = "roArray"
        if m.savedServers.Count() > 0
            ObScreen("Sign in to Silo", "Choose your server", "Saved addresses on this Roku. Each server uses its own sign-in.", "", SiloUISignInChoices())
            return
        end if
    end if
end sub

sub ObServerAddressDialog()
    dialog = CreateObject("roSGNode", "KeyboardDialog")
    dialog.title = "Silo server address"
    dialog.buttons = ["Connect", "Cancel"]
    dialog.text = TextOr(m.obServerUrl)
    dialog.observeField("buttonSelected", "onObServerSelected")
    dialog.observeField("wasClosed", "onObServerClosed")
    m.obServerDialog = dialog
    m.top.dialog = dialog
end sub

sub onObServerSelected()
    dialog = m.obServerDialog
    if dialog = invalid then return
    address = ""
    if dialog.buttonSelected = 0
        address = dialog.text.Trim()
        if address = "" then Toast("Enter your Silo server address.") : return
    end if
    dialog.text = ""
    dialog.close = true
    m.obServerDialog = invalid
    if address <> "" then ObConnectSilo(address)
end sub

sub onObServerClosed()
    if m.obServerDialog <> invalid then m.obServerDialog.text = ""
    m.obServerDialog = invalid
    if m.view = "onboarding" then SetZone("obButtons")
end sub

sub ObConnectSilo(address as String)
    m.obServerUrl = address
    m.obFreshProvider = ""
    m.obMode = "silo"
    m.obLast = "silo"
    m.provider = "silo"
    m.sourceId = "" : m.profileId = ""
    ObScreen("Sign in to Silo", "Connecting…", "Creating a sign-in code.", "", [{label: "Back", action: "sources"}])
    Api("set_server", {baseUrl: address}, "ob_server", invalid, "silo")
end sub

sub ObStartPlex()
    m.obFreshProvider = ""
    m.obMode = "plex"
    m.obLast = "plex"
    m.provider = "plex"
    m.sourceId = "" : m.profileId = ""
    ObScreen("SIGN IN TO PLEX", "Connecting…", "Creating a Plex code.", "", [{label: "Back", action: "sources"}])
    Api("pin_start", {}, "ob_pin_start", invalid, "plex")
end sub

sub ObChoose(choice as Object)
    action = choice.action
    if action = "launch" then SiloUILaunchFetch() : return
    if action = "plex" then return
    if action = "cleanup_retry" then SiloUIRetryCleanup() : return
    if action = "cleanup_cancel"
        m.transitionIntent = invalid
        m.obBusy = false
        OnboardingSettings()
        return
    end if
    if m.obBusy = true then return
    if action = "sources" or action = "switch_profile" or action = "signout" or action = "profile"
        if SiloUIBeginTransition(choice) then return
    end if
    if action = "silo" or action = "plex"
        m.obPage = ""
        m.obSwitching = false
        if ObNeedsFreshLogin(action)
            if action = "plex" then ObStartPlex() else ObStartSilo()
            return
        end if
        m.obBusy = true
        Api("session_status", {}, "ob_source_status", action, action)
    else if action = "saved_silo"
        address = SiloUISavedServerAddress(choice.address)
        if address <> "" then ObConnectSilo(address)
    else if action = "silo_servers"
        ObShowSiloServers()
    else if action = "forget_servers"
        m.savedServers = []
        section = AppRegistrySection("servers")
        section.Delete("silo")
        section.Flush()
        ObShowSiloServers()
    else if action = "silo_lan_select"
        SiloUILanSelect(choice)
    else if action = "silo_lan_confirm"
        SiloUILanConfirm(choice)
    else if action = "silo_lan_results"
        if m.lanPhase = "confirm" then SiloUILanCandidates()
    else if action = "silo_find"
        SiloUILanFind()
    else if action = "silo_address"
        if m.lanPhase <> invalid and m.lanPhase <> "" then ObShowSiloServers()
        SiloUILanRetire()
        ObServerAddressDialog()
    else if action = "silo_code"
        if TextOr(m.obServerUrl) = "" then ObStartSilo() else ObConnectSilo(m.obServerUrl)
    else if action = "sources"
        ObChooseSource()
    else if action = "retry"
        if m.obLast = "silo" and TextOr(m.obServerUrl) <> "" then ObConnectSilo(m.obServerUrl) else ObStartSilo()
    else if action = "profile"
        if choice.profile.hasPin = true
            ObProfilePin(choice.profile)
        else
            ObResetScope()
            m.obBusy = true
            Api("select_profile", {profileId: choice.profile.profileId, profileName: choice.profile.name}, "ob_profile_set", invalid, "silo")
        end if
    else if action = "server"
        Api("select_server", {machineId: choice.server.machineId}, "ob_server_set", invalid, "plex")
    else if action = "switch_profile"
        m.obSwitching = true
        m.obBusy = true
        ObScreen("Silo", "Who's watching?", "Loading profiles…", "", [])
        Api("profiles", {}, "ob_profiles", invalid, "silo")
    else if action = "signout"
        ObResetScope()
        m.obBusy = true
        Api("sign_out", {}, "ob_signout", invalid, m.provider)
    else if action = "server_tools"
        ServicesOpen()
    else if action = "profile_audio"
        m.history = []
        SiloUIAudioBrowse()
    else if action = "profile_books"
        m.history = []
        SiloUIEbookBrowse()
        m.ebookBrowseReturn = {view:"home",zone:"nav"}
    else if action = "settings"
        OnboardingSettings()
    else if action = "navigation"
        m.obPage = "preference"
        ObScreen("SETTINGS", "Navigation", "Choose where navigation appears.", "", SiloUINavigationChoices())
    else if action = "navigation_select"
        SiloUINavigationSave(choice.value)
        OnboardingSettings()
    else if action = "metadata_server"
        MetadataServerDialog()
    else if action = "appearance"
        m.obPage = "preference"
        ObScreen("SETTINGS", "Appearance", "Choose how the app looks.", "", SiloUIAppearanceChoices())
    else if action = "appearance_select"
        mode = SiloUIAppearanceMode(choice.value)
        SiloUIApplyAppearance(mode)
        SiloUIAppearanceWrite(mode)
        OnboardingSettings()
    else if action = "home_sections"
        HomeSectionsOpen()
    else if action = "settings_scope"
        choices = SiloUISettingsScopeChoices()
        m.obPage = "preference"
        ObScreen("SETTINGS", "Sync destination", "New changes use this explicit scope when the server supports it.", "", choices)
    else if action = "settings_scope_set"
        if m.settingsWriteBusy = true then return
        m.settingsScope = choice.scope
        OnboardingSettings()
    else if action = "quality" or action = "subtitles" or action = "subtitleLanguage" or action = "showForced" or action = "preferSdh" or action = "autoPlayNext" or action = "promptSeconds" or action = "stillWatching" or action = "introSkipMode" or action = "autoSkipRecap" or action = "autoSkipCredits"
        m.obPage = "preference"
        ObScreen("SETTINGS", "Playback " + action, "Choose your default. Explicit playback choices take priority.", "", SiloUISettingsChoices(action))
    else if action = "settings_inherit"
        SiloUISettingsResetConfirm(choice)
    else if action = "preference"
        SiloUISettingsChange(choice.setting, choice.value)
        OnboardingSettings()
    else if action = "resume"
        if m.obImagesCleared = true then HomeLoad()
        m.obImagesCleared = false
        ShowView("home")
        SetZone("nav")
        if m.heroItem <> invalid then HeroShow(m.heroItem)
    end if
end sub

sub OnboardingProfileMenu()
    m.obSwitching = false
    m.obPage = "profile_menu"
    choices = []
    if m.provider = "silo" then choices.Push({label:"Switch profile",action:"switch_profile"})
    choices.Push({label:"Audiobooks",action:"profile_audio"})
    choices.Push({label:"Books",action:"profile_books"})
    choices.Push({label:"Settings",action:"settings"})
    choices.Push({label:"Back",action:"resume"})
    ObScreen("PROFILE", "Menu", "Choose where to go.", "", choices)
end sub

sub OnboardingSettings()
    m.obSwitching = false
    m.obPage = "settings"
    choices = [{label: "Back to Home", action: "resume"}]
    appearance = m.appearanceLabel
    if appearance = invalid then appearance = "OLED"
    navigation = "Top navigation"
    if m.navigationMode = "left" then navigation = "Left overlay"
    choices.Push({label: "Navigation: " + navigation, action: "navigation"})
    choices.Push({label: "Appearance: " + appearance, action: "appearance"})
    metadataLabel = "Off"
    if HmBaseUrl(MetadataRequestConfig("").baseUrl) <> "" then metadataLabel = "Configured"
    choices.Push({label:"Optional metadata server: " + metadataLabel,action:"metadata_server"})
    choices.Push({label: "Quality: " + m.preferences.quality, action: "quality"})
    choices.Push({label: "Subtitles: " + m.preferences.subtitles, action: "subtitles"})
    if m.provider = "silo" then choices.Push({label:"Server tools",action:"server_tools"})
    language = TextOr(m.preferences.subtitleLanguage)
    if language = "" then language = "No preference"
    choices.Push({label:"Subtitle language: " + language,action:"subtitleLanguage"})
    forced = "On"
    if m.preferences.showForced = false then forced = "Off"
    choices.Push({label:"Allow forced captions: " + forced,action:"showForced"})
    sdh = "Off"
    if m.preferences.preferSdh = true then sdh = "On"
    choices.Push({label:"Prefer SDH/CC (this Roku): " + sdh,action:"preferSdh"})
    autoplay = "On"
    if m.preferences.autoPlayNext = false then autoplay = "Off"
    choices.Push({label:"Autoplay next: " + autoplay,action:"autoPlayNext"})
    intro = TextOr(m.preferences.introSkipMode)
    if intro = "" then intro = "ask"
    if m.preferences.introSkipMode = invalid and m.preferences.autoSkipIntro = true then intro = "always"
    choices.Push({label:"Skip intros: " + intro,action:"introSkipMode"})
    recap = "Off"
    if m.preferences.autoSkipRecap = true then recap = "On"
    choices.Push({label:"Auto-skip recaps: " + recap,action:"autoSkipRecap"})
    credits = "Off"
    if m.preferences.autoSkipCredits = true then credits = "On"
    choices.Push({label:"Auto-skip credits: " + credits,action:"autoSkipCredits"})
    seconds = NumberOr(m.preferences.promptSeconds, 10)
    choices.Push({label:"Next episode countdown: " + seconds.ToStr() + " seconds",action:"promptSeconds"})
    count = NumberOr(m.preferences.stillWatching, 3)
    choices.Push({label:"Still watching (this Roku): " + count.ToStr() + " episodes (0 = never)",action:"stillWatching"})
    scope = TextOr(m.settingsScope)
    if scope = "" then scope = "profile"
    if m.settingsReady <> true then scope = "Unavailable · saved locally"
    choices.Push({label:"Sync new changes to: " + scope,action:"settings_scope"})
    if m.provider = "silo" then choices.Push({label:"Manage Home rows",action:"home_sections"})
    choices.Push({label: "Sign out", action: "signout"})
    if m.cleanupFailed = true then choices.Push({label:"Retry session cleanup",action:"cleanup_retry"})
    source = "Silo"
    if m.provider = "plex" then source = "Plex"
    heading = source
    if m.navSource.text <> "" then heading = heading + " · " + m.navSource.text
    ObScreen("SETTINGS", heading, "Playback and subtitle defaults can sync across devices. Appearance and navigation stay on this Roku.", "", choices)
end sub

function OnboardingKey(key as String) as Boolean
    if m.obBusy = true then return true
    if key = "back"
        if m.lanPhase <> invalid and m.lanPhase <> ""
            if m.lanPhase = "confirm"
                SiloUILanCandidates()
            else
                ObShowSiloServers()
            end if
            return true
        end if
        if m.unresolvedAllocation <> invalid and m.transitionIntent <> invalid then m.transitionIntent = invalid
        if m.obPage = "expired" then return true
        if m.obPage = "preference" or m.obSwitching = true
            m.obSwitching = false
            OnboardingSettings()
            return true
        end if
        if m.provider <> "" and m.sourceId <> ""
            if m.obImagesCleared = true
                m.obImagesCleared = false
                HomeLoad()
            end if
            ShowView("home")
            SetZone("nav")
            if m.heroItem <> invalid then HeroShow(m.heroItem)
            return true
        end if
        if m.obMode <> "" then ObChooseSource() : return true
        return false
    end if
    return true
end function

sub onObSelected()
    if m.view <> "onboarding" or m.obDeferredFocus = true then return
    index = m.obButtons.itemSelected
    if index >= 0 and index < m.obChoices.Count()
        m.obOpeningSelect = true
        ObChoose(m.obChoices[index])
    end if
end sub

sub ObProfilePin(profile as Object)
    m.obPinProfile = profile
    dialog = CreateObject("roSGNode", "KeyboardDialog")
    dialog.title = "Enter profile PIN"
    dialog.buttons = ["Unlock", "Cancel"]
    dialog.keyboard.textEditBox.secureMode = true
    dialog.observeField("buttonSelected", "onObPinSelected")
    dialog.observeField("wasClosed", "onObPinClosed")
    m.obPinDialog = dialog
    m.top.dialog = dialog
end sub

sub onObPinSelected()
    dialog = m.obPinDialog
    if dialog = invalid then return
    if dialog.buttonSelected = 0
        params = {profileId: m.obPinProfile.profileId, profileName: m.obPinProfile.name, pin: dialog.text}
        ObResetScope()
        m.obBusy = true
        Api("profile_verify", params, "ob_profile_set", invalid, "silo")
    end if
    dialog.text = ""
    dialog.close = true
    m.obPinProfile = invalid
    m.obPinDialog = invalid
end sub

sub onObPinClosed()
    if m.obPinDialog <> invalid then m.obPinDialog.text = ""
    m.obPinDialog = invalid
    m.obPinProfile = invalid
    if m.view = "onboarding" then SetZone("obButtons")
end sub

' Fence all prior browse jobs before a profile or source mutation. Keep current
' IDs until the task runs: the API must authenticate with the former scope.
sub ObResetScope()
    HomeCacheRetire()
    if m.streamingGrid <> invalid then StreamingRetire(true)
    PlayerCloseTracks()
    if m.shuffle <> invalid or m.shuffleBusy = true then ShuffleLeave()
    PlayerDiscardPrebuffer()
    m.obImagesCleared = true
    PlexClearImages()
    m.generation = m.generation + 1
    m.searchLoaded = []
    m.searchLoadedTitles = {}
    m.searchLoadedScope = invalid
    m.homeLoadedScope = invalid
    m.libraryLoadedScope = invalid
    m.history = []
    m.homeRows = []
    m.heroItem = invalid
    m.detailItem = invalid
    m.detailVersions = []
    m.detailEpisodes = []
    m.detailSimilarItems = []
    m.detailData = invalid
    m.detailSeasons = []
    m.detailPlexSeasons = []
    m.detailFocusEpisode = invalid
    m.detailReloadItem = invalid
    DetailPhotosClear()
    m.detailCastCount = 0
    if m.detailCast <> invalid then m.detailCast.content = invalid
    m.playNext = invalid
    m.homeProgress = []
    m.libraryType = ""
    m.keyboard.text = ""
    m.searchTimer.control = "stop"
end sub

' A saved connected flag is insufficient after this process observed expiry.
' Only a newly approved login followed by profile/server selection clears it.
function ObNeedsFreshLogin(provider as String) as Boolean
    if m.authExpiredProviders = invalid then return false
    return m.authExpiredProviders[provider] = true
end function

sub ObFreshLoginComplete(provider as String)
    if m.obFreshProvider <> provider then return
    if m.authExpiredProviders <> invalid then m.authExpiredProviders[provider] = false
    m.obFreshProvider = ""
end sub

' One-shot fallback also releases the handoff if a device loses key-up.
sub onObEntryTimer()
    m.obDeferredFocus = false
    if m.view = "onboarding" and m.zone = "obButtons" then SetZone("obButtons")
end sub

sub MetadataServerDialog()
    dialog = CreateObject("roSGNode", "KeyboardDialog")
    dialog.title = "Optional metadata HTTPS URL (empty disables)"
    dialog.buttons = ["Save", "Cancel"]
    dialog.text = MetadataRequestConfig("").baseUrl
    dialog.observeField("buttonSelected", "onMetadataServerSelected")
    dialog.observeField("wasClosed", "onMetadataServerClosed")
    m.metadataServerDialog = dialog
    m.top.dialog = dialog
end sub

sub onMetadataServerSelected()
    dialog = m.metadataServerDialog
    if dialog = invalid then return
    if dialog.buttonSelected = 0
        if not SaveMetadataUrl(dialog.text.Trim())
            Toast("Use an HTTPS URL without credentials, query or fragment.")
            return
        end if
        ObResetScope()
    end if
    dialog.text = ""
    dialog.close = true
    m.metadataServerDialog = invalid
    OnboardingSettings()
end sub

sub onMetadataServerClosed()
    m.metadataServerDialog = invalid
end sub
