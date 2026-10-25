' Allowlisted presentation boundary: never stringify native or server dictionaries.
function SiloUIDiagnosticsEnum(value as Dynamic, allowed as Object) as String
    if type(value) <> "roString" and type(value) <> "String" then return "Unavailable"
    for each candidate in allowed
        if value = candidate then return candidate
    end for
    return "Unavailable"
end function

function SiloUIDiagnosticsNumber(value as Dynamic, maximum as Double, suffix as String) as String
    kind = type(value)
    if kind <> "Integer" and kind <> "roInt" and kind <> "roInteger" and kind <> "roLongInteger" and kind <> "Float" and kind <> "roFloat" and kind <> "Double" and kind <> "roDouble" and kind <> "LongInteger" then return "Unavailable"
    if value < 0 or value > maximum then return "Unavailable"
    return Int(value).ToStr() + suffix
end function

function SiloUIDiagnosticsText(stats as Object, source as Object) as String
    nl = Chr(10)
    text = "Playback diagnostics · Up / Back to close" + nl + "Engine: Native Video"
    text += " / State: " + SiloUIDiagnosticsEnum(stats.state, ["playing", "paused", "buffering", "stopped", "finished", "error"])
    text += nl + "Native video: " + SiloUIDiagnosticsEnum(stats.videoFormat, ["none", "unknown", "hevc", "hevc_b", "mpeg1", "mpeg2", "mpeg4_2", "mpeg4_10b", "mpeg4_15", "AVC vc1", "wmv"])
    text += " " + SiloUIDiagnosticsSize(stats.videoSize)
    text += " / Native audio: " + SiloUIDiagnosticsEnum(stats.audioFormat, ["none", "unknown", "aac", "aac_adif", "aac_adts", "aac_latm", "ac3", "ac4", "alac", "eac3", "flac", "mp3", "opus", "vorbis", "pcm", "dts", "mat", "wma", "wmapro"])
    text += nl + "Stream bitrate: " + SiloUIDiagnosticsNumber(stats.bitrate, 1000000000, " bps")
    text += " / Buffering: " + SiloUIDiagnosticsNumber(stats.buffering, 100, "%")
    text += nl + "Native position: " + SiloUIDiagnosticsNumber(stats.position, 31536000, " s") + " / " + SiloUIDiagnosticsNumber(stats.duration, 31536000, " s")
    text += nl + "Declared stream format: " + SiloUIDiagnosticsEnum(source.streamFormat, ["mkv", "mp4", "hls", "dash", "ism", "mov", "mp3", "wma"])
    ' GetVideoMode values: https://developer.roku.com/dev/docs/ifdeviceinfo
    text += nl + "Display mode: " + SiloUIDiagnosticsEnum(stats.outputMode, ["480i", "480p", "576i", "576p", "720p", "720p50", "1080i", "1080p", "1080p24", "1080p25", "1080p30", "1080p50", "1080p60", "2160p24", "2160p25", "2160p30", "2160p50", "2160p60", "2160p24b10", "2160p25b10", "2160p30b10", "2160p50b10", "2160p60b10", "2160p24Hdr", "2160p30Hdr", "2160p60Hdr", "2160p24Dv", "2160p30Dv", "2160p60Dv"])
    ' streamingSegment.hdrModeStr describes content, not physical display output.
    ' https://developer.roku.com/dev/docs/video
    text += nl + "Native stream HDR: " + SiloUIDiagnosticsRange(stats.hdrMode)
    text += nl + "Display HDR: Unknown"
    if source.recipeRange <> invalid then text += nl + "Recipe range: " + SiloUIDiagnosticsEnum(source.recipeRange,["sdr","hdr10","hdr10_plus","hlg","dolby_vision"])

    original = source.originalPlayback
    if type(original) = "roAssociativeArray" and source.streamFormat = "mkv"
        video = SiloUIDiagnosticsSourceVideo(source)
        text += nl + "Source: " + SiloUIDiagnosticsEnum(video.codec,["hevc","h264","av1"])
        if video.dv_profile = 7 then text += " P7"
        if video.dv_profile = 8 then text += " P8"
        if video.dv_profile = 5 then text += " P5"
        text += " " + SiloUIDiagnosticsNumber(video.width,16384,"") + " x " + SiloUIDiagnosticsNumber(video.height,16384,"")
        text += nl + "Source range: " + SiloUIDiagnosticsSourceRange(video)
        text += nl + "Delivery: Original / MKV / unchanged bytes"
        audio = original.audioIdentity
        if type(audio) <> "roAssociativeArray" then audio = {}
        text += nl + "Selected source audio: " + SiloUIDiagnosticsEnum(audio.codec,["ac3","eac3","aac","truehd"])
        text += " " + SiloUIDiagnosticsEnum(audio.language,["en","eng","es","spa","fr","fra","de","deu","it","ita","pt","por","ja","jpn","ko","kor","zh","zho"])
        text += " " + SiloUIDiagnosticsNumber(audio.channels,32," ch")
        status = "audio unverified"
        if source.mappingPhase = "await_inventory" then status = "audio pending"
        if source.mappingPhase = "selected" then status = "audio matched"
        if source.mappingPhase = "verified_playing" then status = "playing verified"
        if source.mappingPhase = "recovering" then status = "original startup failed"
        text += nl + "Audio mapping: " + status
    else
        video = SiloUIDiagnosticsSourceVideo(source)
        if video.Count() > 0
            text += nl + "Source: " + SiloUIDiagnosticsEnum(video.codec,["hevc","h264","av1"])
            if video.dv_profile = 7 then text += " P7"
            if video.dv_profile = 8 then text += " P8"
            if video.dv_profile = 5 then text += " P5"
            text += " " + SiloUIDiagnosticsNumber(video.width,16384,"") + " x " + SiloUIDiagnosticsNumber(video.height,16384,"")
            text += nl + "Source range: " + SiloUIDiagnosticsSourceRange(video)
            text += nl + "Source color: " + SiloUIDiagnosticsEnum(video.color_primaries,["bt709","bt2020","smpte170m"])
            text += " / " + SiloUIDiagnosticsEnum(video.color_transfer,["bt709","smpte2084","arib-std-b67"])
            text += " / " + SiloUIDiagnosticsEnum(video.color_space,["bt709","bt2020nc","smpte170m"])
        end if
        text += nl + "Delivery: " + SiloUIDiagnosticsEnum(source.delivery,["original","original_http","server_remux_progressive","server_remux_hls","server_transcode_hls","http_progressive"])
    end if
    return text
end function

function SiloUIDiagnosticsDimension(value as Dynamic) as String
    number = SiloUIDiagnosticsNumber(value,16384,"")
    if number = "Unavailable" then return number
    if value <= 0 or value <> Int(value) then return "Unavailable"
    return number
end function

function SiloUIDiagnosticsSize(value as Dynamic) as String
    if type(value) <> "roAssociativeArray" then return "Unavailable"
    width = SiloUIDiagnosticsDimension(value.width)
    height = SiloUIDiagnosticsDimension(value.height)
    if width = "Unavailable" or height = "Unavailable" then return "Unavailable"
    return width + " x " + height
end function

function SiloUIDiagnosticsSegmentSize(previous as Dynamic, segment as Dynamic) as Object
    if type(segment) = "roAssociativeArray"
        if segment.segTypeStr = "video" or segment.segTypeStr = "mux"
            if SiloUIDiagnosticsSize(segment) <> "Unavailable" then return {width:segment.width,height:segment.height}
        end if
    end if
    if SiloUIDiagnosticsSize(previous) <> "Unavailable" then return {width:previous.width,height:previous.height}
    return {}
end function

' Audio renditions may be the most recent event; retain the video range only.
function SiloUIDiagnosticsSegmentHDR(previous as Dynamic, segment as Dynamic) as String
    allowed = ["none","hdr10","dolby_vision","hlg10","hdr10+","sl-hdr2"]
    if type(segment) = "roAssociativeArray"
        if segment.segTypeStr = "video" or segment.segTypeStr = "mux"
            value = SiloUIDiagnosticsEnum(segment.hdrModeStr,allowed)
            if value <> "Unavailable" then return value
        end if
    end if
    return SiloUIDiagnosticsEnum(previous,allowed)
end function

function SiloUIDiagnosticsSourceVideo(source as Object) as Object
    original = source.originalPlayback
    if type(original) = "roAssociativeArray"
        if type(original.videoFacts) = "roAssociativeArray" then return original.videoFacts
    end if
    if type(source.sourceVideo) = "roAssociativeArray" then return source.sourceVideo
    return {}
end function

function SiloUIDiagnosticsRange(value as Dynamic) as String
    known = SiloUIDiagnosticsEnum(value,["none","hdr10","dolby_vision","hlg10","hdr10+","sl-hdr2"])
    if known = "none" then return "SDR"
    if known = "hdr10" then return "HDR10"
    if known = "dolby_vision" then return "Dolby Vision"
    if known = "hlg10" then return "HLG"
    if known = "hdr10+" then return "HDR10+"
    if known = "sl-hdr2" then return "SL-HDR2"
    return "Unknown"
end function

function SiloUIDiagnosticsSourceRange(video as Object) as String
    hdr10 = video.bit_depth = 10 and video.color_transfer = "smpte2084" and video.color_primaries = "bt2020" and video.color_space = "bt2020nc"
    if video.dv_profile = 5 then return "Dolby Vision P5"
    if video.dv_profile = 7 or video.dv_profile = 8
        value = "Dolby Vision P" + Int(video.dv_profile).ToStr()
        base = video.dv_config_present = true and video.dv_bl_compat_id_present = true and video.dv_bl_present = true and hdr10
        if video.dv_profile = 7 then base = base and video.dv_bl_compat_id = 6
        if video.dv_profile = 8 then base = base and video.dv_bl_compat_id = 1
        if base then return value + " / HDR10 base proven"
        return value + " / HDR10 base unknown"
    end if
    if hdr10 then return "HDR10"
    if video.color_transfer = "bt709" then return "SDR"
    return "Unknown"
end function
