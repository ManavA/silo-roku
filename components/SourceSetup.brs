' ButtonGroup owns D-pad movement and OK; this component only translates its events.
sub init()
    m.buttons = m.top.findNode("sourceButtons")
    m.description = m.top.findNode("sourceDescription")
    m.sourceMark = m.top.findNode("sourceMark")
    m.sourceName = m.top.findNode("sourceName")
    m.sourceKind = m.top.findNode("sourceKind")
    m.sourceHeadline = m.top.findNode("sourceHeadline")
    m.sourceStep = m.top.findNode("sourceStep")
    m.buttons.buttons = ["Plex", "Silo"]
    m.buttons.observeField("buttonFocused", "onButtonFocused")
    m.buttons.observeField("buttonSelected", "onButtonSelected")

    ' The initial index is 0, so there may be no 0-to-0 focus event at launch.
    m.top.focusedSource = "plex"
    showDescription("plex")
end sub

sub onButtonFocused()
    source = sourceForIndex(m.buttons.buttonFocused)
    if source = "" then return
    m.top.focusedSource = source
    showDescription(source)
end sub

sub onButtonSelected()
    source = sourceForIndex(m.buttons.buttonSelected)
    if source <> "" then m.top.sourceSelected = source
end sub

function sourceForIndex(index as Integer) as String
    if index = 0 then return "plex"
    if index = 1 then return "silo"
    return ""
end function

sub showDescription(source as String)
    if source = "plex"
        m.sourceMark.text = "P"
        m.sourceName.text = "Plex"
        m.sourceKind.text = "PERSONAL MEDIA SERVER"
        m.sourceHeadline.text = "Your collection," + Chr(10) + "ready to play."
        m.description.text = "Bring your movies and shows from a Plex media server."
        m.sourceStep.text = "Plex account  /  Media server"
    else
        m.sourceMark.text = "S"
        m.sourceName.text = "Silo"
        m.sourceKind.text = "YOUR SILO LIBRARY"
        m.sourceHeadline.text = "Your server." + Chr(10) + "Your next favorite."
        m.description.text = "Connect your Silo server to browse movies, series and saved progress."
        m.sourceStep.text = "Server address  /  Device sign-in"
    end if
end sub
