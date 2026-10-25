' Pure compatibility wire identity/time policy. No session, transport or SDK I/O.
' Numeric file identity stays decimal text; never parse the uint64 as a Float.
function SiloCompatMediaSourceId(decimalString = invalid as Dynamic) as Dynamic
    kind = Type(decimalString)
    if kind <> "String" and kind <> "roString" then return invalid
    if Len(decimalString) < 1 or Len(decimalString) > 20 then return invalid
    if not CreateObject("roRegex","^[1-9][0-9]{0,19}$","").IsMatch(decimalString) then return invalid
    if Len(decimalString) = 20 and decimalString > "18446744073709551615" then return invalid
    digits = "0123456789abcdef":encoded = ""
    while decimalString <> "0"
        quotient = "":remainder = 0
        for index = 1 to Len(decimalString)
            value = remainder * 10 + Asc(Mid(decimalString,index,1)) - 48
            digit = value \ 16:remainder = value mod 16
            if quotient <> "" or digit > 0 then quotient += digit.ToStr()
        end for
        encoded = Mid(digits,remainder+1,1) + encoded
        if quotient = "" then quotient = "0"
        decimalString = quotient
    end while
    encoded = Right("0000000000000000"+encoded,16)
    return "03000000-0000-0000-"+Left(encoded,4)+"-"+Mid(encoded,5)
end function

' Compatibility DTOs require int64 ticks. Bound the numeric calculation below
' JSON's exact-integer ceiling, then truncate sub-tick fractions into int64.
function SiloCompatPositionTicks(seconds = invalid as Dynamic) as Dynamic
    kind = Type(seconds)
    if kind <> "Integer" and kind <> "roInt" and kind <> "roInteger" and kind <> "LongInteger" and kind <> "roLongInteger" and kind <> "Float" and kind <> "roFloat" and kind <> "Double" and kind <> "roDouble" then return invalid
    if seconds <> seconds then return invalid
    if seconds < 0 or seconds > 900719925# then return invalid
    ticks& = seconds * 10000000#
    return ticks&
end function

function SiloCompatManualVersionValid(params as Dynamic, fileId as Dynamic) as Boolean
    marker = SpField(params,"manualVersionSelection")
    if not SpFields(marker,["requestedFileId"],["explicitAudioSelection"]) then return false
    if not SpText(fileId,64) or marker.requestedFileId <> fileId then return false
    if marker.DoesExist("explicitAudioSelection")
        choice = marker.explicitAudioSelection
        if not SpFields(choice,["id","index","track"],[]) then return false
        if not SpNumber(choice.index,31,true) then return false
        if choice.id <> "file:"+fileId+":audio:"+Int(choice.index).ToStr() then return false
        if SpField(params,"audioTrackId") <> choice.id or SpField(params,"audioTrackIndex") <> choice.index then return false
    end if
    if not SpBool(SpField(params,"autoVersion")) or params.autoVersion <> false then return false
    return SpField(params,"eligibilityKind") = "experimental_query_p8_ts_v1" and SpField(params,"autoAudioSelection") = invalid
end function

' Compatibility source proof; native activation is gated separately.
function SiloCompatCandidate(detail as Dynamic, owner as Dynamic, params as Dynamic, snapshot as Dynamic, kind = invalid as Dynamic, qualification = invalid as Dynamic) as Dynamic
    if SpText(kind,64)
        if kind = "experimental_query_p8_hdr10_ac3_fmp4_v1" then return SiloCompatP8HDR10Candidate(detail,owner,params,snapshot,kind)
        if kind = "experimental_query_p8_hdr10_fmp4_v1" then return SiloCompatP8HDR10Candidate(detail,owner,params,snapshot)
        if kind = "experimental_query_p7_hdr10_aac_fmp4_v1" then return SiloCompatP7AACCandidate(detail,owner,params,snapshot,qualification)
        if kind = "experimental_query_p7_hdr10_fmp4_v1" then return SiloCompatP7Candidate(detail,owner,params,snapshot)
    end if
    modern = false
    if kind <> invalid
        if not SpText(kind,64) then return invalid
        if kind <> "experimental_query_p8_ts_v1" then return invalid
        modern = true
    end if
    scope = SpScope(owner)
    if scope = invalid or not SpNumber(SpField(owner,"sessionRevision"),2147483646,true) then return invalid
    if SpField(params,"qualityPreference") <> "original" then return invalid
    captions = modern and SpField(params,"subtitleMode") = "on"
    if not captions and SpField(params,"subtitleMode") <> "off" then return invalid
    file = SiloPlaybackFile(detail,scope.sourceId,SpField(params,"itemId"),SpField(params,"fileId"),SpField(params,"startPositionMs",0))
    if file = invalid then return invalid
    cap = SpField(params,"bandwidthCapKbps",0)
    if not SpNumber(cap,2147483646,true) then return invalid
    if cap > 0 and (file.bitrateKbps <= 0 or file.bitrateKbps > cap) then return invalid
    if modern and file.bitrateKbps <= 0 then return invalid
    uuid = SiloCompatMediaSourceId(file.versionId)
    if uuid = invalid then return invalid
    version = file.version
    if version.container <> "mkv" or type(version.videoTracks) <> "roArray" or version.videoTracks.Count() <> 1 then return invalid
    video = version.videoTracks[0]
    if modern
        if not SiloCompatModernVideo(video) then return invalid
    end if
    if SoVideoGate(video) <> "" or video.dv_profile <> 8 then return invalid
    if not modern and video.width <> 3840 then return invalid
    if type(version.audioTracks) <> "roArray" or version.audioTracks.Count() = 0 or version.audioTracks.Count() > 32 then return invalid
    ordinal = SpField(params,"audioTrackIndex")
    if ordinal = invalid
        for index = 0 to version.audioTracks.Count()-1
            if version.audioTracks[index].isDefault = true
                if ordinal <> invalid then return invalid
                ordinal = index
            end if
        end for
    end if
    if not SpNumber(ordinal,version.audioTracks.Count()-1,true) then return invalid
    if params.DoesExist("manualVersionSelection")
        if not modern or not SiloCompatManualVersionValid(params,file.versionId) then return invalid
        if params.manualVersionSelection.DoesExist("explicitAudioSelection")
            if FormatJson(params.manualVersionSelection.explicitAudioSelection.track) <> FormatJson(version.audioTracks[ordinal]) then return invalid
        end if
        if not params.manualVersionSelection.DoesExist("explicitAudioSelection")
            if version.audioTracks[ordinal].isDefault <> true then return invalid
            for index = 0 to version.audioTracks.Count()-1
                if index <> ordinal and version.audioTracks[index].isDefault = true then return invalid
            end for
        end if
    end if
    audio = version.audioTracks[ordinal]
    if audio.sourceOrdinal <> ordinal or audio.codec <> "eac3" or not SpNumber(audio.channels,6,true) or audio.channels = 0 then return invalid
    if SpField(params,"audioTrackId","") <> "" and params.audioTrackId <> "file:"+file.versionId+":audio:"+ordinal.ToStr() then return invalid
    if not SpText(audio.language,32) then return invalid
    if type(snapshot) <> "roAssociativeArray" then return invalid
    if modern
        if not SiloCompatModernSnapshot(snapshot,video,audio) then return invalid
    else
        if snapshot.model <> "C000X" or snapshot.modelNumber <> "C208X" or snapshot.modelType <> "TV" then return invalid
        if snapshot.os <> "16.0.4.834" or snapshot.videoMode <> "2160p60" or snapshot.dolbyVision <> true or snapshot.hevcMain10 <> true then return invalid
        if snapshot.audioCodec <> audio.codec or snapshot.audioChannels <> audio.channels then return invalid
        if snapshot.audioDecode <> true and snapshot.audioPassthrough <> true then return invalid
    end if
    proof = {subtitleMode:"off",mediaSourceId:uuid,fileId:file.versionId,video:video,audio:audio,audioOrdinal:ordinal,audioInventory:version.audioTracks,startTicks:SiloCompatPositionTicks(SpField(params,"startPositionMs",0)/1000#),snapshot:snapshot}
    if captions
        if not SiloCompatP7Inventories(version.audioTracks,version.subtitleTracks) then return invalid
        proof["captionMode"] = "on":proof["subtitleInventory"] = SpCopy(version.subtitleTracks)
    end if
    if modern then proof.eligibilityKind = "experimental_query_p8_ts_v1"
    return proof
end function

function SiloCompatSourceMetadata(decoded as Dynamic, proof as Dynamic) as Dynamic
    if (SpField(proof,"eligibilityKind") = "experimental_query_p8_hdr10_fmp4_v1" or SpField(proof,"eligibilityKind") = "experimental_query_p8_hdr10_ac3_fmp4_v1") then return SiloCompatHDR10SourceMetadata(decoded,proof,false,true)
    if SpField(proof,"eligibilityKind") = "experimental_query_p7_hdr10_aac_fmp4_v1" then return SiloCompatP7SourceMetadata(decoded,proof)
    if SpField(proof,"eligibilityKind") = "experimental_query_p7_hdr10_fmp4_v1" then return SiloCompatP7SourceMetadata(decoded,proof)
    if SiloCompatClassForKind(SpField(proof,"eligibilityKind")) = invalid then return invalid
    if SpField(SpField(proof,"video"),"dv_profile") <> 8 then return invalid
    if not SiloObject(decoded) or not SiloArray(decoded.MediaSources) then return invalid
    selected = invalid
    for each source in decoded.MediaSources
        if SiloObject(source) and source.Id = proof.mediaSourceId
            if selected <> invalid then return invalid
            selected = source
        end if
    end for
    if selected = invalid or not SiloArray(selected.MediaStreams) then return invalid
    if selected.MediaStreams.Count() > 64 then return invalid
    videoCount = 0:audioCount = 0:subtitleCount = 0:selectedIndex = invalid:seen = {}
    for each stream in selected.MediaStreams
        if not SiloObject(stream) or not SpNumber(stream.Index,4095,true) then return invalid
        key = stream.Index.ToStr()
        if seen.DoesExist(key) then return invalid
        seen[key] = true
        if stream.Type = "Video"
            videoCount++
            if stream.Codec <> "hevc" or stream.Width <> proof.video.width or stream.Height <> proof.video.height or stream.BitDepth <> 10 or stream.VideoRangeType <> "DOVIWithHDR10" then return invalid
            if not SoNear(stream.AverageFrameRate,SoFrameRate(proof.video.frame_rate)) then return invalid
        else if stream.Type = "Audio"
            if audioCount >= proof.audioInventory.Count() then return invalid
            expected = proof.audioInventory[audioCount]
            if stream.Codec <> expected.codec or stream.Language <> expected.language or stream.Channels <> expected.channels then return invalid
            if audioCount = proof.audioOrdinal then selectedIndex = stream.Index
            audioCount++
        else if stream.Type = "Subtitle"
            subtitleCount++
        else
            return invalid
        end if
    end for
    if videoCount <> 1 or audioCount <> proof.audioInventory.Count() or selectedIndex = invalid then return invalid
    if SpField(proof,"captionMode") = "on"
        if not SiloArray(proof.subtitleInventory) or subtitleCount <> proof.subtitleInventory.Count() then return invalid
        for each expected in proof.subtitleInventory
            matched = 0
            for each stream in selected.MediaStreams
                if stream.Type = "Subtitle" and stream.Index = expected.index
                    if stream.Codec <> expected.codec or stream.Language <> expected.language then return invalid
                    if not SpBool(stream.IsForced) or stream.IsForced <> expected.forced then return invalid
                    matched++
                end if
            end for
            if matched <> 1 then return invalid
        end for
    end if
    return {audioStreamIndex:selectedIndex,subtitleCount:subtitleCount,source:selected}
end function

function SiloCompatPlaybackReceipt(decoded as Dynamic, proof as Dynamic, baseUrl as Dynamic, audioIndex as Dynamic) as Dynamic
    if (SpField(proof,"eligibilityKind") = "experimental_query_p8_hdr10_fmp4_v1" or SpField(proof,"eligibilityKind") = "experimental_query_p8_hdr10_ac3_fmp4_v1") then return SiloCompatHDR10Receipt(decoded,proof,baseUrl,audioIndex,true)
    if SpField(proof,"eligibilityKind") = "experimental_query_p7_hdr10_aac_fmp4_v1" then return SiloCompatP7Receipt(decoded,proof,baseUrl,audioIndex)
    if SpField(proof,"eligibilityKind") = "experimental_query_p7_hdr10_fmp4_v1" then return SiloCompatP7Receipt(decoded,proof,baseUrl,audioIndex)
    if not SiloObject(decoded) or not SiloArray(decoded.MediaSources) then return invalid
    if decoded.MediaSources.Count() <> 1 or not SiloCompatPattern(decoded.PlaySessionId,"^[A-Za-z0-9_-]+$",128) then return invalid
    metadata = SiloCompatSourceMetadata(decoded,proof)
    if metadata = invalid or metadata.audioStreamIndex <> audioIndex then return invalid
    source = metadata.source
    if source.DefaultAudioStreamIndex <> audioIndex then return invalid
    if source.DoesExist("DefaultSubtitleStreamIndex")
        subtitleIndex = SiloNumber(source.DefaultSubtitleStreamIndex,invalid)
        if subtitleIndex = invalid then return invalid
        if subtitleIndex <> -1 then return invalid
    else
        ' Official Go DTO omits its nil default for explicit Off.
        if SpField(proof,"subtitleMode") <> "off" then return invalid
    end if
    ' PlaybackInfo applies the explicit Off selection to every subtitle stream.
    ' Metadata before the request may legitimately advertise a default subtitle.
    for each stream in source.MediaStreams
        if stream.Type = "Subtitle"
            if not SpBool(SpField(stream,"IsDefault")) then return invalid
            if stream.IsDefault <> false then return invalid
        end if
    end for
    if source.SupportsDirectPlay <> false or source.SupportsTranscoding <> true or source.SiloSeekReanchor <> true then return invalid
    if source.TranscodingSubProtocol <> "hls" or source.TranscodingContainer <> "ts" then return invalid
    if not SiloCompatPattern(source.TranscodingUrl,"^[!-~]+$",2048) then return invalid
    expected = "/Videos/"+proof.mediaSourceId+"/remux-ts-v1/master.m3u8?PlaySessionId="+decoded.PlaySessionId+"&MediaSourceId="+proof.mediaSourceId
    base = SiloUrlParts(baseUrl)
    if base.ok <> true then return invalid
    ' Official route is origin-relative, including an advertised listener prefix.
    privateUrl = ""
    if source.TranscodingUrl = expected
        privateUrl = baseUrl+expected
    else if source.TranscodingUrl = base.path+expected
        privateUrl = base.authority+source.TranscodingUrl
    else
        return invalid
    end if
    return {playSessionId:decoded.PlaySessionId,url:privateUrl,audioStreamIndex:audioIndex,class:"copied_dv8_ts",videoCopyRecipe:true,physicalDVVerified:false}
end function

function SiloCompatDeviceProfile(proof as Object) as Object
    if SpField(proof,"eligibilityKind") = "experimental_query_p7_hdr10_aac_fmp4_v1"
        if not SiloCompatP7AACProof(proof) then return {}
        return {Name:"Silo Roku",MaxStreamingBitrate:120000000,DirectPlayProfiles:[],TranscodingProfiles:[{Type:"Video",Context:"Streaming",Protocol:"hls",Container:"mp4",VideoCodec:"hevc",AudioCodec:"aac",MaxAudioChannels:"2"}],CodecProfiles:[{Type:"Video",Codec:"hevc",Conditions:[{Condition:"EqualsAny",Property:"VideoRangeType",Value:"HDR10",IsRequired:true},{Condition:"EqualsAny",Property:"VideoCodecTag",Value:"hvc1",IsRequired:true}]}]}
    end if
    if (SpField(proof,"eligibilityKind") = "experimental_query_p8_hdr10_fmp4_v1" or SpField(proof,"eligibilityKind") = "experimental_query_p8_hdr10_ac3_fmp4_v1")
        if not SiloCompatP8HDR10Proof(proof) then return {}
        return {Name:"Silo Roku",MaxStreamingBitrate:120000000,DirectPlayProfiles:[],TranscodingProfiles:[{Type:"Video",Context:"Streaming",Protocol:"hls",Container:"mp4",VideoCodec:"hevc",AudioCodec:proof.audio.codec,MaxAudioChannels:proof.audio.channels.ToStr()}],CodecProfiles:[{Type:"Video",Codec:"hevc",Conditions:[{Condition:"EqualsAny",Property:"VideoRangeType",Value:"HDR10",IsRequired:true},{Condition:"EqualsAny",Property:"VideoCodecTag",Value:"hvc1",IsRequired:true}]}]}
    end if
    if SpField(proof,"eligibilityKind") = "experimental_query_p7_hdr10_fmp4_v1"
        if not SiloCompatP7Proof(proof) then return {}
        return {Name:"Silo Roku",MaxStreamingBitrate:120000000,DirectPlayProfiles:[],TranscodingProfiles:[{Type:"Video",Context:"Streaming",Protocol:"hls",Container:"mp4",VideoCodec:"hevc",AudioCodec:"ac3",MaxAudioChannels:proof.audio.channels.ToStr()}],CodecProfiles:[{Type:"Video",Codec:"hevc",Conditions:[{Condition:"EqualsAny",Property:"VideoRangeType",Value:"HDR10",IsRequired:true},{Condition:"EqualsAny",Property:"VideoCodecTag",Value:"hvc1",IsRequired:true}]}]}
    end if
    if SiloCompatClassForKind(SpField(proof,"eligibilityKind")) = invalid or SpField(SpField(proof,"video"),"dv_profile") <> 8 then return {}
    return {Name:"Silo Roku",DirectPlayProfiles:[],TranscodingProfiles:[{Type:"Video",Protocol:"hls",Container:"mp4",VideoCodec:"hevc",AudioCodec:proof.audio.codec,MaxAudioChannels:proof.audio.channels.ToStr()}],CodecProfiles:[{Type:"Video",Codec:"hevc",Conditions:[{Condition:"LessThanEqual",Property:"Width",Value:proof.video.width.ToStr(),IsRequired:true},{Condition:"LessThanEqual",Property:"Height",Value:proof.video.height.ToStr(),IsRequired:true}]}]}
end function

' Strict prerequisites are local to this experimental route; legacy gates stay intact.
function SiloCompatModernVideo(video as Dynamic) as Boolean
    if type(video) <> "roAssociativeArray" then return false
    for each name in ["dv_config_present","dv_bl_present","dv_rpu_present","dv_bl_compat_id_present","interlaced"]
        if not SpBool(SpField(video,name)) then return false
    end for
    for each name in ["dv_el_present","hdr10_plus"]
        if video.DoesExist(name)
            if not SpBool(video[name]) then return false
        end if
    end for
    for each name in ["dv_profile","dv_level","dv_bl_compat_id","level","bit_depth"]
        if not SpNumber(SpField(video,name),1000,true) then return false
    end for
    if video.level <> 150 and video.level <> 153 then return false
    rate = SoFrameRate(SpField(video,"frame_rate"))
    if rate = invalid then return false
    if rate <= 0 or rate > 24 then return false
    return true
end function

function SiloCompatModernIdentity(snapshot as Dynamic) as Boolean
    if type(snapshot) <> "roAssociativeArray" then return false
    for each name in ["model","modelNumber","modelType"]
        value = SpField(snapshot,name)
        if not SpText(value,128) then return false
        if value.Trim() = "" then return false
    end for
    if not SpText(SpField(snapshot,"os"),64) then return false
    if not CreateObject("roRegex","^[0-9]+[.][0-9]+[.][0-9]+[.][0-9]+$","").IsMatch(snapshot.os) then return false
    mode = SpField(snapshot,"videoMode")
    if not SpText(mode,16) then return false
    ' Documented GetVideoMode spellings; suffixes do not replace SDK evidence.
    if not CreateObject("roRegex","^2160p((24|25|30|50|60)(b10)?|(30|60)Dv)$","").IsMatch(mode) then return false
    if not SpBool(SpField(snapshot,"dolbyVision")) then return false
    return snapshot.dolbyVision = true
end function

function SiloCompatModernSnapshot(snapshot as Dynamic, video as Object, audio as Object) as Boolean
    if not SpFields(snapshot,["model","modelNumber","modelType","os","videoMode","dolbyVision","hevcMain10","audioCodec","audioChannels","audioDecode","audioPassthrough","videoQuery","audioContainer"],[]) then return false
    if not SiloCompatModernIdentity(snapshot) then return false
    if not SpBool(snapshot.hevcMain10) then return false
    if not snapshot.hevcMain10 then return false
    query = snapshot.videoQuery
    if not SpFields(query,["codec","container","profile","level","result"],[]) then return false
    level = "5.0"
    if video.level = 153 then level = "5.1"
    if query.codec <> "hevc" or query.container <> "ts" or query.profile <> "main 10" or query.level <> level then return false
    if not SpBool(query.result) then return false
    if not query.result then return false
    if snapshot.audioContainer <> "ts" or snapshot.audioCodec <> audio.codec then return false
    if not SpNumber(snapshot.audioChannels,6,true) then return false
    if snapshot.audioChannels <> audio.channels then return false
    for each name in ["audioDecode","audioPassthrough"]
        value = snapshot[name]
        if value <> invalid
            if not SpBool(value) then return false
        end if
    end for
    return snapshot.audioDecode = true or snapshot.audioPassthrough = true
end function

function SiloCompatHDR10Identity(snapshot as Dynamic) as Boolean
    if type(snapshot) <> "roAssociativeArray" then return false
    for each name in ["model","modelNumber","modelType"]
        value = SpField(snapshot,name)
        if not SpText(value,128) then return false
        if value.Trim() = "" then return false
    end for
    if not SpText(SpField(snapshot,"os"),64) then return false
    if not CreateObject("roRegex","^[0-9]+[.][0-9]+[.][0-9]+[.][0-9]+$","").IsMatch(snapshot.os) then return false
    mode = SpField(snapshot,"videoMode")
    if not SpText(mode,16) then return false
    if not CreateObject("roRegex","^2160p((24|25|30|50|60)(b10)?|(30|60)Dv)$","").IsMatch(mode) then return false
    if not SpBool(SpField(snapshot,"hdr10")) then return false
    return snapshot.hdr10 = true
end function

function SiloCompatP7Video(video as Dynamic) as Boolean
    if not SiloCompatModernVideo(video) then return false
    if SoVideoGate(video) <> "" then return false
    return video.dv_profile = 7 and video.dv_level = 6 and video.dv_bl_compat_id = 6 and video.dv_el_present = true and video.dv_enhancement_layer = "unknown" and video.level = 153 and video.width = 3840 and video.height = 2160
end function

function SiloCompatP7Snapshot(snapshot as Dynamic, video as Object, audio as Object) as Boolean
    if not SpFields(snapshot,["model","modelNumber","modelType","os","videoMode","hdr10","hevcMain10","audioCodec","audioChannels","audioDecode","audioPassthrough","videoQuery","audioContainer"],[]) then return false
    if not SiloCompatHDR10Identity(snapshot) then return false
    if not SpBool(snapshot.hevcMain10) then return false
    if not snapshot.hevcMain10 then return false
    query = snapshot.videoQuery
    if not SpFields(query,["codec","container","profile","level","result"],[]) then return false
    if query.codec <> "hevc" or query.container <> "mp4" or query.profile <> "main 10" or query.level <> "5.1" then return false
    if not SpBool(query.result) then return false
    if not query.result then return false
    if snapshot.audioContainer <> "mp4" or snapshot.audioCodec <> "ac3" or snapshot.audioCodec <> audio.codec then return false
    if not SpNumber(snapshot.audioChannels,6,true) then return false
    if (snapshot.audioChannels <> 2 and snapshot.audioChannels <> 6) or snapshot.audioChannels <> audio.channels then return false
    for each name in ["audioDecode","audioPassthrough"]
        value = snapshot[name]
        if value <> invalid
            if not SpBool(value) then return false
        end if
    end for
    return snapshot.audioDecode = true or snapshot.audioPassthrough = true
end function

function SiloCompatP7AACSnapshot(snapshot as Dynamic, video as Object) as Boolean
    if not SpFields(snapshot,["model","modelNumber","modelType","os","videoMode","hdr10","hevcMain10","videoQuery","targetAudioCodec","targetAudioChannels","targetAudioDecode","targetAudioContainer"],[]) then return false
    if not SiloCompatHDR10Identity(snapshot) or not SpBool(snapshot.hevcMain10) or not snapshot.hevcMain10 then return false
    query = snapshot.videoQuery
    if not SpFields(query,["codec","container","profile","level","result"],[]) then return false
    if query.codec <> "hevc" or query.container <> "mp4" or query.profile <> "main 10" or query.level <> "5.1" then return false
    if not SpBool(query.result) or not query.result then return false
    if snapshot.targetAudioCodec <> "aac" or snapshot.targetAudioContainer <> "mp4" then return false
    if not SpNumber(snapshot.targetAudioChannels,2,true) or snapshot.targetAudioChannels <> 2 then return false
    if not SpBool(snapshot.targetAudioDecode) then return false
    return snapshot.targetAudioDecode = true
end function

function SiloCompatP7Inventories(audios as Dynamic, subtitles as Dynamic) as Boolean
    if type(audios) <> "roArray" or type(subtitles) <> "roArray" then return false
    if audios.Count() < 1 or audios.Count() > 32 or audios.Count()+subtitles.Count()+1 > 64 then return false
    for index = 0 to audios.Count()-1
        audio = audios[index]
        if not SpNumber(SpField(audio,"sourceOrdinal"),31,true) then return false
        if audio.sourceOrdinal <> index or not SpText(SpField(audio,"codec"),32) then return false
        if not SpBool(SpField(audio,"wireIndexPresent")) then return false
        if audio.wireIndexPresent then return false
        if not SpNumber(SpField(audio,"channels"),32,true) then return false
        if audio.channels = 0 or not SpText(SpField(audio,"language"),32,true) then return false
        if not SpBool(SpField(audio,"isDefault")) then return false
    end for
    seen = {}
    for each subtitle in subtitles
        if not SpNumber(SpField(subtitle,"index"),4095,true) then return false
        if subtitle.index < audios.Count()+1 then return false
        key = subtitle.index.ToStr()
        if seen.DoesExist(key) then return false
        seen[key] = true
        if not SpText(SpField(subtitle,"codec"),32) or not SpText(SpField(subtitle,"language"),32,true) then return false
        for each name in ["isDefault","forced","hearingImpaired","external"]
            if not SpBool(SpField(subtitle,name)) then return false
        end for
    end for
    return true
end function

function SiloCompatP7Candidate(detail as Dynamic, owner as Dynamic, params as Dynamic, snapshot as Dynamic) as Dynamic
    scope = SpScope(owner)
    if scope = invalid or not SpNumber(SpField(owner,"sessionRevision"),2147483646,true) then return invalid
    if SpField(params,"subtitleMode") <> "off" or SpField(params,"qualityPreference") <> "original" then return invalid
    file = SiloPlaybackFile(detail,scope.sourceId,SpField(params,"itemId"),SpField(params,"fileId"),SpField(params,"startPositionMs",0))
    if file = invalid then return invalid
    if not SpNumber(file.bitrateKbps,2147483646,true) then return invalid
    if file.bitrateKbps <= 0 or detail.versions.Count() <> 1 then return invalid
    cap = SpField(params,"bandwidthCapKbps",0)
    if not SpNumber(cap,2147483646,true) then return invalid
    if cap > 0 and file.bitrateKbps > cap then return invalid
    uuid = SiloCompatMediaSourceId(file.versionId)
    if uuid = invalid then return invalid
    version = file.version
    if version.container <> "mkv" or type(version.videoTracks) <> "roArray" then return invalid
    if version.videoTracks.Count() <> 1 then return invalid
    video = version.videoTracks[0]
    if not SiloCompatP7Video(video) then return invalid
    if not SiloCompatP7Inventories(SpField(version,"audioTracks"),SpField(version,"subtitleTracks")) then return invalid
    ordinal = SpField(params,"audioTrackIndex")
    if not SpNumber(ordinal,version.audioTracks.Count()-1,true) then return invalid
    if SpField(params,"audioTrackId") <> "file:"+file.versionId+":audio:"+ordinal.ToStr() then return invalid
    audio = version.audioTracks[ordinal]
    if audio.codec <> "ac3" or (audio.channels <> 2 and audio.channels <> 6) or not SpText(audio.language,32) then return invalid
    if not SiloCompatP7Snapshot(snapshot,video,audio) then return invalid
    return {eligibilityKind:"experimental_query_p7_hdr10_fmp4_v1",subtitleMode:"off",mediaSourceId:uuid,fileId:file.versionId,video:video,audio:audio,audioOrdinal:ordinal,audioInventory:version.audioTracks,subtitleInventory:version.subtitleTracks,sourceBitrateKbps:file.bitrateKbps,sourceDurationMs:file.durationMs,startTicks:SiloCompatPositionTicks(SpField(params,"startPositionMs",0)/1000#),snapshot:snapshot,ownerBinding:{provider:scope.provider,sourceId:scope.sourceId,profileId:scope.profileId,generation:scope.generation,sessionRevision:owner.sessionRevision}}
end function

' The locally named qualification is a trusted QA opt-in, not server attestation.
' Its closed schema deliberately excludes configurable server Version fields.
function SiloCompatP7AACQualification(owner as Dynamic, qualification as Dynamic) as Dynamic
    scope = SpScope(owner)
    if scope = invalid or not SpNumber(SpField(owner,"sessionRevision"),2147483646,true) then return invalid
    if not SpText(scope.profileId,256) then return invalid
    required = ["schemaVersion","kind","approved","sourceId","profileId","generation"]
    hasRevision = false
    if type(owner) = "roAssociativeArray" and owner.DoesExist("sessionRevision") then
        hasRevision = true:required.Push("sessionRevision")
    end if
    if not SpFields(qualification,required,[]) then return invalid
    if not SpNumber(qualification.schemaVersion,1,true) or qualification.schemaVersion <> 1 then return invalid
    if qualification.kind <> "stock48ae-p7-hdr10-aac2-v1" then return invalid
    if not SpBool(qualification.approved) or not qualification.approved then return invalid
    if not SpText(qualification.sourceId,512) or qualification.sourceId <> scope.sourceId then return invalid
    if not SpText(qualification.profileId,256) or qualification.profileId <> scope.profileId then return invalid
    if not SpNumber(qualification.generation,2147483646,true) or qualification.generation <> scope.generation then return invalid
    if hasRevision
        if not SpNumber(qualification.sessionRevision,2147483646,true) or qualification.sessionRevision <> owner.sessionRevision then return invalid
    end if
    return {schemaVersion:1,kind:"stock48ae-p7-hdr10-aac2-v1",approved:true,sourceId:scope.sourceId,profileId:scope.profileId,generation:scope.generation,sessionRevision:SpField(owner,"sessionRevision")}
end function

function SiloCompatP7AACSource(audio as Dynamic, ordinal as Dynamic) as Boolean
    if type(audio) <> "roAssociativeArray" then return false
    if not SpNumber(ordinal,31,true) or not SpNumber(SpField(audio,"sourceOrdinal"),31,true) then return false
    if audio.sourceOrdinal <> ordinal or not SpText(SpField(audio,"language"),32) then return false
    if not SpBool(SpField(audio,"isDefault")) then return false
    if ordinal = 0 then return audio.codec = "truehd" and audio.channels = 8
    if ordinal = 1 then return audio.codec = "ac3" and audio.channels = 6
    return false
end function

function SiloCompatP7AACCandidate(detail as Dynamic, owner as Dynamic, params as Dynamic, snapshot as Dynamic, qualification as Dynamic) as Dynamic
    qualified = SiloCompatP7AACQualification(owner,qualification)
    if qualified = invalid then return invalid
    scope = SpScope(owner)
    if scope = invalid then return invalid
    if SpField(params,"subtitleMode") <> "off" or SpField(params,"qualityPreference") <> "original" then return invalid
    file = SiloPlaybackFile(detail,scope.sourceId,SpField(params,"itemId"),SpField(params,"fileId"),SpField(params,"startPositionMs",0))
    if file = invalid or not SpNumber(file.bitrateKbps,2147483646,true) then return invalid
    if file.bitrateKbps <= 0 or detail.versions.Count() <> 1 then return invalid
    cap = SpField(params,"bandwidthCapKbps",0)
    if not SpNumber(cap,2147483646,true) or (cap > 0 and file.bitrateKbps > cap) then return invalid
    uuid = SiloCompatMediaSourceId(file.versionId)
    if uuid = invalid then return invalid
    version = file.version
    if version.container <> "mkv" or type(version.videoTracks) <> "roArray" or version.videoTracks.Count() <> 1 then return invalid
    video = version.videoTracks[0]
    if not SiloCompatP7Video(video) then return invalid
    if not SiloCompatP7Inventories(SpField(version,"audioTracks"),SpField(version,"subtitleTracks")) then return invalid
    ordinal = SpField(params,"audioTrackIndex")
    if not SpNumber(ordinal,version.audioTracks.Count()-1,true) or not SiloCompatP7AACSource(version.audioTracks[ordinal],ordinal) then return invalid
    if SpField(params,"audioTrackId") <> "file:"+file.versionId+":audio:"+ordinal.ToStr() then return invalid
    audio = version.audioTracks[ordinal]
    if not SiloCompatP7AACSnapshot(snapshot,video) then return invalid
    binding = {provider:"silo",sourceId:qualified.sourceId,profileId:qualified.profileId,generation:qualified.generation,sessionRevision:qualified.sessionRevision}
    return {eligibilityKind:"experimental_query_p7_hdr10_aac_fmp4_v1",subtitleMode:"off",mediaSourceId:uuid,fileId:file.versionId,video:video,audio:audio,audioOrdinal:ordinal,audioInventory:version.audioTracks,subtitleInventory:version.subtitleTracks,sourceBitrateKbps:file.bitrateKbps,sourceDurationMs:file.durationMs,startTicks:SiloCompatPositionTicks(SpField(params,"startPositionMs",0)/1000#),targetAudio:{codec:"aac",channels:2},instanceQualification:qualified,ownerBinding:binding,snapshot:snapshot}
end function

function SiloCompatClassForKind(kind = invalid as Dynamic) as Dynamic
    if kind = invalid then return "copied_dv8_ts"
    if not SpText(kind,64) then return invalid
    if kind = "experimental_query_p8_hdr10_ac3_fmp4_v1" then return "copied_p8_hdr10_ac3_fmp4"
    if kind = "experimental_query_p8_hdr10_fmp4_v1" then return "copied_p8_hdr10_fmp4"
    if kind = "experimental_query_p8_ts_v1" then return "copied_dv8_ts"
    if kind = "experimental_query_p7_hdr10_fmp4_v1" then return "copied_p7_hdr10_fmp4"
    if kind = "experimental_query_p7_hdr10_aac_fmp4_v1" then return "converted_p7_hdr10_aac_fmp4"
    return invalid
end function

function SiloCompatP7AACProof(proof as Dynamic) as Boolean
    if SpField(proof,"eligibilityKind") <> "experimental_query_p7_hdr10_aac_fmp4_v1" or SpField(proof,"subtitleMode") <> "off" then return false
    video = SpField(proof,"video"):audio = SpField(proof,"audio")
    if not SiloCompatP7Video(video) or not SiloCompatP7Inventories(SpField(proof,"audioInventory"),SpField(proof,"subtitleInventory")) then return false
    ordinal = SpField(proof,"audioOrdinal")
    if not SpNumber(ordinal,proof.audioInventory.Count()-1,true) or not SiloCompatP7AACSource(audio,ordinal) then return false
    expected = proof.audioInventory[ordinal]
    for each name in ["sourceOrdinal","codec","channels","language","isDefault"]
        if SpField(audio,name) <> SpField(expected,name) then return false
    end for
    sourceId = SiloCompatMediaSourceId(SpField(proof,"fileId"))
    if sourceId = invalid or sourceId <> SpField(proof,"mediaSourceId") then return false
    if not SpNumber(SpField(proof,"sourceBitrateKbps"),2147483646,true) or proof.sourceBitrateKbps <= 0 then return false
    if not SpNumber(SpField(proof,"sourceDurationMs"),604800000,true) or proof.sourceDurationMs <= 0 then return false
    target = SpField(proof,"targetAudio")
    if not SpFields(target,["codec","channels"],[]) or target.codec <> "aac" or not SpNumber(target.channels,2,true) or target.channels <> 2 then return false
    binding = SpField(proof,"ownerBinding")
    if not SpFields(binding,["provider","sourceId","profileId","generation","sessionRevision"],[]) then return false
    qualification = SiloCompatP7AACQualification(binding,SpField(proof,"instanceQualification"))
    if qualification = invalid then return false
    return SiloCompatP7AACSnapshot(SpField(proof,"snapshot"),video)
end function

function SiloCompatP7Proof(proof as Dynamic) as Boolean
    if SpField(proof,"eligibilityKind") <> "experimental_query_p7_hdr10_fmp4_v1" or SpField(proof,"subtitleMode") <> "off" then return false
    video = SpField(proof,"video"):audio = SpField(proof,"audio")
    if not SiloCompatP7Video(video) then return false
    if not SiloCompatP7Inventories(SpField(proof,"audioInventory"),SpField(proof,"subtitleInventory")) then return false
    ordinal = SpField(proof,"audioOrdinal")
    if not SpNumber(ordinal,proof.audioInventory.Count()-1,true) then return false
    if type(audio) <> "roAssociativeArray" then return false
    if not SpBool(SpField(audio,"isDefault")) then return false
    if not SpNumber(SpField(audio,"sourceOrdinal"),31,true) then return false
    if audio.codec <> "ac3" or not SpNumber(SpField(audio,"channels"),6,true) then return false
    if (audio.channels <> 2 and audio.channels <> 6) or not SpText(SpField(audio,"language"),32) then return false
    expected = proof.audioInventory[ordinal]
    for each name in ["sourceOrdinal","codec","channels","language","isDefault"]
        if SpField(audio,name) <> SpField(expected,name) then return false
    end for
    sourceId = SiloCompatMediaSourceId(SpField(proof,"fileId"))
    if sourceId = invalid then return false
    if sourceId <> SpField(proof,"mediaSourceId") then return false
    if not SpNumber(SpField(proof,"sourceBitrateKbps"),2147483646,true) then return false
    if proof.sourceBitrateKbps <= 0 then return false
    if not SpNumber(SpField(proof,"sourceDurationMs"),604800000,true) then return false
    if proof.sourceDurationMs <= 0 then return false
    return SiloCompatP7Snapshot(SpField(proof,"snapshot"),video,audio)
end function

function SiloCompatP7SourceMetadata(decoded as Dynamic, proof as Dynamic, negotiated = false as Boolean) as Dynamic
    return SiloCompatHDR10SourceMetadata(decoded,proof,negotiated,false)
end function

' Shared exact inventory checks; source video classes remain independently proven.
function SiloCompatHDR10SourceMetadata(decoded as Dynamic, proof as Dynamic, negotiated as Boolean, p8 as Boolean) as Dynamic
    if p8
        if not SiloCompatP8HDR10Proof(proof) then return invalid
    else if SpField(proof,"eligibilityKind") = "experimental_query_p7_hdr10_aac_fmp4_v1"
        if not SiloCompatP7AACProof(proof) then return invalid
    else
        if not SiloCompatP7Proof(proof) then return invalid
    end if
    if not SiloObject(decoded) or not SiloArray(decoded.MediaSources) then return invalid
    selected = invalid
    for each source in decoded.MediaSources
        if SiloObject(source) and source.Id = proof.mediaSourceId
            if selected <> invalid then return invalid
            selected = source
        end if
    end for
    if selected = invalid then return invalid
    if selected.Container <> "mkv" or not SiloArray(selected.MediaStreams) then return invalid
    if selected.MediaStreams.Count() <> 1+proof.audioInventory.Count()+proof.subtitleInventory.Count() then return invalid
    if not SpNumber(SpField(selected,"Bitrate"),2147483646000#) then return invalid
    if selected.Bitrate <> proof.sourceBitrateKbps*1000# then return invalid
    if not SpNumber(SpField(selected,"RunTimeTicks"),6048000000000#) then return invalid
    if selected.RunTimeTicks <> proof.sourceDurationMs*10000# then return invalid
    ' GET Items advertises viewer defaults independently of raw stream flags.
    ' PlaybackInfo projects the explicit selection into its stream flags.
    if not SpNumber(SpField(selected,"DefaultAudioStreamIndex"),proof.audioInventory.Count(),true) then return invalid
    defaultAudioIndex = selected.DefaultAudioStreamIndex
    if defaultAudioIndex < 1 then return invalid
    if negotiated and defaultAudioIndex <> proof.audioOrdinal+1 then return invalid
    defaultSubtitleIndex = invalid
    if selected.DoesExist("DefaultSubtitleStreamIndex")
        if negotiated then return invalid
        if not SpNumber(selected.DefaultSubtitleStreamIndex,4095,true) then return invalid
        for each subtitle in proof.subtitleInventory
            if subtitle.index = selected.DefaultSubtitleStreamIndex then defaultSubtitleIndex = subtitle.index
        end for
        if defaultSubtitleIndex = invalid then return invalid
    end if
    anyDefaultAudio = false
    for each audio in proof.audioInventory
        if audio.isDefault then anyDefaultAudio = true
    end for
    videoCount = 0:audioCount = 0:subtitleCount = 0:selectedIndex = invalid:seen = {}
    for each stream in selected.MediaStreams
        if not SiloObject(stream) or not SpNumber(stream.Index,4095,true) then return invalid
        key = stream.Index.ToStr()
        if seen.DoesExist(key) then return invalid
        seen[key] = true
        if not SpBool(SpField(stream,"IsDefault")) then return invalid
        if stream.Type = "Video"
            videoCount++
            if stream.Index <> 0 then return invalid
            sourceRange = "DOVIWithEL"
            if p8 then sourceRange = "DOVIWithHDR10"
            if stream.Codec <> "hevc" or stream.VideoRangeType <> sourceRange then return invalid
            for each name in ["Width","Height","BitDepth","Level"]
                if not SpNumber(SpField(stream,name),3840,true) then return invalid
            end for
            if stream.Width <> 3840 or stream.Height <> 2160 or stream.BitDepth <> 10 or stream.Level <> proof.video.level then return invalid
            if not SpText(SpField(stream,"Profile"),32) then return invalid
            if LCase(stream.Profile) <> "main 10" then return invalid
            if stream.ColorTransfer <> "smpte2084" or stream.ColorPrimaries <> "bt2020" or stream.ColorSpace <> "bt2020nc" then return invalid
            if not SpBool(SpField(stream,"IsInterlaced")) then return invalid
            if stream.IsInterlaced or not stream.IsDefault then return invalid
            if not SoNear(stream.AverageFrameRate,SoFrameRate(proof.video.frame_rate)) then return invalid
        else if stream.Type = "Audio"
            if audioCount >= proof.audioInventory.Count() then return invalid
            expected = proof.audioInventory[audioCount]
            if stream.Index <> audioCount+1 then return invalid
            if stream.Codec <> expected.codec or SpField(stream,"Language","") <> expected.language then return invalid
            if not SpNumber(SpField(stream,"Channels"),32,true) then return invalid
            if stream.Channels <> expected.channels then return invalid
            defaultAudio = expected.isDefault or (audioCount = 0 and not anyDefaultAudio)
            if negotiated then defaultAudio = stream.Index = defaultAudioIndex
            if stream.IsDefault <> defaultAudio then return invalid
            if audioCount = proof.audioOrdinal then selectedIndex = stream.Index
            audioCount++
        else if stream.Type = "Subtitle"
            if subtitleCount >= proof.subtitleInventory.Count() then return invalid
            expected = proof.subtitleInventory[subtitleCount]
            if stream.Index <> expected.index or stream.Codec <> expected.codec or SpField(stream,"Language","") <> expected.language then return invalid
            for each name in ["IsForced","IsHearingImpaired","IsExternal","IsTextSubtitleStream"]
                if not SpBool(SpField(stream,name)) then return invalid
            end for
            if stream.IsForced <> expected.forced or stream.IsHearingImpaired <> expected.hearingImpaired or stream.IsExternal <> expected.external then return invalid
            defaultSubtitle = expected.isDefault
            if negotiated then defaultSubtitle = false
            if stream.IsDefault <> defaultSubtitle then return invalid
            delivery = "Embed"
            if expected.external then delivery = "External"
            if negotiated and expected.codec = "hdmv_pgs_subtitle" and not expected.external
                if stream.IsTextSubtitleStream then return invalid
                delivery = "Encode"
            end if
            ' stock48ae handlers_playback.go mediaSourceDTO projects text subtitles
            ' to External for remux even with Off. No subtitle URL is consumed.
            if p8 and expected.codec = "subrip"
                if not stream.IsTextSubtitleStream then return invalid
                if negotiated then delivery = "External"
            end if
            if SpField(stream,"DeliveryMethod") <> delivery then return invalid
            subtitleCount++
        else
            return invalid
        end if
    end for
    if videoCount <> 1 or audioCount <> proof.audioInventory.Count() or subtitleCount <> proof.subtitleInventory.Count() or selectedIndex = invalid then return invalid
    return {audioStreamIndex:selectedIndex,subtitleCount:subtitleCount,source:selected}
end function

function SiloCompatP7Receipt(decoded as Dynamic, proof as Dynamic, baseUrl as Dynamic, audioIndex as Dynamic) as Dynamic
    return SiloCompatHDR10Receipt(decoded,proof,baseUrl,audioIndex,false)
end function

' Pure, in-memory handoff for the experimental root-listener stock engine.
' The qualification is a trusted local QA opt-in, never server attestation.
' Canonicalize only the approved stock lane; legacy server resume stays intact.
function SiloCompatStockPreparation(proof as Object, qualified as Boolean, requestedPositionMs as Dynamic) as Object
    result = SpCopy(proof)
    if not qualified or not SiloCompatP7Proof(result) then return result
    result.requestedStartPositionMs = requestedPositionMs
    result.startTicks = 0
    return result
end function

function SiloCompatStockContext(decoded as Dynamic, proof as Dynamic, baseUrl as Dynamic, observedChildUrl as Dynamic, audioIndex as Dynamic, token as Dynamic, owner as Dynamic, qualification as Dynamic) as Dynamic
    if not SiloCompatP7Proof(proof) or not SpNumber(SpField(proof,"startTicks"),0,true) or SpField(proof,"startTicks") <> 0 then return invalid
    if not SpFields(owner,["provider","sourceId","profileId","generation","sessionRevision","holderId","attemptId","planGeneration"],[]) then return invalid
    scope = SpScope(owner)
    if scope = invalid or not SpNumber(owner.sessionRevision,2147483646,true) then return invalid
    binding = SpField(proof,"ownerBinding")
    if not SpFields(binding,["provider","sourceId","profileId","generation","sessionRevision"],[]) then return invalid
    for each name in ["provider","sourceId","profileId","generation","sessionRevision"]
        if SpField(binding,name) <> SpField(owner,name) then return invalid
    end for
    if not SpOpaque(owner.holderId) or not SpOpaque(owner.attemptId) or not SpNumber(owner.planGeneration,2147483646,true) then return invalid
    if not SpFields(qualification,["schemaVersion","kind","approved","sourceId","profileId","generation","sessionRevision","holderId","attemptId","planGeneration","origin","transportPolicy","transportEvidence","rootListenerRequired"],["fileId","mediaSourceId","audioOrdinal","audioStreamIndex","requestedStartPositionMs"]) then return invalid
    if not SpNumber(qualification.schemaVersion,1,true) or qualification.schemaVersion <> 1 or qualification.kind <> "stock-p7-ac3-root-v1" then return invalid
    for each name in ["approved","rootListenerRequired"]
        if not SpBool(SpField(qualification,name)) or SpField(qualification,name) <> true then return invalid
    end for
    for each name in ["sourceId","profileId","generation","sessionRevision","holderId","attemptId","planGeneration"]
        if SpField(qualification,name) <> SpField(owner,name) then return invalid
    end for
    for each name in ["fileId","mediaSourceId","audioOrdinal"]
        if qualification.DoesExist(name) and qualification[name] <> proof[name] then return invalid
    end for
    if qualification.DoesExist("audioStreamIndex") and qualification.audioStreamIndex <> audioIndex then return invalid
    if type(baseUrl) <> "roString" and type(baseUrl) <> "String" then return invalid
    base = SiloUrlParts(baseUrl)
    if base.ok <> true or base.path <> "" or baseUrl <> base.authority then return invalid
    if not CreateObject("roRegex","^https?://[A-Za-z0-9.-]+(:[0-9]{1,5})?$","").IsMatch(baseUrl) then return invalid
    if qualification.origin <> baseUrl then return invalid
    if not SiloStockTransportPolicyValid(qualification.transportPolicy,qualification.transportEvidence,baseUrl) then return invalid
    if not SpText(token,4096) or not CreateObject("roRegex","^[A-Za-z0-9._~-]+$","").IsMatch(token) then return invalid
    receipt = SiloCompatPlaybackReceipt(decoded,proof,baseUrl,audioIndex)
    if receipt = invalid or receipt.class <> "copied_p7_hdr10_fmp4" or receipt.videoCopyRecipe <> true then return invalid
    expected = baseUrl+"/Videos/"+proof.mediaSourceId+"/remux-dv-v1/master.m3u8?PlaySessionId="+receipt.playSessionId+"&MediaSourceId="+proof.mediaSourceId
    if receipt.url <> expected then return invalid
    if type(observedChildUrl) <> "roString" and type(observedChildUrl) <> "String" then return invalid
    childPath = baseUrl+"/Videos/"+proof.mediaSourceId+"/remux-dv-v1/hls/"+receipt.playSessionId+"/stream.m3u8?"
    queryA = "MediaSourceId="+proof.mediaSourceId+"&PlaySessionId="+receipt.playSessionId
    queryB = "PlaySessionId="+receipt.playSessionId+"&MediaSourceId="+proof.mediaSourceId
    if observedChildUrl <> childPath+queryA and observedChildUrl <> childPath+queryB then return invalid
    bookmark = SpField(proof,"requestedStartPositionMs",0)
    if not SpNumber(bookmark,2147483646,true) or bookmark >= proof.sourceDurationMs then return invalid
    if not SpNumber(SpField(qualification,"requestedStartPositionMs",0),2147483646,true) or SpField(qualification,"requestedStartPositionMs",0) <> bookmark then return invalid
    context = {origin:baseUrl,routeItemId:proof.mediaSourceId,mediaSourceId:proof.mediaSourceId,sessionId:receipt.playSessionId,token:token,authMode:"bearer",transportPolicy:qualification.transportPolicy,transportEvidence:qualification.transportEvidence,playlist:observedChildUrl}
    return {context:context,owner:{provider:owner.provider,sourceId:owner.sourceId,profileId:owner.profileId,generation:owner.generation,sessionRevision:owner.sessionRevision,holderId:owner.holderId,attemptId:owner.attemptId,planGeneration:owner.planGeneration},audioStreamIndex:receipt.audioStreamIndex,class:receipt.class,startPositionMs:bookmark}
end function

' Observe a single variant in the fetched master. The context adapter checks
' the resulting URL against the exact owned child route before using it.
function SiloCompatStockMasterChild(body as Dynamic, masterUrl as Dynamic) as Dynamic
    if type(body) <> "String" and type(body) <> "roString" then return invalid
    if Len(body) > 65536 then return invalid
    if (type(masterUrl) <> "String" and type(masterUrl) <> "roString") then return invalid
    marker = "/master.m3u8?"
    at = Instr(1,masterUrl,marker)
    if at <= 0 then return invalid
    parts = SiloUrlParts(masterUrl)
    if parts.ok <> true then return invalid
    lines = body.Split(Chr(10))
    if lines.Count() < 3 or lines.Count() > 256 or lines[0].Trim() <> "#EXTM3U" then return invalid
    pending = false:child = invalid
    for index = 1 to lines.Count()-1
        line = lines[index].Trim()
        if line = "" then continue for
        if Left(line,18) = "#EXT-X-STREAM-INF:"
            if pending or child <> invalid then return invalid
            pending = true
        else if Left(line,1) = "#"
            if pending then return invalid
            if Left(line,15) <> "#EXT-X-VERSION:" then return invalid
        else
            if not pending or child <> invalid or Len(line) > 2048 then return invalid
            if Instr(1,line,":") > 0 or Instr(1,line,"..") > 0 or Instr(1,line,"//") > 0 or Instr(1,line,"#") > 0 then return invalid
            if Left(line,1) = "/"
                child = parts.authority+line
            else
                child = Left(masterUrl,at-1)+"/"+line
            end if
            pending = false
        end if
    end for
    if pending then return invalid
    return child
end function

function SiloCompatHDR10Receipt(decoded as Dynamic, proof as Dynamic, baseUrl as Dynamic, audioIndex as Dynamic, p8 as Boolean) as Dynamic
    if not SiloObject(decoded) or not SiloArray(decoded.MediaSources) then return invalid
    if decoded.MediaSources.Count() <> 1 or not SiloCompatPattern(decoded.PlaySessionId,"^[A-Za-z0-9_-]+$",128) then return invalid
    metadata = SiloCompatHDR10SourceMetadata(decoded,proof,true,p8)
    if metadata = invalid then return invalid
    if not SpNumber(audioIndex,4095,true) or metadata.audioStreamIndex <> audioIndex then return invalid
    source = metadata.source
    if not SpNumber(SpField(source,"DefaultAudioStreamIndex"),4095,true) then return invalid
    if source.DefaultAudioStreamIndex <> audioIndex or source.DoesExist("DefaultSubtitleStreamIndex") then return invalid
    for each name in ["SupportsDirectPlay","SupportsDirectStream","SupportsTranscoding","SiloSeekReanchor"]
        if not SpBool(SpField(source,name)) then return invalid
    end for
    if source.SupportsDirectPlay or source.SupportsDirectStream or not source.SupportsTranscoding or not source.SiloSeekReanchor then return invalid
    if source.TranscodingSubProtocol <> "hls" or source.TranscodingContainer <> "mp4" then return invalid
    if not SiloCompatPattern(source.TranscodingUrl,"^[!-~]+$",2048) then return invalid
    expected = "/Videos/"+proof.mediaSourceId+"/remux-dv-v1/master.m3u8?PlaySessionId="+decoded.PlaySessionId+"&MediaSourceId="+proof.mediaSourceId
    base = SiloUrlParts(baseUrl)
    if base.ok <> true then return invalid
    privateUrl = ""
    if source.TranscodingUrl = expected
        privateUrl = baseUrl+expected
    else if source.TranscodingUrl = base.path+expected
        privateUrl = base.authority+source.TranscodingUrl
    else
        return invalid
    end if
    receiptClass = "copied_p7_hdr10_fmp4"
    if p8 then receiptClass = SiloCompatClassForKind(proof.eligibilityKind)
    if SpField(proof,"eligibilityKind") = "experimental_query_p7_hdr10_aac_fmp4_v1" then receiptClass = "converted_p7_hdr10_aac_fmp4"
    return {playSessionId:decoded.PlaySessionId,url:privateUrl,audioStreamIndex:audioIndex,class:receiptClass,videoCopyRecipe:true,physicalHDRVerified:false}
end function


function SiloCompatP8HDR10Video(video as Dynamic) as Boolean
    if not SiloCompatModernVideo(video) then return false
    if SoVideoGate(video) <> "" then return false
    return video.dv_profile = 8 and video.dv_level = 6 and video.dv_bl_compat_id = 1 and SpBool(SpField(video,"dv_el_present")) and video.dv_el_present = false and video.dv_enhancement_layer = "none" and video.width = 3840 and video.height = 2160
end function

function SiloCompatP8HDR10Snapshot(snapshot as Dynamic, video as Object, audio as Object, codec = "eac3" as String) as Boolean
    if not SpFields(snapshot,["model","modelNumber","modelType","os","videoMode","dolbyVision","hdr10","hevcMain10","audioCodec","audioChannels","audioDecode","audioPassthrough","videoQuery","audioContainer"],[]) then return false
    if not SiloCompatHDR10Identity(snapshot) or not SpBool(snapshot.dolbyVision) then return false
    if not SpBool(snapshot.hevcMain10) then return false
    if not snapshot.hevcMain10 then return false
    query = snapshot.videoQuery
    if not SpFields(query,["codec","container","profile","level","result"],[]) then return false
    level = "5.0"
    if video.level = 153 then level = "5.1"
    if query.codec <> "hevc" or query.container <> "mp4" or query.profile <> "main 10" or query.level <> level then return false
    if not SpBool(query.result) then return false
    if not query.result then return false
    if snapshot.audioContainer <> "mp4" or snapshot.audioCodec <> codec or snapshot.audioCodec <> audio.codec then return false
    if not SpNumber(snapshot.audioChannels,6,true) then return false
    if (snapshot.audioChannels <> 2 and snapshot.audioChannels <> 6) or snapshot.audioChannels <> audio.channels then return false
    for each name in ["audioDecode","audioPassthrough"]
        value = snapshot[name]
        if value <> invalid
            if not SpBool(value) then return false
        end if
    end for
    return snapshot.audioDecode = true or snapshot.audioPassthrough = true
end function

 ' Automatic output choice requires the actual typed negative display answer.
function SiloCompatP8HDR10AutomaticCandidate(detail as Dynamic, owner as Dynamic, params as Dynamic, snapshot as Dynamic) as Dynamic
    dv = SpField(snapshot,"dolbyVision")
    if not SpBool(dv) then return invalid
    if dv then return invalid
    return SiloCompatP8HDR10Candidate(detail,owner,params,snapshot)
end function

function SiloCompatP8HDR10Candidate(detail as Dynamic, owner as Dynamic, params as Dynamic, snapshot as Dynamic, kind = "experimental_query_p8_hdr10_fmp4_v1" as String) as Dynamic
    codec = "eac3"
    if kind = "experimental_query_p8_hdr10_ac3_fmp4_v1"
        codec = "ac3"
        if not SpBool(SpField(params,"autoVersion")) then return invalid
        if params.autoVersion or SpField(params,"autoAudioSelection") <> invalid then return invalid
        if not SpText(SpField(params,"fileId"),64) then return invalid
    end if
    scope = SpScope(owner)
    if scope = invalid or not SpNumber(SpField(owner,"sessionRevision"),2147483646,true) then return invalid
    if SpField(params,"subtitleMode") <> "off" or SpField(params,"qualityPreference") <> "original" then return invalid
    file = SiloPlaybackFile(detail,scope.sourceId,SpField(params,"itemId"),SpField(params,"fileId"),SpField(params,"startPositionMs",0))
    if file = invalid then return invalid
    if not SpNumber(file.bitrateKbps,2147483646,true) then return invalid
    if file.bitrateKbps <= 0 then return invalid
    if codec = "eac3" and detail.versions.Count() <> 1 then return invalid
    cap = SpField(params,"bandwidthCapKbps",0)
    if not SpNumber(cap,2147483646,true) then return invalid
    if cap > 0 and file.bitrateKbps > cap then return invalid
    uuid = SiloCompatMediaSourceId(file.versionId)
    if uuid = invalid then return invalid
    version = file.version
    if version.container <> "mkv" or type(version.videoTracks) <> "roArray" then return invalid
    if version.videoTracks.Count() <> 1 then return invalid
    video = version.videoTracks[0]
    if not SiloCompatP8HDR10Video(video) then return invalid
    if not SiloCompatP7Inventories(SpField(version,"audioTracks"),SpField(version,"subtitleTracks")) then return invalid
    ordinal = SpField(params,"audioTrackIndex")
    if not SpNumber(ordinal,version.audioTracks.Count()-1,true) then return invalid
    if SpField(params,"audioTrackId") <> "file:"+file.versionId+":audio:"+ordinal.ToStr() then return invalid
    audio = version.audioTracks[ordinal]
    if audio.codec <> codec or (audio.channels <> 2 and audio.channels <> 6) or not SpText(audio.language,32) then return invalid
    if not SiloCompatP8HDR10Snapshot(snapshot,video,audio,codec) then return invalid
    return {eligibilityKind:kind,subtitleMode:"off",mediaSourceId:uuid,fileId:file.versionId,video:video,audio:audio,audioOrdinal:ordinal,audioInventory:version.audioTracks,subtitleInventory:version.subtitleTracks,sourceBitrateKbps:file.bitrateKbps,sourceDurationMs:file.durationMs,startTicks:SiloCompatPositionTicks(SpField(params,"startPositionMs",0)/1000#),snapshot:snapshot}
end function

function SiloCompatP8HDR10Proof(proof as Dynamic) as Boolean
    kind = SpField(proof,"eligibilityKind")
    codec = "eac3"
    if kind = "experimental_query_p8_hdr10_ac3_fmp4_v1" then codec = "ac3"
    if kind <> "experimental_query_p8_hdr10_fmp4_v1" and kind <> "experimental_query_p8_hdr10_ac3_fmp4_v1" then return false
    if SpField(proof,"subtitleMode") <> "off" then return false
    video = SpField(proof,"video"):audio = SpField(proof,"audio")
    if not SiloCompatP8HDR10Video(video) then return false
    if not SiloCompatP7Inventories(SpField(proof,"audioInventory"),SpField(proof,"subtitleInventory")) then return false
    ordinal = SpField(proof,"audioOrdinal")
    if not SpNumber(ordinal,proof.audioInventory.Count()-1,true) then return false
    if type(audio) <> "roAssociativeArray" then return false
    if not SpBool(SpField(audio,"isDefault")) then return false
    if not SpNumber(SpField(audio,"sourceOrdinal"),31,true) then return false
    if audio.codec <> codec or not SpNumber(SpField(audio,"channels"),6,true) then return false
    if (audio.channels <> 2 and audio.channels <> 6) or not SpText(SpField(audio,"language"),32) then return false
    expected = proof.audioInventory[ordinal]
    for each name in ["sourceOrdinal","codec","channels","language","isDefault"]
        if SpField(audio,name) <> SpField(expected,name) then return false
    end for
    sourceId = SiloCompatMediaSourceId(SpField(proof,"fileId"))
    if sourceId = invalid then return false
    if sourceId <> SpField(proof,"mediaSourceId") then return false
    if not SpNumber(SpField(proof,"sourceBitrateKbps"),2147483646,true) then return false
    if proof.sourceBitrateKbps <= 0 then return false
    if not SpNumber(SpField(proof,"sourceDurationMs"),604800000,true) then return false
    if proof.sourceDurationMs <= 0 then return false
    return SiloCompatP8HDR10Snapshot(SpField(proof,"snapshot"),video,audio,codec)
end function
