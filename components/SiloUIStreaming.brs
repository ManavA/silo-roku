' Public catalogs use scoped native observations or authorized batch receipts.
' This is a partial view, never a complete inventory or subscription-availability claim.
function StreamingProviders() as Object
    return [{id:"netflix",title:"Netflix",slug:"netflix"},{id:"prime-video",title:"Prime Video",slug:"amazon"},{id:"hbo-max",title:"HBO Max",slug:"max"},{id:"disney-plus",title:"Disney+",slug:"disney"},{id:"hulu",title:"Hulu",slug:"hulu"},{id:"apple-tv-plus",title:"Apple TV+",slug:"apple-tv"},{id:"peacock",title:"Peacock",slug:"peacock"},{id:"paramount-plus",title:"Paramount+",slug:"paramount"},{id:"pluto-tv",title:"Pluto TV",slug:""},{id:"mubi",title:"Mubi",slug:""},{id:"shudder",title:"Shudder",slug:""},{id:"kanopy",title:"Kanopy",slug:""}]
end function

sub StreamingInit()
    m.streamingGrid = m.top.findNode("streamingGrid")
    m.streamingGrid.observeField("itemSelected","onStreamingSelect")
    m.streamingTitle = m.top.findNode("streamingTitle")
    m.streamingTitle.font = SiloUIFont(30,true)
    m.streamingStatus = m.top.findNode("streamingStatus")
    m.streamingStatus.font = SiloUIFont(18,false)
    m.streamingButtons = m.top.findNode("streamingButtons")
end sub

function StreamingScope() as Object
    return {provider:m.provider,sourceId:m.sourceId,profileId:m.profileId,generation:m.generation}
end function

function StreamingScopeKey() as String
    return FormatJson(StreamingScope())
end function

sub StreamingRememberRows(rows as Object)
    scope = StreamingScopeKey()
    if m.streamingIndexScope <> scope then m.streamingIndex = invalid
    m.streamingIndexScope = scope
    for each row in rows
        if row.sectionType <> "streaming" and row.sectionType <> "curated" and row.sectionType <> "formats" then m.streamingIndex = ServiceOwnedIndexAdd(m.streamingIndex,row.items,StreamingScope())
    end for
end sub

function StreamingHomeRows(rows as Object) as Object
    result = []
    for each row in rows
        if row.sectionType <> "streaming" and row.sectionType <> "curated" and row.sectionType <> "formats" then result.Push(row)
    end for
    items = []
    for each service in StreamingProviders()
        items.Push({title:service.title,type:"service",serviceId:service.id,canPlay:false})
    end for
    result.Push({title:"Streaming services",rowId:"home.streaming",sectionType:"streaming",items:items})
    result.Push({title:"Discover",rowId:"home.curated",sectionType:"curated",items:[{title:"Curated picks",type:"service",serviceId:"curated",canPlay:false}]})
    if m.provider = "silo"
        formats = [
            {title:"4K files",type:"format",formatFilter:"4k",canPlay:false},
            {title:"HDR files",type:"format",formatFilter:"hdr",canPlay:false},
            {title:"4K HDR",type:"format",formatFilter:"4k_hdr",canPlay:false},
            {title:"Dolby Vision",type:"format",formatFilter:"dv",canPlay:false}
        ]
        result.Push({title:"Formats in your library",rowId:"home.formats",sectionType:"formats",items:formats})
    end if
    return result
end function

sub StreamingOpen(id as String)
    selected = invalid
    if id = "curated"
        selected = {id:"curated",title:"Curated picks",slug:"home"}
    else
        for each service in StreamingProviders()
            if service.id = id then selected = service : exit for
        end for
    end if
    if selected = invalid then return
    if m.view = "home"
        m.streamingHomeFocus = m.rows.rowItemFocused
        m.history.Push({view:"home",zone:"rows"})
    end if
    m.streamingVisit = NumberOr(m.streamingVisit,0) + 1
    m.streamingOwner = StreamingScopeKey()
    StreamingIdentityInvalidate()
    m.streamingPublicGroups = []
    m.streamingService = selected
    m.streamingGroups = []
    m.streamingGroupIndex = 0
    m.streamingTitle.text = selected.title + " · In your library"
    m.streamingGrid.content = CreateObject("roSGNode","ContentNode")
    if id = "curated"
        BuildButtons(m.streamingButtons,"streamingButtons",["Previous list","Next list","Refresh","Search your source","Back"])
    else
        BuildButtons(m.streamingButtons,"streamingButtons",["Retry / Refresh","Search your source","Back"])
    end if
    ShowView("streaming")
    SetZone("streamingButtons")
    if selected.slug = ""
        m.streamingBusy = false
        m.streamingStatus.text = "This provider catalog is unavailable. Search your source instead."
        return
    end if
    m.streamingStatus.text = "Loading catalog… Partial matches from titles already browsed."
    StreamingRequest("cache_only")
end sub

function StreamingCurrent() as Boolean
    return m.view = "streaming" and m.streamingOwner = StreamingScopeKey()
end function

sub StreamingRequest(mode as String)
    if not StreamingCurrent() or m.streamingService.slug = "" then return
    m.streamingSerial = NumberOr(m.streamingSerial,0) + 1
    StreamingIdentityInvalidate()
    if mode = "refresh" and m.streamingCapability = false then m.streamingCapability = invalid
    m.streamingBusy = true
    action = "service_catalog"
    if m.streamingService.id = "curated" then action = "home_rows"
    Api(action,{slug:m.streamingService.slug,mode:mode},"streaming_catalog",{visit:m.streamingVisit,serial:m.streamingSerial,owner:m.streamingOwner,mode:mode})
end sub

function StreamingCuratedGroups(data as Object) as Object
    groups = []
    if type(data.rows) <> "roArray" then return groups
    inspected = 0
    for each row in data.rows
        inspected = inspected + 1
        if inspected > 12 then exit for
        if type(row) = "roAssociativeArray" and type(row.items) = "roArray"
            matched = ServiceOwnedEntries({rows:[row]},m.streamingIndex,StreamingScope(),24)
            if matched.items.Count() > 0
                title = TextOr(row.title)
                if title = "" then title = "Curated list"
                groups.Push({title:title,items:matched.items})
            end if
        end if
    end for
    return groups
end function

sub StreamingCuratedRender()
    content = CreateObject("roSGNode","ContentNode")
    m.streamingTitle.text = "Curated picks · In your library"
    if m.streamingGroups.Count() > 0
        if m.streamingGroupIndex >= m.streamingGroups.Count() then m.streamingGroupIndex = 0
        group = m.streamingGroups[m.streamingGroupIndex]
        m.streamingTitle.text = "Curated picks · " + group.title
        for each item in group.items
            node = ItemNode(item)
            poster = HmUiArtwork(item.thumbKey)
            if poster <> ""
                node.HDPosterUrl = poster
                node.artCandidates = [poster]
            end if
            content.appendChild(node)
        end for
    end if
    m.streamingGrid.content = content
end sub

sub StreamingCuratedMove(offset as Integer)
    if m.streamingService = invalid or m.streamingService.id <> "curated" then return
    if m.streamingGroups.Count() < 2 then return
    StreamingIdentityInvalidate()
    m.streamingGroupIndex = (m.streamingGroupIndex + offset + m.streamingGroups.Count()) mod m.streamingGroups.Count()
    StreamingCuratedRender()
    StreamingResolveWant()
end sub

sub StreamingResult(result as Object, data as Object, extra as Dynamic)
    if not StreamingCurrent() or type(extra) <> "roAssociativeArray" then return
    if extra.visit <> m.streamingVisit or extra.serial <> m.streamingSerial or extra.owner <> m.streamingOwner then return
    m.streamingBusy = false
    if result.ok = true and m.streamingService.id = "curated" and extra.mode = "refresh" and HmField(data, "refreshQueued") = true
        StreamingRequest("live")
        m.streamingStatus.text = "Catalog refresh requested in the background. Showing the current snapshot."
        return
    end if
    count = 0
    if result.ok = true
        StreamingIdentityInvalidate()
        m.streamingPublicGroups = StreamingPublicGroups(data)
        if m.streamingService.id = "curated"
            groups = StreamingCuratedGroups(data)
            if groups.Count() > 0 or extra.mode <> "cache_only"
                m.streamingGroups = groups
                m.streamingGroupIndex = 0
                StreamingCuratedRender()
            end if
            count = m.streamingGrid.content.getChildCount()
        else
            matched = ServiceOwnedEntries(data,m.streamingIndex,StreamingScope())
            content = CreateObject("roSGNode","ContentNode")
            for each item in matched.items
                node = ItemNode(item)
                poster = HmUiArtwork(item.thumbKey)
                if poster <> ""
                    node.HDPosterUrl = poster
                    node.artCandidates = [poster]
                end if
                content.appendChild(node)
            end for
            count = content.getChildCount()
            if count > 0 or extra.mode <> "cache_only" then m.streamingGrid.content = content
        end if
        m.streamingStatus.text = "Partial matches from titles already browsed; your full library has not been checked."
        if count = 0 then m.streamingStatus.text = "No matches among titles already browsed. Your full library has not been checked."
        if count > 0 and m.zone = "streamingButtons" then SetZone("streamingGrid")
        if count = 0 and m.zone = "streamingGrid" then SetZone("streamingButtons")
    else
        m.streamingStatus.text = "Catalog unavailable. Retry or search your source. Partial matches only."
    end if
    if extra.mode = "cache_only"
        StreamingRequest("live")
    else if result.ok = true
        StreamingResolveWant()
    end if
end sub

sub onStreamingSelect()
    if not StreamingCurrent() or m.streamingGrid.content = invalid then return
    index = m.streamingGrid.itemSelected
    if index < 0 or index >= m.streamingGrid.content.getChildCount() then return
    item = m.streamingGrid.content.getChild(index).item
    ' Check native identity again at the final detail boundary; never route a public seed.
    if HmUiOwnedCard(item,m.provider,m.sourceId) = invalid then return
    DetailOpen(item)
end sub

sub StreamingRestoreHome()
    if m.streamingHomeFocus <> invalid then m.rows.jumpToRowItem = m.streamingHomeFocus
    m.streamingHomeFocus = invalid
end sub

function StreamingKey(key as String) as Boolean
    if not StreamingCurrent() then return true
    if m.zone = "streamingGrid"
        if key = "up" then SetZone("streamingButtons") : return true
        return false
    end if
    if m.zone = "streamingButtons"
        if key = "left" then PillMove("streamingButtons",-1) : return true
        if key = "right" then PillMove("streamingButtons",1) : return true
        if key = "up" then SetZone("nav") : return true
        if key = "down" and m.streamingGrid.content.getChildCount() > 0 then SetZone("streamingGrid") : return true
        if key = "OK"
            index = m.pillGroups.streamingButtons.index
            if m.streamingService.id = "curated"
                if index = 0 then StreamingCuratedMove(-1) : return true
                if index = 1 then StreamingCuratedMove(1) : return true
                if index = 2 and m.streamingBusy <> true then StreamingRequest("refresh")
                if index = 3 then PushView("search","keyboard")
                if index = 4 then PopView()
                return true
            end if
            if index = 0 and m.streamingService.slug = "" then Toast("This provider has no catalog. Search your source instead.") : return true
            if index = 0 and m.streamingBusy <> true then StreamingRequest("refresh")
            if index = 1
                PushView("search","keyboard")
            end if
            if index = 2 then PopView()
            return true
        end if
        return true
    end if
    return false
end function

' A result arriving while Detail covered this hub was intentionally ignored.
' Retire that request so returning cannot leave Refresh blocked indefinitely.
sub StreamingResume()
    if not StreamingCurrent() then return
    m.streamingSerial = NumberOr(m.streamingSerial,0) + 1
    m.streamingBusy = false
    if m.streamingReload = true
        m.streamingReload = false
        m.streamingGrid.content = CreateObject("roSGNode","ContentNode")
        m.streamingGroups = []
        m.streamingGroupIndex = 0
        if m.streamingService.slug = ""
            m.streamingStatus.text = "This provider catalog is unavailable. Search your source instead."
            return
        end if
        if type(m.homeRows) = "roArray" then StreamingRememberRows(m.homeRows)
        m.streamingStatus.text = "Loading catalog… Partial matches from titles already browsed."
        StreamingRequest("cache_only")
    end if
end sub

' Hidden catalogs are disposable; scope changes also discard their route authority.
sub StreamingRetire(resetScope = false as Boolean)
    if not resetScope and m.view = "streaming" then return
    m.streamingSerial = NumberOr(m.streamingSerial,0) + 1
    m.streamingBusy = false
    StreamingIdentityInvalidate()
    m.streamingPublicGroups = []
    m.streamingIndex = invalid
    m.streamingIndexScope = invalid
    m.streamingGroups = []
    m.streamingGroupIndex = 0
    if m.streamingGrid <> invalid then m.streamingGrid.content = invalid
    m.streamingReload = m.streamingService <> invalid
    if resetScope
        m.streamingIdentityPending = invalid
        m.streamingCapabilityScope = invalid
        m.streamingCapability = invalid
        m.streamingOwner = invalid
        m.streamingService = invalid
        m.streamingHomeFocus = invalid
        m.streamingReload = false
    end if
end sub

' Seeds remain separate from source-native cards, including cards without external IDs.
sub StreamingIdentityInvalidate()
    m.streamingLookupSerial = NumberOr(m.streamingLookupSerial,0)+1
    m.streamingLookup = invalid
    m.streamingLookupWanted = invalid
end sub

function StreamingPublicGroups(data as Object) as Object
    groups = []
    if m.streamingService.id = "curated"
        if type(data.rows) <> "roArray" then return groups
        for each row in data.rows
            if groups.Count() >= 12 then exit for
            entries = UiMetadataEntries({rows:[row]},24)
            if entries.Count()>0 then groups.Push({title:TextOr(row.title),entries:entries,items:ServiceOwnedEntries({rows:[row]},m.streamingIndex,StreamingScope(),24).items})
        end for
    else
        entries = UiMetadataEntries(data,48)
        if entries.Count()>0 then groups.Push({title:m.streamingService.title,entries:entries,items:ServiceOwnedEntries(data,m.streamingIndex,StreamingScope()).items})
    end if
    return groups
end function

sub StreamingResolveWant()
    m.streamingLookupWanted = {visit:m.streamingVisit,serial:m.streamingSerial,owner:m.streamingOwner,lookup:m.streamingLookupSerial}
    StreamingResolveStart()
end sub

sub StreamingResolveStart()
    wanted = m.streamingLookupWanted
    if type(wanted) <> "roAssociativeArray" then return
    if wanted.visit <> m.streamingVisit or wanted.serial <> m.streamingSerial or wanted.owner <> m.streamingOwner or wanted.lookup <> m.streamingLookupSerial then return
    if not StreamingCurrent() or m.provider <> "silo" or m.streamingBusy = true then return
    if m.streamingIdentityPending <> invalid then return
    scope = StreamingScopeKey()
    if m.streamingCapabilityScope <> scope
        m.streamingCapabilityScope = scope
        m.streamingCapability = invalid
    end if
    if m.streamingCapability = invalid
        StreamingIdentityRequest("catalog_identity_capabilities",{})
        return
    end if
    if m.streamingCapability <> true then return
    if type(m.streamingPublicGroups) <> "roArray" or m.streamingPublicGroups.Count()=0 then return
    m.streamingGroups = m.streamingPublicGroups
    if m.streamingGroupIndex >= m.streamingGroups.Count() then m.streamingGroupIndex=0
    group = m.streamingGroups[m.streamingGroupIndex]
    if group.lookupDone = true then return
    seeds = []
    for each entry in group.entries
        if seeds.Count() >= m.streamingIdentityMax then exit for
        kind = entry.type
        if kind = "show" then kind = "series"
        seed = {type:kind}
        for each pair in [["tmdbId","tmdb_id"],["imdbId","imdb_id"],["tvdbId","tvdb_id"]]
            if entry[pair[0]] <> "" then seed[pair[1]] = entry[pair[0]]
        end for
        if seed.Count()>1 then seeds.Push(seed)
    end for
    if seeds.Count()=0 then group.lookupDone=true : return
    m.streamingLookup = {seeds:seeds,limit:100,pages:0,seen:{},ids:{},group:m.streamingGroupIndex,partial:group.entries.Count()>seeds.Count()}
    for each item in group.items
        m.streamingLookup.ids[item.itemId]=true
    end for
    StreamingIdentityRender()
    StreamingIdentityRequest("catalog_resolve",{seeds:seeds,limit:100})
end sub

sub StreamingIdentityRequest(action as String, params as Object)
    token = NumberOr(m.streamingIdentityToken,0)+1
    m.streamingIdentityToken = token
    extra = {action:action,token:token,visit:m.streamingVisit,serial:m.streamingSerial,owner:m.streamingOwner,lookup:m.streamingLookupSerial}
    m.streamingIdentityPending = extra
    Api(action,params,"streaming_identity",extra)
end sub

sub StreamingIdentityRender()
    focus = m.streamingGrid.itemFocused
    if m.streamingService.id = "curated"
        StreamingCuratedRender()
    else
        content = CreateObject("roSGNode","ContentNode")
        for each item in m.streamingGroups[0].items
            content.appendChild(ItemNode(item))
        end for
        m.streamingGrid.content = content
    end if
    if focus <> invalid and focus >= 0 and focus < m.streamingGrid.content.getChildCount() then m.streamingGrid.jumpToItem=focus
end sub

sub StreamingIdentityResult(result as Object, data as Object, extra as Dynamic)
    if type(extra) <> "roAssociativeArray" then return
    pending = m.streamingIdentityPending
    if type(pending) <> "roAssociativeArray" then return
    if pending.token <> extra.token then return
    m.streamingIdentityPending = invalid
    if not StreamingCurrent() then return
    if extra.visit <> m.streamingVisit or extra.owner <> m.streamingOwner
        StreamingResolveStart()
        return
    end if
    if extra.serial <> m.streamingSerial or extra.lookup <> m.streamingLookupSerial
        StreamingResolveStart()
        return
    end if
    if extra.action = "catalog_identity_capabilities"
        maximum = HmNumber(HmField(data,"maxIdentityBatch"),0)
        m.streamingCapability = result.ok=true and data.identityResolution=true and maximum>0 and maximum=Int(maximum)
        if maximum>48 then maximum=48
        m.streamingIdentityMax = maximum
        StreamingResolveStart()
        return
    end if
    lookup = m.streamingLookup
    if lookup = invalid then return
    group = m.streamingGroups[lookup.group]
    group.lookupDone = true
    m.streamingStatus.text = "Partial matches. Source lookup unavailable; your full library has not been checked."
    if result.ok <> true then return
    lookup.pages = lookup.pages+1
    if type(data.matches) <> "roArray" then return
    for each match in data.matches
        index = match.seed
        if type(index) <> "Integer" and type(index) <> "roInt" then return
        if index<0 or index>=lookup.seeds.Count() then return
        card = HmUiOwnedCard(match.item,m.provider,m.sourceId)
        if card = invalid then return
        kind = card.type
        if kind = "show" then kind = "series"
        if kind <> lookup.seeds[index].type then return
    end for
    for each match in data.matches
        item = match.item
        if not lookup.ids.DoesExist(item.itemId) and group.items.Count()<100
            lookup.ids[item.itemId]=true
            ' The scoped receipt is authority; public IDs never become native identity.
            item.catalogReceipt = {seed:match.seed,lookup:m.streamingLookupSerial,owner:m.streamingOwner}
            group.items.Push(item)
        end if
    end for
    StreamingIdentityRender()
    m.streamingStatus.text = "Partial matches. Search your library for more titles."
    if lookup.partial then m.streamingStatus.text = "Partial matches. Not all titles in the selected catalog were checked."
    cursor = HmText(HmField(data,"nextCursor"),8192)
    if data.complete <> true and cursor <> "" and lookup.pages<3 and group.items.Count()<100 and not lookup.seen.DoesExist(cursor)
        lookup.seen[cursor]=true
        group.lookupDone = false
        StreamingIdentityRequest("catalog_resolve",{seeds:lookup.seeds,limit:100,cursor:cursor})
    end if
end sub
