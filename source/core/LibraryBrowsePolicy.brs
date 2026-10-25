' Bounded library browse modes. Provider mappings verified against Android
' 1403c556 PlexCatalogApi.sortKeyOf and SiloCatalogApi.sortKeyOf.
function LibraryBrowseModes(provider as String) as Object
    if provider <> "plex" and provider <> "silo" then return []
    return [
        {title:"All titles",libraryMode:"title",uiAction:"library_mode_title"},
        {title:"Recently Added",libraryMode:"added",uiAction:"library_mode_added"},
        {title:"Recently Released",libraryMode:"released",uiAction:"library_mode_released"},
        {title:"Top Rated",libraryMode:"rated",uiAction:"library_mode_rated"},
        {title:"Last Viewed",libraryMode:"viewed",uiAction:"library_mode_viewed"}
    ]
end function

function LibraryBrowseRequest(provider as String, libraryId as String, mode as Dynamic, cursor as String, offset as Integer) as Object
    failure = {ok:false,errorCode:"invalid_library_mode"}
    if libraryId = "" or (type(mode) <> "String" and type(mode) <> "roString") then return failure
    selected = invalid
    for each entry in LibraryBrowseModes(provider)
        if entry.libraryMode = mode then selected = entry
    end for
    if selected = invalid then return failure
    if provider = "plex"
        sorts = {title:"titleSort:asc",added:"addedAt:desc",released:"originallyAvailableAt:desc",rated:"audienceRating:desc",viewed:"lastViewedAt:desc"}
        if offset < 0 then return failure
        return {ok:true,mode:mode,title:selected.title,action:"library_items",params:{sectionId:libraryId,sort:sorts[mode],offset:offset,limit:100}}
    end if
    sorts = {title:"title",added:"added_at",released:"release_date",rated:"rating_imdb",viewed:"last_watched"}
    order = "desc"
    if mode = "title" then order = "asc"
    params = {libraryId:libraryId,sort:sorts[mode],order:order,limit:100}
    if cursor <> "" then params["cursor"] = cursor
    return {ok:true,mode:mode,title:selected.title,action:"catalog_query",params:params}
end function
