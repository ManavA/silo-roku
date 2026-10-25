' Text-only reader; size changes stay local and never write progress.
sub SiloUIEbookInit()
    m.ebookToken = 0
    m.ebookTitle = m.top.findNode("ebookTitle")
    m.ebookBody = m.top.findNode("ebookBody")
    m.ebookStatus = m.top.findNode("ebookStatus")
    m.ebookTitle.font = SiloUIFont(30,true)
    m.ebookSize = 1
    m.ebookBody.font = SiloUIFont(28,false)
    m.ebookStatus.font = SiloUIFont(20,false)
end sub

sub SiloUIEbookOpen(contentId as String, fileId as String, title as String)
    if m.provider <> "silo" or contentId = "" or fileId = "" then return
    if m.view = "ebook" then return
    m.ebookSession = NumberOr(m.ebookSession,0)+1
    if m.ebookSize = invalid then m.ebookSize = 1
    sizes = [24,28,32]
    m.ebookBody.font = SiloUIFont(sizes[m.ebookSize],false)
    m.ebookReturn = {view:m.view,zone:m.zone}
    if m.view = "ebookBrowse" then m.ebookReturn.zone = "ebookBrowseGrid"
    m.ebookScope = HomeProgressScope()
    m.ebookContentId = contentId
    m.ebookFileId = fileId
    m.ebookRevision = ""
    m.ebookPage = invalid
    m.ebookScreens = []
    m.ebookTitle.text = Left(title,160)
    m.ebookBody.text = ""
    ShowView("ebook")
    SetZone("ebook")
    SiloUIEbookRequest("ebook_reader_capability",0,0)
end sub

sub SiloUIEbookRequest(purpose as String, pageIndex as Integer, screenIndex as Integer)
    if m.view <> "ebook" or m.ebookScope <> HomeProgressScope() then return
    m.ebookToken = NumberOr(m.ebookToken,0)+1
    m.ebookPending = {token:m.ebookToken,scope:m.ebookScope,pageIndex:pageIndex,screenIndex:screenIndex,purpose:purpose}
    m.ebookError = false
    m.ebookStatus.text = "Loading…   Back: close"
    if purpose = "ebook_reader_capability"
        Api("ebook_capability",{},purpose,m.ebookPending)
    else
        Api("ebook_text_page",{contentId:m.ebookContentId,fileId:m.ebookFileId,pageIndex:pageIndex},purpose,m.ebookPending)
    end if
end sub

sub SiloUIEbookResult(purpose as String, result as Object, data as Object, extra as Dynamic)
    if m.view <> "ebook" or m.ebookScope <> HomeProgressScope() then return
    if type(extra) <> "roAssociativeArray" then return
    if extra.token <> m.ebookToken or extra.scope <> m.ebookScope then return
    if result.ok <> true
        m.ebookError = true
        m.ebookStatus.text = "Page unavailable. OK: Retry   Left/Right: turn   Back: close"
        return
    end if
    if purpose = "ebook_reader_capability"
        if data.textPages <> true
            m.ebookError = true
            m.ebookStatus.text = "Text reader unavailable. OK: Retry   Back: close"
            return
        end if
        SiloUIEbookRequest("ebook_reader_page",0,0)
        return
    end if
    if m.ebookRevision <> "" and m.ebookRevision <> data.revision
        m.ebookError = true
        m.ebookStatus.text = "Book changed. Back: close and reopen."
        return
    end if
    m.ebookRevision = data.revision
    m.ebookPage = data
    layout = SiloUIEbookLayout(data.text,m.ebookSize)
    m.ebookScreens = layout.screens
    m.ebookOffsets = layout.offsets
    m.ebookScreen = extra.screenIndex
    if m.ebookScreen < 0 then m.ebookScreen = m.ebookScreens.Count()-1
    m.ebookPending = invalid
    SiloUIEbookPaint()
end sub

' Explicit conservative line breaks keep every character reachable without
' depending on device font measurement. One chunk (max 16 KiB) is retained.
function SiloUIEbookScreens(body as String) as Object
    return SiloUIEbookLayout(body,1).screens
end function

function SiloUIEbookLayout(body as String, size as Integer, anchor = -1 as Integer) as Object
    columns = [40,34,30]
    rows = [11,9,8]
    screens = []
    offsets = [0]
    screen = ""
    lines = 0
    column = 0
    for index = 1 to Len(body)
        if index-1 = anchor and screen <> ""
            screens.Push(screen)
            offsets.Push(index-1)
            screen = ""
            lines = 0
            column = 0
        end if
        character = Mid(body,index,1)
        screen = screen+character
        column = column+1
        if character = Chr(10) or (character = " " and column >= columns[size]-8) or column >= columns[size]
            if character <> Chr(10) then screen = screen+Chr(10)
            column = 0
            lines = lines+1
        end if
        if lines >= rows[size]
            screens.Push(screen)
            offsets.Push(index)
            screen = ""
            lines = 0
        end if
    end for
    if screen <> "" then screens.Push(screen)
    if screens.Count() = 0 then screens.Push("")
    return {screens:screens,offsets:offsets}
end function

sub SiloUIEbookPaint()
    m.ebookBody.text = m.ebookScreens[m.ebookScreen]
    m.ebookStatus.text = "Page "+(m.ebookPage.pageIndex+1).ToStr()+"/"+m.ebookPage.totalPages.ToStr()+" · screen "+(m.ebookScreen+1).ToStr()+"/"+m.ebookScreens.Count().ToStr()+"   Left/Right: turn   Options: reader menu   Back: close"
end sub

sub SiloUIEbookRelease()
    m.ebookSession = NumberOr(m.ebookSession,0)+1
    m.ebookOptions = invalid
    if m.ebookPageDialog <> invalid then m.ebookPageDialog.close = true
    m.ebookPageDialog = invalid
    m.ebookJump = invalid
    m.ebookToken = NumberOr(m.ebookToken,0)+1
    m.ebookPending = invalid
    m.ebookPage = invalid
    m.ebookScreens = []
    m.ebookBody.text = ""
    m.ebookTitle.text = ""
    m.ebookStatus.text = ""
    m.ebookContentId = ""
    m.ebookFileId = ""
end sub

function SiloUIEbookKey(key as String) as Boolean
    if m.ebookScope <> HomeProgressScope() then SiloUIEbookRelease() : return true
    if key = "options" then SiloUIEbookOptions() : return true
    if key = "back"
        prior = m.ebookReturn
        SiloUIEbookRelease()
        ShowView(prior.view)
        if prior.view = "ebookBrowse" and m.ebookBrowseScope = HomeProgressScope()
            m.ebookGrid.jumpToItem = m.ebookBrowseSelectedIndex
            m.ebookBrowseStatus.text = ""
        end if
        SetZone(prior.zone)
        return true
    end if
    if key = "OK" and m.ebookError = true and m.ebookPending <> invalid
        pending = m.ebookPending
        SiloUIEbookRequest(pending.purpose,pending.pageIndex,pending.screenIndex)
        return true
    end if
    if key <> "left" and key <> "right" then return true
    if m.ebookPage = invalid then return true
    ' Page turns during fetch are relative to the displayed page. Reversing
    ' direction invalidates the pending result and preserves current text.
    m.ebookToken = m.ebookToken+1
    m.ebookPending = invalid
    m.ebookError = false
    delta = 1
    if key = "left" then delta = -1
    target = m.ebookScreen+delta
    if target >= 0 and target < m.ebookScreens.Count()
        m.ebookScreen = target
        SiloUIEbookPaint()
    else
        pageIndex = m.ebookPage.nextPage
        screenIndex = 0
        if key = "left" then pageIndex = m.ebookPage.previousPage : screenIndex = -1
        if pageIndex >= 0
            SiloUIEbookRequest("ebook_reader_page",pageIndex,screenIndex)
        else
            SiloUIEbookPaint()
        end if
    end if
    return true
end function

sub SiloUIEbookOptions()
    if m.view <> "ebook" or m.ebookScope <> HomeProgressScope() then return
    m.ebookOptions = {session:m.ebookSession,scope:m.ebookScope}
    BrowsePagedChoices("Reader options",["Text size","Go to page"],"onSiloUIEbookOption")
end sub

function SiloUIEbookOptionCurrent() as Boolean
    ticket = m.ebookOptions
    if ticket = invalid or m.view <> "ebook" then return false
    return ticket.session = m.ebookSession and ticket.scope = HomeProgressScope() and ticket.scope = m.ebookScope
end function

sub onSiloUIEbookOption(event as Object)
    index = BrowseChoiceIndex(event)
    if not SiloUIEbookOptionCurrent() then return
    if index = 0
        BrowsePagedChoices("Reader text size",["Small","Medium","Large"],"onSiloUIEbookSize")
    else if index = 1 and m.ebookPage <> invalid
        SiloUIEbookPagePrompt((m.ebookPage.pageIndex+1).ToStr(),false)
    end if
end sub

sub SiloUIEbookPagePrompt(value as String, validation as Boolean)
    if m.ebookPageDialog <> invalid then m.ebookPageDialog.close = true
    dialog = CreateObject("roSGNode", "KeyboardDialog")
    prefix = "Go to page"
    if validation then prefix = "Enter a whole page number"
    dialog.title = prefix+" (1–"+m.ebookPage.totalPages.ToStr()+")"
    dialog.text = value
    dialog.buttons = ["Go", "Cancel"]
    dialog.observeField("buttonSelected","onSiloUIEbookPage")
    dialog.observeField("wasClosed","onSiloUIEbookPageClosed")
    m.ebookJump = {session:m.ebookSession,scope:m.ebookScope}
    m.ebookPageDialog = dialog
    m.top.dialog = dialog
end sub

function SiloUIEbookJumpCurrent(event as Object) as Boolean
    if m.ebookJump = invalid or m.ebookPageDialog = invalid then return false
    if not event.getRoSGNode().IsSameNode(m.ebookPageDialog) then return false
    if m.view <> "ebook" or m.ebookPage = invalid then return false
    return m.ebookJump.session = m.ebookSession and m.ebookJump.scope = m.ebookScope and m.ebookScope = HomeProgressScope()
end function

sub onSiloUIEbookPageClosed(event as Object)
    if not SiloUIEbookJumpCurrent(event) then return
    m.ebookPageDialog = invalid
    m.ebookJump = invalid
end sub

sub onSiloUIEbookPage(event as Object)
    if not SiloUIEbookJumpCurrent(event) then return
    dialog = m.ebookPageDialog
    if dialog.buttonSelected = 0
        value = dialog.text.Trim()
        valid = Len(value) > 0 and Len(value) <= 10
        for position = 1 to Len(value)
            character = Mid(value,position,1)
            if character < "0" or character > "9" then valid = false
        end for
        target = Val(value)
        if not valid or target < 1 or target > m.ebookPage.totalPages
            SiloUIEbookPagePrompt(dialog.text,true)
            return
        end if
    end if
    m.ebookPageDialog = invalid
    m.ebookJump = invalid
    dialog.close = true
    if dialog.buttonSelected <> 0 then return
    if target-1 = m.ebookPage.pageIndex
        m.ebookToken = m.ebookToken+1
        m.ebookPending = invalid
        m.ebookError = false
        SiloUIEbookPaint()
        return
    end if
    SiloUIEbookRequest("ebook_reader_page",target-1,0)
end sub

sub onSiloUIEbookSize(event as Object)
    index = BrowseChoiceIndex(event)
    if index < 0 or index > 2 or not SiloUIEbookOptionCurrent() then return
    m.ebookOptions = invalid
    m.ebookSize = index
    sizes = [24,28,32]
    m.ebookBody.font = SiloUIFont(sizes[index],false)
    if m.ebookPage = invalid then return
    ' Force a screen boundary at the displayed original-text offset. Prefix
    ' screens remain available to Left; inserted line breaks never count.
    anchor = m.ebookOffsets[m.ebookScreen]
    layout = SiloUIEbookLayout(m.ebookPage.text,index,anchor)
    m.ebookScreens = layout.screens
    m.ebookOffsets = layout.offsets
    for screenIndex = 0 to m.ebookScreens.Count()-1
        if m.ebookOffsets[screenIndex] = anchor then m.ebookScreen = screenIndex
    end for
    status = m.ebookStatus.text
    SiloUIEbookPaint()
    if m.ebookPending <> invalid or m.ebookError = true then m.ebookStatus.text = status
end sub
