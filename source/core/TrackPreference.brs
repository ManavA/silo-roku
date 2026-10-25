' Source/profile preferences exclude native IDs, URLs and tokens.
' Apply results only to the current Video/plan; wait for inventory after refusal
' and restore the captured global caption mode. Transient IDs may be subtitle
' URIs: never log or persist them.
function TrackPreferenceNormalize(raw as Dynamic, scope as Dynamic) as Dynamic
    active = TrackPreferenceScope(scope)
    if active = invalid then return invalid
    result = {schemaVersion:1,sourceId:active.sourceId,profileId:active.profileId,subtitleMode:"auto",subtitleLanguage:"eng",subtitleName:"",audioLanguage:"",audioName:""}
    if type(raw) <> "roAssociativeArray" then return result
    if TrackPreferenceField(raw,"sourceId",invalid) <> active.sourceId or TrackPreferenceField(raw,"profileId",invalid) <> active.profileId then return result
    mode = TrackPreferenceField(raw,"subtitleMode","auto")
    if mode = "off" or mode = "on" then result["subtitleMode"] = mode
    result["subtitleLanguage"] = TrackPreferenceLanguage(TrackPreferenceField(raw,"subtitleLanguage","eng"))
    result["subtitleName"] = TrackPreferenceName(TrackPreferenceField(raw,"subtitleName",""))
    result["audioLanguage"] = TrackPreferenceLanguage(TrackPreferenceField(raw,"audioLanguage",""))
    result["audioName"] = TrackPreferenceName(TrackPreferenceField(raw,"audioName",""))
    return result
end function

function TrackPreferenceSetMode(raw as Dynamic, scope as Dynamic, mode as String) as Dynamic
    if mode <> "auto" and mode <> "off" and mode <> "on" then return invalid
    result = TrackPreferenceNormalize(raw,scope)
    if result = invalid then return invalid
    result["subtitleMode"] = mode
    if mode = "auto"
        result["subtitleLanguage"] = "eng"
        result["subtitleName"] = ""
    end if
    return result
end function

' Only a choice found in this playback's native inventory can be remembered.
' Persist the language/name, since a runtime ID is not stable across titles.
function TrackPreferenceRemember(raw as Dynamic, scope as Dynamic, kind as String, trackId as String, tracks as Dynamic) as Dynamic
    if kind <> "subtitle" and kind <> "audio" then return invalid
    result = TrackPreferenceNormalize(raw,scope)
    if result = invalid then return invalid
    if trackId = ""
        if kind = "subtitle" then return TrackPreferenceSetMode(result,scope,"off")
        result["audioLanguage"] = ""
        result["audioName"] = ""
        return result
    end if
    inventory = TrackPreferenceInventory(tracks,kind)
    if inventory = invalid then return invalid
    for each track in inventory
        if track.trackId = trackId
            if kind = "subtitle"
                result["subtitleMode"] = "on"
                result["subtitleLanguage"] = track.language
                result["subtitleName"] = track.name
            else
                result["audioLanguage"] = track.language
                result["audioName"] = track.name
            end if
            return result
        end if
    end for
    return invalid
end function

' Invalid means defer/no field write. Default audio remains Roku's choice.
' Off changes caption visibility, rather than claiming an empty subtitle ID clears
' a native lane. On and Auto need a matching lane before captions are enabled.
function TrackPreferenceResolve(raw as Dynamic, scope as Dynamic, kind as String, tracks as Dynamic) as Dynamic
    if kind <> "subtitle" and kind <> "audio" then return invalid
    preference = TrackPreferenceNormalize(raw,scope)
    if preference = invalid then return invalid
    inventory = TrackPreferenceInventory(tracks,kind)
    if inventory = invalid then return invalid
    if kind = "subtitle" and preference.subtitleMode = "off"
        return {kind:"subtitle",trackId:"",captionMode:"Off",reason:"explicit_off"}
    end if
    wantedLanguage = preference.audioLanguage
    wantedName = preference.audioName
    if kind = "subtitle"
        wantedLanguage = preference.subtitleLanguage
        wantedName = preference.subtitleName
        if preference.subtitleMode = "auto"
            wantedLanguage = ""
            wantedName = ""
        end if
    end if
    selected = invalid
    reason = ""
    if wantedName <> ""
        wantedName = LCase(wantedName)
        for each track in inventory
            if LCase(track.name) = wantedName and (wantedLanguage = "" or track.language = wantedLanguage)
                selected = track
                reason = "explicit_name"
                exit for
            end if
        end for
    end if
    if selected = invalid and wantedLanguage <> ""
        bestScore = -10000
        for each track in inventory
            if track.language = wantedLanguage
                score = TrackPreferenceLaneScore(track,kind,wantedName)
                if score > bestScore
                    selected = track
                    bestScore = score
                    reason = "explicit_language"
                end if
            end if
        end for
    end if
    if selected = invalid and kind = "subtitle"
        bestScore = -10000
        for each track in inventory
            english = track.language = "eng" or Left(track.language,4) = "eng-"
            if track.language = "" or track.language = "und"
                english = TrackPreferenceHasToken(track.name,"english") or TrackPreferenceHasToken(track.name,"eng") or TrackPreferenceHasToken(track.name,"en")
            end if
            if english
                score = TrackPreferenceLaneScore(track,"subtitle",wantedName)
                if score > bestScore
                    selected = track
                    bestScore = score
                    reason = "auto_english"
                end if
            end if
        end for
    end if
    if selected = invalid then return invalid
    result = {kind:kind,trackId:selected.trackId,reason:reason}
    if kind = "subtitle" then result["captionMode"] = "On"
    return result
end function

' Inspect at most 64 native entries, retaining only documented descriptive fields
' and the transient ID used to select this inventory's track. No codec claim is
' made from the existence of a track or its label.
function TrackPreferenceInventory(tracks as Dynamic, kind as String) as Dynamic
    if type(tracks) <> "roArray" then return invalid
    result = []
    seen = {}
    inspected = 0
    for each raw in tracks
        inspected++
        if inspected > 64 then exit for
        if type(raw) = "roAssociativeArray"
            idField = "TrackName"
            nameField = "Description"
            if kind = "audio"
                idField = "Track"
                nameField = "Name"
            end if
            trackId = TrackPreferenceField(raw,idField,invalid)
            if type(trackId) = "String" or type(trackId) = "roString"
                if Len(trackId) > 0 and Len(trackId) <= 1024 and not seen.DoesExist(trackId)
                    seen[trackId] = true
                    caption = TrackPreferenceField(raw,"HasAccessibilityCaption",false) = true
                    descriptive = TrackPreferenceField(raw,"HasAccessibilityDescription",false) = true
                    result.Push({trackId:trackId,language:TrackPreferenceLanguage(TrackPreferenceField(raw,"Language","")),name:TrackPreferenceName(TrackPreferenceField(raw,nameField,"")),caption:caption,descriptive:descriptive})
                end if
            end if
        end if
    end for
    if result.Count() = 0 then return invalid
    return result
end function

' A remembered lane's SDH/CC and forced tokens survive label changes between
' titles. An empty preferred name keeps Auto's full, unforced subtitle default.
function TrackPreferenceLaneScore(track as Object, kind as String, preferredName as String) as Integer
    score = 100
    if kind = "subtitle"
        sdh = track.caption or track.descriptive or TrackPreferenceHasToken(track.name,"sdh") or TrackPreferenceHasToken(track.name,"cc")
        wantedSdh = TrackPreferenceHasToken(preferredName,"sdh") or TrackPreferenceHasToken(preferredName,"cc")
        wantedForced = TrackPreferenceHasToken(preferredName,"forced")
        if sdh = wantedSdh then score = score + 12
        if TrackPreferenceHasToken(track.name,"forced") = wantedForced then score = score + 8
    else
        if track.descriptive then score = score - 40
    end if
    if TrackPreferenceHasToken(track.name,"commentary") then score = score - 80
    return score
end function

function TrackPreferenceHasToken(value as String, token as String) as Boolean
    normalized = CreateObject("roRegex","[^a-z0-9]+","").ReplaceAll(LCase(value)," ")
    return Instr(1," " + normalized.Trim() + " "," " + token + " ") > 0
end function

' Normalize only complete aliases. Region tags remain exact, never prefix-matched.
function TrackPreferenceLanguage(value as Dynamic) as String
    if type(value) <> "String" and type(value) <> "roString" then return ""
    language = LCase(value.Trim())
    if Len(language) > 24 then return ""
    aliases = {en:"eng",english:"eng",fr:"fra",fre:"fra",french:"fra",de:"deu",ger:"deu",german:"deu",es:"spa",spanish:"spa",ja:"jpn",japanese:"jpn",ko:"kor",korean:"kor",pt:"por",portuguese:"por",zh:"zho",chi:"zho",chinese:"zho",it:"ita",italian:"ita",ar:"ara",arabic:"ara",ru:"rus",russian:"rus",hi:"hin",hindi:"hin"}
    if aliases.DoesExist(language) then return aliases[language]
    if not CreateObject("roRegex","^[a-z]{2,3}(-[a-z0-9]{2,8}){0,2}$","").IsMatch(language) then return ""
    separator = Instr(1,language,"-")
    if separator > 0
        base = Left(language,separator - 1)
        if aliases.DoesExist(base) then return aliases[base] + Mid(language,separator)
    end if
    return language
end function

function TrackPreferenceName(value as Dynamic) as String
    if type(value) <> "String" and type(value) <> "roString" then return ""
    name = value.Trim()
    if Len(name) > 96 then return ""
    if CreateObject("roRegex","[\x00-\x1f\x7f]","").IsMatch(name) then return ""
    for each marker in ["://","?","@","=","token","authorization","password","bearer","cookie"]
        if Instr(1,LCase(name),marker) > 0 then return ""
    end for
    return name
end function

function TrackPreferenceScope(value as Dynamic) as Dynamic
    if type(value) <> "roAssociativeArray" then return invalid
    sourceId = TrackPreferenceField(value,"sourceId",invalid)
    profileId = TrackPreferenceField(value,"profileId",invalid)
    if type(sourceId) <> "String" and type(sourceId) <> "roString" then return invalid
    if type(profileId) <> "String" and type(profileId) <> "roString" then return invalid
    if Len(sourceId) <= 5 or Len(sourceId) > 256 or Len(profileId) > 128 then return invalid
    provider = Left(sourceId,5)
    if provider <> "plex:" and provider <> "silo:" then return invalid
    if provider = "silo:" and profileId = "" then return invalid
    for each text in [sourceId,profileId]
        if CreateObject("roRegex","[\x00-\x20\x7f?@#=]","").IsMatch(text) then return invalid
    end for
    return {sourceId:sourceId,profileId:profileId}
end function

function TrackPreferenceField(value as Dynamic, field as String, fallback as Dynamic) as Dynamic
    if type(value) <> "roAssociativeArray" then return fallback
    if not value.DoesExist(field) or value[field] = invalid then return fallback
    return value[field]
end function
