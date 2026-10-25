' External launch parameters never select a server, profile or playback URL.
function SiloUILaunchInput(args as Dynamic) as Dynamic
    if type(args) <> "roAssociativeArray" then return invalid
    id = invalid : media = invalid
    for each key in args
        if LCase(key) = "contentid" then id = args[key]
        if LCase(key) = "mediatype" then media = args[key]
    end for
    if type(id) <> "String" and type(id) <> "roString" then return invalid
    if type(media) <> "String" and type(media) <> "roString" then return invalid
    if Len(id) = 0 or Len(id) > 255 then return invalid
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-"
    for i = 1 to Len(id)
        if Instr(1, allowed, Mid(id, i, 1)) = 0 then return invalid
    end for
    media = LCase(media)
    if media <> "movie" and media <> "episode" and media <> "series" then return invalid
    return {contentId:id,mediaType:media}
end function
