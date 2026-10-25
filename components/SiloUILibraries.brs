sub LibrariesInit()
    m.librariesList = m.top.findNode("librariesList")
    m.librariesRows = m.top.findNode("librariesRows")
    m.librariesTitle = m.top.findNode("librariesTitle")
    m.librariesStatus = m.top.findNode("librariesStatus")
    m.librariesButtons = m.top.findNode("librariesButtons")
    m.librariesTitle.font = SiloUIFont(30,true)
    m.librariesStatus.font = SiloUIFont(18,false)
    m.librariesList.observeField("itemSelected","onLibrariesSelect")
    m.librariesRows.itemSize = [1168,310]
    m.librariesRows.observeField("rowItemSelected","onLibrariesItem")
    BuildPills(m.librariesButtons,"librariesButtons",["Retry","Back"],10,36,16)
end sub

function LibrariesOwner() as Object
    return {provider:m.provider,sourceId:m.sourceId,profileId:m.profileId,generation:m.generation}
end function

function LibrariesCurrent(receipt as Dynamic) as Boolean
    if type(receipt) <> "roAssociativeArray" then return false
    if receipt.token <> m.librariesToken then return false
    owner = LibrariesOwner()
    for each field in ["provider","sourceId","profileId","generation"]
        if receipt.owner[field] <> owner[field] then return false
    end for
    return owner.provider = "silo"
end function

sub LibrariesOpen()
    if m.provider <> "silo" then return
    m.librariesOpeningSelect = false
    m.librariesToken = NumberOr(m.librariesToken,0)+1
    m.librariesOwner = LibrariesOwner()
    m.librariesSelected = invalid
    m.librariesEntries = []
    m.librariesShelves = []
    m.librariesLoading = true
    m.librariesError = false
    m.librariesTitle.text = "Libraries"
    m.librariesStatus.text = "Loading libraries…"
    ShowView("libraries")
    LibrariesPaint()
    SetZone("librariesButtons")
    Api("libraries",{},"libraries_list",{token:m.librariesToken,owner:m.librariesOwner})
end sub

function LibrariesVideo(entries as Dynamic) as Object
    ' Unknown and nonvideo kinds cannot enter the video catalog route.
    groups = [[],[],[]]
    seen = {}
    if type(entries) <> "roArray" then return []
    for each entry in entries
        if type(entry) = "roAssociativeArray"
            id = TextOr(entry.libraryId)
            kind = LCase(TextOr(entry.type))
            group = -1
            if kind = "movie" or kind = "movies" then group = 0
            if kind = "series" or kind = "tv" or kind = "show" or kind = "tvshows" then group = 1
            if kind = "mixed" then group = 2
            if group >= 0 and id <> "" and entry.enabled <> false
                if not seen.DoesExist(id)
                    groups[group].Push(entry)
                    seen[id] = true
                end if
            end if
        end if
    end for
    result = []
    for each group in groups
        for each entry in group
            result.Push(entry)
        end for
    end for
    return result
end function

sub onLibrariesSelect()
    if m.view <> "libraries" then return
    if not LibrariesCurrent({token:m.librariesToken,owner:m.librariesOwner}) then return
    index = NumberOr(m.librariesList.itemSelected,-1)
    if index < 0 or index >= m.librariesEntries.Count() then return
    LibrariesSelect(index)
    m.librariesOpeningSelect = true
end sub

sub LibrariesSelect(index as Integer)
    if index < 0 or index >= m.librariesEntries.Count() then return
    m.librariesOpeningSelect = false
    m.librariesOverviewFocus = index
    m.librariesSelected = m.librariesEntries[index]
    m.librariesTitle.text = m.librariesSelected.title
    ShowView("libraryShelves")
    LibrariesLoadShelves(false)
    SetZone("librariesButtons")
end sub

sub LibrariesLoadShelves(retry as Boolean)
    m.librariesToken = NumberOr(m.librariesToken,0)+1
    m.librariesOwner = LibrariesOwner()
    if not retry
        m.librariesShelves = [{title:"Recently added",sort:"added_at",items:[],state:"new"},{title:"Recently released",sort:"release_date",items:[],state:"new"},{title:"Top rated",sort:"rating_imdb",items:[],state:"new"}]
    end if
    m.librariesPending = 0
    m.librariesFailed = 0
    for index = 0 to m.librariesShelves.Count()-1
        shelf = m.librariesShelves[index]
        if shelf.state <> "ok"
            shelf.state = "loading"
            m.librariesPending = m.librariesPending+1
            receipt = {token:m.librariesToken,owner:m.librariesOwner,libraryId:m.librariesSelected.libraryId,index:index}
            Api("catalog_query",{type:"video",libraryId:receipt.libraryId,sort:shelf.sort,order:"desc",limit:24},"libraries_shelf",receipt)
        end if
    end for
    LibrariesPaint()
end sub

sub LibrariesResult(purpose as String, result as Object, data as Object, receipt as Dynamic)
    if not LibrariesCurrent(receipt) then return
    if purpose = "libraries_list"
        if m.librariesLoading <> true then return
        m.librariesLoading = false
        m.librariesError = result.ok <> true
        m.librariesEntries = LibrariesVideo(data.libraries)
        if m.librariesError then m.librariesEntries = []
        LibrariesPaint()
        if m.view = "libraries" and m.librariesEntries.Count() > 0 then SetZone("librariesList")
        return
    end if
    if m.librariesSelected = invalid then return
    if receipt.libraryId <> m.librariesSelected.libraryId then return
    if receipt.index < 0 or receipt.index >= m.librariesShelves.Count() then return
    shelf = m.librariesShelves[receipt.index]
    if shelf.state <> "loading" then return
    m.librariesPending = m.librariesPending-1
    shelf.state = "failed"
    if result.ok = true and type(data.items) = "roArray"
        shelf.state = "ok"
        shelf.items = []
        for each item in data.items
            if shelf.items.Count() >= 24 then exit for
            shelf.items.Push(item)
        end for
    else
        m.librariesFailed = m.librariesFailed+1
    end if
    ' Publish the bounded batch together so late shelves cannot move focused cards.
    if m.librariesPending = 0 then LibrariesPaint()
end sub

sub LibrariesPaint()
    overview = m.librariesSelected = invalid
    m.librariesList.visible = overview
    m.librariesRows.visible = not overview
    if overview
        content = CreateObject("roSGNode","ContentNode")
        for each entry in m.librariesEntries
            node = content.createChild("ContentNode")
            node.title = entry.title
        end for
        m.librariesList.content = content
        m.librariesStatus.text = ""
        if m.librariesLoading then m.librariesStatus.text = "Loading libraries…"
        if not m.librariesLoading and content.getChildCount() = 0 then m.librariesStatus.text = "No accessible movie or show libraries."
        if m.librariesError then m.librariesStatus.text = "Libraries are unavailable on this server. Retry or use Movies and Shows."
        BuildPills(m.librariesButtons,"librariesButtons",["Retry","Back"],10,36,16)
        return
    end if
    focus = m.librariesRows.rowItemFocused
    focusedShelf = -1
    focusRow = -1
    focusCard = -1
    if type(focus) = "roArray"
        if focus.Count() >= 2
            focusRow = NumberOr(focus[0],-1)
            focusCard = NumberOr(focus[1],-1)
        end if
    end if
    if focusRow >= 0 and focusCard >= 0
        if type(m.librariesVisibleShelves) = "roArray"
            if focusRow < m.librariesVisibleShelves.Count() then focusedShelf = m.librariesVisibleShelves[focusRow]
        end if
    end if
    content = CreateObject("roSGNode","ContentNode")
    sizes = []:cards = []:spaces = []
    m.librariesVisibleShelves = []
    for index = 0 to m.librariesShelves.Count()-1
        shelf = m.librariesShelves[index]
        if shelf.items.Count() > 0
            row = content.createChild("ContentNode")
            row.title = shelf.title
            for each item in shelf.items
                row.appendChild(ItemNode(item))
            end for
            m.librariesVisibleShelves.Push(index)
            sizes.Push(310):cards.Push([160,240]):spaces.Push([24,0])
        end if
    end for
    m.librariesRows.rowHeights = sizes
    m.librariesRows.rowItemSize = cards
    m.librariesRows.rowItemSpacing = spaces
    m.librariesRows.content = content
    if focusedShelf >= 0
        for rowIndex = 0 to m.librariesVisibleShelves.Count()-1
            if m.librariesVisibleShelves[rowIndex] = focusedShelf
                cardIndex = focusCard
                lastCard = content.getChild(rowIndex).getChildCount()-1
                if cardIndex > lastCard then cardIndex = lastCard
                if cardIndex < 0 then cardIndex = 0
                m.librariesRows.jumpToRowItem = [rowIndex,cardIndex]
                exit for
            end if
        end for
    end if
    m.librariesStatus.text = ""
    if m.librariesPending > 0 then m.librariesStatus.text = "Loading shelves…"
    if m.librariesPending = 0 and content.getChildCount() = 0 then m.librariesStatus.text = "Nothing here yet. Browse all titles or go Back."
    if m.librariesFailed > 0 then m.librariesStatus.text = "Some shelves could not load. Retry to load missing shelves."
    if m.librariesFailed = 3 then m.librariesStatus.text = "Shelves could not load. Retry or go Back."
    selected = m.pillGroups.librariesButtons.index
    BuildPills(m.librariesButtons,"librariesButtons",["Browse all","Retry","Back"],10,36,16)
    m.pillGroups.librariesButtons.index = selected
    PaintPills("librariesButtons",m.zone = "librariesButtons")
end sub

sub onLibrariesItem()
    if m.view <> "libraryShelves" then return
    if not LibrariesCurrent({token:m.librariesToken,owner:m.librariesOwner}) then return
    position = m.librariesRows.rowItemSelected
    if type(position) <> "roArray" then return
    if position.Count() < 2 then return
    rowIndex = NumberOr(position[0],-1)
    cardIndex = NumberOr(position[1],-1)
    if rowIndex < 0 or cardIndex < 0 then return
    if m.librariesRows.content = invalid then return
    if rowIndex >= m.librariesRows.content.getChildCount() then return
    row = m.librariesRows.content.getChild(rowIndex)
    if row = invalid then return
    if cardIndex >= row.getChildCount() then return
    node = row.getChild(cardIndex)
    if node <> invalid then DetailOpen(node.item)
end sub

sub LibrariesBrowseAll()
    m.history.Push({view:"libraryShelves",zone:"librariesButtons"})
    LibraryResetFilters()
    m.libraryId = m.librariesSelected.libraryId
    m.libraryCollectionTitle = m.librariesSelected.title
    m.libraryType = "video"
    ShowView("library")
    LibraryQuery(true)
    SetZone("libraryTabs")
end sub

sub LibrariesBack()
    if m.view = "libraryShelves"
        m.librariesToken = NumberOr(m.librariesToken,0)+1
        m.librariesSelected = invalid
        m.librariesTitle.text = "Libraries"
        ShowView("libraries")
        LibrariesPaint()
        m.librariesList.jumpToItem = m.librariesOverviewFocus
        if m.librariesEntries.Count() > 0 then SetZone("librariesList") else SetZone("librariesButtons")
    else
        NavSelect(0)
    end if
end sub

function LibrariesKey(key as String) as Boolean
    if key = "OK" and m.librariesOpeningSelect = true then return true
    if key = "back" then LibrariesBack() : return true
    if m.zone = "librariesButtons"
        if key = "left" then PillMove("librariesButtons",-1) : return true
        if key = "right" then PillMove("librariesButtons",1) : return true
        if key = "up" then SetZone("nav") : return true
        if key = "down"
            if m.view = "libraries" and m.librariesEntries.Count() > 0 then SetZone("librariesList")
            if m.view = "libraryShelves" and m.librariesRows.content.getChildCount() > 0 then SetZone("librariesRows")
            return true
        end if
        if key = "OK"
            index = m.pillGroups.librariesButtons.index
            if m.view = "libraries"
                if index = 0 then LibrariesOpen() else LibrariesBack()
            else
                if index = 0 then LibrariesBrowseAll()
                if index = 1 and m.librariesPending = 0 then LibrariesLoadShelves(true)
                if index = 2 then LibrariesBack()
            end if
            return true
        end if
    end if
    if key = "up" then SetZone("librariesButtons") : return true
    return false
end function

sub LibrariesNavigation()
    m.navItems = ["Home","Search","Movies","Shows","Audiobooks","Books","Settings"]
    if m.provider = "silo"
        m.navItems = ["Home","Search","Movies","Shows","Libraries","Audiobooks","Books","Settings"]
    end if
    BuildPills(m.navPills,"nav",m.navItems,10)
    CenterGroup(m.navPills,1280)
    SiloUINavigationBuild()
end sub
