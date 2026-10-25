function HomeSectionsWrites(saved as Dynamic) as Dynamic
    if type(saved) <> "roArray" then return invalid
    if saved.Count() > 500 then return invalid
    allowed = {id:true,section_id:true,position:true,hidden:true,removed:true,section_type:true,title:true,featured:true,item_limit:true,config:true,is_user_added:true,user_section_type:true,user_config:true,user_title:true}
    writes = []
    for each row in saved
        if type(row) <> "roAssociativeArray" then return invalid
        copy = {}
        for each key in row
            if allowed.DoesExist(key)
                copy[key] = row[key]
            else if key <> "created_at" and key <> "updated_at"
                return invalid
            end if
        end for
        writes.Push(copy)
    end for
    return writes
end function

function HomeSectionsRowIndex(rows as Dynamic, id as Dynamic) as Integer
    if type(rows) <> "roArray" then return -1
    if type(id) <> "String" and type(id) <> "roString" then return -1
    found = -1
    for i = 0 to rows.Count() - 1
        if type(rows[i]) <> "roAssociativeArray" then return -1
        if rows[i].id = id
            if found >= 0 then return -1
            found = i
        end if
    end for
    return found
end function

function HomeSectionsOverride(writes as Object, row as Object) as Dynamic
    found = invalid
    for each entry in writes
        matches = entry.section_id = row.id
        if row.is_custom = true then matches = entry.id = row.id and (entry.section_id = "" or not entry.DoesExist("section_id"))
        if matches
            if found <> invalid then return invalid
            found = entry
        end if
    end for
    if found = invalid
        if row.is_custom = true then return invalid
        found = {section_id:row.id}
        writes.Push(found)
    end if
    return found
end function

function HomeSectionsEdit(saved as Dynamic, rows as Dynamic, intent as Object) as Object
    failure = {ok:false}
    writes = HomeSectionsWrites(saved)
    if writes = invalid then return failure
    index = HomeSectionsRowIndex(rows,intent.id)
    if index < 0 or intent.id = "" then return failure
    if intent.kind = "hidden"
        if type(intent.value) <> "Boolean" and type(intent.value) <> "roBoolean" then return failure
        row = HomeSectionsOverride(writes,rows[index])
        if row = invalid then return failure
        row.hidden = intent.value
    else if intent.kind = "move"
        if intent.direction <> -1 and intent.direction <> 1 then return failure
        target = index + intent.direction
        if target < 0 or target >= rows.Count() then return failure
        order = []
        for each row in rows
            order.Push(row)
        end for
        order[index] = rows[target]
        order[target] = rows[index]
        for i = 0 to order.Count() - 1
            row = HomeSectionsOverride(writes,order[i])
            if row = invalid then return failure
            row.position = i
        end for
    else
        return failure
    end if
    if writes.Count() > 500 then return failure
    return {ok:true,overrides:writes}
end function

function HomeSectionsContinueHidden(rows as Object, intent as Dynamic) as Boolean
    if type(intent) = "roAssociativeArray"
        if intent.kind = "reset" then return true
    end if
    for each row in rows
        if row.section_type = "continue_watching" and row.removed <> true
            hidden = row.hidden <> false
            if type(intent) = "roAssociativeArray"
                if intent.kind = "hidden" and intent.id = row.id then hidden = intent.value = true
            end if
            if not hidden then return false
        end if
    end for
    return true
end function
