' Discovery offers addresses only. Selection and identity consistency precede sign-in.
sub SiloUILanRetire()
    m.lanToken = NumberOr(m.lanToken,0) + 1
    m.lanPhase = ""
    m.lanCandidates = []
    m.lanSelected = invalid
    if m.lanTask <> invalid then m.lanTask.cancelled = true
    m.lanTask = invalid
end sub

sub SiloUILanScreen(title as String, body as String, choices as Object)
    m.lanRendering = true
    ObScreen("Find Silo servers",title,body,"",choices)
    m.lanRendering = false
end sub

sub SiloUILanFind()
    SiloUILanRetire()
    m.obMode = ""
    m.pollTimer.control = "stop"
    m.lanGeneration = m.generation
    m.lanPhase = "discovery"
    SiloUILanScreen("Looking for servers…","Searching this network for five seconds. You can still enter an address manually.",[{label:"Enter server address",action:"silo_address"},{label:"Back",action:"silo_servers"}])
    SiloUILanStartTask("LanDiscoveryTask",{token:m.lanToken,generation:m.generation})
end sub

sub SiloUILanStartTask(kind as String, job as Object)
    task = CreateObject("roSGNode",kind)
    task.job = job
    task.observeField("result","onSiloUILanResult")
    m.lanTask = task
    task.control = "run"
end sub

sub onSiloUILanResult(event as Object)
    SiloUILanResult(event.getData())
end sub

sub SiloUILanResult(result as Dynamic)
    if type(result) <> "roAssociativeArray" then return
    if m.view <> "onboarding" or m.lanPhase = "" then return
    if result.token <> m.lanToken or result.generation <> m.generation or m.lanGeneration <> m.generation then return
    m.lanTask = invalid
    if m.lanPhase = "discovery"
        m.lanCandidates = []
        if result.status = "complete" and type(result.candidates) = "roArray"
            for each candidate in result.candidates
                if m.lanCandidates.Count() >= 16 then exit for
                if LanIdentityRequest([candidate],0).ok then m.lanCandidates.Push(candidate)
            end for
        end if
        SiloUILanCandidates()
    else if m.lanPhase = "identity"
        selection = LanIdentityRequest(m.lanCandidates,m.lanSelected)
        if selection.ok and result.ok = true and result.serverId = selection.serverId
            address = "http://" + selection.address + ":" + StrI(selection.port).Trim()
            SiloUILanRetire()
            ObConnectSilo(address)
        else
            m.lanPhase = "failed"
            SiloUILanScreen("Couldn't confirm this server","This server could not be verified. Enter its address or search again.",[{label:"Enter server address",action:"silo_address"},{label:"Find servers again",action:"silo_find"},{label:"Back to servers",action:"silo_servers"}])
        end if
    end if
end sub

sub SiloUILanCandidates()
    m.lanPhase = "candidates"
    choices = []
    for index = 0 to m.lanCandidates.Count() - 1
        candidate = m.lanCandidates[index]
        address = "http://" + candidate.address + ":" + StrI(candidate.port).Trim()
        choices.Push({label:SiloUILanName(candidate.instance) + address,action:"silo_lan_select",selected:index,token:m.lanToken})
    end for
    choices.Push({label:"Enter server address",action:"silo_address"})
    choices.Push({label:"Find servers again",action:"silo_find"})
    choices.Push({label:"Back to servers",action:"silo_servers"})
    body = "Choose your Silo server."
    if m.lanCandidates.Count() = 0 then body = "No supported servers found. Enter an address manually for older servers, or search again."
    SiloUILanScreen("Servers on this network",body,choices)
end sub

sub SiloUILanSelect(choice as Object)
    if m.lanPhase <> "candidates" or choice.token <> m.lanToken or m.lanGeneration <> m.generation then return
    selection = LanIdentityRequest(m.lanCandidates,choice.selected)
    if not selection.ok then return
    m.lanSelected = choice.selected
    m.lanPhase = "confirm"
    address = "http://" + selection.address + ":" + StrI(selection.port).Trim()
    SiloUILanScreen("Connect to this server?",address + " · Continue to sign in.",[{label:"Continue",action:"silo_lan_confirm",token:m.lanToken},{label:"Back to results",action:"silo_lan_results"},{label:"Enter server address",action:"silo_address"}])
end sub

sub SiloUILanConfirm(choice as Object)
    if m.lanPhase <> "confirm" or choice.token <> m.lanToken or m.lanGeneration <> m.generation then return
    if not LanIdentityRequest(m.lanCandidates,m.lanSelected).ok then return
    m.lanPhase = "identity"
    SiloUILanScreen("Checking server…","Please wait.",[{label:"Back to servers",action:"silo_servers"}])
    SiloUILanStartTask("LanIdentityTask",{token:m.lanToken,generation:m.generation,candidates:m.lanCandidates,selected:m.lanSelected})
end sub

' Keep network-provided names short and printable; the literal address stays visible.
function SiloUILanName(value as Dynamic) as String
    if type(value) <> "String" and type(value) <> "roString" then return ""
    suffix = "._silo._tcp.local."
    if Right(value,Len(suffix)) = suffix then value = Left(value,Len(value)-Len(suffix))
    value = CreateObject("roRegex","[^a-zA-Z0-9 ._-]","").ReplaceAll(Left(value,48)," ").Trim()
    if value = "" then return ""
    return value + " · "
end function
