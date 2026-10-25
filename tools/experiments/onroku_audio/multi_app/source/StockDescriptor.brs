' Pure stock-server descriptor policy. Does not send requests or credentials.
function QaStockMediaReference(base as String, reference as String, origin as String, routeItemId as String, mediaSourceId as String, sessionId as String) as Dynamic
    if not CreateObject("roRegex","^https?://[A-Za-z0-9.-]+(:[0-9]{1,5})?$","").IsMatch(origin) then return invalid
    for each identity in [routeItemId,mediaSourceId,sessionId]
        if not CreateObject("roRegex","^[A-Za-z0-9_-]{1,128}$","").IsMatch(identity) then return invalid
    end for
    queryA="MediaSourceId="+mediaSourceId+"&PlaySessionId="+sessionId
    queryB="PlaySessionId="+sessionId+"&MediaSourceId="+mediaSourceId
    baseParts=base.Split("?"):refParts=reference.Split("?")
    if baseParts.Count()<>2 or refParts.Count()<>2 then return invalid
    if baseParts[1]<>queryA and baseParts[1]<>queryB then return invalid
    if refParts[1]<>queryA and refParts[1]<>queryB then return invalid
    prefix=origin+"/Videos/"+routeItemId+"/remux-dv-v1/"
    if Left(baseParts[0],Len(prefix))<>prefix then return invalid
    tail=Mid(baseParts[0],Len(prefix)+1)
    if tail<>"master.m3u8" and tail<>"hls/"+sessionId+"/stream.m3u8" then return invalid
    resolved=QaRemoteReference(baseParts[0],refParts[0])
    if resolved=invalid then return invalid
    if Left(resolved,Len(prefix))<>prefix then return invalid
    tail=Mid(resolved,Len(prefix)+1)
    if tail<>"master.m3u8"
        child="hls/"+sessionId+"/"
        if Left(tail,Len(child))<>child then return invalid
        leaf=Mid(tail,Len(child)+1)
        if leaf<>"stream.m3u8" and leaf<>"init.mp4" and not CreateObject("roRegex","^[A-Za-z0-9_-]+[.]m4s$","").IsMatch(leaf) then return invalid
    end if
    return resolved+"?"+refParts[1]
end function

' Parse the source snapshot independently of rolling playback readiness.
function QaStockDescriptor(text as String, base as String, origin as String, routeItemId as String, mediaSourceId as String, sessionId as String) as Dynamic
    if Len(text)<1 or Len(text)>1048576 then return invalid
    if QaStockMediaReference(base,base,origin,routeItemId,mediaSourceId,sessionId)=invalid then return invalid
    if Instr(1,base,"/hls/"+sessionId+"/stream.m3u8?")=0 then return invalid
    lines=text.Replace(Chr(13),"").Split(Chr(10))
    if lines[0]<>"#EXTM3U" then return invalid
    q=Chr(34):seenTags={}:duration=invalid:durations=[]:durationMicros=[]:micros=0
    ended=false:eventType=false:startSeen=false:sequenceSeen=false:targetSeen=false
    initUrl=invalid:urls=[]:seenUrls={}
    canonicalQuery="?MediaSourceId="+mediaSourceId+"&PlaySessionId="+sessionId
    for index=1 to lines.Count()-1
        line=lines[index]
        if line<>""
            if ended then return invalid
            if Left(line,1)="#" and Left(line,8)<>"#EXTINF:"
                if duration<>invalid then return invalid
                tag=line.Split(":")[0]
                if seenTags.DoesExist(tag) then return invalid
                seenTags[tag]=true
            end if
            if Left(line,13)="#EXT-X-START:"
                if startSeen then return invalid
                match=CreateObject("roRegex","^#EXT-X-START:TIME-OFFSET=(0([.][0-9]{1,6})?),PRECISE=YES$","").Match(line)
                if match.Count()=0 then return invalid
                if Val(match[1])>0.01 then return invalid
                startSeen=true
            else if Left(line,22)="#EXT-X-MEDIA-SEQUENCE:"
                if sequenceSeen or line<>"#EXT-X-MEDIA-SEQUENCE:0" then return invalid
                sequenceSeen=true
            else if Left(line,22)="#EXT-X-TARGETDURATION:"
                if not CreateObject("roRegex","^#EXT-X-TARGETDURATION:([1-9]|[12][0-9]|30)$","").IsMatch(line) then return invalid
                targetSeen=true
                targetDuration=Val(Mid(line,23))
            else if line="#EXT-X-PLAYLIST-TYPE:EVENT"
                eventType=true
            else if line="#EXT-X-ENDLIST"
                ended=true
            else if Left(line,11)="#EXT-X-MAP:"
                if initUrl<>invalid or urls.Count()>0 then return invalid
                match=CreateObject("roRegex","^#EXT-X-MAP:URI="+q+"([^"+q+"]+)"+q+"$","").Match(line)
                if match.Count()=0 then return invalid
                resolved=QaStockMediaReference(base,match[1],origin,routeItemId,mediaSourceId,sessionId)
                if resolved=invalid then return invalid
                path=resolved.Split("?")[0]
                if Right(path,9)<>"/init.mp4" then return invalid
                initUrl=path+canonicalQuery
            else if Left(line,8)="#EXTINF:"
                if initUrl=invalid or duration<>invalid then return invalid
                match=CreateObject("roRegex","^#EXTINF:([0-9]{1,2}([.][0-9]{1,6})?),$","").Match(line)
                if match.Count()=0 then return invalid
                duration=Val(match[1])
                decimal=match[1].Split(".")
                micros=Int(Val(decimal[0]))*1000000
                if decimal.Count()=2 then micros+=Int(Val(Left(decimal[1]+"000000",6)))
                if micros<=0 or micros>30000000 then return invalid
            else if Left(line,1)<>"#"
                if duration=invalid then return invalid
                resolved=QaStockMediaReference(base,line,origin,routeItemId,mediaSourceId,sessionId)
                if resolved=invalid then return invalid
                path=resolved.Split("?")[0]
                if Right(path,4)<>".m4s" or seenUrls.DoesExist(path) then return invalid
                if urls.Count()>=8192 then return invalid
                seenUrls[path]=true:urls.Push(path+canonicalQuery):durations.Push(duration):durationMicros.Push(micros):duration=invalid
            else
                if not CreateObject("roRegex","^#EXT-X-(VERSION:[67]|PLAYLIST-TYPE:VOD|INDEPENDENT-SEGMENTS)$","").IsMatch(line) then return invalid
            end if
        end if
    end for
    if duration<>invalid or not sequenceSeen or not targetSeen or (not ended and not eventType) then return invalid
    if ended and (initUrl=invalid or urls.Count()=0) then return invalid
    return {targetDuration:targetDuration,init:initUrl,fragments:urls,durations:durations,durationMicros:durationMicros,availableCount:urls.Count(),pending:urls.Count()<3,ended:ended,sequence:0,binding:origin+"/Videos/"+routeItemId+"/remux-dv-v1/hls/"+sessionId+"/stream.m3u8"+canonicalQuery}
end function

' Refreshes may repeat or append. Published source identity/timing cannot drift.
' Upstream EVENT target metadata may grow as longer segments arrive. Local
' publication targets stay fixed and every admitted pair is checked in Rolling.
function QaStockDescriptorRefresh(previous as Dynamic, nextDescriptor as Dynamic) as Dynamic
    if previous=invalid or nextDescriptor=invalid then return invalid
    if previous.binding<>nextDescriptor.binding or previous.sequence<>nextDescriptor.sequence then return invalid
    if previous.init<>invalid and previous.init<>nextDescriptor.init then return invalid
    oldCount=previous.fragments.Count():newCount=nextDescriptor.fragments.Count()
    if newCount<oldCount then return invalid
    if previous.ended and (not nextDescriptor.ended or oldCount<>newCount) then return invalid
    for index=0 to oldCount-1
        if previous.fragments[index]<>nextDescriptor.fragments[index] or previous.durationMicros[index]<>nextDescriptor.durationMicros[index] then return invalid
    end for
    return nextDescriptor
end function

' Runtime credential shape only; every actual URL is separately bound before send.
function QaStockContextValid(c as Dynamic) as Boolean
    if Type(c)<>"roAssociativeArray" then return false
    for each field in ["origin","routeItemId","mediaSourceId","sessionId","token"]
        if Type(c.Lookup(field))<>"roString" and Type(c.Lookup(field))<>"String" then return false
    end for
    if Len(c.token)<1 or Len(c.token)>4096 then return false
    if c.DoesExist("transportPolicy") or c.DoesExist("transportEvidence")
        if not SiloStockTransportPolicyValid(c.transportPolicy,c.transportEvidence,c.origin) then return false
        if c.authMode<>"bearer" then return false
        if c.transportPolicy="native-bearer-origin-scope-v1"
            if not SiloNativeBearerTransportQualified(c.origin,CreateObject("roDeviceInfo")) then return false
        end if
    else
        ' Legacy assertion is restricted to standalone private fixture tooling.
        if c.controlledNoRedirect<>true or c.fixtureOnly<>true then return false
    end if
    if Instr(1,c.token,Chr(10))>0 or Instr(1,c.token,Chr(13))>0 then return false
    if c.DoesExist("authMode")
        if Type(c.authMode)<>"roString" and Type(c.authMode)<>"String" then return false
        if c.authMode<>"emby" and c.authMode<>"bearer" then return false
    end if
    return true
end function

' Fixed choices only: no caller-controlled header name or URL token.
function QaStockAuthHeader(c as Dynamic) as Dynamic
    if not QaStockContextValid(c) then return invalid
    if c.DoesExist("authMode") and c.authMode="bearer" then return {name:"Authorization",value:"Bearer "+c.token}
    return {name:"X-Emby-Token",value:c.token}
end function
