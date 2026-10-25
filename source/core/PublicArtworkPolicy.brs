' Optional exact-ID public artwork. No owned URL, title lookup, storage or playback.
function PublicArtworkCreate() as Object
    return {serial:0,viewer:invalid,wanted:invalid,pending:invalid,cache:[],failed:"",disabled:false,asset:invalid,targets:[],assets:[],failedTargets:[]}
end function

function PublicArtworkReduce(previous as Object, event as Object) as Object
    state = PubArtCopy(previous)
    effects = []
    nowMs = PubArtNumber(HmField(event,"nowMs"),-1)
    if nowMs < 0 then return {state:state,effects:effects}
    kind = HmField(event,"kind")
    if kind = "bind"
        viewer = PubArtScope(HmField(event,"scope"))
        if not PubArtViewerSame(state.viewer,viewer)
            state.viewer = viewer
            state.cache = []
            state.wanted = invalid
            state.asset = invalid
            state.failed = ""
            state.targets = []
            state.assets = []
            state.failedTargets = []
        end if
    else if kind = "memory"
        state.disabled = true
        state.cache = []
        state.wanted = invalid
        state.asset = invalid
        state.failed = ""
        state.targets = []
        state.assets = []
        state.failedTargets = []
    else if kind = "recover"
        state.disabled = false
    else if kind = "focus"
        wanted = PubArtFocus(event,nowMs)
        if state.disabled then wanted = invalid
        if wanted = invalid
            state.wanted = invalid
            state.asset = invalid
            state.targets = []
            state.assets = []
            state.failedTargets = []
            state.failed = ""
        else
            if not PubArtViewerSame(state.viewer,wanted.scope)
                state.viewer = wanted.scope
                state.cache = []
            end if
            sameFocus = PubArtSameFocus(state.wanted,wanted)
            if sameFocus then wanted = state.wanted
            targets = PubArtTargets(event,wanted,nowMs)
            if not sameFocus or not PubArtSameTargets(state.targets,targets)
                retained = []
                failed = []
                for each target in targets
                    asset = PubArtTargetAsset(state.assets,target)
                    if asset = invalid
                        cached = PubArtCached(state,target,nowMs)
                        if cached <> invalid then asset = PubArtAsset(target,cached,state.serial)
                    end if
                    if asset <> invalid then retained.Push(asset)
                    if PubArtFailed(state,target) then failed.Push(PubArtFocusKey(target))
                end for
                state.wanted = wanted
                state.targets = targets
                state.assets = retained
                state.failedTargets = failed
                state.failed = ""
                if PubArtFailed(state,wanted) then state.failed = PubArtFocusKey(wanted)
                state.asset = PubArtTargetAsset(state.assets,wanted)
                if PubArtNextTarget(state) <> invalid
                    remaining = wanted.readyAtMs - nowMs
                    if remaining < 1 then remaining = 1
                    effects.Push({type:"timer",milliseconds:remaining})
                end if
            end if
        end if
    else if kind = "result"
        pending = state.pending
        if pending <> invalid
            if PubArtSameOwner(pending,HmField(event,"owner"))
                state.pending = invalid
                data = PubArtData(HmField(event,"data"),pending)
                valid = PubArtTrue(HmField(event,"ok")) and data <> invalid and not state.disabled
                sameViewer = PubArtViewerSame(state.viewer,pending.scope)
                if valid and sameViewer and not PubArtTrue(HmField(pending,"identityRequired"))
                    if data.posterUri <> "" or data.backdropUri <> ""
                        entry = {type:data.type,tmdbId:data.tmdbId,posterUri:data.posterUri,backdropUri:data.backdropUri,atMs:nowMs}
                        state.cache.Push(entry)
                        while state.cache.Count() > 64
                            state.cache.Shift()
                        end while
                    end if
                end if
                if PubArtTargetWanted(state,pending)
                    state.failedTargets.Push(PubArtFocusKey(pending))
                    if valid then PubArtStoreAsset(state,PubArtAsset(pending,data,pending.artId))
                    state.asset = PubArtTargetAsset(state.assets,state.wanted)
                    if PubArtSameFocus(state.wanted,pending) then state.failed = PubArtFocusKey(state.wanted)
                end if
                PubArtHydrate(state,nowMs)
                PubArtIssue(state,effects,nowMs)
            end if
        end if
    else if kind = "tick"
        PubArtIssue(state,effects,nowMs)
    end if
    return {state:state,effects:effects}
end function

sub PubArtIssue(state as Object, effects as Object, nowMs as Double)
    if state.disabled or state.pending <> invalid or state.wanted = invalid then return
    wanted = PubArtNextTarget(state)
    if wanted = invalid then return
    remaining = state.wanted.readyAtMs - nowMs
    if remaining > 0
        effects.Push({type:"timer",milliseconds:remaining})
        return
    end if
    if state.serial >= 2147483646 then return
    state.serial++
    owner = PubArtCopy(wanted)
    owner["artId"] = state.serial
    state.pending = owner
    params = {type:owner.type,tmdbId:owner.tmdbId}
    if PubArtTrue(HmField(owner,"identityRequired")) then params = {type:owner.type,itemId:owner.itemId,itemType:owner.nativeType}
    effects.Push({type:"request",action:"metadata_artwork",purpose:"public_artwork",scope:owner.scope,
        params:params,artworkOwner:owner})
end sub

function PublicArtworkProjection(state as Object) as Object
    output = {active:false,scopeKey:"",key:"",token:"",posterUri:"",backdropUri:"",cards:[]}
    if state.wanted = invalid or state.disabled then return output
    output["scopeKey"] = state.wanted.scopeKey
    for each target in state.targets
        granted = PubArtTargetAsset(state.assets,target)
        if granted <> invalid
            if granted.posterUri <> "" or granted.backdropUri <> ""
                output.cards.Push({key:target.key,token:granted.token,posterUri:granted.posterUri,backdropUri:granted.backdropUri})
            end if
        end if
    end for
    asset = state.asset
    if type(asset) <> "roAssociativeArray" or state.wanted = invalid or state.disabled then return output
    if not PubArtSameFocus(state.wanted,asset.owner) then return output
    output.active = asset.posterUri <> "" or asset.backdropUri <> ""
    output["scopeKey"] = state.wanted.scopeKey
    output.key = state.wanted.key
    output.token = asset.token
    output["posterUri"] = asset.posterUri
    output["backdropUri"] = asset.backdropUri
    return output
end function

function PubArtAsset(wanted as Object, data as Object, serial as Integer) as Object
    return {owner:wanted,token:"art-"+serial.ToStr(),posterUri:data.posterUri,backdropUri:data.backdropUri}
end function

function PubArtCached(state as Object, wanted as Object, nowMs as Double) as Dynamic
    ' A URI cache is not proof of the current private owned item identity.
    if PubArtTrue(HmField(wanted,"identityRequired")) then return invalid
    fresh = []
    found = invalid
    for each entry in state.cache
        age = nowMs - entry.atMs
        if age >= 0 and age < 600000
            fresh.Push(entry)
            if entry.type = wanted.type and entry.tmdbId = wanted.tmdbId then found = entry
        end if
    end for
    state.cache = fresh
    return found
end function

function PubArtFocus(event as Object, nowMs as Double) as Dynamic
    if not PubArtTrue(HmField(event,"active")) then return invalid
    scope = PubArtScope(HmField(event,"scope"))
    item = HmField(event,"item")
    if scope = invalid or type(item) <> "roAssociativeArray" then return invalid
    scopeKey = PubArtKey(HmField(event,"scopeKey"),120)
    key = PubArtKey(HmField(event,"key"),256)
    provider = HmField(item,"provider")
    if scope.provider = "plex" and provider <> invalid
        if type(provider) <> "String" and type(provider) <> "roString" then return invalid
        if provider <> "plex" and provider <> "metadata" then return invalid
        if provider = "plex"
            if HmField(item,"availability") <> invalid and HmField(item,"availability") <> "owned" then return invalid
        end if
    end if
    nativeType = HmText(HmField(item,"type"),20)
    kind = nativeType
    if kind = "show" or kind = "series" or kind = "tv" then kind = "tv"
    if kind = "episode"
        if scope.provider = "silo" and provider <> "metadata" then kind = "tv"
        if scope.provider = "plex" and provider = "plex" then kind = "tv"
    end if
    if kind <> "movie" and kind <> "tv" then return invalid
    identifier = PubArtTmdb(item)
    identityRequired = scope.provider = "silo" and provider <> "metadata"
    if identityRequired
        if nativeType <> "movie" and nativeType <> "series" and nativeType <> "episode" then return invalid
        if HmField(item,"availability") <> invalid and HmField(item,"availability") <> "owned" then return invalid
        identifier = ""
    end if
    if scope.provider = "plex" and provider = "plex" and (nativeType = "episode" or identifier = "")
        if nativeType <> "movie" and nativeType <> "show" and nativeType <> "episode" then return invalid
        nativeId = PubArtKey(HmField(item,"itemId"),20)
        if not CreateObject("roRegex","^[0-9]{1,20}$","").IsMatch(nativeId) then return invalid
        identityRequired = true
        ' A leaf episode GUID never proves its parent show's public identity.
        identifier = ""
    end if
    if scopeKey = "" or key = "" or (identifier = "" and not identityRequired) then return invalid
    itemId = PubArtKey(HmField(item,"itemId"),256)
    if HmField(item,"provider") = "metadata"
        catalogKind = kind
        if kind = "tv" then catalogKind = "show"
        itemId = PubArtKey(HmField(item,"catalogId"),256)
        if itemId <> "metadata:" + catalogKind + ":" + identifier then return invalid
    else
        if itemId = "" or HmField(item,"sourceId") <> scope.sourceId then return invalid
    end if
    return {scope:scope,scopeKey:scopeKey,key:key,itemId:itemId,type:kind,tmdbId:identifier,
        identityRequired:identityRequired,nativeType:nativeType,readyAtMs:nowMs+240}
end function

' Source is private internal identity: Silo currently includes canonical HTTPS URL.
function PubArtScope(value as Dynamic) as Dynamic
    if type(value) <> "roAssociativeArray" then return invalid
    provider = HmText(HmField(value,"provider"),10)
    source = HmField(value,"sourceId")
    profile = HmField(value,"profileId")
    generation = PubArtNumber(HmField(value,"generation"),-1)
    if provider <> "plex" and provider <> "silo" then return invalid
    if PubArtScopeText(source,512) = "" then return invalid
    if Left(source,Len(provider)+1) <> provider+":" then return invalid
    if type(profile) <> "String" and type(profile) <> "roString" then return invalid
    if Len(profile) > 256 or CreateObject("roRegex","[\x00-\x1f\x7f]","").IsMatch(profile) then return invalid
    if generation < 0 or generation > 2147483647 or generation <> Int(generation) then return invalid
    return {provider:provider,sourceId:source,profileId:profile,generation:generation}
end function

function PubArtTmdb(item as Object) as String
    identifiers = []
    raw = HmField(item,"tmdbId")
    if PubArtHasIdentity(raw) then identifiers.Push(raw)
    external = HmField(item,"externalIds")
    raw = HmField(external,"tmdb")
    if PubArtHasIdentity(raw) then identifiers.Push(raw)
    guids = HmField(item,"guids")
    if type(guids) = "roArray"
        inspected = 0
        for each raw in guids
            inspected++
            if inspected > 16 then return ""
            text = HmText(raw,256)
            if Left(text,7) = "tmdb://" then identifiers.Push(Mid(text,8))
        end for
    end if
    wanted = ""
    for each value in identifiers
        identifier = HmNumericId(value)
        if identifier = "" then return ""
        if wanted <> "" and wanted <> identifier then return ""
        wanted = identifier
    end for
    return wanted
end function

function PubArtData(value as Dynamic, owner as Object) as Dynamic
    if type(value) <> "roAssociativeArray" then return invalid
    if HmText(HmField(value,"type"),10) <> owner.type then return invalid
    identifier = HmNumericId(HmField(value,"tmdbId"))
    if PubArtTrue(HmField(owner,"identityRequired"))
        ' The mapped pipeline already matched this ID to fresh private Detail.
        if HmField(value,"type") <> owner.type then return invalid
        raw = HmField(value,"tmdbId")
        if type(raw) <> "String" and type(raw) <> "roString" then return invalid
        if not CreateObject("roRegex","^[1-9][0-9]{0,11}$","").IsMatch(raw) then return invalid
        if identifier = "" or identifier <> raw then return invalid
    else
        if identifier <> owner.tmdbId then return invalid
    end if
    poster = PubArtUri(HmField(value,"posterUri"),"w342")
    backdrop = PubArtUri(HmField(value,"backdropUri"),"w780")
    return {type:owner.type,tmdbId:identifier,posterUri:poster,backdropUri:backdrop}
end function

function PubArtUri(value as Dynamic, size as String) as String
    uri = HmText(value,256)
    if not CreateObject("roRegex","^https://image\.tmdb\.org/t/p/"+size+"/[A-Za-z0-9_-]+\.(jpg|jpeg|png|webp)$","").IsMatch(uri) then return ""
    return uri
end function

function PubArtSameFocus(a as Dynamic, b as Dynamic) as Boolean
    if type(a) <> "roAssociativeArray" or type(b) <> "roAssociativeArray" then return false
    if not PubArtViewerSame(a.scope,b.scope) then return false
    if PubArtTrue(HmField(a,"identityRequired")) <> PubArtTrue(HmField(b,"identityRequired")) then return false
    if PubArtTrue(HmField(a,"identityRequired")) and HmField(a,"nativeType") <> HmField(b,"nativeType") then return false
    return a.scope.generation = b.scope.generation and a.scopeKey = b.scopeKey and a.key = b.key and a.itemId = b.itemId and a.type = b.type and a.tmdbId = b.tmdbId
end function

function PubArtSameOwner(a as Object, b as Dynamic) as Boolean
    if type(b) <> "roAssociativeArray" then return false
    if PubArtNumber(HmField(b,"artId"),-1) <> a.artId then return false
    if PubArtScope(HmField(b,"scope")) = invalid then return false
    for each key in ["scopeKey","key","itemId","type","tmdbId"]
        if HmText(HmField(b,key),256) <> a[key] then return false
    end for
    return PubArtSameFocus(a,b)
end function

function PubArtViewerSame(a as Dynamic, b as Dynamic) as Boolean
    if type(a) <> "roAssociativeArray" or type(b) <> "roAssociativeArray" then return false
    return a.provider = b.provider and a.sourceId = b.sourceId and a.profileId = b.profileId
end function

function PubArtFocusKey(value as Object) as String
    return value.scopeKey+"|"+value.key+"|"+value.itemId+"|"+value.type+"|"+value.tmdbId
end function

function PubArtScopeText(value as Dynamic, cap as Integer) as String
    if type(value) <> "String" and type(value) <> "roString" then return ""
    if Len(value) = 0 or Len(value) > cap then return ""
    if CreateObject("roRegex","[\x00-\x1f\x7f]","").IsMatch(value) then return ""
    return value
end function

function PubArtKey(value as Dynamic, cap as Integer) as String
    text = PubArtScopeText(value,cap)
    if not CreateObject("roRegex","^[A-Za-z0-9_.:-]+$","").IsMatch(text) then return ""
    return text
end function

function PubArtNumber(value as Dynamic, fallback as Double) as Double
    name = type(value)
    if name <> "Integer" and name <> "roInt" and name <> "roInteger" and name <> "LongInteger" and name <> "roLongInteger" and name <> "Float" and name <> "roFloat" and name <> "Double" and name <> "roDouble" then return fallback
    if value <> value or value < 0 or value > 9007199254740991# then return fallback
    return value
end function

function PubArtCopy(value as Dynamic) as Dynamic
    if type(value) = "roAssociativeArray"
        output = {}
        for each key in value
            output[key] = PubArtCopy(value[key])
        end for
        return output
    else if type(value) = "roArray"
        output = []
        for each entry in value
            output.Push(PubArtCopy(entry))
        end for
        return output
    end if
    return value
end function

function PubArtHasIdentity(value as Dynamic) as Boolean
    if value = invalid then return false
    name = type(value)
    if name = "String" or name = "roString" then return value <> ""
    return true
end function

function PubArtTrue(value as Dynamic) as Boolean
    if type(value) <> "Boolean" and type(value) <> "roBoolean" then return false
    return value = true
end function

' Targets come from a native index neighborhood, not a viewport assertion.
function PubArtTargets(event as Object, wanted as Object, nowMs as Double) as Object
    targets = [wanted]
    values = HmField(event,"neighbors")
    if type(values) <> "roArray" then return targets
    inspected = 0
    for each raw in values
        inspected++
        if inspected > 24 or targets.Count() >= 12 then exit for
        target = PubArtFocus({active:true,scope:wanted.scope,scopeKey:wanted.scopeKey,key:HmField(raw,"key"),item:HmField(raw,"item")},nowMs)
        if target <> invalid
            duplicate = false
            for each current in targets
                if target.key = current.key then duplicate = true
            end for
            if not duplicate
                target["readyAtMs"] = wanted.readyAtMs
                targets.Push(target)
            end if
        end if
    end for
    return targets
end function

function PubArtSameTargets(a as Object, b as Object) as Boolean
    if a.Count() <> b.Count() then return false
    for index = 0 to a.Count() - 1
        if not PubArtSameFocus(a[index],b[index]) then return false
    end for
    return true
end function

function PubArtTargetWanted(state as Object, target as Dynamic) as Boolean
    for each current in state.targets
        if PubArtSameFocus(current,target) then return true
    end for
    return false
end function

function PubArtTargetAsset(assets as Object, target as Dynamic) as Dynamic
    if target = invalid then return invalid
    for each asset in assets
        if PubArtSameFocus(asset.owner,target) then return asset
    end for
    return invalid
end function

function PubArtFailed(state as Object, target as Object) as Boolean
    for each key in state.failedTargets
        if key = PubArtFocusKey(target) then return true
    end for
    return false
end function

function PubArtNextTarget(state as Object) as Dynamic
    for each target in state.targets
        if PubArtTargetAsset(state.assets,target) = invalid and not PubArtFailed(state,target) then return target
    end for
    return invalid
end function

sub PubArtStoreAsset(state as Object, incoming as Object)
    retained = []
    for each asset in state.assets
        if not PubArtSameFocus(asset.owner,incoming.owner) then retained.Push(asset)
    end for
    if retained.Count() < 12 then retained.Push(incoming)
    state.assets = retained
end sub

sub PubArtHydrate(state as Object, nowMs as Double)
    for each target in state.targets
        if PubArtTargetAsset(state.assets,target) = invalid
            cached = PubArtCached(state,target,nowMs)
            if cached <> invalid then PubArtStoreAsset(state,PubArtAsset(target,cached,state.serial))
        end if
    end for
    state.asset = PubArtTargetAsset(state.assets,state.wanted)
end sub
