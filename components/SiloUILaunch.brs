' Cold and roInput links share the existing authentication and allocation drain.
sub SiloUILaunchInit()
    m.launchInitialized = true
    m.launchSerial = 0
    m.launchPending = invalid
    m.launchComplete = false
    m.launchDialog = false
    m.top.observeField("launchInput", "onLaunchInput")
end sub

sub onLaunchInput()
    SiloUILaunchReceive(m.top.launchInput)
end sub

sub SiloUILaunchReceive(args as Dynamic)
    m.launchSerial = m.launchSerial + 1
    m.launchPending = SiloUILaunchInput(args)
    if m.launchPending = invalid
        if m.provider = "silo" and m.view <> "onboarding"
            if m.view = "player" then PlayerClose(false)
            SiloUIBeginTransition({action:"launch"})
        end if
        return
    end if
    m.launchPending.serial = m.launchSerial
    m.launchPending.sourceId = TextOr(m.sourceId)
    SiloUILaunchTry()
end sub

sub SiloUILaunchTry()
    if m.launchPending = invalid then return
    if m.view = "onboarding" then return
    if m.provider <> "silo" or TextOr(m.sourceId) = "" or TextOr(m.profileId) = "" then return
    if m.launchPending.sourceId <> "" and m.launchPending.sourceId <> m.sourceId
        SiloUILaunchHome()
        return
    end if
    if m.transitionIntent <> invalid then return
    if m.view = "player" then PlayerClose(false)
    SiloUIBeginTransition({action:"launch"})
end sub

sub SiloUILaunchFetch()
    if m.launchPending = invalid then SiloUILaunchHome() : return
    ShowView("home")
    SetZone("nav")
    link = m.launchPending
    Api("detail", {itemId:link.contentId}, "launch_detail", {serial:link.serial,id:link.contentId,mediaType:link.mediaType})
end sub

sub SiloUILaunchResult(result as Object, data as Object, extra as Dynamic)
    if m.launchPending = invalid or type(extra) <> "roAssociativeArray" then return
    if extra.serial <> m.launchPending.serial then return
    item = data.item
    if result.ok <> true or type(item) <> "roAssociativeArray" then SiloUILaunchHome() : return
    if TextOr(item.itemId) <> extra.id then SiloUILaunchHome() : return
    if extra.mediaType = "series" and item.type = "series"
        nextId = TextOr(item.playItemId)
        nextLink = SiloUILaunchInput({contentId:nextId,mediaType:"episode"})
        if nextLink = invalid then SiloUILaunchHome() : return
        Api("detail", {itemId:nextId}, "launch_detail", {serial:extra.serial,id:nextId,mediaType:"episode"})
        return
    end if
    expected = extra.mediaType
    ' Roku Search supplies the episode ID for series smart bookmarks too.
    if expected = "series" then expected = "episode"
    if item.type <> expected then SiloUILaunchHome() : return
    m.launchPending = invalid
    PlayItem(item, -1)
end sub

sub SiloUILaunchHome()
    m.launchPending = invalid
    if m.provider <> "silo" then return
    if m.view = "player" then PlayerClose(false)
    ShowView("home")
    SetZone("nav")
    Toast("This title is unavailable. Choose something from Home.")
    SiloUILaunchReady()
end sub

' Roku timestamps these at the next render pass. Loading screens are not dialogs.
sub SiloUILaunchDialog(interactive as Boolean)
    if m.launchComplete = true then return
    if interactive = m.launchDialog then return
    m.launchDialog = interactive
    if interactive
        m.top.signalBeacon("AppDialogInitiate")
    else
        m.top.signalBeacon("AppDialogComplete")
    end if
end sub

sub SiloUILaunchReady()
    if m.launchComplete = true then return
    ready = false
    if m.view = "player"
        if m.video <> invalid then ready = m.video.state = "playing"
    else if m.view = "home"
        ready = m.homeRendered = true
        if m.launchPending <> invalid or m.playLoading = true then ready = false
    end if
    if not ready then return
    SiloUILaunchDialog(false)
    m.top.signalBeacon("AppLaunchComplete")
    m.launchComplete = true
end sub
