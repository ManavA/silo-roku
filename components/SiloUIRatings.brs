' Shared native renderer. Six bounded slots occupy at most 676x60.
function RenderRatingChips(group as Object, item as Object) as Integer
    for each child in group.getChildren(-1, 0)
        if child.hasField("ratingCaption")
            child.unobserveField("loadStatus")
            child.ratingLabel = invalid
        end if
    end for
    group.removeChildren(group.getChildren(-1, 0))
    chips = SiloUIRatingChips(item)
    x = 0 : y = 0
    for i = 0 to chips.Count() - 1
        c = chips[i]
        if i = 3 then x = 0 : y = 32
        width = Len(c.fallback) * 9 + 16
        if c.fallback = "" then width = Len(c.text) * 9 + 16
        if c.asset <> "" then width = width + 42
        if width < 100 then width = 100
        if width > 220 then width = 220
        background = group.createChild("Poster")
        background.uri = "pkg:/images/ui/chip.9.png"
        background.width = width : background.height = 28 : background.translation = [x, y]
        text = c.text : inset = 8
        logo = invalid
        uri = "pkg:/images/ratings/" + c.asset + ".png"
        if c.asset <> ""
            logo = group.createChild("Poster")
            logo.width = 36 : logo.height = 22
            logo.loadDisplayMode = "scaleToFit" : logo.translation = [x + 8, y + 3]
            inset = 50
        else if c.fallback <> ""
            text = c.fallback
        end if
        label = group.createChild("Label")
        label.text = text : label.font = SiloUIFont(17, true)
        label.color = "0xF5F5F7FF"
        label.width = width - inset - 8 : label.height = 28
        label.translation = [x + inset, y] : label.vertAlign = "center"
        if logo <> invalid
            logo.addFields({ratingCaption:c.fallback, ratingLabel:label, ratingX:x, ratingY:y, ratingWidth:width})
            logo.observeField("loadStatus", "onRatingLogoStatus")
            logo.uri = uri
            RatingLogoStatus(logo)
        end if
        x = x + width + 8
    end for
    if chips.Count() = 0 then return 0
    if chips.Count() <= 3 then return 28
    return 60
end function

sub onRatingLogoStatus(event as Object)
    RatingLogoStatus(event.getRoSGNode())
end sub

sub RatingLogoStatus(logo as Object)
    if logo.ratingLabel = invalid then return
    if logo.loadStatus <> "failed" and logo.loadStatus <> "ready" then return
    logo.unobserveField("loadStatus")
    if logo.loadStatus = "failed"
        logo.visible = false
        logo.ratingLabel.text = logo.ratingCaption
        logo.ratingLabel.translation = [logo.ratingX + 8, logo.ratingY]
        logo.ratingLabel.width = logo.ratingWidth - 16
    end if
    logo.ratingLabel = invalid
end sub
