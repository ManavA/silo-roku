' Silo EPUB browser, gated by server text-reader capability.
sub SiloUIEbookBrowseInit()
    m.ebookGrid = m.top.findNode("ebookBrowseGrid")
    m.ebookGrid.observeField("itemSelected","onSiloUIEbookGridSelect")
    m.ebookGrid.observeField("itemFocused","onSiloUIEbookGridFocus")
    m.ebookBrowseStatus = m.top.findNode("ebookBrowseStatus")
    m.ebookBrowseStatus.font = SiloUIFont(20,false)
    m.ebookBrowseTitle = m.top.findNode("ebookBrowseTitle")
    m.ebookBrowseTitle.font = SiloUIFont(30,true)
    BuildPills(m.top.findNode("ebookBrowseButtons"),"ebookBrowseButtons",["Library","Retry","Next page"],10,36,16)
    m.ebookBrowseToken = 0
end sub

sub SiloUIEbookBrowse()
    if m.view <> "ebookBrowse" then m.ebookBrowseReturn = {view:m.view,zone:m.zone}
    m.ebookBrowseTitle.text = "Books"
    ShowView("ebookBrowse")
    SetZone("ebookBrowseButtons")
    m.ebookBrowseToken = NumberOr(m.ebookBrowseToken,0)+1
    m.ebookBrowseScope = HomeProgressScope()
    m.ebookBrowseLibrary = ""
    m.ebookBrowseLibraries = []
    m.ebookBrowsePages = 0
    m.ebookBrowseCursors = []
    m.ebookBrowseCursor = ""
    m.ebookBrowseMore = false
    m.ebookBrowseError = false
    m.ebookBrowseLoading = false
    m.pillGroups.ebookBrowseButtons.index = 1
    PaintPills("ebookBrowseButtons",true)
    m.ebookGrid.content = CreateObject("roSGNode","ContentNode")
    if m.provider <> "silo"
        m.ebookBrowseStatus.text = "Books require a Silo source."
        return
    end if
    m.ebookBrowseStatus.text = "Checking text reader…"
    m.ebookBrowseLoading = true
    Api("ebook_capability",{},"ebook_browse_capability",m.ebookBrowseToken)
end sub

sub SiloUIEbookBrowseResult(purpose as String, result as Object, data as Object, extra as Dynamic)
    if purpose = "ebook_browse_capability" or purpose = "ebook_browse_detail" or purpose = "ebook_browse_libraries" or purpose = "ebook_browse_catalog"
        if extra <> m.ebookBrowseToken or m.ebookBrowseScope <> HomeProgressScope() or m.view <> "ebookBrowse" then return
        m.ebookBrowseLoading = false
        m.ebookBrowseError = result.ok <> true
        m.ebookBrowseFailedPurpose = purpose
        if result.ok <> true
            m.ebookBrowseStatus.text = "Books are unavailable. Select Retry to try again."
            if purpose = "ebook_browse_capability" then m.ebookBrowseStatus.text = "Text reader unavailable on this Silo server. Check server support, then Retry or press Back."
            return
        end if
        if purpose = "ebook_browse_capability"
            if data.textPages <> true
                m.ebookBrowseError = true
                m.ebookBrowseStatus.text = "Text reader unavailable on this Silo server. Check server support, then Retry or press Back."
                return
            end if
            m.ebookBrowseLoading = true
            m.ebookBrowseStatus.text = "Loading EPUB libraries…"
            m.ebookBrowseToken = m.ebookBrowseToken+1
            Api("ebook_libraries",{},"ebook_browse_libraries",m.ebookBrowseToken)
            return
        end if
        if purpose = "ebook_browse_detail"
            if data.contentId <> m.ebookBrowseSelectedId then return
            SiloUIEbookOpen(data.contentId,data.fileId,data.title)
            return
        end if
        if purpose = "ebook_browse_libraries"
            m.ebookBrowseLibraries = data.entries
            if m.ebookBrowseLibraries.Count() = 0
                m.ebookBrowseStatus.text = "No ebook libraries are available for this profile."
                m.pillGroups.ebookBrowseButtons.index = 1
                PaintPills("ebookBrowseButtons",m.zone = "ebookBrowseButtons")
                return
            end if
            if m.ebookBrowseLibraries.Count() > 1
                m.ebookBrowseStatus.text = "Choose an ebook library."
                SiloUIEbookBrowseKey("options")
            else
                SiloUIEbookBrowseLibrary(0)
            end if
            return
        end if
        m.ebookBrowsePages = m.ebookBrowsePages+1
        for each entry in data.entries
            if m.ebookGrid.content.getChildCount() >= 300 then exit for
            found = false
            for i = 0 to m.ebookGrid.content.getChildCount()-1
                if m.ebookGrid.content.getChild(i).item.itemId = entry.id then found = true : exit for
            end for
            if not found then m.ebookGrid.content.appendChild(ItemNode(entry.item))
        end for
        cursor = TextOr(data.nextCursor)
        repeated = false
        for each seen in m.ebookBrowseCursors
            if seen = cursor then repeated = true
        end for
        m.ebookBrowseCursor = cursor
        m.ebookBrowseMore = cursor <> "" and not repeated and m.ebookBrowsePages < 5 and m.ebookGrid.content.getChildCount() < 300
        m.ebookBrowseStatus.text = ""
        if m.ebookGrid.content.getChildCount() = 0 then m.ebookBrowseStatus.text = "No books in this library."

        return
    end if
end sub

sub SiloUIEbookBrowseRetire()
    m.ebookBrowseToken = NumberOr(m.ebookBrowseToken,0)+1
    m.ebookBrowseLoading = false
    if m.ebookGrid <> invalid then m.ebookGrid.content = invalid
end sub

sub SiloUIEbookBrowseLibrary(index as Integer)
    if m.view <> "ebookBrowse" or m.ebookBrowseScope <> HomeProgressScope() then return
    if index < 0 or index >= m.ebookBrowseLibraries.Count() then return
    m.ebookBrowseLibraryIndex = index
    selected = m.ebookBrowseLibraries[index]
    m.ebookBrowseLibrary = selected.id
    m.ebookBrowseTitle.text = "Books · "+selected.title
    m.ebookBrowseToken = m.ebookBrowseToken+1
    m.ebookBrowsePages = 0
    m.ebookBrowseCursors = []
    m.ebookBrowseCursor = ""
    m.ebookBrowseMore = false
    m.ebookBrowseLoading = false
    m.ebookGrid.content = CreateObject("roSGNode","ContentNode")
    SiloUIEbookBrowsePage()
end sub

sub SiloUIEbookBrowsePage()
    if m.view <> "ebookBrowse" or m.ebookBrowseScope <> HomeProgressScope() then return
    if m.ebookBrowseLoading = true or m.ebookBrowseLibrary = "" then return
    if m.ebookBrowsePages >= 5 or m.ebookGrid.content.getChildCount() >= 300 then return
    m.ebookBrowseError = false
    m.ebookBrowseLoading = true
    m.ebookBrowseToken = m.ebookBrowseToken+1
    m.ebookBrowseStatus.text = "Loading books…"
    params = {libraryId:m.ebookBrowseLibrary}
    if m.ebookBrowseCursor <> ""
        params.cursor = m.ebookBrowseCursor
        m.ebookBrowseCursors.Push(m.ebookBrowseCursor)
    end if
    Api("ebook_catalog",params,"ebook_browse_catalog",m.ebookBrowseToken)
end sub

sub onSiloUIEbookGridFocus()
    if m.view <> "ebookBrowse" or m.ebookBrowseScope <> HomeProgressScope() then return
    if m.ebookGrid.content = invalid then return
    if m.ebookBrowseMore and m.ebookGrid.itemFocused >= m.ebookGrid.content.getChildCount()-14 then SiloUIEbookBrowsePage()
end sub

sub onSiloUIEbookGridSelect()
    if m.view <> "ebookBrowse" or m.ebookBrowseScope <> HomeProgressScope() then return
    if m.ebookGrid.content = invalid then return
    node = m.ebookGrid.content.getChild(m.ebookGrid.itemSelected)
    if node = invalid or m.ebookBrowseLoading = true then return
    m.ebookBrowseSelectedIndex = m.ebookGrid.itemSelected
    m.ebookBrowseSelectedId = node.item.itemId
    m.ebookBrowseToken = m.ebookBrowseToken+1
    m.ebookBrowseLoading = true
    m.ebookBrowseStatus.text = "Opening EPUB…"
    Api("ebook_detail",{contentId:node.item.itemId},"ebook_browse_detail",m.ebookBrowseToken)
end sub

function SiloUIEbookBrowseKey(key as String) as Boolean
    if m.ebookBrowseScope <> HomeProgressScope() then return true
    if key = "back"
        prior = m.ebookBrowseReturn
        ShowView(prior.view)
        SetZone(prior.zone)
        return true
    end if
    if key = "options"
        if m.ebookBrowseLibraries.Count() = 0 then return true
        labels = []
        for each library in m.ebookBrowseLibraries
            labels.Push(library.title)
        end for
        m.ebookBrowseChoiceToken = m.ebookBrowseToken
        BrowsePagedChoices("EPUB library",labels,"onSiloUIEbookChoice")
        return true
    end if
    if m.zone = "ebookBrowseButtons"
        if key = "left" then return PillMove("ebookBrowseButtons",-1)
        if key = "right" then return PillMove("ebookBrowseButtons",1)
        if key = "up" then SetZone("nav") : return true
        if key = "down"
            if m.ebookGrid.content.getChildCount() > 0 then SetZone("ebookBrowseGrid")
            return true
        end if
        if key = "OK"
            if m.pillGroups.ebookBrowseButtons.index = 0
                SiloUIEbookBrowseKey("options")
            else if m.ebookBrowseLoading <> true
                if m.pillGroups.ebookBrowseButtons.index = 1
                    if m.ebookBrowseLibrary = ""
                        SiloUIEbookBrowse()
                    else if m.ebookBrowseError = true
                        if m.ebookBrowseFailedPurpose = "ebook_browse_detail"
                            m.ebookBrowseToken = m.ebookBrowseToken+1
                            m.ebookBrowseLoading = true
                            Api("ebook_detail",{contentId:m.ebookBrowseSelectedId},"ebook_browse_detail",m.ebookBrowseToken)
                        else
                            SiloUIEbookBrowsePage()
                        end if
                    else
                        SiloUIEbookBrowseLibrary(m.ebookBrowseLibraryIndex)
                    end if
                else if m.ebookBrowseMore
                    SiloUIEbookBrowsePage()
                end if
            end if
            return true
        end if
    end if
    if m.zone = "ebookBrowseGrid" and key = "up" then SetZone("ebookBrowseButtons") : return true
    return false
end function

sub onSiloUIEbookChoice(event as Object)
    index = BrowseChoiceIndex(event)
    if m.view <> "ebookBrowse" or m.ebookBrowseScope <> HomeProgressScope() or m.ebookBrowseChoiceToken <> m.ebookBrowseToken then return
    SiloUIEbookBrowseLibrary(index)
end sub
