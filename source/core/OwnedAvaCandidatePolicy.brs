' Positive AVA facts from one validated shard at a time. Load with owned-index,
' Metadata adapter/UI and shared cached-reader policies. Never establish absence.
function OwnedAvaCandidateValidJob(job as Dynamic) as Boolean
    if not OwnedIndexManifestKeys(job, ["sourceId", "profileId", "requestId", "manifestUri"]) then return false
    searchJob = {query: "owned", sourceId: OwnedIndexField(job, "sourceId"), profileId: OwnedIndexField(job, "profileId"), requestId: OwnedIndexField(job, "requestId"), manifestUri: OwnedIndexField(job, "manifestUri")}
    return OwnedShardSearchValidJob(searchJob)
end function

function OwnedAvaCandidateFailure(code as String, status = "retryable" as String) as Object
    allowed = ["invalid_job", "auth_required", "session_changed", "cancelled", "invalid_manifest", "invalid_shard", "inventory_missing", "manifest_budget", "shard_budget", "candidate_budget", "task_failed"]
    safe = "invalid_manifest"
    for each name in allowed
        if name = code then safe = name
    end for
    if status <> "cancelled" then status = "retryable"
    return {ok: false, status: status, errorCode: safe}
end function

function OwnedAvaCandidateState(sourceId as String, totalRecords as Integer) as Object
    bad = totalRecords < 0 or totalRecords > 9600 or not HmOwnedSource(sourceId) or Left(sourceId, 5) <> "plex:"
    return {sourceId: sourceId, totalRecords: totalRecords, inspected: 0, nextSample: 0, items: [], invalidRecord: bad, scannedShards: 0, scannedRecords: 0, scannedBytes: 0}
end function

function OwnedAvaCandidateAccumulate(state as Object, records as Object) as Object
    if state.invalidRecord then return state
    if records.Count() > 48
        state["invalidRecord"] = true
        return state
    end if
    for each record in records
        if not OwnedIndexValidCompactRecord(record)
            state["invalidRecord"] = true
            return state
        end if
        position = state.inspected
        state.inspected++
        if state.inspected > state.totalRecords or state.inspected > 9600
            state["invalidRecord"] = true
            return state
        end if
        ' Evenly spaced positions observe later pages and sections without keeping
        ' all records. A deadline still returns only the already validated subset.
        selected = state.totalRecords <= 180
        if not selected and state.nextSample < 180
            selected = position >= Int(state.nextSample * state.totalRecords / 180)
        end if
        if selected and state.items.Count() < 180
            state["nextSample"] += 1
            raw = {provider: "plex", sourceId: state.sourceId, itemId: OwnedIndexText(record, "itemId"), title: OwnedIndexText(record, "title"), type: OwnedIndexText(record, "type"), year: OwnedIndexField(record, "year"), tmdbId: OwnedIndexText(record, "tmdbId"), imdbId: OwnedIndexText(record, "imdbId"), tvdbId: OwnedIndexText(record, "tvdbId")}
            card = HmUiOwnedCard(raw, "plex", state.sourceId)
            if card <> invalid
                if Len(card.title) >= 2
                    ' Rebuild an explicit public whitelist, including safe native
                    ' identity for scene supersession; the AVA POST removes it.
                    state.items.Push({provider: "plex", sourceId: state.sourceId, itemId: card.itemId, title: card.title, type: card.type, year: card.year, tmdbId: card.tmdbId, imdbId: card.imdbId, tvdbId: card.tvdbId, owned: true})
                end if
            end if
        end if
    end for
    return state
end function

function OwnedAvaCandidateResults(state as Object, reason = "observed_subset" as String) as Object
    if reason <> "candidate_budget" then reason = "observed_subset"
    coverage = {partial: true, sourceInventoryComplete: false, authoritativeAbsence: false, scannedShards: state.scannedShards, scannedRecords: state.scannedRecords, scannedBytes: state.scannedBytes, reason: reason}
    return {ok: true, status: "results", items: state.items, coverage: coverage}
end function
