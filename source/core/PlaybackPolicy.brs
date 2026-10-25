' Keep Silo claims at the level Roku APIs actually established.
function RokuSiloCapabilities(avc as Boolean, aac as Boolean, hevc as Boolean) as Object
    video = []
    audio = []
    containers = []
    if avc then video.Push("h264")
    if hevc then video.Push("hevc")
    if aac then audio.Push("aac")
    if video.Count() > 0 and audio.Count() > 0 then containers = ["mp4", "hls"]
    return {video_evidence: "declared", audio_evidence: "declared", codecs_video: video, codecs_video_hardware: [], codecs_audio: audio, containers: containers, hdr: false}
end function

' Profile 5 follows Roku's media specification and Dolby-capable hardware
' families. Profile 8.1 is narrower: native HLS evidence is recorded in
' docs/evidence/2026-10-15-server-native-recipes.md. No profile-7 native claim.
function RokuSiloDVProfileBounds(model as String, modelType as String, number as String, os as Object, maximumLevel as Integer) as Object
    supported = false
    if modelType = "TV"
        for each family in ["7000X","A000X","C000X","C000GB","G000X","J000X","L000X","M000X","P000X"]
            if UCase(model) = family then supported = true
        end for
    else
        for each family in ["3820X","3821X","3820X2","3821X2","4800X","4850X"]
            if UCase(model) = family then supported = true
        end for
    end if
    if not supported or maximumLevel < 4 then return []
    bounds = [{profile:5,max_level:maximumLevel,bl_compatibility_ids:[0]}]
    if modelType = "TV" and UCase(model) = "C000X" and UCase(number) = "C208X"
        qualifiedOS15 = os.major = "15" and os.minor = "3" and os.revision = "4" and os.build = "2402"
        qualifiedOS16 = os.major = "16" and os.minor = "0" and os.revision = "4" and os.build = "834"
        if qualifiedOS15 or qualifiedOS16
            testedLevel = 6
            if maximumLevel < testedLevel then testedLevel = maximumLevel
            bounds.Push({profile:8,max_level:testedLevel,bl_compatibility_ids:[1]})
        end if
    end if
    return bounds
end function
