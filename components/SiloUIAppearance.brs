' Compact app-wide preference; never written into provider playback settings.
sub SiloUIAppearanceInit()
    SiloUIApplyAppearance(SiloUIAppearanceMode(SiloUIAppearanceRead()))
end sub

function SiloUIAppearanceRead() as Dynamic
    section = AppRegistrySection("preferences")
    return section.Read("appearance")
end function

sub SiloUIAppearanceWrite(mode as String)
    section = AppRegistrySection("preferences")
    section.Write("appearance", SiloUIAppearanceMode(mode))
    section.Flush()
end sub

sub SiloUIApplyAppearance(value as Dynamic)
    palette = SiloUIAppearancePalette(value)
    m.appearanceMode = palette.mode
    m.appearanceLabel = palette.label
    m.appearance = palette
    m.top.appearanceMode = palette.mode
    m.top.backgroundColor = palette.base
    m.top.findNode("base").color = palette.base
    m.top.findNode("appearanceWash").color = palette.wash
    m.top.findNode("appearancePanel").color = palette.panel
    m.top.findNode("detailAppearancePanel").color = palette.detailpanel
    m.top.findNode("brandLogoPanel").color = palette.panel
    fadeOpacity = 1
    for each id in ["fadeLeft", "fadeBottom", "fadeTop"]
        m.top.findNode(id).opacity = fadeOpacity
    end for
    for each id in ["heroTitle", "detailTitle", "detailQuality", "detailCompactTitle", "seasonsLabel", "episodesLabel", "detailCastLabel", "detailSimilarLabel", "libraryTitle", "obTitle"]
        m.top.findNode(id).color = palette.text
    end for
    for each id in ["heroMeta", "heroSummary", "detailSub", "detailMeta", "detailSummary", "detailCompactMeta", "detailCompactSummary", "libraryEmpty", "searchHint", "obBody"]
        m.top.findNode(id).color = palette.muted
    end for
    for each id in ["obEyebrow", "obCode", "detailRatings"]
        m.top.findNode(id).color = palette.accent
    end for
    m.top.findNode("rows").rowLabelColor = palette.text
    for each id in ["obButtons"]
        list = m.top.findNode(id)
        list.color = palette.text
        list.focusedColor = palette.focustext
        list.focusBitmapUri = "pkg:/images/ui/list_focus.9.png"
        list.focusBitmapBlendColor = palette.focus
    end for
    for each name in m.pillGroups
        if m.pillGroups[name].buttons = true
            PaintButtons(name, m.zone = name)
        else
            PaintPills(name, m.zone = name)
        end if
    end for
    if m.navigationMode <> invalid then SiloUINavigationSync()
end sub
