' Owned original selection: native handles are commands, never source identities.
function HopText(value as Dynamic) as String
    if type(value) <> "String" and type(value) <> "roString" then return ""
    return LCase(value.Trim())
end function

function HopCodec(value as Dynamic) as String
    value = HopText(value)
    if value = "ac3" or value = "ac-3" or value = "dolby digital" then return "ac3"
    if value = "eac3" or value = "e-ac-3" then return "eac3"
    if value = "aac" then return "aac"
    if value = "truehd" then return "truehd"
    ' Known unselected source lanes do not authorize DTS playback.
    if value = "dts" or value = "dca" then return "dts"
    return ""
end function

' Native Format descriptions are independent of source codec identifiers.
function HopNativeCodec(value as Dynamic) as String
    value = HopText(value)
    if value = "dolby digital plus" then return "eac3"
    if value = "dts coherent acoustics" then return "dts"
    if value = "dolby metadata-enhanced audio transmission" then return "mat"
    if value = "iso/iec 14496-3, advanced audio coding, asc header" then return "aac"
    return HopCodec(value)
end function

function HopLanguage(value as Dynamic) as String
    value = HopText(value)
    aliases = {eng:"en",spa:"es",fra:"fr",fre:"fr",deu:"de",ger:"de",ita:"it",por:"pt",jpn:"ja",kor:"ko",zho:"zh",chi:"zh"}
    if aliases[value] <> invalid then return aliases[value]
    for each code in ["en","es","fr","de","it","pt","ja","ko","zh"]
        if value = code then return code
    end for
    return ""
end function

function SiloUIOriginalCreate(descriptor as Dynamic, token as Integer, generation as Integer, nowMs as Double, experimental = false as Boolean) as Dynamic
    if type(descriptor) <> "roAssociativeArray" then return invalid
    if descriptor.guarded <> true or descriptor.schemaVersion <> 1 or descriptor.mappingMode <> "structured_format" then return invalid
    if type(descriptor.audioIdentity) <> "roAssociativeArray" or type(descriptor.sourceAudio) <> "roArray" then return invalid
    for each key in ["sourceId","itemId","fileId","sessionId","planId","playbackAttemptId","outputFingerprint"]
        value = descriptor[key]
        if HopText(value) = "" then return invalid
        if Len(value) > 512 then return invalid
    end for
    if type(descriptor.scope) <> "roAssociativeArray" then return invalid
    if descriptor.sourceAudio.Count() = 0 or descriptor.sourceAudio.Count() > 24 then return invalid
    identity = descriptor.audioIdentity
    if HopText(identity.id) = "" or HopCodec(identity.codec) = "" or HopLanguage(identity.language) = "" then return invalid
    if HopCodec(identity.codec) = "dts" then return invalid
    if not HopNumber(identity.index,4095) or not HopNumber(identity.channels,32) then return invalid
    count = 0
    sourceIndex = 0
    for each audio in descriptor.sourceAudio
        if type(audio) <> "roAssociativeArray" then return invalid
        if not HopNumber(audio.index,4095) or not HopNumber(audio.channels,32) then return invalid
        if audio.index <> sourceIndex then return invalid
        sourceIndex++
        if HopCodec(audio.codec) = "" or HopLanguage(audio.language) = "" then return invalid
        if audio.index = identity.index and HopCodec(audio.codec) = HopCodec(identity.codec) and HopLanguage(audio.language) = HopLanguage(identity.language) and audio.channels = identity.channels then count++
    end for
    if count <> 1 then return invalid
    return {descriptor:descriptor,token:token,generation:generation,experimental:experimental,phase:"await_inventory",restartCount:0,initialRestartMapping:false,mappingProvenance:"",seenBuffering:false,freshInventoryRequired:false,startedMs:nowMs,lastAdvanceMs:nowMs,inventorySignature:"",revision:0,trackId:"",playingPosition:invalid}
end function

' Never use Name or array position as codec/identity evidence.
function SiloUIOriginalResolve(descriptor as Object, inventory as Dynamic) as Object
    pending = {status:"pending",trackId:""}
    refused = {status:"refused",trackId:""}
    if type(inventory) <> "roArray" then return pending
    if inventory.Count() = 0 then return pending
    if inventory.Count() > 24 then return refused
    wanted = descriptor.audioIdentity
    codec = HopCodec(wanted.codec)
    language = HopLanguage(wanted.language)
    if codec = "" or codec = "truehd" or codec = "dts" or language = "" then return refused
    matches = []
    handles = {}
    for each native in inventory
        if type(native) <> "roAssociativeArray" then return refused
        handle = native.Track
        if type(handle) <> "String" and type(handle) <> "roString" then return refused
        if Len(handle) = 0 or Len(handle) > 4096 then return refused
        if handles.DoesExist(handle) then return refused
        handles[handle] = true
        nativeCodec = HopNativeCodec(native.Format)
        if nativeCodec = "" then return refused
        nativeLanguage = HopLanguage(native.Language)
        if nativeCodec = codec and (nativeLanguage = "" or nativeLanguage = language)
            if nativeLanguage = "" then return refused
            if native.Channels <> invalid
                if not HopNumber(native.Channels,32) then return refused
                if native.Channels <> wanted.channels then return refused
            end if
            matches.Push(handle)
        end if
    end for
    ' Missing native channels cannot distinguish source commentary/main lanes.
    sourceMatches = 0
    for each audio in descriptor.sourceAudio
        if HopCodec(audio.codec) = codec and HopLanguage(audio.language) = language then sourceMatches++
    end for
    if sourceMatches <> 1 or matches.Count() <> 1 then return refused
    return {status:"matched",trackId:matches[0]}
end function

function SiloUIOriginalReduce(previous as Dynamic, event as Dynamic) as Object
    result = {state:previous,command:invalid}
    if type(previous) <> "roAssociativeArray" or type(event) <> "roAssociativeArray" then return result
    if not HopNumber(event.nowMs,604800000) or not HopNumber(event.token,2147483647) or not HopNumber(event.generation,2147483647) then return result
    state = {}
    for each key in previous
        state[key] = previous[key]
    end for
    result.state = state
    if event.token <> state.token or event.generation <> state.generation then return result
    if state.phase = "recovering" or state.phase = "closed" then return result
    if event.kind = "cancel"
        state.phase = "closed"
        state.trackId = ""
        return result
    end if
    startupBudgetMs = 30000
    if state.experimental = true or SiloUIOriginalQualifiedP8(state.descriptor) or SiloUIOriginalQualifiedFilm(state.descriptor) then startupBudgetMs = 60000
    if state.phase <> "verified_playing" and event.nowMs - state.startedMs >= startupBudgetMs then return HopRecover(result,"startup_timeout")
    if state.phase = "verified_playing" and event.kind = "tick"
        if event.nativeState <> "paused" and event.nowMs - state.lastAdvanceMs >= 30000 then return HopRecover(result,"stall_timeout")
    end if
    if event.kind = "observation"
        if event.nativeState = "error" then return HopRecover(result,"native_error")
        if event.outputFingerprint <> invalid
            if event.outputFingerprint <> state.descriptor.outputFingerprint then return HopRecover(result,"output_changed")
        end if
        if event.nativeState = "buffering"
            state.seenBuffering = true
            if state.phase = "restarting" then state.phase = "await_inventory"
        end if
        if event.nativeState = "finished" and state.phase <> "verified_playing"
            if state.phase = "restarting" then return result
            if state.restartCount = 0 and state.seenBuffering
                state.restartCount = 1
                state.generation++
                state.phase = "restarting"
                state.seenBuffering = false
                state.freshInventoryRequired = true
                state.inventorySignature = ""
                state.revision++
                state.trackId = ""
                state.playingPosition = invalid
                result.command = {kind:"restart"}
                return result
            end if
            return HopRecover(result,"startup_failure")
        end if

    end if
    if event.kind = "observation" and state.phase = "verified_playing"
        if event.nativeState = "paused" then state.lastAdvanceMs = event.nowMs
        if event.nativeState = "playing"
            if event.audioTrack <> state.trackId or HopCodec(event.audioFormat) <> HopCodec(state.descriptor.audioIdentity.codec) then return HopRecover(result,"audio_unverified")
        end if
    end if
    if event.kind = "observation" and (state.phase = "selected" or state.phase = "verified_playing")
        correct = event.nativeState = "playing" and event.audioTrack = state.trackId and HopCodec(event.audioFormat) = HopCodec(state.descriptor.audioIdentity.codec)
        if correct and HopNumber(event.positionMs,604800000)
            if state.playingPosition <> invalid
                if event.positionMs > state.playingPosition
                    state.phase = "verified_playing"
                    state.lastAdvanceMs = event.nowMs
                end if
            end if
            state.playingPosition = event.positionMs
        else
            state.playingPosition = invalid
        end if
    end if
    if event.kind = "inventory"
        sameContent = event.provenance = "same_content_restart"
        if sameContent and state.restartCount <> 1 then return result
        if state.phase = "restarting" then return result
        if sameContent
            if state.initialRestartMapping <> true or state.seenBuffering <> true then return HopRecover(result,"audio_unverified")
            if event.bindingValidated <> true then return HopRecover(result,"binding_changed")
            if not SiloUIOriginalRestartSubset(state.descriptor,event.inventory,state.experimental = true) then return HopRecover(result,"audio_unverified")
        else if state.freshInventoryRequired and event.freshInventory <> true
            return result
        end if
        signature = SiloUIOriginalInventorySignature(event.inventory)
        if signature = state.inventorySignature then return result
        state.inventorySignature = signature
        state.revision++
        mapping = SiloUIOriginalResolve(state.descriptor,event.inventory)
        if mapping.status = "pending" and state.trackId <> "" then return HopRecover(result,"inventory_lost")
        if mapping.status = "refused" then return HopRecover(result,"audio_unverified")
        if mapping.status = "matched"
            state.mappingProvenance = "fresh_inventory"
            if sameContent then state.mappingProvenance = "same_content_restart"
            if state.restartCount = 0 then state.initialRestartMapping = SiloUIOriginalRestartSubset(state.descriptor,event.inventory,state.experimental = true)
            state.freshInventoryRequired = false
            state.playingPosition = invalid
            state.trackId = mapping.trackId
            state.phase = "selected"
            result.command = {kind:"select",trackId:mapping.trackId}
        end if
    end if
    return result
end function

function HopRecover(result as Object, reason as String) as Object
    result.state.phase = "recovering"
    result.state.trackId = ""
    result.state.reason = reason
    result.command = {kind:"recover",reason:reason}
    return result
end function

function HopNumber(value as Dynamic, maximum as Double) as Boolean
    kind = type(value)
    if kind <> "Integer" and kind <> "roInt" and kind <> "roInteger" and kind <> "LongInteger" and kind <> "roLongInteger" and kind <> "Float" and kind <> "roFloat" and kind <> "Double" and kind <> "roDouble" then return false
    return value >= 0 and value <= maximum and value = Int(value)
end function

function SiloUIOriginalInventorySignature(raw as Dynamic) as String
    if type(raw) <> "roArray" then return "empty"
    if raw.Count() > 24 then return "oversized"
    facts = []
    for each track in raw
        if type(track) <> "roAssociativeArray" then return "malformed"
        facts.Push({track:track.Track,codec:track.Format,language:track.Language,channels:track.Channels})
    end for
    return FormatJson(facts)
end function

 ' This local descriptor is minted only by the exact ordinary Task receipt.
' Marker alone cannot enlarge another profile, output or source-audio family.
function SiloUIOriginalQualifiedP8(descriptor as Dynamic) as Boolean
    if type(descriptor) <> "roAssociativeArray" then return false
    if descriptor.qualifiedRoute <> "p8_explicit_ac3_stereo_v1" then return false
    if not HopNumber(descriptor.dolbyVisionProfile,8) or descriptor.dolbyVisionProfile <> 8 then return false
    if descriptor.outputFingerprint <> "C000X/C208X/16.0.4.834/2160p60/hdr10" and descriptor.outputFingerprint <> "C000X/C208X/16.0.4.842/2160p60/hdr10" then return false
    video = descriptor.qualifiedVideo
    if type(video) <> "roAssociativeArray" then return false
    if video.width <> 3840 or not HopNumber(video.height,2160) then return false
    if video.height = 0 or video.dolbyVisionLevel <> 6 or video.baseCompatibility <> 1 then return false
    rateKind = type(video.frameRate)
    if rateKind <> "Float" and rateKind <> "roFloat" and rateKind <> "Double" and rateKind <> "roDouble" then return false
    if video.frameRate <= 0 or video.frameRate > 60 then return false
    if Abs(video.frameRate-24000.0/1001.0) >= 0.0001 then return false
    scope = descriptor.scope
    if type(scope) <> "roAssociativeArray" then return false
    if scope.provider <> "silo" or scope.sourceId <> descriptor.sourceId or HopText(scope.profileId) = "" then return false
    if not HopNumber(scope.generation,2147483646) then return false
    audio = descriptor.audioIdentity
    if type(audio) <> "roAssociativeArray" then return false
    if audio.codec <> "ac3" or audio.language <> "en" or audio.channels <> 2 or audio.layout <> "stereo" then return false
    tracks = descriptor.sourceAudio
    if type(tracks) <> "roArray" then return false
    if tracks.Count() <> 2 then return false
    selected = 0:other = 0
    for each track in tracks
        if type(track) <> "roAssociativeArray" or track.language <> "en" then return false
        if track.index = audio.index
            if track.codec <> "ac3" or track.channels <> 2 or track.layout <> "stereo" then return false
            selected++
        else
            if track.codec <> "dts" or track.channels <> 6 then return false
            if track.layout <> "5.1" and track.layout <> "5.1(side)" then return false
            other++
        end if
    end for
    return selected = 1 and other = 1
end function

' The experimental P8 DTS exception recognizes an unselected lane, never a DTS target.
' MAT is a native inventory description only for the existing TrueHD class.
function SiloUIOriginalRestartSubset(descriptor as Object, raw as Dynamic, experimental = false as Boolean) as Boolean
    if type(raw) <> "roArray" or type(descriptor.sourceAudio) <> "roArray" then return false
    if raw.Count() <> 2 or descriptor.sourceAudio.Count() <> 2 then return false
    if HopCodec(descriptor.audioIdentity.codec) <> "ac3" then return false
    language = HopLanguage(descriptor.audioIdentity.language)
    dtsP8 = (experimental or SiloUIOriginalQualifiedP8(descriptor)) and HopNumber(descriptor.dolbyVisionProfile,8) and descriptor.dolbyVisionProfile = 8
    sourceAC3 = 0:sourceOther = 0:otherCodec = "":otherChannels = invalid:ac3Channels = invalid
    for each audio in descriptor.sourceAudio
        if HopLanguage(audio.language) <> language then return false
        codec = HopCodec(audio.codec)
        if codec = "ac3"
            sourceAC3++:ac3Channels = audio.channels
        else if codec = "truehd" or (codec = "dts" and dtsP8)
            sourceOther++:otherCodec = codec:otherChannels = audio.channels
        else
            return false
        end if
    end for
    if sourceAC3 <> 1 or sourceOther <> 1 then return false
    if otherCodec = "dts"
        if ac3Channels <> 2 and ac3Channels <> 6 then return false
        if not HopNumber(otherChannels,8) or otherChannels = 0 then return false
    end if
    nativeAC3 = 0:nativeOther = 0
    for each track in raw
        if type(track) <> "roAssociativeArray" then return false
        if HopLanguage(track.Language) <> language then return false
        codec = HopNativeCodec(track.Format)
        if codec = "ac3"
            nativeAC3++
            if otherCodec = "dts" and track.DoesExist("Channels")
                if not HopNumber(track.Channels,32) or track.Channels <> ac3Channels then return false
            end if
        else if (otherCodec = "truehd" and (codec = "mat" or codec = "truehd")) or (otherCodec = "dts" and codec = "dts")
            nativeOther++
            if otherCodec = "dts" and track.DoesExist("Channels")
                if not HopNumber(track.Channels,8) or track.Channels <> otherChannels then return false
            end if
        else
            return false
        end if
    end for
    if nativeAC3 <> 1 or nativeOther <> 1 then return false
    return SiloUIOriginalResolve(descriptor,raw).status = "matched"
end function

function SiloUIOriginalQualifiedFilm(descriptor as Dynamic) as Boolean
    if type(descriptor) <> "roAssociativeArray" then return false
    if descriptor.qualifiedRoute <> "hdr10_base_original_v1" then return false
    fingerprint = descriptor.outputFingerprint
    if fingerprint <> "C000X/C208X/16.0.4.834/2160p60/hdr10" and fingerprint <> "C000X/C208X/16.0.4.842/2160p60/hdr10" then return false
    scope = descriptor.scope
    if type(scope) <> "roAssociativeArray" then return false
    if scope.provider <> "silo" or scope.sourceId <> descriptor.sourceId or HopText(scope.profileId) = "" then return false
    if not HopNumber(scope.generation,2147483646) then return false
    video = descriptor.videoFacts:audio = descriptor.audioIdentity
    if type(video) <> "roAssociativeArray" or type(audio) <> "roAssociativeArray" then return false
    if not HopNumber(video.width,3840) or not HopNumber(video.height,2160) then return false
    if video.width <= 1920 then return false
    if video.height = 0 or video.bit_depth <> 10 or video.dv_level <> 6 then return false
    if video.codec <> "hevc" or HopText(video.profile) <> "main 10" or video.interlaced <> false then return false
    if video.color_transfer <> "smpte2084" or video.color_primaries <> "bt2020" or video.color_space <> "bt2020nc" then return false
    if video.dv_bl_present <> true or video.dv_rpu_present <> true or video.dv_config_present <> true or video.dv_bl_compat_id_present <> true then return false
    if video.hdr10_plus <> invalid and video.hdr10_plus <> false then return false
    if HopLanguage(audio.language) = "" then return false
    if audio.channels <> 2 and audio.channels <> 6 then return false
    if audio.channels = 2 and audio.layout <> "stereo" then return false
    if audio.channels = 6 and audio.layout <> "5.1" and audio.layout <> "5.1(side)" then return false
    rate = descriptor.frameRate
    kind = type(rate)
    if kind <> "Float" and kind <> "roFloat" and kind <> "Double" and kind <> "roDouble" then return false
    if video.dv_profile = 8
        if descriptor.dolbyVisionProfile <> 8 or video.dv_bl_compat_id <> 1 or video.dv_enhancement_layer <> "none" then return false
        if video.dv_el_present <> invalid and video.dv_el_present <> false then return false
        if video.level <> 150 and video.level <> 153 then return false
        return audio.codec = "eac3" and (Abs(rate-24.0) < 0.0001 or Abs(rate-24000.0/1001.0) < 0.0001)
    end if
    if video.dv_profile = 7
        if descriptor.dolbyVisionProfile <> 7 or video.dv_bl_compat_id <> 6 or video.dv_el_present <> true or video.level <> 153 then return false
        if video.dv_enhancement_layer <> invalid and video.dv_enhancement_layer <> "" and video.dv_enhancement_layer <> "unknown" then return false
        return audio.codec = "ac3" and Abs(rate-24000.0/1001.0) < 0.0001
    end if
    return false
end function
