' Silo entry point. Only filtered memory/focus values reach scene fields.
sub Main(args = invalid as Dynamic)
    screen = CreateObject("roSGScreen")
    port = CreateObject("roMessagePort")
    screen.SetMessagePort(port)
    scene = screen.CreateScene("SiloUIScene")
    screen.Show()
    input = CreateObject("roInput")
    if input <> invalid
        input.SetMessagePort(port)
        transportEnabled = input.EnableTransportEvents()
    end if
    if type(args) = "roAssociativeArray"
        if args.Count() > 0 then scene.launchInput = args
    end if

    deviceInfo = CreateObject("roDeviceInfo")
    if deviceInfo <> invalid
        deviceInfo.SetMessagePort(port)
        deviceInfo.EnableAppFocusEvent(true)
        deviceInfo.EnableScreensaverExitedEvent(true)
    end if
    memoryMonitor = CreateObject("roAppMemoryMonitor")
    memoryWarningsEnabled = false
    if memoryMonitor <> invalid
        memoryMonitor.SetMessagePort(port)
        memoryWarningsEnabled = memoryMonitor.EnableMemoryWarningEvent(true)
    end if
    if memoryWarningsEnabled
        pressure = MainMemoryPressure("roAppMemoryNotificationEvent", {memoryUsagePercent:memoryMonitor.GetMemoryLimitPercent()})
        if pressure >= 0 then scene.memoryPressure = pressure
    else
        ' Older firmware and unsupported models use device-wide warnings.
        if deviceInfo <> invalid then deviceInfo.EnableLowGeneralMemoryEvent(true)
    end if

    while true
        message = wait(0, port)
        messageType = type(message)
        if messageType = "roSGScreenEvent"
            if message.IsScreenClosed()
                exit while
            end if
        else if messageType = "roInputEvent"
            if message.IsInput() then MainInput(input, scene, message.GetInfo())
        else if messageType = "roAppMemoryNotificationEvent" or messageType = "roDeviceInfoEvent"
            info = message.GetInfo()
            pressure = MainMemoryPressure(messageType, info)
            if pressure >= 0 then scene.memoryPressure = pressure
            if messageType = "roDeviceInfoEvent"
                appFocused = MainAppFocus(info)
                if type(appFocused) = "Boolean" or type(appFocused) = "roBoolean"
                    if scene.HasField("appFocused") then scene.appFocused = appFocused
                end if
            end if
        end if
    end while
end sub

' invalid means unrelated/malformed device info; preserve current app focus.
function MainAppFocus(info as Dynamic) as Dynamic
    if type(info) <> "roAssociativeArray" then return invalid
    focused = info.Lookup("appFocused")
    if type(focused) = "Boolean" or type(focused) = "roBoolean" then return focused
    exited = info.Lookup("exitedScreensaver")
    if type(exited) = "Boolean" or type(exited) = "roBoolean"
        if exited then return true
    end if
    return invalid
end function

' -1 means ignore this event and preserve the previous pressure value.
function MainMemoryPressure(eventType as String, info as Dynamic) as Integer
    if type(info) <> "roAssociativeArray" then return -1
    if eventType = "roAppMemoryNotificationEvent"
        usage = info.Lookup("memoryUsagePercent")
        if usage = invalid then usage = info.Lookup("MemoryUsagePercent")
        usageType = type(usage)
        if usageType <> "Integer" and usageType <> "roInt" and usageType <> "roInteger" and usageType <> "LongInteger" and usageType <> "roLongInteger" then return -1
        if usage < 0 then return -1
        if usage > 100 then return 100
        return usage
    else if eventType = "roDeviceInfoEvent"
        level = info.Lookup("generalMemoryLevel")
        if type(level) <> "String" and type(level) <> "roString" then return -1
        ' These are equivalent cleanup severities, not measured app usage.
        if level = "normal" then return 0
        if level = "low" then return 80
        if level = "critical" then return 95
    end if
    return -1
end function

' Transport events must never enter the deep-link observer.
sub MainInput(input as Object, scene as Object, info as Dynamic)
    if type(info) = "roAssociativeArray"
        if info.type = "transport"
            result = scene.callFunc("handleTransport", info)
            response = {id:info.id,status:"error.generic"}
            if type(result) = "roAssociativeArray"
                for each status in ["success","success.seek-start","success.seek-end","error.generic"]
                    if result.status = status then response.status = status
                end for
            end if
            input.EventResponse(response)
            return
        end if
    end if
    scene.launchInput = info
end sub
