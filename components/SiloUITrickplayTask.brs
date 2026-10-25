sub init()
    m.top.functionName = "TrickplayRun"
end sub

sub TrickplayRun()
    m.tpPath = ""
    try
        m.tpJob = m.top.job
        m.tpSession = LoadSession("silo")
        m.tpRevision = SessionRevision("silo")
        if TrickplayCurrent() then TrickplayScrub()
    catch exception
        ' Neither signed sheet locations nor native error text may escape.
    end try
    m.top.result = {}
    TrickplayDelete()
    m.tpSession = invalid
end sub

function TrickplayCurrent() as Boolean
    if m.top.cancelled then return false
    if m.tpRevision <> m.tpJob.sessionRevision or m.tpRevision <> SessionRevision("silo") then return false
    session = LoadSession("silo")
    for each key in ["sourceId","profileId"]
        if ArtworkText(session,key) <> ArtworkText(m.tpJob,key) then return false
    end for
    for each key in ["accessToken","profileToken","refreshToken","baseUrl"]
        if ArtworkText(session,key) <> ArtworkText(m.tpSession,key) then return false
    end for
    return true
end function

function TrickplayNow() as Double
    return CreateObject("roDateTime").AsSeconds()
end function

function TrickplayManifest() as Object
    request = BuildSiloRequest("trickplay",m.tpSession,{itemId:m.tpJob.itemId,fileId:m.tpJob.fileId})
    if request.ok <> true then return {ok:false}
    request.responseBodyLimit = 65536
    response = HttpRequest(request,3000)
    if response.ok <> true or not TrickplayCurrent() then return {ok:false}
    raw = ParseJson(response.body)
    return SiloUITrickplayManifest(raw,m.tpJob.fileId,SiloBaseUrl(m.tpSession.baseUrl),TrickplayNow())
end function

sub TrickplayScrub()
    manifest = TrickplayManifest()
    refreshes = 0
    downloads = 0
    currentSheet = -1
    rate = CreateObject("roTimespan")
    lastDownload = -500
    idlePort = CreateObject("roMessagePort")
    while TrickplayCurrent()
        if manifest.ok <> true then return
        if manifest.expires <= TrickplayNow() + 5
            m.top.result = {}
            TrickplayDelete()
            if refreshes >= 1 then return
            refreshes = refreshes + 1
            manifest = TrickplayManifest()
            currentSheet = -1
        else
            tile = SiloUITrickplayTile(manifest,m.top.targetMs)
            if tile.ok <> true then return
            if currentSheet <> tile.sheet and rate.TotalMilliseconds() - lastDownload >= 500
                m.top.result = {}
                TrickplayDelete()
                lastDownload = rate.TotalMilliseconds()
                downloads = downloads + 1
                m.tpPath = "tmp:/scrub-" + m.tpJob.sequence.ToStr() + "-" + downloads.ToStr() + ".jpg"
                status = TrickplayDownload(manifest.urls[tile.sheet])
                if status = 401 or status = 403
                    if refreshes >= 1 then return
                    refreshes = refreshes + 1
                    manifest = TrickplayManifest()
                    currentSheet = -1
                else
                    if status <> 200 or not TrickplayInspect(manifest) or not TrickplayCurrent() then return
                    currentSheet = tile.sheet
                    projection = {ok:true,uri:m.tpPath,sheet:currentSheet,intervalMs:manifest.intervalMs,width:manifest.width,height:manifest.height,columns:manifest.columns,rows:manifest.rows,count:manifest.count,sheetWidth:manifest.sheetWidth,sheetHeight:manifest.sheetHeight,expires:manifest.expires}
                    m.top.result = projection
                end if
            end if
        end if
        wait(100,idlePort)
    end while
end sub

' The sheet's signature is its only authority. No app headers reach image hosts.
function TrickplayDownload(url as String) as Integer
    port = CreateObject("roMessagePort")
    transfer = CreateObject("roUrlTransfer")
    transfer.SetMessagePort(port)
    transfer.SetUrl(url)
    transfer.RetainBodyOnError(false)
    if Left(LCase(url),8) = "https://"
        if not transfer.SetCertificatesFile("common:/certs/ca-bundle.crt") then return 0
        if not transfer.EnablePeerVerification(true) or not transfer.EnableHostVerification(true) then return 0
    end if
    if not TrickplayCurrent() then return 0
    if not transfer.AsyncGetToFile(m.tpPath) then return 0
    clock = CreateObject("roTimespan")
    while clock.TotalMilliseconds() < 4000
        if not TrickplayCurrent() or TrickplayTooLarge()
            transfer.AsyncCancel()
            return 0
        end if
        event = wait(100,port)
        if type(event) = "roUrlEvent" and event.GetSourceIdentity() = transfer.GetIdentity()
            if TrickplayTooLarge() then return 0
            return event.GetResponseCode()
        end if
    end while
    transfer.AsyncCancel()
    return 0
end function

function TrickplayTooLarge() as Boolean
    fs = CreateObject("roFileSystem")
    for each path in [m.tpPath,m.tpPath+".tmp"]
        stat = fs.Stat(path)
        if ArtworkField(stat,"size",0) > 1048576 then return true
    end for
    return false
end function

function TrickplayInspect(manifest as Object) as Boolean
    stat = CreateObject("roFileSystem").Stat(m.tpPath)
    size = ArtworkField(stat,"size",0)
    if size < 12 or size > 1048576 then return false
    header = CreateObject("roByteArray")
    count = size
    if count > 65536 then count = 65536
    if not header.ReadFile(m.tpPath,0,count) then return false
    return SiloUITrickplayJpeg(header,manifest.sheetWidth,manifest.sheetHeight)
end function

sub TrickplayDelete()
    if not CreateObject("roRegex","^tmp:/scrub-[0-9]+-[0-9]+[.]jpg$","").IsMatch(m.tpPath) then return
    fs = CreateObject("roFileSystem")
    fs.Delete(m.tpPath)
    fs.Delete(m.tpPath+".tmp")
    m.tpPath = ""
end sub
