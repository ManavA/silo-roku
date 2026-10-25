' Ebook network work stays in ApiTask, scoped to the acting Silo profile.
function TaskEbookAction(session as Object, action as String, params as Object, scope as Object, revision as Integer) as Object
    if SiloText(scope.sourceId) <> SiloText(session.sourceId) or SiloText(scope.profileId) <> SiloText(session.profileId) then return TaskError("session_changed")
    if SessionRevision("silo") <> revision then return TaskError("session_changed")
    request = BuildSiloEbookRequest(action, session, params)
    if request.ok <> true then return request
    response = HttpRequest(request, 6000)
    if response.ok <> true and SiloText(response.errorCode) = "auth_required"
        fresh = TaskRefreshSilo(session, revision)
        if fresh <> invalid
            session = fresh
            if SiloText(session.sourceId) <> SiloText(scope.sourceId) or SiloText(session.profileId) <> SiloText(scope.profileId) then return TaskError("session_changed")
            request = BuildSiloEbookRequest(action, session, params)
            if request.ok = true then response = HttpRequest(request, 6000)
        end if
    end if
    if SessionRevision("silo") <> revision then return TaskError("session_changed")
    if response.ok <> true then return TaskSiloHttpError(response)
    raw = ParseJson(response.body)
    if not SiloObject(raw) then return TaskError("invalid_response")
    if action = "ebook_detail" then return SiloEbookDetail(raw, SiloText(params.contentId))
    if action = "ebook_libraries" or action = "ebook_catalog"
        if not SiloArray(raw.items) or raw.items.Count() > 100 then return TaskError("invalid_response")
        entries = []
        for each item in raw.items
            if not SiloObject(item) then return TaskError("invalid_response")
            if action = "ebook_libraries" and item.type = "ebooks"
                if SiloText(item.id) <> "" then entries.Push({id:SiloText(item.id),title:Left(SiloText(item.name),120)})
            else if action = "ebook_catalog" and item.type = "ebook"
                projected = SiloItem(item)
                if projected.ok <> true then return TaskError("invalid_response")
                entries.Push({id:SiloText(item.content_id),title:Left(SiloText(item.title),160),item:projected.item})
            end if
        end for
        cursor = ""
        if SiloObject(raw.page) and raw.page.has_more = true then cursor = SiloText(raw.page.next_cursor)
        if Len(cursor) > 1024 then return TaskError("invalid_response")
        return {ok:true,data:{entries:entries,nextCursor:cursor}}
    end if
    if action = "ebook_text_page" then return SiloEbookTextPage(raw, params.pageIndex)
    if action = "ebook_capability"
        if raw.state <> "available" or raw.text_pages <> true then return TaskError("ebook_unavailable")
        return {ok:true,data:{textPages:true}}
    end if
    if action = "ebook_save_progress"
        if not SiloEbookProgressReceipt(raw, params) then return TaskError("progress_unconfirmed")
        return {ok:true,data:{saved:true}}
    end if
    if action = "ebook_progress"
        if raw.progress = invalid then return {ok:true,data:{progress:invalid}}
        if not SiloObject(raw.progress) then return TaskError("invalid_response")
        return {ok:true,data:{progress:raw.progress}}
    end if
    return TaskError("unsupported_action")
end function
