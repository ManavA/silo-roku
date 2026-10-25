' Manual controls have no native focused label; native lists keep their own speech.
sub SiloUIAccessibilityInit()
    m.audioGuide = CreateObject("roAudioGuide")
    m.audioGuideFocus = ""
    m.top.observeField("appFocused", "onSiloUIAccessibilityOwnerChanged")
    m.top.observeField("dialog", "onSiloUIAccessibilityOwnerChanged")
end sub

sub onSiloUIAccessibilityOwnerChanged()
    m.audioGuideFocus = ""
end sub

function SiloUIAccessibilityVisible(node as Object) as Boolean
    while node <> invalid
        if node.visible = false then return false
        if node.opacity <> invalid
            if node.opacity <= 0 then return false
        end if
        node = node.getParent()
    end while
    return true
end function

sub SiloUIAccessibilityFocused()
    identity = ""
    text = ""
    node = invalid
    if m.top.appFocused = true and m.top.dialog = invalid and m.manualFocus <> invalid
        if m.manualFocus.hasFocus()
            zone = m.zone
            if m.view <> "" and m.view <> "player" and m.view <> "onboarding"
                if zone = "avatar" or (zone = "nav" and m.navigationMode = "left") or (zone = "drawer" and m.drawerOpen = true and m.drawerIndex = -1)
                    if zone = "avatar" then node = m.top.findNode("avatar") else node = m.top.findNode("navMenu")
                    text = "Profile menu, button"
                    identity = m.view + ":" + zone + ":profile"
                else if (zone = "nav") or (zone = "drawer" and m.drawerOpen = true) or SiloUINavigationContentZone(m.view, zone)
                    row = m.pillGroups[zone]
                    if row <> invalid
                        index = row.index
                        if zone = "drawer" then index = m.drawerIndex
                        if index >= 0 and index < row.pills.Count()
                            node = row.pills[index].label
                            label = node.text
                            if type(label) = "String" or type(label) = "roString"
                                ' Never read input values or link-like strings through a painted label.
                                if Instr(1, label, "://") = 0 and Instr(1, label, "@") = 0
                                    label = Left(label.Trim(), 120)
                                    if label <> ""
                                        text = label + ", button, " + (index + 1).ToStr() + " of " + row.pills.Count().ToStr()
                                        identity = m.view + ":" + zone + ":" + index.ToStr()
                                    end if
                                end if
                            end if
                        end if
                    end if
                end if
            end if
        end if
    end if
    if node = invalid then identity = ""
    if node <> invalid
        if not SiloUIAccessibilityVisible(node) then identity = ""
    end if
    if identity = ""
        m.audioGuideFocus = ""
        return
    end if
    key = identity + ":" + text
    if m.audioGuideFocus = key then return
    m.audioGuideFocus = key
    if m.audioGuide <> invalid then m.audioGuide.Say(text, true, false)
end sub
