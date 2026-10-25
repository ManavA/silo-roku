' Library grid (Movies / Shows) with sort pills and cursor paging, plus Search.

sub LibraryInit()
    m.grid = m.top.findNode("grid")
    m.grid.observeField("itemSelected", "onGridSelect")
    m.grid.observeField("itemFocused", "onGridFocus")
    m.libraryTitle = m.top.findNode("libraryTitle")
    m.libraryTitle.font = SiloUIFont(30, true)
    m.libraryTabs = m.top.findNode("libraryTabs")
    m.libraryEmpty = m.top.findNode("libraryEmpty")
    m.libraryEmpty.font = SiloUIFont(20, false)
    LibraryBuildSorts()
    m.libraryType = ""
    m.libraryToken = 0
end sub

sub LibraryBuildSorts()
    m.librarySorts = [{label: "Recently added", sort: "added_at", order: "desc"}, {label: "A–Z", sort: "title", order: "asc"}, {label: "Newest", sort: "release_date", order: "desc"}]
    if m.provider = "silo" then m.librarySorts.Push({label:"Top rated",sort:"rating_imdb",order:"desc"})
    labels = []
    for each s in m.librarySorts
        labels.Push(s.label)
    end for
    BuildPills(m.libraryTabs, "libraryTabs", labels, 10, 36, 16)
    m.librarySortProvider = m.provider
end sub

sub LibraryOpen(kind as String, formatFilter = "" as String)
    if m.libraryReload <> true or m.libraryType <> kind then LibraryResetFilters()
    m.libraryReload = false
    m.libraryType = kind
    if formatFilter <> ""
        m.libraryFormatFilter = formatFilter
        m.libraryFormatTitle = LibraryFormatTitle(formatFilter)
    end if
    m.libraryTitle.text = LibraryTitleText(kind, m.libraryCollectionTitle, m.libraryFormatTitle)
    ShowView("library")
    LibraryQuery(true)
    SetZone("libraryTabs")
end sub

sub LibraryOpenFormat(formatFilter as String)
    if m.provider <> "silo" or LibraryFormatTitle(formatFilter) = "" then return
    if m.view = "home"
        m.streamingHomeFocus = m.rows.rowItemFocused
        m.history.Push({view:"home",zone:"rows"})
    end if
    LibraryOpen("video", formatFilter)
end sub

sub LibraryQuery(reset as Boolean)
    if m.librarySortProvider <> m.provider then LibraryBuildSorts()
    if m.libraryPerson = invalid or m.libraryPerson = "" then m.libraryTitle.text = LibraryTitleText(m.libraryType, m.libraryCollectionTitle, m.libraryFormatTitle)
    m.libraryError = false
    if m.libraryRetryButtons <> invalid then m.libraryRetryButtons.visible = false
    if reset
        m.libraryToken = m.libraryToken + 1
        m.libraryHasNext = false
        m.libraryPages = 0
        m.libraryCursor = ""
        m.libraryMore = false
        m.libraryLoadedScope = invalid
        m.grid.content = CreateObject("roSGNode", "ContentNode")
        m.libraryEmpty.text = "Loading…"
    end if
    if m.provider = "plex"
        if reset
            Api("sections", {}, "lib_sections", m.libraryToken)
        else
            LibraryPlexPage()
        end if
        return
    end if
    sort = m.librarySorts[m.pillGroups.libraryTabs.index]
    params = {type: m.libraryType, sort: sort.sort, order: sort.order, limit: 60, libraryId:m.libraryId, source:m.librarySource, collectionId:m.libraryCollection, genre:m.libraryGenre, watched:m.libraryWatched, namePrefix:m.libraryPrefix, formatFilter:m.libraryFormatFilter}
    if m.libraryDecade <> invalid and m.libraryDecade > 0 then params.decade = m.libraryDecade
    if m.libraryMinimumRating <> invalid and m.libraryMinimumRating > 0 then params.minimumRating = m.libraryMinimumRating
    if m.libraryPerson = invalid or m.libraryPerson = ""
        if params.DoesExist("decade") or params.DoesExist("minimumRating") or TextOr(m.libraryGenre) <> ""
            hint = Instr(1,m.libraryTitle.text," • Options:")
            if hint > 0 then m.libraryTitle.text = Left(m.libraryTitle.text,hint - 1)
        end if
        if TextOr(m.libraryGenre) <> "" then m.libraryTitle.text = m.libraryTitle.text + " • " + m.libraryGenre
        if params.DoesExist("decade") then m.libraryTitle.text = m.libraryTitle.text + " • " + params.decade.ToStr() + "s"
        if params.DoesExist("minimumRating") then m.libraryTitle.text = m.libraryTitle.text + " • IMDb " + params.minimumRating.ToStr() + "+"
    end if
    action = "catalog_query"
    if m.libraryPerson <> "" then action = "person_items" : params.personId = m.libraryPerson
    if m.libraryCursor <> "" then params.cursor = m.libraryCursor
    m.libraryRequestedCursor = m.libraryCursor
    m.libraryLoading = true
    Api(action, params, "lib_page", m.libraryToken)
end sub

function LibraryFormatTitle(formatFilter as String) as String
    if formatFilter = "4k" then return "4K files"
    if formatFilter = "hdr" then return "HDR files"
    if formatFilter = "4k_hdr" then return "4K HDR files"
    if formatFilter = "dv" then return "Dolby Vision files"
    return ""
end function

function LibraryTitleText(kind as String, collectionTitle as Dynamic, formatTitle = invalid as Dynamic) as String
    title = "Movies"
    if kind = "series" then title = "Shows"
    if kind = "video" then title = "Videos"
    if type(collectionTitle) = "String" or type(collectionTitle) = "roString"
        if collectionTitle <> "" then return title + " • " + Left(collectionTitle, 70)
    end if
    if type(formatTitle) = "String" or type(formatTitle) = "roString"
        if formatTitle <> "" then return title + " • " + formatTitle
    end if
    return title + " • Options: filters and lists"
end function

sub LibraryResult(purpose as String, result as Object, data as Object, extra as Dynamic)
    if purpose = "lib_genres" then LibraryGenresResult(result,data,extra) : return
    if extra <> m.libraryToken then return
    if purpose = "lib_choices" or purpose = "lib_collections" or purpose = "lib_server_collections"
        if not BrowseContextCurrent(m.libraryChoiceContext) then return
        if m.view <> "library" then return
        if result.ok <> true then Toast("This server does not offer this selection.") : return
        entries = data.libraries
        m.browseChoiceKind = "library"
        if purpose = "lib_collections" then entries = data.entries : m.browseChoiceKind = "collection"
        if purpose = "lib_server_collections" then entries = data.entries : m.browseChoiceKind = "server_collection"
        if type(entries) <> "roArray" then return
        m.browseChoiceEntries = entries
        labels = ["All titles"]
        for each entry in entries
            if labels.Count() >= 61 then exit for
            labels.Push(entry.title)
        end for
        BrowsePagedChoices("Select", labels, "onLibraryChoice")
        return
    end if
    m.libraryLoading = false
    if purpose = "lib_sections"
        if result.ok <> true then m.libraryError = true : m.libraryRetrySections = purpose = "lib_sections" : LibraryShowRetry() : return
        m.librarySection = SiloUIPlexSection(data.sections, m.libraryType)
        if m.librarySection = "" then m.libraryEmpty.text = "No matching library." : return
        m.libraryOffset = 0
        LibraryPlexPage()
        return
    end if
    if result.ok <> true then m.libraryError = true : m.libraryRetrySections = purpose = "lib_sections" : LibraryShowRetry() : return
    m.libraryLoadedScope = SearchCaptureScope()
    m.libraryLoadedRevision = NumberOr(m.libraryLoadedRevision,0) + 1
    m.libraryPages = NumberOr(m.libraryPages, 0) + 1
    items = data.items
    if type(items) <> "roArray" then items = []
    for each item in items
        if m.grid.content.getChildCount() >= 300 then exit for
        found = false
        for index = 0 to m.grid.content.getChildCount() - 1
            existing = m.grid.content.getChild(index).item
            if existing <> invalid and existing.itemId = item.itemId then found = true : exit for
        end for
        if not found then m.grid.content.appendChild(ItemNode(item))
    end for
    if m.provider = "plex"
        m.libraryOffset = NumberOr(data.nextOffset, m.grid.content.getChildCount())
        m.libraryMore = data.hasMore = true
        if m.libraryRetryButtons <> invalid then m.libraryRetryButtons.visible = false
        if m.zone = "libraryRetry" then LibraryFocusContent()
        m.libraryEmpty.text = ""
        if m.grid.content.getChildCount() = 0 then m.libraryEmpty.text = "Nothing here yet."
        return
    end if
    if m.libraryRetryButtons <> invalid then m.libraryRetryButtons.visible = false
    if m.zone = "libraryRetry" then LibraryFocusContent()
    m.libraryCursor = TextOr(data.nextCursor)
    m.libraryHasNext = data.hasMore = true and m.libraryCursor <> "" and m.libraryCursor <> m.libraryRequestedCursor
    m.libraryMore = m.libraryHasNext and m.grid.content.getChildCount() < 300 and m.libraryPages < 5
    m.libraryEmpty.text = ""
    if m.grid.content.getChildCount() = 0 then m.libraryEmpty.text = "Nothing here yet."
end sub

sub LibraryFocusContent()
    if m.grid.content <> invalid and m.grid.content.getChildCount() > 0 then SetZone("grid") else SetZone("libraryTabs")
end sub

sub onGridFocus()
    if m.publicArtwork <> invalid then SiloUIArtworkFocused()
    if m.grid.content = invalid or m.libraryError = true then return
    count = m.grid.content.getChildCount()
    if m.libraryMore and not m.libraryLoading and m.grid.itemFocused >= count - 14 then LibraryQuery(false)
end sub

sub onGridSelect()
    node = m.grid.content.getChild(m.grid.itemSelected)
    if node <> invalid then DetailOpen(node.item)
end sub

function LibraryKey(key as String) as Boolean
    if key = "options" then LibraryOptions() : return true
    if m.zone = "libraryRetry"
        if key = "OK"
            if m.libraryLoading = true then return true
            m.libraryError = false
            if m.libraryRetrySections = true
                m.libraryLoading = true
                Api("sections",{},"lib_sections",m.libraryToken)
            else
                LibraryQuery(false)
            end if
            return true
        end if
        if key = "up" then SetZone("libraryTabs") : return true
        if key = "down" and m.grid.content <> invalid then SetZone("grid") : return true
        return true
    end if
    if m.zone = "libraryTabs"
        if key = "left" or key = "right"
            delta = 1
            if key = "left" then delta = -1
            if PillMove("libraryTabs", delta) then LibraryQuery(true)
            return true
        end if
        if key = "up" then SetZone("nav") : return true
        if key = "down"
            if m.libraryError = true then SetZone("libraryRetry") else LibraryFocusContent()
            return true
        end if
        return true
    end if
    if m.zone = "grid" and key = "up" then SetZone("libraryTabs") : return true
    return false
end function

' ---------- search ----------

sub SearchInit()
    m.keyboard = m.top.findNode("keyboard")
    m.keyboard.observeField("text", "onSearchText")
    m.searchGrid = m.top.findNode("searchGrid")
    m.searchGrid.observeField("itemSelected", "onSearchSelect")
    m.searchGrid.observeField("itemFocused", "onSearchFocus")
    m.searchHint = m.top.findNode("searchHint")
    m.searchHint.font = SiloUIFont(20, false)
    m.searchHint.text = SearchPrompt()
    m.searchKind = ""
    m.searchKindScope = invalid
    m.searchToken = 0
    m.searchFailed = false
    m.searchTimer = CreateObject("roSGNode", "Timer")
    m.searchTimer.duration = 0.4
    m.searchTimer.observeField("fire", "onSearchTimer")
end sub

sub onSearchText()
    SearchSyncKind()
    ' Retire every reply as soon as text changes, including during debounce.
    m.searchToken = m.searchToken + 1
    SearchResetPages()
    m.searchTimer.control = "stop"
    m.searchGrid.content = CreateObject("roSGNode", "ContentNode")
    if m.view = "search" and m.zone = "searchGrid" then SetZone("keyboard")
    m.searchHint.text = SearchStatus("Searching…")
    if Len(m.keyboard.text.Trim()) < 2
        m.searchHint.text = SearchPrompt()
        return
    end if
    m.searchTimer.control = "start"
end sub

sub SearchResetPages()
    m.searchProvisional = false
    m.searchFailed = false
    m.searchLoading = false
    m.searchMore = false
    m.searchPages = 0
    m.searchCursor = ""
    m.searchSeenCursors = []
    m.searchOwner = invalid
    m.searchPeoplePending = false
    m.searchPersonPendingToken = invalid
end sub

sub onSearchTimer()
    SearchSyncKind()
    m.searchReload = false
    m.searchToken = m.searchToken + 1
    SearchResetPages()
    m.searchGrid.content = CreateObject("roSGNode", "ContentNode")
    text = m.keyboard.text.Trim()
    if Len(text) < 2
        m.searchHint.text = SearchPrompt()
        return
    end if
    m.searchOwner = {query:text, provider:m.provider, sourceId:m.sourceId, profileId:m.profileId, generation:m.generation, kind:m.searchKind}
    SearchPage()
    SearchShowLoaded()
end sub

function SearchCaptureScope() as Object
    return {provider:m.provider,sourceId:m.sourceId,profileId:m.profileId,generation:m.generation}
end function

function SearchLoadedScopeCurrent(scope as Dynamic) as Boolean
    if type(scope) <> "roAssociativeArray" then return false
    return scope.provider = m.provider and scope.sourceId = m.sourceId and scope.profileId = m.profileId and scope.generation = m.generation
end function

sub SearchEnsureLoadedScope()
    if not SearchLoadedScopeCurrent(m.searchLoadedScope)
        m.searchLoaded = []
        m.searchLoadedTitles = {}
        m.searchLoadedHome = invalid
        m.searchLoadedLibrary = invalid
    end if
    m.searchLoadedScope = SearchCaptureScope()
end sub

sub SearchRememberLoaded(incoming as Object)
    if incoming.Count() = 0 then return
    m.searchLoaded = SearchIndexAdd(m.searchLoaded,incoming,m.sourceId,100)
    titles = {}
    context = SearchQueryContext("")
    for each item in m.searchLoaded
        prior = m.searchLoadedTitles[item.itemId]
        if prior <> invalid and prior.title = item.title
            titles[item.itemId] = prior
        else
            titles[item.itemId] = {title:item.title,text:SearchNormalizeText(item.title,context.separator)}
        end if
    end for
    m.searchLoadedTitles = titles
end sub

sub SearchShowLoaded()
    if m.provider <> "silo" or not SearchContextCurrent() or m.searchPages <> 0 or m.searchLoading <> true then return
    SearchEnsureLoadedScope()
    incoming = []
    if SearchLoadedScopeCurrent(m.homeLoadedScope) and type(m.homeRows) = "roArray"
        if m.searchLoadedHome = invalid or m.searchLoadedHome.revision <> m.homeLoadedRevision
            for each row in m.homeRows
                if type(row.items) = "roArray"
                    for each item in row.items
                        if incoming.Count() >= 100 then exit for
                        incoming.Push(item)
                    end for
                end if
                if incoming.Count() >= 100 then exit for
            end for
            m.searchLoadedHome = {revision:m.homeLoadedRevision}
        end if
    end if
    SearchRememberLoaded(incoming)
    incoming = []
    if SearchLoadedScopeCurrent(m.libraryLoadedScope) and m.grid <> invalid
        if m.grid.content <> invalid and (m.searchLoadedLibrary = invalid or m.searchLoadedLibrary.revision <> m.libraryLoadedRevision)
            for index = 0 to m.grid.content.getChildCount() - 1
                if incoming.Count() >= 100 then exit for
                incoming.Push(m.grid.content.getChild(index).item)
            end for
            m.searchLoadedLibrary = {revision:m.libraryLoadedRevision}
        end if
    end if
    SearchRememberLoaded(incoming)
    matches = SearchLoadedMatches(m.searchLoaded,m.searchLoadedTitles,m.searchOwner.query,m.searchKind)
    for each item in matches
        m.searchGrid.content.appendChild(ItemNode(item))
    end for
    m.searchProvisional = matches.Count() > 0
    if m.searchProvisional then m.searchHint.text = SearchStatus("Loaded titles · Incomplete · Searching…")
end sub

function SearchOwnerCurrent() as Boolean
    owner = m.searchOwner
    if owner = invalid then return false
    if owner.provider <> m.provider or owner.sourceId <> m.sourceId or owner.profileId <> m.profileId or owner.generation <> m.generation then return false
    return owner.query = m.keyboard.text.Trim() and owner.kind = m.searchKind
end function

function SearchContextCurrent() as Boolean
    if not SearchOwnerCurrent() or m.view <> "search" or m.searchPeoplePending = true or m.searchPersonPendingToken <> invalid then return false
    if m.top <> invalid
        if m.top.dialog <> invalid then if m.top.dialog.close <> true and m.top.dialog.wasClosed <> true then return false
    end if
    return m.zone = "keyboard" or m.zone = "searchGrid"
end function

sub SearchPage()
    if not SearchContextCurrent() or m.searchLoading = true then return
    m.searchFailed = false
    m.searchLoading = true
    m.searchToken = m.searchToken + 1
    m.searchHint.text = SearchStatus("Searching…")
    count = m.searchGrid.content.getChildCount()
    if m.searchProvisional = true
        m.searchHint.text = SearchStatus("Loaded titles · Incomplete · Searching…")
    else if count > 0
        label = count.ToStr() + " results"
        if count = 1 then label = "1 result"
        m.searchHint.text = SearchStatus(label + " · Loading more…")
    end if
    params = {query:m.searchOwner.query, limit:36}
    if m.searchOwner.provider = "silo" and m.searchOwner.kind <> "" then params.type = m.searchOwner.kind
    if m.searchCursor <> "" then params.cursor = m.searchCursor
    if m.searchOwner.provider = "plex" then Api("search", params, "search_results", m.searchToken) else Api("catalog_query", params, "search_results", m.searchToken)
end sub

sub SearchResult(purpose as String, result as Object, data as Object, extra as Dynamic)
    if extra <> m.searchToken or not SearchOwnerCurrent() or m.searchLoading <> true then return
    ' Same-owner replies may settle while hidden; only visible focus can dispatch more.
    m.searchLoading = false
    if result.ok <> true
        m.searchFailed = true
        message = "Search failed. Press Options to retry."
        if m.searchProvisional = true then message = "Loaded titles · Incomplete · " + message
        m.searchHint.text = SearchStatus(message)
        return
    end if
    if m.searchPages = 0
        SearchRemember()
        if m.searchProvisional = true then m.searchGrid.content = CreateObject("roSGNode", "ContentNode")
        m.searchProvisional = false
    end if
    m.searchPages = m.searchPages + 1
    root = m.searchGrid.content
    before = root.getChildCount()
    loadedItems = []
    if type(data.items) = "roArray"
        pageItems = 0
        for each item in data.items
            if pageItems >= 36 or root.getChildCount() >= 108 then exit for
            pageItems = pageItems + 1
            found = false
            for index = 0 to root.getChildCount() - 1
                existing = root.getChild(index).item
                if item.itemId <> invalid and existing.itemId = item.itemId then found = true : exit for
            end for
            if item.type <> "episode" and not found
                root.appendChild(ItemNode(item))
                loadedItems.Push(item)
            end if
        end for
    end if
    if m.provider = "silo"
        SearchEnsureLoadedScope()
        SearchRememberLoaded(loadedItems)
    end if
    cursor = ""
    if type(data.nextCursor) = "roString" or type(data.nextCursor) = "String" then cursor = data.nextCursor
    seen = cursor = m.searchCursor
    for each prior in m.searchSeenCursors
        if cursor = prior then seen = true
    end for
    m.searchSeenCursors.Push(m.searchCursor)
    hasNext = m.searchOwner.provider = "silo" and data.hasMore = true and cursor <> "" and not seen
    capped = m.searchPages >= 3 or root.getChildCount() >= 108
    m.searchMore = hasNext and not capped
    m.searchCursor = cursor
    count = root.getChildCount()
    m.searchHint.text = count.ToStr() + " results"
    if count = 1 then m.searchHint.text = "1 result"
    if count = 0 then m.searchHint.text = "No matches."
    if hasNext and capped then m.searchHint.text = m.searchHint.text + " · Refine your search for more."
    m.searchHint.text = SearchStatus(m.searchHint.text)
    ' A filtered page has no new focus event to make its cursor reachable.
    if m.searchMore and root.getChildCount() = before then SearchPage()
end sub

sub SearchResume()
    if not SearchContextCurrent() or m.searchLoading = true or m.searchFailed = true then return
    if Len(m.searchOwner.query) < 2 then return
    if m.searchPages = 0
        SearchPage()
    else if m.searchMore = true and m.searchGrid.content.getChildCount() = 0
        SearchPage()
    else
        onSearchFocus()
    end if
end sub

sub onSearchDialogClosed()
    ' A replaced dialog may report closure after its successor is visible.
    if m.top.dialog <> invalid
        if m.top.dialog.close <> true and m.top.dialog.wasClosed <> true then return
    end if
    if m.searchOptionsDebounce = true
        m.searchOptionsDebounce = false
        if BrowseContextCurrent(m.searchOptionsContext) and m.searchOptionsQuery = m.keyboard.text.Trim() then onSearchText()
        return
    end if
    SearchResume()
end sub

sub onSearchFocus()
    if m.publicArtwork <> invalid then SiloUIArtworkFocused()
    if not SearchContextCurrent() or m.zone <> "searchGrid" then return
    if m.searchLoading = true or m.searchFailed = true or m.searchMore <> true then return
    if m.searchGrid.itemFocused >= m.searchGrid.content.getChildCount() - 4 then SearchPage()
end sub

sub onSearchSelect()
    node = m.searchGrid.content.getChild(m.searchGrid.itemSelected)
    if node <> invalid then DetailOpen(node.item)
end sub

function SearchKey(key as String) as Boolean
    if key = "options" and m.searchFailed = true
        m.searchTimer.control = "stop"
        SearchPage()
        return true
    end if
    if key = "options" and m.provider = "silo"
        SearchSyncKind()
        m.searchOptionsQuery = m.keyboard.text.Trim()
        m.searchOptionsDebounce = not SearchOwnerCurrent()
        if m.searchOptionsDebounce then m.searchTimer.control = "stop"
        m.searchOptionsContext = BrowseCaptureContext()
        BrowseDialog("Search • " + SearchKindLabel(), ["All titles", "Movies", "Shows", "Search people", "Recent searches", "Cancel"], "onSearchOption")
        return true
    end if
    if m.zone = "keyboard"
        if key = "right" and m.searchGrid.content <> invalid and m.searchGrid.content.getChildCount() > 0 then SetZone("searchGrid") : return true
        if key = "up" then SetZone("nav") : return true
    else if m.zone = "searchGrid"
        if key = "left" then SetZone("keyboard") : return true
        if key = "up" then SetZone("nav") : return true
    end if
    return false
end function

function SearchPrompt() as String
    if m.provider = "plex" then return "Search titles. Options searches people."
    return SearchStatus("Search titles. Options filters and people.")
end function

function SearchKindLabel() as String
    if m.searchKind = "movie" then return "Movies"
    if m.searchKind = "series" then return "Shows"
    return "All titles"
end function

function SearchStatus(message as String) as String
    if m.provider <> "silo" then return message
    return SearchKindLabel() + " · " + message
end function

sub SearchSyncKind()
    scope = m.searchKindScope
    if scope = invalid
        m.searchKind = ""
        m.searchRecents = SearchLoadRecents()
    else if scope.provider <> m.provider or scope.sourceId <> m.sourceId or scope.profileId <> m.profileId or scope.generation <> m.generation
        m.searchKind = ""
        m.searchRecents = SearchLoadRecents()
    end if
    if m.searchRecents = invalid then m.searchRecents = []
    m.searchKindScope = {provider:m.provider,sourceId:m.sourceId,profileId:m.profileId,generation:m.generation}
end sub

function SearchRecentText(value as Dynamic, limit as Integer) as Boolean
    if type(value) <> "String" and type(value) <> "roString" then return false
    if Len(value) = 0 or Len(value) > limit then return false
    for index = 1 to Len(value)
        code = Asc(Mid(value,index,1))
        if code < 32 or code = 127 then return false
    end for
    return true
end function

function SearchRecentScope() as Boolean
    if m.provider <> "silo" then return false
    return SearchRecentText(m.sourceId,512) and SearchRecentText(m.profileId,256)
end function

function SearchLoadRecents() as Object
    if not SearchRecentScope() then return []
    section = AppRegistrySection("silo")
    raw = section.Read("recentSearches")
    if Len(raw) = 0 or Len(raw) > 2048 then return []
    record = ParseJson(raw,"i")
    if type(record) <> "roAssociativeArray" then return []
    schemaType = type(record.schemaVersion)
    if schemaType <> "Integer" and schemaType <> "roInt" and schemaType <> "roInteger" then return []
    if not SearchRecentText(record.sourceId,512) or not SearchRecentText(record.profileId,256) then return []
    if type(record.revision) <> "String" and type(record.revision) <> "roString" then return []
    if record.schemaVersion <> 1 or record.sourceId <> m.sourceId or record.profileId <> m.profileId then return []
    if record.revision <> section.Read("revision") then return []
    if type(record.queries) <> "roArray" then return []
    if record.queries.Count() > 8 then return []
    for each query in record.queries
        if not SearchRecentText(query,120) then return []
    end for
    return record.queries
end function

sub SearchSaveRecents()
    if not SearchRecentScope() then return
    section = AppRegistrySection("silo")
    if m.searchRecents.Count() = 0
        section.Delete("recentSearches")
    else
        ' One slot bounds registry use; the revision retires history on sign-out.
        record = {schemaVersion:1,sourceId:m.sourceId,profileId:m.profileId,revision:section.Read("revision"),queries:m.searchRecents}
        raw = FormatJson(record)
        if Len(raw) > 2048 then return
        section.Write("recentSearches",raw)
    end if
    section.Flush()
end sub

sub onSearchOption(event as Object)
    if m.searchOptionsQuery <> m.keyboard.text.Trim() then return
    if BrowseTakeDialog(event,"onSearchOption") = invalid then return
    index = m.browseDialog.buttonSelected
    m.browseDialog.close = true
    if index = 4
        SearchRecentChoices()
        return
    end if
    if index = 3
        m.searchOptionsDebounce = false
        m.searchTimer.control = "stop"
        if not SearchOwnerCurrent()
            SearchResetPages()
            m.searchOwner = {query:m.keyboard.text.Trim(), provider:m.provider, sourceId:m.sourceId, profileId:m.profileId, generation:m.generation, kind:m.searchKind}
        end if
        m.searchPeoplePending = true
        m.searchToken = m.searchToken + 1
        m.searchLoading = false
        Api("people", {query:m.keyboard.text}, "browse_people", m.searchToken)
        return
    end if
    if index < 0 or index > 2 then onSearchDialogClosed() : return
    kinds = ["", "movie", "series"]
    if m.searchKind = kinds[index] then onSearchDialogClosed() : return
    m.searchOptionsDebounce = false
    m.searchKind = kinds[index]
    onSearchText()
end sub

sub SearchRemember()
    SearchSyncKind()
    query = m.searchOwner.query
    if Len(query) > 120 then return
    for index = 1 to Len(query)
        code = Asc(Mid(query,index,1))
        if code < 32 or code = 127 then return
    end for
    recent = [query]
    for each prior in m.searchRecents
        if LCase(prior) <> LCase(query) and recent.Count() < 8 then recent.Push(prior)
    end for
    m.searchRecents = recent
    SearchSaveRecents()
end sub

sub SearchRecentChoices()
    SearchSyncKind()
    m.searchRecentQuery = m.keyboard.text.Trim()
    m.searchRecentChoices = []
    for each query in m.searchRecents
        m.searchRecentChoices.Push(query)
    end for
    labels = []
    for each query in m.searchRecentChoices
        labels.Push(query)
    end for
    title = "Recent searches"
    if labels.Count() = 0 then title = "No recent searches"
    if labels.Count() > 0 then labels.Push("Clear recent searches")
    BrowsePagedChoices(title,labels,"onSearchRecent")
end sub

sub onSearchRecent(event as Object)
    if m.searchRecentQuery <> m.keyboard.text.Trim() then return
    index = BrowseChoiceIndex(event)
    if index < 0 then onSearchDialogClosed() : return
    count = m.searchRecentChoices.Count()
    if index >= 0 and index < count
        m.searchOptionsDebounce = false
        query = m.searchRecentChoices[index]
        ' Use the normal text observer once; unchanged text needs an explicit restart.
        if m.keyboard.text = query
            onSearchText()
        else
            m.keyboard.text = query
        end if
        return
    end if
    if count > 0 and index = count
        m.searchRecents = []
        SearchSaveRecents()
    end if
    onSearchDialogClosed()
end sub

sub LibraryPlexPage()
    sort = m.librarySorts[m.pillGroups.libraryTabs.index]
    m.libraryLoading = true
    Api("library_items", {sectionId: m.librarySection, sort: SiloUIPlexSort(sort.sort, sort.order), offset: m.libraryOffset, limit: 60}, "lib_page", m.libraryToken)
end sub

sub LibraryShowRetry()
    m.libraryError = true
    m.libraryEmpty.text = "Couldn't load this library."
    if m.libraryFormatFilter <> invalid and m.libraryFormatFilter <> "" then m.libraryEmpty.text = "This server couldn't filter by " + LibraryFormatTitle(m.libraryFormatFilter) + ". Try another format or clear filters."
    if m.libraryRetryButtons = invalid then m.libraryRetryButtons = m.top.findNode("libraryRetryButtons")
    m.libraryRetryButtons.visible = true
    BuildButtons(m.libraryRetryButtons,"libraryRetry",["Retry"])
    if m.view = "library" then SetZone("libraryRetry")
end sub

' Native dialogs keep optional browse controls out of the poster layout.
sub BrowseDialog(title as String, labels as Object, handler as String)
    dialog = CreateObject("roSGNode", "Dialog")
    dialog.title = title
    dialog.maxHeight = 620
    dialog.buttons = labels
    m.browseDialog = dialog
    BrowseBindDialog(dialog,handler)
    dialog.observeField("buttonSelected", handler)
    if m.view = "search" then dialog.observeField("wasClosed", "onSearchDialogClosed")
    m.top.dialog = dialog
end sub

sub LibraryOptions()
    if m.provider <> "silo" then return
    BrowsePagedChoices("Browse • Filters and lists", ["Libraries", "Collections", "Server collections", "Genre", "Watched status", "A–Z jump", "Watchlist", "Favorites", "History", "Clear filters", "Next page", "Audiobooks", LibraryShuffleLabel(), "Release decade", "Minimum IMDb rating"], "onLibraryOption")
end sub

function LibraryShuffleLabel() as String
    if TextOr(m.libraryCollection) <> "" then return "Shuffle full collection"
    return "Shuffle full library"
end function

sub LibraryShuffle()
    scope = {kind:"library",id:TextOr(m.libraryId)}
    if TextOr(m.libraryCollection) <> ""
        scope = {kind:"user_collection",id:m.libraryCollection}
        if m.librarySource = "library_collection" then scope.kind = "library_collection"
    end if
    needsConfirmation = TextOr(m.libraryPerson) <> "" or TextOr(m.libraryGenre) <> "" or TextOr(m.libraryWatched) <> "" or TextOr(m.libraryPrefix) <> "" or TextOr(m.libraryFormatFilter) <> ""
    needsConfirmation = needsConfirmation or NumberOr(m.libraryDecade,0) > 0 or NumberOr(m.libraryMinimumRating,0) > 0
    source = TextOr(m.librarySource)
    needsConfirmation = needsConfirmation or source = "person" or source = "watchlist" or source = "favorites" or source = "history"
    if not needsConfirmation
        ShuffleBegin(scope.kind,scope.id)
        return
    end if
    BrowseDialog(LibraryShuffleLabel(), [LibraryShuffleLabel(), "Cancel"], "onLibraryShuffleConfirm")
    m.browseDialog.message = "Shuffle uses the full library or collection. Browse filters, person selections and lists do not apply."
    m.browseDialogTicket.scope = scope
end sub

sub onLibraryShuffleConfirm(event as Object)
    ticket = BrowseTakeDialog(event,"onLibraryShuffleConfirm")
    if ticket = invalid then return
    m.browseDialog.close = true
    if ticket.node.buttonSelected <> 0 then return
    ShuffleBegin(ticket.scope.kind,ticket.scope.id)
end sub

sub onLibraryOption(event as Object)
    index = BrowseChoiceIndex(event)
    if index < 0 then return
    m.libraryChoiceContext = BrowseCaptureContext()
    if index = 11 then SiloUIAudioBrowse() : return
    if index = 0 then Api("libraries", {}, "lib_choices", m.libraryToken) : return
    if index = 1 then Api("collections", {}, "lib_collections", m.libraryToken) : return
    if index = 2 then Api("server_collections", {}, "lib_server_collections", m.libraryToken) : return
    if index = 12
        LibraryShuffle()
        return
    end if
    if index = 13
        m.browseChoiceKind = "decade"
        m.browseChoices = ["All decades", "2020s", "2010s", "2000s", "1990s", "1980s", "1970s", "1960s", "1950s", "1940s", "1930s", "1920s", "1910s", "1900s"]
    else if index = 14
        m.browseChoiceKind = "rating"
        m.browseChoices = ["Any rating", "IMDb 6+", "IMDb 7+", "IMDb 8+", "IMDb 9+"]
    else if index = 3
        LibraryGenresOpen()
        return
    else if index = 4
        m.browseChoiceKind = "watched"
        m.browseChoices = ["All statuses", "Watched", "Unwatched"]
    else if index = 5
        m.browseChoiceKind = "prefix"
        m.browseChoices = ["All letters"]
        for letter = 65 to 90
            m.browseChoices.Push(Chr(letter))
        end for
    else if index >= 6 and index <= 8
        sources = ["watchlist", "favorites", "history"]
        m.librarySource = sources[index - 6]
        m.libraryCollection = ""
        m.libraryCollectionTitle = ""
        m.libraryPerson = ""
        LibraryQuery(true)
        return
    else if index = 10
        if m.libraryHasNext <> true or m.libraryLoading = true then Toast("No next page available.") : return
        m.libraryToken = m.libraryToken + 1
        m.libraryPages = 0
        m.libraryMore = false
        m.grid.content = CreateObject("roSGNode", "ContentNode")
        LibraryQuery(false)
        return
    else if index = 9
        LibraryResetFilters()
        LibraryQuery(true)
        return
    else
        return
    end if
    BrowsePagedChoices("Filter", m.browseChoices, "onLibraryChoice")
end sub

sub LibraryResetFilters()
    m.libraryId = ""
    m.librarySource = "query"
    m.libraryCollection = ""
    m.libraryCollectionTitle = ""
    m.libraryPerson = ""
    m.libraryGenre = ""
    m.libraryWatched = ""
    m.libraryPrefix = ""
    m.libraryFormatFilter = ""
    m.libraryFormatTitle = ""
    m.libraryDecade = 0
    m.libraryMinimumRating = 0
end sub

function LibraryCollectionChoice(kind as String, entry as Dynamic) as Object
    clear = {source:"query",collectionId:"",libraryId:""}
    if type(entry) <> "roAssociativeArray" then return clear
    id = entry.id
    if type(id) <> "String" and type(id) <> "roString" then return clear
    if id = "" then return clear
    if kind = "collection" and entry.source = "user_collection"
        return {source:"user_collection",collectionId:id,libraryId:""}
    end if
    if kind = "server_collection" and entry.source = "library_collection"
        libraryId = entry.libraryId
        if type(libraryId) <> "String" and type(libraryId) <> "roString" then return clear
        if libraryId = "" then return clear
        return {source:"library_collection",collectionId:id,libraryId:libraryId}
    end if
    return clear
end function

sub onLibraryChoice(event as Object)
    index = BrowseChoiceIndex(event)
    if index < 0 then return
    if m.browseChoiceKind = "library"
        m.libraryId = ""
        if index > 0 then m.libraryId = m.browseChoiceEntries[index - 1].libraryId
        m.libraryCollection = ""
        m.libraryCollectionTitle = ""
        m.librarySource = "query"
    else if m.browseChoiceKind = "collection" or m.browseChoiceKind = "server_collection"
        entry = invalid
        if index > 0 and index <= m.browseChoiceEntries.Count() then entry = m.browseChoiceEntries[index - 1]
        selection = LibraryCollectionChoice(m.browseChoiceKind, entry)
        m.libraryCollection = selection.collectionId
        m.librarySource = selection.source
        m.libraryId = selection.libraryId
        m.libraryCollectionTitle = ""
        if selection.collectionId <> "" then m.libraryCollectionTitle = Left(entry.title, 70)
    else if m.browseChoiceKind = "decade"
        m.libraryDecade = 0
        if index > 0 and index <= 13 then m.libraryDecade = 2030 - index * 10
    else if m.browseChoiceKind = "rating"
        m.libraryMinimumRating = 0
        if index > 0 and index <= 4 then m.libraryMinimumRating = 5 + index
    else if m.browseChoiceKind = "genre"
        m.libraryGenre = ""
        if index > 0 then m.libraryGenre = m.browseChoices[index]
    else if m.browseChoiceKind = "watched"
        statuses = ["", "watched", "unwatched"]
        m.libraryWatched = statuses[index]
    else if m.browseChoiceKind = "prefix"
        m.libraryPrefix = ""
        if index > 0 then m.libraryPrefix = m.browseChoices[index]
    end if
    LibraryQuery(true)
end sub

sub BrowsePerson(personId as String)
    if personId = "" or m.provider <> "silo" then return
    m.browsePersonContext = BrowseCaptureContext()
    m.browsePersonView = m.view
    m.browsePersonVisit = m.detailToken
    m.browsePersonId = personId
    m.browsePersonToken = NumberOr(m.browsePersonToken, 0) + 1
    m.searchPersonPendingToken = invalid
    if m.view = "search" then m.searchPersonPendingToken = m.browsePersonToken
    Api("person", {personId:personId}, "browse_person", m.browsePersonToken)
end sub

sub BrowseResult(purpose as String, result as Object, data as Object, extra as Dynamic)
    if purpose = "browse_collection_create"
        if extra = invalid or m.browseCollectionTicket = invalid then return
        if not BrowseContextCurrent(extra.context) then return
        if extra.requestId <> m.browseCollectionTicket.requestId or m.browseCollectionStage <> "creating" then return
        m.browseCollectionStage = "done"
        m.browseMutationPending = false
        if result.ok <> true then Toast("Collection creation was not confirmed. Check your collections before trying again.") : return
        m.libraryReload = true
        if extra.addTitle = true
            m.browseMutationContext = extra.context
            m.browseMutationPending = true
            m.browseMutationGeneration = m.generation
            m.browseMutationToken = NumberOr(m.browseMutationToken,0)+1
            m.browseMutationAction = "collection_created_add"
            ApiOwned("collection_add",{itemId:extra.itemId,collectionId:data.collectionId},"browse_social",m.browseMutationToken,extra.context.owner)
        else
            Toast("Collection created.")
        end if
        m.browseCollectionTicket = invalid
        return
    else if purpose = "browse_collection_capabilities" or purpose = "browse_collection_choices"
        if extra = invalid or m.browseCollectionTicket = invalid then return
        if not BrowseContextCurrent(extra.context) then return
        if extra.requestId <> m.browseCollectionTicket.requestId then return
        if extra.itemId <> m.browseCollectionTicket.itemId then return
        expectedStage = "choices"
        if purpose = "browse_collection_capabilities" then expectedStage = "capabilities"
        if m.browseCollectionStage <> expectedStage then return
        m.browseCollectionStage = "done"
        if result.ok <> true then Toast("Collection editing is unavailable. Use the server's collection manager.") : return
        if purpose = "browse_collection_capabilities"
            m.browseCollectionCanCreate = data.canCreate = true
            if data.supported <> true
                if m.browseCollectionCanCreate <> true then Toast("Collection editing is unavailable. Use the server's collection manager.") : return
                m.browseCollectionEntries = []
                m.browseCollectionStage = "select"
                BrowsePagedChoices("Collections",["New collection"],"onBrowseCollection")
                return
            end if
            m.browseCollectionStage = "choices"
            ApiOwned("collection_choices",{itemId:extra.itemId},"browse_collection_choices",extra,extra.context.owner)
            return
        end if
        m.browseCollectionEntries = []
        labels = []
        for each entry in data.entries
            if entry.creatorProfileId = m.profileId and entry.collectionType = "manual"
                if entry.contains = true or entry.contains = false
                    m.browseCollectionEntries.Push(entry)
                    label = "Add to "
                    if entry.contains = true then label = "Remove from "
                    labels.Push(label + entry.title)
                end if
            end if
        end for
        if m.browseCollectionCanCreate = true then labels.Push("New collection")
        if labels.Count() = 0 then Toast("Create a manual collection in the server's collection manager first.") : return
        m.browseCollectionStage = "select"
        BrowsePagedChoices("Collections",labels,"onBrowseCollection")
    else if purpose = "browse_person"
        if extra <> m.browsePersonToken then return
        if m.searchPersonPendingToken = extra then m.searchPersonPendingToken = invalid
        if not BrowseContextCurrent(m.browsePersonContext) then return
        if m.view <> m.browsePersonView then return
        if m.view = "detail" and m.detailToken <> m.browsePersonVisit then return
        if result.ok <> true then Toast("Person information is unavailable.") : SearchResume() : return
        m.browsePerson = data.person
        BrowseDialog(data.person.name, ["Filmography", "Close"], "onBrowsePerson")
        m.browseDialog.message = Left(TextOr(data.person.bio), 1600)
    else if purpose = "browse_social"
        if not BrowseContextCurrent(m.browseMutationContext) then return
        if extra <> m.browseMutationToken then return
        m.browseMutationPending = false
        if result.ok <> true
            if m.browseMutationAction = "collection_created_add" then Toast("Collection created; title was not added.") : return
            Toast("Couldn't save this change. This server may not support it.") : return
        end if
        Toast("Saved.")
        m.homeReload = true
        m.libraryReload = true
        if m.view = "home"
            if m.browseMutationAction = "home_dismiss" then m.homeProgress = []
            HomeLoad()
        end if
    else if purpose = "browse_people"
        if extra <> m.searchToken then return
        m.searchPeoplePending = false
        if not SearchContextCurrent() then return
        if result.ok <> true then Toast("People search is unavailable.") : SearchResume() : return
        m.browsePeople = data.entries
        labels = []
        for each person in m.browsePeople
            labels.Push(person.title)
        end for
        if labels.Count() = 0 then Toast("No people found.") : SearchResume() : return
        BrowsePagedChoices("People", labels, "onBrowsePeople")
    end if
end sub

sub onBrowsePerson(event as Object)
    if BrowseTakeDialog(event,"onBrowsePerson") = invalid then return
    index = m.browseDialog.buttonSelected
    m.browseDialog.close = true
    if index <> 0 then return
    m.history.Push({view:m.view,zone:m.zone,browseDetailItem:m.detailItem})
    LibraryResetFilters()
    m.libraryPerson = m.browsePersonId
    m.librarySource = "person"
    m.libraryType = "video"
    m.libraryTitle.text = m.browsePerson.name
    ShowView("library")
    LibraryQuery(true)
    SetZone("libraryTabs")
end sub

sub onBrowsePeople(event as Object)
    index = BrowseChoiceIndex(event)
    if index < 0 then return
    if index < m.browsePeople.Count() then BrowsePerson(m.browsePeople[index].id)
end sub

sub BrowseSocial(item as Object)
    if m.provider <> "silo" or item = invalid then return
    if m.browseMutationPending = true and m.browseMutationGeneration = m.generation then return
    m.browseMutationPending = false
    m.browseSubtitleTools = m.view = "detail"
    m.browseDismissParams = invalid
    m.browseCollectionTicket = invalid
    m.browseSocialItem = item
    labels = ["Add to watchlist", "Remove from watchlist", "Add to favorites", "Remove from favorites"]
    if m.view = "home" and m.zone = "rows" and m.rows.rowItemFocused <> invalid
        index = m.rows.rowItemFocused[0]
        if index < m.homeRows.Count()
            surface = TextOr(m.homeRows[index].sectionType)
            if surface = "continue_watching" or surface = "next_up"
                if (surface = "continue_watching" and TextOr(item.progressUpdatedAt) <> "") or (surface = "next_up" and TextOr(item.seriesId) <> "")
                    m.browseDismissParams = {itemId:item.itemId,surface:surface,progressUpdatedAt:TextOr(item.progressUpdatedAt),seriesId:TextOr(item.seriesId)}
                    labels.Push("Hide from this home row")
                end if
            end if
        end if
    end if
    if m.browseSubtitleTools then labels.Push("Subtitle tools")
    m.browseGenreIndex = -1
    if m.browseSubtitleTools and type(item.genres) = "roArray"
        if item.genres.Count() > 0 and (item.type = "movie" or item.type = "series" or item.type = "episode")
            m.browseGenreIndex = labels.Count()
            labels.Push("Browse genre")
        end if
    end if
    m.browseCollectionIndex = labels.Count()
    labels.Push("Add or remove from collection")
    m.browseSynopsisIndex = -1
    if m.browseSubtitleTools and TextOr(item.summary).Trim() <> ""
        m.browseSynopsisIndex = labels.Count()
        labels.Push("Synopsis")
    end if
    m.browseHomeSectionsIndex = -1
    m.browseHomeSectionsId = ""
    if m.view = "home" and m.zone = "rows"
        focus = SiloUIHomeFocusPosition(m.rows.rowItemFocused,m.homeRows.Count())
        if focus <> invalid
            m.browseHomeSectionsId = TextOr(m.homeRows[focus[0]].rowId)
            if m.browseHomeSectionsId <> ""
                m.browseHomeSectionsIndex = labels.Count()
                labels.Push("Manage this Home row")
            end if
        end if
    end if
    labels.Push("Cancel")
    BrowseDialog("Save or remove", labels, "onBrowseSocial")
end sub

sub onBrowseSocial(event as Object)
    ticket = BrowseTakeDialog(event,"onBrowseSocial")
    if ticket = invalid then return
    index = m.browseDialog.buttonSelected
    m.browseDialog.close = true
    if index = m.browseHomeSectionsIndex and index >= 0
        HomeSectionsOpen(m.browseHomeSectionsId)
        return
    end if
    if index = m.browseSynopsisIndex and index >= 0
        DetailSynopsisOpen(m.browseSocialItem)
        return
    end if
    if index = m.browseCollectionIndex and index >= 0
        m.browseCollectionStage = "capabilities"
        m.browseCollectionSequence = NumberOr(m.browseCollectionSequence,0)+1
        m.browseCollectionTicket = {context:ticket.context,itemId:m.browseSocialItem.itemId,requestId:m.browseCollectionSequence}
        ApiOwned("collection_capabilities",{},"browse_collection_capabilities",m.browseCollectionTicket,ticket.context.owner)
        return
    end if
    if index = m.browseGenreIndex and index >= 0
        m.browseGenres = m.browseSocialItem.genres
        m.browseGenreItem = m.browseSocialItem
        BrowsePagedChoices("Browse genre",m.browseGenres,"onBrowseGenre")
        return
    end if
    if index < 0 or index > 4 then return
    if index = 4 and m.browseSubtitleTools = true then ServicesSubtitles() : return
    if index = 4 and m.browseDismissParams = invalid then return
    actions = ["watchlist_add", "watchlist_remove", "favorite_add", "favorite_remove"]
    m.browseMutationContext = ticket.context
    m.browseMutationPending = true
    m.browseMutationGeneration = m.generation
    m.browseMutationToken = NumberOr(m.browseMutationToken, 0) + 1
    if index = 4
        m.browseMutationAction = "home_dismiss"
        ApiOwned("home_dismiss", m.browseDismissParams, "browse_social", m.browseMutationToken,ticket.context.owner)
    else
        m.browseMutationAction = actions[index]
        ApiOwned(actions[index], {itemId:m.browseSocialItem.itemId}, "browse_social", m.browseMutationToken,ticket.context.owner)
    end if
end sub

sub onBrowseGenre(event as Object)
    index = BrowseChoiceIndex(event)
    if index < 0 or index >= m.browseGenres.Count() then return
    item = m.browseGenreItem
    m.history.Push({view:m.view,zone:m.zone,browseDetailItem:item})
    LibraryResetFilters()
    m.libraryGenre = m.browseGenres[index]
    m.libraryType = "movie"
    if item.type = "series" or item.type = "episode" then m.libraryType = "series"
    ShowView("library")
    LibraryQuery(true)
    SetZone("libraryTabs")
end sub

' Six data choices per native dialog; Back closes without changing the filter.
sub BrowsePagedChoices(title as String, choices as Object, handler as String, start = 0 as Integer)
    m.browsePaged = {title:title,choices:choices,handler:handler,start:start,count:0,previous:-1,nextPage:-1}
    labels = []
    for index = start to choices.Count() - 1
        if labels.Count() >= 6 then exit for
        labels.Push(Left(TextOr(choices[index]), 90))
    end for
    m.browsePaged.count = labels.Count()
    if start > 0
        m.browsePaged.previous = labels.Count()
        labels.Push("Previous choices")
    end if
    if start + m.browsePaged.count < choices.Count()
        m.browsePaged.nextPage = labels.Count()
        labels.Push("More choices")
    end if
    labels.Push("Cancel")
    BrowseDialog(title, labels, handler)
end sub

function BrowseChoiceIndex(event as Object) as Integer
    if m.browsePaged = invalid then return -1
    if BrowseTakeDialog(event,m.browsePaged.handler) = invalid then return -1
    index = m.browseDialog.buttonSelected
    m.browseDialog.close = true
    page = m.browsePaged
    if index = page.previous
        BrowsePagedChoices(page.title, page.choices, page.handler, page.start - 6)
        return -1
    end if
    if index = page.nextPage
        BrowsePagedChoices(page.title, page.choices, page.handler, page.start + 6)
        return -1
    end if
    if index >= page.count then return -1
    return page.start + index
end function

sub onBrowseCollection(event as Object)
    ticket = m.browseCollectionTicket
    if ticket = invalid or m.browseCollectionStage <> "select" then return
    if not BrowseContextCurrent(ticket.context) then return
    index = BrowseChoiceIndex(event)
    if index = m.browseCollectionEntries.Count() and m.browseCollectionCanCreate = true
        m.browseCollectionStage = "name"
        dialog = CreateObject("roSGNode", "KeyboardDialog")
        dialog.title = "New private collection"
        dialog.buttons = ["Create", "Create and add", "Cancel"]
        BrowseBindDialog(dialog,"onBrowseCollectionCreate")
        dialog.observeField("buttonSelected","onBrowseCollectionCreate")
        m.top.dialog = dialog
        return
    end if
    if index < 0 or index >= m.browseCollectionEntries.Count() then return
    entry = m.browseCollectionEntries[index]
    if entry.creatorProfileId <> m.profileId or entry.collectionType <> "manual" then return
    m.browseCollectionTicket = invalid
    action = "collection_add"
    if entry.contains = true then action = "collection_remove"
    m.browseMutationContext = ticket.context
    m.browseMutationPending = true
    m.browseMutationGeneration = m.generation
    m.browseMutationToken = NumberOr(m.browseMutationToken,0)+1
    m.browseMutationAction = action
    ApiOwned(action,{itemId:ticket.itemId,collectionId:entry.id},"browse_social",m.browseMutationToken,ticket.context.owner)
end sub

sub onBrowseCollectionCreate(event as Object)
    ticket = m.browseCollectionTicket
    if ticket = invalid or m.browseCollectionStage <> "name" then return
    if not BrowseContextCurrent(ticket.context) then return
    dialogTicket = BrowseTakeDialog(event,"onBrowseCollectionCreate")
    if dialogTicket = invalid then return
    dialog = dialogTicket.node
    index = dialog.buttonSelected
    dialog.close = true
    m.browseCollectionStage = "done"
    if index <> 0 and index <> 1 then return
    name = TextOr(dialog.text).Trim()
    if name = "" or Len(name) > 100 then Toast("Enter a collection name of up to 100 characters.") : return
    ticket.addTitle = index = 1
    m.browseCollectionStage = "creating"
    m.browseMutationPending = true
    m.browseMutationGeneration = m.generation
    ApiOwned("collection_create",{name:name},"browse_collection_create",ticket,ticket.context.owner)
end sub

function LibraryGenreNow() as Integer
    return CreateObject("roDateTime").AsSeconds()
end function

function LibraryGenreParams() as Object
    source = TextOr(m.librarySource)
    if source = "" then source = "query"
    if TextOr(m.libraryPerson) <> "" then source = "person"
    return {source:source,libraryId:TextOr(m.libraryId),collectionId:TextOr(m.libraryCollection),personId:TextOr(m.libraryPerson),type:TextOr(m.libraryType)}
end function

function LibraryGenreKey(params as Object) as String
    return FormatJson([m.provider,m.sourceId,m.profileId,m.generation,DetailPhotoSessionRevision(),params])
end function

sub LibraryGenresShow(genres as Object, fallback = false as Boolean)
    m.browseChoiceKind = "genre"
    m.browseChoices = ["All genres"]
    for each genre in genres
        m.browseChoices.Push(genre)
    end for
    title = "Genres in this library"
    source = TextOr(m.librarySource)
    if source = "favorites" or source = "watchlist" or source = "history" then title = "Genres in this list"
    if TextOr(m.libraryCollection) <> "" then title = "Genres in this collection"
    if TextOr(m.libraryPerson) <> "" then title = "Genres for this person"
    if fallback then title = "Standard genres • server genres unavailable"
    BrowsePagedChoices(title,m.browseChoices,"onLibraryChoice")
end sub

sub LibraryGenresFallback()
    LibraryGenresShow(["Action", "Adventure", "Animation", "Comedy", "Crime", "Documentary", "Drama", "Family", "Fantasy", "History", "Horror", "Music", "Mystery", "Romance", "Science Fiction", "Thriller", "War", "Western"],true)
end sub

sub LibraryGenresOpen()
    if m.provider <> "silo" then return
    params = LibraryGenreParams()
    key = LibraryGenreKey(params)
    now = LibraryGenreNow()
    if m.libraryGenreCache = invalid then m.libraryGenreCache = []
    fresh = []
    cached = invalid
    for each entry in m.libraryGenreCache
        if now >= entry.at and now - entry.at < 300
            fresh.Push(entry)
            if entry.key = key then cached = entry.genres
        end if
    end for
    m.libraryGenreCache = fresh
    m.libraryGenrePending = invalid
    if cached <> invalid then LibraryGenresShow(cached) : return
    BrowseDialog("Loading genres…",["Cancel"],"onLibraryGenreCancel")
    pending = {key:key,context:BrowseCaptureContext(),sequence:m.browseDialogSequence,node:m.browseDialog,ticket:m.browseDialogTicket,token:m.libraryToken}
    m.libraryGenrePending = pending
    Api("catalog_genres",params,"lib_genres",{token:m.libraryToken,sequence:pending.sequence})
end sub

sub onLibraryGenreCancel(event as Object)
    ticket = BrowseTakeDialog(event,"onLibraryGenreCancel")
    if ticket = invalid then return
    m.libraryGenrePending = invalid
    ticket.node.close = true
end sub

sub LibraryGenresResult(result as Object, data as Object, extra as Dynamic)
    pending = m.libraryGenrePending
    if pending = invalid or type(extra) <> "roAssociativeArray" then return
    if pending.token <> m.libraryToken or extra.token <> pending.token or extra.sequence <> pending.sequence then return
    if pending.sequence <> m.browseDialogSequence or pending.ticket.used = true then return
    if not BrowseContextCurrent(pending.context) then return
    if pending.key <> LibraryGenreKey(LibraryGenreParams()) then return
    if m.top.dialog = invalid or pending.node.wasClosed = true then return
    if not pending.node.isSameNode(m.top.dialog) then return
    m.libraryGenrePending = invalid
    pending.ticket.used = true
    pending.node.close = true
    if result.ok <> true or type(data.genres) <> "roArray" then LibraryGenresFallback() : return
    if m.libraryGenreCache = invalid then m.libraryGenreCache = []
    while m.libraryGenreCache.Count() >= 4
        m.libraryGenreCache.Shift()
    end while
    m.libraryGenreCache.Push({key:pending.key,at:LibraryGenreNow(),genres:data.genres})
    LibraryGenresShow(data.genres)
end sub
