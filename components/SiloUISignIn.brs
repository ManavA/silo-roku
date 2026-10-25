' Address history contains origins only; tokens remain in the existing scoped session.
sub SiloUISignInInit()
    m.obQr = m.top.findNode("obQr")
    m.obQrGeneration = 0
    section = AppRegistrySection("servers")
    raw = invalid
    if section.Exists("silo") then raw = ParseJson(section.Read("silo"))
    m.savedServers = SiloUISavedServers(raw)
end sub

sub SiloUISignInRemember()
    m.savedServers = SiloUISavedServers(m.savedServers,TextOr(m.obServerUrl))
    section = AppRegistrySection("servers")
    section.Write("silo",FormatJson(m.savedServers))
    section.Flush()
end sub

function SiloUISignInChoices() as Object
    choices = []
    for each address in m.savedServers
        choices.Push({label:address,action:"saved_silo",address:address})
    end for
    choices.Push({label:"Enter another server address",action:"silo_address"})
    choices.Push({label:"Find servers on this network",action:"silo_find"})
    choices.Push({label:"Forget saved addresses",action:"forget_servers"})
    choices.Push({label:"Back",action:"sources"})
    return choices
end function

sub SiloUISignInClearQr()
    if m.obQr = invalid then return
    m.obQrGeneration = NumberOr(m.obQrGeneration,0) + 1
    if m.obQrTask <> invalid then m.obQrTask.control = "stop"
    m.obQrTask = invalid
    m.obQr.removeChildren(m.obQr.getChildren(-1,0))
    m.obQr.visible = false
    m.obBody.width = 1000
end sub

sub SiloUISignInShowQr(uri as String)
    SiloUISignInClearQr()
    task = CreateObject("roSGNode", "SiloUIQrTask")
    task.job = {uri:uri,generation:m.obQrGeneration}
    task.observeField("result","onSiloUISignInQr")
    m.obQrTask = task
    task.control = "run"
end sub

sub onSiloUISignInQr(event as Object)
    SiloUISignInQrResult(event.getData())
end sub

sub SiloUISignInQrResult(result as Object)
    if result.generation <> m.obQrGeneration or m.view <> "onboarding" or m.obMode <> "silo" then return
    m.obQrTask = invalid
    if type(result.matrix) <> "roArray" then return
    if result.matrix.Count() = 0 then return
    SiloUISignInPaintQr(result.matrix)
end sub

sub SiloUISignInPaintQr(matrix as Object)
    m.obBody.width = 670
    m.obCode.translation = [96,450]
    m.obButtons.translation = [0,0]
    viewport = m.top.findNode("obChoiceViewport")
    viewport.translation = [96,560]
    viewport.clippingRect = [0,0,1088,92]
    m.obButtons.numRows = 2
    m.top.findNode("obMore").visible = m.obChoices.Count() > m.obButtons.numRows
    white = m.obQr.createChild("Rectangle")
    white.width = 270: white.height = 270: white.color = "0xFFFFFFFF"
    ' Horizontal runs bound the node count and preserve a four-module quiet zone.
    for y = 0 to 36
        x = 0
        while x < 37
            if matrix[y][x] = 1
                start = x
                while x < 37
                    if matrix[y][x] <> 1 then exit while
                    x = x+1
                end while
                black = m.obQr.createChild("Rectangle")
                black.translation = [(start+4)*6,(y+4)*6]
                black.width = (x-start)*6: black.height = 6: black.color = "0x000000FF"
            else
                x = x+1
            end if
        end while
    end for
    m.obQr.visible = true
end sub
