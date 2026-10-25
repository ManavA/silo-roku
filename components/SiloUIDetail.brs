' Detail: logo/title over backdrop, actions, ratings, seasons and episode stills.

sub DetailInit()
    m.detailRatingsHeight = 0
    m.detailCompact = m.top.findNode("detailCompact")
    m.detailCompactTitle = m.top.findNode("detailCompactTitle")
    m.detailCompactTitle.font = SiloUIFont(24, true)
    m.detailCompactMeta = m.top.findNode("detailCompactMeta")
    m.detailCompactMeta.font = SiloUIFont(18, false)
    m.detailCompactSummary = m.top.findNode("detailCompactSummary")
    m.detailCompactSummary.font = SiloUIFont(18, false)
    m.detailLowerViewport = m.top.findNode("detailLowerViewport")
    m.detailLowerContent = m.top.findNode("detailLowerContent")
    m.detailSeasonViewport = m.top.findNode("detailSeasonViewport")
    m.detailSeasonOffset = 0
    m.detailDisplayEpisode = invalid
    m.detailBody = m.top.findNode("detailBody")
    m.detailLogo = m.top.findNode("detailLogo")
    m.detailLogo.observeField("loadStatus", "onDetailLogo")
    m.detailTitle = m.top.findNode("detailTitle")
    m.detailTitle.font = SiloUIFont(44, true)
    m.detailSub = m.top.findNode("detailSub")
    m.detailSub.font = SiloUIFont(20, true)
    m.detailMeta = m.top.findNode("detailMeta")
    m.detailMeta.font = SiloUIFont(18, false)
    m.detailQuality = m.top.findNode("detailQuality")
    m.detailQuality.font = SiloUIFont(18, true)
    m.detailButtons = m.top.findNode("detailButtons")
    m.detailRatings = m.top.findNode("detailRatings")
    m.detailSummary = m.top.findNode("detailSummary")
    m.detailSummary.font = SiloUIFont(18, false)
    m.seasonsLabel = m.top.findNode("seasonsLabel")
    m.seasonsLabel.font = SiloUIFont(22, true)
    m.seasonPills = m.top.findNode("seasonPills")
    m.episodesLabel = m.top.findNode("episodesLabel")
    m.episodesLabel.font = SiloUIFont(22, true)
    m.episodes = m.top.findNode("episodes")
    m.episodes.itemSize = [1168, 190]
    m.episodes.rowItemSize = [[256, 174]]
    m.episodes.rowItemSpacing = [[20, 0]]
    m.episodes.observeField("rowItemSelected", "onEpisodeSelect")
    m.episodes.observeField("rowItemFocused", "onEpisodeFocus")
    m.detailVisit = 0
    m.detailSeasonRequest = 0
    m.detailCast = m.top.findNode("detailCast")
    m.detailCast.observeField("rowItemSelected", "onDetailCastSelect")
    m.detailCast.itemSize = [1168, 222]
    m.detailCast.rowItemSize = [[144, 214]]
    m.detailCast.rowItemSpacing = [[20, 0]]
    m.detailCastCount = 0
    m.detailSimilar = m.top.findNode("detailSimilar")
    m.detailSimilar.observeField("rowItemSelected", "onDetailSimilarSelect")
    m.detailSimilar.itemSize = [1168, 260]
    m.detailSimilar.rowItemSize = [[150, 225]]
    m.detailSimilar.rowItemSpacing = [[20, 0]]
    m.detailItem = invalid
    m.detailSeasons = []
    m.detailEpisodes = []
end sub

sub DetailOpen(item as Object)
    m.detailRatingsHeight = 0
    m.detailRatings.visible = false
    m.detailRatings.removeChildren(m.detailRatings.getChildren(-1, 0))
    DetailPhotosClear()
    m.detailDisplayEpisode = invalid
    m.detailSeasonOffset = 0
    m.detailReloadItem = invalid
    PlayerDiscardPrebuffer()
    m.detailVisit = m.detailVisit + 1
    m.detailAudioChoice = invalid
    m.detailAudioTicket = invalid
    m.detailExperimentalTicket = invalid
    m.detailExperimentalPending = false
    m.detail4KPendingPlay = invalid
    m.detailExperimentalAvailable = false
    m.detailExperimentalDetail = invalid
    m.detailMarkPending = false
    m.detailOpeningSelect = true
    m.detailVersions = []
    m.detailSelectedVersion = ""
    m.detailCast.content = invalid
    m.detailCastCount = 0
    m.detailSimilar.content = invalid
    m.detailSimilarItems = []
    m.detailItem = invalid
    target = item
    m.detailFocusEpisode = invalid
    if item.type = "episode" and (TextOr(item.seriesId) <> "" or TextOr(item.seriesItemId) <> "")
        m.detailFocusEpisode = item
        seriesId = TextOr(item.seriesId)
        if seriesId = "" then seriesId = TextOr(item.seriesItemId)
        target = {itemId: seriesId, title: TextOr(item.seriesTitle), type: "series", art: item.art, badges: {}}
    end if
    if m.view = "detail"
        ShowView("detail")
    else
        m.history.Push({view: m.view, zone: m.zone})
        ShowView("detail")
    end if
    m.detailToken = m.detailVisit
    m.detailRequestedItemId = TextOr(target.itemId)
    m.detailOwnedScope = StreamingScopeKey()
    m.detailSeasons = []
    m.detailPlexSeasons = []
    m.detailEpisodes = []
    m.episodes.content = CreateObject("roSGNode", "ContentNode")
    m.seasonPills.removeChildrenIndex(m.seasonPills.getChildCount(), 0)
    m.pillGroups.Delete("seasons")
    DetailRender(target)
    SetZone("detailButtons")
    Api("detail", {itemId: target.itemId}, "detail_item", m.detailToken)
    if m.provider = "plex"
        Api("related", {itemId: target.itemId}, "detail_similar", m.detailToken)
        if DetailIsSeries(target) then Api("children", {itemId: target.itemId, limit: 100}, "detail_seasons", m.detailToken)
    else
        Api("similar", {itemId: target.itemId}, "detail_similar", m.detailToken)
        if DetailIsSeries(target) then Api("seasons", {seriesId: target.itemId}, "detail_seasons", m.detailToken)
    end if
end sub

function DetailIsSeries(item as Object) as Boolean
    return item.type = "series" or item.type = "show"
end function

function DetailBackdrop() as String
    if m.detailItem = invalid then return ""
    art = ItemArt(m.detailItem)
    if type(art) <> "roAssociativeArray" then return ""
    uri = ArtField(art, "backdrop")
    if uri = "" then uri = ArtField(art, "still")
    return uri
end function

sub DetailRender(item as Object)
    ' Keep art from the summary item when the detail payload omits it.
    if m.detailItem <> invalid and m.detailItem.itemId = item.itemId
        old = m.detailItem.art
        if type(item.art) <> "roAssociativeArray" or item.art.Count() = 0 then item.art = old
    end if
    m.detailItem = item
    art = ItemArt(item)
    if type(art) <> "roAssociativeArray" then art = {}
    m.detailTitle.text = TextOr(item.title)
    logo = ArtField(art, "logo")
    if m.detailLogo.uri <> logo
        m.detailLogo.visible = false
        m.detailLogo.uri = logo
    else
        m.detailLogo.visible = logo <> "" and m.detailLogo.loadStatus = "ready"
    end if
    subtitle = DetailSourceHeading(item,m.detailVersions,TextOr(m.detailSelectedVersion))
    m.detailSub.text = subtitle
    m.detailMeta.text = MetaLine(item)
    m.detailQuality.text = DetailSourceQuality(item,m.detailVersions,TextOr(m.detailSelectedVersion),m.detailAudioChoice)
    m.detailRatingsHeight = RenderRatingChips(m.detailRatings, item)
    m.detailSummary.text = TextOr(item.summary)
    labels = []
    resume = SiloUIDetailResumeMs(item)
    if DetailIsSeries(item)
        labels.Push("Play")
    else if resume > 0
        resumeDuration = FormatDuration(resume)
        if resumeDuration = "" then resumeDuration = Int(resume / 1000#).ToStr() + "s"
        labels.Push("Resume " + resumeDuration)
        labels.Push("From beginning")
    else
        labels.Push("Play")
    end if
    if item.watched = true
        labels.Push("Mark unwatched")
    else
        labels.Push("Mark watched")
    end if
    if type(m.detailVersions) = "roArray" and m.detailVersions.Count() > 1 then labels.Push("Version")
    if SiloUIDetailAudioChoices(m.provider,item,m.detailVersions,TextOr(m.detailSelectedVersion)).Count() > 1 then labels.Push("Audio")
    if m.provider = "silo" and DetailIsSeries(item)
        labels.Push("Shuffle series")
        if type(m.detailSeasons) = "roArray" and m.pillGroups.seasons <> invalid
            seasonIndex = m.pillGroups.seasons.index
            if seasonIndex >= 0 and seasonIndex < m.detailSeasons.Count()
                if TextOr(m.detailSeasons[seasonIndex].itemId) <> "" then labels.Push("Shuffle season")
            end if
        end if
    end if
    if m.detailExperimentalAvailable = true
        if DetailExperimentalCurrent(m.detailExperimentalTicket) then labels.Push("Experimental Play")
    end if
    m.detailActions = labels
    focused = m.zone = "detailButtons"
    BuildButtons(m.detailButtons, "detailButtons", labels)
    PaintButtons("detailButtons", focused)
    backdrop = DetailBackdrop()
    if backdrop = ""
        m.backdrop.uri = ""
        m.backdropOld.uri = ""
        m.backdropOld.opacity = 0
    end if
    SetBackdrop(backdrop)
    DetailCompactRender()
    DetailLayout()
end sub

sub onDetailLogo()
    if m.memoryHigh = true then return
    if m.detailLogo.loadStatus = "ready"
        FitLogo(m.detailLogo, 460, 140)
        m.detailLogo.visible = true
        m.detailTitle.visible = not m.detailLogo.visible
        if m.view = "detail" then DetailLayout()
    end if
end sub

sub DetailLayout()
    y = 0
    if m.detailLogo.visible
        y = m.detailLogo.height + 16
        m.detailTitle.visible = false
    else
        m.detailTitle.visible = true
        m.detailTitle.translation = [0, 20]
        y = 20 + m.detailTitle.boundingRect().height + 12
    end if
    for each node in [m.detailSub, m.detailMeta, m.detailQuality]
        node.visible = node.text <> ""
        if node.visible
            node.translation = [0, y]
            y = y + 28
        end if
    end for
    y = y + 12
    m.detailButtons.translation = [0, y]
    y = y + 66
    ratingsHeight = NumberOr(m.detailRatingsHeight, 0)
    m.detailRatings.visible = ratingsHeight > 0
    if m.detailRatings.visible
        m.detailRatings.translation = [0, y]
        y = y + ratingsHeight + 4
    end if
    m.detailSummary.translation = [0, y]
    y = y + m.detailSummary.boundingRect().height + 24
    m.detailOverviewBottom = 96 + y
    y = 0
    hasSeasons = m.detailSeasons.Count() > 0
    m.seasonsLabel.visible = hasSeasons
    m.detailSeasonViewport.visible = hasSeasons
    m.detailSeasonsY = y
    if hasSeasons
        m.seasonsLabel.translation = [0, y]
        m.detailSeasonViewport.translation = [0, y + 36]
        y = y + 96
    end if
    hasEpisodes = m.detailEpisodes.Count() > 0
    m.episodesLabel.visible = hasEpisodes
    m.episodes.visible = hasEpisodes
    m.detailEpisodesY = y
    if hasEpisodes
        m.episodesLabel.translation = [0, y]
        m.episodes.translation = [0, y + 38]
        y = y + 238
    end if
    m.detailCastY = y
    m.top.findNode("detailCastLabel").translation = [0, y]
    m.top.findNode("detailCastLabel").visible = m.detailCastCount > 0
    m.detailCast.translation = [0, y + 38]
    m.detailCast.visible = m.detailCastCount > 0
    if m.detailCast.visible then y = y + 268
    m.detailSimilar.translation = [0, y + 36]
    m.top.findNode("detailSimilarLabel").translation = [0, y]
    m.detailSimilarY = y
    m.detailSimilar.visible = m.detailSimilarItems.Count() > 0
    m.top.findNode("detailSimilarLabel").visible = m.detailSimilar.visible
    DetailScroll()
end sub

sub DetailScroll()
    compact = m.zone = "seasons" or m.zone = "episodes" or m.zone = "detailCast" or m.zone = "detailSimilar"
    m.detailBody.translation = [56, 96]
    m.detailBody.visible = not compact
    m.detailCompact.visible = compact
    m.nav.visible = true
    shift = 0
    viewportY = m.detailOverviewBottom
    if compact
        viewportY = 284
        if m.zone = "seasons" then shift = m.detailSeasonsY
        if m.zone = "episodes" then shift = m.detailEpisodesY
        if m.zone = "detailCast" then shift = m.detailCastY
        if m.zone = "detailSimilar" then shift = m.detailSimilarY
    end if
    if viewportY > 684 then viewportY = 684
    m.detailLowerViewport.translation = [36, viewportY]
    m.detailLowerViewport.clippingRect = [0, 0, 1188, 684 - viewportY]
    m.detailLowerContent.translation = [20, -shift]
    if m.zone = "seasons" then DetailRevealSeason()
end sub

sub DetailCompactRender()
    item = m.detailDisplayEpisode
    if item = invalid then item = m.detailItem
    if item = invalid then return
    heading = TextOr(item.title)
    if m.detailDisplayEpisode <> invalid then heading = SiloUIDetailEpisodeHeading(item)
    m.detailCompactTitle.text = heading
    m.detailCompactMeta.text = MetaLine(item)
    m.detailCompactSummary.text = TextOr(item.summary)
end sub

sub DetailRevealSeason()
    row = m.pillGroups.seasons
    if row = invalid or row.pills.Count() = 0 then return
    pill = row.pills[row.index]
    leftEdge = pill.group.translation[0]
    m.detailSeasonOffset = SiloUIDetailSeasonOffset(m.detailSeasonOffset, leftEdge, leftEdge + pill.width, row.width, 1168)
    m.seasonPills.translation = [-m.detailSeasonOffset, 0]
end sub

sub DetailResult(purpose as String, result as Object, data as Object, extra as Dynamic)
    if purpose = "detail_episode_actions" then DetailEpisodeResult(result,data,extra) : return
    if purpose = "detail_experimental_probe"
        if not DetailExperimentalCurrent(extra) then return
        availableType = type(data.available)
        available = result.ok = true and (availableType = "Boolean" or availableType = "roBoolean") and data.available = true
        if extra.scope = "episode"
            m.detailEpisode.experimentalAvailable = available
            if m.detailEpisode.ticket.mode = "actions" and m.top.dialog <> invalid
                if m.detailEpisode.ticket.node.isSameNode(m.top.dialog)
                    previous = m.detailEpisode.ticket
                    focusedLabel = ""
                    focusedIndex = NumberOr(previous.node.buttonFocused,-1)
                    if focusedIndex >= 0 and focusedIndex < previous.labels.Count() then focusedLabel = previous.labels[focusedIndex]
                    previous.used = true
                    previous.node.close = true
                    DetailEpisodeMenu()
                    for i = 0 to m.detailEpisode.ticket.labels.Count()-1
                        if m.detailEpisode.ticket.labels[i] = focusedLabel then m.detailEpisode.ticket.node.focusButton = i
                    end for
                end if
            end if
            return
        end if
        m.detailExperimentalAvailable = available
        m.detailExperimentalPending = false
        DetailExperimentalRender()
        captured = m.detail4KPendingPlay
        m.detail4KPendingPlay = invalid
        if type(captured) = "roAssociativeArray"
            if BrowseContextCurrent(captured.context) and captured.selectedVersion = TextOr(m.detailSelectedVersion)
                if DetailExperimentalCurrent(captured.ticket)
                    if not Detail4KSubtitleConsent(captured.startMs) then PlayItem(m.detailItem,captured.startMs,captured.selectedVersion,captured.audio)
                end if
            end if
        end if
        return
    end if
    if m.view <> "detail" or m.detailItem = invalid then return
    if purpose = "detail_episodes"
        if type(extra) <> "roAssociativeArray" then return
        if not SiloUIDetailCurrent(m.view, m.detailToken, extra.visit, m.detailSeasonRequest, extra.season) then return
    else if purpose = "detail_mark"
        if type(extra) <> "roAssociativeArray" or extra.visit <> m.detailToken then return
        m.detailMarkPending = false
        if result.ok <> true then Toast("Couldn't update watched status.") : return
        if extra.item.itemId = m.detailItem.itemId
            m.detailItem.watched = extra.watched
            DetailRender(m.detailItem)
        else
            for each ep in m.detailEpisodes
                if ep.itemId = extra.item.itemId
                    ep.watched = extra.watched
                    ep.resumeMs = 0
                end if
            end for
            if m.episodes <> invalid and m.episodes.content <> invalid
                row = m.episodes.content.getChild(0)
                if row <> invalid
                    for index = 0 to row.getChildCount() - 1
                        node = row.getChild(index)
                        if node <> invalid and node.item <> invalid and node.item.itemId = extra.item.itemId
                            item = node.item
                            item.watched = extra.watched
                            item.resumeMs = 0
                            node.item = item
                            node.watched = extra.watched
                            node.resumeMs = 0
                        end if
                    end for
                end if
            end if
        end if
        Toast("Updated.")
        return
    else
        if extra <> m.detailToken then return
    end if
    if purpose = "detail_item"
        if result.ok <> true then return
        item = data.item
        if type(item) <> "roAssociativeArray" then return
        if TextOr(item.itemId) = "" or TextOr(item.itemId) <> TextOr(m.detailRequestedItemId) then return
        if m.detailOwnedScope <> StreamingScopeKey() then return
        StreamingRememberRows([{items:[item]}])
        m.detailVersions = data.versions
        if type(m.detailVersions) <> "roArray" then m.detailVersions = []
        m.detailCastPeople = SiloUICastPeople(data.cast)
        castRoot = CreateObject("roSGNode", "ContentNode")
        castRow = castRoot.createChild("ContentNode")
        for each person in m.detailCastPeople
            castNode = castRow.createChild("ContentNode")
            castNode.addFields({personName:person.name,personRole:person.role,personId:person.personId,photoUri:""})
        end for
        m.detailCastCount = m.detailCastPeople.Count()
        m.detailCast.content = castRoot
        m.detailExperimentalDetail = data
        DetailRender(item)
        DetailExperimentalProbe()
        DetailPhotosStart()
        if not DetailIsSeries(item) and m.detailVersions.Count() = 1 then PlayerPrebuffer(item, data.versions, data.markers, data)
    else if purpose = "detail_similar"
        if result.ok <> true or type(data.items) <> "roArray" then return
        m.detailSimilarItems = data.items
        root = CreateObject("roSGNode", "ContentNode")
        row = root.createChild("ContentNode")
        for each similar in data.items
            row.appendChild(ItemNode(similar))
        end for
        m.detailSimilar.content = root
        DetailLayout()
    else if purpose = "detail_seasons"
        if result.ok <> true or type(data.items) <> "roArray" then return
        if m.provider = "plex"
            for each entry in data.items
                m.detailPlexSeasons.Push(entry)
            end for
            if data.hasMore = true and NumberOr(data.nextOffset, 0) > 0 and m.detailPlexSeasons.Count() < 100
                Api("children", {itemId: m.detailItem.itemId, offset: data.nextOffset, limit: 100}, "detail_seasons", m.detailToken)
                return
            end if
            data.items = m.detailPlexSeasons
        end if
        m.detailSeasons = []
        labels = []
        chosen = 0
        for each season in data.items
            number = NumberOr(season.seasonNumber, -1)
            if number >= 0
                m.detailSeasons.Push(season)
                name = TextOr(season.title)
                if name = "" then name = "Season " + number.ToStr()
                labels.Push(name)
                if m.detailFocusEpisode <> invalid and m.detailFocusEpisode.seasonNumber = number then chosen = m.detailSeasons.Count() - 1
            end if
        end for
        if m.detailSeasons.Count() = 0 then return
        BuildPills(m.seasonPills, "seasons", labels, 12, 40, 17)
        m.detailSeasonOffset = 0
        m.pillGroups.seasons.index = chosen
        DetailRevealSeason()
        PaintPills("seasons", m.zone = "seasons")
        DetailLoadSeason(chosen)
    else if purpose = "detail_episodes"
        if result.ok <> true or type(data.items) <> "roArray" then return
        if m.provider = "plex"
            for each entry in data.items
                m.detailEpisodes.Push(entry)
            end for
            if data.hasMore = true and NumberOr(data.nextOffset, 0) > 0 and m.detailEpisodes.Count() < 500
                nextExtra = {visit: extra.visit, season: extra.season, itemId: extra.itemId}
                Api("children", {itemId: extra.itemId, offset: data.nextOffset, limit: 100}, "detail_episodes", nextExtra)
                return
            end if
            data.items = m.detailEpisodes
        else
            m.detailEpisodes = data.items
        end if
        root = CreateObject("roSGNode", "ContentNode")
        row = root.createChild("ContentNode")
        focusIndex = 0
        for i = 0 to data.items.Count() - 1
            ep = data.items[i]
            row.appendChild(ItemNode(ep, true))
            if m.detailFocusEpisode <> invalid and ep.itemId = m.detailFocusEpisode.itemId then focusIndex = i
        end for
        m.episodes.content = root
        m.episodesLabel.text = m.detailSeasonName
        DetailLayout()
        if focusIndex > 0 then m.episodes.jumpToRowItem = [0, focusIndex]
    end if
end sub

sub DetailLoadSeason(index as Integer)
    m.detailDisplayEpisode = invalid
    DetailCompactRender()
    m.detailSeasonRequest = m.detailSeasonRequest + 1
    m.detailEpisodes = []
    m.episodes.content = invalid
    season = m.detailSeasons[index]
    m.detailSeasonName = m.pillGroups.seasons.pills[index].label.text
    if m.provider = "plex"
        Api("children", SiloUIPlexChildren(season, 100, 0), "detail_episodes", {visit: m.detailToken, season: m.detailSeasonRequest, itemId: season.itemId})
    else
        Api("episodes", {seriesId: m.detailItem.itemId, seasonNumber: season.seasonNumber}, "detail_episodes", {visit: m.detailToken, season: m.detailSeasonRequest})
    end if
end sub

function DetailFocusedEpisode() as Dynamic
    focus = m.episodes.rowItemFocused
    if focus = invalid or m.episodes.content = invalid then return invalid
    row = m.episodes.content.getChild(0)
    if row = invalid then return invalid
    node = row.getChild(focus[1])
    if node = invalid then return invalid
    return node.item
end function

sub onEpisodeFocus()
    if m.view <> "detail" or m.zone <> "episodes" then return
    ep = DetailFocusedEpisode()
    if ep = invalid then return
    m.detailDisplayEpisode = ep
    DetailCompactRender()
end sub

sub onEpisodeSelect()
    if m.view <> "detail" or m.zone <> "episodes" then return
    ep = DetailFocusedEpisode()
    if ep <> invalid then PlayItem(ep, NumberOr(ep.resumeMs, 0))
end sub

sub DetailAction(index as Integer)
    item = m.detailItem
    if item = invalid then return
    label = m.detailActions[index]
    if label = "Experimental Play"
        ticket = m.detailExperimentalTicket
        if m.detailExperimentalAvailable <> true or not DetailExperimentalCurrent(ticket) then Toast("Experimental playback changed. Wait for a fresh check.") : return
        Toast("Experimental 4K: HDR fallback, subtitles off.")
        PlayItem(item, NumberOr(item.resumeMs,0), ticket.fileId, m.detailAudioChoice, ticket)
    else if Left(label, 4) = "Play" or Left(label, 6) = "Resume"
        if DetailIsSeries(item)
            target = TextOr(item.playItemId)
            if target = "" and m.detailEpisodes.Count() > 0 then target = m.detailEpisodes[0].itemId
            if target = "" then Toast("Nothing to play yet.") : return
            PlayItem({itemId: target, title: item.title, art: item.art}, -1)
        else
            startMs = SiloUIDetailResumeMs(item)
            if not Detail4KSubtitleConsent(startMs) then PlayItem(item, startMs, m.detailSelectedVersion, m.detailAudioChoice)
        end if
    else if label = "From beginning"
        if DetailIsSeries(item) then PlayItem(item, 0, m.detailSelectedVersion, m.detailAudioChoice) : return
        if not Detail4KSubtitleConsent(0) then PlayItem(item, 0, m.detailSelectedVersion, m.detailAudioChoice)
    else if label = "Mark watched" or label = "Mark unwatched"
        DetailMark(item)
    else if label = "Shuffle series"
        ShuffleBegin("series",item.itemId)
    else if label = "Shuffle season"
        season = m.detailSeasons[m.pillGroups.seasons.index]
        ShuffleBegin("season",TextOr(season.itemId))
    else if label = "Version"
        DetailVersionPicker()
    else if label = "Audio"
        DetailAudioPicker()
    end if
end sub

function DetailKey(key as String) as Boolean
    if key = "options"
        if m.zone = "episodes" then DetailEpisodeOpen() else BrowseSocial(m.detailItem)
        return true
    end if
    if key = "OK" and m.detailOpeningSelect = true then return true
    if m.zone = "detailCast"
        if key = "OK"
            focused = m.detailCast.rowItemFocused
            if focused <> invalid and focused[1] < m.detailCastPeople.Count() then BrowsePerson(m.detailCastPeople[focused[1]].personId)
            return true
        end if
        if key = "up"
            if m.detailEpisodes.Count() > 0 then SetZone("episodes") else SetZone("detailButtons")
            DetailScroll()
            return true
        end if
        if key = "down" and m.detailSimilarItems.Count() > 0 then SetZone("detailSimilar") : DetailScroll() : return true
        return false
    end if
    if m.zone = "detailSimilar"
        if key = "up"
            if m.detailCastCount > 0 then SetZone("detailCast") else SetZone("detailButtons")
            DetailScroll()
            return true
        end if
        return false
    end if
    if m.zone = "detailButtons"
        if key = "left" then PillMove("detailButtons", -1) : return true
        if key = "right" then PillMove("detailButtons", 1) : return true
        if key = "up" then SetZone("nav") : return true
        if key = "OK" then DetailAction(m.pillGroups.detailButtons.index) : return true
        if key = "play" then DetailAction(0) : return true
        if key = "down"
            if m.pillGroups.seasons <> invalid
                SetZone("seasons")
            else if m.detailEpisodes.Count() > 0
                SetZone("episodes") : onEpisodeFocus()
            else if m.detailCastCount > 0
                SetZone("detailCast")
            else if m.detailSimilarItems.Count() > 0
                SetZone("detailSimilar")
            end if
            DetailScroll()
            return true
        end if
        return true
    end if
    if m.zone = "seasons"
        if key = "left" or key = "right"
            delta = 1
            if key = "left" then delta = -1
            if PillMove("seasons", delta) then DetailLoadSeason(m.pillGroups.seasons.index)
            DetailRevealSeason()
            return true
        end if
        if key = "up" then SetZone("detailButtons") : DetailScroll() : return true
        if key = "down" and m.detailEpisodes.Count() > 0 then SetZone("episodes") : onEpisodeFocus() : DetailScroll() : return true
        return true
    end if
    if m.zone = "episodes"
        if key = "down"
            if m.detailCastCount > 0 then SetZone("detailCast") else if m.detailSimilarItems.Count() > 0 then SetZone("detailSimilar")
            DetailScroll()
            return true
        end if
        if key = "up"
            if m.pillGroups.seasons <> invalid then SetZone("seasons") else SetZone("detailButtons")
            DetailScroll()
            return true
        end if
        if key = "play"
            ep = DetailFocusedEpisode()
            if ep <> invalid then PlayItem(ep, NumberOr(ep.resumeMs, 0))
            return true
        end if
    end if
    return false
end function

sub DetailMark(item as Object)
    if m.detailMarkPending = true then return
    watched = item.watched <> true
    action = "mark_watched"
    if not watched then action = "mark_unwatched"
    if m.provider = "plex"
        action = "scrobble"
        if not watched then action = "unscrobble"
    end if
    m.detailMarkPending = true
    Api(action, {itemId: item.itemId}, "detail_mark", {visit: m.detailToken, item: item, watched: watched})
end sub

sub DetailVersionPicker()
    PlayerDiscardPrebuffer()
    dialog = CreateObject("roSGNode", "Dialog")
    dialog.title = "Version"
    dialog.message = "Auto may use another file. Selecting a version keeps that file."
    labels = SiloUIDetailVersionLabels(m.detailVersions,TextOr(m.detailSelectedVersion))
    labels.Push("Cancel")
    dialog.buttons = labels
    m.detailVersionVisit = m.detailToken
    m.detailVersionDialog = dialog
    dialog.observeField("buttonSelected", "onDetailVersion")
    m.top.dialog = dialog
end sub

sub onDetailVersion()
    dialog = m.detailVersionDialog
    if dialog = invalid then return
    index = dialog.buttonSelected
    dialog.close = true
    if m.view <> "detail" or m.detailVersionVisit <> m.detailToken or index > m.detailVersions.Count() then return
    if index < 0 then return
    m.detailSelectedVersion = ""
    if index > 0 then m.detailSelectedVersion = TextOr(m.detailVersions[index-1].versionId)
    m.detailAudioChoice = invalid
    m.detailAudioTicket = invalid
    DetailRender(m.detailItem)
    DetailExperimentalProbe()
    if index = 0 then Toast("Using automatic version selection.") else Toast("Version selected.")
end sub

sub DetailAudioPicker()
    if m.view <> "detail" then return
    choices = SiloUIDetailAudioChoices(m.provider,m.detailItem,m.detailVersions,TextOr(m.detailSelectedVersion))
    if choices.Count() < 2 then Toast("Select a version with multiple audio tracks first.") : return
    dialog = CreateObject("roSGNode", "Dialog")
    dialog.title = "Audio"
    labels = ["Server default"]
    for each choice in choices
        labels.Push(choice.label)
    end for
    labels.Push("Cancel")
    dialog.buttons = labels
    ticket = BrowseEventTicket(dialog,"detail_audio")
    ticket.choices = choices
    m.detailAudioTicket = ticket
    dialog.observeField("buttonSelected","onDetailAudio")
    m.top.dialog = dialog
end sub

sub onDetailAudio(event as Object)
    ticket = m.detailAudioTicket
    if not BrowseTakeEventTicket(ticket,event) then return
    index = ticket.node.buttonSelected
    ticket.node.close = true
    if index < 0 or index > ticket.choices.Count() then return
    if index = 0
        m.detailAudioChoice = invalid
        DetailExperimentalProbe()
        Toast("Using server default audio.")
        return
    end if
    choice = ticket.choices[index-1]
    current = SiloUIDetailAudioChoices(m.provider,m.detailItem,m.detailVersions,TextOr(m.detailSelectedVersion))
    if current.Count() < 2 then Toast("Version changed. Choose audio again.") : return
    fresh = SiloUIDetailAudioMatch(choice,TextOr(m.detailItem.itemId),current[0].fileId,m.detailVersions)
    if fresh = invalid then Toast("Audio selection changed. Choose audio again.") : return
    fresh.visit = m.detailToken
    fresh.sourceId = m.sourceId
    fresh.profileId = m.profileId
    fresh.generation = m.generation
    m.detailAudioChoice = fresh
    DetailExperimentalProbe()
    PlayerDiscardPrebuffer()
    Toast("Audio: " + fresh.label)
end sub

sub onDetailSimilarSelect()
    if m.view <> "detail" or m.zone <> "detailSimilar" then return
    focus = m.detailSimilar.rowItemSelected
    if focus <> invalid and focus[1] < m.detailSimilarItems.Count() then DetailOpen(m.detailSimilarItems[focus[1]])
end sub

' One worker drains a finite eight-person queue. Poster references are cleared
' before deleting Scene-owned files; cancelled workers retain their observer.
sub DetailPhotosClear()
    m.detailPhotoQueue = []
    if m.detailPhotoTask <> invalid then m.detailPhotoTask.cancelled = true
    if m.detailCast <> invalid and m.detailCast.content <> invalid
        row = m.detailCast.content.getChild(0)
        if row <> invalid
            for i = 0 to row.getChildCount() - 1
                node = row.getChild(i)
                uri = node.photoUri
                node.photoUri = ""
                DetailPhotoDelete(uri)
            end for
        end if
    end if
    DetailPhotoNext()
end sub

sub DetailPhotosStart()
    m.detailPhotoQueue = []
    if m.view <> "detail" or m.provider <> "silo" or m.memoryHigh = true then return
    if m.detailCast.content = invalid then return
    row = m.detailCast.content.getChild(0)
    if row = invalid then return
    for i = 0 to row.getChildCount() - 1
        node = row.getChild(i)
        if node.photoUri = "" and CreateObject("roRegex", "^[A-Za-z0-9_.:-]{1,128}$", "").IsMatch(node.personId)
            m.detailPhotoQueue.Push({index:i,personId:node.personId})
        end if
    end for
    DetailPhotoNext()
end sub

sub DetailPhotoNext()
    if m.detailPhotoTask <> invalid or m.detailPhotoQueue = invalid then return
    cleanup = []
    if m.detailPhotoDeletes <> invalid
        while m.detailPhotoDeletes.Count() > 0 and cleanup.Count() < 8
            cleanup.Push(m.detailPhotoDeletes.Shift())
        end while
    end if
    if cleanup.Count() = 0
        if m.detailPhotoQueue.Count() = 0 or m.view <> "detail" or m.memoryHigh = true then return
    end if
    task = CreateObject("roSGNode", "PersonPhotoTask")
    task.observeField("result", "onDetailPhoto")
    if cleanup.Count() > 0
        task.job = {}
        task.cleanupPaths = cleanup
    else
        entry = m.detailPhotoQueue.Shift()
        m.requestId = m.requestId + 1
        task.job = {sourceId:m.sourceId,profileId:m.profileId,generation:m.generation,visit:m.detailVisit,itemId:m.detailItem.itemId,personId:entry.personId,index:entry.index,requestId:m.requestId}
    end if
    m.detailPhotoTask = task
    task.control = "run"
end sub

sub onDetailPhoto(event as Object)
    task = event.getRoSGNode()
    result = event.getData()
    owner = result.owner
    current = task.cancelled <> true and m.view = "detail" and m.detailItem <> invalid
    if current
        current = owner.sourceId = m.sourceId and owner.profileId = m.profileId and owner.generation = m.generation and owner.visit = m.detailVisit and owner.itemId = m.detailItem.itemId
    end if
    attached = false
    if current and m.detailCast.content <> invalid
        row = m.detailCast.content.getChild(0)
        if row <> invalid
            node = row.getChild(owner.index)
            if node <> invalid and node.personId = owner.personId and result.sessionRevision = DetailPhotoSessionRevision()
                node.photoUri = result.uri
                attached = true
            end if
        end if
    end if
    if not attached then DetailPhotoDelete(result.uri)
    task.unobserveField("result")
    m.detailPhotoTask = invalid
    DetailPhotoNext()
end sub

sub DetailPhotoDelete(uri as String)
    if not CreateObject("roRegex", "^tmp:/personphoto-[0-9]+-[0-9]+[.](jpg|png|webp)$", "").IsMatch(uri) then return
    if m.detailPhotoDeletes = invalid then m.detailPhotoDeletes = []
    for each queued in m.detailPhotoDeletes
        if queued = uri then return
    end for
    ' At most eight displayed files plus the single retiring photo worker.
    if m.detailPhotoDeletes.Count() < 9 then m.detailPhotoDeletes.Push(uri)
end sub

' Read only the compact revision; credentials never enter the render thread.
function DetailPhotoSessionRevision() as Integer
    try
        section = AppRegistrySection("silo")
        if section = invalid then return -1
        if not section.Exists("revision") then return 0
        return Val(section.Read("revision"))
    catch exception
        return -1
    end try
end function

sub onDetailCastSelect()
    if m.view <> "detail" or m.zone <> "detailCast" then return
    focused = m.detailCast.rowItemSelected
    if focused <> invalid and focused[1] < m.detailCastPeople.Count() then BrowsePerson(m.detailCastPeople[focused[1]].personId)
end sub

' Async device proof is scoped to this exact detail visit and captured audio.
function DetailExperimentalCurrent(ticket as Dynamic) as Boolean
    if type(ticket) <> "roAssociativeArray" then return false
    if ticket.scope = "episode"
        if not DetailEpisodeCurrent() then return false
        state = m.detailEpisode
        if state.experimentalTicket = invalid then return false
        if ticket.probe <> state.experimentalTicket.probe then return false
        if ticket.kind <> "experimental_original" or ticket.visit <> m.detailToken or ticket.sourceId <> m.sourceId or ticket.profileId <> m.profileId or ticket.generation <> m.generation then return false
        if ticket.itemId <> state.item.itemId or ticket.audioSignature <> FormatJson(state.audio) then return false
        return ticket.fileId = SiloUIDetailExperimentalVersion(m.provider,state.item,state.versions,TextOr(state.selected))
    end if
    if m.detailExperimentalTicket = invalid then return false
    if m.view <> "detail" or m.provider <> "silo" or m.detailItem = invalid then return false
    if ticket.kind <> "experimental_original" or ticket.probe <> m.detailExperimentalTicket.probe then return false
    if ticket.visit <> m.detailToken or ticket.sourceId <> m.sourceId or ticket.profileId <> m.profileId or ticket.generation <> m.generation then return false
    if ticket.itemId <> m.detailItem.itemId or ticket.audioSignature <> FormatJson(m.detailAudioChoice) then return false
    fileId = SiloUIDetailExperimentalVersion(m.provider,m.detailItem,m.detailVersions,TextOr(m.detailSelectedVersion))
    return fileId <> "" and ticket.fileId = fileId
end function

sub DetailExperimentalRender()
    index = 0
    if type(m.pillGroups) = "roAssociativeArray"
        if m.pillGroups.detailButtons <> invalid then index = m.pillGroups.detailButtons.index
    end if
    DetailRender(m.detailItem)
    if type(m.pillGroups) <> "roAssociativeArray" then return
    if m.pillGroups.detailButtons <> invalid and type(m.detailActions) = "roArray"
        if index >= m.detailActions.Count() then index = m.detailActions.Count()-1
        if index < 0 then index = 0
        m.pillGroups.detailButtons.index = index
        PaintButtons("detailButtons",m.zone = "detailButtons")
    end if
end sub

sub DetailExperimentalProbe(episode = false as Boolean)
    if episode
        state = m.detailEpisode
        state.experimentalAvailable = false
        state.experimentalTicket = invalid
        if not DetailEpisodeCurrent() then return
        DetailExperimentalRequest(state.item,state.versions,state.selected,state.audio,state.detail,true)
        return
    end if
    m.detail4KPendingPlay = invalid
    m.detailExperimentalPending = false
    wasAvailable = m.detailExperimentalAvailable = true
    m.detailExperimentalAvailable = false
    m.detailExperimentalTicket = invalid
    if m.view <> "detail" or m.detailItem = invalid then return
    fileId = SiloUIDetailExperimentalVersion(m.provider,m.detailItem,m.detailVersions,TextOr(m.detailSelectedVersion))
    if wasAvailable then DetailExperimentalRender()
    if fileId = "" or type(m.detailExperimentalDetail) <> "roAssociativeArray" then return
    DetailExperimentalRequest(m.detailItem,m.detailVersions,TextOr(m.detailSelectedVersion),m.detailAudioChoice,m.detailExperimentalDetail,false)
end sub

sub DetailExperimentalRequest(item as Object, versions as Object, selected as String, audioChoice as Dynamic, detail as Dynamic, episode as Boolean)
    fileId = SiloUIDetailExperimentalVersion(m.provider,item,versions,selected)
    if fileId = "" or type(detail) <> "roAssociativeArray" then return
    params = {itemId:item.itemId,fileId:fileId,detail:detail}
    if audioChoice <> invalid
        if audioChoice.visit <> m.detailToken or audioChoice.sourceId <> m.sourceId or audioChoice.profileId <> m.profileId or audioChoice.generation <> m.generation then return
        audio = SiloUIDetailAudioMatch(audioChoice,item.itemId,fileId,versions)
        if audio = invalid then return
        params.audioTrackIndex = audio.sourceOrdinal
        params.audioTrackId = "file:"+fileId+":audio:"+audio.sourceOrdinal.ToStr()
    end if
    m.detailExperimentalProbeId = NumberOr(m.detailExperimentalProbeId,0)+1
    ticket = {kind:"experimental_original",visit:m.detailToken,sourceId:m.sourceId,profileId:m.profileId,generation:m.generation,itemId:item.itemId,fileId:fileId,audioSignature:FormatJson(audioChoice),probe:m.detailExperimentalProbeId}
    if episode
        ticket.scope = "episode"
        m.detailEpisode.experimentalTicket = ticket
    else
        m.detailExperimentalTicket = ticket
        m.detailExperimentalPending = true
    end if
    Api("experimental_playback_probe",params,"detail_experimental_probe",ticket)
end sub

' An explicit choice applies only to this captured playback attempt. Settings
' remain untouched; the existing fresh ticket fences file/audio/visit identity.
function Detail4KSubtitleConsent(startMs as Double) as Boolean
    if not DetailExperimentalCurrent(m.detailExperimentalTicket) then return false
    if type(m.preferences) <> "roAssociativeArray" then return false
    if m.preferences.subtitles = invalid or m.preferences.subtitles = "off" then return false
    if m.detailExperimentalAvailable <> true and m.detailExperimentalPending <> true then return false
    if type(m.detail4KPendingPlay) = "roAssociativeArray"
        if BrowseContextCurrent(m.detail4KPendingPlay.context) then return true
    end if
    if type(m.browseDialogTicket) = "roAssociativeArray"
        if m.browseDialogTicket.handler = "onDetail4KConsent" and m.browseDialogTicket.used <> true
            if BrowseContextCurrent(m.browseDialogTicket.context) and m.top.dialog <> invalid
                if m.browseDialogTicket.node.isSameNode(m.top.dialog) then return true
            end if
        end if
    end if
    captured = {ticket:m.detailExperimentalTicket,startMs:startMs,selectedVersion:TextOr(m.detailSelectedVersion),audio:m.detailAudioChoice,context:BrowseCaptureContext()}
    if m.detailExperimentalPending = true
        ' The existing API task timeout/error result releases this one-shot intent.
        m.detail4KPendingPlay = captured
        return true
    end if
    BrowseDialog("4K playback · HDR fallback may apply",["Play 4K without subtitles","Keep subtitle preference","Cancel"],"onDetail4KConsent")
    m.browseDialogTicket.playback = captured
    return true
end function

sub onDetail4KConsent(event as Object)
    dialogTicket = BrowseTakeDialog(event,"onDetail4KConsent")
    if dialogTicket = invalid then return
    index = dialogTicket.node.buttonSelected
    dialogTicket.node.close = true
    captured = dialogTicket.playback
    if type(captured) <> "roAssociativeArray" then return
    if m.detailExperimentalAvailable <> true or not DetailExperimentalCurrent(captured.ticket) then return
    if captured.selectedVersion <> TextOr(m.detailSelectedVersion) then return
    if index = 0
        PlayItem(m.detailItem,captured.startMs,captured.ticket.fileId,captured.audio,captured.ticket)
    else if index = 1
        PlayItem(m.detailItem,captured.startMs,captured.selectedVersion,captured.audio)
    end if
end sub

sub DetailEpisodeOpen()
    ep = DetailFocusedEpisode()
    if ep = invalid then return
    m.detailEpisode = {active:true,context:BrowseCaptureContext(),season:m.detailSeasonRequest,item:ep,versions:[],selected:"",audio:invalid,loading:true}
    DetailEpisodeShow("Loading episode",["Cancel"],"loading")
    Api("detail",{itemId:ep.itemId},"detail_episode_actions",m.detailEpisode.ticket)
end sub

function DetailEpisodeCurrent() as Boolean
    state = m.detailEpisode
    if state = invalid or state.active <> true then return false
    if not BrowseContextCurrent(state.context) or m.view <> "detail" or m.zone <> "episodes" then return false
    if state.season <> m.detailSeasonRequest then return false
    ep = DetailFocusedEpisode()
    return ep <> invalid and TextOr(ep.itemId) = TextOr(state.item.itemId)
end function

sub DetailEpisodeShow(title as String, labels as Object, mode as String)
    dialog = CreateObject("roSGNode","Dialog")
    dialog.title = title
    dialog.buttons = labels
    dialog.observeField("buttonSelected","onDetailEpisodeAction")
    dialog.observeField("wasClosed","onDetailEpisodeClosed")
    ticket = BrowseEventTicket(dialog,"episode_actions")
    ticket.mode = mode
    ticket.labels = labels
    m.detailEpisode.ticket = ticket
    m.top.dialog = dialog
end sub

sub DetailEpisodeMenu()
    state = m.detailEpisode
    labels = SiloUIEpisodeActionLabels(m.provider,state.item,state.versions,state.selected)
    if state.experimentalAvailable = true and DetailExperimentalCurrent(state.experimentalTicket)
        labels.Pop()
        labels.Push("Experimental Play")
        labels.Push("Cancel")
    end if
    DetailEpisodeShow(TextOr(state.item.title),labels,"actions")
end sub

sub DetailEpisodeResult(result as Object, data as Object, ticket as Dynamic)
    if not DetailEpisodeCurrent() then return
    state = m.detailEpisode
    if state.loading <> true or ticket = invalid then return
    if not ticket.node.isSameNode(state.ticket.node) or ticket.used = true then return
    if m.top.dialog = invalid then state.active = false : return
    if not ticket.node.isSameNode(m.top.dialog) then state.active = false : return
    state.loading = false
    ticket.used = true
    ticket.node.close = true
    if result.ok = true and type(data.item) = "roAssociativeArray"
        if TextOr(data.item.itemId) = TextOr(state.item.itemId) and TextOr(data.item.sourceId) = TextOr(state.item.sourceId) and TextOr(data.item.sourceId) = m.sourceId
            state.detail = data
            state.item = data.item
            if type(data.versions) = "roArray" then state.versions = data.versions
        else
            state.active = false
            Toast("Episode changed. Open its options again.")
            return
        end if
    else
        Toast("Version and audio information is unavailable.")
    end if
    DetailEpisodeMenu()
    DetailExperimentalProbe(true)
end sub

sub onDetailEpisodeClosed(event as Object)
    state = m.detailEpisode
    if state = invalid then return
    if not state.ticket.node.isSameNode(event.getRoSGNode()) then return
    if state.ticket.used <> true then state.active = false
end sub

sub onDetailEpisodeAction(event as Object)
    if not DetailEpisodeCurrent() then return
    state = m.detailEpisode
    ticket = state.ticket
    if not BrowseTakeEventTicket(ticket,event) then return
    index = ticket.node.buttonSelected
    ticket.node.close = true
    if index < 0 or index >= ticket.labels.Count() then state.active = false : return
    label = ticket.labels[index]
    if label = "Cancel" then state.active = false : return
    if ticket.mode = "version"
        state.selected = ""
        if index > 0 and index <= state.versions.Count() then state.selected = TextOr(state.versions[index-1].versionId)
        state.audio = invalid
        DetailExperimentalProbe(true)
        DetailEpisodeMenu()
    else if ticket.mode = "audio"
        state.audio = invalid
        if index > 0 and index <= ticket.choices.Count()
            choice = ticket.choices[index-1]
            fresh = SiloUIDetailAudioMatch(choice,TextOr(state.item.itemId),choice.fileId,state.versions)
            if fresh <> invalid
                fresh.visit = m.detailToken
                fresh.sourceId = m.sourceId
                fresh.profileId = m.profileId
                fresh.generation = m.generation
                state.audio = fresh
            end if
        end if
        DetailExperimentalProbe(true)
        DetailEpisodeMenu()
    else
        DetailEpisodeChoose(label)
    end if
end sub

sub DetailEpisodeChoose(label as String)
    state = m.detailEpisode
    if label = "Experimental Play"
        if state.experimentalAvailable <> true or not DetailExperimentalCurrent(state.experimentalTicket) then return
        Toast("Experimental 4K: HDR fallback, subtitles off.")
        PlayItem(state.item,SiloUIDetailResumeMs(state.item),state.experimentalTicket.fileId,state.audio,state.experimentalTicket)
        state.active = false
    else if label = "Version"
        labels = SiloUIDetailVersionLabels(state.versions,state.selected)
        labels.Push("Cancel")
        DetailEpisodeShow("Episode version",labels,"version")
    else if label = "Audio"
        choices = SiloUIDetailAudioChoices(m.provider,state.item,state.versions,state.selected)
        labels = ["Server default"]
        for each choice in choices
            labels.Push(choice.label)
        end for
        labels.Push("Cancel")
        DetailEpisodeShow("Episode audio",labels,"audio")
        state.ticket.choices = choices
    else if label = "Mark watched" or label = "Mark unwatched"
        DetailMark(state.item)
        state.active = false
    else if label = "Play" or Left(label,6) = "Resume" or label = "From beginning"
        startMs = SiloUIDetailResumeMs(state.item)
        if label = "From beginning" then startMs = 0
        PlayItem(state.item,startMs,state.selected,state.audio)
        state.active = false
    end if
end sub

function DetailPlaybackVersions(itemId as String) as Dynamic
    if DetailEpisodeCurrent()
        if TextOr(m.detailEpisode.item.itemId) = itemId then return m.detailEpisode.versions
    end if
    return m.detailVersions
end function

sub DetailSynopsisOpen(item as Object)
    if m.view <> "detail" or TextOr(item.summary).Trim() = "" then return
    m.detailSynopsis = {text:TextOr(item.summary),title:TextOr(item.title),starts:[1],page:0,zone:m.zone,context:BrowseCaptureContext()}
    DetailSynopsisRender()
end sub

sub DetailSynopsisRender()
    state = m.detailSynopsis
    if state = invalid or not BrowseContextCurrent(state.context) then return
    start = state.starts[state.page]
    finish = start
    newlines = 0
    while finish <= Len(state.text) and finish < start + 400
        if Mid(state.text,finish,1) = Chr(10) then newlines = newlines + 1
        finish = finish + 1
        if newlines >= 6 then exit while
    end while
    ' Keep pairs together when the runtime counts UTF-16 code units.
    if finish <= Len(state.text)
        code = Asc(Mid(state.text,finish,1))
        if code >= 56320 and code <= 57343 then finish = finish - 1
    end if
    state.nextStart = finish
    actions = []
    if state.page > 0 then actions.Push("Previous page")
    if finish <= Len(state.text) then actions.Push("Next page")
    actions.Push("Close")
    state.actions = actions
    BrowseDialog(state.title + " · Synopsis · Page " + (state.page+1).ToStr(),actions,"onDetailSynopsis")
    m.browseDialog.message = Mid(state.text,start,finish-start)
    m.browseDialog.observeField("wasClosed","onDetailSynopsisClosed")
end sub

sub onDetailSynopsis(event as Object)
    ticket = BrowseTakeDialog(event,"onDetailSynopsis")
    if ticket = invalid or m.detailSynopsis = invalid then return
    state = m.detailSynopsis
    index = ticket.node.buttonSelected
    if index < 0 or index >= state.actions.Count() then return
    action = state.actions[index]
    ticket.node.close = true
    if action = "Close"
        m.detailSynopsis = invalid
        SetZone(state.zone)
        return
    end if
    if action = "Previous page"
        state.page = state.page - 1
    else
        if state.starts.Count() = state.page+1 then state.starts.Push(state.nextStart)
        state.page = state.page+1
    end if
    DetailSynopsisRender()
end sub

sub onDetailSynopsisClosed(event as Object)
    ticket = m.browseDialogTicket
    if ticket = invalid or m.detailSynopsis = invalid then return
    if ticket.handler <> "onDetailSynopsis" or ticket.used = true then return
    if not BrowseContextCurrent(ticket.context) then return
    if not ticket.node.isSameNode(event.getRoSGNode()) then return
    if m.top.dialog <> invalid
        if not ticket.node.isSameNode(m.top.dialog) then return
    end if
    ticket.used = true
    zone = m.detailSynopsis.zone
    m.detailSynopsis = invalid
    SetZone(zone)
end sub
