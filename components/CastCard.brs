sub init()
    m.photo = m.top.findNode("photo")
    m.initial = m.top.findNode("initial")
    m.name = m.top.findNode("name")
    m.role = m.top.findNode("role")
    m.border = m.top.findNode("border")
    nameFont = CreateObject("roSGNode", "Font")
    nameFont.uri = "pkg:/images/fonts/Roboto-Medium.ttf"
    nameFont.size = 18
    m.name.font = nameFont
    roleFont = CreateObject("roSGNode", "Font")
    roleFont.uri = "pkg:/images/fonts/Roboto-Regular.ttf"
    roleFont.size = 16
    m.role.font = roleFont
    m.photo.observeField("loadStatus", "onPhoto")
end sub

sub onContent()
    if m.content <> invalid then m.content.unobserveField("photoUri")
    m.photo.uri = ""
    m.photo.visible = false
    m.name.text = ""
    m.role.text = ""
    m.initial.text = "?"
    m.content = m.top.itemContent
    if m.content = invalid then return
    m.name.text = m.content.personName
    m.role.text = m.content.personRole
    if m.name.text <> "" then m.initial.text = UCase(Left(m.name.text, 1))
    m.content.observeField("photoUri", "onPhotoUri")
    onPhotoUri()
end sub

sub onPhotoUri()
    m.photo.uri = ""
    m.photo.visible = false
    if m.content <> invalid then m.photo.uri = m.content.photoUri
end sub

sub onPhoto()
    m.photo.visible = m.photo.uri <> "" and m.photo.loadStatus = "ready"
end sub

sub onFocus()
    m.border.visible = m.top.focusPercent > 0.5 and m.top.rowFocusPercent > 0.5 and m.top.itemHasFocus = true and m.top.rowHasFocus = true
end sub
