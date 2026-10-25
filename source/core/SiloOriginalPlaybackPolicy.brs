' Fresh, per-file original-byte policy. No transport, native handles or storage.
' Runtime activation remains disabled until owned native acceptance and review.
function SiloOriginalActivationEnabled() as Boolean
    return false
end function

function SiloP8OriginalActivationEnabled() as Boolean
    return false
end function

function SiloOriginalDefaultSubtitle(file as Dynamic, preferences as Dynamic) as Dynamic
    fileId = SoFileId(SpField(file,"file_id"))
    tracks = SpField(file,"subtitle_tracks")
    if fileId = "" or not SiloArray(tracks) then return invalid
    if tracks.Count() = 0 or tracks.Count() > 64 then return invalid
    if preferences <> invalid and not SiloObject(preferences) then return invalid
    externalCount = 0:embeddedCount = 0:defaultPosition = -1:externalSeen = false
    for position = 0 to tracks.Count()-1
        track = tracks[position]
        if not SiloObject(track) then return invalid
        for each field in ["external","default","forced","hearing_impaired"]
            if not SpBool(SpField(track,field)) then return invalid
        end for
        if track.external
            externalCount++:externalSeen = true
        else
            if externalSeen then return invalid
            embeddedCount++
        end if
        if track.default
            if defaultPosition >= 0 then return invalid
            defaultPosition = position
        end if
    end for
    if defaultPosition < 0 then return invalid
    chosen = tracks[defaultPosition]
    rawCodec = SpField(chosen,"codec")
    if not SpText(rawCodec,32) then return invalid
    codec = LCase(rawCodec):language = SoLanguage(SpField(chosen,"language"))
    if not SiloContains(["subrip","srt","webvtt","vtt","ass","ssa","mov_text","text"],codec) or language = "" then return invalid
    preferred = SpField(preferences,"subtitleLanguage","")
    if preferred <> ""
        if SoLanguage(preferred) = "" or SoLanguage(preferred) <> language then return invalid
    end if
    showForced = SpField(preferences,"showForced")
    if showForced <> invalid
        if not SpBool(showForced) then return invalid
        if not showForced and chosen.forced then return invalid
    end if
    sdh = SpField(preferences,"preferSdh")
    if sdh <> invalid
        if not SpBool(sdh) or sdh <> chosen.hearing_impaired then return invalid
    end if
    ' Catalog is embedded-first; V3 adds external tracks before embedded tracks.
    ordinal = externalCount + defaultPosition:source = "embedded"
    if chosen.external then ordinal = defaultPosition - embeddedCount:source = "external"
    return {trackId:"file:"+fileId+":subtitle:"+ordinal.ToStr(),combinedIndex:ordinal,source:source,codec:codec,language:language,forced:chosen.forced,hearingImpaired:chosen.hearing_impaired}
end function

function SiloOriginalClaims(proof as Dynamic) as Object
    profile = SpField(SpField(proof,"videoFacts"),"dv_profile")
    enabled = false
    if profile = 7 then enabled = SiloOriginalActivationEnabled()
    if profile = 8 then enabled = SiloP8OriginalActivationEnabled()
    if SoOrdinaryP8Proof(proof) or SoOrdinaryFilmProof(proof) then enabled = true
    if not enabled then return []
    if type(SpField(proof,"claims")) <> "roArray" then return []
    return SpCopy(proof.claims)
end function

' selectedSourceAudio uses official AUDIO ARRAY ORDINAL, never wire/native index.
' Explicit source selectors and fresh effective_audio_track_index are preserved.
' Returns {ok,proof} or {ok:false,reason}; proof is memory-only request evidence.
function SiloOriginalEligibility(freshFile as Dynamic, selectedSourceAudio as Dynamic, deviceSnapshot as Dynamic, requestIntent as Dynamic) as Object
    file = SpField(freshFile,"wire")
    denied = SoSourceGate(freshFile,deviceSnapshot,requestIntent)
    if denied <> "" then return SoDenied(denied)
    fileId = SoFileId(SpField(file,"file_id"))
    if fileId = "" or fileId <> SpField(requestIntent,"fileId") then return SoDenied("file_identity")
    for each key in ["sourceId","itemId"]
        if not SpText(SpField(freshFile,key),512) or SpField(freshFile,key) <> SpField(requestIntent,key) then return SoDenied("source_identity")
    end for
    scope = SpScope(SpField(freshFile,"scope"))
    if scope = invalid or not SoScopeEqual(scope,SpField(requestIntent,"scope")) then return SoDenied("scope_identity")
    if scope.sourceId <> freshFile.sourceId then return SoDenied("scope_identity")
    quality = SpField(requestIntent,"qualityPreference")
    if quality <> "auto" and quality <> "original" then return SoDenied("quality_intent")
    cap = SpField(requestIntent,"bandwidthCapKbps",0):bitrate = SoSourceBitrate(file)
    if not SpNumber(bitrate,2147483646,true) or bitrate = 0 or not SpNumber(cap,2147483646,true) then return SoDenied("bitrate_unknown")
    if cap > 0 and cap < bitrate then return SoDenied("bandwidth_intent")
    caption = SpField(requestIntent,"subtitleMode") = "sidecar" and SpField(requestIntent,"ordinaryRequestScoped") = true and SpField(requestIntent,"experimentalOriginal") <> true
    if SpField(requestIntent,"subtitleMode") <> "off" and not caption then return SoDenied("subtitle_intent")
    if not SpOpaque(SpField(requestIntent,"playbackAttemptId")) then return SoDenied("attempt_identity")
    tracks = SpField(file,"audio_tracks")
    if type(tracks) <> "roArray" then return SoDenied("audio_inventory")
    if tracks.Count() = 0 or tracks.Count() > 32 then return SoDenied("audio_inventory")
    defaultIndex = 0:foundDefault = false:sourceAudio = []:seenAudio = {}
    for index = 0 to tracks.Count()-1
        track = tracks[index]
        if type(track) <> "roAssociativeArray" then return SoDenied("audio_inventory")
        if track.DoesExist("index") then return SoDenied("audio_index_convention")
        if not SpText(track.codec,32) or not SpText(track.language,32) or not SpNumber(track.channels,8,true) then return SoDenied("audio_inventory")
        if track.channels = 0 or not SpText(track.layout,32) or not SpBool(track.default) then return SoDenied("audio_inventory")
        language = SoLanguage(track.language)
        if language = "" then return SoDenied("audio_language")
        key = LCase(track.codec)+":"+language+":"+Int(track.channels).ToStr()
        if seenAudio.DoesExist(key) then return SoDenied("audio_ambiguous")
        seenAudio[key] = true
        sourceAudio.Push({index:index,codec:LCase(track.codec),language:language,channels:track.channels,layout:track.layout})
        if track.default and not foundDefault then defaultIndex = index:foundDefault = true
    end for
    chosen = defaultIndex:explicit = false
    effective = SpField(file,"effective_audio_track_index")
    if effective <> invalid
        if not SpNumber(effective,tracks.Count()-1,true) then return SoDenied("audio_identity")
        chosen = effective
    end if
    if selectedSourceAudio <> invalid
        chosen = SpField(selectedSourceAudio,"index")
        if not SpNumber(chosen,tracks.Count()-1,true) then return SoDenied("audio_identity")
        explicit = SpField(selectedSourceAudio,"explicit") = true
    end if
    if not SoAudioPlayable(tracks[chosen],deviceSnapshot,SpField(requestIntent,"experimentalOriginal") = true)
        if SpField(requestIntent,"experimentalOriginal") = true then return SoDenied("explicit_audio_required")
        if explicit then return SoDenied("explicit_audio_unsupported")
        ' The observed unsupported TrueHD lane is the only admitted automatic
        ' substitution. A usable AAC/EAC3 server preference stays on its normal
        ' route; lack of original mapping qualification is not decode failure.
        if LCase(tracks[chosen].codec) <> "truehd" then return SoDenied("preferred_audio_unqualified")
        currentRole = SoAudioRole(tracks[chosen])
        if currentRole = "unknown" then return SoDenied("audio_role_unknown")
        compatible = -1
        for index = 0 to tracks.Count()-1
            candidate = tracks[index]
            if LCase(candidate.codec) = "ac3" and SoLanguage(candidate.language) = SoLanguage(tracks[chosen].language) and SoAudioPlayable(candidate,deviceSnapshot) and SoAudioRole(candidate) = currentRole
                if compatible >= 0 then return SoDenied("audio_ambiguous")
                compatible = index
            end if
        end for
        if compatible < 0 then return SoDenied("audio_unsupported")
        chosen = compatible
    end if
    track = tracks[chosen]
    fileId = SoFileId(SpField(file,"file_id"))
    if fileId = "" then return SoDenied("file_identity")
    identity = {index:chosen,id:"file:"+fileId+":audio:"+Int(chosen).ToStr(),codec:LCase(track.codec),language:SoLanguage(track.language),channels:track.channels,layout:track.layout}
    if selectedSourceAudio <> invalid
        id = SpField(selectedSourceAudio,"id","")
        if id <> "" and id <> identity.id then return SoDenied("audio_identity")
    end if
    claims = ["client_managed_dynamic_range_v1"]
    if chosen <> defaultIndex then claims.Push("client_selected_audio_track_v1")
    proof = {fileId:fileId,sourceId:SpField(freshFile,"sourceId"),itemId:SpField(freshFile,"itemId"),scope:SpCopy(SpField(freshFile,"scope")),videoFacts:SoVideoFacts(file.video_tracks[0]),audioIdentity:identity,sourceAudio:sourceAudio,outputFingerprint:SpField(deviceSnapshot,"outputFingerprint"),mappingMode:"structured_format",sourceBitrateKbps:SoSourceBitrate(file),qualityPreference:SpField(requestIntent,"qualityPreference"),playbackAttemptId:SpField(requestIntent,"playbackAttemptId"),claims:claims}
    if caption
        proof["subtitleSidecarRequired"] = true
        for each name in ["subtitleTrackId","subtitleTrackIndex"]
            if requestIntent.DoesExist(name) then proof[name] = requestIntent[name]
        end for
    end if
    ' Ordinary authority is minted only from fresh matching Task evidence.
    ' Keep the independently qualified explicit DTS-to-AC3 family as well.
    if SpField(requestIntent,"experimentalOriginal") <> true and SpField(requestIntent,"ordinaryRequestScoped") = true and SoP8Snapshot(deviceSnapshot)
        proof["qualifiedRoute"] = "hdr10_base_original_v1"
        if not SoOrdinaryFilmProof(proof) then proof.Delete("qualifiedRoute")
        if SpField(proof,"qualifiedRoute") = invalid and SpField(selectedSourceAudio,"explicit") = true
            proof["qualifiedRoute"] = "p8_explicit_ac3_stereo_v1"
            if not SoOrdinaryP8Proof(proof) then proof.Delete("qualifiedRoute")
        end if
    end if
    return {ok:true,proof:proof}
end function

 ' A typed local claim, minted only after fresh structural eligibility. Never
' deserialize this marker from a server response or synthesize an audio choice.
function SoOrdinaryP8Proof(proof as Dynamic) as Boolean
    if SpField(proof,"qualifiedRoute") <> "p8_explicit_ac3_stereo_v1" then return false
    video = SpField(proof,"videoFacts")
    if SpField(video,"dv_profile") <> 8 or SpField(video,"dv_level") <> 6 or SpField(video,"dv_bl_compat_id") <> 1 then return false
    if SoVideoGate(video) <> "" then return false
    if SpField(video,"width") <> 3840 or not SoNear(SoFrameRate(SpField(video,"frame_rate")),24000.0/1001.0) then return false
    audio = SpField(proof,"audioIdentity")
    if SpField(audio,"codec") <> "ac3" or SpField(audio,"language") <> "en" or SpField(audio,"channels") <> 2 or SpField(audio,"layout") <> "stereo" then return false
    tracks = SpField(proof,"sourceAudio")
    if not SiloArray(tracks) then return false
    if tracks.Count() <> 2 then return false
    selected = 0:other = 0
    for each track in tracks
        if SpField(track,"language") <> "en" then return false
        if SpField(track,"index") = SpField(audio,"index")
            if SpField(track,"codec") <> "ac3" or SpField(track,"channels") <> 2 or SpField(track,"layout") <> "stereo" then return false
            selected++
        else
            if SpField(track,"codec") <> "dts" or SpField(track,"channels") <> 6 then return false
            layout = SpField(track,"layout")
            if layout <> "5.1" and layout <> "5.1(side)" then return false
            other++
        end if
    end for
    return selected = 1 and other = 1
end function

function SoDenied(reason as String) as Object
    return {ok:false,reason:reason}
end function

function SoFileId(value as Dynamic) as String
    if SpText(value,10)
        if CreateObject("roRegex","^[1-9][0-9]{0,9}$","").IsMatch(value)
            if Val(value) <= 2147483646 then return value
        end if
    end if
    return ""
end function

function SoAudioPlayable(track as Object, device as Dynamic, experimental = false as Boolean) as Boolean
    codec = LCase(SpField(track,"codec",""))
    if codec <> "ac3"
        if codec <> "eac3" then return false
        if experimental
            if not SoExperimentalSnapshot(device) then return false
        else
            if not SoP8Snapshot(device) then return false
        end if
    end if
    channels = SpField(track,"channels"):layout = SpField(track,"layout")
    if channels <> 2 and channels <> 6 then return false
    if channels = 2 and layout <> "stereo" then return false
    if channels = 6 and layout <> "5.1" and layout <> "5.1(side)" then return false
    queries = SpField(device,"audioQueries")
    if type(queries) <> "roArray" then return false
    if queries.Count() > 32 then return false
    for each query in queries
        if SpField(query,"codec") = codec and SpField(query,"container") = "mkv" and SpField(query,"chcnt") = channels and SpField(query,"result") = true then return true
    end for
    return false
end function

' Snapshot query results must be captured afresh for these exact query inputs.
' Raster constraints are independent: Roku rejects width/height decoder keys.
function SoSourceGate(fresh as Dynamic, device as Dynamic, intent as Dynamic) as String
    if SpField(fresh,"fresh") <> true or SpField(device,"fresh") <> true then return "stale_evidence"
    experimental = SpField(intent,"experimentalOriginal") = true
    if experimental and not SoExperimentalSnapshot(device) then return "device_unqualified"
    historical = false
    if not experimental
        if SpField(device,"model") <> "C000X" or SpField(device,"modelType") <> "TV" or SpField(device,"modelNumber") <> "C208X" then return "device_unqualified"
        os = SpField(device,"os")
        historical = SpField(os,"major") = "15" and SpField(os,"minor") = "3" and SpField(os,"revision") = "4" and SpField(os,"build") = "2402"
        if not historical and not SoP8Snapshot(device) then return "device_unqualified"
        if SpField(device,"videoMode") <> "2160p60" or SpField(device,"hdr10") <> true or not SpOpaque(SpField(device,"outputFingerprint")) then return "output_unqualified"
    end if
    file = SpField(fresh,"wire")
    if SpField(file,"container") <> "mkv" or SpField(file,"codec_video") <> "hevc" or SpField(file,"hdr") <> true then return "source_unqualified"
    videos = SpField(file,"video_tracks")
    if type(videos) <> "roArray" then return "video_inventory"
    if videos.Count() <> 1 then return "video_inventory"
    video = videos[0]
    if SpField(video,"dv_profile") = 7
        if not experimental and not historical
            if not SoExperimentalSnapshot(device) then return "device_unqualified"
            if SpField(intent,"experimentalOriginal") <> true and SpField(intent,"ordinaryRequestScoped") <> true then return "device_unqualified"
        end if
    else if SpField(video,"dv_profile") = 8
        if not experimental and not SoP8Snapshot(device) then return "device_unqualified"
    else
        return "base_unproven"
    end if
    videoDenied = SoVideoGate(video)
    if videoDenied <> "" then return videoDenied
    query = SpField(device,"videoQuery")
    if SpField(query,"codec") <> "hevc" or SpField(query,"container") <> "mkv" or SpField(query,"profile") <> "main 10" or SpField(query,"level") <> "5.1" or SpField(query,"result") <> true then return "decoder_unproven"
    return ""
end function



' This gate authorizes only a request-scoped experiment, never shipping support.
function SoExperimentalSnapshot(device as Dynamic) as Boolean
    if SpField(device,"fresh") <> true then return false
    for each key in ["model","modelType","modelNumber"]
        value = SpField(device,key)
        if not SpText(value,128) then return false
        if value.Trim() = "" then return false
    end for
    os = SpField(device,"os")
    for each key in ["major","minor","revision","build"]
        value = SpField(os,key)
        if not SpText(value,16) then return false
        if not CreateObject("roRegex","^[0-9]+$","").IsMatch(value) then return false
    end for
    mode = SpField(device,"videoMode")
    if not SpText(mode,32) then return false
    ' GetVideoMode values: https://developer.roku.com/dev/docs/ifdeviceinfo
    if not CreateObject("roRegex","^2160p((24|25|30|50|60)(b10)?|(30|60)Dv)$","").IsMatch(mode) then return false
    if SpField(device,"hdr10") <> true or not SpOpaque(SpField(device,"outputFingerprint")) then return false
    query = SpField(device,"videoQuery")
    return SpField(query,"codec") = "hevc" and SpField(query,"container") = "mkv" and SpField(query,"profile") = "main 10" and SpField(query,"level") = "5.1" and SpField(query,"result") = true
end function

' Unknown capability evidence is not proof of an unpatched server. Original
' must itself be advertised; a supported copy recipe supersedes this experiment.
function SiloExperimentalServer(data as Dynamic) as Boolean
    if SpField(data,"allowed") <> true or SpField(data,"state") <> "available" then return false
    if not SpOpaque(SpField(data,"installationId")) then return false
    versions = SpField(data,"protocolVersions")
    deliveries = SpField(data,"deliveries"):features = SpField(data,"features")
    if type(versions) <> "roArray" or type(deliveries) <> "roArray" or type(features) <> "roArray" then return false
    if versions.Count() > 16 or deliveries.Count() > 32 or features.Count() > 64 then return false
    v3 = false
    for each version in versions
        if SpNumber(version,100) and version = 3 then v3 = true
    end for
    if not v3 then return false
    for each entries in [deliveries,features]
        for each entry in entries
            if not SpText(entry,128) then return false
        end for
    end for
    if not SiloContains(deliveries,"original_http") then return false
    return true
end function

' OS16 P8 qualification is independent of the historical OS15 P7 lane.
function SoP8Snapshot(device as Dynamic) as Boolean
    if SpField(device,"fresh") <> true then return false
    if SpField(device,"model") <> "C000X" or SpField(device,"modelType") <> "TV" or SpField(device,"modelNumber") <> "C208X" then return false
    os = SpField(device,"os")
    if SpField(os,"major") <> "16" or SpField(os,"minor") <> "0" or SpField(os,"revision") <> "4" or (SpField(os,"build") <> "834" and SpField(os,"build") <> "842") then return false
    if SpField(device,"videoMode") <> "2160p60" or SpField(device,"hdr10") <> true or not SpOpaque(SpField(device,"outputFingerprint")) then return false
    query = SpField(device,"videoQuery")
    return SpField(query,"codec") = "hevc" and SpField(query,"container") = "mkv" and SpField(query,"profile") = "main 10" and SpField(query,"level") = "5.1" and SpField(query,"result") = true
end function

function SoVideoGate(video as Dynamic) as String
    if SpField(video,"codec") <> "hevc" or not SpText(SpField(video,"profile"),32) then return "video_unqualified"
    if LCase(video.profile) <> "main 10" then return "video_unqualified"
    profile = SpField(video,"dv_profile")
    if profile <> 7 and profile <> 8 then return "base_unproven"
    level = SpField(video,"level")
    if level <> 153
        if profile <> 8 or level <> 150 then return "video_unqualified"
    end if
    if SpField(video,"bit_depth") <> 10 or SpField(video,"interlaced") <> false then return "video_unqualified"
    if SpField(video,"color_transfer") <> "smpte2084" or SpField(video,"color_primaries") <> "bt2020" or SpField(video,"color_space") <> "bt2020nc" then return "base_unproven"
    if SpField(video,"dv_level") <> 6 then return "base_unproven"
    for each key in ["dv_config_present","dv_bl_compat_id_present","dv_bl_present","dv_rpu_present"]
        if SpField(video,key) <> true then return "base_unproven"
    end for
    layer = SpField(video,"dv_enhancement_layer")
    if profile = 7
        if SpField(video,"dv_bl_compat_id") <> 6 or SpField(video,"dv_el_present") <> true then return "base_unproven"
        ' Historical observed subclass; no MEL/FEL or presentation claim.
        if layer <> invalid and layer <> "" and layer <> "unknown" then return "enhancement_layer_unqualified"
    else
        if SpField(video,"dv_bl_compat_id") <> 1 then return "base_unproven"
        if layer <> "none" then return "enhancement_layer_unqualified"
        ' Official Go omitempty omits false; explicit values must be Boolean.
        if video.DoesExist("dv_el_present")
            if not SpBool(video.dv_el_present) then return "base_unproven"
            if video.dv_el_present <> false then return "base_unproven"
        end if
    end if
    if SpField(video,"hdr10_plus",false) <> false then return "base_unproven"
    width = SpField(video,"width"):height = SpField(video,"height")
    if not SpNumber(width,3840,true) or not SpNumber(height,2160,true) then return "video_dimensions"
    if width = 0 or height = 0 then return "video_dimensions"
    rate = SoFrameRate(SpField(video,"frame_rate"))
    if rate = invalid then return "video_frame_rate"
    return ""
end function

function SoFrameRate(value as Dynamic) as Dynamic
    if not SpText(value,32) then return invalid
    if not CreateObject("roRegex","^[0-9]+([.][0-9]+)?(/[0-9]+([.][0-9]+)?)?$","").IsMatch(value) then return invalid
    parts = value.Tokenize("/"):denominator = 1
    if parts.Count() = 2 then denominator = Val(parts[1])
    numerator = Val(parts[0])
    if not SpNumber(numerator,1000000000) or not SpNumber(denominator,1000000000) then return invalid
    if denominator <= 0 or numerator <= 0 or numerator / denominator > 60 then return invalid
    return numerator / denominator
end function

function SoScopeEqual(leftScope as Dynamic, rightScope as Dynamic) as Boolean
    leftValue = SpScope(leftScope):rightValue = SpScope(rightScope)
    if leftValue = invalid or rightValue = invalid then return false
    for each key in ["provider","sourceId","profileId","generation"]
        if leftValue[key] <> rightValue[key] then return false
    end for
    return true
end function

' Exact aliases only. Unknown metadata cannot disambiguate an inventory.
function SoLanguage(value as Dynamic) as String
    if not SpText(value,32) then return ""
    aliases = {"en":"en","eng":"en","fr":"fr","fra":"fr","fre":"fr","de":"de","deu":"de","ger":"de","es":"es","spa":"es","ja":"ja","jpn":"ja","it":"it","ita":"it","pt":"pt","por":"pt"}
    key = LCase(value)
    if aliases.DoesExist(key) then return aliases[key]
    return ""
end function

' Generic V3 transport validation MUST run before this narrower validator.
' The wire plan has no sourceId/profile/output/attempt field; immutable owner
' binds those request facts. Refusal does not transfer allocated lease ownership.
' Returns {ok:true,descriptor:<bounded no-URL execution>} or denied(reason).
function SiloOriginalReceipt(proof as Dynamic, returnedV3Plan as Dynamic, owner as Dynamic) as Object
    plan = returnedV3Plan
    for each key in ["sourceId","itemId","fileId","playbackAttemptId","outputFingerprint"]
        if not SpText(SpField(proof,key),512) or SpField(proof,key) <> SpField(owner,key) then return SoDenied("receipt_owner")
    end for
    if not SoScopeEqual(SpField(proof,"scope"),SpField(owner,"scope")) then return SoDenied("receipt_owner")
    if SpField(proof,"mappingMode") <> "structured_format" then return SoDenied("receipt_proof")
    if SpField(proof,"qualityPreference") <> "auto" and SpField(proof,"qualityPreference") <> "original" then return SoDenied("receipt_quality")
    session = SpField(owner,"sessionId"):planId = SpField(plan,"plan_id")
    if not SpOpaque(session) or session <> SpField(plan,"session_id") or not SpOpaque(planId) or not SpOpaque(SpField(plan,"plan_attempt_key")) then return SoDenied("receipt_session")
    if SpField(owner,"planId",planId) <> planId then return SoDenied("receipt_session")
    if SpField(plan,"protocol_version") <> 3 or SpField(plan,"delivery") <> "original_http" or SpField(plan,"decision_reason") <> "client_managed_dynamic_range" then return SoDenied("receipt_delivery")
    stream = SpField(plan,"stream")
    if SpField(stream,"protocol") <> "http_progressive" or SpField(stream,"container") <> "mkv" then return SoDenied("receipt_delivery")
    for each key in ["requested_media_file_id","effective_media_file_id"]
        if SoFileId(SpField(plan,key)) <> proof.fileId then return SoDenied("receipt_file")
    end for
    transformations = SpField(plan,"transformations")
    if type(transformations) <> "roArray" then return SoDenied("receipt_transformations")
    if transformations.Count() <> 0 then return SoDenied("receipt_transformations")
    corrections = SpField(plan,"runtime_corrections")
    if type(corrections) <> "roArray" then return SoDenied("receipt_transformations")
    if corrections.Count() <> 0 then return SoDenied("receipt_transformations")
    audio = SpField(proof,"audioIdentity"):selected = SpField(SpField(plan,"selected_tracks"),"audio")
    if not SpNumber(SpField(audio,"index"),31,true) or not SpOpaque(SpField(audio,"id")) then return SoDenied("receipt_audio")
    if SpField(selected,"index") <> audio.index or SpField(selected,"id") <> audio.id then return SoDenied("receipt_audio")
    source = SpField(plan,"source"):video = SpField(proof,"videoFacts")
    if SoFileId(SpField(source,"media_file_id")) <> proof.fileId then return SoDenied("receipt_file")
    if SoVideoGate(video) <> "" then return SoDenied("receipt_proof")
    enhancement = "unknown"
    if SpField(video,"dv_profile") = 8 then enhancement = "none"
    expected = {container:"mkv",video_codec:"hevc",video_profile:"main 10",video_level:SpField(video,"level"),bit_depth:10,color_range:SpField(video,"color_range"),width:SpField(video,"width"),height:SpField(video,"height"),dynamic_range:"dolby_vision",hdr10_plus:false,dolby_vision_profile:SpField(video,"dv_profile"),dolby_vision_level:SpField(video,"dv_level"),dv_bl_compat_id:SpField(video,"dv_bl_compat_id"),dv_base_layer_proven:true,dv_enhancement_layer:enhancement,audio_codec:SpField(audio,"codec"),audio_channels:SpField(audio,"channels"),audio_layout:SpField(audio,"layout"),bitrate_kbps:SpField(proof,"sourceBitrateKbps")}
    for each key in expected
        if SpField(source,key) <> expected[key] then return SoDenied("receipt_source")
    end for
    frameRate = SoFrameRate(SpField(video,"frame_rate"))
    if not SoNear(SpField(source,"frame_rate"),frameRate) then return SoDenied("receipt_source")
    recipe = SpField(plan,"effective_recipe")
    for each key in ["video_codec","audio_codec","width","height","dynamic_range","audio_channels","audio_layout","bitrate_kbps"]
        if SpField(recipe,key) <> expected[key] then return SoDenied("receipt_recipe")
    end for
    if not SoNear(SpField(recipe,"frame_rate"),frameRate) then return SoDenied("receipt_recipe")
    if SpField(proof,"subtitleSidecarRequired") = true
        receipt = SiloSelectedSubtitleReceipt(plan,SpField(owner,"baseUrl"),session)
        if receipt.ok <> true then return SoDenied("receipt_subtitle_invalid")
        if SpField(receipt.public,"kind") <> "sidecar_pending" then return SoDenied("receipt_subtitle_delivery")
        if not SiloContains(["subrip","srt","webvtt","vtt","ass","ssa","mov_text","text"],SpField(receipt.public,"codec")) then return SoDenied("receipt_subtitle_codec")
        if SpField(receipt.privateArtifact,"timingOriginSeconds") <> 0 then return SoDenied("receipt_subtitle_clock")
        if proof.DoesExist("subtitleTrackId")
            if SpField(receipt.public,"trackId") <> proof.subtitleTrackId then return SoDenied("receipt_subtitle_selection")
        end if
        if proof.DoesExist("subtitleTrackIndex")
            if SpField(receipt.public,"combinedIndex") <> proof.subtitleTrackIndex then return SoDenied("receipt_subtitle_selection")
        end if
        expectedSubtitle = SpField(proof,"defaultSubtitle")
        if expectedSubtitle <> invalid
            for each field in ["source","codec","forced","hearingImpaired"]
                if SpField(receipt.public,field) <> SpField(expectedSubtitle,field) then return SoDenied("receipt_subtitle_selection")
            end for
            if SoLanguage(SpField(receipt.public,"language")) <> expectedSubtitle.language then return SoDenied("receipt_subtitle_selection")
        end if
    else
        if SpField(SpField(plan,"subtitle"),"mode") <> "off" then return SoDenied("receipt_subtitle")
    end if
    descriptor = {schemaVersion:1,sessionId:SpField(owner,"sessionId"),planId:SpField(returnedV3Plan,"plan_id"),guarded:true}
    for each key in ["sourceId","itemId","fileId","playbackAttemptId","outputFingerprint","scope","audioIdentity","sourceAudio","mappingMode"]
        descriptor[key] = SpCopy(SpField(proof,key))
    end for
    descriptor["dolbyVisionProfile"] = SpField(video,"dv_profile")
    if SoOrdinaryFilmProof(proof)
        descriptor["qualifiedRoute"] = proof.qualifiedRoute
        descriptor["videoFacts"] = SpCopy(video)
        descriptor["frameRate"] = frameRate
    end if
    if SoOrdinaryP8Proof(proof)
        descriptor["qualifiedRoute"] = proof.qualifiedRoute
        descriptor["qualifiedVideo"] = {width:video.width,height:video.height,frameRate:frameRate,dolbyVisionLevel:video.dv_level,baseCompatibility:video.dv_bl_compat_id}
    end if
    return {ok:true,descriptor:descriptor}
end function

function SoNear(leftValue as Dynamic, rightValue as Dynamic) as Boolean
    if not SpNumber(leftValue,1000000000) or not SpNumber(rightValue,1000000000) then return false
    return Abs(leftValue-rightValue) < 0.0001
end function

' Official 48ae normalizes very large bitrates as bits/s; video-track bitrate
' supersedes file bitrate when supplied. Do not use display resolution labels.
function SoSourceBitrate(file as Dynamic) as Dynamic
    bitrate = SpField(file,"bitrate")
    tracks = SpField(file,"video_tracks")
    if type(tracks) = "roArray"
        if tracks.Count() = 1
            trackBitrate = SpField(tracks[0],"bitrate")
            if SpNumber(trackBitrate,2147483646,true)
                if trackBitrate > 0 then bitrate = trackBitrate
            end if
        end if
    end if
    if not SpNumber(bitrate,2147483646,true) then return invalid
    if bitrate > 10000000 then return Int(bitrate/1000)
    return bitrate
end function

function SoVideoFacts(video as Object) as Object
    output = {}
    for each key in ["codec","profile","level","width","height","bit_depth","frame_rate","interlaced","color_transfer","color_primaries","color_space","color_range","dv_profile","dv_level","dv_bl_compat_id","dv_config_present","dv_bl_compat_id_present","dv_bl_present","dv_rpu_present","dv_el_present","dv_enhancement_layer","hdr10_plus"]
        value = SpField(video,key)
        if value <> invalid then output[key] = value
    end for
    return output
end function

' No raw title is retained. Empty labels preserve the unlabelled program;
' recognized role labels must agree across title and embedded_title. Arbitrary
' different labels cannot authorize an automatic source-audio substitution.
function SoAudioRole(track as Object) as String
    role = "unlabelled"
    for each field in ["title","embedded_title"]
        label = SpField(track,field,"")
        if not SpText(label,128,true) then return "unknown"
        label = LCase(label.Trim())
        ' Official scanner Title falls back to ffprobe codec long name, then
        ' uppercase codec, only when tags.title / EmbeddedTitle is empty.
        if field = "title" and SpField(track,"embedded_title","") = ""
            codec = LCase(SpField(track,"codec",""))
            if codec = "truehd" and (label = "truehd" or label = "dolby truehd") then label = ""
            if codec = "ac3" and (label = "ac3" or label = "atsc a/52a (ac-3)") then label = ""
        end if
        current = "unlabelled"
        if label <> ""
            if CreateObject("roRegex","(^|[^a-z])(commentary|commentaries)([^a-z]|$)","").IsMatch(label)
                current = "commentary"
            else if CreateObject("roRegex","(^|[^a-z])(description|descriptive|described)([^a-z]|$)","").IsMatch(label)
                current = "description"
            else if label = "main" or label = "original" or label = "default" or label = "main audio" or label = "original audio"
                current = "main"
            else if SoTechnicalAudioLabel(label,track)
                current = "unlabelled"
            else
                return "unknown"
            end if
        end if
        if role <> "unlabelled" and current <> "unlabelled" and role <> current then return "unknown"
        if current <> "unlabelled" then role = current
    end for
    return role
end function

' A technical title carries no program role. Only whole codec/layout labels
' are accepted; every supplied channel descriptor must agree with wire facts.
function SoTechnicalAudioLabel(label as String, track as Object) as Boolean
    codec = LCase(SpField(track,"codec",""))
    pattern = ""
    if codec = "truehd" then pattern = "(dolby )?truehd"
    if codec = "ac3" then pattern = "(dolby digital|ac-?3|atsc a/52a \(ac-3\))"
    if pattern = "" then return false
    ' Codec-specific surround extensions are technical only at their known layout.
    if codec = "truehd" and CreateObject("roRegex","^(dolby )?truehd atmos 7\.1$","").IsMatch(label)
        label = CreateObject("roRegex"," atmos","").Replace(label,"")
    end if
    if codec = "ac3" and CreateObject("roRegex","^(dolby digital|ac-?3) 5\.1-ex$","").IsMatch(label)
        label = CreateObject("roRegex","-ex$","").Replace(label,"")
    end if
    matcher = CreateObject("roRegex","^"+pattern+"( (1\.0|2\.0|5\.1|7\.1|[1268] channels?))?$","")
    if not matcher.IsMatch(label) then return false
    descriptor = CreateObject("roRegex","^"+pattern+" ?","").Replace(label,"")
    if descriptor = "" then return true
    expected = 0:layout = ""
    if descriptor = "1.0" or descriptor = "1 channel" or descriptor = "1 channels" then expected = 1:layout = "mono"
    if descriptor = "2.0" or descriptor = "2 channel" or descriptor = "2 channels" then expected = 2:layout = "stereo"
    if descriptor = "5.1" or descriptor = "6 channel" or descriptor = "6 channels" then expected = 6:layout = "5.1"
    if descriptor = "7.1" or descriptor = "8 channel" or descriptor = "8 channels" then expected = 8:layout = "7.1"
    channels = SpField(track,"channels")
    if channels <> invalid and channels <> expected then return false
    actualLayout = LCase(SpField(track,"layout",""))
    if actualLayout <> "" and actualLayout <> layout
        if layout = "mono" and actualLayout = "1.0" then return true
        if layout = "stereo" and actualLayout = "2.0" then return true
        if layout = "5.1" and actualLayout = "5.1(side)" then return true
        return false
    end if
    return true
end function

' HDR10 base-layer handling, never a Dolby Vision output capability. The fresh
' file, decoder/audio queries and immutable receipt remain mandatory fences.
function SoOrdinaryFilmProof(proof as Dynamic) as Boolean
    if SpField(proof,"qualifiedRoute") <> "hdr10_base_original_v1" then return false
    video = SpField(proof,"videoFacts")
    if SoVideoGate(video) <> "" then return false
    if SpField(video,"width") <= 1920 then return false
    audio = SpField(proof,"audioIdentity")
    if SoLanguage(SpField(audio,"language")) = "" then return false
    channels = SpField(audio,"channels"):layout = SpField(audio,"layout")
    if channels <> 2 and channels <> 6 then return false
    if channels = 2 and layout <> "stereo" then return false
    if channels = 6 and layout <> "5.1" and layout <> "5.1(side)" then return false
    if SpField(video,"dv_profile") = 8
        return SpField(audio,"codec") = "eac3" and (SoNear(SoFrameRate(SpField(video,"frame_rate")),24.0) or SoNear(SoFrameRate(SpField(video,"frame_rate")),24000.0/1001.0))
    end if
    if SpField(video,"dv_profile") = 7
        return SpField(audio,"codec") = "ac3" and SoNear(SoFrameRate(SpField(video,"frame_rate")),24000.0/1001.0)
    end if
    return false
end function
