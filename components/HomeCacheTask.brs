sub init()
    m.top.functionName = "runHomeCache"
end sub

sub runHomeCache()
    m.cacheJob = m.top.job
    m.cacheFs = CreateObject("roFileSystem")
    m.cacheClock = CreateObject("roTimespan")
    m.cacheClock.Mark()
    m.cacheSession = LoadSession("silo")
    m.cacheRevision = SessionRevision("silo")
    result = {ok:false}
    try
        if m.cacheJob.action = "purge"
            HomeCachePurge()
        else if HomeCacheCurrent()
            owner = HomeCacheOwner()
            if owner <> ""
                m.cacheOwner = owner
                if m.cacheJob.action = "read" then result = HomeCacheRead()
                if m.cacheJob.action = "write" then HomeCacheWrite()
            end if
        end if
    catch ignored
        ' Eviction, unsupported storage and corrupt files are ordinary misses.
    end try
    HomeCacheDelete("tmp:/silo-home-v1.part")
    HomeCacheDelete("tmp:/silo-home-v1.part.tmp")
    if m.top.cancelled then result = {ok:false}
    m.top.job = {}
    m.cacheSession = invalid
    m.top.result = result
end sub

function HomeCacheCurrent() as Boolean
    if m.top.cancelled then return false
    if HomeCacheText(m.cacheJob,"provider") <> "silo" then return false
    current = LoadSession("silo")
    if SessionRevision("silo") <> m.cacheRevision then return false
    if HomeCacheText(current,"accountId") = "" or HomeCacheText(current,"accessToken") = "" then return false
    for each key in ["accountId","sourceId","profileId","accessToken","profileToken"]
        if HomeCacheText(current,key) <> HomeCacheText(m.cacheSession,key) then return false
    end for
    if HomeCacheText(current,"profileId") = "" then return false
    for each key in ["sourceId","profileId"]
        if HomeCacheText(m.cacheJob,key) <> HomeCacheText(current,key) then return false
    end for
    return true
end function

function HomeCacheOwner() as String
    bytes = CreateObject("roByteArray")
    bytes.FromAsciiString(FormatJson([m.cacheSession.accountId,m.cacheSession.sourceId,m.cacheSession.profileId]))
    digest = CreateObject("roEVPDigest")
    if digest.Setup("sha256") <> 0 then return ""
    return LCase(digest.Process(bytes))
end function

function HomeCacheMetadataPath() as String
    return "cachefs:/silo-home-v1-" + m.cacheOwner + ".json"
end function

function HomeCacheOwnedPath(path as String) as Boolean
    return CreateObject("roRegex","^cachefs:/silo-home-v1-[a-f0-9]{64}(-[0-6][.]img|[.]json([.]part)?)$","").IsMatch(path)
end function

function HomeCacheDelete(path as String) as Boolean
    if not HomeCacheOwnedPath(path) and path <> "tmp:/silo-home-v1.part" and path <> "tmp:/silo-home-v1.part.tmp" then return false
    m.cacheFs.Delete(path)
    return not m.cacheFs.Exists(path)
end function

function HomeCachePurge() as Boolean
    files = m.cacheFs.GetDirectoryListing("cachefs:/")
    if type(files) <> "roArray" and type(files) <> "roList" then return false
    ' A surviving manifest must never observe reused image slots.
    for each name in files
        path = "cachefs:/"+name
        if HomeCacheOwnedPath(path) and Instr(1,name,".json") > 0
            if not HomeCacheDelete(path) then return false
        end if
    end for
    cleared = true
    for each name in files
        path = "cachefs:/"+name
        if HomeCacheOwnedPath(path)
            if not HomeCacheDelete(path) then cleared = false
        end if
    end for
    return cleared
end function

function HomeCacheFileSize(path as String) as Dynamic
    stat = m.cacheFs.Stat(path)
    if type(stat) <> "roAssociativeArray" then return -1
    kind = type(stat.size)
    if kind <> "Integer" and kind <> "roInt" and kind <> "LongInteger" and kind <> "roLongInteger" then return -1
    return stat.size
end function

function HomeCacheFileBytes(path as String, maximum as Integer) as Dynamic
    size = HomeCacheFileSize(path)
    if size <= 0 or size > maximum then return invalid
    bytes = CreateObject("roByteArray")
    if not bytes.ReadFile(path,0,maximum+1) then return invalid
    if bytes.Count() <> size or bytes.Count() > maximum then return invalid
    return bytes
end function

function HomeCacheRead() as Object
    bytes = HomeCacheFileBytes(HomeCacheMetadataPath(),65536)
    if bytes = invalid then return {ok:false}
    snapshot = ParseJson(bytes.ToAsciiString(),"i")
    if type(snapshot) <> "roAssociativeArray" then return {ok:false}
    if snapshot.schema <> 1 or snapshot.owner <> m.cacheOwner then return {ok:false}
    now = CreateObject("roDateTime").AsSeconds()
    if type(snapshot.savedAt) <> "Integer" and type(snapshot.savedAt) <> "roInt" then return {ok:false}
    if snapshot.savedAt > now or now-snapshot.savedAt > 86400 then return {ok:false}
    row = snapshot.row
    if type(row) <> "roAssociativeArray" then return {ok:false}
    projected = HomeCacheProjection([row])
    if projected.row = invalid then return {ok:false}
    if row.items.Count() > 6 or row.items.Count() <> projected.row.items.Count() then return {ok:false}
    projected.row.title = "Saved titles"
    total = bytes.Count()
    for index = 0 to row.items.Count()-1
        path = HomeCachePath(m.cacheOwner,index)
        if HomeCacheText(row.items[index].art,"poster") <> path then return {ok:false}
        image = HomeCacheFileBytes(path,262144)
        if image = invalid then return {ok:false}
        if not HomeCacheImageValid(image) then return {ok:false}
        total += image.Count()
        projected.row.items[index].art = {poster:path}
        projected.row.items[index].sourceId = m.cacheSession.sourceId
    end for
    heroPath = HomeCachePath(m.cacheOwner,6)
    if HomeCacheText(snapshot,"hero") = heroPath
        hero = HomeCacheFileBytes(heroPath,262144)
        if hero <> invalid
            if HomeCacheImageValid(hero) then total += hero.Count():projected.row.items[0].art.backdrop = heroPath
        end if
    end if
    if total > 1900544 or not HomeCacheCurrent() then return {ok:false}
    return {ok:true,rows:[projected.row]}
end function

sub HomeCacheWrite()
    projection = HomeCacheProjection(m.cacheJob.rows)
    ' Replace within a fixed seven-image namespace; interruption becomes a miss.
    if not HomeCachePurge() then return
    if projection.row = invalid then return
    row = projection.row
    accepted = []
    for each download in projection.downloads
        if not HomeCacheCurrent() or m.cacheClock.TotalMilliseconds() >= 6000 then exit for
        path = HomeCachePath(m.cacheOwner,accepted.Count())
        if HomeCacheDownload(download.url,path)
            card = row.items[download.index]
            card.art = {poster:path}
            accepted.Push(card)
        end if
    end for
    if accepted.Count() = 0 or not HomeCacheCurrent() then HomeCachePurge():return
    row.items = accepted
    hero = ""
    if HomeCacheText(m.cacheJob,"heroItemId") = accepted[0].itemId
        candidate = HomeCachePath(m.cacheOwner,6)
        if HomeCacheDownload(HomeCacheText(m.cacheJob,"heroUrl"),candidate) then hero = candidate
    end if
    snapshot = {schema:1,owner:m.cacheOwner,savedAt:CreateObject("roDateTime").AsSeconds(),row:row,hero:hero}
    bytes = CreateObject("roByteArray")
    bytes.FromAsciiString(FormatJson(snapshot))
    path = HomeCacheMetadataPath()
    if bytes.Count() > 65536 or not HomeCacheCurrent() then HomeCachePurge():return
    if not bytes.WriteFile(path+".part") then HomeCachePurge():return
    if not HomeCacheCurrent() then HomeCachePurge():return
    if not m.cacheFs.Rename(path+".part",path) then HomeCachePurge()
end sub

function HomeCacheHeader(headers as Dynamic, key as String) as String
    if type(headers) <> "roAssociativeArray" then return ""
    for each name in headers
        if LCase(name) = key then return headers[name]
    end for
    return ""
end function

function HomeCacheTransfer(url as String, head as Boolean) as Dynamic
    if not HomeCacheCurrent() or m.cacheClock.TotalMilliseconds() >= 6000 then return invalid
    port = CreateObject("roMessagePort")
    transfer = CreateObject("roUrlTransfer")
    transfer.SetMessagePort(port)
    transfer.SetUrl(url)
    transfer.SetCertificatesFile("common:/certs/ca-bundle.crt")
    transfer.EnablePeerVerification(true)
    transfer.EnableHostVerification(true)
    transfer.RetainBodyOnError(false)
    if head
        started = transfer.AsyncHead()
    else
        HomeCacheDelete("tmp:/silo-home-v1.part")
        transfer.AddHeader("Range","bytes=0-262143")
        started = transfer.AsyncGetToFile("tmp:/silo-home-v1.part")
    end if
    if not started then return invalid
    clock = CreateObject("roTimespan")
    clock.Mark()
    while clock.TotalMilliseconds() < 1500 and m.cacheClock.TotalMilliseconds() < 6000
        if not HomeCacheCurrent() then exit while
        oversized = false
        if not head
            for each path in ["tmp:/silo-home-v1.part","tmp:/silo-home-v1.part.tmp"]
                if HomeCacheFileSize(path) > 262144 then oversized = true
            end for
        end if
        if oversized then exit while
        event = wait(50,port)
        if type(event) = "roUrlEvent"
            if event.GetSourceIdentity() = transfer.GetIdentity()
                return {status:event.GetResponseCode(),headers:event.GetResponseHeaders()}
            end if
        end if
    end while
    transfer.AsyncCancel()
    HomeCacheDelete("tmp:/silo-home-v1.part")
    HomeCacheDelete("tmp:/silo-home-v1.part.tmp")
    return invalid
end function

function HomeCacheDownload(url as String, path as String) as Boolean
    ' Signed URLs are volatile Task input. No app headers follow CDN redirects.
    if Len(url) > 4096 then return false
    if Left(url,1) = "/" and Left(url,2) <> "//" then url = HomeCacheText(m.cacheSession,"baseUrl")+url
    if not CreateObject("roRegex","^https://[^/@?# ]+(/[^ ]*)?$","").IsMatch(url) then return false
    head = HomeCacheTransfer(url,true)
    if head <> invalid
        length = Val(HomeCacheHeader(head.headers,"content-length"))
        if length > 262144 then return false
        if head.status <> 200 and head.status <> 405 and head.status <> 501 then return false
    end if
    response = HomeCacheTransfer(url,false)
    if response = invalid then return false
    if response.status <> 200 and response.status <> 206 then return false
    if Val(HomeCacheHeader(response.headers,"content-length")) > 262144 then return false
    bytes = HomeCacheFileBytes("tmp:/silo-home-v1.part",262144)
    if bytes = invalid then return false
    if response.status = 206
        expected = "bytes 0-"+(bytes.Count()-1).ToStr()+"/"+bytes.Count().ToStr()
        if HomeCacheHeader(response.headers,"content-range") <> expected then return false
    end if
    if not HomeCacheImageValid(bytes) or not HomeCacheCurrent() then return false
    return bytes.WriteFile(path)
end function
