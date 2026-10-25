' Standalone, header-free Silo file/context validation. No transport or registry.
function SpField(raw as Dynamic, key as String, fallback = invalid as Dynamic) as Dynamic
    if type(raw) <> "roAssociativeArray" then return fallback
    if raw.DoesExist(key) then return raw[key]
    for each name in raw
        if LCase(name) = LCase(key) then return raw[name]
    end for
    return fallback
end function

function SpFields(raw as Dynamic, required as Object, optional as Object) as Boolean
    if type(raw) <> "roAssociativeArray" then return false
    if raw.Count() < required.Count() or raw.Count() > required.Count()+optional.Count() then return false
    allowed = {}:seen = {}
    for each key in required
        allowed[LCase(key)] = true
    end for
    for each key in optional
        allowed[LCase(key)] = true
    end for
    for each key in raw
        folded = LCase(key)
        if not allowed.DoesExist(folded) or seen.DoesExist(folded) then return false
        seen[folded] = true
    end for
    for each key in required
        if not seen.DoesExist(LCase(key)) then return false
    end for
    return true
end function

function SpText(raw as Dynamic, maximum as Integer, empty = false as Boolean) as Boolean
    if type(raw) <> "String" and type(raw) <> "roString" then return false
    if Len(raw) > maximum or (not empty and raw = "") then return false
    return not CreateObject("roRegex","[\x00-\x1f\x7f]","").IsMatch(raw)
end function

function SpOpaque(raw as Dynamic, maximum = 256 as Integer, minimum = 1 as Integer) as Boolean
    if not SpText(raw,maximum) then return false
    if Len(raw) < minimum or raw = "." or raw = ".." or Instr(1,raw,"://") > 0 then return false
    return CreateObject("roRegex","^[A-Za-z0-9_.:/-]+$","").IsMatch(raw)
end function

function SpBool(raw as Dynamic) as Boolean
    return type(raw) = "Boolean" or type(raw) = "roBoolean"
end function

function SpCopy(raw as Dynamic) as Dynamic
    if type(raw) = "roAssociativeArray"
        output = {}
        for each key in raw
            output[key] = SpCopy(raw[key])
        end for
        return output
    else if type(raw) = "roArray"
        output = []
        for each value in raw
            output.Push(SpCopy(value))
        end for
        return output
    end if
    return raw
end function

function SpNumber(raw as Dynamic, maximum as Double, whole = false as Boolean) as Boolean
    kind = type(raw)
    if kind <> "Integer" and kind <> "roInt" and kind <> "roInteger" and kind <> "LongInteger" and kind <> "roLongInteger" and kind <> "Float" and kind <> "roFloat" and kind <> "Double" and kind <> "roDouble" then return false
    if raw <> raw or raw < 0 or raw > maximum then return false
    if whole then return raw = Int(raw)
    return true
end function

' Only a validated, bounded description may leave the Task. The artifact URL is
' returned separately for a future Task-owned fetch and must never enter a plan.
function SiloSelectedSubtitleReceipt(rawPlan as Dynamic, baseUrl as Dynamic, sessionId as Dynamic) as Object
    refused = {ok:false,public:invalid,privateArtifact:invalid}
    absent = {ok:true,public:invalid,privateArtifact:invalid}
    if type(rawPlan) <> "roAssociativeArray" then return refused
    subtitle = SpField(rawPlan,"subtitle")
    if subtitle = invalid then return absent
    if type(subtitle) <> "roAssociativeArray" then return refused
    mode = SpField(subtitle,"mode")
    if mode <> "off" and mode <> "burn_in" and mode <> "render" and mode <> "convert" then return refused
    tracks = SpField(rawPlan,"selected_tracks")
    if type(tracks) <> "roAssociativeArray" then return refused
    chosen = SpField(tracks,"subtitle")
    if mode = "off"
        if chosen <> invalid or tracks.DoesExist("subtitle") then return refused
        if SpField(subtitle,"track_id","") <> "" or SpField(subtitle,"artifact") <> invalid or SpField(subtitle,"embedded") <> invalid then return refused
        return {ok:true,public:{kind:"off",mode:"off",renderingReady:false},privateArtifact:invalid}
    end if
    if type(chosen) <> "roAssociativeArray" then return refused
    index = SpField(chosen,"index")
    fileId = SpField(rawPlan,"effective_media_file_id")
    if not SpOpaque(fileId,32) or not SpNumber(index,127,true) then return refused
    trackId = "file:" + fileId + ":subtitle:" + Int(index).ToStr()
    if SpField(chosen,"id") <> trackId or SpField(subtitle,"track_id") <> trackId then return refused
    inventory = SpField(subtitle,"inventory")
    if type(inventory) <> "roArray" or inventory.Count() = 0 or inventory.Count() > 128 then return refused
    row = invalid
    for ordinal = 0 to inventory.Count()-1
        entry = inventory[ordinal]
        if type(entry) <> "roAssociativeArray" then return refused
        if SpField(entry,"combined_index") <> ordinal then return refused
        if SpField(entry,"track_id") <> "file:" + fileId + ":subtitle:" + Int(ordinal).ToStr() then return refused
        if ordinal = index then row = entry
    end for
    if row = invalid then return refused
    source = SpField(row,"source")
    if source <> "external" and source <> "embedded" and source <> "downloaded" then return refused
    language = SpField(row,"language",""):label = SpField(row,"label",""):codec = SpField(row,"codec","")
    if not SpText(language,16,true) or not SpText(label,120,true) or not SpText(codec,32,true) then return refused
    if not SpBool(SpField(row,"forced")) or not SpBool(SpField(row,"hearing_impaired")) then return refused
    public = {kind:"unsupported",mode:mode,trackId:trackId,combinedIndex:index,source:source,codec:codec,language:language,label:label,forced:row.forced,hearingImpaired:row.hearing_impaired,renderingReady:false}
    artifact = SpField(subtitle,"artifact"):embedded = SpField(subtitle,"embedded")
    if mode = "burn_in"
        if artifact <> invalid or embedded <> invalid then return refused
        public.kind = "burn_in"
        return {ok:true,public:public,privateArtifact:invalid}
    end if
    if embedded <> invalid
        if mode <> "render" or artifact <> invalid or source <> "embedded" or type(embedded) <> "roAssociativeArray" then return refused
        if not SpNumber(SpField(embedded,"stream_index"),4095,true) then return refused
        containerId = SpField(embedded,"container_track_id","")
        if not SpText(containerId,32,true) then return refused
        public.kind = "embedded_render"
        return {ok:true,public:public,privateArtifact:invalid}
    end if
    if type(artifact) <> "roAssociativeArray" or SpField(row,"delivery") <> "sidecar" then return refused
    artifactUrl = SpField(artifact,"url"):inventoryUrl = SpField(row,"url")
    if not SpText(artifactUrl,2048) or not SpText(inventoryUrl,2048) then return refused
    format = SpField(artifact,"format")
    matchingUrl = artifactUrl = inventoryUrl
    if mode = "convert" and format = "vtt" then matchingUrl = artifactUrl = SpSubtitleConvertedUrl(inventoryUrl)
    if not matchingUrl then return refused
    if not SpText(baseUrl,1024) then return refused
    base = SiloUrlParts(baseUrl)
    resolved = SiloResolveUrl(artifactUrl,baseUrl)
    address = SiloUrlParts(resolved)
    if not base.ok or not address.ok or base.origin <> address.origin then return refused
    if Instr(1,resolved,"#") > 0 or Instr(1,resolved,Chr(92)) > 0 then return refused
    if Left(address.path,1) <> "/" or Left(address.path,2) = "//" then return refused
    mime = SpField(artifact,"mime_type")
    originSeconds = SpField(artifact,"timing_origin_seconds")
    if not SpNumber(originSeconds,604800) then return refused
    expectedMime = ""
    if format = "vtt" then expectedMime = "text/vtt"
    if format = "srt" then expectedMime = "application/x-subrip"
    if expectedMime = ""
        return {ok:true,public:public,privateArtifact:invalid}
    end if
    if mime <> expectedMime then return refused
    if not SpSubtitleOwnedArtifact(address.path,sessionId,fileId,index,format) then return refused
    public.kind = "sidecar_pending"
    public["format"] = format:public["mimeType"] = mime
    return {ok:true,public:public,privateArtifact:{url:resolved,format:format,mimeType:mime,timingOriginSeconds:originSeconds}}
end function

' The v2 projection publishes a session-scoped path with the effective file
' and combined ordinal. A same-origin URL alone does not prove selection.
function SpSubtitleOwnedArtifact(path as Dynamic, sessionId as Dynamic, fileId as String, index as Dynamic, format as String) as Boolean
    if not SpText(sessionId,128) then return false
    if not CreateObject("roRegex","^[A-Za-z0-9-]+$","").IsMatch(sessionId) then return false
    if not SpText(path,2048) then return false
    question = Instr(1,path,"?")
    if question = 0 then return false
    expected = "/api/v2/stream/" + sessionId + "/subtitles/" + Int(index).ToStr() + "." + format
    if Left(path,question-1) <> expected then return false
    query = Mid(path,question+1)
    fields = query.Tokenize("&")
    if fields.Count() = 0 or fields[0] <> "file_id=" + fileId then return false
    for fieldIndex = 1 to fields.Count()-1
        field = fields[fieldIndex]
        if not SpText(field,256) or Left(field,8) = "file_id=" then return false
    end for
    return true
end function

' Mirrors the server's convert-mode extension change; the source identity and
' every non-representation query field must remain byte-for-byte identical.
function SpSubtitleConvertedUrl(raw as String) as String
    question = Instr(1,raw,"?")
    path = raw:query = ""
    if question > 0 then path = Left(raw,question-1):query = Mid(raw,question+1)
    dot = 0
    for position = Len(path) to 1 step -1
        character = Mid(path,position,1)
        if character = "/" then exit for
        if character = "." then dot = position:exit for
    end for
    if dot > 0 then path = Left(path,dot-1)
    path += ".vtt"
    if question = 0 then return path
    retained = []
    for each field in query.Tokenize("&")
        if field <> "original=1" then retained.Push(field)
    end for
    if retained.Count() = 0 then return path
    result = path + "?" + retained[0]
    for index = 1 to retained.Count()-1
        result += "&" + retained[index]
    end for
    return result
end function

function SpScope(raw as Dynamic) as Dynamic
    if SpField(raw,"provider") <> "silo" then return invalid
    source = SpField(raw,"sourceId"):profile = SpField(raw,"profileId")
    if not SpText(source,512) or not SpText(profile,256,true) then return invalid
    if Left(source,5) <> "silo:" or Len(source) <= 5 then return invalid
    if not SpNumber(SpField(raw,"generation"),2147483646,true) then return invalid
    return {provider:"silo",sourceId:source,profileId:profile,generation:SpField(raw,"generation")}
end function

function SiloPlaybackFile(detail as Dynamic, sourceId as Dynamic, itemId as Dynamic, fileId as Dynamic, targetMs as Dynamic) as Dynamic
    if not SpText(sourceId,512) or not SpOpaque(itemId) or not SpOpaque(fileId) then return invalid
    if Left(sourceId,5) <> "silo:" or not SpNumber(targetMs,604800000) then return invalid
    if not SpBool(SpField(detail,"versionsComplete")) then return invalid
    if SpField(detail,"versionsComplete") <> true then return invalid
    item = SpField(detail,"item"):versions = SpField(detail,"versions")
    if SpField(item,"sourceId") <> sourceId or SpField(item,"itemId") <> itemId then return invalid
    if type(versions) <> "roArray" then return invalid
    if versions.Count() = 0 or versions.Count() > 16 then return invalid
    seen = {}:selected = invalid:selectedIndex = -1
    for index = 0 to versions.Count()-1
        row = versions[index]:id = SpField(row,"versionId")
        if not SpOpaque(id) then return invalid
        if seen.DoesExist(id) then return invalid
        seen[id] = true
        if SpField(row,"sourceId") <> sourceId or SpField(row,"itemId") <> itemId then return invalid
        if id = fileId then selected = row:selectedIndex = index
    end for
    if selected = invalid then return invalid
    duration = SpField(selected,"durationMs"):bitrate = SpField(selected,"bitrateKbps")
    if not SpNumber(duration,604800000) or not SpNumber(bitrate,2147483646) then return invalid
    if duration <= 0 or targetMs >= duration then return invalid
    return {sourceId:sourceId,itemId:itemId,versionId:fileId,versionIndex:selectedIndex,durationMs:duration,bitrateKbps:bitrate,version:selected}
end function

function SiloPlaybackTracks(raw as Dynamic) as Dynamic
    if not SpFields(raw,[],["audio","subtitle"]) then return invalid
    tracks = {}
    for each name in ["audio","subtitle"]
        value = SpField(raw,name)
        if value <> invalid
            if not SpFields(value,["id"],["index"]) then return invalid
            id = SpField(value,"id")
            if not SpOpaque(id) then return invalid
            track = {id:id}
            index = SpField(value,"index")
            if index <> invalid
                if not SpNumber(index,4095,true) then return invalid
                track["index"] = index
            end if
            tracks[name] = track
        else if raw.DoesExist(name)
            return invalid
        end if
    end for
    return tracks
end function

function SiloPlaybackQualities(raw as Dynamic) as Dynamic
    if type(raw) <> "roArray" then return invalid
    if raw.Count() > 16 then return invalid
    output = []:seen = {}
    for each row in raw
        if not SpFields(row,["label","preservesSource"],["height","bitrateKbps","displayName"]) then return invalid
        label = SpField(row,"label")
        if not SpText(label,64) or not SpBool(SpField(row,"preservesSource")) then return invalid
        if seen.DoesExist(label) then return invalid
        seen[label] = true
        quality = {label:label,preservesSource:SpField(row,"preservesSource")}
        for each field in ["height","bitrateKbps"]
            value = SpField(row,field)
            if value <> invalid
                cap = 200000
                if field = "height" then cap = 4320
                if not SpNumber(value,cap,true) then return invalid
                if value <= 0 then return invalid
                quality[field] = value
            else if row.DoesExist(field)
                return invalid
            end if
        end for
        display = SpField(row,"displayName")
        if display <> invalid
            if not SpText(display,120) then return invalid
            quality["displayName"] = display
        end if
        output.Push(quality)
    end for
    return output
end function

function SiloPlaybackContext(plan as Dynamic, scope as Dynamic) as Dynamic
    active = SpScope(scope)
    if active = invalid or SpField(plan,"provider") <> "silo" then return invalid
    raw = SpField(plan,"siloPlayback")
    fields = ["schemaVersion","sourceId","profileId","itemId","fileId","sessionRevision","installationId","sessionId","playbackAttemptId","planId","planAttemptId","planAttemptKey","attemptedPlanKeys","attemptCount","allowAlternateVersions","qualityPreference","selectedTracks","availableQualities"]
    if not SpFields(raw,fields,["bandwidthCapKbps","originalDisabled","subtitleOffRequired","mediaAuthMode"]) then return invalid
    if not SpNumber(SpField(raw,"schemaVersion"),1,true) then return invalid
    if SpField(raw,"schemaVersion") <> 1 then return invalid
    if SpField(raw,"sourceId") <> active.sourceId or SpField(raw,"profileId") <> active.profileId then return invalid
    if not SpNumber(SpField(raw,"sessionRevision"),2147483646,true) then return invalid
    if not SpNumber(SpField(raw,"attemptCount"),8,true) then return invalid
    if not SpBool(SpField(raw,"allowAlternateVersions")) then return invalid
    if SpField(raw,"allowAlternateVersions") <> false then return invalid
    output = {schemaVersion:1,sourceId:active.sourceId,profileId:active.profileId,sessionRevision:SpField(raw,"sessionRevision"),attemptCount:SpField(raw,"attemptCount"),allowAlternateVersions:false}
    for each name in ["itemId","fileId","installationId","sessionId","playbackAttemptId","planId","planAttemptId","planAttemptKey"]
        value = SpField(raw,name)
        minimum = 1:maximum = 256
        if name = "playbackAttemptId" or name = "planAttemptId" then minimum = 8:maximum = 128
        if not SpOpaque(value,maximum,minimum) then return invalid
        output[name] = value
    end for
    if SpField(plan,"sourceId") <> output.sourceId or SpField(plan,"itemId") <> output.itemId or SpField(plan,"versionId") <> output.fileId or SpField(plan,"sessionId") <> output.sessionId or SpField(plan,"installationId") <> output.installationId then return invalid
    keys = SpField(raw,"attemptedPlanKeys")
    if type(keys) <> "roArray" then return invalid
    if keys.Count() > 16 then return invalid
    output["attemptedPlanKeys"] = []:seen = {}
    for each key in keys
        if not SpOpaque(key,128,8) then return invalid
        if seen.DoesExist(key) then return invalid
        seen[key] = true:output.attemptedPlanKeys.Push(key)
    end for
    quality = SpField(raw,"qualityPreference")
    if not SpText(quality,64) then return invalid
    if quality <> "original" and quality <> "4k" and quality <> "1080p_high" and quality <> "1080p" and quality <> "720p" and quality <> "480p" then return invalid
    tracks = SiloPlaybackTracks(SpField(raw,"selectedTracks"))
    qualities = SiloPlaybackQualities(SpField(raw,"availableQualities"))
    if tracks = invalid or qualities = invalid then return invalid
    output["qualityPreference"] = quality:output["selectedTracks"] = tracks:output["availableQualities"] = qualities
    if raw.DoesExist("originalDisabled")
        if not SpBool(raw.originalDisabled) then return invalid
        output["originalDisabled"] = raw.originalDisabled
    end if
    if raw.DoesExist("subtitleOffRequired")
        if not SpBool(raw.subtitleOffRequired) then return invalid
        output["subtitleOffRequired"] = raw.subtitleOffRequired
    end if
    if raw.DoesExist("mediaAuthMode")
        if not SpText(raw.mediaAuthMode,32) or raw.mediaAuthMode <> "api_header_v1" then return invalid
        output["mediaAuthMode"] = raw.mediaAuthMode
    end if
    cap = SpField(raw,"bandwidthCapKbps")
    if cap <> invalid
        if not SpNumber(cap,200000,true) then return invalid
        if cap <= 0 then return invalid
        output["bandwidthCapKbps"] = cap
    else if raw.DoesExist("bandwidthCapKbps")
        return invalid
    end if
    return output
end function

' Retained server plan IDs have no minimum length; the mutation request does.
function SiloPlaybackCanReplan(context as Dynamic) as Boolean
    for each key in ["playbackAttemptId","planId","planAttemptId","planAttemptKey"]
        if not SpOpaque(SpField(context,key),128,8) then return false
    end for
    count = SpField(context,"attemptCount")
    if not SpNumber(count,8,true) then return false
    if count >= 8 then return false
    keys = SpField(context,"attemptedPlanKeys")
    if type(keys) <> "roArray" then return false
    if keys.Count() > 16 then return false
    found = false
    for each key in keys
        if not SpOpaque(key,128,8) then return false
        if key = SpField(context,"planAttemptKey") then found = true
    end for
    if keys.Count() = 16 and not found then return false
    return true
end function

' Internal startup authorization from fresh native inventory. Quality and
' failure requests cannot introduce arbitrary same-file track selectors.
function SiloPlaybackAudioContext(current as Object, detail as Object, audio as Object) as Dynamic
    file = SiloPlaybackFile(detail,current.sourceId,current.itemId,current.fileId,0)
    if file = invalid then return invalid
    found = false
    for each track in SpField(file.version,"audioTracks",[])
        if SpField(track,"index") = SpField(audio,"index") and SpField(track,"id") = SpField(audio,"id") then found = true
    end for
    if not found or not SpNumber(SpField(audio,"index"),4095,true) then return invalid
    nextContext = SpCopy(current)
    nextContext.selectedTracks.audio = {id:"file:"+current.fileId+":audio:"+Int(audio.index).ToStr(),index:Int(audio.index)}
    return nextContext
end function

function SiloPlaybackReplanBody(context as Dynamic, params as Dynamic, capabilities as Object, playbackContext as Object, trackChange = false as Boolean) as Object
    failed = {ok:false,errorCode:"invalid_request"}
    if type(context) <> "roAssociativeArray" then return failed
    plan = {provider:"silo",sourceId:SpField(context,"sourceId"),itemId:SpField(context,"itemId"),versionId:SpField(context,"fileId"),sessionId:SpField(context,"sessionId"),installationId:SpField(context,"installationId"),siloPlayback:context}
    scope = {provider:"silo",sourceId:SpField(context,"sourceId"),profileId:SpField(context,"profileId"),generation:0}
    current = SiloPlaybackContext(plan,scope)
    if current = invalid then return failed
    if not SiloPlaybackCanReplan(current) then return failed
    quality = SpField(params,"qualityPreference"):position = SpField(params,"positionMs"):requestId = SpField(params,"replanRequestId")
    if not SpText(quality,64) or not SpNumber(position,604800000) or not SpOpaque(requestId,128,8) then return failed
    ' A provider track mutation preserves the accepted request's quality even
    ' when the server menu omits an equivalent source-resolution rung.
    if trackChange
        if quality <> current.qualityPreference or params.DoesExist("failureClassification") then return failed
    end if
    available = false
    for each row in current.availableQualities
        if row.label = quality then available = true
    end for
    if current.attemptCount >= 8 then return failed
    if quality <> "original" and quality <> "4k" and quality <> "1080p_high" and quality <> "1080p" and quality <> "720p" and quality <> "480p" then return failed
    tracks = current.selectedTracks
    override = SpField(params,"selectedTracks")
    if override <> invalid
        tracks = SiloPlaybackTracks(override)
        if tracks = invalid then return failed
        ' A manual replacement may only name a currently proven same-file lane.
        for each name in ["audio","subtitle"]
            selected = SpField(tracks,name):known = SpField(current.selectedTracks,name)
            if selected <> invalid
                if known = invalid then return failed
                if FormatJson(selected) <> FormatJson(known) then return failed
            end if
        end for
        if SpField(current.selectedTracks,"audio") <> invalid and SpField(tracks,"audio") = invalid then return failed
    end if
    if not available and not trackChange
        ' Failure recovery retains accepted intent; the menu lists new choices.
        failure = SpField(params,"failureClassification")
        retainedFailure = (failure = "decoder_failure" or failure = "buffering_timeout") and quality = current.qualityPreference
        if not retainedFailure or FormatJson(tracks) <> FormatJson(current.selectedTracks) then return failed
    end if
    keys = []
    for each key in current.attemptedPlanKeys
        keys.Push(key)
    end for
    found = false
    for each key in keys
        if key = current.planAttemptKey then found = true
    end for
    if not found then keys.Push(current.planAttemptKey)
    if keys.Count() > 16 then return failed
    nextContext = {}
    for each key in current
        nextContext[key] = current[key]
    end for
    nextContext["attemptCount"] = current.attemptCount+1:nextContext["attemptedPlanKeys"] = keys:nextContext["qualityPreference"] = quality:nextContext["selectedTracks"] = tracks
    body = {installation_id:current.installationId,protocol_version:3,playback_attempt_id:current.playbackAttemptId,replan_request_id:requestId,
        failed_plan_id:current.planId,plan_attempt_id:current.planAttemptId,plan_attempt_key:current.planAttemptKey,attempted_plan_keys:SpCopy(keys),attempt_count:nextContext.attemptCount,
        operation:"quality_change",quality_preference:quality,position_seconds:position/1000#,metered:false,selected_tracks:SpCopy(tracks),client_features:[],client_capabilities:capabilities,client_playback_context:playbackContext}
    if trackChange then body.operation = "track_change"
    failure = SpField(params,"failureClassification")
    if failure = invalid and FormatJson(tracks) <> FormatJson(current.selectedTracks) then body.operation = "track_change"
    if failure <> invalid
        if failure <> "decoder_failure" and failure <> "buffering_timeout" then return failed
        body.operation = "failure_recovery"
        body["failure"] = {classification:failure}
    end if
    if current.DoesExist("bandwidthCapKbps") then body["bandwidth_cap_kbps"] = current.bandwidthCapKbps
    return {ok:true,body:body,context:nextContext}
end function

' Auto delegates only within one unambiguous native presentation and part.
' This is candidate inventory only; the worker pins the final chosen anchor.
function SiloNativeSelection(detail as Object, sourceId as String, itemId as String, selected as String) as Dynamic
    versions = SpField(detail,"versions")
    if type(versions) <> "roArray" or versions.Count() = 0 then return invalid
    fileId = selected
    if fileId = "" then fileId = SpField(versions[0],"versionId","")
    if SiloPlaybackFile(detail,sourceId,itemId,fileId,0) = invalid then return invalid
    pinned = {fileId:fileId,allowedFileIds:[fileId],allowAlternateVersions:false}
    if selected <> "" then return pinned
    variants = SpField(detail,"playbackVariants")
    if type(variants) <> "roArray" or variants.Count() <> 1 then return pinned
    variant = variants[0]
    if SpField(variant,"partCount") <> 1 then return pinned
    parts = SpField(variant,"parts")
    if type(parts) <> "roArray" or parts.Count() <> 1 then return pinned
    part = parts[0]:anchor = SpField(part,"defaultFileId","")
    if anchor = "" then anchor = SpField(variant,"defaultFileId","")
    ids = SpField(part,"fileIds")
    if type(ids) <> "roArray" or ids.Count() = 0 or ids.Count() > 16 then return pinned
    if not SpOpaque(anchor) then return pinned
    seen = {}:allowed = []:found = false
    for each id in ids
        if not SpOpaque(id) then return pinned
        if seen.DoesExist(id) then return pinned
        if SiloPlaybackFile(detail,sourceId,itemId,id,0) = invalid then return pinned
        seen[id] = true:allowed.Push(id)
        if id = anchor then found = true
    end for
    if not found then return pinned
    return {fileId:anchor,allowedFileIds:allowed,allowAlternateVersions:true}
end function

' Automatic SDR recovery only descends. Unknown output stays within HD; a
' retained server menu, when present, must explicitly offer the next profile.
function SiloFallbackQuality(current as String, maximum as String, qualities = invalid as Dynamic) as String
    if current <> "original" and current <> "4k" and current <> "1080p_high" and current <> "1080p" and current <> "720p" then return ""
    candidates = ["720p", "480p"]
    if current = "720p" then candidates = ["480p"]
    if maximum = "1080p" or maximum = "2160p"
        if current <> "1080p" and current <> "720p" then candidates = ["1080p", "720p", "480p"]
    end if
    for each candidate in candidates
        if qualities = invalid then return candidate
        if type(qualities) = "roArray"
            for each quality in qualities
                if SpField(quality,"label") = candidate then return candidate
            end for
        end if
    end for
    return ""
end function

' Source choices are a URL-free snapshot, independent of selected subtitle mode.
function SiloSourceSubtitleInventory(rawPlan as Dynamic, plan as Dynamic, scope as Dynamic) as Dynamic
    current = SiloPlaybackContext(plan,scope)
    if current = invalid then return invalid
    if SpField(rawPlan,"effective_media_file_id") <> current.fileId then return invalid
    if SpField(rawPlan,"plan_id") <> current.planId or SpField(rawPlan,"plan_attempt_key") <> current.planAttemptKey then return invalid
    session = SpField(rawPlan,"session_id",current.sessionId)
    if session <> current.sessionId then return invalid
    inventory = SpField(SpField(rawPlan,"subtitle"),"inventory")
    if type(inventory) <> "roArray" then return invalid
    if inventory.Count() > 128 then return invalid
    entries = []
    for ordinal = 0 to inventory.Count()-1
        entry = inventory[ordinal]
        if type(entry) <> "roAssociativeArray" then return invalid
        seenFields = {}
        for each key in entry
            folded = LCase(key)
            if seenFields.DoesExist(folded) then return invalid
            seenFields[folded] = true
        end for
        index = SpField(entry,"combined_index")
        if not SpNumber(index,127,true) then return invalid
        if index <> ordinal then return invalid
        trackId = "file:" + current.fileId + ":subtitle:" + Int(ordinal).ToStr()
        if SpField(entry,"track_id") <> trackId then return invalid
        source = SpField(entry,"source"):delivery = SpField(entry,"delivery")
        if source <> "external" and source <> "embedded" and source <> "downloaded" then return invalid
        if delivery <> "sidecar" and delivery <> "burn_in_only" then return invalid
        codec = SpField(entry,"codec",""):language = SpField(entry,"language",""):label = SpField(entry,"label","")
        if not SpText(codec,32,true) or not SpText(language,16,true) or not SpText(label,120,true) then return invalid
        forced = SpField(entry,"forced"):isDefault = SpField(entry,"default"):hearing = SpField(entry,"hearing_impaired")
        if not SpBool(forced) or not SpBool(isDefault) or not SpBool(hearing) then return invalid
        entries.Push({trackId:trackId,combinedIndex:index,source:source,codec:codec,language:language,label:label,forced:forced,default:isDefault,hearingImpaired:hearing,delivery:delivery})
    end for
    owner = {sourceId:current.sourceId,profileId:current.profileId,generation:SpField(scope,"generation"),sessionRevision:current.sessionRevision,sessionId:current.sessionId,fileId:current.fileId,planId:current.planId,planAttemptId:current.planAttemptId,planAttemptKey:current.planAttemptKey,playbackAttemptId:current.playbackAttemptId,attemptCount:current.attemptCount}
    return {owner:owner,entries:entries}
end function

' Only this owned server snapshot can authorize an explicit source selection.
function SiloUserSubtitleSelection(plan as Dynamic, scope as Dynamic, trackId as Dynamic, index as Dynamic) as Dynamic
    current = SiloPlaybackContext(plan,scope)
    if current = invalid or not SpNumber(index,127,true) then return invalid
    inventory = SpField(plan,"sourceSubtitleInventory")
    if not SpFields(inventory,["owner","entries"],[]) then return invalid
    owner = SpField(inventory,"owner")
    ownerFields = ["sourceId","profileId","generation","sessionRevision","sessionId","fileId","planId","planAttemptId","planAttemptKey","playbackAttemptId","attemptCount"]
    if not SpFields(owner,ownerFields,[]) then return invalid
    if not SpNumber(SpField(owner,"generation"),2147483646,true) or not SpNumber(SpField(owner,"sessionRevision"),2147483646,true) then return invalid
    if not SpNumber(SpField(owner,"attemptCount"),8,true) then return invalid
    for each key in ownerFields
        expected = SpField(current,key)
        if key = "generation" then expected = SpField(scope,"generation")
        if SpField(owner,key) <> expected then return invalid
    end for
    entries = SpField(inventory,"entries")
    if type(entries) <> "roArray" then return invalid
    if entries.Count() > 128 then return invalid
    wire = []
    fields = ["trackId","combinedIndex","source","codec","language","label","forced","default","hearingImpaired","delivery"]
    for each entry in entries
        if not SpFields(entry,fields,[]) then return invalid
        wire.Push({track_id:SpField(entry,"trackId"),combined_index:SpField(entry,"combinedIndex"),source:SpField(entry,"source"),codec:SpField(entry,"codec"),language:SpField(entry,"language"),label:SpField(entry,"label"),forced:SpField(entry,"forced"),default:SpField(entry,"default"),hearing_impaired:SpField(entry,"hearingImpaired"),delivery:SpField(entry,"delivery")})
    end for
    raw = {plan_id:current.planId,plan_attempt_key:current.planAttemptKey,session_id:current.sessionId,effective_media_file_id:current.fileId,subtitle:{inventory:wire}}
    validated = SiloSourceSubtitleInventory(raw,plan,scope)
    if validated = invalid then return invalid
    if index >= validated.entries.Count() then return invalid
    chosen = validated.entries[index]
    if chosen.trackId <> trackId then return invalid
    return {id:chosen.trackId,index:chosen.combinedIndex}
end function

' Seek authority is optional and URL-free. It never changes native admission.
function SiloSeekFeatures(raw as Dynamic) as Dynamic
    if type(raw) <> "roArray" then return invalid
    if raw.Count() > 64 then return invalid
    out = []:seen = {}
    for each value in raw
        if not SpText(value,96) then return invalid
        if not CreateObject("roRegex","^[a-z0-9_.-]+$","").IsMatch(value) then return invalid
        if seen.DoesExist(value) then return invalid
        seen[value] = true:out.Push(value)
    end for
    if not seen.DoesExist("seek_reanchor_v1") then return invalid
    return out
end function

function SiloSeekUuid(value as Dynamic) as Boolean
    if not SpText(value,36) then return false
    return CreateObject("roRegex","^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$","").IsMatch(value)
end function

function SiloSeekEqual(left as Dynamic, right as Dynamic) as Boolean
    if type(left) = "roAssociativeArray"
        if type(right) <> "roAssociativeArray" then return false
        if left.Count() <> right.Count() then return false
        for each key in left
            if not right.DoesExist(key) then return false
            if not SiloSeekEqual(left[key],right[key]) then return false
        end for
        return true
    else if type(left) = "roArray"
        if type(right) <> "roArray" then return false
        if left.Count() <> right.Count() then return false
        for i = 0 to left.Count()-1
            if not SiloSeekEqual(left[i],right[i]) then return false
        end for
        return true
    end if
    if type(right) = "roArray" or type(right) = "roAssociativeArray" then return false
    return left = right
end function

' Generated native request facts and server route facts have a bounded schema.
' Unknown nested keys disable this optional operation, never leak into a plan.
function SiloSeekSafeTree(raw as Dynamic, depth = 0 as Integer) as Boolean
    if depth > 8 then return false
    if type(raw) = "roAssociativeArray"
        if raw.Count() > 64 then return false
        names = "video_evidence audio_evidence codecs_video codecs_video_hardware codecs_audio containers max_resolution hdr hdr_details hdr10 hdr10_max_width hdr10_max_height hdr10_max_frame_rate hdr10_max_bitrate_kbps hdr10_plus hlg dolby_vision_profiles dolby_vision_profile_levels bl_compatibility_ids profile max_level enhanced_layer video_range bit_depth dv_bl_compat_id dv_base_layer_proven dv_el_type protocol_version app_version device platform model form_factor output display audio hdr_evidence hdr_types known supports_hdr supports_hdr10 supports_hdr10_plus supports_hlg supports_dolby_vision passthrough codecs channels max_channels codecs_decode codecs_passthrough decode_codecs passthrough_codecs deliveries original_http progressive hls enabled supported_on_device video_codecs audio_decode_codecs audio_passthrough_codecs subtitles embedded_text sidecar_text ass_styling embedded_bitmap sidecar_bitmap font_attachments features auth_header_refresh validated_claims transformations failure_reason video_codec audio_codec dynamic_range width height frame_rate bitrate_kbps audio_channels audio_layout video_sample_entry segment_container media_file_id duration_seconds container video_profile video_level color_range dolby_vision_profile dolby_vision_level dv_enhancement_layer video_copy_unsafe video audio codec atmos_preserved dts_variant reason dolby_vision dolby_vision_reason ass_styling_preserved bitmap_overlay bitmap_sidecar name executor recipe_version id registry_revision action stream_index container_track_id format mime_type mode track_id"
        allowed = {}:seen = {}
        for each name in names.Tokenize(" ")
            allowed[name] = true
        end for
        for each key in raw
            folded = LCase(key)
            if not allowed.DoesExist(folded) or seen.DoesExist(folded) then return false
            seen[folded] = true
            if not SiloSeekSafeTree(raw[key],depth+1) then return false
        end for
        return true
    else if type(raw) = "roArray"
        if raw.Count() > 64 then return false
        for each value in raw
            if not SiloSeekSafeTree(value,depth+1) then return false
        end for
        return true
    else if type(raw) = "String" or type(raw) = "roString"
        return SpText(raw,256,true) and Instr(1,raw,"://") = 0
    else if SpBool(raw)
        return true
    end if
    return SpNumber(raw,2147483646)
end function

function SiloSeekRoute(raw as Dynamic) as Dynamic
    if type(raw) <> "roAssociativeArray" then return invalid
    source = SpField(raw,"source"):recipe = SpField(raw,"effective_recipe")
    stream = SpField(raw,"stream"):subtitle = SpField(raw,"subtitle")
    if not SpFields(source,["media_file_id","hdr10_plus","dv_enhancement_layer"],["duration_seconds","container","video_codec","video_profile","video_level","bit_depth","color_range","width","height","frame_rate","bitrate_kbps","dynamic_range","dolby_vision_profile","dolby_vision_level","dv_bl_compat_id","dv_base_layer_proven","audio_codec","audio_channels","audio_layout","video_copy_unsafe"]) then return invalid
    if not SpFields(recipe,[],["video_codec","video_sample_entry","segment_container","audio_codec","dynamic_range","width","height","frame_rate","bitrate_kbps","audio_channels","audio_layout"]) then return invalid
    if recipe.DoesExist("segment_container")
        if not SpText(recipe.segment_container,16) then return invalid
        if recipe.segment_container <> "mpegts" then return invalid
        if recipe.DoesExist("video_sample_entry") then return invalid
    end if
    if not SpFields(stream,["url","protocol"],["container","mime_type","headers","header_refresh","header_refresh_url"]) then return invalid
    if not SpFields(subtitle,["mode"],["track_id","embedded","artifact","inventory"]) then return invalid
    if not SpText(SpField(raw,"delivery"),32) then return invalid
    if not CreateObject("roRegex","^(original_http|server_remux_progressive|server_remux_hls|server_transcode_hls)$","").IsMatch(raw.delivery) then return invalid
    if not SpText(stream.protocol,32) then return invalid
    if not CreateObject("roRegex","^(hls|dash|progressive|http_progressive|http|original_http)$","").IsMatch(stream.protocol) then return invalid
    if stream.DoesExist("container")
        if not SpText(stream.container,32,true) then return invalid
        if not CreateObject("roRegex","^[a-zA-Z0-9_-]*$","").IsMatch(stream.container) then return invalid
    end if
    if stream.DoesExist("mime_type")
        if not SpText(stream.mime_type,128) then return invalid
        if not CreateObject("roRegex","^[a-zA-Z0-9][a-zA-Z0-9.+-]*/[a-zA-Z0-9][a-zA-Z0-9.+-]*$","").IsMatch(stream.mime_type) then return invalid
    end if
    if stream.DoesExist("header_refresh")
        if not SpText(stream.header_refresh,32,true) then return invalid
        if stream.header_refresh <> "" and stream.header_refresh <> "none" then return invalid
    end if
    if raw.DoesExist("subtitle_fidelity_policy")
        if not SpText(raw.subtitle_fidelity_policy,32) then return invalid
        if raw.subtitle_fidelity_policy <> "require_authored_fidelity" and raw.subtitle_fidelity_policy <> "allow_simplified_rendering" then return invalid
    end if
    subroute = {mode:subtitle.mode}
    if subtitle.DoesExist("track_id") then subroute["track_id"] = subtitle.track_id
    if subtitle.DoesExist("embedded") then subroute["embedded"] = SpCopy(subtitle.embedded)
    if subtitle.DoesExist("artifact")
        artifact = subtitle.artifact
        if not SpFields(artifact,["url","format","mime_type","timing_origin_seconds"],[]) then return invalid
        subroute["format"] = artifact.format:subroute["mime_type"] = artifact.mime_type
    end if
    out = {source:SpCopy(source),recipe:SpCopy(recipe),subtitle:subroute}
    for each name in ["delivery","requested_media_file_id","effective_media_file_id","claims","transformations","applied_quirks","runtime_corrections","subtitle_fidelity_policy"]
        if raw.DoesExist(name) then out[name] = SpCopy(raw[name])
    end for
    ' A nil server []string is JSON null; canonicalize only empty transformation claims.
    if out.DoesExist("transformations")
        if type(out.transformations) <> "roArray" or out.transformations.Count() > 64 then return invalid
        for each transformation in out.transformations
            if not SpFields(transformation,["name","executor","recipe_version"],["validated_claims"]) then return invalid
            for each name in ["name","executor","recipe_version"]
                if not SpText(transformation[name],96) then return invalid
            end for
            if transformation.DoesExist("validated_claims")
                claims = transformation.validated_claims
                if claims = invalid
                    transformation.Delete("validated_claims")
                else
                    if type(claims) <> "roArray" then return invalid
                    if claims.Count() > 64 then return invalid
                    for each claim in claims
                        if not SpText(claim,96) then return invalid
                        if not CreateObject("roRegex","^[a-zA-Z0-9_.-]+$","").IsMatch(claim) then return invalid
                    end for
                    if claims.Count() = 0 then transformation.Delete("validated_claims")
                end if
            end if
        end for
    end if
    out["protocol"] = stream.protocol
    if stream.DoesExist("container") then out["container"] = stream.container
    if stream.DoesExist("mime_type") then out["mime_type"] = stream.mime_type
    if stream.DoesExist("header_refresh") then out["header_refresh"] = stream.header_refresh
    ' Validate the nested immutable data before adding fixed route field names.
    for each key in ["source","recipe","subtitle","claims","transformations","applied_quirks","runtime_corrections"]
        if out.DoesExist(key) then if not SiloSeekSafeTree(out[key]) then return invalid
    end for
    if Len(FormatJson(out)) > 16384 then return invalid
    return out
end function

function SiloSeekTimeline(raw as Dynamic) as Dynamic
    required = ["source_start_seconds","stream_origin_seconds","player_start_seconds","timeline_offset_seconds","can_seek_anywhere","seek_restoration"]
    if not SpFields(raw,required,["seek_window_start_seconds","seek_window_end_seconds"]) then return invalid
    for each key in ["source_start_seconds","stream_origin_seconds","player_start_seconds","timeline_offset_seconds","seek_window_start_seconds","seek_window_end_seconds"]
        if raw.DoesExist(key) then if not SpNumber(raw[key],604800) then return invalid
    end for
    if not SpBool(raw.can_seek_anywhere) or not SpText(raw.seek_restoration,32) then return invalid
    if raw.DoesExist("seek_window_end_seconds")
        if not raw.DoesExist("seek_window_start_seconds") then return invalid
        if raw.seek_window_end_seconds < raw.seek_window_start_seconds then return invalid
    end if
    return SpCopy(raw)
end function

function SiloSeekDescriptor(plan as Dynamic, scope as Dynamic) as Dynamic
    current = SiloPlaybackContext(plan,scope):d = SpField(plan,"seekReanchor")
    if current = invalid then return invalid
    if not SpFields(d,["schemaVersion","owner","control","request","route","timeline","discoveryFeatures","serverFeatures"],[]) then return invalid
    if Len(FormatJson(d)) > 32768 then return invalid
    if d.schemaVersion <> 1 or not SoSeekScopeEqual(d.owner,SpScope(scope)) then return invalid
    if not SiloSeekEqual(d.control,current) then return invalid
    if SpField(plan,"planId") <> current.planId or SpField(plan,"planAttemptKey") <> current.planAttemptKey then return invalid
    if not SiloSeekRouteProof(d.route) then return invalid
    if d.route.source.media_file_id <> current.fileId or d.route.effective_media_file_id <> current.fileId then return invalid
    if SiloSeekFeatures(d.discoveryFeatures) = invalid or SiloSeekFeatures(d.serverFeatures) = invalid then return invalid
    request = d.request
    if not SpFields(request,["client_capabilities","client_playback_context","client_features","quality_preference","metered"],["bandwidth_cap_kbps","bandwidth_estimate_kbps"]) then return invalid
    if not SiloSeekSafeTree(request.client_capabilities) or not SiloSeekSafeTree(request.client_playback_context) then return invalid
    if SiloSeekFeatures(request.client_features) = invalid then return invalid
    if request.quality_preference <> current.qualityPreference or request.metered <> false then return invalid
    if not SiloSeekEqual(SpField(request,"bandwidth_cap_kbps"),SpField(current,"bandwidthCapKbps")) then return invalid
    if SiloSeekTimeline(d.timeline) = invalid then return invalid
    if Len(FormatJson(d)) > 32768 then return invalid
    return SpCopy(d)
end function

function SoSeekScopeEqual(left as Dynamic, right as Dynamic) as Boolean
    if left = invalid or right = invalid then return false
    if not SpFields(left,["provider","sourceId","profileId","generation"],[]) then return false
    for each key in ["provider","sourceId","profileId","generation"]
        if SpField(left,key) <> SpField(right,key) then return false
    end for
    return true
end function

' Validate the canonical proof with the same bounded source/recipe schema used
' at acceptance. The private URL is deliberately absent from this projection.
function SiloSeekRouteProof(route as Dynamic) as Boolean
    if not SpFields(route,["source","recipe","subtitle","delivery","requested_media_file_id","effective_media_file_id","protocol"],["container","mime_type","header_refresh","claims","transformations","applied_quirks","runtime_corrections","subtitle_fidelity_policy"]) then return false
    if Len(FormatJson(route)) > 16384 then return false
    if not SpFields(route.subtitle,["mode"],["track_id","embedded","format","mime_type"]) then return false
    raw = {source:route.source,effective_recipe:route.recipe,subtitle:SpCopy(route.subtitle),stream:{url:"",protocol:route.protocol}}
    for each key in ["container","mime_type","header_refresh"]
        if route.DoesExist(key) then raw.stream[key] = route[key]
    end for
    if route.subtitle.DoesExist("format") or route.subtitle.DoesExist("mime_type")
        if not route.subtitle.DoesExist("format") or not route.subtitle.DoesExist("mime_type") then return false
        raw.subtitle["artifact"] = {url:"",format:route.subtitle.format,mime_type:route.subtitle.mime_type,timing_origin_seconds:0}
        raw.subtitle.Delete("format"):raw.subtitle.Delete("mime_type")
    end if
    for each key in ["delivery","requested_media_file_id","effective_media_file_id","claims","transformations","applied_quirks","runtime_corrections","subtitle_fidelity_policy"]
        if route.DoesExist(key) then raw[key] = SpCopy(route[key])
    end for
    canonical = SiloSeekRoute(raw)
    if canonical = invalid then return false
    return SiloSeekEqual(route,canonical)
end function

' Presentation only. Rebuild from bounded enums; never retain arbitrary DTO keys.
function SiloStartRequestFacts(raw as Dynamic) as Dynamic
    if not SiloObject(raw) then return invalid
    safe = {}
    enums = {quality:["unknown","auto","original","2160p","1080p","720p","480p"],selection:["auto","manual"],videoCodec:["unknown","h264","hevc","av1","vp9","mpeg2","mpeg4"],audioCodec:["unknown","aac","ac3","eac3","truehd","dts","flac","opus","mp3","pcm"],hdr10:["unknown","yes","no"],dolbyVision:["unknown","yes","no"]}
    for each key in enums
        value = SpField(raw,key)
        if not SiloContains(enums[key],value) then return invalid
        safe[key] = value
    end for
    for each key in ["mpegts","separateAudio","dv7To81","hevcAdmitted","hlsEnabled","hlsSupported","originalEnabled","originalSupported"]
        value = SpField(raw,key)
        if not SpBool(value) then return invalid
        safe[key] = value
    end for
    if raw.DoesExist("copyMpegts")
        if not SpBool(raw.copyMpegts) then return invalid
        safe["copyMpegts"] = raw.copyMpegts
    end if
    if raw.DoesExist("hlsHevcAdmitted")
        if not SpBool(raw.hlsHevcAdmitted) then return invalid
        safe["hlsHevcAdmitted"] = raw.hlsHevcAdmitted
    end if
    for each key in ["width","height","dvProfile","dvBaseCompatibility"]
        value = SpField(raw,key)
        limit = 16384
        if key = "dvProfile" or key = "dvBaseCompatibility" then limit = 15
        if value <> invalid
            if not SpNumber(value,limit,true) then return invalid
            safe[key] = value
        end if
    end for
    return safe
end function

function SiloStartValidationFacts(stage as Dynamic, reason as Dynamic) as Dynamic
    allowed = {audio_selection:["audio_mismatch"],media_auth:["invalid_media_auth"],plan_context:["invalid_plan_context"],original_receipt:["receipt_audio","receipt_delivery","receipt_file","receipt_owner","receipt_proof","receipt_quality","receipt_recipe","receipt_session","receipt_source","receipt_subtitle","receipt_subtitle_invalid","receipt_subtitle_delivery","receipt_subtitle_codec","receipt_subtitle_clock","receipt_subtitle_selection","receipt_transformations"]}
    if type(stage) <> "String" and type(stage) <> "roString" then return invalid
    if not allowed.DoesExist(stage) then return invalid
    if not SiloContains(allowed[stage],reason) then reason = "unavailable"
    return {validationStage:stage,validationReason:reason}
end function

function SiloStartAttempts(raw as Dynamic) as Object
    safe = []
    if not SiloArray(raw) then return safe
    for each entry in raw
        request = SiloStartRequestFacts(SpField(entry,"request"))
        status = SpField(entry,"httpStatus")
        outcome = SpField(entry,"outcome")
        if request <> invalid and SpNumber(status,599,true) and SiloContains(["plan","playable","terminal","adaptation_unavailable","other","missing","null","invalid"],outcome)
            if status >= 100
                reason = SpField(entry,"originalReason")
                reasons = ["not_checked","unavailable","eligible","qualified_route_not_enabled","native_copy_preferred","base_unproven","decoder_unproven","device_unqualified","enhancement_layer_unqualified","output_unqualified","source_unqualified","stale_evidence","video_dimensions","video_frame_rate","video_inventory","video_unqualified","attempt_identity","audio_ambiguous","audio_identity","audio_index_convention","audio_inventory","audio_language","audio_role_unknown","audio_unsupported","bandwidth_intent","bitrate_unknown","explicit_audio_required","explicit_audio_unsupported","file_identity","preferred_audio_unqualified","quality_intent","scope_identity","source_identity","subtitle_intent"]
                if not SiloContains(reasons,reason) then reason = "unavailable"
                row = {request:request,httpStatus:status,outcome:outcome,originalReason:reason}
                validation = SiloStartValidationFacts(SpField(entry,"validationStage"),SpField(entry,"validationReason"))
                if validation <> invalid
                    row["validationStage"] = validation.validationStage
                    row["validationReason"] = validation.validationReason
                end if
                safe.Push(row)
                if safe.Count() > 8 then safe.Delete(1)
            end if
        end if
    end for
    return safe
end function
