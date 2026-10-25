' Exact physical facts and private client intent; no allocator or native writes.
function PrField(v as Dynamic,k as String,f as Dynamic) as Dynamic
    if type(v)<>"roAssociativeArray" then return f
    if not v.DoesExist(k) then return f
    return v[k]
end function
function PrText(v as Dynamic,n as Integer) as Boolean
    if type(v)<>"String" and type(v)<>"roString" then return false
    if Len(v)=0 or Len(v)>n or Instr(1,v,"://")>0 or Left(LCase(v),5)="data:" then return false
    for i=1 to Len(v)
        c=Asc(Mid(v,i,1))
        if c<32 or c=127 then return false
    end for
    return true
end function
function PrNumber(v as Dynamic,max as Double,whole = false as Boolean) as Boolean
    k=type(v)
    if k<>"Integer" and k<>"roInt" and k<>"roInteger" and k<>"LongInteger" and k<>"roLongInteger" and k<>"Float" and k<>"roFloat" and k<>"Double" and k<>"roDouble" then return false
    if v<>v or v<0 or v>max then return false
    if whole then return v=Int(v)
    return true
end function
function PrBool(v as Dynamic) as Boolean
    return type(v)="Boolean" or type(v)="roBoolean"
end function
function PrCopy(v as Object) as Object
    ' Trusted params/validated intent retain normal case-insensitive lookup.
    out={}
    for each k in v
        out[k]=v[k]
    end for
    return out
end function
function PrFile(detail as Dynamic,versionId as Dynamic,target as Dynamic) as Dynamic
    complete=PrField(detail,"versionsComplete",invalid)
    if not PrBool(complete) then return invalid
    if not complete then return invalid
    item=PrField(detail,"item",invalid):versions=PrField(detail,"versions",invalid)
    if not PrText(versionId,256) or not PrNumber(target,604800000) then return invalid
    source=PrField(item,"sourceId",invalid):id=PrField(item,"itemId",invalid)
    if not PrText(source,512) or Left(source,5)<>"plex:" or not PrText(id,128) then return invalid
    if type(versions)<>"roArray" or versions.Count()>16 then return invalid
    selected=invalid:index=-1
    for i=0 to versions.Count()-1
        row=versions[i]
        if PrField(row,"versionId",invalid)=versionId
            if selected<>invalid then return invalid
            selected=row:index=i
        end if
    end for
    if selected=invalid then return invalid
    for each field in ["sourceId","itemId"]
        if PrField(selected,field,invalid)<>item[field] then return invalid
    end for
    for each field in ["mediaId","partId"]
        if not PrText(PrField(selected,field,invalid),128) then return invalid
    end for
    for each field in ["mediaIndex","partIndex","partCount"]
        if not PrNumber(PrField(selected,field,invalid),2147483646,true) then return invalid
    end for
    if selected.partCount<>1 or selected.partIndex<>0 then return invalid
    duration=PrField(selected,"durationMs",invalid)
    if not PrNumber(duration,604800000) or duration<=0 or target>=duration then return invalid
    return {sourceId:source,itemId:id,versionId:versionId,mediaId:selected.mediaId,partId:selected.partId,
        versionIndex:index,mediaIndex:selected.mediaIndex,partIndex:selected.partIndex,durationMs:duration,version:selected}
end function
function PrIdentity(file as Dynamic) as Dynamic
    if type(file)<>"roAssociativeArray" then return invalid
    out={}
    for each k in ["sourceId","itemId","mediaId","partId","versionId"]
        if not PrText(PrField(file,k,invalid),512) then return invalid
        out[k]=file[k]
    end for
    return out
end function
function PrSameFile(a as Dynamic,b as Dynamic) as Boolean
    a=PrIdentity(a):b=PrIdentity(b)
    if a=invalid or b=invalid then return false
    for each k in a
        if a[k]<>b[k] then return false
    end for
    return true
end function
function PrAudioKnown(version as Object,id as Dynamic) as Boolean
    if not PrText(id,20) then return false
    if not CreateObject("roRegex","^[0-9]{1,20}$","").IsMatch(id) then return false
    rows=PrField(version,"audio",invalid)
    if type(rows)<>"roArray" or rows.Count()>32 then return false
    matches=0
    for each row in rows
        if PrField(row,"id",invalid)=id then matches++
    end for
    return matches=1
end function
function PrIntent(raw as Dynamic,source as Dynamic,itemId as Dynamic,versionId as Dynamic) as Dynamic
    if type(raw)<>"roAssociativeArray" then return invalid
    if PrField(raw,"schemaVersion",invalid)<>1 or not PrNumber(PrField(raw,"schemaVersion",invalid),1,true) then return invalid
    if PrField(raw,"sourceId",invalid)<>source or PrField(raw,"itemId",invalid)<>itemId or PrField(raw,"versionId",invalid)<>versionId then return invalid
    if not PrText(source,512) or not PrText(itemId,128) or not PrText(versionId,256) then return invalid
    if not PrNumber(PrField(raw,"owedStartMs",invalid),604800000) or not PrBool(PrField(raw,"forceCompatible",invalid)) then return invalid
    allowed={schemaversion:true,sourceid:true,itemid:true,versionid:true,owedstartms:true,forcecompatible:true,maxvideobitrate:true,videoresolution:true,audiostreamid:true}
    seen={}
    for each k in raw
        folded=LCase(k)
        if not allowed.DoesExist(folded) or seen.DoesExist(folded) then return invalid
        seen[folded]=true
    end for
    if raw.DoesExist("maxVideoBitrate")
        if not PrNumber(raw.maxVideoBitrate,200000,true) or raw.maxVideoBitrate<1 then return invalid
    end if
    if raw.DoesExist("videoResolution")
        if not PrText(raw.videoResolution,12) then return invalid
        if raw.videoResolution<>"1280x720" and raw.videoResolution<>"1920x1080" and raw.videoResolution<>"3840x2160" then return invalid
    end if
    if raw.DoesExist("audioStreamId")
        if not PrText(raw.audioStreamId,20) or not CreateObject("roRegex","^[0-9]{1,20}$","").IsMatch(raw.audioStreamId) then return invalid
    end if
    return PrCopy(raw)
end function
function PrIngress(params as Object,plan as Object,detail as Object) as Dynamic
    source=PrField(plan,"sourceId",invalid):item=PrField(plan,"itemId",invalid):version=PrField(plan,"versionId",invalid)
    start=PrField(params,"startPositionMs",PrField(plan,"startPositionMs",invalid))
    raw={schemaVersion:1,sourceId:source,itemId:item,versionId:version,owedStartMs:start,forceCompatible:PrField(params,"forceTranscode",false)}
    for each k in ["maxVideoBitrate","videoResolution","audioStreamId"]
        if params.DoesExist(k) then raw[k]=params[k]
    end for
    result=PrIntent(raw,source,item,version)
    if result=invalid then return invalid
    file=PrFile(detail,version,start)
    if file=invalid then return invalid
    if result.DoesExist("audioStreamId")
        if not PrAudioKnown(file.version,result.audioStreamId) then return invalid
    end if
    return result
end function
function PrQualityRows(intent as Object) as Object
    rows=[{handle:"pr-1-0",label:"Auto",cap:invalid,resolution:"",selected:false},
        {handle:"pr-1-1",label:"Up to 720p / 4 Mbps",cap:4000,resolution:"1280x720",selected:false},
        {handle:"pr-1-2",label:"Up to 1080p / 8 Mbps",cap:8000,resolution:"1920x1080",selected:false},
        {handle:"pr-1-3",label:"Up to 1080p / 20 Mbps",cap:20000,resolution:"1920x1080",selected:false}]
    for each row in rows
        row.selected=PrField(intent,"maxVideoBitrate",invalid)=row.cap and PrField(intent,"videoResolution","")=row.resolution
    end for
    return rows
end function
function PrVersionRows(detail as Object,current as String) as Object
    rows=[]:versions=PrField(detail,"versions",[])
    if type(versions)<>"roArray" or versions.Count()>16 then return rows
    for each version in versions
        id=PrField(version,"versionId",invalid)
        file=PrFile(detail,id,0)
        if file<>invalid
            label="File "+(rows.Count()+1).ToStr()
            height=PrField(version,"height",invalid)
            if PrNumber(height,2160,true) and height>0 then label=height.ToStr()+"p source"
            container=PrField(version,"container",""):codec=PrField(version,"videoCodec","")
            if PrText(container,12) then label+=" / "+container
            if PrText(codec,16) then label+=" / "+codec
            rows.Push({handle:"pr-1-"+rows.Count().ToStr(),label:Left(label,80),file:file,selected:id=current})
        end if
    end for
    return rows
end function
function PrParams(state as Object,row as Object,target as Double) as Dynamic
    id=state.versionId
    if state.changeKind="version" then id=row.file.versionId
    file=PrFile(state.detail,id,target)
    if file=invalid then return invalid
    intent=PrIntent(state.clientIntent,state.scope.sourceId,state.itemId,state.versionId)
    if intent=invalid then return invalid
    if id<>state.versionId and intent.DoesExist("audioStreamId") then return invalid
    if intent.DoesExist("audioStreamId")
        if not PrAudioKnown(file.version,intent.audioStreamId) then return invalid
    end if
    params={itemId:state.itemId,detail:state.detail,versionIndex:file.versionIndex,partIndex:file.partIndex,
        versionId:id,startPositionMs:target,replacementFile:PrIdentity(file),forceTranscode:intent.forceCompatible}
    for each k in ["maxVideoBitrate","videoResolution","audioStreamId"]
        if intent.DoesExist(k) then params[k]=intent[k]
    end for
    if state.changeKind="audio"
        params["audioStreamId"]=row.id:params["forceTranscode"]=true
    else if state.changeKind="quality"
        params.Delete("maxVideoBitrate"):params.Delete("videoResolution")
        if row.cap<>invalid
            params["maxVideoBitrate"]=row.cap:params["videoResolution"]=row.resolution
        end if
    end if
    return params
end function
