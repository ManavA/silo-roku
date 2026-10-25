' Appearance is app-wide and independent of source playback preferences.
function SiloUIAppearanceMode(value as Dynamic) as String
    if type(value) <> "String" and type(value) <> "roString" then return "oled"
    for each mode in ["oled", "glass", "silo_blue", "light_blue"]
        if value = mode then return mode
    end for
    return "oled"
end function

function SiloUIAppearanceChoices() as Object
    return [
        {label:"OLED · true black", action:"appearance_select", value:"oled"},
        {label:"Glass · translucent dark", action:"appearance_select", value:"glass"},
        {label:"Silo blue", action:"appearance_select", value:"silo_blue"},
        {label:"Light blue", action:"appearance_select", value:"light_blue"},
        {label:"Back to Settings", action:"settings"}
    ]
end function

function SiloUIAppearancePalette(value as Dynamic) as Object
    mode = SiloUIAppearanceMode(value)
    palette = {mode:mode, label:"OLED", base:"0x000000FF", panel:"0x000000FF", detailpanel:"0x000000B3", wash:"0x000000B3", text:"0xFFFFFFFF", muted:"0xC3CBDAFF", accent:"0x7CD4FFFF", focus:"0xFFFFFFFF", focustext:"0x090A0DFF", pill:"0x20242CFF"}
    if mode = "glass"
        palette.label = "Glass"
        palette.base = "0x111827FF"
        palette.panel = "0x182235D9"
        palette.detailpanel = "0x18223590"
        palette.wash = "0x142139C8"
        palette.focus = "0xC8E8FFFF"
        palette.pill = "0x233147FF"
    else if mode = "silo_blue"
        palette.label = "Silo blue"
        palette.base = "0x071D35FF"
        palette.panel = "0x0B2D50F0"
        palette.detailpanel = "0x0B2D50B3"
        palette.wash = "0x071D35C8"
        palette.focus = "0x7CD4FFFF"
        palette.pill = "0x123956FF"
    else if mode = "light_blue"
        palette.label = "Light blue"
        palette.base = "0x07111FFF"
        palette.panel = "0x10243BE8"
        palette.detailpanel = "0x10243BB3"
        palette.wash = "0x07111FB8"
        palette.muted = "0xC3D5E8FF"
        palette.accent = "0xA7D9FFFF"
        palette.focus = "0xB8E1FFFF"
        palette.focustext = "0x07111FFF"
        palette.pill = "0x1A344DFF"
    end if
    return palette
end function

' The wordmark already names the service; retain only a distinct server name.
function SiloUIAppearanceServerLabel(value as Dynamic) as String
    if type(value) <> "String" and type(value) <> "roString" then return ""
    label = value.Trim()
    if LCase(label) = "silo" then return ""
    return label
end function
