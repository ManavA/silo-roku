' Positive exact-ID joins for <=100 public Services candidates. Account/session,
' manifest bodies, shard records and URLs remain private to the read-only Task.
' Load with OwnedIndex/Manifest and OwnedShardSearch policies; reuse their cache
' scope, path and metadata rules without applying Search's title ranking.
function OwnedServiceMatchValidJob(job as Dynamic) as Boolean
    if not OwnedIndexManifestKeys(job, ["sourceId", "profileId", "requestId", "manifestUri", "candidates"]) then return false
    context = {query: "owned", sourceId: OwnedIndexField(job, "sourceId"), profileId: OwnedIndexField(job, "profileId"), requestId: OwnedIndexField(job, "requestId"), manifestUri: OwnedIndexField(job, "manifestUri")}
    if not OwnedShardSearchValidJob(context) then return false
    candidates = OwnedIndexField(job, "candidates")
    if type(candidates) <> "roArray" then return false
    if candidates.Count() > 100 then return false
    seen = {}
    for each candidate in candidates
        if not OwnedServiceMatchValidCandidate(candidate) then return false
        catalogId = OwnedIndexText(candidate, "catalogId")
        if seen.DoesExist(catalogId) then return false
        seen[catalogId] = true
    end for
    return true
end function

function OwnedServiceMatchExternalId(value as Dynamic, namespace as String) as String
    if type(value) <> "String" and type(value) <> "roString" then return ""
    if namespace = "imdbId"
        if CreateObject("roRegex", "^tt[0-9]{1,16}$", "").IsMatch(value) then return value
        return ""
    end if
    if namespace <> "tmdbId" and namespace <> "tvdbId" then return ""
    if not CreateObject("roRegex", "^[0-9]{1,16}$", "").IsMatch(value) then return ""
    while Len(value) > 1 and Left(value, 1) = "0"
        value = Mid(value, 2)
    end while
    if value = "0" then return ""
    return value
end function

function OwnedServiceMatchValidCandidate(candidate as Dynamic) as Boolean
    if not OwnedIndexManifestKeys(candidate, ["catalogId", "type", "tmdbId", "imdbId", "tvdbId"]) then return false
    kind = OwnedIndexText(candidate, "type")
    if kind <> "movie" and kind <> "show" then return false
    for each name in ["tmdbId", "imdbId", "tvdbId"]
        value = OwnedIndexField(candidate, name)
        if type(value) <> "String" and type(value) <> "roString" then return false
        if value <> "" and OwnedServiceMatchExternalId(value, name) <> value then return false
    end for
    identity = OwnedIndexText(candidate, "tmdbId")
    if identity = "" and OwnedIndexText(candidate, "imdbId") <> "" then identity = "imdb:" + OwnedIndexText(candidate, "imdbId")
    if identity = "" and OwnedIndexText(candidate, "tvdbId") <> "" then identity = "tvdb:" + OwnedIndexText(candidate, "tvdbId")
    if identity = "" then return false
    return OwnedIndexText(candidate, "catalogId") = "metadata:" + kind + ":" + identity
end function

function OwnedServiceMatchFailure(code as String, status = "retryable" as String) as Object
    allowed = ["invalid_job", "auth_required", "session_changed", "cancelled", "invalid_manifest", "invalid_shard", "inventory_missing", "manifest_budget", "shard_budget", "match_budget", "task_failed"]
    safe = "invalid_manifest"
    for each name in allowed
        if name = code then safe = name
    end for
    if status <> "cancelled" then status = "retryable"
    return {ok: false, status: status, errorCode: safe}
end function

function OwnedServiceMatchState(candidates as Object, sourceId as String) as Object
    state = {sourceId: sourceId, candidates: candidates, lookup: {}, matched: {}, invalidRecord: false, scannedShards: 0, scannedRecords: 0, scannedBytes: 0}
    if candidates.Count() > 0
        for index = 0 to candidates.Count() - 1
            candidate = candidates[index]
            for each name in ["tmdbId", "imdbId", "tvdbId"]
                value = OwnedIndexText(candidate, name)
                if value <> ""
                    key = OwnedIndexText(candidate, "type") + ":" + name + ":" + value
                    if not state.lookup.DoesExist(key) then state.lookup[key] = []
                    state.lookup[key].Push(index)
                end if
            end for
        end for
    end if
    return state
end function

' The worker validated this one <=48-record shard before reaching the join.
' Candidate buckets avoid comparing every public seed with every owned record.
function OwnedServiceMatchAccumulate(state as Object, records as Object) as Object
    if records.Count() > 48
        state.invalidRecord = true
        return state
    end if
    for each record in records
        itemId = OwnedIndexText(record, "itemId")
        if not CreateObject("roRegex", "^[0-9]{1,128}$", "").IsMatch(itemId)
            state.invalidRecord = true
            return state
        end if
        kind = OwnedIndexText(record, "type")
        ids = {}
        for each name in ["tmdbId", "imdbId", "tvdbId"]
            ids[name] = OwnedServiceMatchExternalId(OwnedIndexField(record, name), name)
        end for
        inspected = {}
        for each name in ["tmdbId", "imdbId", "tvdbId"]
            key = kind + ":" + name + ":" + ids[name]
            if ids[name] <> "" and state.lookup.DoesExist(key)
                for each index in state.lookup[key]
                    ordinal = index.ToStr()
                    if not inspected.DoesExist(ordinal) and not state.matched.DoesExist(ordinal)
                        inspected[ordinal] = true
                        candidate = state.candidates[index]
                        conflict = false
                        for each namespace in ["tmdbId", "imdbId", "tvdbId"]
                            wanted = OwnedIndexText(candidate, namespace)
                            if wanted <> "" and ids[namespace] <> "" and wanted <> ids[namespace] then conflict = true
                        end for
                        if not conflict
                            card = {provider: "plex", sourceId: state.sourceId, itemId: itemId, title: Left(OwnedIndexText(record, "title"), 120), type: kind, year: OwnedIndexField(record, "year", 0), tmdbId: ids.tmdbId, imdbId: ids.imdbId, tvdbId: ids.tvdbId, owned: true, canPlay: kind = "movie", availability: "owned", catalogId: OwnedIndexText(candidate, "catalogId")}
                            state.matched[ordinal] = card
                        end if
                    end if
                end for
            end if
        end for
    end for
    return state
end function

function OwnedServiceMatchResults(state as Object, reason = "observed_subset" as String) as Object
    items = []
    seen = {}
    if state.candidates.Count() > 0
        for index = 0 to state.candidates.Count() - 1
            ordinal = index.ToStr()
            if state.matched.DoesExist(ordinal)
                card = state.matched[ordinal]
                if not seen.DoesExist(card.itemId)
                    seen[card.itemId] = true
                    items.Push(card)
                end if
            end if
        end for
    end if
    if reason <> "match_budget" then reason = "observed_subset"
    coverage = {partial: true, sourceInventoryComplete: false, authoritativeAbsence: false, candidateCount: state.candidates.Count(), matchedCandidates: state.matched.Count(), scannedShards: state.scannedShards, scannedRecords: state.scannedRecords, scannedBytes: state.scannedBytes, reason: reason}
    return {ok: true, status: "results", items: items, coverage: coverage}
end function
