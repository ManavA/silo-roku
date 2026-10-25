' Search retains at most 100 owned cards while observing one validated 48-slot
' cache shard at a time. Its positive evidence never establishes source absence.
function OwnedShardSearchValidJob(job as Dynamic) as Boolean
    if not OwnedIndexKeys(job, ["query", "sourceId", "profileId", "requestId", "manifestUri"]) then return false
    if job.Count() <> 5 then return false
    query = OwnedIndexField(job, "query")
    if type(query) <> "String" and type(query) <> "roString" then return false
    if Len(query) < 2 or Len(query) > 120 then return false
    if CreateObject("roRegex", "[\x00-\x1f\x7f]", "").IsMatch(query) then return false
    context = SearchQueryContext(query)
    if Len(context.text) < 2 then return false
    if not CreateObject("roRegex", "^plex:[A-Za-z0-9._:-]{1,160}$", "").IsMatch(OwnedIndexText(job, "sourceId")) then return false
    profile = OwnedIndexField(job, "profileId")
    if type(profile) <> "String" and type(profile) <> "roString" then return false
    if not OwnedIndexIdentifier(profile, true) then return false
    requestId = OwnedIndexField(job, "requestId")
    if type(requestId) = "String" or type(requestId) = "roString"
        if not OwnedIndexIdentifier(requestId) then return false
    else
        if OwnedIndexInteger(requestId) < 0 then return false
    end if
    return OwnedShardSearchRunId(OwnedIndexText(job, "manifestUri")) <> ""
end function

function OwnedShardSearchRunId(path as String) as String
    if not CreateObject("roRegex", "^cachefs:/owned-manifest-[A-Za-z0-9_-]{1,64}[.]json$", "").IsMatch(path) then return ""
    prefix = "cachefs:/owned-manifest-"
    return Mid(path, Len(prefix) + 1, Len(path) - Len(prefix) - 5)
end function

function OwnedShardSearchPathAllowed(path as String) as Boolean
    if OwnedShardSearchRunId(path) <> "" then return true
    return CreateObject("roRegex", "^cachefs:/owned-[A-Za-z0-9_-]{1,64}-[A-Za-z0-9_-]{1,64}-[0-9]{1,10}[.]json$", "").IsMatch(path)
end function

function OwnedShardSearchFailure(code as String, status = "retryable" as String) as Object
    allowed = ["invalid_job", "auth_required", "session_changed", "cancelled", "invalid_manifest", "invalid_shard", "inventory_missing", "manifest_budget", "shard_budget", "search_budget", "task_failed"]
    safe = "invalid_manifest"
    for each name in allowed
        if name = code then safe = name
    end for
    if status <> "cancelled" then status = "retryable"
    return {ok: false, status: status, errorCode: safe}
end function

function OwnedShardSearchScope(job as Object, session as Object, revision as Integer) as Object
    return {provider: "plex", sourceId: OwnedIndexText(job, "sourceId"), profileId: OwnedIndexText(job, "profileId"), accountId: OwnedIndexText(session, "accountId"), sessionRevision: revision, inventoryRunId: OwnedShardSearchRunId(OwnedIndexText(job, "manifestUri"))}
end function

function OwnedShardSearchShardJob(job as Object, entry as Object) as Object
    return {provider: "plex", sourceId: OwnedIndexText(job, "sourceId"), profileId: OwnedIndexText(job, "profileId"), inventoryRunId: OwnedShardSearchRunId(OwnedIndexText(job, "manifestUri")), libraryId: OwnedIndexText(entry, "libraryId"), offset: OwnedIndexField(entry, "offset"), limit: 48, requestId: OwnedIndexField(job, "requestId")}
end function

' Both inputs have already passed their schema validators. Match the actual
' shard to every retained manifest field, including exact native item order.
function OwnedShardSearchMetadataMatches(data as Object, entry as Object) as Boolean
    for each name in ["libraryId", "offset", "rawCount", "nextOffset", "createdAt", "expiresAt"]
        if OwnedIndexField(data, name) <> OwnedIndexField(entry, name) then return false
    end for
    if OwnedIndexField(data, "pageTerminal") <> OwnedIndexField(entry, "terminal") then return false
    if OwnedIndexField(data, "externalIdsComplete") <> OwnedIndexField(entry, "identityComplete") then return false
    records = OwnedIndexField(data, "records")
    ids = OwnedIndexField(entry, "itemIds")
    if type(records) <> "roArray" or type(ids) <> "roArray" then return false
    if records.Count() <> OwnedIndexField(entry, "recordCount") or records.Count() <> ids.Count() then return false
    if records.Count() > 0
        for index = 0 to records.Count() - 1
            if OwnedIndexText(records[index], "itemId") <> ids[index] then return false
        end for
    end if
    return true
end function

function OwnedShardSearchState(query as String, sourceId as String) as Object
    return {sourceId: sourceId, context: SearchQueryContext(query), ranked: [], inspected: 0, invalidRecord: false, scannedShards: 0, scannedRecords: 0, scannedBytes: 0}
end function


' Project one record once, preserving the first folded key and text defaults.
' Unknown/private fields never enter the bounded seven-field view.
function OwnedShardSearchRecordFields(record as Dynamic, allowed as Object, canonicalKeys as Object) as Object
    fields = {}
    if type(record) <> "roAssociativeArray" then return fields
    keys = record.Keys()
    canonical = keys.Count() = 7
    if canonical
        for index = 0 to 6
            if keys[index] <> canonicalKeys[index]
                canonical = false
                exit for
            end if
        end for
    end if
    if canonical then return {itemid:record["itemId"],type:record["type"],title:record["title"],year:record["year"],tmdbid:record["tmdbId"],imdbid:record["imdbId"],tvdbid:record["tvdbId"]}
    for each key in keys
        folded = LCase(key)
        if allowed.DoesExist(folded)
            if not fields.DoesExist(folded) then fields[folded] = record[key]
        end if
    end for
    return fields
end function

function OwnedShardSearchRecordText(fields as Object, key as String) as String
    value = fields[key]
    kind = type(value)
    if kind = "String" or kind = "roString" then return value
    return ""
end function


' The owned projection supplies no resume/watched/provider fields. Preserve the
' ordinary card value guards without rebuilding an AA for generic field reads.
function OwnedShardSearchCard(fields as Object, sourceId as String) as Dynamic
    if Left(sourceId,5) <> "plex:" or Len(sourceId) <= 5 then return invalid
    itemId = OwnedShardSearchRecordText(fields,"itemid")
    title = Left(OwnedShardSearchRecordText(fields,"title").Trim(),120)
    kind = OwnedShardSearchRecordText(fields,"type")
    if title = "" then return invalid
    if kind <> "movie" and kind <> "show" and kind <> "series" and kind <> "episode" and kind <> "season" and kind <> "collection" then return invalid
    if not SearchNativeId(itemId,"plex") then return invalid
    card = {provider:"plex",sourceId:sourceId,itemId:itemId,title:title,type:kind}
    year = fields.year
    if year = invalid then year = 0
    yearKind = type(year)
    if yearKind = "Integer" or yearKind = "roInt" or yearKind = "roInteger" then card["year"] = year
    return card
end function

function OwnedShardSearchAccumulate(state as Object, records as Object) as Object
    ' The manifest and shard contracts limit each records array to 48 entries.
    if records.Count() > 48
        state.invalidRecord = true
        return state
    end if
    allowedFields = {itemid:true,type:true,title:true,year:true,tmdbid:true,imdbid:true,tvdbid:true}
    canonicalKeys = ["imdbId","itemId","title","tmdbId","tvdbId","type","year"]
    for each record in records
        state.inspected++
        if state.inspected > 9600 then exit for
        fields = OwnedShardSearchRecordFields(record,allowedFields,canonicalKeys)
        card = OwnedShardSearchCard(fields, state.sourceId)
        if card = invalid
            state.invalidRecord = true
            return state
        end if
        for each name in ["tmdbId", "imdbId", "tvdbId"]
            card[name] = OwnedShardSearchRecordText(fields,LCase(name))
        end for
        bucket = SearchTitleBucket(card.title, state.context)
        if bucket < 4
            ' The volatile 500-card policy has a three-digit arrival suffix.
            ' Preserve its priority and extend stability for all 9600 records.
            priority = Left(SearchRankKey(card, bucket, state.context.tokens.Count(), state.inspected), 8)
            rank = priority + Right("00000" + state.inspected.ToStr(), 5)
            keep = true
            if state.ranked.Count() >= 100 then keep = rank < state.ranked[99].sortkey
            if keep
                state.ranked.Push({sortkey: rank, card: card})
                state.ranked.SortBy("sortkey")
                if state.ranked.Count() > 100 then state.ranked.Pop()
            end if
        end if
    end for
    return state
end function

function OwnedShardSearchResults(state as Object, reason = "observed_subset" as String) as Object
    items = []
    for each entry in state.ranked
        items.Push(entry.card)
    end for
    if reason <> "search_budget" then reason = "observed_subset"
    coverage = {partial: true, sourceInventoryComplete: false, authoritativeAbsence: false, scannedShards: state.scannedShards, scannedRecords: state.scannedRecords, scannedBytes: state.scannedBytes, reason: reason}
    return {ok: true, status: "results", items: items, coverage: coverage}
end function
