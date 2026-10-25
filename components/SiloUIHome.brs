' Home: hero for the focused title over full-bleed art, poster rails below.

sub HomeInit()
    m.homeCacheEnabled = false
    m.heroRatingsHeight = 0
    m.rows = m.top.findNode("rows")
    m.rows.itemSize = [1224, 290]
    m.rows.rowItemSize = [[150, 225]]
    m.rows.rowItemSpacing = [[20, 0]]
    m.rows.itemSpacing = [0, 26]
    m.rows.rowHeights = [264]
    m.rows.rowLabelFont = SiloUIFont(20, true)
    m.rows.observeField("rowItemFocused", "onHomeFocus")
    m.rows.observeField("rowItemSelected", "onHomeSelect")
    m.heroLogo = m.top.findNode("heroLogo")
    m.heroLogo.observeField("loadStatus", "onHeroLogo")
    m.heroTitle = m.top.findNode("heroTitle")
    m.heroTitle.font = SiloUIFont(44, true)
    m.heroMeta = m.top.findNode("heroMeta")
    m.heroMeta.font = SiloUIFont(19, false)
    m.heroRatings = m.top.findNode("heroRatings")
    m.heroChips = m.top.findNode("heroRatingChips")
    m.heroDots = m.top.findNode("heroDots")
    m.heroTimer = m.top.findNode("heroTimer")
    m.heroTimer.observeField("fire", "onHeroTick")
    m.heroIndex = 0
    m.homeProgress = []
    m.heroSummary = m.top.findNode("heroSummary")
    m.heroSummary.font = SiloUIFont(18, false)
    m.heroButtons = m.top.findNode("heroButtons")
    m.heroItem = invalid
    m.homeToken = 0
end sub

sub HomeLoad(skipImages = false as Boolean)
    HomeEnsureProgressScope()
    m.homeRevalidating = false
    if m.homeSnapshotScope = HomeProgressScope() and type(m.homeRows) = "roArray"
        m.homeRevalidating = SiloUIHomeHeroRow(m.homeRows) >= 0
    end if
    m.homeRendered = m.homeRevalidating
    if not m.homeRevalidating
        m.homeRows = []
        m.rows.content = CreateObject("roSGNode", "ContentNode")
        HeroShow({title: "Loading your library…", type: "", art: {}})
    end if
    m.homeToken = NumberOr(m.homeToken,0) + 1
    m.homeCacheFresh = false
    m.homeCacheSaved = false
    m.homeHydration = invalid
    m.homeRetry = false
    m.homeErrors = 0
    m.homeReload = false
    if m.homeRetryButtons <> invalid then m.homeRetryButtons.visible = false
    if m.view = "home" and m.zone = "homeRetry" then SetZone("heroButtons")
    if m.provider = "plex" and TextOr(m.plexImageBase) = "" and not skipImages
        Api("image_context", {}, "home_image_context", {token:m.homeToken,scope:HomeProgressScope()})
        return
    end if
    PlayerDiscardPrebuffer()
    m.heroPrebufferAttempt = false
    if not m.homeRevalidating
        BuildButtons(m.heroButtons, "heroButtons", ["Play", "Details"])
        if m.view = "home" then SetZone("heroButtons")
    end if
    if m.provider = "silo"
        Api("home", {}, "home_silo", {token:m.homeToken,scope:HomeProgressScope()})
        if not m.homeRevalidating and m.homeLayoutChangedScope <> HomeProgressScope() then HomeCacheStart("read")
    else
        m.plexPending = 3
        m.plexRows = {}
        Api("home_continue", {}, "home_plex", {token:m.homeToken,scope:HomeProgressScope(),key:"Continue Watching"})
        Api("home_on_deck", {}, "home_plex", {token:m.homeToken,scope:HomeProgressScope(),key:"On Deck"})
        Api("sections", {}, "home_plex_sections", {token:m.homeToken,scope:HomeProgressScope()})
    end if
end sub

sub HomeResult(purpose as String, result as Object, data as Object, extra as Dynamic)
    sectionExtra = extra
    if type(extra) = "roAssociativeArray"
        if extra.token <> m.homeToken then return
        if extra.scope <> invalid and extra.scope <> HomeProgressScope() then return
        extra = extra.key
    end if
    if result.ok <> true then m.homeErrors = NumberOr(m.homeErrors,0) + 1
    if purpose = "home_silo"
        if result.ok <> true then HomeShowRetry() : return
        m.homeCacheFresh = true
        m.homeHydration = SiloUIHomeHydration(data.rows, HomeProgressScope())
        HomeHydrationPump()
    else if purpose = "home_silo_section"
        if m.homeHydration = invalid then return
        SiloUIHomeHydrationComplete(m.homeHydration, sectionExtra.scope, sectionExtra.index, result, data)
        HomeHydrationPump()
    else if purpose = "home_plex"
        m.plexRows[extra] = data
        HomePlexMaybeDone()
    else if purpose = "home_plex_sections"
        m.plexSections = []
        if result.ok = true and type(data.sections) = "roArray" then m.plexSections = data.sections
        m.plexRecent = {}
        for each section in m.plexSections
            m.plexPending = m.plexPending + 1
            Api("library_items", {sectionId: section.sectionId, sort: "addedAt:desc", limit: 24}, "home_plex_recent", {token:m.homeToken,scope:HomeProgressScope(),key:section.sectionId})
        end for
        HomePlexMaybeDone()
    else if purpose = "home_plex_recent"
        m.plexRecent[extra] = data
        HomePlexMaybeDone()
    end if
end sub

sub HomeHydrationPump()
    state = m.homeHydration
    if state = invalid or state.scope <> HomeProgressScope() then return
    if m.view <> "home" then m.homeReload = true : return
    rows = []
    itemCount = 0
    for each row in state.rows
        if row.items.Count() > 0
            rows.Push(row)
            itemCount = itemCount + row.items.Count()
        end if
    end for
    ' Inline content (or the first completed section) must not wait behind
    ' unrelated network requests before becoming usable.
    if rows.Count() > 0 and state.renderedItems = invalid
        HomeHydrationRender(rows)
        state.renderedItems = itemCount
    end if
    index = SiloUIHomeHydrationNext(state)
    if index >= 0
        Api("home_section_items", {sectionId:state.rows[index].rowId}, "home_silo_section", {token:m.homeToken,scope:state.scope,index:index})
        return
    end if
    if state.active >= 0 then return
    if state.renderedItems <> itemCount
        if rows.Count() > 0 or state.errors = 0 or m.homeRevalidating <> true then HomeHydrationRender(rows)
    end if
    if state.errors > 0 then HomeShowRetry()
end sub

sub HomeHydrationRender(rows as Object, refreshComplete = true as Boolean)
    priorHero = m.heroItem
    if m.homeRendered <> true or m.homeRevalidating = true or SiloUIHomeHeroRow(rows) < 0 then priorHero = invalid
    rowId = ""
    column = 0
    if m.homeRendered = true and m.rows <> invalid and type(m.homeRows) = "roArray"
        focus = SiloUIHomeFocusPosition(m.rows.rowItemFocused, m.homeRows.Count())
        if focus <> invalid
            rowId = TextOr(m.homeRows[focus[0]].rowId)
            column = focus[1]
        end if
    end if
    HomeSetRows(rows)
    if refreshComplete then m.homeRevalidating = false
    if rowId <> ""
        for index = 0 to m.homeRows.Count() - 1
            if m.homeRows[index].rowId = rowId
                if column >= m.homeRows[index].items.Count() then column = m.homeRows[index].items.Count() - 1
                if column >= 0 then m.rows.jumpToRowItem = [index,column]
            end if
        end for
    end if
    if type(priorHero) = "roAssociativeArray" then HeroShow(priorHero)
    HomeCacheSave()
end sub

sub HomePlexMaybeDone()
    m.plexPending = m.plexPending - 1
    if m.plexPending > 0 then return
    rows = []
    for each name in ["Continue Watching", "On Deck"]
        d = m.plexRows[name]
        if d <> invalid and type(d.items) = "roArray" and d.items.Count() > 0 then
            sectionType = "on_deck"
            if name = "Continue Watching" then sectionType = "continue_watching"
            rows.Push({title: name, rowId: "plex_" + sectionType, sectionType: sectionType, items: d.items})
        end if
    end for
    if type(m.plexSections) = "roArray"
        for each section in m.plexSections
            d = m.plexRecent[section.sectionId]
            if d <> invalid and type(d.items) = "roArray" and d.items.Count() > 0 then rows.Push({title: "Recently Added · " + section.title, rowId: "plex_recent_" + section.sectionId, sectionType: "recently_added", items: d.items})
        end for
    end if
    if rows.Count() > 0 or NumberOr(m.homeErrors,0) = 0 or m.homeRevalidating <> true then HomeHydrationRender(rows)
    if NumberOr(m.homeErrors,0) > 0 then HomeShowRetry()
end sub

sub HomeSetRows(rows as Object)
    m.homeLoadedRevision = NumberOr(m.homeLoadedRevision,0) + 1
    m.homeLoadedScope = {provider:m.provider,sourceId:m.sourceId,profileId:m.profileId,generation:m.generation}
    HomeEnsureProgressScope()
    HomeVisibilityCheck(rows)
    allowSynthetic = m.provider <> "silo" or (m.homeContinueLayoutScope = HomeProgressScope() and m.homeContinueLayoutToken = m.homeToken and m.homeContinueHidden <> true)
    if m.homeProgress <> invalid then rows = SiloUIHomeApplyProgress(rows, m.homeProgress, allowSynthetic)
    if m.homeCacheRendering <> true then StreamingRememberRows(rows)
    rows = StreamingHomeRows(rows)
    m.homeRows = rows
    m.seriesPosters = SiloUISeriesPosters(rows)
    m.seriesPostersScope = HomeProgressScope()
    m.homeSnapshotScope = HomeProgressScope()
    m.heroIndex = 0
    sizes = []
    heights = []
    root = CreateObject("roSGNode", "ContentNode")
    for each row in rows
        rowNode = root.createChild("ContentNode")
        rowNode.title = row.title
        rowNode.addFields({sectionType: TextOr(row.sectionType), rowId: TextOr(row.rowId)})
        landscape = false
        if row.sectionType = "continue_watching"
            for each item in row.items
                if item.type = "episode" then landscape = true
            end for
        end if
        if row.sectionType = "curated"
            sizes.Push([360, 92])
            heights.Push(136)
        else if row.sectionType = "streaming" or row.sectionType = "formats"
            sizes.Push([180, 92])
            heights.Push(136)
        else if landscape
            sizes.Push([280, 188])
            heights.Push(230)
        else
            sizes.Push([150, 225])
            heights.Push(264)
        end if
        count = 0
        for each item in row.items
            if count >= 40 then exit for
            node = ItemNode(item, landscape)
            if row.sectionType = "streaming" and item.serviceId <> "shudder"
                node.HDPosterUrl = "pkg:/images/providers/" + item.serviceId + ".png"
                node.artCandidates = [node.HDPosterUrl]
            end if
            rowNode.appendChild(node)
            count = count + 1
        end for
    end for
    m.rows.rowItemSize = sizes
    m.rows.rowHeights = heights
    m.rows.content = root
    heroRow = SiloUIHomeHeroRow(rows)
    HomePaintDots()
    if heroRow < 0
        HeroShow({title: "Your library is empty", summary: "Add media to your server and it will show up here.", type: "", art: {}})
        m.homeRendered = true
        if m.launchInitialized = true then SiloUILaunchReady()
        return
    end if
    HeroShow(rows[heroRow].items[0])
    HomeSyncTimer()
    m.homeRendered = true
    if m.launchInitialized = true then SiloUILaunchReady()
end sub

function HomeFocusedItem() as Dynamic
    if m.rows.content = invalid then return invalid
    focus = SiloUIHomeFocusPosition(m.rows.rowItemFocused, m.rows.content.getChildCount())
    if focus = invalid then return invalid
    row = m.rows.content.getChild(focus[0])
    if row = invalid then return invalid
    focus = SiloUIHomeFocusPosition(focus, m.rows.content.getChildCount(), row.getChildCount())
    if focus = invalid then return invalid
    node = row.getChild(focus[1])
    if node = invalid then return invalid
    return node.item
end function

sub onHomeFocus()
    if m.zone <> "rows" then return
    item = HomeFocusedItem()
    if item <> invalid and item.type <> "service" and item.type <> "format" then HeroShow(item)
    if m.publicArtwork <> invalid then SiloUIArtworkFocused()
end sub

sub onHomeSelect()
    item = HomeFocusedItem()
    if item = invalid then return
    if item.type = "format" then LibraryOpenFormat(TextOr(item.formatFilter)) : return
    if item.type = "service" then StreamingOpen(TextOr(item.serviceId)) : return
    DetailOpen(item)
end sub

sub HomeRefreshHero()
    if m.heroItem <> invalid then HeroShow(m.heroItem)
end sub

sub HeroShow(item as Object)
    m.heroItem = item
    PlayerSyncHeroPrebuffer()
    art = ItemArt(item)
    if type(art) <> "roAssociativeArray" then art = {}
    logo = ArtField(art, "logo")
    title = TextOr(item.title)
    if item.type = "episode" and TextOr(item.seriesTitle) <> "" then title = item.seriesTitle
    m.heroTitle.text = title
    if m.heroLogo.uri = logo and logo <> "" and m.heroLogo.loadStatus = "ready"
        m.heroLogo.visible = true
    else
        m.heroLogo.visible = false
        m.heroLogo.uri = logo
    end if
    subtitle = ""
    if item.type = "episode" then subtitle = TextOr(item.title)
    meta = MetaLine(item)
    quality = QualityLine(item)
    if quality <> "" then meta = JoinDots([meta, quality])
    if subtitle <> "" then meta = JoinDots([subtitle, meta])
    m.heroMeta.text = meta
    m.heroRatings.text = ""
    HomeRatingChips(item)
    m.heroSummary.text = TextOr(item.summary)
    HeroLayout()
    backdrop = ArtField(art, "backdrop")
    if backdrop = "" then backdrop = ArtField(art, "still")
    if m.view = "home" then SetBackdrop(backdrop)
    label = "Play"
    if NumberOr(item.resumeMs, 0) > 60000 then label = "Resume"
    row = m.pillGroups.heroButtons
    if row <> invalid then row.pills[0].label.text = label
end sub

sub onHeroLogo()
    if m.memoryHigh = true then return
    if m.heroLogo.loadStatus = "ready"
        FitLogo(m.heroLogo, 440, 130)
        m.heroLogo.visible = true
        HeroLayout()
    end if
end sub

sub HeroLayout()
    y = 0
    if m.heroLogo.visible
        m.heroLogo.translation = [0, 0]
        y = m.heroLogo.height + 14
        m.heroTitle.visible = false
    else
        m.heroTitle.visible = true
        m.heroTitle.translation = [0, 40]
        y = 40 + m.heroTitle.boundingRect().height + 10
    end if
    m.heroMeta.translation = [0, y]
    y = y + 30
    if m.heroChips.getChildCount() > 0
        m.heroChips.translation = [0, y]
        y = y + NumberOr(m.heroRatingsHeight, 0) + 4
    end if
    m.heroSummary.translation = [0, y + 4]
    m.heroButtons.translation = [56, 372]
    ' Use absolute scene coordinates: hero text and actions have different parents.
    hero = m.top.findNode("hero")
    summaryTop = hero.translation[1] + y + 4
    lines = Int((m.heroButtons.translation[1] - 8 - summaryTop) / 24)
    if lines < 0 then lines = 0
    if lines > 3 then lines = 3
    m.heroSummary.visible = lines > 0
    ' Hidden labels still keep a valid positive native maxLines value.
    if lines = 0 then lines = 1
    m.heroSummary.maxLines = lines
end sub

function HomeKey(key as String) as Boolean
    if key = "options" then BrowseSocial(HomeFocusedItem()) : return true
    if m.zone = "homeRetry"
        if key = "OK" then HomeLoad() : return true
        if key = "up" then SetZone("nav") : return true
        if key = "down" and m.homeRows.Count() > 0 then SetZone("rows") : return true
        return true
    end if
    if m.zone = "heroButtons"
        if key = "left" then return PillMove("heroButtons", -1) or true
        if key = "right" then PillMove("heroButtons", 1) : return true
        if key = "up" then SetZone("nav") : return true
        if key = "down"
            if m.homeRetry = true then SetZone("homeRetry") : return true
            if m.homeRows.Count() > 0 then SetZone("rows") : onHomeFocus()
            return true
        end if
        if key = "OK" and m.heroItem <> invalid and TextOr(m.heroItem.itemId) <> ""
            if m.pillGroups.heroButtons.index = 0
                PlayItem(m.heroItem, NumberOr(m.heroItem.resumeMs, 0))
            else
                DetailOpen(m.heroItem)
            end if
            return true
        end if
        if key = "play" and m.heroItem <> invalid then PlayItem(m.heroItem, NumberOr(m.heroItem.resumeMs, 0)) : return true
        return true
    end if
    if m.zone = "rows"
        if key = "up" then SetZone("heroButtons") : return true
        if key = "play"
            item = HomeFocusedItem()
            if item <> invalid and item.type = "service" then StreamingOpen(TextOr(item.serviceId)) : return true
            if item <> invalid then PlayItem(item, NumberOr(item.resumeMs, 0))
            return true
        end if
    end if
    return false
end function

sub HomeSyncTimer()
    PlayerSyncHeroPrebuffer()
    if m.heroTimer = invalid then return
    m.heroTimer.control = "stop"
    if m.view = "home" and m.zone = "heroButtons" and m.memoryHigh <> true then m.heroTimer.control = "start"
end sub

sub onHeroTick()
    if m.view <> "home" or m.zone <> "heroButtons" then return
    if m.homeRows.Count() = 0 then return
    heroRow = SiloUIHomeHeroRow(m.homeRows)
    if heroRow < 0 then return
    items = m.homeRows[heroRow].items
    if items.Count() = 0 then return
    m.heroIndex = SiloUIHomeNextHero(m.view, m.zone, m.heroIndex, items.Count())
    HeroShow(items[m.heroIndex])
    HomePaintDots()
end sub

sub HomePaintDots()
    if m.heroDots = invalid then return
    m.heroDots.removeChildren(m.heroDots.getChildren(-1, 0))
    count = 0
    heroRow = SiloUIHomeHeroRow(m.homeRows)
    if heroRow >= 0 then count = m.homeRows[heroRow].items.Count()
    if count > 6 then count = 6
    for index = 0 to count - 1
        dot = m.heroDots.createChild("Poster")
        dot.uri = "pkg:/images/ui/chip.9.png"
        dot.width = 8 : dot.height = 8 : dot.translation = [index * 16, 0]
        dot.opacity = 0.35
        if index = m.heroIndex then dot.opacity = 1
    end for
end sub

sub HomeRatingChips(item as Object)
    m.heroRatingsHeight = RenderRatingChips(m.heroChips, item)
end sub

function HomeProgressScope() as String
    return m.generation.ToStr() + ":" + TextOr(m.provider) + ":" + TextOr(m.sourceId) + ":" + TextOr(m.profileId)
end function

sub HomeEnsureProgressScope()
    scope = HomeProgressScope()
    if m.homeProgressScope <> scope
        m.homeProgress = []
        m.seriesPosters = {}
        m.seriesPostersScope = ""
    end if
    m.homeProgressScope = scope
end sub

sub HomeUpdateProgress(item as Object, playbackScope as Dynamic)
    HomeEnsureProgressScope()
    if playbackScope <> m.homeProgressScope then return
    m.homeProgress = SiloUIHomeRememberProgress(m.homeProgress, item)
    if m.homeRows = invalid then return
    focus = SiloUIHomeFocusPosition(m.rows.rowItemFocused, m.homeRows.Count())
    priorRow = invalid
    if focus <> invalid
        candidateRow = m.homeRows[focus[0]]
        if type(candidateRow.items) = "roArray"
            focus = SiloUIHomeFocusPosition(focus, m.homeRows.Count(), candidateRow.items.Count())
            if focus <> invalid then priorRow = candidateRow
        end if
    end if
    focused = HomeFocusedItem()
    hero = m.heroItem
    heroIndex = m.heroIndex
    HomeSetRows(m.homeRows)
    m.heroIndex = heroIndex
    heroRow = SiloUIHomeHeroRow(m.homeRows)
    if heroRow >= 0
        count = m.homeRows[heroRow].items.Count()
        if m.heroIndex >= count then m.heroIndex = 0
    end if
    if hero <> invalid
        if SiloUIHomeSameItem(hero, item) then hero = item
        HeroShow(hero)
    end if
    HomePaintDots()
    if priorRow <> invalid
        restored = SiloUIHomeRestoreFocus(m.homeRows, priorRow, focused, focus)
        if restored <> invalid then m.rows.jumpToRowItem = restored
    end if
end sub

sub HomeShowRetry()
    m.homeRetry = true
    if m.homeRetryButtons = invalid then m.homeRetryButtons = m.top.findNode("homeRetryButtons")
    m.homeRetryButtons.visible = true
    BuildButtons(m.homeRetryButtons,"homeRetry",["Retry"])
    if m.homeRows = invalid or m.homeRows.Count() = 0
        HeroShow({title:"Couldn't load Home",summary:"Check your connection, then retry.",type:"",art:{}})
        if m.view = "home" then SetZone("homeRetry")
    else
        Toast("Some Home rows could not load. Retry is available below the hero.")
    end if
    m.homeRendered = true
    if m.launchInitialized = true then SiloUILaunchReady()
end sub

' Exactly one cache worker owns this namespace, including cancellation cleanup.
sub HomeCacheYield()
    m.homeCacheYielded = true
    if m.homeCacheTask = invalid then return
    if m.homeCacheJob.action <> "purge" then m.homeCacheTask.cancelled = true
    if m.homeCacheJob.action = "write" then m.homeCacheSaved = false
end sub

sub HomeCacheStart(action as String)
    if action <> "purge"
        if m.homeCacheEnabled <> true then return
        if m.view <> "home" or m.homeCacheYielded = true then return
        if m.playLoading = true or m.playPlan <> invalid or m.prebuf <> invalid then return
    end if
    if m.homeCacheTask <> invalid then return
    if action <> "purge" and m.provider <> "silo" then return
    task = CreateObject("roSGNode","HomeCacheTask")
    job = {action:action,provider:m.provider,sourceId:m.sourceId,profileId:m.profileId,generation:m.generation,token:NumberOr(m.homeToken,0)}
    if action = "write"
        projection = HomeCacheProjection(m.homeRows)
        job.rows = []
        if projection.row <> invalid
            for each download in projection.downloads
                projection.row.items[download.index].art = {poster:download.url}
            end for
            job.rows = [projection.row]
        end if
        if type(m.heroItem) = "roAssociativeArray"
            job.heroItemId = TextOr(m.heroItem.itemId)
            job.heroUrl = ArtField(ItemArt(m.heroItem),"backdrop")
        end if
    end if
    m.homeCacheTask = task
    m.homeCacheJob = job
    task.job = job
    task.observeField("result","onHomeCacheResult")
    task.control = "run"
end sub

sub HomeCacheSave()
    if m.homeCacheEnabled <> true then return
    if m.homeReload = true then return
    if m.view <> "home" or m.homeCacheYielded = true then return
    if m.playLoading = true or m.playPlan <> invalid or m.prebuf <> invalid then return
    if m.homeSnapshotScope <> HomeProgressScope() then return
    if m.provider <> "silo" or m.homeCacheFresh <> true or m.homeCacheSaved = true then return
    if m.homeCacheTask <> invalid then return
    m.homeCacheSaved = true
    if SiloUIHomeHeroRow(m.homeRows) < 0
        HomeCacheStart("purge")
    else
        HomeCacheStart("write")
    end if
end sub

sub HomeCacheRetire()
    m.homeCachePurgePending = true
    if m.homeCacheTask <> invalid
        m.homeCacheTask.cancelled = true
    else
        m.homeCachePurgePending = false
        HomeCacheStart("purge")
    end if
end sub

sub onHomeCacheResult(event as Object)
    result = event.getData()
    job = m.homeCacheJob
    cancelled = m.homeCacheTask.cancelled = true
    m.homeCacheTask.unobserveField("result")
    m.homeCacheTask = invalid
    m.homeCacheJob = invalid
    if m.homeCachePurgePending = true
        m.homeCachePurgePending = false
        HomeCacheStart("purge")
        return
    end if
    if not cancelled and m.view = "home" and m.homeCacheYielded <> true and HomeCacheCanPublish(job,SiloUIOwner(),NumberOr(m.homeToken,0),m.homeCacheFresh = true)
        if job.action = "read" and result.ok = true
            m.homeCacheRendering = true
            HomeSetRows(result.rows)
            m.homeCacheRendering = false
            m.homeLoadedScope = invalid
            m.homeRevalidating = true
        end if
    end if
    HomeCacheSave()
end sub

sub HomeVisibilityCheck(rows as Object)
    if m.provider <> "silo" then return
    if not SiloUIHomeNeedsSynthetic(rows,m.homeProgress) then return
    scope = HomeProgressScope()
    if m.homeContinueLayoutScope = scope and m.homeContinueLayoutToken = m.homeToken then return
    if m.homeVisibilityPending <> invalid
        if m.homeVisibilityPending.scope = scope and m.homeVisibilityPending.token = m.homeToken then return
    end if
    m.homeVisibilityPending = {scope:scope,token:m.homeToken}
    ApiOwned("home_sections_settings",{},"home_visibility",m.homeVisibilityPending,SiloUIOwner())
end sub

sub HomeVisibilityResult(result as Object, data as Object, extra as Dynamic)
    if type(extra) <> "roAssociativeArray" then return
    if extra.scope <> HomeProgressScope() or extra.token <> m.homeToken then return
    if result.sessionRevision <> SessionRevision("silo") then return
    if m.homeVisibilityPending = invalid then return
    if m.homeVisibilityPending.scope <> extra.scope or m.homeVisibilityPending.token <> extra.token then return
    m.homeVisibilityPending = invalid
    m.homeContinueLayoutScope = extra.scope
    m.homeContinueLayoutToken = extra.token
    m.homeContinueHidden = true
    if result.ok = true then m.homeContinueHidden = HomeSectionsContinueHidden(data.items,invalid)
    if result.ok <> true then Toast("Home row visibility could not be checked.")
    if m.view = "home" and type(m.homeRows) = "roArray" then HomeHydrationRender(m.homeRows,false)
end sub
