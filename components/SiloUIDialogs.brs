' Native dialogs are asynchronous visits, not mutable global selections. Tokens
' and owners contain no credentials; emitted node identity makes use one-shot.
function BrowseCaptureContext() as Object
    context = {owner:{provider:m.provider,sourceId:m.sourceId,profileId:m.profileId,generation:m.generation},view:m.view,viewToken:m.browseViewToken}
    if m.view = "detail"
        context.visit = m.detailToken
        context.itemId = ""
        if m.detailItem <> invalid then context.itemId = TextOr(m.detailItem.itemId)
    else if m.view = "onboarding"
        context.visit = m.obQrGeneration
    else if m.view = "library"
        context.visit = m.libraryToken
    else if m.view = "home"
        context.visit = m.homeToken
    else if m.view = "search"
        context.visit = m.searchToken
    else if m.view = "audio"
        context.visit = m.audioToken
    else if m.view = "player"
        context.visit = m.playToken
    end if
    return context
end function

function BrowseContextCurrent(context as Dynamic) as Boolean
    if type(context) <> "roAssociativeArray" then return false
    current = BrowseCaptureContext()
    a = context.owner:b = current.owner
    if a.provider <> b.provider or a.sourceId <> b.sourceId or a.profileId <> b.profileId or a.generation <> b.generation then return false
    return context.view = current.view and context.viewToken = current.viewToken and context.visit = current.visit and context.itemId = current.itemId
end function

function BrowseEventTicket(node as Object, handler as String) as Object
    m.browseDialogSequence = NumberOr(m.browseDialogSequence,0)+1
    return {node:node,handler:handler,context:BrowseCaptureContext(),used:false}
end function

sub BrowseBindDialog(node as Object, handler as String)
    m.browseDialogTicket = BrowseEventTicket(node,handler)
end sub

function BrowseTakeEventTicket(ticket as Dynamic, event as Dynamic) as Boolean
    if ticket = invalid or event = invalid then return false
    if ticket.used = true or not BrowseContextCurrent(ticket.context) then return false
    if not ticket.node.isSameNode(event.getRoSGNode()) then return false
    if m.top.dialog = invalid then return false
    if not ticket.node.isSameNode(m.top.dialog) then return false
    ticket.used = true
    return true
end function

function BrowseTakeDialog(event as Dynamic, handler as String) as Dynamic
    ticket = m.browseDialogTicket
    if ticket = invalid then return invalid
    if ticket.handler <> handler then return invalid
    if not BrowseTakeEventTicket(ticket,event) then return invalid
    return ticket
end function
