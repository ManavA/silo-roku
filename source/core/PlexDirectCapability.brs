' Capability facts/queries alone do not approve a provider route.
' Profile, level, bit depth, network delivery, file indexing and seekability
' remain separate facts. Production MKV selection is deliberately unchanged.
function PlexDirectCapabilityQueries(plan as Dynamic) as Object
    failure = {ok:false,errorCode:"invalid_capability_facts"}
    if type(plan) <> "roAssociativeArray" then return failure
    if not PdcTrue(PdcField(plan,"ok",invalid)) then return failure
    container = PdcText(plan,"container")
    if container <> "mp4" and container <> "mkv" then return failure
    if PdcText(plan,"streamFormat") <> container then return failure
    codec = PdcText(plan,"videoCodec")
    if codec = "h264"
        codec = "mpeg4 avc"
    else if codec <> "hevc"
        return failure
    end if
    audioCodec = PdcText(plan,"audioCodec")
    if audioCodec <> "aac" and audioCodec <> "ac3" and audioCodec <> "eac3" then return failure
    width = PdcField(plan,"width",invalid)
    height = PdcField(plan,"height",invalid)
    channels = PdcField(plan,"audioChannels",invalid)
    if not PdcPositiveInteger(width,2147483647) then return failure
    if not PdcPositiveInteger(height,2147483647) then return failure
    if not PdcPositiveInteger(channels,8) then return failure
    ' Native C208X rejects width/height properties. Keep these as independent
    ' validated metadata rather than submitting unsupported query properties.
    return {ok:true,video:{codec:codec,container:container},dimensions:{width:width,height:height},
        audio:{codec:audioCodec,container:container,chcnt:channels}}
end function


' Initial conservative MP4 eligibility ceiling, independent of decoder query
' properties. GetVideoMode describes output; this does not infer decoder maxima.
' Until exact stream facts/device proof widen eligibility, even 2160p output is
' capped at 1920x1080. A 720p output uses 1280x720. Unknown modes fail closed.
function PlexDirectMp4DimensionsAllowed(queries as Dynamic, videoMode as Dynamic) as Boolean
    if not PdcQueriesValid(queries) then return false
    if PdcText(PdcField(queries,"video",invalid),"container") <> "mp4" then return false
    if type(videoMode) <> "String" and type(videoMode) <> "roString" then return false
    mode = LCase(videoMode)
    maximumWidth = 0
    maximumHeight = 0
    if mode = "720p" or mode = "720p50"
        maximumWidth = 1280
        maximumHeight = 720
    else
        for each known in ["1080i","1080i50","1080p","1080p24","1080p25","1080p30","1080p50","1080p60b10","1080p60dv","2160p24","2160p25","2160p30","2160p30dv","2160p50","2160p60","2160p60dv"]
            if mode = known
                maximumWidth = 1920
                maximumHeight = 1080
                exit for
            end if
        end for
    end if
    if maximumWidth = 0 then return false
    dimensions = queries.dimensions
    return dimensions.width <= maximumWidth and dimensions.height <= maximumHeight
end function

function PlexDirectCapabilityAccepted(queries as Dynamic, videoResult as Dynamic, audioResult as Dynamic) as Boolean
    if not PdcQueriesValid(queries) then return false
    return PdcResultTrue(videoResult) and PdcResultTrue(audioResult)
end function

' This opt-in probe calls decoder APIs only. It never assigns Video.content,
' sends an HTTP request, starts a server lease, or changes a saved bookmark.
function PlexDirectCapabilityProbe(plan as Dynamic, device as Object) as Object
    queries = PlexDirectCapabilityQueries(plan)
    if not queries.ok then return queries
    videoResult = device.CanDecodeVideo(queries.video)
    audioResult = device.CanDecodeAudio(queries.audio)
    if not PlexDirectCapabilityAccepted(queries,videoResult,audioResult)
        return {ok:false,errorCode:"capability_rejected"}
    end if
    return {ok:true,videoSupported:true,audioSupported:true}
end function

function PdcQueriesValid(queries as Dynamic) as Boolean
    if type(queries) <> "roAssociativeArray" then return false
    if not PdcTrue(PdcField(queries,"ok",invalid)) then return false
    video = PdcField(queries,"video",invalid)
    audio = PdcField(queries,"audio",invalid)
    dimensions = PdcField(queries,"dimensions",invalid)
    if type(video) <> "roAssociativeArray" or type(audio) <> "roAssociativeArray" then return false
    if type(dimensions) <> "roAssociativeArray" then return false
    container = PdcText(video,"container")
    if container <> "mp4" and container <> "mkv" then return false
    if PdcText(audio,"container") <> container then return false
    codec = PdcText(video,"codec")
    if codec <> "mpeg4 avc" and codec <> "hevc" then return false
    codec = PdcText(audio,"codec")
    if codec <> "aac" and codec <> "ac3" and codec <> "eac3" then return false
    if not PdcPositiveInteger(PdcField(dimensions,"width",invalid),2147483647) then return false
    if not PdcPositiveInteger(PdcField(dimensions,"height",invalid),2147483647) then return false
    return PdcPositiveInteger(PdcField(audio,"chcnt",invalid),8)
end function

function PdcResultTrue(result as Dynamic) as Boolean
    if type(result) <> "roAssociativeArray" then return false
    return PdcTrue(PdcField(result,"result",invalid))
end function

function PdcTrue(value as Dynamic) as Boolean
    kind = type(value)
    if kind <> "Boolean" and kind <> "roBoolean" then return false
    return value = true
end function

function PdcPositiveInteger(value as Dynamic, maximum as Double) as Boolean
    kind = type(value)
    if kind <> "Integer" and kind <> "roInt" and kind <> "roInteger" and kind <> "LongInteger" and kind <> "roLongInteger" and kind <> "Float" and kind <> "roFloat" and kind <> "Double" and kind <> "roDouble" then return false
    if value <> value then return false
    if value < 1 or value > maximum then return false
    return value = Int(value)
end function

function PdcField(value as Dynamic, key as String, fallback as Dynamic) as Dynamic
    if type(value) <> "roAssociativeArray" then return fallback
    if not value.DoesExist(key) then return fallback
    return value[key]
end function

function PdcText(value as Dynamic, key as String) as String
    text = PdcField(value,key,invalid)
    kind = type(text)
    if kind <> "String" and kind <> "roString" then return ""
    return LCase(text)
end function
