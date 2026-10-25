' Pure display formatting and content field mapping. No SceneGraph or environment state.

function SiloUISeriesPosters(rows as Object) as Object
    posters = {}
    for each row in rows
        if type(row.items) = "roArray"
            for each item in row.items
                if item.type = "series" or item.type = "show"
                    source = TextOr(item.sourceId):id = TextOr(item.itemId)
                    if source <> "" and id <> "" and type(item.art) = "roAssociativeArray"
                        poster = TextOr(item.art.poster)
                        if poster <> ""
                            if not posters.DoesExist(source) then posters[source] = {}
                            posters[source][id] = poster
                        end if
                    end if
                end if
            end for
        end if
    end for
    return posters
end function

function SiloUIEpisodePortraitArt(item as Object, art as Object, posters as Object) as Object
    if item.type <> "episode" then return art
    source = TextOr(item.sourceId):id = TextOr(item.seriesId)
    if source <> "" and id <> "" and posters.DoesExist(source)
        poster = TextOr(posters[source][id])
        if poster <> ""
            portrait = {poster:poster}
            childPoster = TextOr(art.poster)
            if art.posterIsEpisodeStill = false and childPoster <> "" and childPoster <> poster then portrait["posterFallback"] = childPoster
            return portrait
        end if
    end if
    if art.posterIsEpisodeStill = false and TextOr(art.poster) <> "" then return {poster:art.poster}
    return {}
end function

function SiloUIItemFields(item as Object, art as Dynamic, landscape = false as Boolean, baseUrl = "" as String) as Object
    if type(art) <> "roAssociativeArray" then art = {}
    poster = SiloUIArtField(art, "poster", baseUrl)
    if landscape
        poster = SiloUIArtField(art, "still", baseUrl)
        if poster = "" then poster = SiloUIArtField(art, "backdrop", baseUrl)
        if poster = "" then poster = SiloUIArtField(art, "poster", baseUrl)
    else if poster = "" and item.type = "episode"
        poster = SiloUIArtField(art, "still", baseUrl)
    end if
    title = TextOr(item.title)
    if not landscape and item.type = "episode" and TextOr(item.seriesTitle) <> "" then title = item.seriesTitle
    if landscape and NumberOr(item.episodeNumber, 0) > 0 then title = item.episodeNumber.ToStr() + ". " + title
    badges = item.badges
    if type(badges) <> "roAssociativeArray" then badges = {}
    candidates = SiloUIArtworkCandidates(art, landscape, baseUrl)
    if poster = "" and candidates.Count() > 0 then poster = candidates[0]
    return {title: title, HDPosterUrl: poster, artCandidates:candidates, item: item, landscape: landscape, badges: badges, durationMs: NumberOr(item.durationMs, 0), resumeMs: NumberOr(item.resumeMs, 0), watched: item.watched = true}
end function

function SiloUIArtworkCandidates(art as Object, landscape as Boolean, baseUrl as String) as Object
    kinds = ["poster", "still", "backdrop"]
    if landscape then kinds = ["still", "backdrop", "poster"]
    if not landscape and art.DoesExist("posterFallback") then kinds = ["poster", "posterFallback", "still", "backdrop"]
    candidates = []
    for each kind in kinds
        uri = SiloUIArtField(art, kind, baseUrl)
        duplicate = false
        for each existing in candidates
            if existing = uri then duplicate = true
        end for
        if uri <> "" and not duplicate then candidates.Push(uri)
    end for
    return candidates
end function

function SiloUIArtField(art as Object, name as String, baseUrl as String) as String
    value = TextOr(art[name])
    if Left(value, 1) = "/" then return baseUrl + value
    return value
end function

function NumberOr(value as Dynamic, fallback as Dynamic) as Dynamic
    t = type(value)
    if t = "Integer" or t = "roInt" or t = "roInteger" or t = "LongInteger" or t = "roLongInteger" or t = "Float" or t = "roFloat" or t = "Double" or t = "roDouble" then return value
    return fallback
end function

function TextOr(value as Dynamic) as String
    if type(value) = "String" or type(value) = "roString" then return value
    return ""
end function

function FormatDuration(ms as Dynamic) as String
    minutes = Int(NumberOr(ms, 0) / 60000)
    if minutes <= 0 then return ""
    if minutes < 60 then return minutes.ToStr() + "m"
    rest = minutes mod 60
    if rest = 0 then return Int(minutes / 60).ToStr() + "h"
    return Int(minutes / 60).ToStr() + "h " + rest.ToStr() + "m"
end function

function JoinDots(parts as Object) as String
    out = ""
    for each part in parts
        if part <> invalid and part <> ""
            if out <> "" then out = out + "  ·  "
            out = out + part
        end if
    end for
    return out
end function

function MetaLine(item as Object) as String
    year = ""
    if NumberOr(item.year, 0) > 0 then year = item.year.ToStr()
    kind = ""
    if item.type = "movie" then kind = "Movie"
    if item.type = "series" or item.type = "show" then kind = "Series"
    if item.type = "episode" and NumberOr(item.seasonNumber, -1) > 0 then kind = "S" + item.seasonNumber.ToStr() + " E" + NumberOr(item.episodeNumber, 0).ToStr()
    return JoinDots([year, FormatDuration(item.durationMs), TextOr(item.contentRating), kind])
end function

function QualityLine(item as Object) as String
    b = item.badges
    if type(b) <> "roAssociativeArray" then return ""
    res = UCase(TextOr(b.resolution))
    if res = "2160P" then res = "4K"
    return JoinDots([res, SourceVideoCodecs(b), TextOr(b.hdr), TextOr(b.audio), TextOr(b.audio_channels)])
end function

function RatingsLine(item as Object) as String
    b = item.badges
    if type(b) <> "roAssociativeArray" then return ""
    parts = []
    if NumberOr(b.imdb, invalid) <> invalid then parts.Push("IMDb " + Str(Int(b.imdb * 10) / 10.0).Trim())
    if NumberOr(b.rtCritic, invalid) <> invalid then parts.Push("Rotten Tomatoes " + b.rtCritic.ToStr() + "%")
    if NumberOr(b.rtAudience, invalid) <> invalid then parts.Push("Audience " + b.rtAudience.ToStr() + "%")
    return JoinDots(parts)
end function

function ResolutionLabel(value as Dynamic) as String
    value = TextOr(value)
    v = LCase(value)
    if v = "2160p" or v = "4k" or v = "uhd" then return "4K"
    return UCase(value)
end function

' Source metadata only: these labels do not establish decoder or output support.
function VideoCodecLabel(value as Dynamic) as String
    codec = LCase(TextOr(value).Trim())
    if codec = "h264" or codec = "h.264" or codec = "avc" or codec = "mpeg4 avc" then return "H.264"
    if codec = "h265" or codec = "h.265" or codec = "hevc" then return "HEVC"
    if codec = "av1" then return "AV1"
    if codec = "vp9" then return "VP9"
    if codec = "mpeg2" or codec = "mpeg2video" then return "MPEG-2"
    if codec = "vc1" or codec = "vc-1" then return "VC-1"
    if codec = "mpeg4" then return "MPEG-4"
    return ""
end function

function SourceVideoCodecs(badges as Dynamic) as String
    if type(badges) <> "roAssociativeArray" then return ""
    raw = [badges.videoCodec]
    if type(badges.videoCodecs) = "roArray"
        for each value in badges.videoCodecs
            if raw.Count() < 17 then raw.Push(value)
        end for
    end if
    labels = []
    for each value in raw
        label = VideoCodecLabel(value)
        duplicate = false
        for each existing in labels
            if existing = label then duplicate = true
        end for
        if label <> "" and not duplicate then labels.Push(label)
    end for
    if labels.Count() > 2 then return "Mixed codecs"
    if labels.Count() = 2 then return labels[0] + " / " + labels[1]
    if labels.Count() = 1 then return labels[0]
    return ""
end function

function SourceVersionQuality(version as Object, audioChoice = invalid as Dynamic) as String
    container = LCase(TextOr(version.container))
    known = false
    for each value in ["mp4","m4v","mov","mkv","webm","avi","ts","mpegts"]
        if container = value then known = true
    end for
    if not known then container = ""
    codec = VideoCodecLabel(version.videoCodec)
    if codec = "" then codec = "Codec unknown"
    return JoinDots([ResolutionLabel(version.resolution),codec,UCase(container),SourceRangeLabel(version),SourceAudioLabel(version,audioChoice)])
end function

function DetailSourceQuality(item as Object, versions as Dynamic, selected as String, audioChoice = invalid as Dynamic) as String
    if item.type = "series" or item.type = "show" then return QualityLine(item)
    if type(versions) <> "roArray" then return QualityLine(item)
    if selected <> ""
        for each version in versions
            if TextOr(version.versionId) = selected then return JoinDots(["Selected source",SourceVersionQuality(version,audioChoice)])
        end for
        return "Source unavailable"
    end if
    if versions.Count() = 1 then return JoinDots(["Source",SourceVersionQuality(versions[0],audioChoice)])
    if versions.Count() > 1
        summary = QualityLine(item)
        if summary <> "" then return JoinDots(["Library includes",summary])
        return ""
    end if
    return QualityLine(item)
end function

function DetailSourceHeading(item as Object, versions as Dynamic, selected as String) as String
    if item.type = "series" or item.type = "show" then return ""
    if type(versions) <> "roArray" or selected <> "" or versions.Count() < 2 then return ""
    codecs = []
    for each version in versions
        codecs.Push(version.videoCodec)
    end for
    return JoinDots(["Auto",versions.Count().ToStr()+" versions",SourceVideoCodecs({videoCodecs:codecs})])
end function

function SourceRangeLabel(version as Object) as String
    if type(version.videoTracks) = "roArray" and version.videoTracks.Count() = 1
        track = version.videoTracks[0]
        profile = NumberOr(track.dv_profile,0)
        if profile > 0 and profile <= 9 and profile = Int(profile) then return "DV P"+profile.ToStr()
        range = LCase(TextOr(track.video_range))
        if range = "" then range = LCase(TextOr(track.video_range_type))
        if range = "dolbyvision" or range = "dolby_vision" then return "DV"
        if track.hdr10_plus = true or range = "hdr10+" or range = "hdr10plus" then return "HDR10+"
        if range = "hdr10" then return "HDR10"
        if range = "hlg" then return "HLG"
    end if
    if version.hdr = true then return "HDR"
    return ""
end function

function SourceAudioLabel(version as Object, choice as Dynamic) as String
    codec = TextOr(version.audioCodec):channels = 0
    if type(version.audioTracks) = "roArray"
        for each track in version.audioTracks
            if track.isDefault = true or track.default = true or track.selected = true
                codec = TextOr(track.codec):channels = NumberOr(track.channels,0)
                exit for
            end if
        end for
    end if
    if type(choice) = "roAssociativeArray"
        if TextOr(choice.fileId) <> "" and choice.fileId = version.versionId then codec = TextOr(choice.codec):channels = NumberOr(choice.channels,0)
    end if
    codec = LCase(codec)
    names = {aac:"AAC",ac3:"AC3","ac-3":"AC3",eac3:"EAC3","e-ac-3":"EAC3",truehd:"TrueHD",dts:"DTS",dca:"DTS","dts-hd ma":"DTS-HD MA",dts_hd_ma:"DTS-HD MA",flac:"FLAC",opus:"Opus",mp3:"MP3",alac:"ALAC",pcm:"PCM"}
    label = names[codec]
    if label = invalid then return ""
    layout = ""
    if channels = 1 then layout = "Mono"
    if channels = 2 then layout = "Stereo"
    if channels = 6 then layout = "5.1"
    if channels = 8 then layout = "7.1"
    return JoinDots([label,layout])
end function
