' A cachefs launch hint, never durable authority. No credentials, account IDs,
' media records, URL, timestamps, or registry writes belong in this pointer.
function OwnedIndexPointerPath() as String
    return "cachefs:/silo-owned-pointer-v1.json"
end function

function OwnedIndexPointerPathAllowed(path as String) as Boolean
    return path = OwnedIndexPointerPath() or path = OwnedIndexPointerPath() + ".part"
end function

function OwnedIndexPointerCreate(runId as String) as Object
    if OwnedIndexManifestUri(runId) = "" then return {ok: false}
    body = FormatJson({schema: 1, inventoryRunId: runId})
    return {ok: true, uri: OwnedIndexPointerPath(), body: body, bytes: OwnedIndexByteCount(body)}
end function

function OwnedIndexPointerDecode(body as String) as Object
    if Len(body) > 512 or OwnedIndexByteCount(body) > 512 then return {ok: false}
    data = ParseJson(body)
    if not OwnedIndexManifestKeys(data, ["schema", "inventoryRunId"]) then return {ok: false}
    if OwnedIndexManifestNumber(OwnedIndexField(data, "schema")) <> 1 then return {ok: false}
    runId = OwnedIndexText(data, "inventoryRunId")
    uri = OwnedIndexManifestUri(runId)
    if uri = "" then return {ok: false}
    return {ok: true, inventoryRunId: runId, manifestUri: uri}
end function

function OwnedIndexRestoreValidJob(job as Dynamic) as Boolean
    if not OwnedIndexManifestKeys(job, ["provider", "sourceId", "profileId", "requestId"]) then return false
    page = {provider: OwnedIndexField(job, "provider"), sourceId: OwnedIndexField(job, "sourceId"), profileId: OwnedIndexField(job, "profileId"), requestId: OwnedIndexField(job, "requestId"), inventoryRunId: "restore", libraryId: "0", offset: 0, limit: 48}
    return OwnedIndexValidJob(page)
end function

function OwnedIndexRestorePathAllowed(path as String) as Boolean
    if path = OwnedIndexPointerPath() then return true
    manifest = CreateObject("roRegex", "^cachefs:/owned-manifest-[A-Za-z0-9_-]{1,64}[.]json$", "").IsMatch(path)
    shard = CreateObject("roRegex", "^cachefs:/owned-[A-Za-z0-9_-]{1,64}-[A-Za-z0-9_-]{1,64}-[0-9]{1,10}[.]json$", "").IsMatch(path)
    return manifest or shard
end function

function OwnedIndexRestoreEnvelope(job as Dynamic, outcome as Object) as Object
    result = {status: "miss"}
    result["inventoryRunId"] = ""
    result["manifestUri"] = ""
    if OwnedIndexRestoreValidJob(job)
        for each name in ["provider", "sourceId", "profileId", "requestId"]
            result[name] = OwnedIndexField(job, name)
        end for
    end if
    status = OwnedIndexText(outcome, "status")
    if status = "cancelled" then result.status = "cancelled"
    if status <> "ready" or not OwnedIndexRestoreValidJob(job) then return result
    runId = OwnedIndexText(outcome, "inventoryRunId")
    uri = OwnedIndexManifestUri(runId)
    if uri = "" or uri <> OwnedIndexText(outcome, "manifestUri") then return result
    result.status = "ready"
    result["inventoryRunId"] = runId
    result["manifestUri"] = uri
    return result
end function
