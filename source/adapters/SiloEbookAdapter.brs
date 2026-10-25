' Ebook progress uses the verified v2 profile-scoped reader contract.
function SiloEbookDetail(raw as Dynamic, contentId as String) as Object
    failure = SiloError("unsupported_ebook", "This book has no readable EPUB file.")
    if not SiloObject(raw) or raw.type <> "ebook" or SiloText(raw.content_id) <> contentId then return failure
    if not SiloArray(raw.versions) or raw.versions.Count() > 64 then return failure
    for each version in raw.versions
        if not SiloObject(version) then return failure
        fileId = SiloText(version.file_id)
        if LCase(SiloText(version.container)) = "epub" and CreateObject("roRegex", "^[0-9]{1,18}$", "").IsMatch(fileId)
            return {ok:true,data:{contentId:contentId,fileId:fileId,title:Left(SiloText(raw.title),200)}}
        end if
    end for
    return failure
end function

function BuildSiloEbookRequest(action as String, session as Object, params as Object) as Object
    if action = "ebook_libraries" then return BuildSiloRequest("libraries", session, {})
    if action = "ebook_detail" then return BuildSiloRequest("detail", session, {itemId:SiloText(params.contentId)})
    if action = "ebook_catalog"
        query = {type:"ebook",libraryId:SiloText(params.libraryId),limit:36}
        if SiloText(params.cursor) <> ""
            if Len(params.cursor) > 1024 then return SiloError("invalid_request", "This book page is unavailable.")
            query.cursor = params.cursor
        end if
        return BuildSiloRequest("catalog_query", session, query)
    end if
    request = BuildSiloRequest("libraries", session, {})
    if not request.ok then return request
    base = SiloBaseUrl(SiloText(session.baseUrl))
    if action = "ebook_capability"
        request.url = base + "/api/v2/capabilities/ebooks"
        return request
    end if
    contentId = SiloText(params.contentId)
    if contentId = "" or Len(contentId) > 256 then return SiloError("invalid_request", "This book is unavailable.")
    if action = "ebook_text_page"
        fileId = SiloText(params.fileId)
        pageIndex = SiloNumber(params.pageIndex, -1)
        if fileId = "" or Len(fileId) > 256 or pageIndex < 0 or pageIndex > 9999 or pageIndex <> Int(pageIndex) then return SiloError("invalid_request", "This page is unavailable.")
        request.url = base + "/api/v2/ebooks/" + SiloEscape(contentId) + "/files/" + SiloEscape(fileId) + "/text-pages/" + pageIndex.ToStr()
        return request
    end if
    request.url = base + "/api/v2/ebooks/" + SiloEscape(contentId) + "/progress"
    if action = "ebook_progress" then return request
    if action <> "ebook_save_progress" then return SiloError("unsupported_action", "This reader operation is unavailable.")
    fileId = SiloText(params.fileId)
    location = SiloText(params.location)
    updatedAt = SiloText(params.updatedAt)
    if fileId = "" or Len(fileId) > 256 or location = "" or Len(location) > 8192 then return SiloError("invalid_request", "This reading position is unavailable.")
    ' The server always returns UTC with exactly three millisecond digits.
    ' Requiring that wire form lets the receipt compare the original event.
    if not CreateObject("roRegex", "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z$", "").IsMatch(updatedAt) then return SiloError("invalid_request", "This reading position is unavailable.")
    if type(params.progress) <> "Float" and type(params.progress) <> "Double" and type(params.progress) <> "Integer" then return SiloError("invalid_request", "This reading position is unavailable.")
    if params.progress < 0 or params.progress > 1 then return SiloError("invalid_request", "This reading position is unavailable.")
    request.method = "PUT"
    request.headers["Content-Type"] = "application/json"
    request.body = FormatJson({file_id:fileId,location:location,progress:params.progress,updated_at:updatedAt})
    return request
end function

' Project one fully received page. The scene must fence source/profile and
' latest page intent before showing it; a failed fetch never advances progress.
function SiloEbookTextPage(raw as Dynamic, requestedIndex as Integer) as Object
    failure = SiloError("invalid_page", "This page is unavailable.")
    if not SiloObject(raw) then return failure
    revision = SiloText(raw.revision)
    location = SiloText(raw.location)
    pageIndex = SiloNumber(raw.page_index, -1)
    total = SiloNumber(raw.total_pages, -1)
    body = raw.text
    if type(body) <> "String" and type(body) <> "roString" then return failure
    if not CreateObject("roRegex", "^[0-9a-f]{64}$", "").IsMatch(revision) then return failure
    if Left(location, Len("silo-text-v1:" + revision + ":")) <> "silo-text-v1:" + revision + ":" then return failure
    if Len(location) > 160 or body = "" or Len(body) > 16384 then return failure
    if pageIndex <> requestedIndex or total < 1 or total > 10000 or pageIndex < 0 or pageIndex >= total then return failure
    previous = SiloNumber(raw.previous_page, -1)
    following = SiloNumber(raw.next_page, -1)
    if pageIndex = 0 and previous <> -1 then return failure
    if pageIndex > 0 and previous <> pageIndex - 1 then return failure
    if pageIndex = total - 1 and following <> -1 then return failure
    if pageIndex < total - 1 and following <> pageIndex + 1 then return failure
    return {ok:true,data:{text:body,location:location,revision:revision,pageIndex:pageIndex,totalPages:total,previousPage:previous,nextPage:following}}
end function

' An equal timestamp and location mean this exact event was stored. A newer
' receipt is intentionally not treated as confirmation of an older event.
function SiloEbookProgressReceipt(raw as Dynamic, expected as Object) as Boolean
    if not SiloObject(raw) or not SiloObject(raw.progress) then return false
    saved = raw.progress
    if type(saved.progress) <> "Float" and type(saved.progress) <> "Double" and type(saved.progress) <> "Integer" then return false
    if type(expected.progress) <> "Float" and type(expected.progress) <> "Double" and type(expected.progress) <> "Integer" then return false
    return SiloText(saved.content_id) = SiloText(expected.contentId) and SiloText(saved.file_id) = SiloText(expected.fileId) and SiloText(saved.location) = SiloText(expected.location) and SiloText(saved.updated_at) = SiloText(expected.updatedAt) and Abs(saved.progress - expected.progress) < 0.000001
end function
