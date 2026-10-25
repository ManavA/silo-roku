' Compact owned-title inventory, one Plex raw-slot window at a time. A terminal
' page is not a complete inventory or an atomic snapshot of the server library.
function OwnedIndexField(data as Dynamic, key as String, fallback = invalid as Dynamic) as Dynamic
    if type(data) <> "roAssociativeArray" then return fallback
    foldedKey = LCase(key)
    for each name in data.Keys()
        if LCase(name) = foldedKey
            return data[name]
        end if
    end for
    return fallback
end function

function OwnedIndexExactField(data as Dynamic, key as String, fallback = invalid as Dynamic) as Dynamic
    if type(data) <> "roAssociativeArray" then return fallback
    for each name in data.Keys()
        if name = key
            return data[name]
        end if
    end for
    return fallback
end function

function OwnedIndexHasField(data as Dynamic, key as String) as Boolean
    if type(data) <> "roAssociativeArray" then return false
    for each name in data.Keys()
        if LCase(name) = LCase(key) then return true
    end for
    return false
end function

function OwnedIndexText(data as Dynamic, key as String) as String
    value = OwnedIndexField(data, key)
    if type(value) = "String" or type(value) = "roString" then return value
    return ""
end function

function OwnedIndexInteger(value as Dynamic, fallback = -1 as Integer) as Integer
    kind = type(value)
    if kind = "String" or kind = "roString"
        if not CreateObject("roRegex", "^[0-9]{1,10}$", "").IsMatch(value) then return fallback
        number = Val(value)
    else if kind = "Integer" or kind = "LongInteger" or kind = "Float" or kind = "Double" or kind = "roInt" or kind = "roInteger" or kind = "roLongInteger" or kind = "roFloat" or kind = "roDouble"
        number = value
    else
        return fallback
    end if
    if number < 0 or number > 2147483647 then return fallback
    if Int(number) <> number then return fallback
    return Int(number)
end function

' Wire responses may encode a count as text, but a persisted shard has a
' canonical JSON schema. Reject text before any arithmetic on cached data.
function OwnedIndexStoredNumber(value as Dynamic) as Boolean
    kind = type(value)
    return kind = "Integer" or kind = "LongInteger" or kind = "Float" or kind = "Double" or kind = "roInt" or kind = "roInteger" or kind = "roLongInteger" or kind = "roFloat" or kind = "roDouble"
end function

function OwnedIndexByteCount(body as String) as Integer
    bytes = CreateObject("roByteArray")
    bytes.FromAsciiString(body)
    return bytes.Count()
end function

function OwnedIndexKeys(data as Dynamic, allowed as Object) as Boolean
    if type(data) <> "roAssociativeArray" then return false
    keys = data.Keys()
    if keys.Count() = 0 then return true
    allowedKeys = {}
    for each name in allowed
        allowedKeys[LCase(name)] = true
    end for
    for each key in keys
        if not allowedKeys.DoesExist(LCase(key)) then return false
    end for
    return true
end function

function OwnedIndexIdentifier(value as String, allowEmpty = false as Boolean) as Boolean
    if allowEmpty and value = "" then return true
    return CreateObject("roRegex", "^[A-Za-z0-9._:-]{1,128}$", "").IsMatch(value)
end function

function OwnedIndexValidJob(job as Dynamic) as Boolean
    if not OwnedIndexKeys(job, ["provider", "sourceId", "profileId", "inventoryRunId", "libraryId", "offset", "limit", "requestId", "writeShard"]) then return false
    if OwnedIndexText(job, "provider") <> "plex" then return false
    if not CreateObject("roRegex", "^plex:[A-Za-z0-9._:-]{1,160}$", "").IsMatch(OwnedIndexText(job, "sourceId")) then return false
    profile = OwnedIndexField(job, "profileId")
    if type(profile) <> "String" and type(profile) <> "roString" then return false
    if not OwnedIndexIdentifier(profile, true) then return false
    if not CreateObject("roRegex", "^[A-Za-z0-9_-]{1,64}$", "").IsMatch(OwnedIndexText(job, "inventoryRunId")) then return false
    if not CreateObject("roRegex", "^[A-Za-z0-9_-]{1,64}$", "").IsMatch(OwnedIndexText(job, "libraryId")) then return false
    offset = OwnedIndexInteger(OwnedIndexField(job, "offset"))
    if offset < 0 or offset > 2147483599 then return false
    if OwnedIndexInteger(OwnedIndexField(job, "limit", 48)) <> 48 then return false
    requestId = OwnedIndexField(job, "requestId")
    if type(requestId) = "String" or type(requestId) = "roString"
        if not OwnedIndexIdentifier(requestId) then return false
    else
        if OwnedIndexInteger(requestId) < 0 then return false
    end if
    writeShard = OwnedIndexField(job, "writeShard", false)
    return type(writeShard) = "Boolean" or type(writeShard) = "roBoolean"
end function

function OwnedIndexFailure(code as String, status = "retryable" as String) as Object
    allowed = ["invalid_job", "invalid_response", "invalid_request", "invalid_server", "client_identity_missing", "auth_required", "session_changed", "cancelled", "decode_error", "page_mismatch", "page_budget", "response_too_large", "duplicate_identity", "invalid_record", "identity_conflict", "storage_error", "invalid_shard", "shard_budget", "network_error", "network_unavailable", "network_timeout", "forbidden", "not_found", "rate_limited", "server_error", "http_error", "task_failed"]
    safe = "invalid_response"
    for each name in allowed
        if name = code then safe = name
    end for
    return {ok: false, status: status, errorCode: safe}
end function

function OwnedIndexSessionMatches(job as Object, original as Object, current as Object, revision as Integer, currentRevision as Integer) as Boolean
    if revision < 0 or revision <> currentRevision then return false
    if OwnedIndexText(original, "sourceId") <> OwnedIndexText(job, "sourceId") then return false
    if OwnedIndexText(original, "profileId") <> OwnedIndexText(job, "profileId") then return false
    if not OwnedIndexIdentifier(OwnedIndexText(original, "accountId")) then return false
    for each key in ["sourceId", "profileId", "accountId", "baseUrl", "token", "accountToken", "clientId"]
        if OwnedIndexText(original, key) <> OwnedIndexText(current, key) then return false
    end for
    return true
end function

function OwnedIndexRecord(raw as Dynamic) as Object
    if type(raw) <> "roAssociativeArray" then return OwnedIndexFailure("invalid_record")
    mediaType = OwnedIndexText(raw, "type")
    if mediaType <> "movie" and mediaType <> "show"
        if mediaType = "" then return OwnedIndexFailure("invalid_record")
        return {ok: true, skipped: true}
    end if
    itemId = OwnedIndexText(raw, "ratingKey")
    title = OwnedIndexText(raw, "title")
    if not OwnedIndexIdentifier(itemId) then return OwnedIndexFailure("invalid_record")
    if Len(title) = 0 or Len(title) > 256 then return OwnedIndexFailure("invalid_record")
    if CreateObject("roRegex", "[\x00-\x1f\x7f]", "").IsMatch(title) then return OwnedIndexFailure("invalid_record")
    year = OwnedIndexInteger(OwnedIndexField(raw, "year", 0))
    if year < 0 or year > 9999 then return OwnedIndexFailure("invalid_record")
    record = {itemId: itemId, type: mediaType, title: title, year: year, tmdbId: "", imdbId: "", tvdbId: ""}
    guids = OwnedIndexExactField(raw, "Guid", [])
    if type(guids) <> "roArray" then return OwnedIndexFailure("invalid_record")
    if guids.Count() > 16 then return OwnedIndexFailure("invalid_record")
    legacy = OwnedIndexExactField(raw, "guid", "")
    if type(legacy) <> "String" and type(legacy) <> "roString" then return OwnedIndexFailure("invalid_record")
    candidates = []
    if legacy <> "" then candidates.Push(legacy)
    for each entry in guids
        if type(entry) <> "roAssociativeArray" then return OwnedIndexFailure("invalid_record")
        candidates.Push(OwnedIndexText(entry, "id"))
    end for
    for each guid in candidates
        field = ""
        identity = ""
        if CreateObject("roRegex", "^tmdb://[0-9]{1,16}$", "").IsMatch(guid)
            field = "tmdbId"
            identity = Mid(guid, 8)
        else if CreateObject("roRegex", "^tvdb://[0-9]{1,16}$", "").IsMatch(guid)
            field = "tvdbId"
            identity = Mid(guid, 8)
        else if CreateObject("roRegex", "^imdb://tt[0-9]{1,16}$", "").IsMatch(guid)
            field = "imdbId"
            identity = Mid(guid, 8)
        end if
        if field <> ""
            existing = OwnedIndexText(record, field)
            if existing <> "" and existing <> identity then return OwnedIndexFailure("identity_conflict")
            record[field] = identity
        end if
    end for
    return {ok: true, skipped: false, record: record}
end function

function OwnedIndexDecodePage(job as Object, body as String) as Object
    if not OwnedIndexValidJob(job) then return OwnedIndexFailure("invalid_job")
    if Len(body) > 262144 then return OwnedIndexFailure("response_too_large")
    if OwnedIndexByteCount(body) > 262144 then return OwnedIndexFailure("response_too_large")
    decoded = ParseJson(body)
    container = OwnedIndexField(decoded, "MediaContainer")
    if type(container) <> "roAssociativeArray" then return OwnedIndexFailure("decode_error")
    offset = OwnedIndexInteger(OwnedIndexField(job, "offset"))
    if OwnedIndexInteger(OwnedIndexField(container, "offset", offset)) <> offset then return OwnedIndexFailure("page_mismatch")
    metadata = OwnedIndexField(container, "Metadata")
    if type(metadata) <> "roArray" then return OwnedIndexFailure("decode_error")
    rawCount = metadata.Count()
    if rawCount > 48 then return OwnedIndexFailure("page_budget")
    if OwnedIndexInteger(OwnedIndexField(container, "size", rawCount)) <> rawCount then return OwnedIndexFailure("page_mismatch")
    totalValue = OwnedIndexField(container, "totalSize")
    totalKnown = OwnedIndexHasField(container, "totalSize")
    total = offset + rawCount
    if totalKnown
        total = OwnedIndexInteger(totalValue)
        if total < offset + rawCount then return OwnedIndexFailure("page_mismatch")
        if rawCount = 0 and total > offset then return OwnedIndexFailure("page_mismatch")
    end if
    records = []
    identities = {}
    externalIdsComplete = true
    for each raw in metadata
        compact = OwnedIndexRecord(raw)
        if compact.ok <> true then return compact
        if not compact.skipped
            record = compact.record
            if identities.DoesExist(record.itemId) then return OwnedIndexFailure("duplicate_identity")
            identities[record.itemId] = true
            records.Push(record)
            if record.tmdbId = "" and record.imdbId = "" and record.tvdbId = "" then externalIdsComplete = false
        end if
    end for
    hasMore = false
    if totalKnown
        hasMore = offset + rawCount < total
    else
        hasMore = rawCount = 48
    end if
    nextOffset = -1
    if hasMore then nextOffset = offset + rawCount
    page = {offset: offset, pageSize: 48, rawCount: rawCount, totalSize: total, totalKnown: totalKnown, hasMore: hasMore, nextOffset: nextOffset, pageTerminal: not hasMore, externalIdsComplete: externalIdsComplete, records: records}
    return {ok: true, page: page}
end function

function OwnedIndexValidCompactRecord(record as Dynamic) as Boolean
    if not OwnedIndexKeys(record, ["itemId", "type", "title", "year", "tmdbId", "imdbId", "tvdbId"]) then return false
    if record.Count() <> 7 then return false
    fields = {}
    for each key in record.Keys()
        fields[LCase(key)] = record[key]
    end for
    for each name in ["itemid", "type", "title", "tmdbid", "imdbid", "tvdbid"]
        kind = type(fields[name])
        if kind <> "String" and kind <> "roString" then return false
    end for
    if not OwnedIndexStoredNumber(fields.year) then return false
    year = OwnedIndexInteger(fields.year)
    if year < 0 or year > 9999 then return false
    if fields.type <> "movie" and fields.type <> "show" then return false
    if not OwnedIndexIdentifier(fields.itemid) then return false
    if Len(fields.title) = 0 or Len(fields.title) > 256 then return false
    if CreateObject("roRegex", "[\x00-\x1f\x7f]", "").IsMatch(fields.title) then return false
    for each name in ["tmdbid", "imdbid", "tvdbid"]
        value = fields[name]
        if value <> ""
            pattern = "^[0-9]{1,16}$"
            if name = "imdbid" then pattern = "^tt[0-9]{1,16}$"
            if not CreateObject("roRegex", pattern, "").IsMatch(value) then return false
        end if
    end for
    return true
end function

function OwnedIndexValidPage(page as Dynamic, job as Object) as Boolean
    if not OwnedIndexKeys(page, ["offset", "pageSize", "rawCount", "totalSize", "totalKnown", "hasMore", "nextOffset", "pageTerminal", "externalIdsComplete", "records"]) then return false
    if page.Count() <> 10 then return false
    for each name in ["offset", "pageSize", "rawCount", "totalSize", "nextOffset"]
        if not OwnedIndexStoredNumber(OwnedIndexField(page, name)) then return false
    end for
    if OwnedIndexInteger(OwnedIndexField(page, "offset")) <> OwnedIndexInteger(OwnedIndexField(job, "offset")) then return false
    if OwnedIndexInteger(OwnedIndexField(page, "pageSize")) <> 48 then return false
    count = OwnedIndexInteger(OwnedIndexField(page, "rawCount"))
    if count < 0 or count > 48 then return false
    records = OwnedIndexField(page, "records")
    if type(records) <> "roArray" then return false
    if records.Count() > count then return false
    for each name in ["totalKnown", "hasMore", "pageTerminal", "externalIdsComplete"]
        value = OwnedIndexField(page, name)
        if type(value) <> "Boolean" and type(value) <> "roBoolean" then return false
    end for
    boundary = page.offset + count
    total = OwnedIndexInteger(OwnedIndexField(page, "totalSize"))
    if total < boundary then return false
    if count = 0 and total > boundary then return false
    expectedMore = count = 48
    if page.totalKnown then expectedMore = boundary < total
    if not page.totalKnown and total <> boundary then return false
    if page.hasMore <> expectedMore or page.pageTerminal <> not expectedMore then return false
    if expectedMore
        if page.nextOffset <> boundary then return false
    else
        if page.nextOffset <> -1 then return false
    end if
    seen = {}
    external = true
    for each record in records
        if not OwnedIndexValidCompactRecord(record) then return false
        if seen.DoesExist(record.itemId) then return false
        seen[record.itemId] = true
        if record.tmdbId = "" and record.imdbId = "" and record.tvdbId = "" then external = false
    end for
    return page.externalIdsComplete = external
end function

function OwnedIndexShard(job as Object, page as Object, session as Object, revision as Integer, now as Integer) as Object
    if not OwnedIndexValidJob(job) then return OwnedIndexFailure("invalid_job")
    if not OwnedIndexValidPage(page, job) then return OwnedIndexFailure("invalid_shard")
    if not OwnedIndexSessionMatches(job, session, session, revision, revision) then return OwnedIndexFailure("session_changed")
    if now < 1 or now > 2147480047 then return OwnedIndexFailure("invalid_shard")
    data = {schema: 1, provider: "plex", sourceId: OwnedIndexText(job, "sourceId"), profileId: OwnedIndexText(job, "profileId"), accountId: OwnedIndexText(session, "accountId"), sessionRevision: revision, inventoryRunId: OwnedIndexText(job, "inventoryRunId"), libraryId: OwnedIndexText(job, "libraryId"), createdAt: now, expiresAt: now + 3600}
    for each key in page.Keys()
        data[key] = page[key]
    end for
    body = FormatJson(data)
    bytes = OwnedIndexByteCount(body)
    if bytes > 65536 then return OwnedIndexFailure("shard_budget")
    uri = "cachefs:/owned-" + OwnedIndexText(job, "inventoryRunId") + "-" + OwnedIndexText(job, "libraryId") + "-" + page.offset.ToStr() + ".json"
    return {ok: true, uri: uri, body: body, bytes: bytes}
end function

function OwnedIndexValidateShard(body as String, job as Object, session as Object, revision as Integer, now as Integer) as Object
    if not OwnedIndexValidJob(job) then return OwnedIndexFailure("invalid_shard")
    if Len(body) > 65536 then return OwnedIndexFailure("shard_budget")
    if OwnedIndexByteCount(body) > 65536 then return OwnedIndexFailure("shard_budget")
    data = ParseJson(body)
    headers = ["schema", "provider", "sourceId", "profileId", "accountId", "sessionRevision", "inventoryRunId", "libraryId", "createdAt", "expiresAt"]
    fields = ["offset", "pageSize", "rawCount", "totalSize", "totalKnown", "hasMore", "nextOffset", "pageTerminal", "externalIdsComplete", "records"]
    allowed = []
    allowed.Append(headers)
    allowed.Append(fields)
    if not OwnedIndexKeys(data, allowed) then return OwnedIndexFailure("invalid_shard")
    if data.Count() <> 20 then return OwnedIndexFailure("invalid_shard")
    for each name in ["schema", "sessionRevision", "createdAt", "expiresAt"]
        if not OwnedIndexStoredNumber(OwnedIndexField(data, name)) then return OwnedIndexFailure("invalid_shard")
    end for
    if OwnedIndexInteger(OwnedIndexField(data, "schema")) <> 1 then return OwnedIndexFailure("invalid_shard")
    for each key in ["provider", "sourceId", "profileId", "inventoryRunId", "libraryId"]
        if OwnedIndexText(data, key) <> OwnedIndexText(job, key) then return OwnedIndexFailure("invalid_shard")
    end for
    if OwnedIndexText(data, "accountId") <> OwnedIndexText(session, "accountId") then return OwnedIndexFailure("invalid_shard")
    if OwnedIndexInteger(OwnedIndexField(data, "sessionRevision")) <> revision then return OwnedIndexFailure("invalid_shard")
    createdAt = OwnedIndexInteger(OwnedIndexField(data, "createdAt"))
    expiresAt = OwnedIndexInteger(OwnedIndexField(data, "expiresAt"))
    if createdAt < 1 or createdAt > now or now >= expiresAt or expiresAt - createdAt <> 3600 then return OwnedIndexFailure("invalid_shard")
    page = {}
    for each key in fields
        page[key] = OwnedIndexField(data, key)
    end for
    if not OwnedIndexValidPage(page, job) then return OwnedIndexFailure("invalid_shard")
    return {ok: true}
end function
