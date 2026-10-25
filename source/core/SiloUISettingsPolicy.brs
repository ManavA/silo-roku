' Only neutral, compact display choices may enter the preferences registry.
function SiloUISettingsPreferences(raw as Dynamic) as Object
    out = {quality: "original", subtitles: "off"}
    if type(raw) <> "roAssociativeArray" then return out
    for each quality in ["original", "1080p", "720p", "480p"]
        if raw.quality = quality then out.quality = quality
    end for
    for each mode in ["off", "on", "forced", "auto", "always"]
        if raw.subtitles = mode then out.subtitles = mode
    end for
    for each setting in ["showForced", "preferSdh", "autoPlayNext", "autoSkipIntro", "autoSkipRecap", "autoSkipCredits"]
        if type(raw[setting]) = "Boolean" or type(raw[setting]) = "roBoolean" then out[setting] = raw[setting]
    end for
    for each mode in ["never", "ask", "always"]
        if raw.introSkipMode = mode then out["introSkipMode"] = mode : out["autoSkipIntro"] = mode = "always"
    end for
    for each setting in ["promptSeconds", "stillWatching"]
        value = raw[setting]
        maximum = 120
        if setting = "stillWatching" then maximum = 20
        if type(value) = "Integer" or type(value) = "roInt" or type(value) = "roInteger" or type(value) = "LongInteger" or type(value) = "roLongInteger"
            if value >= 0 and value <= maximum then out[setting] = value
        end if
    end for
    if type(raw.subtitleLanguage) = "String" or type(raw.subtitleLanguage) = "roString"
        if CreateObject("roRegex", "^[a-zA-Z]{2,3}(-[a-zA-Z]{2})?$", "").IsMatch(raw.subtitleLanguage) or raw.subtitleLanguage = "" then out["subtitleLanguage"] = LCase(raw.subtitleLanguage)
    end if
    return out
end function

' Inventory is normalized by TrackPreferenceInventory. Forced never falls back
' to a full subtitle lane; the empty ID means captions remain disabled.
function SiloUISettingsSubtitle(mode as String, tracks as Dynamic) as String
    if mode = "off" or type(tracks) <> "roArray" then return ""
    for each track in tracks
        if type(track) = "roAssociativeArray"
            if type(track.trackId) = "roString" or type(track.trackId) = "String"
                if mode = "on" then return track.trackId
                label = track.name
                if label = invalid then label = track.label
                if type(label) <> "roString" and type(label) <> "String" then label = ""
                tokens = CreateObject("roRegex", "[^a-z0-9]+", "").ReplaceAll(LCase(label), " ")
                if mode = "forced" and (track.forced = true or Instr(1, " " + tokens.Trim() + " ", " forced ") > 0) then return track.trackId
            end if
        end if
    end for
    return ""
end function

function SiloUISettingsPlayback(provider as String, raw as Dynamic) as Object
    quality = SiloUISettingsPreferences(raw).quality
    params = {qualityPreference: quality}
    if provider = "plex"
        if quality = "1080p" then params["maxVideoBitrate"] = 8000 : params["videoResolution"] = "1920x1080"
        if quality = "720p" then params["maxVideoBitrate"] = 4000 : params["videoResolution"] = "1280x720"
    end if
    return params
end function

' Unknown output modes retain the user's default; only a known HD mode caps 4K.
function SiloUISpeedQuality(provider as String, quality as String, explicit as Boolean, resolution as String, mode as String) as String
    if provider <> "silo" or explicit or quality <> "original" then return quality
    resolution = LCase(resolution)
    if resolution <> "2160p" and resolution <> "4k" and resolution <> "3840x2160" then return quality
    mode = LCase(mode)
    if Left(mode, 5) = "1080p" or Left(mode, 5) = "1080i" then return "1080p"
    if Left(mode, 4) = "720p" then return "720p"
    if Left(mode, 4) = "480p" or Left(mode, 4) = "480i" then return "720p"
    return quality
end function

function SiloUISpeedHero(rows as Dynamic, itemId as String, view as String, zone as String) as Boolean
    if view <> "home" or zone <> "heroButtons" or itemId = "" or type(rows) <> "roArray" then return false
    for each row in rows
        if row.sectionType = "continue_watching" and type(row.items) = "roArray"
            if row.items.Count() > 0 then return row.items[0].itemId = itemId
        end if
    end for
    return false
end function

' Canonical remote keys only. UI appearance, navigation, SDH and passout count
' are device choices and never enter settings-values requests.
function SiloUISettingsRemote() as Object
    return {"autoSkipIntro":"playback.auto_skip_intro","autoSkipRecap":"playback.auto_skip_recap","autoSkipCredits":"playback.auto_skip_credits","introSkipMode":"playback.intro_skip_mode",quality:"playback.preferred_quality",subtitles:"playback.subtitle_mode","subtitleLanguage":"playback.subtitle_language","showForced":"playback.show_forced_subtitles","autoPlayNext":"playback.auto_play_next","promptSeconds":"playback.next_up_prompt_seconds"}
end function

function SiloUISettingsKeys(manifest as Dynamic, revision as Integer) as Object
    keys = []
    if type(manifest) <> "roAssociativeArray" then return keys
    if type(manifest.definitions) <> "roArray" then return keys
    known = SiloUISettingsRemote()
    for each definition in manifest.definitions
        if type(definition) = "roAssociativeArray"
            if type(definition.introduced_in) = "Integer" or type(definition.introduced_in) = "roInt" or type(definition.introduced_in) = "roInteger" or type(definition.introduced_in) = "LongInteger" or type(definition.introduced_in) = "roLongInteger"
                if definition.introduced_in <= revision and definition.persistence = "remote"
                    for each setting in known
                        if definition.key = known[setting] then keys.Push(definition.key)
                    end for
                end if
            end if
        end if
    end for
    return keys
end function

function SiloUISettingsEffective(local as Dynamic, response as Dynamic) as Object
    out = SiloUISettingsPreferences(local)
    if type(response) <> "roAssociativeArray" then return out
    if type(response.items) <> "roArray" then return out
    known = SiloUISettingsRemote()
    for each row in response.items
        if type(row) = "roAssociativeArray"
            for each setting in known
                if row.key = known[setting]
                    out[setting] = row.value
                    if setting = "quality" and row.value <> "1080p" and row.value <> "720p" and row.value <> "480p" then out.quality = "original"
                end if
            end for
        end if
    end for
    return SiloUISettingsPreferences(out)
end function

function SiloUISettingsLanguage(value as Dynamic) as String
    if type(value) <> "String" and type(value) <> "roString" then return ""
    value = LCase(value)
    separator = Instr(1,value,"-")
    if separator > 1 then value = Left(value,separator - 1)
    aliases = {en:"eng",fr:"fra",fre:"fra",es:"spa",de:"deu",ger:"deu",it:"ita",ja:"jpn",ko:"kor",zh:"zho",chi:"zho",pt:"por"}
    if aliases.DoesExist(value) then return aliases[value]
    return value
end function

' Explicit native selection is session-local and outranks all defaults.
' Auto enables full captions when audio differs from the preferred language;
' matching or unknown audio uses only a forced lane. Always prefers full lanes.
function SiloUISettingsSelectSubtitle(raw as Dynamic, tracks as Dynamic, audioLanguage as String, explicit = "" as String) as String
    if explicit = "off" then return ""
    if type(tracks) <> "roArray" then return ""
    if explicit <> ""
        for each track in tracks
            if track.trackId = explicit then return explicit
        end for
        return ""
    end if
    prefs = SiloUISettingsPreferences(raw)
    mode = prefs.subtitles
    if mode = "off" and prefs.showForced <> true then return ""
    language = SiloUISettingsLanguage(prefs.subtitleLanguage)
    forcedOnly = mode = "forced" or mode = "off"
    if mode = "auto" then forcedOnly = language = "" or audioLanguage = "" or SiloUISettingsLanguage(audioLanguage) = language
    best = ""
    bestScore = -1000
    inspected = 0
    for each track in tracks
        inspected++
        if inspected > 64 then exit for
        if type(track) = "roAssociativeArray"
            if type(track.trackId) = "String" or type(track.trackId) = "roString"
                label = track.name
                if label = invalid then label = track.label
                if type(label) <> "String" and type(label) <> "roString" then label = ""
                tokens = " " + CreateObject("roRegex", "[^a-z0-9]+", "").ReplaceAll(LCase(label), " ").Trim() + " "
                forced = track.forced = true or Instr(1,tokens," forced ") > 0
                sdh = track.caption = true or track.descriptive = true or Instr(1,tokens," sdh ") > 0 or Instr(1,tokens," cc ") > 0
                matches = language = "" or SiloUISettingsLanguage(track.language) = language
                if forced and prefs.showForced = false then matches = false
                if matches and (not forcedOnly or (forced and prefs.showForced <> false))
                    score = 0
                    if not forced then score = score + 20
                    if sdh = (prefs.preferSdh = true) then score = score + 10
                    if score > bestScore then best = track.trackId : bestScore = score
                end if
            end if
        end if
    end for
    return best
end function

function SiloUISettingsCanWrite(manifest as Dynamic, revision as Integer, key as String, scope as String) as Boolean
    keys = SiloUISettingsKeys(manifest, revision)
    found = false
    for each candidate in keys
        if candidate = key then found = true
    end for
    if not found then return false
    for each definition in manifest.definitions
        if type(definition) = "roAssociativeArray"
            if definition.key = key and type(definition.allowed_scopes) = "roArray"
                for each allowed in definition.allowed_scopes
                    if allowed = scope then return true
                end for
            end if
        end if
    end for
    return false
end function

function SiloUISettingsBinge(raw as Dynamic, advances as Integer) as Object
    prefs = SiloUISettingsPreferences(raw)
    seconds = 10
    threshold = 3
    if prefs.promptSeconds <> invalid then seconds = prefs.promptSeconds
    if prefs.stillWatching <> invalid then threshold = prefs.stillWatching
    return {autoplay:prefs.autoPlayNext <> false,seconds:seconds,ask:threshold > 0 and advances >= threshold}
end function

' Defaults (including policy-constrained defaults) are not a user pin. A
' remote authored row must identify the actual winning scope before it pins.
function SiloUISettingsAuthoredQuality(row as Object) as Boolean
    known = false
    for each scope in ["account", "profile", "profile_device", "profile_client", "profile_library", "profile_series"]
        if row.source = scope and row.scope = scope then known = true
    end for
    if not known then return false
    return row.value = "original" or row.value = "1080p" or row.value = "720p" or row.value = "480p"
end function

function SiloUISettingsCacheGet(rows as Dynamic, sourceId as String, profileId as String) as Dynamic
    if type(rows) <> "roArray" then return invalid
    inspected = 0
    for each row in rows
        inspected++
        if inspected > 4 then exit for
        if type(row) = "roAssociativeArray"
            if row.sourceId = sourceId and row.profileId = profileId
                prefs = SiloUISettingsPreferences(row.preferences)
                prefs["qualityExplicit"] = row.qualityExplicit = true
                return prefs
            end if
        end if
    end for
    return invalid
end function

' Four recent source/profile snapshots fit the compact preferences budget;
' identity bounds prevent long URLs from consuming the encrypted registry.
function SiloUISettingsCachePut(rows as Dynamic, sourceId as String, profileId as String, prefs as Dynamic, explicit as Boolean) as Object
    out = []
    if Len(sourceId) > 512 or Len(profileId) > 128 then return out
    out.Push({sourceId:sourceId,profileId:profileId,preferences:SiloUISettingsPreferences(prefs),qualityExplicit:explicit})
    if type(rows) <> "roArray" then return out
    inspected = 0
    for each row in rows
        inspected++
        if inspected > 4 or out.Count() >= 4 then exit for
        if type(row) = "roAssociativeArray"
            if type(row.sourceId) = "String" or type(row.sourceId) = "roString"
                if type(row.profileId) = "String" or type(row.profileId) = "roString"
                    if Len(row.sourceId) <= 512 and Len(row.profileId) <= 128 and (row.sourceId <> sourceId or row.profileId <> profileId)
                        out.Push({sourceId:row.sourceId,profileId:row.profileId,preferences:SiloUISettingsPreferences(row.preferences),qualityExplicit:row.qualityExplicit=true})
                    end if
                end if
            end if
        end if
    end for
    return out
end function
