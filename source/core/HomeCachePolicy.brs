' Restart data is display-only; credentials and progress never enter the projection.
function HomeCacheText(value as Dynamic, key as String) as String
    if type(value) <> "roAssociativeArray" then return ""
    text = value[key]
    if type(text) = "String" or type(text) = "roString" then return text
    return ""
end function

function HomeCacheId(value as String) as Boolean
    return CreateObject("roRegex", "^[A-Za-z0-9_.:-]{1,256}$", "").IsMatch(value) and value <> "." and value <> ".."
end function

function HomeCacheProjection(rows as Dynamic) as Object
    result = {row:invalid,downloads:[]}
    if type(rows) <> "roArray" or rows.Count() = 0 then return result
    ' Cache only the first displayed rail. Personal rows must revalidate.
    row = rows[0]
    kind = HomeCacheText(row,"sectionType")
    if kind = "continue_watching" or kind = "on_deck" or kind = "streaming" or kind = "formats" or kind = "curated" then return result
    if type(row) <> "roAssociativeArray" then return result
    if type(row.items) <> "roArray" then return result
    if not HomeCacheId(HomeCacheText(row,"rowId")) then return result
    projected = {rowId:row.rowId,title:Left(HomeCacheText(row,"title"),128),sectionType:kind,items:[]}
    for each item in row.items
        if projected.items.Count() >= 6 then exit for
        itemId = HomeCacheText(item,"itemId")
        itemKind = HomeCacheText(item,"type")
        if not HomeCacheId(itemId) then exit for
        if itemKind <> "movie" and itemKind <> "series" and itemKind <> "episode" then exit for
        title = Left(HomeCacheText(item,"title"),256)
        if title = "" then exit for
        card = {itemId:itemId,title:title,type:itemKind,summary:Left(HomeCacheText(item,"summary"),1024),art:{},homeCached:true}
        projected.items.Push(card)
        url = HomeCacheText(item.art,"poster")
        if Len(url) > 4096 then url = ""
        result.downloads.Push({index:projected.items.Count()-1,role:"poster",url:url})
    end for
    if projected.items.Count() > 0 then result.row = projected
    return result
end function

function HomeCacheCanPublish(job as Object, current as Object, token as Integer, fresh as Boolean) as Boolean
    if fresh then return false
    for each key in ["provider","sourceId","profileId","generation"]
        if job[key] <> current[key] then return false
    end for
    return job.token = token
end function

function HomeCachePath(owner as String, index as Integer) as String
    if not CreateObject("roRegex","^[a-f0-9]{64}$","").IsMatch(owner) then return ""
    if index < 0 or index > 6 then return ""
    return "cachefs:/silo-home-v1-" + owner + "-" + index.ToStr() + ".img"
end function

' Check dimensions before the native Poster sees an encoded file.
function HomeCacheImageValid(bytes as Object) as Boolean
    count = bytes.Count()
    if count < 24 or count > 262144 then return false
    width = 0:height = 0
    if bytes[0] = 137 and bytes[1] = 80 and bytes[2] = 78 and bytes[3] = 71
        if bytes[4] <> 13 or bytes[5] <> 10 or bytes[6] <> 26 or bytes[7] <> 10 then return false
        if bytes[12] <> 73 or bytes[13] <> 72 or bytes[14] <> 68 or bytes[15] <> 82 then return false
        if bytes[16] <> 0 or bytes[17] <> 0 or bytes[20] <> 0 or bytes[21] <> 0 then return false
        width = bytes[18]*256+bytes[19]:height = bytes[22]*256+bytes[23]
    else if bytes[0] = 255 and bytes[1] = 216
        offset = 2
        while offset+8 < count
            if bytes[offset] <> 255 then return false
            marker = bytes[offset+1]:offset += 2
            if marker = 255 then offset-- : continue while
            if marker = 0 or marker = 217 or marker = 218 then return false
            length = bytes[offset]*256+bytes[offset+1]
            if length < 2 or offset+length > count then return false
            if marker = 192 or marker = 193 or marker = 194
                if length < 8 then return false
                height = bytes[offset+3]*256+bytes[offset+4]
                width = bytes[offset+5]*256+bytes[offset+6]
                exit while
            end if
            offset += length
        end while
    end if
    fitsBounds = (width <= 1920 and height <= 1080) or (width <= 1080 and height <= 1920)
    return width > 0 and height > 0 and fitsBounds and width*height <= 2073600
end function
