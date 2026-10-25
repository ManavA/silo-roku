' Compat captions use title-clock SRT; HLS WebVTT maps do not establish the
' clock of a side-loaded caption file. The compatibility bearer stays here.
function CompatSubtitleSelection(metadata as Object, proof as Object) as Dynamic
    if SpField(proof,"captionMode") <> "on" then return invalid
    tracks = proof.subtitleInventory
    if tracks.Count() = 0 then return {disposition:"unavailable"}
    index = SpField(metadata.source,"DefaultSubtitleStreamIndex")
    if not SpNumber(index,4095,true) then return invalid
    chosen = invalid
    for each track in tracks
        if track.index = index
            if chosen <> invalid then return invalid
            chosen = track
        end if
    end for
    if chosen = invalid then return invalid
    if not SiloContains(["subrip","srt","webvtt","vtt","ass","ssa","mov_text","text"],chosen.codec) then return invalid
    return {disposition:"selected",track:SpCopy(chosen)}
end function

function CompatSubtitleCurrent() as Boolean
    return m.top.cancelled <> true and m.compatToken <> "" and CompatOwnerCurrent()
end function

function CompatSubtitlePrepare(selection as Object, proof as Object) as Object
    if selection.disposition = "unavailable" then return {ok:true,caption:{disposition:"unavailable"}}
    if not CompatSubtitleCurrent() then return {ok:false,errorCode:"cancelled"}
    base = m.compatSession.compatConnectInfo.publicUrl
    path = "/Videos/"+proof.mediaSourceId+"/"+proof.mediaSourceId+"/Subtitles/"+selection.track.index.ToStr()+"/stream.srt"
    plan = {url:base+path+"?PlaySessionId="+m.compatPlaySession+"&CopyTimestamps=true",token:m.compatToken,mimeType:"application/x-subrip",isCurrent:CompatSubtitleCurrent}
    partial = "":final = ""
    try
        stem = SiloSubtitleNewStem()
        if stem = "" then return {ok:false,errorCode:"storage_error"}
        partial = stem+".part":final = stem+".srt"
        clock = SiloSubtitleClock():clock.Mark()
        outcome = SiloSubtitleTransport(plan,partial,clock)
        if outcome.ok = true then outcome = SiloSubtitleInspect(partial,"srt")
        if outcome.ok = true and (not CompatSubtitleCurrent() or clock.TotalMilliseconds() >= 10000) then outcome = {ok:false,errorCode:"cancelled"}
        if outcome.ok = true
            if not SiloSubtitleRename(partial,final) then outcome = {ok:false,errorCode:"storage_error"}
        end if
        if outcome.ok = true and not CompatSubtitleCurrent() then outcome = {ok:false,errorCode:"cancelled"}
        SiloSubtitleDelete(partial)
        if outcome.ok <> true
            SiloSubtitleDelete(final)
            return outcome
        end if
        return {ok:true,caption:{disposition:"ready",uri:final,track:SpCopy(selection.track)}}
    catch exception
        SiloSubtitleDelete(partial):SiloSubtitleDelete(final)
        return {ok:false,errorCode:"subtitle_fetch_failed"}
    end try
end function

sub CompatSubtitleDelete()
    if SiloObject(m.compatCaption)
        if SpField(m.compatCaption,"disposition") = "ready" then SiloSubtitleDelete(m.compatCaption.uri)
    end if
    m.compatCaption = invalid
end sub
