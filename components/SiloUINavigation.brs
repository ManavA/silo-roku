' App-wide setting: independent of providers and appearance.
sub SiloUINavigationInit()
    section = AppRegistrySection("preferences")
    m.navigationMode = SiloUINavigationMode(section.Read("navigation"))
    m.drawerOpen = false
    m.drawerIndex = 0
    m.navigationReturn = invalid
end sub

sub SiloUINavigationSave(value as Dynamic)
    mode = SiloUINavigationMode(value)
    section = AppRegistrySection("preferences")
    section.Write("navigation", mode)
    section.Flush()
    m.navigationMode = mode
    ' A drawer-only destination has no corresponding top pill.
    if mode = "top" and m.pillGroups <> invalid
        row = m.pillGroups.nav
        if row <> invalid
            if row.index >= row.pills.Count() then row.index = 0
        end if
    end if
    m.drawerOpen = false
    m.navigationReturn = invalid
end sub

sub SiloUINavigationBuild()
    m.top.findNode("navMenuLabel").font = SiloUIFont(16, true)
    parent = m.top.findNode("drawerItems")
    labels = m.navItems
    if type(labels) <> "roArray" then labels = ["Home", "Search", "Movies", "Shows", "Audiobooks", "Books", "Settings"]
    BuildPills(parent, "drawer", labels, 0, 48, 22)
    for i = 0 to m.pillGroups.drawer.pills.Count() - 1
        pill = m.pillGroups.drawer.pills[i]
        pill.group.translation = [0, i * 64]
        pill.bg.width = 184
        pill.label.width = 184
    end for
end sub

sub SiloUINavigationSync()
    leftMode = m.navigationMode = "left"
    drawerColor = "0x080C1499"
    if m.appearanceMode = "glass" then drawerColor = "0x080C1480"
    m.top.findNode("navDrawerBackground").color = drawerColor
    for each name in ["avatar", "navPills", "navSource"]
        m.top.findNode(name).visible = not leftMode
    end for
    m.top.findNode("navMenu").visible = leftMode
    m.top.findNode("navDrawer").visible = leftMode and m.drawerOpen = true
    m.top.findNode("navSiloLogo").visible = true
    if leftMode
        menuBackground = m.top.findNode("navMenuFocus")
        menuLabel = m.top.findNode("navMenuLabel")
        menuLabel.text = m.top.findNode("avatarText").text
        if menuLabel.text = "" then menuLabel.text = "?"
        menuBackground.uri = "pkg:/images/ui/pill.9.png"
        menuLabel.color = "0xFFFFFFFF"
        menuBackground.opacity = 0
        if m.zone = "nav" or (m.zone = "drawer" and m.drawerIndex = -1)
            menuBackground.uri = "pkg:/images/ui/card_focus.9.png"
            menuBackground.opacity = 1
        end if
        if m.pillGroups.drawer <> invalid
            m.pillGroups.drawer.index = m.drawerIndex
            PaintPills("drawer", m.drawerOpen = true)
        end if
    end if
end sub

sub SiloUINavigationDismiss(restore as Boolean)
    target = m.navigationReturn
    m.drawerOpen = false
    m.navigationReturn = invalid
    SiloUINavigationSync()
    if not restore then return
    if target <> invalid
        validOwner = target.provider = m.provider and target.sourceId = m.sourceId and target.profileId = m.profileId and target.generation = m.generation
        if validOwner and target.view = m.view and SiloUINavigationContentZone(m.view, target.zone) and SiloUINavigationFocusAvailable(target.zone)
            SetZone(target.zone)
            return
        end if
    end if
    SetZone("nav")
end sub

function SiloUINavigationKey(key as String) as Boolean
    if m.drawerOpen = true
        previousIndex = m.drawerIndex
        if key = "up" and m.drawerIndex >= 0 then m.drawerIndex = m.drawerIndex - 1
        if key = "down" and m.drawerIndex < m.pillGroups.drawer.pills.Count() - 1 then m.drawerIndex = m.drawerIndex + 1
        if key = "back" or key = "right"
            SiloUINavigationDismiss(true)
        else if key = "OK"
            index = m.drawerIndex
            SiloUINavigationDismiss(false)
            if index = -1
                if m.provider = "silo" then ObChoose({action:"switch_profile"}) else OnboardingSettings()
            else
                NavSelect(index)
            end if
        else
            SiloUINavigationSync()
            if m.drawerIndex <> previousIndex then SiloUIAccessibilityFocused()
        end if
        return true
    end if
    if m.zone = "nav"
        if key = "OK"
            if m.provider = "silo" then ObChoose({action:"switch_profile"}) else OnboardingSettings()
            return true
        end if
        if key = "left" or key = "back"
            SiloUINavigationOpen()
            return true
        end if
        ' Down retains the existing content route; Right stays collapsed.
        if key = "left" or key = "right" then return true
    end if
    if (key = "left" or key = "back") and SiloUINavigationAtEdge(key)
        SiloUINavigationOpen()
        return true
    end if
    return false
end function

sub SiloUINavigationOpen()
    ' SetZone captures the content owner before focus moves to the manual drawer.
    if m.zone <> "nav" then SetZone("nav")
    m.drawerOpen = true
    m.drawerIndex = m.pillGroups.nav.index
    SetZone("drawer")
end sub

function SiloUINavigationAtEdge(key as String) as Boolean
    if not SiloUINavigationContentZone(m.view, m.zone) then return false
    for each name in ["heroButtons", "detailButtons", "seasons", "libraryTabs", "audioBrowseButtons", "ebookBrowseButtons", "librariesButtons"]
        if m.zone = name
            row = m.pillGroups[name]
            if row = invalid then return false
            return row.index = 0
        end if
    end for
    if m.zone = "librariesList" then return key = "left" or key = "back"
    if m.zone = "audioBrowseGrid"
        if m.audioGrid.itemFocused = invalid or m.audioGrid.numColumns = invalid then return false
        if m.audioGrid.numColumns < 1 then return false
        return m.audioGrid.itemFocused mod m.audioGrid.numColumns = 0
    end if
    if m.zone = "ebookBrowseGrid"
        if m.ebookGrid.itemFocused = invalid or m.ebookGrid.numColumns = invalid then return false
        if m.ebookGrid.numColumns < 1 then return false
        return m.ebookGrid.itemFocused mod m.ebookGrid.numColumns = 0
    end if
    if m.zone = "grid"
        if m.grid.itemFocused = invalid or m.grid.numColumns = invalid then return false
        if m.grid.numColumns < 1 then return false
        return m.grid.itemFocused mod m.grid.numColumns = 0
    end if
    ' RowLists own Left, including their native wrap. Back alone uses the
    ' focused row's first card, without resetting its vertical position.
    if key <> "back" then return false
    for each name in ["rows", "episodes", "detailCast", "detailSimilar", "librariesRows"]
        if m.zone = name
            node = m[name]
            if node = invalid then return false
            if node.rowItemFocused = invalid then return false
            return node.rowItemFocused[1] = 0
        end if
    end for
    return false
end function

' Native lists can lose content after a request or memory cleanup while the menu is open.
function SiloUINavigationFocusAvailable(zone as String) as Boolean
    node = invalid
    nativeList = false
    for each name in ["rows", "episodes", "detailCast", "detailSimilar", "grid", "searchGrid", "streamingGrid", "librariesList", "librariesRows"]
        if zone = name
            nativeList = true
            node = m[name]
        end if
    end for
    if zone = "audioBrowseGrid"
        nativeList = true
        node = m.audioGrid
    end if
    if zone = "ebookBrowseGrid"
        nativeList = true
        node = m.ebookGrid
    end if
    if nativeList
        if node = invalid then return false
        if node.content = invalid then return false
        if zone = "librariesList" or zone = "grid" or zone = "searchGrid" or zone = "streamingGrid" or zone = "audioBrowseGrid" or zone = "ebookBrowseGrid" then return node.content.getChildCount() > 0
        for i = 0 to node.content.getChildCount() - 1
            if node.content.getChild(i).getChildCount() > 0 then return true
        end for
        return false
    end if
    if zone = "homeRetry" then return m.top.findNode("homeRetryButtons").visible = true
    if zone = "libraryRetry" then return m.top.findNode("libraryRetryButtons").visible = true
    if zone = "seasons"
        if m.detailSeasons = invalid then return false
        return m.detailSeasons.Count() > 0
    end if
    return true
end function
