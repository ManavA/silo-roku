' Request-local stock audio selection evidence. No SDK, transport or gate calls.
function SiloAutoAudioFacts(raw as Dynamic) as Dynamic
    if type(raw) <> "roAssociativeArray" then return invalid
    seen = {}
    for each name in raw
        key = LCase(name)
        if seen.DoesExist(key) then return invalid
        seen[key] = true
    end for
    fileId = SpField(raw,"file_id")
    if not SpText(fileId,20) then return invalid
    if not CreateObject("roRegex","^[1-9][0-9]{0,19}$","").IsMatch(fileId) then return invalid
    if Len(fileId) = 20 and fileId > "18446744073709551615" then return invalid
    tracks = SpField(raw,"audio_tracks")
    if type(tracks) <> "roArray" then return invalid
    if tracks.Count() = 0 or tracks.Count() > 32 then return invalid
    facts = {schema:"stock_48ae_audio_v1",file_id:fileId,tracks:[],effective_preference:{state:"absent"},preferred_ordinal:0,equivalence:"published_language_title_inference"}
    foundDefault = false
    for ordinal = 0 to tracks.Count()-1
        track = tracks[ordinal]
        if type(track) <> "roAssociativeArray" then return invalid
        fields = {}
        for each name in track
            key = LCase(name)
            if fields.DoesExist(key) then return invalid
            fields[key] = true
        end for
        ' This stock schema does not publish audio role flags or wire indices.
        ' A present flag needs a separately reviewed schema, never coercion.
        for each name in ["index","hearing_impaired","forced","external"]
            if fields.DoesExist(name) then return invalid
        end for
        codec = SpField(track,"codec"):channels = SpField(track,"channels")
        layout = SpField(track,"layout"):isDefault = SpField(track,"default")
        if not SpText(codec,32) or not SpText(layout,32) or not SpBool(isDefault) then return invalid
        if not SpNumber(channels,8,true) or channels = 0 then return invalid
        language = SpField(track,"language","")
        title = SpField(track,"title",""):embedded = SpField(track,"embedded_title","")
        if not SpText(language,32,true) or not SpText(title,128,true) or not SpText(embedded,128,true) then return invalid
        row = {source_ordinal:ordinal,id:"file:"+fileId+":audio:"+ordinal.ToStr(),codec:LCase(codec),channels:channels,layout:layout,default:isDefault,language:SoLanguage(language),source_language:language,title:title,title_present:fields.DoesExist("title"),embedded_title:embedded,embedded_title_present:fields.DoesExist("embedded_title"),role:SoAudioRole(track),hearing_impaired:{state:"schema_unpublished",value:invalid}}
        facts.tracks.Push(row)
        if isDefault and not foundDefault then facts.preferred_ordinal = ordinal:foundDefault = true
    end for
    if seen.DoesExist("effective_audio_track_index")
        effective = SpField(raw,"effective_audio_track_index")
        if not SpNumber(effective,tracks.Count()-1,true) then return invalid
        facts.effective_preference = {state:"present",ordinal:effective}
        facts.preferred_ordinal = effective
    end if
    return facts
end function

' Exact MP4 query answers are supplied by the caller, never queried or cached
' here. Native preference remains the caller's independently proven decision.
function SiloAutoAudioChoose(facts as Dynamic, queries as Dynamic) as Dynamic
    if not SpFields(facts,["schema","file_id","tracks","effective_preference","preferred_ordinal","equivalence"],[]) then return invalid
    if type(facts.tracks) <> "roArray" or type(queries) <> "roArray" then return invalid
    if facts.tracks.Count() = 0 or facts.tracks.Count() > 32 or queries.Count() <> facts.tracks.Count() then return invalid
    if not SpNumber(facts.preferred_ordinal,facts.tracks.Count()-1,true) then return invalid
    ' Reconstruct only the published selection fields to verify the supplied
    ' projection, including title presence, defaults, role and unknown HI.
    raw = {file_id:facts.file_id,audio_tracks:[]}
    for each track in facts.tracks
        if not SpFields(track,["source_ordinal","id","codec","channels","layout","default","language","source_language","title","title_present","embedded_title","embedded_title_present","role","hearing_impaired"],[]) then return invalid
        if not SpBool(track.title_present) or not SpBool(track.embedded_title_present) then return invalid
        if not SpFields(track.hearing_impaired,["state","value"],[]) then return invalid
        if track.hearing_impaired.state <> "schema_unpublished" or track.hearing_impaired.value <> invalid then return invalid
        source = {codec:track.codec,channels:track.channels,layout:track.layout,default:track.default,language:track.source_language}
        if track.title_present then source["title"] = track.title
        if track.embedded_title_present then source["embedded_title"] = track.embedded_title
        raw.audio_tracks.Push(source)
    end for
    preference = facts.effective_preference
    if not SpFields(preference,["state"],["ordinal"]) then return invalid
    if preference.state = "present"
        if not preference.DoesExist("ordinal") then return invalid
        raw["effective_audio_track_index"] = preference.ordinal
    else if preference.state <> "absent" or preference.DoesExist("ordinal")
        return invalid
    end if
    verified = SiloAutoAudioFacts(raw)
    if verified = invalid then return invalid
    if FormatJson(verified) <> FormatJson(facts) then return invalid
    for ordinal = 0 to queries.Count()-1
        query = queries[ordinal]:track = facts.tracks[ordinal]
        if not SpFields(query,["source_ordinal","codec","channels","container","decode","passthrough"],[]) then return invalid
        if not SpNumber(query.source_ordinal,31,true) or not SpNumber(query.channels,8,true) then return invalid
        if not SpText(query.codec,32) or not SpText(query.container,8) then return invalid
        if query.source_ordinal <> ordinal or query.codec <> track.codec or query.channels <> track.channels or query.container <> "mp4" then return invalid
        if query.decode <> invalid then if not SpBool(query.decode) then return invalid
        if query.passthrough <> invalid then if not SpBool(query.passthrough) then return invalid
    end for
    preferred = facts.preferred_ordinal:query = queries[preferred]
    chosen = preferred:selection = "preferred"
    if query.decode <> true and query.passthrough <> true
        ' Unknown preferred support is not evidence of inability to play it.
        if query.decode <> false or query.passthrough <> false then return invalid
        preferredTrack = facts.tracks[preferred]
        if preferredTrack.language = "" or preferredTrack.role = "unknown" then return invalid
        chosen = -1:selection = "equivalent_fallback"
        for ordinal = 0 to facts.tracks.Count()-1
            track = facts.tracks[ordinal]:query = queries[ordinal]
            if track.codec = "ac3" and track.channels = 6 and track.language = preferredTrack.language and track.role = preferredTrack.role
                if query.decode = true or query.passthrough = true
                    if chosen >= 0 then return invalid
                    chosen = ordinal
                end if
            end if
        end for
        if chosen < 0 then return invalid
    end if
    track = facts.tracks[chosen]
    return {mode:"auto",selection:selection,file_id:facts.file_id,audio_track_id:track.id,audio_track_index:chosen,preferred_ordinal:preferred,equivalence:facts.equivalence,basis:SpCopy(facts),queries:SpCopy(queries)}
end function

' Conversion is a separate last-resort choice. It is valid only when every
' source audio lane is freshly and explicitly false for MP4 decode/copy.
function SiloAutoAudioAACConversion(facts as Dynamic, queries as Dynamic) as Dynamic
    if not SpFields(facts,["schema","file_id","tracks","effective_preference","preferred_ordinal","equivalence"],[]) then return invalid
    if type(facts.tracks) <> "roArray" or type(queries) <> "roArray" then return invalid
    if facts.tracks.Count() = 0 or facts.tracks.Count() > 32 or queries.Count() <> facts.tracks.Count() then return invalid
    if not SpNumber(facts.preferred_ordinal,facts.tracks.Count()-1,true) then return invalid
    raw = {file_id:facts.file_id,audio_tracks:[]}
    for each track in facts.tracks
        if not SpFields(track,["source_ordinal","id","codec","channels","layout","default","language","source_language","title","title_present","embedded_title","embedded_title_present","role","hearing_impaired"],[]) then return invalid
        if not SpBool(track.title_present) or not SpBool(track.embedded_title_present) then return invalid
        if not SpFields(track.hearing_impaired,["state","value"],[]) or track.hearing_impaired.state <> "schema_unpublished" or track.hearing_impaired.value <> invalid then return invalid
        source = {codec:track.codec,channels:track.channels,layout:track.layout,default:track.default,language:track.source_language}
        if track.title_present then source["title"] = track.title
        if track.embedded_title_present then source["embedded_title"] = track.embedded_title
        raw.audio_tracks.Push(source)
    end for
    preference = facts.effective_preference
    if not SpFields(preference,["state"],["ordinal"]) then return invalid
    if preference.state = "present"
        if not preference.DoesExist("ordinal") then return invalid
        raw["effective_audio_track_index"] = preference.ordinal
    else if preference.state <> "absent" or preference.DoesExist("ordinal")
        return invalid
    end if
    verified = SiloAutoAudioFacts(raw)
    if verified = invalid or FormatJson(verified) <> FormatJson(facts) then return invalid
    for ordinal = 0 to queries.Count()-1
        query = queries[ordinal]:track = facts.tracks[ordinal]
        if not SpFields(query,["source_ordinal","codec","channels","container","decode","passthrough"],[]) then return invalid
        if not SpNumber(query.source_ordinal,31,true) or query.source_ordinal <> ordinal then return invalid
        if not SpText(query.codec,32) or not SpNumber(query.channels,8,true) then return invalid
        if query.codec <> track.codec or query.channels <> track.channels or query.container <> "mp4" then return invalid
        if query.decode <> false or query.passthrough <> false then return invalid
    end for
    preferred = facts.preferred_ordinal:track = facts.tracks[preferred]
    return {mode:"auto",selection:"aac_conversion",file_id:facts.file_id,audio_track_id:track.id,audio_track_index:preferred,preferred_ordinal:preferred,equivalence:facts.equivalence,basis:SpCopy(facts),queries:SpCopy(queries)}
end function
