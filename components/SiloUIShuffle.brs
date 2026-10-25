' One server-owned shuffle with one in-flight mutation and no automatic retry.
sub ShuffleBegin(kind as String, id as String)
    if m.provider <> "silo" or id = "" then Toast("Choose a library, collection or season first.") : return
    if m.shuffle <> invalid or m.shuffleBusy = true then Toast("Stop the existing shuffle first.") : return
    m.shuffleEpoch = NumberOr(m.shuffleEpoch,0) + 1
    m.shuffleOwner = SiloUIOwner()
    m.shufflePending = {kind:kind,scopeId:id}
    m.shuffleStartOwner = ShuffleUiOwner()
    m.shuffleBusy = true
    ApiOwned("shuffle_capabilities",{},"shuffle_caps",{token:m.shuffleEpoch,ui:ShuffleUiOwner()},m.shuffleOwner)
end sub

sub ShuffleResult(purpose as String, result as Object, data as Object, extra as Dynamic)
    if type(extra) <> "roAssociativeArray" then return
    if extra.token <> m.shuffleEpoch then return
    m.shuffleBusy = false
    uiCurrent = ShuffleUiCurrent(extra.ui)
    if purpose = "shuffle_caps" or purpose = "shuffle_start"
        if type(m.shuffleStartOwner) = "roAssociativeArray"
            if not ShuffleUiCurrent(m.shuffleStartOwner) then return
        end if
    end if
    if result.ok <> true
        if uiCurrent then Toast("Shuffle request was not confirmed. Open controls to retry.")
        return
    end if
    if purpose = "shuffle_caps"
        if not uiCurrent then return
        allowed = false
        if data.allowed = true and type(data.kinds) = "roArray"
            for each kind in data.kinds
                if kind = m.shufflePending.kind then allowed = true
            end for
        end if
        if not allowed then Toast("This server does not support that shuffle scope.") : return
        m.shuffleBusy = true
        ApiOwned("shuffle_start",m.shufflePending,"shuffle_start",{token:m.shuffleEpoch,ui:ShuffleUiOwner()},m.shuffleOwner)
    else if purpose = "shuffle_stop"
        m.shuffle = invalid
        if uiCurrent then m.playNext = invalid
        if uiCurrent then Toast("Shuffle stopped.")
    else
        if m.shuffle <> invalid
            if data.shuffleId <> m.shuffle.shuffleId
                if uiCurrent then Toast("Shuffle identity changed.")
                return
            end if
        end if
        m.shuffle = data
        if result.sessionRevision <> invalid then m.shuffleOwner["sessionRevision"] = result.sessionRevision
        if not uiCurrent then return
        if m.view = "player" and m.playItem.itemId = data.current.itemId then m.playNext = data.next
        if purpose = "shuffle_advance" and extra.play = true
            ShufflePlayCurrent(extra.automatic = true)
        else
            ShuffleDialog()
        end if
    end if
end sub

function ShuffleUiOwner() as Object
    return BrowseCaptureContext()
end function

function ShuffleUiCurrent(owner as Dynamic) as Boolean
    return BrowseContextCurrent(owner)
end function

sub ShuffleDialog()
    if m.shuffle = invalid then return
    dialog = CreateObject("roSGNode","Dialog")
    dialog.title = "Shuffle: " + TextOr(m.shuffle.scope.title)
    dialog.message = "Current: " + TextOr(m.shuffle.current.title) + Chr(10) + "Next: " + TextOr(m.shuffle.next.title)
    dialog.buttons = ["Play current pick", "Play next pick", "Pick another next", "Stop shuffle"]
    dialog.observeField("buttonSelected","onShuffleChoice")
    dialog.observeField("wasClosed","onShuffleClosed")
    m.shuffleDialog = dialog
    m.shuffleDialogOwner = ShuffleUiOwner()
    m.shuffleDialogEpoch = m.shuffleEpoch
    m.top.dialog = dialog
end sub

sub onShuffleClosed(event = invalid as Dynamic)
    if event = invalid then return
    if m.shuffleDialog = invalid then return
    if not m.shuffleDialog.isSameNode(event.getRoSGNode()) then return
    if m.top <> invalid
        if m.top.dialog = invalid then return
        if not m.shuffleDialog.isSameNode(m.top.dialog) then return
    end if
    m.shuffleDialog = invalid
    if not ShuffleUiCurrent(m.shuffleDialogOwner) or m.shuffleDialogEpoch <> m.shuffleEpoch then return
    if m.view = "player" then PlayerPlaybackFocus()
end sub

sub onShuffleChoice(event = invalid as Dynamic)
    if event = invalid then return
    if m.shuffleDialog = invalid or m.shuffle = invalid then return
    if not m.shuffleDialog.isSameNode(event.getRoSGNode()) then return
    if m.top <> invalid
        if m.top.dialog = invalid then return
        if not m.shuffleDialog.isSameNode(m.top.dialog) then return
    end if
    if not ShuffleUiCurrent(m.shuffleDialogOwner) or m.shuffleDialogEpoch <> m.shuffleEpoch
        m.shuffleDialog.close = true
        m.shuffleDialog = invalid
        return
    end if
    index = m.shuffleDialog.buttonSelected
    dialog = m.shuffleDialog
    m.shuffleDialog = invalid
    dialog.close = true
    if m.view = "player" then PlayerPlaybackFocus()
    if m.shuffleBusy = true then Toast("Wait for the current shuffle request.") : return
    if index = 0 then ShufflePlayCurrent(false)
    if index = 1 then ShuffleAdvance(false)
    if index = 2
        m.shuffleBusy = true
        ApiOwned("shuffle_skip",{shuffleId:m.shuffle.shuffleId,itemId:m.shuffle.next.itemId},"shuffle_skip",{token:m.shuffleEpoch,ui:ShuffleUiOwner()},m.shuffleOwner)
    end if
    if index = 3 then ShuffleStop()
end sub

sub ShuffleAdvance(automatic as Boolean)
    if m.shuffle = invalid or m.shuffleBusy = true then return
    m.shuffleBusy = true
    ApiOwned("shuffle_advance",{shuffleId:m.shuffle.shuffleId,itemId:m.shuffle.current.itemId},"shuffle_advance",{token:m.shuffleEpoch,play:true,automatic:automatic,ui:ShuffleUiOwner()},m.shuffleOwner)
end sub

sub ShufflePlayCurrent(automatic as Boolean)
    if m.shuffle = invalid then return
    item = m.shuffle.current
    m.shuffleAdvancing = true
    if PlayerDeferCompatNext(item,automatic) then m.shuffleAdvancing = false : return
    if m.view = "player"
        PlayerClose(true,false)
    end if
    if automatic then m.bingeAdvances = NumberOr(m.bingeAdvances,0) + 1 else m.bingeAdvances = 0
    m.bingeAdvancing = true
    PlayItem(item,0)
    m.shuffleAdvancing = false
end sub

sub ShuffleStop()
    if m.shuffle = invalid or m.shuffleBusy = true then return
    m.shuffleBusy = true
    ApiOwned("shuffle_stop",{shuffleId:m.shuffle.shuffleId},"shuffle_stop",{token:m.shuffleEpoch,ui:ShuffleUiOwner()},m.shuffleOwner)
end sub

' Scope transitions invalidate pending UI results. Stop only with the captured
' source/profile/revision; the worker refuses changed authentication ownership.
sub ShuffleLeave()
    if m.shuffleDialog <> invalid then m.shuffleDialog.close = true
    m.shuffleDialog = invalid
    if m.shuffle <> invalid
        ApiOwned("shuffle_stop",{shuffleId:m.shuffle.shuffleId},"shuffle_cleanup",invalid,m.shuffleOwner)
    end if
    m.shuffle = invalid
    m.shuffleBusy = false
    m.shuffleEpoch = NumberOr(m.shuffleEpoch,0) + 1
end sub

function ShuffleAllocationResult(entry as Object, result as Object) as Boolean
    if entry.purpose <> "shuffle_start" then return false
    current = entry.generation = m.generation
    if type(entry.extra) = "roAssociativeArray" then current = current and entry.extra.token = m.shuffleEpoch
    if type(m.shuffleStartOwner) = "roAssociativeArray" then current = current and ShuffleUiCurrent(m.shuffleStartOwner)
    if current then return false
    if type(entry.extra) = "roAssociativeArray"
        if entry.extra.token = m.shuffleEpoch
            m.shuffleBusy = false
            m.shuffleEpoch++
        end if
    end if
    if result.ok = true and type(result.data) = "roAssociativeArray"
        owner = entry.owner
        if result.sessionRevision <> invalid then owner["sessionRevision"] = result.sessionRevision
        ApiOwned("shuffle_stop",{shuffleId:result.data.shuffleId},"shuffle_cleanup",invalid,owner)
    end if
    return true
end function
