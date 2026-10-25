' Manifest URLs remain worker-private. Scene receives only local sheets and geometry.
function SiloUITrickplayManifest(raw as Dynamic, fileId as String, base as String, nowSeconds as Double) as Object
    failed = {ok:false}
    if type(raw) <> "roAssociativeArray" or fileId = "" then return failed
    if ArtworkText(raw,"file_id") <> fileId then return failed
    for each key in ["interval_ms","thumbnail_width","thumbnail_height","tile_columns","tile_rows","thumbnail_count"]
        number = ArtworkField(raw,key,invalid)
        if not ArtworkInteger(number) then return failed
        if number < 1 then return failed
    end for
    if raw.interval_ms < 1000 or raw.interval_ms > 60000 or raw.thumbnail_count > 100000 then return failed
    if raw.thumbnail_width > 640 or raw.thumbnail_height > 360 or raw.tile_columns > 16 or raw.tile_rows > 16 then return failed
    width = raw.thumbnail_width * raw.tile_columns
    height = raw.thumbnail_height * raw.tile_rows
    if width > 4096 or height > 4096 or width * height > 4194304 then return failed
    sheets = ArtworkField(raw,"sheets",invalid)
    count = Int((raw.thumbnail_count - 1) / (raw.tile_columns * raw.tile_rows)) + 1
    if type(sheets) <> "roArray" then return failed
    if sheets.Count() <> count or count > 128 then return failed
    expires = ArtworkText(raw,"expires_at")
    if not CreateObject("roRegex","^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}([.][0-9]{1,3})?Z$","").IsMatch(expires) then return failed
    date = CreateObject("roDateTime")
    date.FromISO8601String(expires)
    expiry = date.AsSeconds()
    if expiry <= nowSeconds + 5 or expiry > nowSeconds + 86400 then return failed
    configured = SiloUrlParts(base)
    if not configured.ok then return failed
    urls = []
    for index = 0 to sheets.Count() - 1
        entry = sheets[index]
        if ArtworkField(entry,"index",invalid) <> index then return failed
        url = SiloResolveUrl(ArtworkText(entry,"url"),base)
        if Len(url) > 4096 then return failed
        resolved = SiloUrlParts(url)
        if not resolved.ok then return failed
        if resolved.origin <> configured.origin then return failed
        prefix = "/api/v2/artwork/trickplay/" + fileId + "/"
        if Left(resolved.path,Len(prefix)) <> prefix then return failed
        suffix = Mid(resolved.path,Len(prefix)+1)
        if not CreateObject("roRegex","^[0-9]+/[0-9]+[.][0-9]+[.]jpg[?][A-Za-z0-9_=&%-]{1,2048}$","").IsMatch(suffix) then return failed
        urls.Push(url)
    end for
    return {ok:true,fileId:fileId,intervalMs:raw.interval_ms,width:raw.thumbnail_width,height:raw.thumbnail_height,columns:raw.tile_columns,rows:raw.tile_rows,count:raw.thumbnail_count,sheetWidth:width,sheetHeight:height,expires:expiry,urls:urls}
end function

function SiloUITrickplayTile(manifest as Object, positionMs as Double) as Object
    if manifest.ok <> true or positionMs < 0 then return {ok:false}
    index = Int(positionMs / manifest.intervalMs)
    if index >= manifest.count then index = manifest.count - 1
    perSheet = manifest.columns * manifest.rows
    tile = index mod perSheet
    return {ok:true,sheet:Int(index / perSheet),x:(tile mod manifest.columns)*manifest.width,y:Int(tile / manifest.columns)*manifest.height}
end function

' Read only bounded marker headers; never ask the bitmap decoder to inspect a URL.
function SiloUITrickplayJpeg(bytes as Object, width as Integer, height as Integer) as Boolean
    size = bytes.Count()
    if size < 12 or size > 65536 then return false
    if width < 1 or height < 1 or width > 4096 or height > 4096 then return false
    if width * height > 4194304 then return false
    if bytes[0] <> 255 or bytes[1] <> 216 then return false
    cursor = 2
    while cursor + 4 < size
        if bytes[cursor] <> 255 then return false
        marker = bytes[cursor+1]
        if marker = 255
            cursor = cursor + 1
        else
            length = bytes[cursor+2]*256 + bytes[cursor+3]
            if length < 2 or cursor + 2 + length > size then return false
            if marker = 192 or marker = 194
                if length < 11 then return false
                if bytes[cursor+4] <> 8 then return false
                return bytes[cursor+5]*256 + bytes[cursor+6] = height and bytes[cursor+7]*256 + bytes[cursor+8] = width and (bytes[cursor+9] = 1 or bytes[cursor+9] = 3)
            end if
            if marker = 218 or marker = 217 or marker = 0 then return false
            cursor = cursor + 2 + length
        end if
    end while
    return false
end function
