' Private Task-only selected text fetch. Never pass this module's plan to SceneGraph.
function SiloSubtitleFetchPlan(receipt as Dynamic, session as Dynamic, owner as Dynamic) as Object
    refused = {ok:false,errorCode:"invalid_subtitle_receipt"}
    if type(receipt) <> "roAssociativeArray" or type(session) <> "roAssociativeArray" or type(owner) <> "roAssociativeArray" then return refused
    if SpField(receipt,"ok") <> true then return refused
    public = SpField(receipt,"public")
    artifact = SpField(receipt,"privateArtifact")
    if type(public) <> "roAssociativeArray" or type(artifact) <> "roAssociativeArray" then return refused
    if SpField(public,"kind") <> "sidecar_pending" or SpField(public,"renderingReady") <> false then return refused
    format = SpField(public,"format")
    mime = SpField(public,"mimeType")
    if format <> "vtt" and format <> "srt" then return refused
    if format = "vtt" and mime <> "text/vtt" then return refused
    if format = "srt" and mime <> "application/x-subrip" then return refused
    if SpField(artifact,"format") <> format or SpField(artifact,"mimeType") <> mime then return refused
    if not SpNumber(SpField(artifact,"timingOriginSeconds"),604800) then return refused
    if not SpText(SpField(owner,"sourceId"),512) or not SpText(SpField(owner,"profileId"),256,true) then return refused
    if not SpOpaque(SpField(owner,"planAttemptKey"),256) then return refused
    if not SpOpaque(SpField(owner,"fileId"),32) or not SpText(SpField(owner,"sessionId"),128) then return refused
    if not SpNumber(SpField(owner,"selectedOrdinal"),127,true) then return refused
    if not SpNumber(SpField(owner,"generation"),2147483646,true) or not SpNumber(SpField(owner,"requestId"),2147483646,true) then return refused
    if not SpNumber(SpField(owner,"sessionRevision"),2147483646,true) then return refused
    offsetMs = SpField(owner,"timelineOffsetMs")
    if not SpNumber(offsetMs,604800000,true) then return refused
    if SpField(public,"combinedIndex") <> owner.selectedOrdinal then return refused
    trackId = "file:" + owner.fileId + ":subtitle:" + Int(owner.selectedOrdinal).ToStr()
    if SpField(public,"trackId") <> trackId then return refused
    if SpField(session,"sourceId") <> owner.sourceId or SpField(session,"profileId") <> owner.profileId then return refused
    token = SpField(session,"accessToken")
    if not SpText(token,4096) or not SpText(SpField(session,"baseUrl"),1024) then return refused
    url = SpField(artifact,"url")
    if not SpText(url,2048) then return refused
    base = SiloUrlParts(session.baseUrl)
    address = SiloUrlParts(url)
    if not base.ok or not address.ok or base.origin <> address.origin then return refused
    if Instr(1,url,"#") > 0 or Instr(1,url,Chr(92)) > 0 then return refused
    if not SpSubtitleOwnedArtifact(address.path,owner.sessionId,owner.fileId,owner.selectedOrdinal,format) then return refused
    if format = "srt" and offsetMs > 0 then return {ok:false,errorCode:"subtitle_timing_unsupported"}
    fetchUrl = SiloSubtitleFetchUrl(url,format,offsetMs)
    if fetchUrl = "" then return refused
    finalAddress = SiloUrlParts(fetchUrl)
    if not finalAddress.ok or finalAddress.origin <> base.origin then return refused
    if not SpSubtitleOwnedArtifact(finalAddress.path,owner.sessionId,owner.fileId,owner.selectedOrdinal,format) then return refused
    safeOwner = {sourceId:owner.sourceId,profileId:owner.profileId,generation:owner.generation,requestId:owner.requestId,sessionRevision:owner.sessionRevision,sessionId:owner.sessionId,planAttemptKey:owner.planAttemptKey,fileId:owner.fileId,selectedOrdinal:owner.selectedOrdinal,timelineOffsetMs:offsetMs}
    return {ok:true,url:fetchUrl,token:token,format:format,mimeType:mime,timingOriginSeconds:artifact.timingOriginSeconds,owner:safeOwner}
end function

' Task-only admission for a prebound whole-track native VTT. This returns a
' pending transport descriptor, never a rendering receipt or an HTTP response.
function SiloSubtitleTransportPlan(receipt as Dynamic, session as Dynamic, owner as Dynamic, avPlan as Dynamic) as Object
    refused = {ok:false,errorCode:"invalid_subtitle_transport"}
    prepared = SiloSubtitleFetchPlan(receipt,session,owner)
    if not prepared.ok then return refused
    if prepared.format <> "vtt" then return {ok:false,errorCode:"subtitle_native_unsupported"}
    if type(avPlan) <> "roAssociativeArray" then return refused
    context = SpField(avPlan,"siloPlayback")
    if type(context) <> "roAssociativeArray" or SpField(context,"mediaAuthMode") <> "api_header_v1" then return refused
    if not SpText(SpField(owner,"sessionId"),128) or not CreateObject("roRegex","^[A-Za-z0-9_.-]+$","").IsMatch(owner.sessionId) then return refused
    if owner.sessionId = "." or owner.sessionId = ".." then return refused
    fileId = SpField(owner,"fileId")
    if not SpText(fileId,32) or fileId = "." or fileId = ".." then return refused
    if not CreateObject("roRegex","^[A-Za-z0-9._-]+$","").IsMatch(fileId) then return refused
    for each name in ["sessionId","sourceId","planAttemptKey"]
        if SpField(avPlan,name) <> SpField(owner,name) then return refused
    end for
    for each name in ["sourceId","profileId","fileId","sessionId","sessionRevision","planAttemptKey"]
        if SpField(context,name) <> SpField(owner,name) then return refused
    end for
    if SpField(avPlan,"versionId") <> fileId then return refused
    if not SpNumber(SpField(avPlan,"timelineOffsetMs"),604800000,true) then return refused
    if avPlan.timelineOffsetMs <> owner.timelineOffsetMs then return refused
    headers = SpField(avPlan,"headers")
    if type(headers) <> "roAssociativeArray" or headers.Count() <> 1 or not headers.DoesExist("Authorization") then return refused
    if headers.Authorization <> "Bearer " + prepared.token then return refused
    base = SiloUrlParts(session.baseUrl)
    caption = SiloUrlParts(prepared.url)
    url = SpField(avPlan,"url")
    if not SpText(url,2048) or Instr(1,url,"#") > 0 then return refused
    if not base.ok or not caption.ok or caption.origin <> base.origin then return refused
    if not SiloHeaderMediaUrlAllowed(url,session.baseUrl,owner.sessionId,fileId) then return refused
    return {ok:true,transport:{uri:prepared.url,format:prepared.format,mimeType:prepared.mimeType,timingOriginSeconds:prepared.timingOriginSeconds,apiOrigin:base.origin,authMode:"api_header_v1",owner:prepared.owner}}
end function

' The server publishes only these identity fields. Unknown fields (including
' credential-looking fields), encoded keys and duplicates never reach HTTP.
function SiloSubtitleFetchUrl(raw as String, format as String, offsetMs as Dynamic) as String
    question = Instr(1,raw,"?")
    if question = 0 then return ""
    path = Left(raw,question-1)
    fields = Mid(raw,question+1).Tokenize("&")
    if fields.Count() = 0 or fields.Count() > 6 then return ""
    seen = {}
    kept = []
    for index = 0 to fields.Count()-1
        field = fields[index]
        if not SpText(field,256) then return ""
        equals = Instr(1,field,"=")
        if equals < 2 then return ""
        name = Left(field,equals-1)
        value = Mid(field,equals+1)
        if not CreateObject("roRegex","^[a-z_]+$","").IsMatch(name) or seen.DoesExist(name) then return ""
        seen[name] = true
        if name = "file_id"
            if index <> 0 then return ""
        else if name = "original"
            if format <> "srt" or value <> "1" then return ""
        else if name = "downloaded_subtitle_id"
            if not CreateObject("roRegex","^[1-9][0-9]{0,15}$","").IsMatch(value) then return ""
        else if name = "embedded_stream_index"
            if not CreateObject("roRegex","^[0-9]{1,4}$","").IsMatch(value) then return ""
        else if name = "external_subtitle_key"
            if not CreateObject("roRegex","^[0-9a-f]{64}$","").IsMatch(value) then return ""
        else if name = "timestamp_offset"
            if format <> "vtt" or not CreateObject("roRegex","^-?[0-9]{1,8}([.][0-9]{1,3})?$","").IsMatch(value) then return ""
        else
            return ""
        end if
        if name <> "timestamp_offset" then kept.Push(field)
    end for
    if kept.Count() = 0 then return ""
    result = path + "?" + kept[0]
    for index = 1 to kept.Count()-1
        result += "&" + kept[index]
    end for
    if format = "vtt" and offsetMs > 0 then result += "&timestamp_offset=" + SiloSubtitleOffsetText(offsetMs)
    if Len(result) > 2048 then return ""
    return result
end function

function SiloSubtitleOffsetText(offsetMs as Dynamic) as String
    whole = Int(offsetMs / 1000)
    remainder = offsetMs - whole * 1000
    result = "-" + whole.ToStr()
    if remainder = 0 then return result
    fraction = Right("00" + Int(remainder).ToStr(),3)
    while Right(fraction,1) = "0"
        fraction = Left(fraction,Len(fraction)-1)
    end while
    return result + "." + fraction
end function

function TaskSiloSubtitleFetch(receipt as Dynamic, session as Dynamic, owner as Dynamic) as Object
    plan = SiloSubtitleFetchPlan(receipt,session,owner)
    if plan.ok <> true then return {ok:false,errorCode:plan.errorCode}
    if not SiloSubtitleCurrent(plan.owner,session) then return {ok:false,errorCode:"cancelled"}
    partial = "":final = ""
    try
    stem = SiloSubtitleNewStem()
    if stem = "" then return {ok:false,errorCode:"storage_error"}
    partial = stem + ".part"
    final = stem + "." + plan.format
    clock = SiloSubtitleClock()
    clock.Mark()
    transferred = SiloSubtitleTransport(plan,partial,clock)
    if transferred.ok <> true
        SiloSubtitleDelete(partial)
        SiloSubtitleDelete(final)
        return {ok:false,errorCode:transferred.errorCode}
    end if
    if not SiloSubtitleCurrent(plan.owner,session) or clock.TotalMilliseconds() >= 10000
        SiloSubtitleDelete(partial)
        SiloSubtitleDelete(final)
        return {ok:false,errorCode:"cancelled"}
    end if
    inspected = SiloSubtitleInspect(partial,plan.format)
    if inspected.ok <> true
        SiloSubtitleDelete(partial)
        SiloSubtitleDelete(final)
        return {ok:false,errorCode:inspected.errorCode}
    end if
    if not SiloSubtitleCurrent(plan.owner,session) or clock.TotalMilliseconds() >= 10000
        SiloSubtitleDelete(partial)
        SiloSubtitleDelete(final)
        return {ok:false,errorCode:"cancelled"}
    end if
    if not SiloSubtitleRename(partial,final)
        SiloSubtitleDelete(partial)
        SiloSubtitleDelete(final)
        return {ok:false,errorCode:"storage_error"}
    end if
    SiloSubtitleDelete(partial)
    if not SiloSubtitleCurrent(plan.owner,session) or clock.TotalMilliseconds() >= 10000
        SiloSubtitleDelete(final)
        return {ok:false,errorCode:"cancelled"}
    end if
    return {ok:true,uri:final,format:plan.format,mimeType:plan.mimeType,timingOriginSeconds:plan.timingOriginSeconds,owner:plan.owner}
    catch exception
        SiloSubtitleDelete(partial)
        SiloSubtitleDelete(final)
        return {ok:false,errorCode:"task_failed"}
    end try
end function

function SiloSubtitleClock() as Object
    return CreateObject("roTimespan")
end function

function SiloSubtitleCurrent(owner as Object, session as Object) as Boolean
    if m.top.cancelled = true then return false
    if SessionRevision("silo") <> owner.sessionRevision then return false
    current = LoadSession("silo")
    if type(current) <> "roAssociativeArray" then return false
    return SpField(current,"sourceId") = owner.sourceId and SpField(current,"profileId") = owner.profileId and SpField(current,"accessToken") = SpField(session,"accessToken")
end function

function SiloSubtitleNewStem() as String
    fs = SiloSubtitleFileSystem()
    for attempt = 1 to 4
        nonce = LCase(SiloSubtitleUuid())
        if CreateObject("roRegex","^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$","").IsMatch(nonce)
            stem = "tmp:/silo-subtitle-" + nonce
            if SiloSubtitleStat(fs,stem + ".part") = invalid and SiloSubtitleStat(fs,stem + ".part.tmp") = invalid and SiloSubtitleStat(fs,stem + ".vtt") = invalid and SiloSubtitleStat(fs,stem + ".srt") = invalid then return stem
        end if
    end for
    return ""
end function

function SiloSubtitleTransport(plan as Object, path as String, clock as Object) as Object
    transfer = invalid
    transferArmed = false
    try
    transfer = SiloSubtitleNewTransfer()
    port = SiloSubtitleNewPort()
    if transfer = invalid or port = invalid then return {ok:false,errorCode:"network_unavailable"}
    transfer.SetMessagePort(port)
    transfer.SetUrl(plan.url)
    transfer.RetainBodyOnError(false)
    if Left(plan.url,8) = "https://"
        if not transfer.SetCertificatesFile("common:/certs/ca-bundle.crt") then return {ok:false,errorCode:"tls_error"}
        if not transfer.EnablePeerVerification(true) then return {ok:false,errorCode:"tls_error"}
        if not transfer.EnableHostVerification(true) then return {ok:false,errorCode:"tls_error"}
    end if
    if not transfer.AddHeader("Authorization","Bearer " + plan.token) then return {ok:false,errorCode:"network_error"}
    if not SiloSubtitleTransferCurrent(plan) then return {ok:false,errorCode:"cancelled"}
    transferArmed = true
    if not transfer.AsyncGetToFile(path) then return {ok:false,errorCode:"network_error"}
    while clock.TotalMilliseconds() < 10000
        if not SiloSubtitleTransferCurrent(plan)
            transfer.AsyncCancel()
            return {ok:false,errorCode:"cancelled"}
        end if
        if SiloSubtitleTooLarge(path)
            transfer.AsyncCancel()
            return {ok:false,errorCode:"subtitle_too_large"}
        end if
        event = SiloSubtitleWait(port)
        if SiloSubtitleEventMatches(event,transfer)
            if event.GetResponseCode() <> 200 then return {ok:false,errorCode:"network_error"}
            if not SiloSubtitleMimeMatches(plan.mimeType,event.GetResponseHeaders()) then return {ok:false,errorCode:"invalid_subtitle_response"}
            if SiloSubtitleTooLarge(path) then return {ok:false,errorCode:"subtitle_too_large"}
            return {ok:true}
        end if
    end while
    transfer.AsyncCancel()
    return {ok:false,errorCode:"network_timeout"}
    catch exception
        if transferArmed and transfer <> invalid
            try
                transfer.AsyncCancel()
            catch cleanupException
            end try
        end if
        return {ok:false,errorCode:"task_failed"}
    end try
end function

function SiloSubtitleNewTransfer() as Object
    return CreateObject("roUrlTransfer")
end function

function SiloSubtitleNewPort() as Object
    return CreateObject("roMessagePort")
end function

function SiloSubtitleWait(port as Object) as Dynamic
    return wait(100,port)
end function

function SiloSubtitleEventMatches(event as Dynamic, transfer as Object) as Boolean
    return SiloSubtitleEventType(event) = "roUrlEvent" and event.GetSourceIdentity() = transfer.GetIdentity()
end function

function SiloSubtitleEventType(event as Dynamic) as String
    return type(event)
end function

function SiloSubtitleFileSystem() as Object
    return CreateObject("roFileSystem")
end function

function SiloSubtitleUuid() as String
    return CreateObject("roDeviceInfo").GetRandomUUID()
end function

function SiloSubtitleRead(path as String) as String
    return ReadAsciiFile(path)
end function

function SiloSubtitleMimeMatches(expected as String, headers as Dynamic) as Boolean
    if type(headers) <> "roAssociativeArray" then return false
    found = false
    for each name in headers
        if LCase(name) = "content-type"
            value = headers[name]
            if not SpText(value,128) or found then return false
            parts = value.Tokenize(";")
            if parts.Count() = 0 then return false
            first = LCase(parts[0].Trim())
            if first <> expected then return false
            found = true
        end if
    end for
    return found
end function

function SiloSubtitleTooLarge(path as String) as Boolean
    fs = SiloSubtitleFileSystem()
    total = 0
    for each candidate in [path,path + ".tmp"]
        stat = SiloSubtitleStat(fs,candidate)
        if type(stat) = "roAssociativeArray"
            size = SpField(stat,"size")
            if not SpNumber(size,1048576,true) then return true
            total += size
            if total > 1048576 then return true
        end if
    end for
    return false
end function

function SiloSubtitleInspect(path as String, format as String) as Object
    fs = SiloSubtitleFileSystem()
    stat = SiloSubtitleStat(fs,path)
    if type(stat) <> "roAssociativeArray" then return {ok:false,errorCode:"storage_error"}
    size = SpField(stat,"size")
    if not SpNumber(size,1048576,true) or size < 12 then return {ok:false,errorCode:"invalid_subtitle_response"}
    body = SiloSubtitleRead(path)
    if type(body) <> "String" and type(body) <> "roString" then return {ok:false,errorCode:"storage_error"}
    if Len(body) < 12 or Len(body) > 1048576 then return {ok:false,errorCode:"invalid_subtitle_response"}
    if SiloSubtitleTextSignature(body,format) then return {ok:true}
    return {ok:false,errorCode:"invalid_subtitle_response"}
end function

function SiloSubtitleTextSignature(body as String, format as String) as Boolean
    if Len(body) < 12 or Len(body) > 1048576 then return false
    if Left(body,3) = Chr(239) + Chr(187) + Chr(191) then body = Mid(body,4)
    if format = "vtt" then return Left(body,6) = "WEBVTT" and (Mid(body,7,1) = Chr(10) or Mid(body,7,1) = Chr(13) or Mid(body,7,1) = " ")
    if format = "srt" then return CreateObject("roRegex","^[0-9]{1,6}\r?\n[0-9]{2}:[0-9]{2}:[0-9]{2}[,.][0-9]{3} *--> *[0-9]{2}:[0-9]{2}:[0-9]{2}[,.][0-9]{3}","").IsMatch(body)
    return false
end function

function SiloSubtitleRename(fromPath as String, toPath as String) as Boolean
    return SiloSubtitleFileSystem().Rename(fromPath,toPath)
end function

sub SiloSubtitleDelete(path as String)
    if type(path) <> "String" and type(path) <> "roString" then return
    if not CreateObject("roRegex","^tmp:/silo-subtitle-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}[.](part|vtt|srt)$","").IsMatch(path) then return
    fs = SiloSubtitleFileSystem()
    fs.Delete(path)
    fs.Delete(path + ".tmp")
end sub


' Native Stat returns an empty associative array for a missing path on the
' qualified Roku. Older/test implementations may return invalid instead.
function SiloSubtitleStat(fs as Object, path as String) as Dynamic
    stat = fs.Stat(path)
    if type(stat) = "roAssociativeArray"
        if stat.Count() = 0 then return invalid
    end if
    return stat
end function

function SiloSubtitleTransferCurrent(plan as Object) as Boolean
    if plan.DoesExist("isCurrent")
        check = plan.isCurrent
        return check()
    end if
    return SiloSubtitleCurrent(plan.owner,{accessToken:plan.token})
end function
