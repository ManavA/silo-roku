' Shared current SDK facts for dormant compatibility eligibility; no transport.
function SiloCompatSnapshot(device as Object, audio as Object) as Object
    try
        os = device.GetOSVersion():details = device.GetModelDetails():display = device.GetDisplayProperties()
        if type(os) <> "roAssociativeArray" or type(details) <> "roAssociativeArray" or type(display) <> "roAssociativeArray" then return {}
        video = SiloCompatDecodeEvidence(device.CanDecodeVideo({codec:"hevc",profile:"main 10",level:"5.1"}))
        decode = SiloCompatDecodeEvidence(device.CanDecodeAudio({codec:audio.codec,container:"mkv",chcnt:audio.channels,passthru:0}))
        passthrough = SiloCompatDecodeEvidence(device.CanDecodeAudio({codec:audio.codec,container:"mkv",chcnt:audio.channels,passthru:1}))
        if not SpBool(video) or not SpBool(display.DolbyVision) then return {}
        if not video or not display.DolbyVision then return {}
        snapshot = {model:device.GetModel(),modelNumber:details.ModelNumber,modelType:device.GetModelType(),os:SiloText(os.major)+"."+SiloText(os.minor)+"."+SiloText(os.revision)+"."+SiloText(os.build),videoMode:device.GetVideoMode(),dolbyVision:display.DolbyVision,hevcMain10:video,audioCodec:audio.codec,audioChannels:audio.channels,audioDecode:decode,audioPassthrough:passthrough}
        if not SiloCompatModernIdentity(snapshot) then return {}
        return snapshot
    catch error
        ' An SDK failure supplies no eligibility evidence.
    end try
    return {}
end function

' Preserve unknown evidence rather than coercing malformed SDK results to false.
function SiloCompatDecodeEvidence(raw as Dynamic) as Dynamic
    result = SpField(raw,"result")
    if not SpBool(result) then return invalid
    return result
end function

function SiloCompatSnapshotForKind(device as Object, audio as Object, kind = invalid as Dynamic, videoFacts = invalid as Dynamic) as Object
    if kind = invalid then return SiloCompatSnapshot(device,audio)
    if not SpText(kind,64) then return {}
    if kind = "experimental_query_p8_hdr10_ac3_fmp4_v1" then return SiloCompatP8HDR10SDKSnapshot(device,audio,videoFacts,"ac3")
    if kind = "experimental_query_p8_hdr10_fmp4_v1" then return SiloCompatP8HDR10SDKSnapshot(device,audio,videoFacts)
    if kind = "experimental_query_p7_hdr10_aac_fmp4_v1" then return SiloCompatP7AACSDKSnapshot(device,audio,videoFacts)
    if kind = "experimental_query_p7_hdr10_fmp4_v1" then return SiloCompatP7SDKSnapshot(device,audio,videoFacts)
    if kind <> "experimental_query_p8_ts_v1" then return {}
    level = SpField(videoFacts,"level")
    if not SpNumber(level,153,true) then return {}
    if level <> 150 and level <> 153 then return {}
    queryLevel = "5.0"
    if level = 153 then queryLevel = "5.1"
    if SpField(audio,"codec") <> "eac3" then return {}
    if not SpNumber(SpField(audio,"channels"),6,true) then return {}
    if audio.channels = 0 then return {}
    try
        os = device.GetOSVersion():details = device.GetModelDetails():display = device.GetDisplayProperties()
        if type(os) <> "roAssociativeArray" or type(details) <> "roAssociativeArray" or type(display) <> "roAssociativeArray" then return {}
        snapshot = {model:device.GetModel(),modelNumber:details.ModelNumber,modelType:device.GetModelType(),os:SiloText(os.major)+"."+SiloText(os.minor)+"."+SiloText(os.revision)+"."+SiloText(os.build),videoMode:device.GetVideoMode(),dolbyVision:display.DolbyVision}
        if not SiloCompatModernIdentity(snapshot) then return {}
        video = SiloCompatDecodeEvidence(device.CanDecodeVideo({codec:"hevc",container:"ts",profile:"main 10",level:queryLevel}))
        if not SpBool(video) then return {}
        if not video then return {}
    catch error
        return {}
    end try
    decode = invalid:passthrough = invalid
    try
        decode = SiloCompatDecodeEvidence(device.CanDecodeAudio({codec:audio.codec,container:"ts",chcnt:audio.channels,passthru:0}))
    catch error
        ' The other direction may still have a positive typed SDK result.
    end try
    try
        passthrough = SiloCompatDecodeEvidence(device.CanDecodeAudio({codec:audio.codec,container:"ts",chcnt:audio.channels,passthru:1}))
    catch error
        ' Unknown is retained separately from an explicit false result.
    end try
    snapshot.hevcMain10 = video
    snapshot.videoQuery = {codec:"hevc",container:"ts",profile:"main 10",level:queryLevel,result:video}
    snapshot.audioCodec = audio.codec:snapshot.audioChannels = audio.channels:snapshot.audioContainer = "ts"
    snapshot.audioDecode = decode:snapshot.audioPassthrough = passthrough
    return snapshot
end function

' Separate target evidence for the explicitly qualified P7/AAC2 route.
' Source audio stays untouched; the device must positively decode MP4 AAC stereo.
function SiloCompatP7AACSDKSnapshot(device as Object, audio as Object, videoFacts as Dynamic) as Object
    if not SiloCompatP7Video(videoFacts) then return {}
    if type(audio) <> "roAssociativeArray" then return {}
    if not ((audio.codec = "truehd" and audio.channels = 8) or (audio.codec = "ac3" and audio.channels = 6)) then return {}
    try
        os = device.GetOSVersion():details = device.GetModelDetails():display = device.GetDisplayProperties()
        if type(os) <> "roAssociativeArray" or type(details) <> "roAssociativeArray" or type(display) <> "roAssociativeArray" then return {}
        snapshot = {model:device.GetModel(),modelNumber:details.ModelNumber,modelType:device.GetModelType(),os:SiloText(os.major)+"."+SiloText(os.minor)+"."+SiloText(os.revision)+"."+SiloText(os.build),videoMode:device.GetVideoMode(),hdr10:display.hdr10}
        if not SiloCompatHDR10Identity(snapshot) then return {}
        video = SiloCompatDecodeEvidence(device.CanDecodeVideo({codec:"hevc",container:"mp4",profile:"main 10",level:"5.1"}))
        if not SpBool(video) or not video then return {}
        audioDecode = SiloCompatDecodeEvidence(device.CanDecodeAudio({codec:"aac",container:"mp4",chcnt:2,passthru:0}))
        if not SpBool(audioDecode) or not audioDecode then return {}
    catch error
        return {}
    end try
    snapshot.hevcMain10 = video
    snapshot.videoQuery = {codec:"hevc",container:"mp4",profile:"main 10",level:"5.1",result:video}
    snapshot.targetAudioCodec = "aac":snapshot.targetAudioChannels = 2:snapshot.targetAudioDecode = audioDecode:snapshot.targetAudioContainer = "mp4"
    return snapshot
end function

' Separate HDR10 output evidence: no Dolby Vision query or model allowlist.
function SiloCompatP7SDKSnapshot(device as Object, audio as Object, videoFacts as Dynamic) as Object
    if not SpNumber(SpField(videoFacts,"level"),153,true) then return {}
    if videoFacts.level <> 153 then return {}
    if SpField(audio,"codec") <> "ac3" then return {}
    if not SpNumber(SpField(audio,"channels"),6,true) then return {}
    if audio.channels <> 2 and audio.channels <> 6 then return {}
    try
        os = device.GetOSVersion():details = device.GetModelDetails():display = device.GetDisplayProperties()
        if type(os) <> "roAssociativeArray" or type(details) <> "roAssociativeArray" or type(display) <> "roAssociativeArray" then return {}
        snapshot = {model:device.GetModel(),modelNumber:details.ModelNumber,modelType:device.GetModelType(),os:SiloText(os.major)+"."+SiloText(os.minor)+"."+SiloText(os.revision)+"."+SiloText(os.build),videoMode:device.GetVideoMode(),hdr10:display.hdr10}
        if not SiloCompatHDR10Identity(snapshot) then return {}
        video = SiloCompatDecodeEvidence(device.CanDecodeVideo({codec:"hevc",container:"mp4",profile:"main 10",level:"5.1"}))
        if not SpBool(video) then return {}
        if not video then return {}
    catch error
        return {}
    end try
    decode = invalid:passthrough = invalid
    try
        decode = SiloCompatDecodeEvidence(device.CanDecodeAudio({codec:audio.codec,container:"mp4",chcnt:audio.channels,passthru:0}))
    catch error
        ' A separately positive passthrough result can still prove this audio.
    end try
    try
        passthrough = SiloCompatDecodeEvidence(device.CanDecodeAudio({codec:audio.codec,container:"mp4",chcnt:audio.channels,passthru:1}))
    catch error
        ' Unknown stays distinct from a negative answer.
    end try
    snapshot.hevcMain10 = video
    snapshot.videoQuery = {codec:"hevc",container:"mp4",profile:"main 10",level:"5.1",result:video}
    snapshot.audioCodec = audio.codec:snapshot.audioChannels = audio.channels:snapshot.audioContainer = "mp4"
    snapshot.audioDecode = decode:snapshot.audioPassthrough = passthrough
    return snapshot
end function

' Exact MP4 output queries preserve the real display Dolby Vision answer.
function SiloCompatP8HDR10SDKSnapshot(device as Object, audio as Object, videoFacts as Dynamic, codec = "eac3" as String) as Object
    if not SpNumber(SpField(videoFacts,"level"),153,true) then return {}
    if videoFacts.level <> 150 and videoFacts.level <> 153 then return {}
    queryLevel = "5.0"
    if videoFacts.level = 153 then queryLevel = "5.1"
    if SpField(audio,"codec") <> codec then return {}
    if not SpNumber(SpField(audio,"channels"),6,true) then return {}
    if audio.channels <> 2 and audio.channels <> 6 then return {}
    try
        os = device.GetOSVersion():details = device.GetModelDetails():display = device.GetDisplayProperties()
        if type(os) <> "roAssociativeArray" or type(details) <> "roAssociativeArray" or type(display) <> "roAssociativeArray" then return {}
        snapshot = {model:device.GetModel(),modelNumber:details.ModelNumber,modelType:device.GetModelType(),os:SiloText(os.major)+"."+SiloText(os.minor)+"."+SiloText(os.revision)+"."+SiloText(os.build),videoMode:device.GetVideoMode(),hdr10:display.hdr10,dolbyVision:display.DolbyVision}
        if not SiloCompatHDR10Identity(snapshot) then return {}
        video = SiloCompatDecodeEvidence(device.CanDecodeVideo({codec:"hevc",container:"mp4",profile:"main 10",level:queryLevel}))
        if not SpBool(video) then return {}
        if not video then return {}
    catch error
        return {}
    end try
    decode = invalid:passthrough = invalid
    try
        decode = SiloCompatDecodeEvidence(device.CanDecodeAudio({codec:audio.codec,container:"mp4",chcnt:audio.channels,passthru:0}))
    catch error
        ' A separately positive passthrough result can still prove this audio.
    end try
    try
        passthrough = SiloCompatDecodeEvidence(device.CanDecodeAudio({codec:audio.codec,container:"mp4",chcnt:audio.channels,passthru:1}))
    catch error
        ' Unknown stays distinct from a negative answer.
    end try
    snapshot.hevcMain10 = video
    snapshot.videoQuery = {codec:"hevc",container:"mp4",profile:"main 10",level:queryLevel,result:video}
    snapshot.audioCodec = audio.codec:snapshot.audioChannels = audio.channels:snapshot.audioContainer = "mp4"
    snapshot.audioDecode = decode:snapshot.audioPassthrough = passthrough
    return snapshot
end function
