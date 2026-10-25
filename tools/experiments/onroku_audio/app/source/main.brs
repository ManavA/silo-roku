sub Main()
    screen = CreateObject("roSGScreen")
    port = CreateObject("roMessagePort")
    screen.SetMessagePort(port)
    screen.CreateScene("SiloUIScene")
    screen.Show()
    while true
        event = Wait(0, port)
        if Type(event) = "roSGScreenEvent"
            if event.IsScreenClosed() then return
        end if
    end while
end sub
