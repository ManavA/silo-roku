' Scene-only local caption receipt. A Task-private URL is never accepted here.
function SiloUISubtitleLocalUri(uri as Dynamic, format as Dynamic) as Boolean
    if type(uri) <> "String" and type(uri) <> "roString" then return false
    if format <> "vtt" and format <> "srt" then return false
    pattern = "^tmp:/silo-subtitle-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\." + format + "$"
    return CreateObject("roRegex",pattern,"").IsMatch(uri)
end function

function SiloUISubtitleWhole(value as Dynamic, maximum as Integer) as Boolean
    kind = type(value)
    if kind <> "Integer" and kind <> "roInt" and kind <> "roInteger" and kind <> "LongInteger" and kind <> "roLongInteger" and kind <> "Float" and kind <> "roFloat" and kind <> "Double" and kind <> "roDouble" then return false
    if value <> value or value < 0 or value > maximum then return false
    return value = Int(value)
end function

' ISO 639-2 bibliographic codes for Roku ContentNode.SubtitleTracks. The
' two-letter and terminology aliases below come from iso-codes iso_639-2.json.
function SiloUISubtitleLanguage(raw as Dynamic) as String
    if type(raw) <> "String" and type(raw) <> "roString" then return "und"
    code = LCase(raw.Trim())
    if not CreateObject("roRegex","^[a-z]{2,3}$","").IsMatch(code) then return "und"
    data = ""
    if Len(code) = 2
        data += "aa:aar|ab:abk|ae:ave|af:afr|ak:aka|am:amh|an:arg|ar:ara|as:asm|av:ava|"
        data += "ay:aym|az:aze|ba:bak|be:bel|bg:bul|bi:bis|bm:bam|bn:ben|bo:tib|br:bre|"
        data += "bs:bos|ca:cat|ce:che|ch:cha|co:cos|cr:cre|cs:cze|cu:chu|cv:chv|cy:wel|"
        data += "da:dan|de:ger|dv:div|dz:dzo|ee:ewe|el:gre|en:eng|eo:epo|es:spa|et:est|"
        data += "eu:baq|fa:per|ff:ful|fi:fin|fj:fij|fo:fao|fr:fre|fy:fry|ga:gle|gd:gla|"
        data += "gl:glg|gn:grn|gu:guj|gv:glv|ha:hau|he:heb|hi:hin|ho:hmo|hr:hrv|ht:hat|"
        data += "hu:hun|hy:arm|hz:her|ia:ina|id:ind|ie:ile|ig:ibo|ii:iii|ik:ipk|io:ido|"
        data += "is:ice|it:ita|iu:iku|ja:jpn|jv:jav|ka:geo|kg:kon|ki:kik|kj:kua|kk:kaz|"
        data += "kl:kal|km:khm|kn:kan|ko:kor|kr:kau|ks:kas|ku:kur|kv:kom|kw:cor|ky:kir|"
        data += "la:lat|lb:ltz|lg:lug|li:lim|ln:lin|lo:lao|lt:lit|lu:lub|lv:lav|mg:mlg|"
        data += "mh:mah|mi:mao|mk:mac|ml:mal|mn:mon|mr:mar|ms:may|mt:mlt|my:bur|na:nau|"
        data += "nb:nob|nd:nde|ne:nep|ng:ndo|nl:dut|nn:nno|no:nor|nr:nbl|nv:nav|ny:nya|"
        data += "oc:oci|oj:oji|om:orm|or:ori|os:oss|pa:pan|pi:pli|pl:pol|ps:pus|pt:por|"
        data += "qu:que|rm:roh|rn:run|ro:rum|ru:rus|rw:kin|sa:san|sc:srd|sd:snd|se:sme|"
        data += "sg:sag|si:sin|sk:slo|sl:slv|sm:smo|sn:sna|so:som|sq:alb|sr:srp|ss:ssw|"
        data += "st:sot|su:sun|sv:swe|sw:swa|ta:tam|te:tel|tg:tgk|th:tha|ti:tir|tk:tuk|"
        data += "tl:tgl|tn:tsn|to:ton|tr:tur|ts:tso|tt:tat|tw:twi|ty:tah|ug:uig|uk:ukr|"
        data += "ur:urd|uz:uzb|ve:ven|vi:vie|vo:vol|wa:wln|wo:wol|xh:xho|yi:yid|yo:yor|"
        data += "za:zha|zh:chi|zu:zul|"
    else
        data = "bod:tib|ces:cze|cym:wel|deu:ger|ell:gre|eus:baq|fas:per|fra:fre|"
        data += "hye:arm|isl:ice|kat:geo|mkd:mac|mri:mao|msa:may|mya:bur|nld:dut|"
        data += "ron:rum|slk:slo|sqi:alb|zho:chi|"
    end if
    for each pair in data.Tokenize("|")
        if Left(pair,Len(code)) = code then return Right(pair,3)
    end for
    if Len(code) = 3 then return code
    return "und"
end function

function SiloUISubtitleBinding(plan as Dynamic, generation as Dynamic, requestId as Dynamic) as Dynamic
    if type(plan) <> "roAssociativeArray" then return invalid
    if plan.DoesExist("subtitleTransport") then return SiloUISubtitleTransportBinding(plan,generation,requestId)
    if plan.provider <> "silo" then return invalid
    if plan.subtitleMode <> "render" and plan.subtitleMode <> "convert" then return invalid
    selected = plan.selectedSubtitle
    artifact = plan.subtitleArtifact
    context = plan.siloPlayback
    if type(selected) <> "roAssociativeArray" or type(artifact) <> "roAssociativeArray" or type(context) <> "roAssociativeArray" then return invalid
    if selected.kind <> "sidecar_ready" or selected.renderingReady <> true then return invalid
    format = selected.format
    mime = selected.mimeType
    if format = "vtt" and mime <> "text/vtt" then return invalid
    if format = "srt" and mime <> "application/x-subrip" then return invalid
    if not SiloUISubtitleLocalUri(artifact.uri,format) then return invalid
    if artifact.format <> format or artifact.mimeType <> mime then return invalid
    if not SiloUISubtitleWhole(selected.combinedIndex,127) then return invalid
    ordinal = Int(selected.combinedIndex)
    owner = artifact.owner
    if type(owner) <> "roAssociativeArray" then return invalid
    if not SiloUISubtitleWhole(owner.generation,2147483646) or not SiloUISubtitleWhole(owner.requestId,2147483646) then return invalid
    if not SiloUISubtitleWhole(owner.sessionRevision,2147483646) or not SiloUISubtitleWhole(owner.selectedOrdinal,127) then return invalid
    if owner.generation <> generation or owner.requestId <> requestId or owner.selectedOrdinal <> ordinal then return invalid
    if type(owner.fileId) <> "String" and type(owner.fileId) <> "roString" then return invalid
    if owner.fileId = "" or Len(owner.fileId) > 32 then return invalid
    if selected.trackId <> "file:" + owner.fileId + ":subtitle:" + ordinal.ToStr() then return invalid
    if owner.sourceId <> plan.sourceId or owner.sourceId <> context.sourceId then return invalid
    if owner.profileId <> context.profileId then return invalid
    if owner.fileId <> plan.versionId or owner.fileId <> context.fileId then return invalid
    if owner.sessionId <> plan.sessionId or owner.sessionId <> context.sessionId then return invalid
    if owner.sessionRevision <> context.sessionRevision or owner.planAttemptKey <> context.planAttemptKey then return invalid
    if not SiloUISubtitleWhole(owner.timelineOffsetMs,604800000) or not SiloUISubtitleWhole(plan.timelineOffsetMs,604800000) then return invalid
    if owner.timelineOffsetMs <> plan.timelineOffsetMs then return invalid
    if type(artifact.timingOriginSeconds) <> "Integer" and type(artifact.timingOriginSeconds) <> "roInt" and type(artifact.timingOriginSeconds) <> "roInteger" and type(artifact.timingOriginSeconds) <> "Float" and type(artifact.timingOriginSeconds) <> "roFloat" and type(artifact.timingOriginSeconds) <> "Double" and type(artifact.timingOriginSeconds) <> "roDouble" then return invalid
    if artifact.timingOriginSeconds <> artifact.timingOriginSeconds or artifact.timingOriginSeconds < 0 or artifact.timingOriginSeconds > 604800 then return invalid
    language = SiloUISubtitleLanguage(selected.language)
    suffix = Mid(artifact.uri,20,8)
    description = "Source subtitle " + ordinal.ToStr() + " " + suffix
    return {uri:artifact.uri,format:format,language:language,description:description,selectedOrdinal:ordinal,owner:owner}
end function

' The Task publishes a private, owned API media URI only for an opted-in
' header-authenticated attempt. Recheck it in Scene before Video sees either
' the URI or the sole Bearer header. This path never turns the URI into a file.
function SiloUISubtitleTransportBinding(plan as Dynamic, generation as Dynamic, requestId as Dynamic) as Dynamic
    if type(plan) <> "roAssociativeArray" or plan.provider <> "silo" then return invalid
    if plan.subtitleMode <> "render" and plan.subtitleMode <> "convert" then return invalid
    selected = plan.selectedSubtitle:transport = plan.subtitleTransport:context = plan.siloPlayback
    if type(selected) <> "roAssociativeArray" or type(transport) <> "roAssociativeArray" or type(context) <> "roAssociativeArray" then return invalid
    if context.mediaAuthMode <> "api_header_v1" or transport.authMode <> "api_header_v1" then return invalid
    if selected.kind <> "sidecar_pending" or selected.renderingReady <> false then return invalid
    if selected.format <> "vtt" or selected.mimeType <> "text/vtt" then return invalid
    if transport.format <> "vtt" or transport.mimeType <> "text/vtt" then return invalid
    if not SiloUISubtitleWhole(selected.combinedIndex,127) then return invalid
    ordinal = Int(selected.combinedIndex)
    owner = transport.owner
    if type(owner) <> "roAssociativeArray" then return invalid
    if not SiloUISubtitleWhole(owner.generation,2147483646) or not SiloUISubtitleWhole(owner.requestId,2147483646) then return invalid
    if not SiloUISubtitleWhole(owner.sessionRevision,2147483646) or not SiloUISubtitleWhole(owner.selectedOrdinal,127) then return invalid
    if owner.generation <> generation or owner.requestId <> requestId or owner.selectedOrdinal <> ordinal then return invalid
    for each field in ["sourceId","sessionId","planAttemptKey","fileId"]
        value = owner[field]
        if type(value) <> "String" and type(value) <> "roString" then return invalid
        if value = "" or Len(value) > 256 then return invalid
    end for
    if type(owner.profileId) <> "String" and type(owner.profileId) <> "roString" then return invalid
    if Len(owner.profileId) > 256 then return invalid
    if Len(owner.fileId) > 32 or not SiloUISubtitleTransportSegment(owner.fileId) then return invalid
    if selected.trackId <> "file:" + owner.fileId + ":subtitle:" + ordinal.ToStr() then return invalid
    if owner.sourceId <> plan.sourceId or owner.sourceId <> context.sourceId then return invalid
    if owner.profileId <> context.profileId or owner.fileId <> plan.versionId or owner.fileId <> context.fileId then return invalid
    if owner.sessionId <> plan.sessionId or owner.sessionId <> context.sessionId then return invalid
    if not SiloUISubtitleTransportSegment(owner.sessionId) then return invalid
    if owner.sessionRevision <> context.sessionRevision or owner.planAttemptKey <> context.planAttemptKey then return invalid
    if not SiloUISubtitleWhole(owner.timelineOffsetMs,604800000) or not SiloUISubtitleWhole(plan.timelineOffsetMs,604800000) then return invalid
    if owner.timelineOffsetMs <> plan.timelineOffsetMs then return invalid
    if not SiloUISubtitleTransportSeconds(transport.timingOriginSeconds) then return invalid
    if type(selected.language) <> "String" and type(selected.language) <> "roString" then return invalid
    if Len(selected.language) > 16 then return invalid
    if type(transport.apiOrigin) <> "String" and type(transport.apiOrigin) <> "roString" then return invalid
    api = SiloUISubtitleTransportURL(transport.apiOrigin + "/")
    av = SiloUISubtitleTransportURL(plan.url)
    caption = SiloUISubtitleTransportURL(transport.uri)
    if api = invalid or av = invalid or caption = invalid then return invalid
    if api.path <> "/" or transport.apiOrigin <> api.origin then return invalid
    if av.origin <> api.origin or caption.origin <> api.origin then return invalid
    if not SiloUISubtitleTransportAVPath(av.path,owner.sessionId,owner.fileId) then return invalid
    if not SiloUISubtitleTransportCaptionPath(caption.path,owner.sessionId,owner.fileId,ordinal) then return invalid
    headers = plan.headers
    if type(headers) <> "roAssociativeArray" or headers.Count() <> 1 or not headers.DoesExist("Authorization") then return invalid
    bearer = headers.Authorization
    if type(bearer) <> "String" and type(bearer) <> "roString" then return invalid
    if Left(bearer,7) <> "Bearer " or Len(bearer) < 8 or Len(bearer) > 4103 then return invalid
    if CreateObject("roRegex","[\x00-\x20\x7f]","").IsMatch(Mid(bearer,8)) then return invalid
    language = SiloUISubtitleLanguage(selected.language)
    description = "Source subtitle " + ordinal.ToStr() + " g" + Int(owner.generation).ToStr() + " r" + Int(owner.requestId).ToStr() + " v" + Int(owner.sessionRevision).ToStr()
    return {uri:transport.uri,format:"vtt",language:language,description:description,selectedOrdinal:ordinal,owner:owner}
end function

' The server session identifier is one literal path segment in both owned
' routes. Do not permit dot segments or encoded separators to acquire a
' different meaning after the URI leaves Scene.
function SiloUISubtitleTransportSegment(raw as Dynamic) as Boolean
    if type(raw) <> "String" and type(raw) <> "roString" then return false
    if Len(raw) < 1 or Len(raw) > 128 or raw = "." or raw = ".." then return false
    return CreateObject("roRegex","^[A-Za-z0-9_.-]+$","").IsMatch(raw)
end function

function SiloUISubtitleTransportSeconds(value as Dynamic) as Boolean
    kind = type(value)
    if kind <> "Integer" and kind <> "roInt" and kind <> "roInteger" and kind <> "LongInteger" and kind <> "roLongInteger" and kind <> "Float" and kind <> "roFloat" and kind <> "Double" and kind <> "roDouble" then return false
    return value = value and value >= 0 and value <= 604800
end function

' Match SiloUrlParts' normalized origin while refusing URL credentials and
' ambiguity; every accepted path remains an exact v2 media route below.
function SiloUISubtitleTransportURL(raw as Dynamic) as Dynamic
    if type(raw) <> "String" and type(raw) <> "roString" then return invalid
    if Len(raw) > 2048 or Instr(1,raw,"#") > 0 or Instr(1,raw,Chr(92)) > 0 then return invalid
    if CreateObject("roRegex","[\x00-\x20\x7f]","").IsMatch(raw) then return invalid
    parts = CreateObject("roRegex","^(https?)://([^/?#]+)(/[^#]*)$","i").Match(raw)
    if parts.Count() <> 4 then return invalid
    scheme = LCase(parts[1]):authority = LCase(parts[2])
    if Instr(1,authority,"@") > 0 then return invalid
    hostParts = CreateObject("roRegex","^(\[[0-9a-f:]+\]|[a-z0-9.-]+)(:[0-9]+)?$","i").Match(authority)
    if hostParts.Count() < 2 then return invalid
    port = "80"
    if scheme = "https" then port = "443"
    if hostParts.Count() > 2 and hostParts[2] <> "" then port = Mid(hostParts[2],2)
    number = Val(port)
    if number < 1 or number > 65535 then return invalid
    return {origin:scheme + "://" + hostParts[1] + ":" + number.ToStr(),path:parts[3]}
end function

function SiloUISubtitleTransportAVPath(path as String, sessionId as String, fileId as String) as Boolean
    if path = "/api/v2/playback/transcode/" + sessionId + "/master.m3u8" then return true
    if path = "/api/v2/playback/transcode/" + sessionId + "/master.m3u8?file_id=" + fileId then return true
    expected = "/api/v2/stream/" + sessionId
    if Left(path,Len(expected)) <> expected then return false
    query = Mid(path,Len(expected)+1)
    if query = "" then return true
    if Left(query,1) <> "?" then return false
    query = Mid(query,2)
    if query = "" or Left(query,1) = "&" or Right(query,1) = "&" or Instr(1,query,"&&") > 0 then return false
    fields = query.Tokenize("&")
    if fields.Count() = 0 or fields.Count() > 2 then return false
    seen = {}
    for each field in fields
        equal = Instr(1,field,"=")
        if equal < 2 then return false
        name = Left(field,equal-1):value = Mid(field,equal+1)
        if seen.DoesExist(name) then return false
        seen[name] = true
        if name = "file_id"
            if value <> fileId then return false
        else if name = "seek"
            if not SiloUISubtitleTransportDecimal(value,604800) then return false
        else
            return false
        end if
    end for
    return true
end function

function SiloUISubtitleTransportCaptionPath(path as String, sessionId as String, fileId as String, ordinal as Integer) as Boolean
    expected = "/api/v2/stream/" + sessionId + "/subtitles/" + ordinal.ToStr() + ".vtt?"
    if Left(path,Len(expected)) <> expected then return false
    query = Mid(path,Len(expected)+1)
    if query = "" or Left(query,1) = "&" or Right(query,1) = "&" or Instr(1,query,"&&") > 0 then return false
    fields = query.Tokenize("&")
    if fields.Count() = 0 or fields.Count() > 5 or fields[0] <> "file_id=" + fileId then return false
    seen = {file_id:true}
    for index = 1 to fields.Count()-1
        equal = Instr(1,fields[index],"=")
        if equal < 2 then return false
        name = Left(fields[index],equal-1):value = Mid(fields[index],equal+1)
        if seen.DoesExist(name) then return false
        seen[name] = true
        if name = "timestamp_offset"
            if not CreateObject("roRegex","^-?[0-9]{1,8}([.][0-9]{1,3})?$","").IsMatch(value) then return false
        else if name = "embedded_stream_index"
            if not CreateObject("roRegex","^[0-9]{1,4}$","").IsMatch(value) then return false
        else if name = "downloaded_subtitle_id"
            if not CreateObject("roRegex","^[1-9][0-9]{0,15}$","").IsMatch(value) then return false
        else if name = "external_subtitle_key"
            if not CreateObject("roRegex","^[0-9a-f]{64}$","").IsMatch(value) then return false
        else
            return false
        end if
    end for
    return true
end function

function SiloUISubtitleTransportDecimal(raw as String, maximum as Integer) as Boolean
    if not CreateObject("roRegex","^[0-9]{1,6}([.][0-9]{1,9})?$","").IsMatch(raw) then return false
    return Val(raw) <= maximum
end function

' Native TrackName need not equal the requested URI. Only a fresh, unique
' metadata match identifies the native lane; inventory position is irrelevant.
function SiloUISubtitleNativeCandidate(binding as Dynamic, inventory as Dynamic) as Dynamic
    if type(binding) <> "roAssociativeArray" or type(inventory) <> "roArray" then return invalid
    if inventory.Count() > 64 then return invalid
    matches = 0
    candidate = invalid
    for each row in inventory
        if type(row) = "roAssociativeArray"
            language = row.Language
            if type(language) = "String" or type(language) = "roString"
                language = LCase(language.Trim())
                sameLanguage = SiloUISubtitleLanguage(language) = binding.language
                if binding.language = "und" then sameLanguage = language = "und"
                if row.Description = binding.description and sameLanguage
                    trackName = row.TrackName
                    if type(trackName) <> "String" and type(trackName) <> "roString" then return invalid
                    if trackName = "" or Len(trackName) > 256 then return invalid
                    matches++
                    candidate = trackName
                end if
            end if
        end if
    end for
    if matches <> 1 then return invalid
    return candidate
end function

function SiloUISubtitleCurrentMatches(binding as Dynamic, current as Dynamic, inventory as Dynamic) as Boolean
    candidate = SiloUISubtitleNativeCandidate(binding,inventory)
    if candidate = invalid then return false
    if type(current) <> "String" and type(current) <> "roString" then return false
    return current = candidate
end function

' A result may arrive after its Scene owner has retired. Validate against the
' immutable request that produced the file before removing an unused artifact.
function SiloUISubtitleResultBinding(entry as Dynamic, result as Dynamic) as Dynamic
    if type(entry) <> "roAssociativeArray" or type(result) <> "roAssociativeArray" then return invalid
    if type(entry.owner) <> "roAssociativeArray" then return invalid
    binding = SiloUISubtitleBinding(result.plan,entry.generation,result.requestId)
    if binding = invalid then return invalid
    if binding.owner.sourceId <> entry.owner.sourceId or binding.owner.profileId <> entry.owner.profileId then return invalid
    if entry.owner.sessionRevision <> invalid
        if binding.owner.sessionRevision <> entry.owner.sessionRevision then return invalid
    end if
    return binding
end function

function SiloUISubtitleIntent(plan as Dynamic) as String
    if type(plan) <> "roAssociativeArray" or plan.provider <> "silo" then return "preference"
    if plan.subtitleMode = "off"
        if type(plan.siloPlayback) = "roAssociativeArray"
            if plan.siloPlayback.subtitleOffRequired = true then return "off"
        end if
        return "preference"
    end if
    if plan.subtitleMode = "burn_in" then return "burn_in"
    if plan.subtitleMode = "render" or plan.subtitleMode = "convert"
        if type(plan.selectedSubtitle) = "roAssociativeArray"
            kind = plan.selectedSubtitle.kind
            if kind = "sidecar_pending" or kind = "sidecar_ready" or kind = "fetch_failed" then return "selected"
        end if
    end if
    return "preference"
end function

function SiloUISubtitleStartupNotice(plan as Dynamic) as String
    if type(plan) <> "roAssociativeArray" or plan.provider <> "silo" then return ""
    if type(plan.selectedSubtitle) <> "roAssociativeArray" then return ""
    if plan.selectedSubtitle.kind = "fetch_failed" then return "Subtitles could not load. Playback continues."
    return ""
end function

function SiloUISubtitleOverrideOwned(choice as Dynamic, plan as Dynamic, scope as Dynamic) as Boolean
    if type(choice) <> "roAssociativeArray" or type(plan) <> "roAssociativeArray" or type(scope) <> "roAssociativeArray" then return false
    if SiloUISubtitleIntent(plan) <> "off" then return false
    return scope.provider = "silo" and choice.sourceId = scope.sourceId and choice.profileId = scope.profileId and choice.generation = scope.generation and choice.sessionId = plan.sessionId and choice.fileId = plan.versionId
end function

function SiloUISubtitleLocalOffOwned(mark as Dynamic, plan as Dynamic, scope as Dynamic) as Boolean
    if type(mark) <> "roAssociativeArray" or type(plan) <> "roAssociativeArray" or type(scope) <> "roAssociativeArray" then return false
    if SiloUISubtitleIntent(plan) <> "selected" then return false
    return mark.sourceId = scope.sourceId and mark.profileId = scope.profileId and mark.generation = scope.generation and mark.sessionId = plan.sessionId and mark.fileId = plan.versionId
end function

function SiloUISubtitleOverrideCapture(plan as Dynamic, scope as Dynamic, choice as Dynamic, inventory as Dynamic) as Dynamic
    if type(choice) <> "roAssociativeArray" or type(plan) <> "roAssociativeArray" or type(scope) <> "roAssociativeArray" then return invalid
    if SiloUISubtitleIntent(plan) <> "off" or choice.kind <> "subtitle" then return invalid
    if type(choice.trackId) <> "String" and type(choice.trackId) <> "roString" then return invalid
    if choice.trackId = "" or Len(choice.trackId) > 1024 then return invalid
    candidate = SiloUISubtitleOverrideTrack(choice,inventory)
    if candidate = invalid or candidate <> choice.trackId then return invalid
    return {sourceId:scope.sourceId,profileId:scope.profileId,generation:scope.generation,sessionId:plan.sessionId,fileId:plan.versionId,language:choice.language,name:choice.name}
end function

function SiloUISubtitleOverrideCandidate(choice as Dynamic, plan as Dynamic, scope as Dynamic, inventory as Dynamic) as Dynamic
    if not SiloUISubtitleOverrideOwned(choice,plan,scope) then return invalid
    return SiloUISubtitleOverrideTrack(choice,inventory)
end function

function SiloUISubtitleOverrideTrack(choice as Dynamic, inventory as Dynamic) as Dynamic
    if type(choice) <> "roAssociativeArray" or type(inventory) <> "roArray" then return invalid
    if inventory.Count() > 64 then return invalid
    count = 0
    candidate = invalid
    for each raw in inventory
        if type(raw) = "roAssociativeArray"
            id = raw.TrackName
            if type(id) = "String" or type(id) = "roString"
                if id <> "" and Len(id) <= 1024
                    if TrackPreferenceLanguage(raw.Language) = choice.language and TrackPreferenceName(raw.Description) = choice.name
                        count++
                        candidate = id
                    end if
                end if
            end if
        end if
    end for
    if count <> 1 then return invalid
    return candidate
end function

sub SiloUISubtitleDeleteLocal(uri as Dynamic)
    if SiloUISubtitleLocalUri(uri,"vtt") or SiloUISubtitleLocalUri(uri,"srt") then DeleteFile(uri)
end sub

sub SiloUISubtitleResultCleanup(entry as Dynamic, result as Dynamic)
    binding = SiloUISubtitleResultBinding(entry,result)
    if binding = invalid then return
    if m.subtitleBinding <> invalid
        if m.subtitleBinding.uri = binding.uri then return
    end if
    SiloUISubtitleDeleteLocal(binding.uri)
end sub

' Retain the exact old content identity until a native stopped event confirms
' it is detached. A delayed stop can then retire only this older file.
sub SiloUISubtitleRetireBound()
    if m.subtitleBinding = invalid then return
    binding = m.subtitleBinding
    m.subtitleBinding = invalid
    if m.subtitleRetired = invalid then m.subtitleRetired = []
    m.subtitleRetired.Push({uri:binding.uri,content:binding.content,generation:binding.bindingGeneration})
    m.video.control = "stop"
    m.video.content = invalid
    SiloUISubtitleDrainRetired()
end sub

sub SiloUISubtitleDrainRetired()
    if m.subtitleRetired = invalid or m.subtitleRetired.Count() = 0 then return
    if m.video.state <> "stopped" then return
    retained = []
    for each old in m.subtitleRetired
        stillBound = m.subtitleBinding <> invalid
        if stillBound then stillBound = m.subtitleBinding.uri = old.uri
        stillAttached = false
        if m.video.content <> invalid and old.content <> invalid
            stillAttached = old.content.isSameNode(m.video.content)
        end if
        if stillBound or stillAttached
            retained.Push(old)
        else
            SiloUISubtitleDeleteLocal(old.uri)
        end if
    end for
    m.subtitleRetired = retained
end sub
