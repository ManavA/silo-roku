' Silo TV shell. Provider work stays in ApiTask; this scene owns layout, focus
' and navigation. Signed artwork URLs live only on in-memory content nodes.

sub init()
    m.top.backgroundColor = "0x000000FF"
    m.top.backgroundURI = ""
    m.provider = ""
    m.sourceId = ""
    m.profileId = ""
    m.generation = 1
    m.requestId = 0
    m.pending = {}
    m.cleanupTickets = {}
    m.focusTraceRemaining = 160
    m.zone = ""
    m.view = ""
    m.history = []
    m.pillGroups = {}
    m.manualFocus = m.top.findNode("manualFocus")
    SiloUIAccessibilityInit()

    m.backdrop = m.top.findNode("backdrop")
    m.backdropOld = m.top.findNode("backdropOld")
    m.backdropFade = m.top.findNode("backdropFade")
    m.backdrop.observeField("loadStatus", "onBackdropLoaded")
    m.backdropTimer = m.top.findNode("backdropTimer")
    m.backdropTimer.observeField("fire", "onBackdropTimer")
    m.toast = m.top.findNode("toast")
    m.toast.font = SiloUIFont(18, false)
    m.toastTimer = m.top.findNode("toastTimer")
    m.toastTimer.observeField("fire", "onToastTimer")

    m.nav = m.top.findNode("nav")
    m.navPills = m.top.findNode("navPills")
    m.navSource = m.top.findNode("navSource")
    m.navSource.font = SiloUIFont(16, false)
    m.avatarText = m.top.findNode("avatarText")
    m.avatarText.font = SiloUIFont(20, true)
    m.navItems = ["Home", "Search", "Movies", "Shows", "Audiobooks", "Books", "Settings"]
    m.navIndex = 0
    BuildPills(m.navPills, "nav", m.navItems, 10)
    CenterGroup(m.navPills, 1280)

    SiloUIArtworkInit()
    HomeInit()
    StreamingInit()
    DetailInit()
    PlayerInit()
    SiloUIAudioInit()
    SiloUIEbookInit()
    SiloUIEbookBrowseInit()
    OnboardingInit()
    LibraryInit()
    LibrariesInit()
    SearchInit()
    SiloUIAppearanceInit()
    SiloUINavigationInit()
    SiloUINavigationBuild()
    SiloUILaunchInit()
    Boot()
end sub

' Fonts and pills

function SiloUIFont(size as Integer, bold as Boolean) as Object
    font = CreateObject("roSGNode", "Font")
    font.uri = "pkg:/images/fonts/Roboto-Regular.ttf"
    if bold then font.uri = "pkg:/images/fonts/Roboto-Medium.ttf"
    font.size = size
    return font
end function

' A pill row is a manual focus zone: the scene keeps the index and paints it.
sub BuildPills(parent as Object, name as String, labels as Object, spacing as Integer, height = 40 as Integer, fontSize = 18 as Integer)
    parent.removeChildrenIndex(parent.getChildCount(), 0)
    x = 0
    pills = []
    for each text in labels
        g = parent.createChild("Group")
        g.translation = [x, 0]
        bg = g.createChild("Poster")
        bg.uri = "pkg:/images/ui/pill.9.png"
        lbl = g.createChild("Label")
        lbl.font = SiloUIFont(fontSize, true)
        lbl.text = text
        lbl.color = "0xFFFFFFFF"
        rect = lbl.boundingRect()
        w = Int(rect.width) + 32
        estimate = Len(text) * Int(fontSize * 0.55) + 32
        if w < estimate then w = estimate
        if w < 70 then w = 70
        bg.width = w : bg.height = height
        lbl.width = w : lbl.height = height
        lbl.horizAlign = "center" : lbl.vertAlign = "center"
        pills.Push({group: g, bg: bg, label: lbl, width: w})
        x = x + w + spacing
    end for
    m.pillGroups[name] = {pills: pills, index: 0, width: x - spacing}
    PaintPills(name, false)
end sub

sub PaintPills(name as String, focused as Boolean)
    row = m.pillGroups[name]
    if row = invalid then return
    palette = m.appearance
    if palette = invalid then palette = {text:"0xFFFFFFFF", muted:"0xC3CBDAFF", focus:"0xFFFFFFFF", focustext:"0x0B0E14FF", pill:"0x20242CFF"}
    for i = 0 to row.pills.Count() - 1
        pill = row.pills[i]
        active = i = row.index
        if active and focused
            pill.bg.uri = "pkg:/images/ui/pill_focus.9.png"
            pill.label.color = palette.focustext
            pill.bg.blendColor = palette.focus
        else if active
            pill.bg.uri = "pkg:/images/ui/pill_focus.9.png"
            pill.label.color = palette.text
            pill.bg.blendColor = palette.pill
        else
            pill.bg.uri = "pkg:/images/ui/pill_focus.9.png"
            pill.label.color = palette.muted
            pill.bg.blendColor = palette.pill
        end if
        if name = "nav"
            if not focused or not active then pill.label.color = "0xFFFFFFFF"
        end if
        pill.bg.opacity = 1
    end for
end sub

sub CenterGroup(group as Object, width as Integer)
    name = ""
    for each key in m.pillGroups
        if m.pillGroups[key].pills.Count() > 0 and m.pillGroups[key].pills[0].group.getParent().isSameNode(group) then name = key
    end for
    if name = "" then return
    t = group.translation
    group.translation = [Int((width - m.pillGroups[name].width) / 2), t[1]]
end sub

function PillMove(name as String, delta as Integer) as Boolean
    row = m.pillGroups[name]
    if row = invalid then return false
    target = row.index + delta
    if target = row.index or target < 0 or target >= row.pills.Count() then return false
    row.index = target
    PaintPills(name, true)
    if m.zone = name then SiloUIAccessibilityFocused()
    return true
end function

sub BuildButtons(parent as Object, name as String, labels as Object)
    parent.removeChildrenIndex(parent.getChildCount(), 0)
    x = 0
    pills = []
    for i = 0 to labels.Count() - 1
        g = parent.createChild("Group")
        g.translation = [x, 0]
        bg = g.createChild("Poster")
        lbl = g.createChild("Label")
        lbl.font = SiloUIFont(20, true)
        lbl.text = labels[i]
        ' boundingRect can lag the custom font; never go below an estimate.
        rect = lbl.boundingRect()
        w = Int(rect.width) + 48
        estimate = Len(labels[i]) * 11 + 48
        if w < estimate then w = estimate
        if i = 0 and w < 144 then w = 144
        bg.width = w : bg.height = 46
        lbl.width = w : lbl.height = 46
        lbl.horizAlign = "center" : lbl.vertAlign = "center"
        pills.Push({group: g, bg: bg, label: lbl, width: w})
        x = x + w + 14
    end for
    m.pillGroups[name] = {pills: pills, index: 0, width: x - 14, buttons: true}
    PaintButtons(name, false)
end sub

sub PaintButtons(name as String, focused as Boolean)
    row = m.pillGroups[name]
    if row = invalid then return
    palette = m.appearance
    if palette = invalid then palette = {text:"0xFFFFFFFF", muted:"0xC3CBDAFF", focus:"0xFFFFFFFF", focustext:"0x0B0E14FF", pill:"0x20242CFF"}
    for i = 0 to row.pills.Count() - 1
        pill = row.pills[i]
        if i = row.index and focused
            pill.bg.uri = "pkg:/images/ui/button.9.png"
            pill.label.color = palette.focustext
            pill.bg.blendColor = palette.focus
        else
            pill.bg.uri = "pkg:/images/ui/button.9.png"
            pill.label.color = palette.text
            pill.bg.blendColor = palette.pill
        end if
    end for
end sub

sub PaintZone(name as String, focused as Boolean)
    row = m.pillGroups[name]
    if row = invalid then return
    if row.buttons = true
        PaintButtons(name, focused)
    else
        PaintPills(name, focused)
    end if
end sub

' Focus

sub SetZone(zone as String)
    if m.navigationMode = "left"
        if zone = "nav" and m.zone <> "nav" and m.zone <> "drawer"
            m.navigationReturn = invalid
            if SiloUINavigationContentZone(m.view, m.zone) then m.navigationReturn = {view:m.view,zone:m.zone,provider:m.provider,sourceId:m.sourceId,profileId:m.profileId,generation:m.generation}
        end if
    end if
    SiloUIFocusTrace("zoneBefore", zone)
    if m.zone <> "" then PaintZone(m.zone, false)
    m.zone = zone
    node = invalid
    if zone = "obButtons" then node = m.obButtons
    if zone = "rows" then node = m.rows
    if zone = "episodes" then node = m.episodes
    if zone = "detailSimilar" then node = m.detailSimilar
    if zone = "detailCast" then node = m.detailCast
    if zone = "grid" then node = m.grid
    if zone = "librariesList" then node = m.librariesList
    if zone = "librariesRows" then node = m.librariesRows
    if zone = "audioBrowseGrid" then node = m.audioGrid
    if zone = "ebookBrowseGrid" then node = m.ebookGrid
    if zone = "streamingGrid" then node = m.streamingGrid
    if zone = "keyboard" then node = m.keyboard
    if zone = "searchGrid" then node = m.searchGrid
    if zone = "player" then node = m.video
    if node <> invalid
        if zone = "obButtons" and m.obDeferredFocus = true
            m.manualFocus.setFocus(true)
        else
            node.setFocus(true)
        end if
    else
        ' A peer leaf moves focus out of a native list; focusing its Scene
        ' ancestor can leave that hidden descendant holding Select.
        m.manualFocus.setFocus(true)
        PaintZone(zone, true)
    end if
    if zone = "nav" then PaintPills("nav", true)
    m.top.findNode("avatarBg").opacity = 0.45
    if zone = "avatar" then m.top.findNode("avatarBg").opacity = 1
    if m.navigationMode <> invalid then SiloUINavigationSync()
    HomeSyncTimer()
    if m.publicArtwork <> invalid then SiloUIArtworkFocused()
    SiloUIFocusTrace("zoneAfter", zone)
    if m.view = "search" and (zone = "keyboard" or zone = "searchGrid") then SearchResume()
    SiloUIAccessibilityFocused()
end sub

' Views

sub ShowView(view as String)
    if m.publicArtwork <> invalid then SiloUIArtworkRetire()
    if m.view = "home" and view <> "home" then HomeCacheYield()
    if view <> "player" and m.playerStatusPanel <> invalid then m.playerStatusPanel.visible = false
    if m.playLoading = true then PlayerCancelPreparation()
    m.browseViewToken = NumberOr(m.browseViewToken,0)+1
    if m.navigationMode <> invalid
        if m.zone = "drawer" then SetZone("nav")
        m.drawerOpen = false
        m.navigationReturn = invalid
        SiloUINavigationSync()
    end if
    if m.view = "detail" and view <> "detail" then DetailPhotosClear()
    if view <> "detail" then PlayerDiscardPrebuffer()
    if m.view = "audioBrowse" and view <> "audioBrowse" then SiloUIAudioBrowseRetire()
    if m.view = "audio" and view <> "audio" then SiloUIAudioRelease()
    if m.view = "ebookBrowse" and view <> "ebookBrowse" and view <> "ebook" then SiloUIEbookBrowseRetire()
    if m.view = "ebook" and view <> "ebook" and view <> "ebookBrowse" then SiloUIEbookBrowseRetire()
    if m.view = "ebook" and view <> "ebook" then SiloUIEbookRelease()
    if m.view <> view then BackdropClear()
    returningHome = m.view <> "home" and view = "home"
    m.view = view
    if returningHome
        m.homeCacheYielded = false
        HomeCacheSave()
    end if
    for each name in ["home", "detail", "library", "search", "onboarding", "audio", "audioBrowse", "streaming", "ebook", "ebookBrowse"]
        m.top.findNode(name).visible = name = view
    end for
    librariesView = m.top.findNode("libraries")
    librariesView.visible = view = "libraries" or view = "libraryShelves"
    m.nav.visible = view <> "onboarding" and view <> "player" and view <> "audio" and view <> "ebook"
    showArt = view = "home" or view = "detail"
    m.backdrop.visible = showArt
    m.backdropOld.visible = showArt
    m.top.findNode("fadeLeft").visible = showArt
    m.top.findNode("fadeBottom").visible = showArt
    HomeSyncTimer()
    if view = "detail" then DetailPhotosStart()
end sub

sub PushView(view as String, zone as String)
    m.history.Push({view: m.view, zone: m.zone})
    ShowView(view)
    SetZone(zone)
end sub

function PopView() as Boolean
    if m.history.Count() = 0 then return false
    prior = m.history.Pop()
    ShowView(prior.view)
    if prior.view = "home"
        if m.homeReload = true then HomeLoad() else HomeRefreshHero()
        if m.streamingHomeFocus <> invalid then StreamingRestoreHome()
    end if
    if prior.view = "library" and m.libraryReload = true then LibraryOpen(m.libraryType)
    if prior.view = "libraryShelves" or prior.view = "libraries"
        if not LibrariesCurrent({token:m.librariesToken,owner:m.librariesOwner}) then LibrariesOpen() : return true
        LibrariesPaint()
    end if
    if prior.view = "streaming" then StreamingResume()
    if prior.view = "search" and m.searchReload = true then onSearchTimer()
    if prior.view = "detail" and prior.browseDetailItem <> invalid then DetailOpen(prior.browseDetailItem) : return true
    if prior.view = "detail" and m.detailReloadItem <> invalid then DetailOpen(m.detailReloadItem) : return true
    if prior.view = "detail" then SetBackdrop(DetailBackdrop())
    if prior.view = "streaming" and prior.zone = "streamingGrid"
        if m.streamingGrid.content = invalid or m.streamingGrid.content.getChildCount() = 0 then prior.zone = "streamingButtons"
    end if
    SetZone(prior.zone)
    return true
end function

' Backdrop

function BackdropOwner() as Object
    itemId = ""
    if m.view = "home" and m.heroItem <> invalid then itemId = TextOr(m.heroItem.itemId)
    if m.view = "detail" and m.detailItem <> invalid then itemId = TextOr(m.detailItem.itemId)
    return {provider:m.provider,sourceId:m.sourceId,profileId:m.profileId,generation:m.generation,view:m.view,itemId:itemId}
end function

function BackdropOwnerCurrent() as Boolean
    if m.backdropOwner = invalid then return false
    owner = BackdropOwner()
    for each key in owner
        if owner[key] <> m.backdropOwner[key] then return false
    end for
    return true
end function

sub BackdropClear()
    m.backdropTimer.control = "stop"
    m.backdropFade.control = "stop"
    m.pendingBackdrop = ""
    m.backdropRetried = false
    m.backdropOwner = invalid
    m.backdrop.uri = ""
    m.backdrop.opacity = 0
    m.backdropOld.uri = ""
    m.backdropOld.opacity = 0
end sub

sub SetBackdrop(uri as String)
    if not BackdropOwnerCurrent() then BackdropClear()
    if m.memoryHigh = true then return
    m.backdropOwner = BackdropOwner()
    if uri <> m.pendingBackdrop then m.backdropRetried = false
    if uri <> "" and uri = m.backdrop.uri and m.backdrop.loadStatus = "failed" and m.backdropRetried <> true
        ' A refocus can retry once; clear the URI so Poster starts a fresh load.
        m.backdropRetried = true
        m.backdrop.uri = ""
        m.backdrop.opacity = 0
    end if
    m.pendingBackdrop = uri
    if uri = "" then BackdropClear() : return
    m.backdropTimer.control = "stop"
    m.backdropTimer.control = "start"
end sub

sub onBackdropTimer()
    if m.memoryHigh = true or not BackdropOwnerCurrent() then return
    uri = m.pendingBackdrop
    if uri = invalid or uri = m.backdrop.uri then return
    m.backdropFade.control = "stop"
    ' Retain only a successfully loaded image of this same owner while replacing it.
    if m.backdrop.loadStatus = "ready" and m.backdrop.opacity > 0
        m.backdropOld.uri = m.backdrop.uri
        m.backdropOld.opacity = 1
    end if
    m.backdrop.opacity = 0
    m.backdrop.uri = uri
end sub

sub onBackdropLoaded()
    if m.memoryHigh = true or not BackdropOwnerCurrent() then return
    if m.backdrop.uri <> m.pendingBackdrop then return
    if m.backdrop.loadStatus = "ready"
        m.backdropFade.control = "start"
    else if m.backdrop.loadStatus = "failed"
        m.backdropFade.control = "stop"
        m.backdrop.opacity = 0
        if m.publicArtwork <> invalid then SiloUIArtworkBackdrop()
    end if
end sub

' API

sub Api(action as String, params as Object, purpose as String, extra = invalid as Dynamic, provider = "" as String)
    if provider = "" then provider = m.provider
    owner = SiloUIOwner()
    owner.provider = provider
    ApiOwned(action, params, purpose, extra, owner)
end sub

sub ApiOwned(action as String, params as Object, purpose as String, extra as Dynamic, owner as Object)
    if purpose = "play_start" or purpose = "play_prebuf" or purpose = "play_recover_version" or purpose = "audio_start"
        if SiloUIPlaybackAdmissionBlocked()
            ' A refused old dispatch must not retire a newer foreground UI.
            if owner.provider <> m.provider or owner.sourceId <> m.sourceId or owner.profileId <> m.profileId or owner.generation <> m.generation then return
            if purpose = "play_start" or purpose = "play_recover_version"
                if extra <> m.playToken then return
            end if
            if purpose = "audio_start"
                if extra <> m.audioToken then return
            end if
            if purpose = "play_prebuf"
                if m.prebuf <> invalid then if extra = m.prebuf.token then m.prebuf = invalid
            else
                m.playLoading = false
                m.audioLoading = false
                PlayerSetPlaybackStatus("")
                SiloUIShowPlaybackAdmissionFailure()
            end if
            return
        end if
    end if
    m.requestId = m.requestId + 1
    task = CreateObject("roSGNode", "ApiTask")
    task.job = {provider: owner.provider, action: action, params: params, sourceId: owner.sourceId, profileId: owner.profileId, generation: owner.generation, requestId: m.requestId}
    if owner.artworkOwner <> invalid
        job = task.job
        job["artworkOwner"] = owner.artworkOwner
        task.job = job
    end if
    if owner.sessionRevision <> invalid then task.job = SiloUIOwnedJob(task.job, owner.sessionRevision)
    task.observeField("result", "onApiResult")
    m.pending[m.requestId.ToStr()] = {task: task, purpose: purpose, extra: extra, generation: owner.generation, owner: owner}
    if purpose = "play_recover" and owner.provider = "silo"
        captured = SiloPlaybackContext(params.plan,owner)
        if captured <> invalid
            if owner.sessionRevision = invalid or captured.sessionRevision = owner.sessionRevision
                capturedOwner = ParseJson(FormatJson(owner))
                capturedOwner["sessionRevision"] = captured.sessionRevision
                m.pending[m.requestId.ToStr()]["owner"] = capturedOwner
                m.pending[m.requestId.ToStr()]["recoveryContext"] = captured
                task.job = SiloUIOwnedJob(task.job,captured.sessionRevision)
            end if
        end if
    end if
    task.control = "run"
end sub

sub onApiResult(event as Object)
    result = event.getData()
    if type(result) <> "roAssociativeArray" then return
    key = ""
    if result.requestId <> invalid then key = result.requestId.ToStr()
    entry = m.pending[key]
    if entry = invalid then return
    m.pending.Delete(key)
    entry.task.unobserveField("result")
    if entry.purpose = "public_artwork"
        SiloUIArtworkResult(result,entry.extra)
        return
    end if
    resume = m.compatNativeResume
    if entry.purpose = "play_start" and type(resume) = "roAssociativeArray"
        if result.requestId = resume.requestId
            params = SpField(entry.task.job,"params")
            sameRequest = type(params) = "roAssociativeArray"
            if sameRequest
                sameRequest = FormatJson(SpField(params,"excludedVersionIds")) = FormatJson(resume.excludedVersionIds)
                sameRequest = sameRequest and FormatJson(SpField(params,"compatExcludedFileIds")) = FormatJson(resume.compatExcludedFileIds)
            end if
            if not sameRequest
                m.compatNativeResume = invalid
                if entry.extra = m.playToken then m.playLoading = false:PlayerSetPlaybackStatus("")
                ' Reject presentation while retaining the captured allocation cleanup authority.
                entry.extra = -1
                SiloUIAllocationResult(entry,result)
                SiloUIDrainMaybeDone()
                return
            end if
        end if
    end if
    if entry.purpose = "audio_preference"
        PlaybackAudioPreferenceResult(entry.extra)
        return
    end if
    m.subtitleResultRequestId = result.requestId
    ' A failed ordinary stop is not proof that its native owner disappeared.
    ' Only the dormant compatibility admission reads this conservative fence.
    if entry.purpose = "play_report" and result.ok <> true
        reportJob = entry.task.job
        if type(reportJob) = "roAssociativeArray"
            if reportJob.action = "playback_stop" then m.compatNativeStopFailure = entry.owner
        end if
    end if
    if entry.purpose = "seek_reanchor"
        SiloUISeekResult(entry,result)
        m.subtitleResultRequestId = invalid
        SiloUIDrainMaybeDone()
        return
    end if
    if entry.purpose = "subtitle_off" or entry.purpose = "subtitle_select"
        PlaybackSubtitleChangeApiResult(entry,result)
        m.subtitleResultRequestId = invalid
        SiloUIDrainMaybeDone()
        return
    end if
    ' Owned audio sync acknowledgements must drain even after the playback token
    ' changes; the immutable ticket, not the current view, owns the next sample.
    if entry.purpose = "audio_sync"
        if result.errorCode = "auth_required" and entry.generation = m.generation then SiloUIAuthExpired(entry)
        SiloUIAudioSyncResult(result,entry.extra)
        return
    end if
    if entry.purpose = "cleanup_stop"
        if result.errorCode = "auth_required" and entry.generation = m.generation then SiloUIAuthExpired(entry)
        SiloUICleanupResult(result, entry.extra)
        return
    end if
    if Left(entry.purpose,8) = "shuffle_"
        if ShuffleAllocationResult(entry,result) then return
    end if
    recovered = SiloUIRecoveryResult(entry,result)
    allocated = SiloUIAllocationResult(entry, result) or recovered
    if result.errorCode = "auth_required" and entry.generation = m.generation
        SiloUISubtitleResultCleanup(entry,result)
        SiloUIAuthExpired(entry)
        return
    end if
    if entry.purpose = "play_start" and result.errorCode = "compat_prepare_required"
        if SiloUICompatContinuation(entry,result)
            if m.compatPreparation = invalid and m.transitionIntent = invalid and entry.extra = m.playToken and SoScopeEqual(entry.owner,SiloUIOwner())
                m.playLoading = false
                PlayerShowFailure("experimental_selection",result)
            end if
            m.subtitleResultRequestId = invalid
            return
        end if
    end if
    SiloUIDrainMaybeDone()
    if allocated or entry.generation <> m.generation
        SiloUISubtitleResultCleanup(entry,result)
        return
    end if
    if result.ok <> true then print "Silo request action="; result.action; " ok=false code="; result.errorCode
    data = result.data
    if data = invalid then data = {}
    p = entry.purpose
    if p = "home_image_context"
        if type(entry.extra) = "roAssociativeArray"
            if entry.extra.token <> m.homeToken then return
        end if
        if m.provider <> "plex" then return
        if m.view <> "home"
            m.homeReload = true
            return
        end if
        if result.ok <> true or entry.task.imageHolder = invalid
            HomeLoad(true)
            Toast("Artwork is unavailable.")
            return
        end if
        m.plexImageBase = TextOr(data.imageBaseUrl)
        agent = entry.task.imageHolder.GetHttpAgent()
        for each id in PlexImageNodes()
            m.top.findNode(id).SetHttpAgent(agent)
        end for
        HomeLoad()
        return
    end if
    if p = "streaming_identity"
        StreamingIdentityResult(result,data,entry.extra)
        return
    end if
    if p = "streaming_catalog"
        StreamingResult(result,data,entry.extra)
        return
    end if
    if p = "services_result"
        ServicesResult(result,data,entry.extra)
    else if Left(p,8) = "shuffle_"
        ShuffleResult(p,result,data,entry.extra)
    else if p = "audio_select"
        PlaybackAudioResult(result, entry.extra)
    else if p = "home_visibility"
        HomeVisibilityResult(result,data,entry.extra)
    else if Left(p, 14) = "home_sections_"
        HomeSectionsResult(p,result,data,entry.extra)
    else if Left(p, 9) = "settings_"
        SiloUISettingsResult(p, result, data, entry.extra)
    else if Left(p, 7) = "browse_"
        BrowseResult(p, result, data, entry.extra)
    else if Left(p, 7) = "launch_"
        SiloUILaunchResult(result, data, entry.extra)
    else if Left(p, 3) = "ob_"
        OnboardingResult(p, result, data, entry.extra)
    else if Left(p, 5) = "home_"
        HomeResult(p, result, data, entry.extra)
    else if Left(p, 7) = "detail_"
        DetailResult(p, result, data, entry.extra)
    else if Left(p, 13) = "ebook_browse_"
        SiloUIEbookBrowseResult(p,result,data,entry.extra)
    else if Left(p, 13) = "ebook_reader_"
        SiloUIEbookResult(p,result,data,entry.extra)
    else if Left(p, 6) = "audio_"
        SiloUIAudioResult(p,result,data,entry.extra)
    else if Left(p, 5) = "play_"
        PlayerResult(p, result, data, entry.extra)
    else if Left(p, 10) = "libraries_"
        LibrariesResult(p,result,data,entry.extra)
    else if Left(p, 4) = "lib_"
        LibraryResult(p, result, data, entry.extra)
    else if Left(p, 7) = "search_"
        SearchResult(p, result, data, entry.extra)
    end if
    SiloUISubtitleResultCleanup(entry,result)
    m.subtitleResultRequestId = invalid
    if m.launchInitialized = true then SiloUILaunchReady()
end sub

sub Toast(text as String)
    m.toast.translation = [56,660]
    if m.view = "player" and m.transportEnabled = true then m.toast.translation = [92,492]
    if m.view = "onboarding" then m.toast.translation = [96,688]
    m.toast.text = text
    m.toastTimer.control = "stop"
    m.toastTimer.control = "start"
end sub

sub onToastTimer()
    m.toast.text = ""
end sub

' Content helpers

function ItemNode(item as Object, landscape = false as Boolean) as Object
    node = CreateObject("roSGNode", "ContentNode")
    art = ItemArt(item)
    if not landscape and m.provider = "silo" and item.type = "episode"
        posters = {}
        if m.seriesPostersScope = HomeProgressScope() and type(m.seriesPosters) = "roAssociativeArray" then posters = m.seriesPosters
        art = SiloUIEpisodePortraitArt(item, art, posters)
    end if
    fields = SiloUIItemFields(item, art, landscape, TextOr(m.baseUrl))
    node.title = fields.title
    node.HDPosterUrl = fields.HDPosterUrl
    fields.Delete("title")
    fields.Delete("HDPosterUrl")
    node.addFields(fields)
    return node
end function

function ArtField(art as Object, name as String) as String
    value = art[name]
    if type(value) <> "String" and type(value) <> "roString" then return ""
    if Left(value, 1) = "/" and m.baseUrl <> invalid then return m.baseUrl + value
    return value
end function

sub FitLogo(poster as Object, maxW as Integer, maxH as Integer)
    bw = poster.bitmapWidth
    bh = poster.bitmapHeight
    if bw <= 0 or bh <= 0 then return
    scale = maxW / bw
    if bh * scale > maxH then scale = maxH / bh
    poster.width = Int(bw * scale)
    poster.height = Int(bh * scale)
end sub

' Boot

sub Boot()
    m.bootChecks = 0
    Api("session_status", {}, "ob_status", "silo", "silo")
end sub

sub EnterSource(provider as String, status as Object)
    if provider <> "silo" then return
    PlexClearImages()
    m.generation = m.generation + 1
    m.searchLoaded = []
    m.searchLoadedTitles = {}
    m.searchLoadedScope = invalid
    m.homeLoadedScope = invalid
    m.libraryLoadedScope = invalid
    m.provider = provider
    LibrariesNavigation()
    m.obSwitching = false
    m.authExpiredScope = ""
    m.speculationDisabled = m.cleanupFailed = true
    m.trackPref = {}
    m.trackPrefLanes = {}
    m.obPage = ""
    m.preferences = SiloUISettingsPreferences(invalid)
    m.qualityExplicit = false
    m.obImagesCleared = false
    m.sourceId = TextOr(status.sourceId)
    m.baseUrl = ""
    if Left(m.sourceId, 12) = "silo:http://" or Left(m.sourceId, 13) = "silo:https://" then m.baseUrl = Mid(m.sourceId, 6)
    m.profileId = TextOr(status.profileId)
    SiloUISettingsLoad()
    name = TextOr(status.profileName)
    if name = "" then name = TextOr(status.accountName)
    initial = "?"
    if name <> "" then initial = UCase(Left(name, 1))
    m.avatarText.text = initial
    m.navSource.text = SiloUIAppearanceServerLabel(status.serverName)
    m.history = []
    ShowView("home")
    m.pillGroups.nav.index = 0
    if provider = "plex" then Api("image_context", {}, "home_image_context") else HomeLoad()
    SiloUISettingsStart()
    if m.launchInitialized = true then SiloUILaunchTry()
end sub

' Keys

function onKeyEvent(key as String, press as Boolean) as Boolean
    if key = "back" and press then if PlayerFailureBack() then return true
    if key = "OK"
        m.selectKeyDown = press
        if not press and m.obDeferredFocus = true
            timer = m.top.findNode("obEntryTimer")
            timer.control = "stop"
            timer.duration = 0.01
            timer.control = "start"
        end if
    end if
    stage = "keyRelease"
    if press then stage = "keyPress"
    if key = "up" or key = "down" or key = "left" or key = "right" or key = "OK" or key = "back" or key = "options" or key = "play" or key = "rewind" or key = "fastforward" then SiloUIFocusTrace(stage, key)
    if not press
        if key = "OK"
            m.detailOpeningSelect = false
            m.librariesOpeningSelect = false
            m.obOpeningSelect = false
        end if
        return false
    end if
    ' User navigation owns focus before drawer/Back routing can intercept it.
    ' Releases and catalog/focus callbacks must preserve pending audio restoration.
    if m.view = "audioBrowse"
        if key = "up" or key = "down" or key = "left" or key = "right" or key = "OK" or key = "back" or key = "options" then m.audioBrowseRestore = invalid
    end if
    if key = "OK" and m.obOpeningSelect = true then return true
    if m.transitionIntent <> invalid and m.obBusy = true then return true
    if m.view = "ebook" then return SiloUIEbookKey(key)
    if m.view = "ebookBrowse" and key = "back" and m.drawerOpen <> true then return SiloUIEbookBrowseKey(key)
    if m.view = "audio" then return SiloUIAudioKey(key)
    if m.view = "player" then return PlayerKey(key)
    if m.view = "onboarding" then return OnboardingKey(key)
    if key = "back" and m.playLoading = true then PlayerCancelPreparation()
    if m.navigationMode = "left"
        if SiloUINavigationKey(key) then return true
    end if
    if m.zone = "avatar"
        if key = "right" or key = "back" or key = "down" then SetZone("nav") : return true
        if key = "OK"
            OnboardingProfileMenu()
            return true
        end if
        return true
    end if
    if m.zone = "nav"
        if key = "left"
            if m.pillGroups.nav.index = 0 then SetZone("avatar") : return true
            return PillMove("nav", -1)
        end if
        if key = "right" then return PillMove("nav", 1)
        if key = "OK" then NavSelect(m.pillGroups.nav.index) : return true
        if key = "down"
            if m.view = "home" then SetZone("heroButtons") : return true
            if m.view = "detail" then SetZone("detailButtons") : return true
            if m.view = "streaming" then SetZone("streamingButtons") : return true
            if m.view = "audioBrowse" then SetZone("audioBrowseButtons") : return true
            if m.view = "ebookBrowse" then SetZone("ebookBrowseButtons") : return true
            if m.view = "libraries" or m.view = "libraryShelves" then SetZone("librariesButtons") : return true
            if m.view = "library" then LibraryFocusContent() : return true
            if m.view = "search" then SetZone("keyboard") : return true
        end if
        if key = "back"
            if PopView() then return true
            if m.view <> "home" then NavSelect(0) : return true
            return false
        end if
        return true
    end if
    if key = "back"
        if m.view = "libraries" or m.view = "libraryShelves" then LibrariesBack() : return true
        if m.view = "detail" and (m.zone = "detailCast" or m.zone = "detailSimilar" or m.zone = "episodes" or m.zone = "seasons") then SetZone("detailButtons") : DetailScroll() : return true
        if m.view = "home"
            if m.zone = "rows" and m.rows.rowItemFocused <> invalid and (m.rows.rowItemFocused[0] > 0 or m.rows.rowItemFocused[1] > 0)
                m.rows.jumpToRowItem = [0, 0]
                return true
            end if
            if m.zone = "rows" then SetZone("heroButtons") else SetZone("nav")
            return true
        end if
        if PopView() then return true
        SetZone("nav")
        return true
    end if
    if m.view = "home" then return HomeKey(key)
    if m.view = "detail" then return DetailKey(key)
    if m.view = "streaming" then return StreamingKey(key)
    if m.view = "audioBrowse" then return SiloUIAudioBrowseKey(key)
    if m.view = "ebookBrowse" then return SiloUIEbookBrowseKey(key)
    if m.view = "libraries" or m.view = "libraryShelves" then return LibrariesKey(key)
    if m.view = "library" then return LibraryKey(key)
    if m.view = "search" then return SearchKey(key)
    return false
end function

sub NavSelect(index as Integer)
    m.pillGroups.nav.index = index
    PaintPills("nav", m.zone = "nav")
    name = m.navItems[index]
    m.librariesToken = NumberOr(m.librariesToken,0)+1
    m.history = []
    if name = "Home"
        ShowView("home")
        if m.homeReload = true then HomeLoad() else HomeRefreshHero()
        SetZone("heroButtons")
    else if name = "Search"
        ShowView("search")
        if m.searchReload = true then onSearchTimer()
        SetZone("keyboard")
    else if name = "Libraries"
        LibrariesOpen()
    else if name = "Movies"
        LibraryOpen("movie")
    else if name = "Shows"
        LibraryOpen("series")
    else if name = "Audiobooks"
        SiloUIAudioBrowse()
    else if name = "Books"
        SiloUIEbookBrowse()
        ' Navigation selection closes/retains no previous content owner. Back
        ' returns to Home instead of a retired grid or a closed drawer zone.
        m.ebookBrowseReturn = {view:"home",zone:"nav"}
    else if name = "Settings"
        OnboardingSettings()
    end if
end sub

' Temporary native QA trace: fixed labels/booleans only, capped per launch.
function SiloUIFocusLabel(value as Dynamic) as String
    for each allowed in ["", "home", "detail", "library", "search", "onboarding", "player", "nav", "avatar", "obButtons", "heroButtons", "rows", "detailButtons", "seasons", "episodes", "detailCast", "detailSimilar", "grid", "keyboard", "searchGrid", "libraryTabs", "zoneBefore", "zoneAfter", "keyPress", "keyRelease", "homeFocus", "homeSelect", "up", "down", "left", "right", "OK", "back", "play", "options", "rewind", "fastforward"]
        if value = allowed then return allowed
    end for
    return "other"
end function

sub SiloUIFocusTrace(stage as String, input = "" as String)
    if m.focusTraceRemaining = invalid or m.focusTraceRemaining <= 0 then return
    m.focusTraceRemaining = m.focusTraceRemaining - 1
    prefix = "SiloUI focus "
    if stage = "keyPress" or stage = "keyRelease" then prefix = "SiloUI key "
    line = prefix + "stage=" + SiloUIFocusLabel(stage) + " input=" + SiloUIFocusLabel(input) + " view=" + SiloUIFocusLabel(m.view) + " zone=" + SiloUIFocusLabel(m.zone)
    for each name in ["top", "obButtons", "manualFocus", "rows", "episodes", "detailCast", "detailSimilar", "grid", "keyboard", "searchGrid", "video"]
        node = m[name]
        if node <> invalid
            line = line + " " + name + "Focus=" + SiloUIFocusBit(node.hasFocus()) + " " + name + "Chain=" + SiloUIFocusBit(node.isInFocusChain())
        end if
    end for
    print line
end sub

function SiloUIFocusBit(value as Boolean) as String
    if value then return "true"
    return "false"
end function


function PlexImageNodes() as Object
    return ["rows", "grid", "searchGrid", "episodes", "detailSimilar", "backdrop", "backdropOld", "heroLogo", "detailLogo", "nextStill"]
end function

sub PlexClearImages()
    m.plexImageBase = ""
    m.pendingBackdrop = ""
    if m.backdropTimer <> invalid then m.backdropTimer.control = "stop"
    clean = CreateObject("roHttpAgent")
    clean.SetCertificatesFile("common:/certs/ca-bundle.crt")
    for each id in PlexImageNodes()
        node = m.top.findNode(id)
        if node <> invalid
            if id = "rows" or id = "grid" or id = "searchGrid" or id = "episodes" or id = "detailSimilar" then node.content = invalid else node.uri = ""
            node.SetHttpAgent(clean)
        end if
    end for
end sub

function ItemArt(item as Object) as Object
    if m.memoryHigh = true then return {}
    if m.provider = "plex"
        base = TextOr(m.plexImageBase)
        thumb = TextOr(item.thumbKey)
        backdrop = TextOr(item.backdropKey)
        return {poster: SiloUIPlexArt(base, thumb, "poster"), still: SiloUIPlexArt(base, thumb, "still"), backdrop: SiloUIPlexArt(base, backdrop, "backdrop")}
    end if
    if type(item.art) = "roAssociativeArray" then return item.art
    return {}
end function
