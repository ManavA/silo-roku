sub HomeSectionsOpen(rowId = "" as String)
    if m.provider <> "silo" then return
    if m.homeSections <> invalid
        if m.homeSections.busy = true and HomeSectionsSameOwner(m.homeSections.owner,SiloUIOwner()) then Toast("Wait for the Home layout request.") : return
    end if
    m.homeSectionsSerial = NumberOr(m.homeSectionsSerial,0) + 1
    m.homeSections = {serial:m.homeSectionsSerial,owner:SiloUIOwner(),context:BrowseCaptureContext(),busy:false,rows:[],selected:rowId}
    HomeSectionsRead(invalid)
end sub

function HomeSectionsSameOwner(a as Object, b as Object) as Boolean
    for each key in ["provider","sourceId","profileId","generation"]
        if a[key] <> b[key] then return false
    end for
    return true
end function

function HomeSectionsCurrent(extra as Dynamic) as Boolean
    state = m.homeSections
    if state = invalid or type(extra) <> "roAssociativeArray" then return false
    if extra.serial <> state.serial then return false
    owner = SiloUIOwner()
    for each key in ["provider","sourceId","profileId","generation"]
        if state.owner[key] <> owner[key] then return false
    end for
    return BrowseContextCurrent(state.context)
end function

sub HomeSectionsRead(intent as Dynamic)
    state = m.homeSections
    state.busy = true
    state.intent = intent
    state.stage = "read"
    extra = {serial:state.serial}
    ApiOwned("home_sections_list",{},"home_sections_read",extra,state.owner)
end sub

sub HomeSectionsBegin(intent as Object)
    state = m.homeSections
    if state = invalid then return
    if not HomeSectionsCurrent({serial:state.serial}) then return
    if state.busy = true then return
    state.serial++
    m.homeSectionsSerial = state.serial
    HomeSectionsRead(intent)
end sub

sub HomeSectionsResult(purpose as String, result as Object, data as Object, extra as Dynamic)
    if not HomeSectionsCurrent(extra)
        if m.homeSections <> invalid and type(extra) = "roAssociativeArray"
            if m.homeSections.serial = extra.serial then m.homeSections.busy = false
        end if
        return
    end if
    state = m.homeSections
    expected = "home_sections_" + state.stage
    if purpose <> expected then return
    if result.sessionRevision <> SessionRevision("silo") or (state.owner.sessionRevision <> invalid and result.sessionRevision <> state.owner.sessionRevision)
        state.busy = false
        state.stage = "done"
        Toast("Home layout session changed. Reopen Manage Home rows.")
        return
    end if
    if result.ok <> true
        state.busy = false
        state.stage = "done"
        if purpose = "home_sections_write"
            Toast("Home layout save was not confirmed. Reading the server layout before another change.")
            HomeSectionsRead(invalid)
        else
            Toast("Home rows could not be read. Reopen Manage Home rows to try again.")
        end if
        return
    end if
    if state.owner.sessionRevision = invalid then state.owner.sessionRevision = result.sessionRevision
    if purpose = "home_sections_read"
        state.saved = data.items
        state.stage = "rows"
        ApiOwned("home_sections_settings",{},"home_sections_rows",extra,state.owner)
    else if purpose = "home_sections_rows"
        state.rows = data.items
        m.homeContinueLayoutScope = HomeProgressScope()
        m.homeContinueLayoutToken = m.homeToken
        m.homeContinueHidden = HomeSectionsContinueHidden(state.rows,invalid)
        if state.intent = invalid
            state.busy = false
            state.stage = "done"
            if state.selected <> ""
                id = state.selected
                state.selected = ""
                HomeSectionsRowMenu(id)
            else
                HomeSectionsMenu()
            end if
            return
        end if
        action = "home_sections_save"
        params = {}
        if state.intent.kind = "reset"
            action = "home_sections_reset"
        else
            edited = HomeSectionsEdit(state.saved,state.rows,state.intent)
            if edited.ok <> true
                state.busy = false
                state.stage = "done"
                Toast("This Home layout cannot be safely changed by this Roku. No changes were sent.")
                return
            end if
            params = {overrides:edited.overrides}
        end if
        state.stage = "write"
        ApiOwned(action,params,"home_sections_write",extra,state.owner)
    else if purpose = "home_sections_write"
        if data.acknowledged <> true
            state.busy = false
            state.stage = "done"
            Toast("Home layout save was not confirmed. Reading the server layout before another change.")
            HomeSectionsRead(invalid)
            return
        end if
        HomeSectionsChanged()
        state.context = BrowseCaptureContext()
        state.busy = false
        state.stage = "done"
        Toast("Home layout saved.")
        HomeSectionsRead(invalid)
    end if
end sub

sub HomeSectionsMenu()
    state = m.homeSections
    labels = []
    for each row in state.rows
        label = TextOr(row.title)
        if label = "" then label = "Home row"
        if row.hidden = true then label = label + " (hidden)"
        labels.Push(label)
    end for
    labels.Push("Reset Home layout")
    labels.Push("Cancel")
    BrowsePagedChoices("Manage Home rows",labels,"onHomeSectionsMenu")
    m.browseDialogTicket.homeSerial = state.serial
end sub

sub onHomeSectionsMenu(event as Object)
    state = m.homeSections
    if state = invalid then return
    if m.browseDialogTicket = invalid then return
    if m.browseDialogTicket.homeSerial <> state.serial then return
    index = BrowseChoiceIndex(event)
    if index < 0
        if m.browseDialogTicket <> invalid then m.browseDialogTicket.homeSerial = state.serial
        return
    end if
    if not HomeSectionsCurrent({serial:state.serial}) or state.busy = true then return
    if index < state.rows.Count()
        HomeSectionsRowMenu(state.rows[index].id)
    else if index = state.rows.Count()
        BrowseDialog("Reset Home layout?",["Reset Home layout","Cancel"],"onHomeSectionsReset")
        m.browseDialog.message = "Remove all Home row overrides for this profile and restore the server layout. Library layouts are unchanged."
        m.browseDialogTicket.homeSerial = state.serial
    else
        m.homeSections = invalid
    end if
end sub

sub HomeSectionsRowMenu(id as String)
    state = m.homeSections
    index = HomeSectionsRowIndex(state.rows,id)
    if index < 0 then HomeSectionsMenu() : return
    row = state.rows[index]
    label = "Hide row"
    if row.hidden = true then label = "Show row"
    choices = [{label:label,kind:"hidden",id:id,value:row.hidden <> true}]
    if index > 0 then choices.Push({label:"Move up",kind:"move",id:id,direction:-1})
    if index < state.rows.Count()-1 then choices.Push({label:"Move down",kind:"move",id:id,direction:1})
    choices.Push({label:"Manage all Home rows",kind:"manage"})
    labels = []
    for each choice in choices
        labels.Push(choice.label)
    end for
    BrowseDialog("Home row: " + TextOr(row.title),labels,"onHomeSectionsRow")
    m.browseDialogTicket.homeSerial = state.serial
    m.browseDialogTicket.homeChoices = choices
end sub

sub onHomeSectionsRow(event as Object)
    ticket = BrowseTakeDialog(event,"onHomeSectionsRow")
    if ticket = invalid then return
    state = m.homeSections
    if state = invalid then return
    if ticket.homeSerial <> state.serial then return
    index = m.browseDialog.buttonSelected
    m.browseDialog.close = true
    if index < 0 or index >= ticket.homeChoices.Count() then return
    choice = ticket.homeChoices[index]
    if choice.kind = "manage" then HomeSectionsMenu() : return
    HomeSectionsBegin(choice)
end sub

sub onHomeSectionsReset(event as Object)
    ticket = BrowseTakeDialog(event,"onHomeSectionsReset")
    if ticket = invalid then return
    state = m.homeSections
    if state = invalid then return
    if ticket.homeSerial <> state.serial then return
    index = m.browseDialog.buttonSelected
    m.browseDialog.close = true
    if index = 0 then HomeSectionsBegin({kind:"reset"}) else HomeSectionsMenu()
end sub

sub HomeSectionsChanged()
    m.homeContinueLayoutScope = HomeProgressScope()
    m.homeContinueLayoutToken = m.homeToken
    m.homeContinueHidden = HomeSectionsContinueHidden(m.homeSections.rows,m.homeSections.intent)
    m.homeLayoutChangedScope = HomeProgressScope()
    HomeCacheRetire()
    m.homeReload = true
    if m.view = "home" then HomeLoad()
end sub
