' Signed photo locations are worker-private, never normalized catalog fields.
function PersonPhotoRequest(personId as String, body as String) as Object
    if Len(body) > 32768 then return {ok:false}
    value = ParseJson(body)
    if type(value) <> "roAssociativeArray" then return {ok:false}
    if ArtworkText(value,"id") <> personId then return {ok:false}
    url = ArtworkText(value,"photo_url")
    if not ArtworkSafeSignedUrl(url) then return {ok:false}
    return {ok:true,method:"GET",url:url,headers:{}}
end function

function PersonPhotoJobValid(job as Dynamic) as Boolean
    if type(job) <> "roAssociativeArray" then return false
    allowed = {sourceId:true,profileId:true,generation:true,visit:true,itemId:true,personId:true,index:true,requestId:true}
    for each key in job
        if not allowed.DoesExist(key) then return false
    end for
    for each key in ["generation","visit","index","requestId"]
        if not ArtworkInteger(ArtworkField(job,key,invalid)) then return false
    end for
    if job.index > 7 then return false
    for each key in ["itemId","personId"]
        if not CreateObject("roRegex", "^[A-Za-z0-9_.:-]{1,128}$", "").IsMatch(ArtworkText(job,key)) then return false
    end for
    if not CreateObject("roRegex", "^[A-Za-z0-9_.:-]{1,128}$", "").IsMatch(ArtworkText(job,"profileId")) then return false
    source = ArtworkText(job,"sourceId")
    if Left(source,5) <> "silo:" or Len(source) > 1024 then return false
    return true
end function
