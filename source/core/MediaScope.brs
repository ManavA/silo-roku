' Bind normalized media identity to the chosen server before it reaches UI.
function ScopedMediaItem(item as Dynamic, sourceId as String) as Object
    if type(item) <> "roAssociativeArray" then return {}
    copy = {}
    for each key in item
        copy[key] = item[key]
    end for
    if copy.DoesExist("itemId") or copy.DoesExist("libraryId") or copy.DoesExist("versionId") or copy.DoesExist("sectionId") or copy.DoesExist("personId") then copy["sourceId"] = sourceId
    return copy
end function

function ScopedMediaArray(items as Dynamic, sourceId as String, limit as Integer) as Object
    output = []
    if type(items) <> "roArray" then return output
    for each item in items
        if output.Count() >= limit then exit for
        output.Push(ScopedMediaItem(item, sourceId))
    end for
    return output
end function

function ScopeCatalogData(data as Dynamic, sourceId as String) as Object
    if type(data) <> "roAssociativeArray" then return {}
    result = {}
    for each key in data
        result[key] = data[key]
    end for
    if data.DoesExist("items") then result["items"] = ScopedMediaArray(data["items"], sourceId, 100)
    if data.DoesExist("libraries") then result["libraries"] = ScopedMediaArray(data["libraries"], sourceId, 50)
    if data.DoesExist("sections") then result["sections"] = ScopedMediaArray(data["sections"], sourceId, 50)
    if data.DoesExist("versions") then result["versions"] = ScopedMediaArray(data["versions"], sourceId, 20)
    if data.DoesExist("extras") then result["extras"] = ScopedMediaArray(data["extras"], sourceId, 24)
    if data.DoesExist("cast") then result["cast"] = ScopedMediaArray(data["cast"], sourceId, 32)
    if data.DoesExist("crew") then result["crew"] = ScopedMediaArray(data["crew"], sourceId, 32)
    if data.DoesExist("person") then result["person"] = ScopedMediaItem(data["person"], sourceId)
    if data.DoesExist("item") then result["item"] = ScopedMediaItem(data["item"], sourceId)
    if data.DoesExist("rows") and type(data["rows"]) = "roArray"
        rows = []
        for each row in data["rows"]
            if rows.Count() >= 12 then exit for
            scopedRow = ScopedMediaItem(row, sourceId)
            if scopedRow.DoesExist("items") then scopedRow["items"] = ScopedMediaArray(scopedRow["items"], sourceId, 24)
            rows.Push(scopedRow)
        end for
        result["rows"] = rows
    end if
    return result
end function
