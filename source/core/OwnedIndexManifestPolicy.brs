' Disposable inventory metadata; load with OwnedIndexPolicy.brs. Keep account/
' revision scope and readback bodies in the private Scan Task, without credentials
' or media/artwork URLs. Schema 1 bounds: 200 shards and libraries, 128 KiB manifest,
' 4 MiB total. IDs are retained only for duplicate detection.
' Offset scans are not atomic: sourceInventoryComplete and authoritativeAbsence
' remain false even after contiguous terminal coverage.
function OwnedIndexManifestFailure(code as String) as Object
    allowed = ["invalid_scope", "invalid_manifest", "manifest_expired", "invalid_shard", "shard_budget", "manifest_budget", "page_mismatch", "duplicate_identity", "scan_invalidated"]
    safe = "invalid_manifest"
    for each candidate in allowed
        if candidate = code then safe = candidate
    end for
    return {ok: false, errorCode: safe}
end function

function OwnedIndexManifestKeys(value as Dynamic, names as Object) as Boolean
    if not OwnedIndexKeys(value, names) then return false
    if value.Count() <> names.Count() then return false
    seen = {}
    for each key in value.Keys()
        folded = LCase(key)
        if seen.DoesExist(folded) then return false
        seen[folded] = true
    end for
    return true
end function

function OwnedIndexManifestNumber(value as Dynamic) as Integer
    kind = type(value)
    if kind = "String" or kind = "roString" or kind = "Boolean" or kind = "roBoolean" then return -1
    return OwnedIndexInteger(value)
end function

function OwnedIndexManifestBoolean(value as Dynamic) as Boolean
    return type(value) = "Boolean" or type(value) = "roBoolean"
end function

function OwnedIndexManifestScope(value as Dynamic) as Object
    result = {}
    for each key in ["provider", "sourceId", "profileId", "accountId", "sessionRevision", "inventoryRunId"]
        result[key] = OwnedIndexField(value, key)
    end for
    return result
end function

function OwnedIndexManifestScopeValid(scope as Dynamic) as Boolean
    if not OwnedIndexManifestKeys(scope, ["provider", "sourceId", "profileId", "accountId", "sessionRevision", "inventoryRunId"]) then return false
    if OwnedIndexText(scope, "provider") <> "plex" then return false
    if not CreateObject("roRegex", "^plex:[A-Za-z0-9._:-]{1,160}$", "").IsMatch(OwnedIndexText(scope, "sourceId")) then return false
    profile = OwnedIndexField(scope, "profileId")
    if type(profile) <> "String" and type(profile) <> "roString" then return false
    if not OwnedIndexIdentifier(profile, true) then return false
    if not OwnedIndexIdentifier(OwnedIndexText(scope, "accountId")) then return false
    if OwnedIndexManifestNumber(OwnedIndexField(scope, "sessionRevision")) < 0 then return false
    return OwnedIndexManifestUri(OwnedIndexText(scope, "inventoryRunId")) <> ""
end function

function OwnedIndexManifestUri(inventoryRunId as String) as String
    if not CreateObject("roRegex", "^[A-Za-z0-9_-]{1,64}$", "").IsMatch(inventoryRunId) then return ""
    return "cachefs:/owned-manifest-" + inventoryRunId + ".json"
end function

function OwnedIndexManifestShardUri(runId as String, libraryId as String, offset as Integer) as String
    if OwnedIndexManifestUri(runId) = "" then return ""
    if not CreateObject("roRegex", "^[A-Za-z0-9_-]{1,64}$", "").IsMatch(libraryId) then return ""
    if offset < 0 or offset > 2147483599 then return ""
    return "cachefs:/owned-" + runId + "-" + libraryId + "-" + offset.ToStr() + ".json"
end function

function OwnedIndexManifestCreate(scope as Dynamic, now as Integer) as Object
    if not OwnedIndexManifestScopeValid(scope) then return OwnedIndexManifestFailure("invalid_scope")
    if now < 1 or now > 2147480047 then return OwnedIndexManifestFailure("invalid_manifest")
    manifest = {schema: 1, createdAt: now, expiresAt: now + 3600, totalBytes: 0, shardCount: 0, libraries: [], shards: [], sourceInventoryComplete: false, authoritativeAbsence: false}
    for each key in OwnedIndexManifestScope(scope).Keys()
        manifest[key] = OwnedIndexField(scope, key)
    end for
    return {ok: true, manifest: manifest}
end function

' Reconstruct a library from retained references. An invalidated library may
' contain holes, but references still have to increase and stop at a terminal
' page. Such a library cannot accept new pages; the caller starts a fresh run.
function OwnedIndexManifestLibraryState(libraryId as String, shards as Object, intact as Boolean) as Dynamic
    state = {libraryId: libraryId, rawOffset: 0, nextOffset: 0, terminal: false, identityComplete: intact, coverageValid: intact, rawCount: 0, recordCount: 0}
    found = false
    expected = 0
    stopped = false
    for each shard in shards
        if OwnedIndexText(shard, "libraryId") = libraryId
            offset = OwnedIndexField(shard, "offset")
            if stopped then return invalid
            if intact and offset <> expected then return invalid
            if found and offset < expected then return invalid
            state["rawOffset"] = offset
            state["nextOffset"] = OwnedIndexField(shard, "nextOffset")
            state["rawCount"] = OwnedIndexField(state, "rawCount") + OwnedIndexField(shard, "rawCount")
            state["recordCount"] = OwnedIndexField(state, "recordCount") + OwnedIndexField(shard, "recordCount")
            if not OwnedIndexField(shard, "identityComplete") then state["identityComplete"] = false
            stopped = OwnedIndexField(shard, "terminal")
            state["terminal"] = intact and stopped
            expected = offset + OwnedIndexField(shard, "rawCount")
            found = true
        end if
    end for
    if not found and intact then return invalid
    return state
end function

function OwnedIndexManifestValidateInternal(manifest as Dynamic, scope as Dynamic, now as Integer, fresh as Boolean) as Object
    if not OwnedIndexManifestScopeValid(scope) then return OwnedIndexManifestFailure("invalid_scope")
    names = ["schema", "provider", "sourceId", "profileId", "accountId", "sessionRevision", "inventoryRunId", "createdAt", "expiresAt", "totalBytes", "shardCount", "libraries", "shards", "sourceInventoryComplete", "authoritativeAbsence"]
    if not OwnedIndexManifestKeys(manifest, names) then return OwnedIndexManifestFailure("invalid_manifest")
    if not OwnedIndexManifestScopeValid(OwnedIndexManifestScope(manifest)) then return OwnedIndexManifestFailure("invalid_scope")
    for each key in OwnedIndexManifestScope(scope).Keys()
        if OwnedIndexField(manifest, key) <> OwnedIndexField(scope, key) then return OwnedIndexManifestFailure("invalid_scope")
    end for
    if OwnedIndexManifestNumber(OwnedIndexField(manifest, "schema")) <> 1 then return OwnedIndexManifestFailure("invalid_manifest")
    for each key in ["sourceInventoryComplete", "authoritativeAbsence"]
        value = OwnedIndexField(manifest, key)
        if not OwnedIndexManifestBoolean(value) then return OwnedIndexManifestFailure("invalid_manifest")
        if value then return OwnedIndexManifestFailure("invalid_manifest")
    end for
    createdAt = OwnedIndexManifestNumber(OwnedIndexField(manifest, "createdAt"))
    expiresAt = OwnedIndexManifestNumber(OwnedIndexField(manifest, "expiresAt"))
    if createdAt < 1 or createdAt > 2147480047 or expiresAt - createdAt <> 3600 then return OwnedIndexManifestFailure("invalid_manifest")
    if fresh and (now < createdAt or now >= expiresAt) then return OwnedIndexManifestFailure("manifest_expired")
    shards = OwnedIndexField(manifest, "shards")
    libraries = OwnedIndexField(manifest, "libraries")
    if type(shards) <> "roArray" or type(libraries) <> "roArray" then return OwnedIndexManifestFailure("invalid_manifest")
    if shards.Count() > 200 or libraries.Count() > 200 then return OwnedIndexManifestFailure("manifest_budget")
    if OwnedIndexManifestNumber(OwnedIndexField(manifest, "shardCount")) <> shards.Count() then return OwnedIndexManifestFailure("invalid_manifest")
    libraryIds = {}
    for each library in libraries
        if not OwnedIndexManifestKeys(library, ["libraryId", "rawOffset", "nextOffset", "terminal", "identityComplete", "coverageValid", "rawCount", "recordCount"]) then return OwnedIndexManifestFailure("invalid_manifest")
        libraryId = OwnedIndexText(library, "libraryId")
        if OwnedIndexManifestShardUri(OwnedIndexText(scope, "inventoryRunId"), libraryId, 0) = "" then return OwnedIndexManifestFailure("invalid_manifest")
        if libraryIds.DoesExist(libraryId) then return OwnedIndexManifestFailure("invalid_manifest")
        libraryIds[libraryId] = true
        for each flag in ["terminal", "identityComplete", "coverageValid"]
            if not OwnedIndexManifestBoolean(OwnedIndexField(library, flag)) then return OwnedIndexManifestFailure("invalid_manifest")
        end for
        for each field in ["rawOffset", "rawCount", "recordCount"]
            if OwnedIndexManifestNumber(OwnedIndexField(library, field)) < 0 then return OwnedIndexManifestFailure("invalid_manifest")
        end for
    end for
    totalBytes = 0
    seenItems = {}
    seenPaths = {}
    for each shard in shards
        if not OwnedIndexManifestKeys(shard, ["libraryId", "offset", "rawCount", "nextOffset", "terminal", "identityComplete", "recordCount", "itemIds", "uri", "bytes", "createdAt", "expiresAt"]) then return OwnedIndexManifestFailure("invalid_manifest")
        libraryId = OwnedIndexText(shard, "libraryId")
        if not libraryIds.DoesExist(libraryId) then return OwnedIndexManifestFailure("invalid_manifest")
        offset = OwnedIndexManifestNumber(OwnedIndexField(shard, "offset"))
        uri = OwnedIndexManifestShardUri(OwnedIndexText(scope, "inventoryRunId"), libraryId, offset)
        if uri = "" or uri <> OwnedIndexText(shard, "uri") then return OwnedIndexManifestFailure("invalid_manifest")
        if seenPaths.DoesExist(uri) then return OwnedIndexManifestFailure("invalid_manifest")
        seenPaths[uri] = true
        rawCount = OwnedIndexManifestNumber(OwnedIndexField(shard, "rawCount"))
        recordCount = OwnedIndexManifestNumber(OwnedIndexField(shard, "recordCount"))
        if rawCount < 0 or rawCount > 48 or recordCount < 0 or recordCount > rawCount then return OwnedIndexManifestFailure("invalid_manifest")
        terminal = OwnedIndexField(shard, "terminal")
        if not OwnedIndexManifestBoolean(terminal) or not OwnedIndexManifestBoolean(OwnedIndexField(shard, "identityComplete")) then return OwnedIndexManifestFailure("invalid_manifest")
        nextOffset = OwnedIndexField(shard, "nextOffset")
        if terminal
            if type(nextOffset) = "String" or type(nextOffset) = "roString" then return OwnedIndexManifestFailure("invalid_manifest")
            if nextOffset <> -1 then return OwnedIndexManifestFailure("invalid_manifest")
        else
            if rawCount = 0 or OwnedIndexManifestNumber(nextOffset) <> offset + rawCount then return OwnedIndexManifestFailure("invalid_manifest")
        end if
        itemIds = OwnedIndexField(shard, "itemIds")
        if type(itemIds) <> "roArray" then return OwnedIndexManifestFailure("invalid_manifest")
        if itemIds.Count() <> recordCount then return OwnedIndexManifestFailure("invalid_manifest")
        for each itemId in itemIds
            if type(itemId) <> "String" and type(itemId) <> "roString" then return OwnedIndexManifestFailure("invalid_manifest")
            if not OwnedIndexIdentifier(itemId) then return OwnedIndexManifestFailure("invalid_manifest")
            if seenItems.DoesExist(itemId) then return OwnedIndexManifestFailure("duplicate_identity")
            seenItems[itemId] = true
        end for
        bytes = OwnedIndexManifestNumber(OwnedIndexField(shard, "bytes"))
        if bytes < 1 or bytes > 65536 then return OwnedIndexManifestFailure("shard_budget")
        totalBytes = totalBytes + bytes
        shardCreated = OwnedIndexManifestNumber(OwnedIndexField(shard, "createdAt"))
        shardExpires = OwnedIndexManifestNumber(OwnedIndexField(shard, "expiresAt"))
        if shardCreated < createdAt or shardCreated >= expiresAt or shardExpires - shardCreated <> 3600 then return OwnedIndexManifestFailure("invalid_manifest")
        if fresh and (now < shardCreated or now >= shardExpires) then return OwnedIndexManifestFailure("manifest_expired")
    end for
    if OwnedIndexManifestNumber(OwnedIndexField(manifest, "totalBytes")) <> totalBytes then return OwnedIndexManifestFailure("invalid_manifest")
    for each library in libraries
        state = OwnedIndexManifestLibraryState(OwnedIndexText(library, "libraryId"), shards, OwnedIndexField(library, "coverageValid"))
        if state = invalid then return OwnedIndexManifestFailure("page_mismatch")
        for each key in state.Keys()
            if OwnedIndexField(library, key) <> state[key] then return OwnedIndexManifestFailure("invalid_manifest")
        end for
    end for
    metadataBytes = OwnedIndexByteCount(FormatJson(manifest))
    if metadataBytes > 131072 or totalBytes + metadataBytes > 4194304 then return OwnedIndexManifestFailure("manifest_budget")
    return {ok: true}
end function

function OwnedIndexManifestValidate(manifest as Dynamic, scope as Dynamic, now as Integer) as Object
    return OwnedIndexManifestValidateInternal(manifest, scope, now, true)
end function

function OwnedIndexManifestQuota(manifest as Dynamic, reservationBytes = 65536 as Integer) as Object
    validated = OwnedIndexManifestValidateInternal(manifest, OwnedIndexManifestScope(manifest), 0, false)
    if validated.ok <> true
        validated["canWrite"] = false
        return validated
    end if
    if reservationBytes < 1 or reservationBytes > 65536
        result = OwnedIndexManifestFailure("shard_budget")
        result["canWrite"] = false
        return result
    end if
    metadataBytes = OwnedIndexByteCount(FormatJson(manifest))
    remainingBytes = 4194304 - OwnedIndexField(manifest, "totalBytes") - metadataBytes
    remainingShards = 200 - OwnedIndexField(manifest, "shardCount")
    ' Reserve worst-case reference/library metadata (48 IDs up to 128 chars).
    canWrite = remainingShards > 0 and remainingBytes >= reservationBytes + 8192 and metadataBytes + 8192 <= 131072
    return {ok: true, canWrite: canWrite, remainingShards: remainingShards, remainingBytes: remainingBytes}
end function

function OwnedIndexManifestAppend(manifest as Dynamic, job as Dynamic, shardBody as String, shardUri as String, shardBytes as Integer, now as Integer) as Object
    scope = OwnedIndexManifestScope(manifest)
    validated = OwnedIndexManifestValidate(manifest, scope, now)
    if validated.ok <> true then return validated
    if not OwnedIndexValidJob(job) then return OwnedIndexManifestFailure("invalid_shard")
    for each key in ["provider", "sourceId", "profileId", "inventoryRunId"]
        if OwnedIndexField(job, key) <> OwnedIndexField(scope, key) then return OwnedIndexManifestFailure("invalid_scope")
    end for
    expectedUri = OwnedIndexManifestShardUri(OwnedIndexText(scope, "inventoryRunId"), OwnedIndexText(job, "libraryId"), OwnedIndexInteger(OwnedIndexField(job, "offset")))
    if shardUri <> expectedUri then return OwnedIndexManifestFailure("invalid_shard")
    if shardBytes < 1 or shardBytes > 65536 or Len(shardBody) > 65536 then return OwnedIndexManifestFailure("shard_budget")
    if OwnedIndexByteCount(shardBody) <> shardBytes then return OwnedIndexManifestFailure("invalid_shard")
    data = ParseJson(shardBody)
    ' Wire integer parsing permits digit strings, but persisted metadata must
    ' contain JSON numbers before shared page validation performs arithmetic.
    for each key in ["schema", "sessionRevision", "createdAt", "expiresAt", "offset", "pageSize", "rawCount", "totalSize"]
        if OwnedIndexManifestNumber(OwnedIndexField(data, key)) < 0 then return OwnedIndexManifestFailure("invalid_shard")
    end for
    nextOffset = OwnedIndexField(data, "nextOffset")
    if OwnedIndexManifestNumber(nextOffset) < 0
        kind = type(nextOffset)
        if kind <> "Integer" and kind <> "LongInteger" and kind <> "Float" and kind <> "Double" and kind <> "roInt" and kind <> "roInteger" and kind <> "roLongInteger" and kind <> "roFloat" and kind <> "roDouble" then return OwnedIndexManifestFailure("invalid_shard")
        if nextOffset <> -1 then return OwnedIndexManifestFailure("invalid_shard")
    end if
    checked = OwnedIndexValidateShard(shardBody, job, scope, OwnedIndexField(scope, "sessionRevision"), now)
    if checked.ok <> true then return OwnedIndexManifestFailure("invalid_shard")
    if OwnedIndexField(data, "createdAt") < OwnedIndexField(manifest, "createdAt") then return OwnedIndexManifestFailure("invalid_shard")
    libraryId = OwnedIndexText(job, "libraryId")
    current = invalid
    for each library in OwnedIndexField(manifest, "libraries")
        if OwnedIndexText(library, "libraryId") = libraryId then current = library
    end for
    if current <> invalid
        if not OwnedIndexField(current, "coverageValid") then return OwnedIndexManifestFailure("scan_invalidated")
        if OwnedIndexField(current, "terminal") then return OwnedIndexManifestFailure("page_mismatch")
        if OwnedIndexField(current, "nextOffset") <> OwnedIndexField(job, "offset") then return OwnedIndexManifestFailure("page_mismatch")
    else
        if OwnedIndexField(job, "offset") <> 0 then return OwnedIndexManifestFailure("page_mismatch")
    end if
    result = ParseJson(FormatJson(manifest))
    ids = []
    for each record in OwnedIndexField(data, "records")
        ids.Push(OwnedIndexText(record, "itemId"))
    end for
    ref = {libraryId: libraryId, offset: OwnedIndexField(data, "offset"), rawCount: OwnedIndexField(data, "rawCount"), nextOffset: OwnedIndexField(data, "nextOffset"), terminal: OwnedIndexField(data, "pageTerminal"), identityComplete: OwnedIndexField(data, "externalIdsComplete"), recordCount: ids.Count(), itemIds: ids, uri: shardUri, bytes: shardBytes, createdAt: OwnedIndexField(data, "createdAt"), expiresAt: OwnedIndexField(data, "expiresAt")}
    OwnedIndexField(result, "shards").Push(ref)
    result["shardCount"] = OwnedIndexField(result, "shards").Count()
    result["totalBytes"] = OwnedIndexField(result, "totalBytes") + shardBytes
    libraries = []
    for each library in OwnedIndexField(result, "libraries")
        if OwnedIndexText(library, "libraryId") <> libraryId then libraries.Push(library)
    end for
    libraries.Push(OwnedIndexManifestLibraryState(libraryId, OwnedIndexField(result, "shards"), true))
    result["libraries"] = libraries
    checked = OwnedIndexManifestValidate(result, scope, now)
    if checked.ok <> true then return checked
    return {ok: true, manifest: result}
end function

function OwnedIndexManifestCoverage(manifest as Dynamic, scope as Dynamic, now as Integer) as Object
    checked = OwnedIndexManifestValidate(manifest, scope, now)
    if checked.ok <> true
        checked["libraries"] = []
        checked["sourceInventoryComplete"] = false
        checked["authoritativeAbsence"] = false
        return checked
    end if
    return {ok: true, libraries: ParseJson(FormatJson(OwnedIndexField(manifest, "libraries"))), sourceInventoryComplete: false, authoritativeAbsence: false}
end function

' Removes refs only; a caller performs filesystem deletion from PurgePlan.
' Unknown/malformed input paths cause failure without changing the manifest.
function OwnedIndexManifestEvict(manifest as Dynamic, uris as Dynamic, now as Integer) as Object
    scope = OwnedIndexManifestScope(manifest)
    checked = OwnedIndexManifestValidateInternal(manifest, scope, now, false)
    if checked.ok <> true then return checked
    if type(uris) <> "roArray" then return OwnedIndexManifestFailure("invalid_shard")
    if uris.Count() > 200 then return OwnedIndexManifestFailure("manifest_budget")
    removed = {}
    affected = {}
    for each uri in uris
        if type(uri) <> "String" and type(uri) <> "roString" then return OwnedIndexManifestFailure("invalid_shard")
        found = false
        for each shard in OwnedIndexField(manifest, "shards")
            if OwnedIndexText(shard, "uri") = uri
                found = true
                removed[uri] = true
                affected[OwnedIndexText(shard, "libraryId")] = true
            end if
        end for
        if not found then return OwnedIndexManifestFailure("invalid_shard")
    end for
    result = ParseJson(FormatJson(manifest))
    retained = []
    totalBytes = 0
    for each shard in OwnedIndexField(result, "shards")
        if not removed.DoesExist(OwnedIndexText(shard, "uri"))
            retained.Push(shard)
            totalBytes = totalBytes + OwnedIndexField(shard, "bytes")
        end if
    end for
    result["shards"] = retained
    result["totalBytes"] = totalBytes
    result["shardCount"] = retained.Count()
    libraries = []
    for each library in OwnedIndexField(result, "libraries")
        libraryId = OwnedIndexText(library, "libraryId")
        intact = OwnedIndexField(library, "coverageValid") and not affected.DoesExist(libraryId)
        libraries.Push(OwnedIndexManifestLibraryState(libraryId, retained, intact))
    end for
    result["libraries"] = libraries
    return {ok: true, manifest: result}
end function

function OwnedIndexManifestExpire(manifest as Dynamic, now as Integer) as Object
    checked = OwnedIndexManifestValidateInternal(manifest, OwnedIndexManifestScope(manifest), now, false)
    if checked.ok <> true then return checked
    uris = []
    for each shard in OwnedIndexField(manifest, "shards")
        if now >= OwnedIndexField(manifest, "expiresAt") or now >= OwnedIndexField(shard, "expiresAt")
            uris.Push(OwnedIndexText(shard, "uri"))
        end if
    end for
    return OwnedIndexManifestEvict(manifest, uris, now)
end function

' Sign-out can purge an expired run. Validate all metadata before constructing
' exact owned-prefix paths. Never forward a caller path or directory listing.
' Publication uses the unique run URI; Rename cannot replace an existing file.
function OwnedIndexManifestPurgePlan(manifest as Dynamic) as Object
    result = []
    checked = OwnedIndexManifestValidateInternal(manifest, OwnedIndexManifestScope(manifest), 0, false)
    if checked.ok <> true then return result
    for each shard in OwnedIndexField(manifest, "shards")
        uri = OwnedIndexManifestShardUri(OwnedIndexText(manifest, "inventoryRunId"), OwnedIndexText(shard, "libraryId"), OwnedIndexField(shard, "offset"))
        result.Push(uri)
        result.Push(uri + ".part")
    end for
    uri = OwnedIndexManifestUri(OwnedIndexText(manifest, "inventoryRunId"))
    result.Push(uri)
    result.Push(uri + ".part")
    return result
end function
