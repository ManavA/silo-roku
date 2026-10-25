function SiloUIDetailVersion(versions as Dynamic, selected as String) as String
    if type(versions) <> "roArray" or versions.Count() = 0 then return ""
    if selected = "" then selected = versions[0].versionId
    matches = 0
    for each version in versions
        if version.versionId = selected then matches = matches + 1
    end for
    if matches <> 1 then return ""
    return selected
end function

function SiloUIDetailCurrent(view as String, visit as Dynamic, responseVisit as Dynamic, season as Dynamic, responseSeason as Dynamic) as Boolean
    return view = "detail" and visit = responseVisit and season = responseSeason
end function

function SiloUIDetailEpisodeHeading(ep as Object) as String
    line = "Selected: "
    if ep.seasonNumber <> invalid then line = line + "S" + ep.seasonNumber.ToStr() + " · "
    if ep.episodeNumber <> invalid then line = line + "E" + ep.episodeNumber.ToStr() + " · "
    if type(ep.title) = "roString" or type(ep.title) = "String" then line = line + ep.title
    return line
end function

function SiloUIDetailSeasonOffset(offset as Integer, leftEdge as Integer, rightEdge as Integer, rowWidth as Integer, viewportWidth as Integer) as Integer
    if leftEdge < offset then offset = leftEdge
    if rightEdge > offset + viewportWidth then offset = rightEdge - viewportWidth
    maximum = rowWidth - viewportWidth
    if maximum < 0 then maximum = 0
    if offset > maximum then offset = maximum
    if offset < 0 then offset = 0
    return offset
end function

' Public cast presentation contains identities and bounded captions only.
function SiloUICastPeople(people as Dynamic) as Object
    result = []
    if type(people) <> "roArray" then return result
    for each person in people
        if type(person) = "roAssociativeArray"
            name = "":role = "":personId = ""
            if type(person.name) = "String" or type(person.name) = "roString" then name = Left(person.name, 80)
            if type(person.role) = "String" or type(person.role) = "roString" then role = Left(person.role.Replace("|", ","), 160)
            if type(person.personId) = "String" or type(person.personId) = "roString" then personId = person.personId
            result.Push({name:name,role:role,personId:personId})
            if result.Count() = 8 then exit for
        end if
    end for
    return result
end function

' Explicit audio choices refer to normalized source identities, never Video handles.
function SiloUIDetailAudioText(value as Dynamic) as String
    if type(value) = "String" or type(value) = "roString" then return value
    return ""
end function

function SiloUIDetailAudioOrdinal(value as Dynamic) as Boolean
    kind = type(value)
    if kind <> "Integer" and kind <> "roInt" and kind <> "roInteger" and kind <> "LongInteger" and kind <> "roLongInteger" and kind <> "Float" and kind <> "roFloat" and kind <> "Double" and kind <> "roDouble" then return false
    return value >= 0 and value <= 4095 and Int(value) = value
end function

function SiloUIDetailAudioChoices(provider as String, item as Dynamic, versions as Dynamic, selected as String) as Object
    choices = []
    if provider <> "silo" or type(item) <> "roAssociativeArray" or type(versions) <> "roArray" then return choices
    if item.type = "series" or item.type = "show" or SiloUIDetailAudioText(item.itemId) = "" then return choices
    if versions.Count() = 0 or versions.Count() > 16 then return choices
    if selected = "" and versions.Count() <> 1 then return choices
    fileId = SiloUIDetailVersion(versions,selected)
    if fileId = "" then return choices
    tracks = invalid
    for each version in versions
        if version.versionId = fileId then tracks = version.audioTracks
    end for
    if type(tracks) <> "roArray" then return choices
    if tracks.Count() > 32 then return choices
    seenIds = {}:seenOrdinals = {}
    for each track in tracks
        if type(track) = "roAssociativeArray"
            trackId = SiloUIDetailAudioText(track.id)
            codec = LCase(SiloUIDetailAudioText(track.codec)).Trim()
            language = LCase(SiloUIDetailAudioText(track.language)).Trim()
            if SiloUIDetailAudioOrdinal(track.sourceOrdinal) and trackId <> "" and Len(trackId) <= 512 and codec <> ""
                key = Int(track.sourceOrdinal).ToStr()
                if seenIds.DoesExist(trackId) or seenOrdinals.DoesExist(key) then return []
                seenIds[trackId] = true:seenOrdinals[key] = true
                channels = 0
                if SiloUIDetailAudioOrdinal(track.channels) then channels = track.channels
                label = SiloUIDetailAudioLabel(language,codec,channels)
                choices.Push({itemId:item.itemId,fileId:fileId,trackId:trackId,sourceOrdinal:Int(track.sourceOrdinal),codec:codec,language:language,channels:channels,label:label})
            end if
        end if
    end for
    if choices.Count() < 2 then return []
    return choices
end function

function SiloUIDetailAudioLabel(language as String, codec as String, channels as Integer) as String
    languages = {en:"English",eng:"English",es:"Spanish",spa:"Spanish",fr:"French",fra:"French",fre:"French",de:"German",deu:"German",ger:"German",it:"Italian",ita:"Italian",ja:"Japanese",jpn:"Japanese",ko:"Korean",kor:"Korean",zh:"Chinese",zho:"Chinese",chi:"Chinese",pt:"Portuguese",por:"Portuguese"}
    name = languages[language]
    if name = invalid then name = Left(UCase(language),16)
    if name = "" then name = "Unknown language"
    codecs = {ac3:"Dolby Digital","ac-3":"Dolby Digital",eac3:"Dolby Digital Plus","e-ac-3":"Dolby Digital Plus",dts:"DTS",dca:"DTS",aac:"AAC",truehd:"Dolby TrueHD"}
    format = codecs[codec]
    if format = invalid then format = Left(UCase(codec),32)
    label = name + " · " + format
    if channels = 1 then return label + " · Mono"
    if channels = 2 then return label + " · Stereo"
    if channels = 6 then return label + " · 5.1"
    if channels = 8 then return label + " · 7.1"
    if channels > 0 then label += " · " + channels.ToStr() + " channels"
    return label
end function

function SiloUIDetailAudioMatch(choice as Dynamic, itemId as String, fileId as String, versions as Dynamic) as Dynamic
    if type(choice) <> "roAssociativeArray" then return invalid
    if choice.itemId <> itemId or choice.fileId <> fileId then return invalid
    for each track in SiloUIDetailAudioChoices("silo",{itemId:itemId,type:"movie"},versions,fileId)
        if track.trackId = choice.trackId and track.sourceOrdinal = choice.sourceOrdinal and track.codec = choice.codec and track.language = choice.language and track.channels = choice.channels then return track
    end for
    return invalid
end function

' Catalog qualification only; the Task separately proves device and fresh source.
function SiloUIDetailExperimentalVersion(provider as String, item as Dynamic, versions as Dynamic, selected as String) as String
    if provider <> "silo" or type(item) <> "roAssociativeArray" or type(versions) <> "roArray" then return ""
    if item.type <> "movie" and item.type <> "episode" then return ""
    if SiloUIDetailAudioText(item.itemId) = "" or versions.Count() > 16 then return ""
    seen = {}:qualified = "":matches = 0
    for each version in versions
        if type(version) <> "roAssociativeArray" then return ""
        fileId = SiloUIDetailAudioText(version.versionId)
        if fileId = "" or seen.DoesExist(fileId) then return ""
        seen[fileId] = true
        if selected = "" or selected = fileId
            tracks = version.videoTracks
            if type(tracks) = "roArray"
                if tracks.Count() = 1 and type(tracks[0]) = "roAssociativeArray"
                    video = tracks[0]
                    compatible = (video.dv_profile = 7 and video.dv_bl_compat_id = 6) or (video.dv_profile = 8 and video.dv_bl_compat_id = 1)
                    if compatible and video.codec = "hevc" and SiloUIDetailExperimentalRaster(video) and video.bit_depth = 10 and video.color_transfer = "smpte2084" and video.color_primaries = "bt2020" and video.color_space = "bt2020nc"
                        qualified = fileId:matches++
                    end if
                end if
            end if
        end if
    end for
    if matches <> 1 then return ""
    return qualified
end function

' Cinematic UHD can omit letterbox rows; the worker rechecks decoder bounds.
function SiloUIDetailExperimentalRaster(video as Object) as Boolean
    width = video.width:height = video.height
    numericWidth = false:numericHeight = false
    for each kind in ["Integer","roInt","roInteger","LongInteger","roLongInteger","Float","roFloat","Double","roDouble"]
        if type(width) = kind then numericWidth = true
        if type(height) = kind then numericHeight = true
    end for
    if not numericWidth or not numericHeight then return false
    if width <> 3840 or height <= 0 or height > 2160 then return false
    return Int(height) = height
end function

' Match detail labels and ordinary Play to the same bounded resume position.
function SiloUIDetailResumeMs(item as Object) as Double
    resume = NumberOr(item.resumeMs,0)
    if resume <> resume or resume <= 0 or resume > 315576000000# then return 0
    return resume
end function

' Number identical encodes without exposing source filenames or private identifiers.
' Auto retains the existing device/server selection policy; source facts are not support claims.
function SiloUIDetailVersionLabels(versions as Object, selected as String) as Object
    automatic = "Auto"
    if selected = "" then automatic = automatic + " (selected)"
    labels = [automatic]
    for index = 0 to versions.Count()-1
        version = versions[index]
        label = "Version " + (index+1).ToStr()
        if selected <> "" and TextOr(version.versionId) = selected then label = label + " (selected)"
        bitrate = NumberOr(version.bitrateKbps,0)
        rate = ""
        if bitrate > 0 and bitrate <= 1000000 then rate = Str(Int(bitrate / 100#) / 10.0).Trim() + " Mbps"
        labels.Push(JoinDots([label,SourceVersionQuality(version),rate]))
    end for
    return labels
end function

function SiloUIEpisodeActionLabels(provider as String, item as Object, versions as Object, selected as String) as Object
    labels = ["Play"]
    resume = SiloUIDetailResumeMs(item)
    if resume > 0
        labels = ["Resume", "From beginning"]
    end if
    if item.watched = true then labels.Push("Mark unwatched") else labels.Push("Mark watched")
    if versions.Count() > 1 then labels.Push("Version")
    if SiloUIDetailAudioChoices(provider,item,versions,selected).Count() > 1 then labels.Push("Audio")
    labels.Push("Cancel")
    return labels
end function
