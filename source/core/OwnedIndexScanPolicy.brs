' Public scan job/envelope policy. Account identity, revision, wire bodies and
' compact records stay inside the Task. Coverage never establishes absence.
function OwnedIndexScanValidJob(job as Dynamic) as Boolean
    if not OwnedIndexManifestKeys(job, ["provider", "sourceId", "profileId", "requestId", "inventoryRunId"]) then return false
    page = {provider: OwnedIndexField(job, "provider"), sourceId: OwnedIndexField(job, "sourceId"), profileId: OwnedIndexField(job, "profileId"), requestId: OwnedIndexField(job, "requestId"), inventoryRunId: OwnedIndexField(job, "inventoryRunId"), libraryId: "0", offset: 0, limit: 48}
    return OwnedIndexValidJob(page)
end function

function OwnedIndexScanDecodeSections(body as String) as Object
    if Len(body) > 262144 then return OwnedIndexFailure("response_too_large")
    if OwnedIndexByteCount(body) > 262144 then return OwnedIndexFailure("response_too_large")
    decoded = ParseJson(body)
    container = OwnedIndexField(decoded, "MediaContainer")
    if type(container) <> "roAssociativeArray" then return OwnedIndexFailure("decode_error")
    directories = OwnedIndexField(container, "Directory")
    if type(directories) <> "roArray" then return OwnedIndexFailure("decode_error")
    sections = []
    seen = {}
    for each directory in directories
        if sections.Count() >= 24 then exit for
        if type(directory) <> "roAssociativeArray" then return OwnedIndexFailure("decode_error")
        kind = OwnedIndexText(directory, "type")
        if kind = "movie" or kind = "show"
            id = OwnedIndexText(directory, "key")
            if not CreateObject("roRegex", "^[A-Za-z0-9_-]{1,64}$", "").IsMatch(id) then return OwnedIndexFailure("decode_error")
            if seen.DoesExist(id) then return OwnedIndexFailure("duplicate_identity")
            seen[id] = true
            sections.Push({libraryId: id, type: kind})
        end if
    end for
    return {ok: true, discovery: {sections: sections, truncated: directories.Count() >= 24 or sections.Count() >= 24}}
end function

function OwnedIndexScanPathAllowed(path as String) as Boolean
    if OwnedIndexPointerPathAllowed(path) then return true
    shard = CreateObject("roRegex", "^cachefs:/owned-[A-Za-z0-9_-]{1,64}-[A-Za-z0-9_-]{1,64}-[0-9]{1,10}[.]json([.]part)?$", "").IsMatch(path)
    manifest = CreateObject("roRegex", "^cachefs:/owned-manifest-[A-Za-z0-9_-]{1,64}[.]json([.]part)?$", "").IsMatch(path)
    return shard or manifest
end function

function OwnedIndexScanFileLimit(path as String) as Integer
    if not OwnedIndexScanPathAllowed(path) then return 0
    if OwnedIndexPointerPathAllowed(path) then return 512
    if CreateObject("roRegex", "^cachefs:/owned-manifest-[A-Za-z0-9_-]{1,64}[.]json([.]part)?$", "").IsMatch(path) then return 131072
    return 65536
end function

function OwnedIndexScanEmptyCoverage() as Object
    coverage = {}
    for each name in ["shardCount", "recordCount", "rawCount", "discoveredSections", "terminalSections"]
        coverage[name] = 0
    end for
    for each name in ["discoveryTruncated", "sourceInventoryComplete", "authoritativeAbsence"]
        coverage[name] = false
    end for
    return coverage
end function

function OwnedIndexScanEnvelope(job as Dynamic, outcome as Object, state as Dynamic, now as Integer) as Object
    result = {status: "retryable", provider: "plex", sourceId: "", profileId: "", requestId: invalid, inventoryRunId: "", manifestUri: "", coverage: OwnedIndexScanEmptyCoverage()}
    if OwnedIndexScanValidJob(job)
        for each name in ["provider", "sourceId", "profileId", "requestId", "inventoryRunId"]
            result[name] = OwnedIndexField(job, name)
        end for
    end if
    status = OwnedIndexText(outcome, "status")
    if status = "cancelled" then result.status = "cancelled"
    if status <> "ready" and status <> "partial" then return result
    if not OwnedIndexScanValidJob(job) then return result
    if not OwnedIndexCoordinatorValidState(state) then return result
    if not state.finished or state.status = "cancelled" then return result
    checked = OwnedIndexManifestCoverage(state.manifest, state.scope, now)
    if OwnedIndexField(checked, "ok", false) <> true then return result
    uri = OwnedIndexManifestUri(OwnedIndexText(job, "inventoryRunId"))
    if uri = "" or OwnedIndexText(outcome, "manifestUri") <> uri then return result
    coverage = OwnedIndexScanEmptyCoverage()
    coverage["shardCount"] = OwnedIndexField(state.manifest, "shardCount")
    coverage["discoveredSections"] = state.sections.Count()
    coverage["discoveryTruncated"] = state.sectionTruncated
    for each library in checked.libraries
        coverage["recordCount"] += OwnedIndexField(library, "recordCount")
        coverage["rawCount"] += OwnedIndexField(library, "rawCount")
    end for
    for each section in state.sections
        if section.status = "terminal" then coverage["terminalSections"] += 1
    end for
    result.status = status
    result["manifestUri"] = uri
    result.coverage = coverage
    return result
end function

' Bound stale cache directory work before opening or deleting any inventory file.
function OwnedIndexScanRunDirectoryUnused(runId as String, files as Dynamic) as Boolean
    if OwnedIndexManifestUri(runId) = "" then return false
    if type(files) <> "roArray" and type(files) <> "roList" then return false
    if files.Count() > 512 then return false
    for each name in files
        if type(name) <> "String" and type(name) <> "roString" then return false
        path = "cachefs:/" + name
        if OwnedIndexScanPathAllowed(path)
            if path = OwnedIndexManifestUri(runId) or path = OwnedIndexManifestUri(runId) + ".part" then return false
            if Left(path, Len("cachefs:/owned-" + runId + "-")) = "cachefs:/owned-" + runId + "-" then return false
        end if
    end for
    return true
end function

function OwnedIndexScanRegularFile(stat as Dynamic) as Boolean
    return OwnedIndexText(stat, "type") = "file"
end function
