' Session-only overlays keep delayed Home responses behind local playback progress.
function SiloUIHomeNextHero(view as String, zone as String, index as Integer, count as Integer) as Integer
    if view <> "home" or zone <> "heroButtons" or count < 1 then return index
    if count > 6 then count = 6
    return (index + 1) mod count
end function

function SiloUIHomeSameItem(a as Object, b as Object) as Boolean
    if a.itemId = invalid or a.itemId = "" or b.itemId <> a.itemId then return false
    if a.sourceId = invalid or a.sourceId = "" then return false
    return a.sourceId = b.sourceId
end function

function SiloUIHomeApplyProgress(rows as Object, changes as Object, allowSynthetic = true as Boolean) as Object
    output = []
    hasContinue = false
    for each row in rows
        copy = {}
        copy.Append(row)
        copy.items = []
        isContinue = row.sectionType = "continue_watching"
        if isContinue then hasContinue = true
        for each item in row.items
            updated = item
            matched = false
            for each change in changes
                if SiloUIHomeSameItem(item, change)
                    matched = true
                    updated = {}
                    updated.Append(item)
                    updated.resumeMs = change.resumeMs
                    updated.watched = change.watched
                end if
            end for
            if not isContinue or not matched or updated.watched <> true then copy.items.Push(updated)
        end for
        if isContinue
            for each change in changes
                found = false
                for each item in copy.items
                    if SiloUIHomeSameItem(item, change) then found = true
                end for
                if not found and change.watched <> true and change.resumeMs > 0 then copy.items.Unshift(change)
            end for
        end if
        output.Push(copy)
    end for
    if not hasContinue and allowSynthetic
        items = []
        for each change in changes
            if change.watched <> true and change.resumeMs > 0 then items.Push(change)
        end for
        if items.Count() > 0 then output.Unshift({sectionType:"continue_watching",rowId:"local_continue",title:"Continue Watching",items:items})
    end if
    return output
end function

function SiloUIHomeHeroRow(rows as Object) as Integer
    for index = 0 to rows.Count() - 1
        if rows[index].sectionType <> "streaming" and rows[index].sectionType <> "curated" and rows[index].sectionType <> "formats" and rows[index].items.Count() > 0 then return index
    end for
    return -1
end function

function SiloUIHomeRememberProgress(changes as Object, item as Object) as Object
    recent = []
    for each prior in changes
        if not SiloUIHomeSameItem(prior, item) then recent.Push(prior)
    end for
    snapshot = {}
    snapshot.Append(item)
    recent.Push(snapshot)
    while recent.Count() > 40
        recent.Shift()
    end while
    return recent
end function

function SiloUIHomeRestoreFocus(rows as Object, priorRow as Object, item as Dynamic, fallback as Object) as Dynamic
    rowIndex = fallback[0]
    for index = 0 to rows.Count() - 1
        row = rows[index]
        same = priorRow.rowId <> invalid and priorRow.rowId <> "" and row.rowId = priorRow.rowId
        if not same and (priorRow.rowId = invalid or priorRow.rowId = "") then same = row.sectionType = priorRow.sectionType and row.title = priorRow.title
        if same then rowIndex = index : exit for
    end for
    if rowIndex >= rows.Count() then rowIndex = rows.Count() - 1
    if rowIndex < 0 then return invalid
    if rows[rowIndex].items.Count() = 0 then rowIndex = SiloUIHomeHeroRow(rows)
    if rowIndex < 0 then return invalid
    items = rows[rowIndex].items
    itemIndex = fallback[1]
    if item <> invalid
        for index = 0 to items.Count() - 1
            if SiloUIHomeSameItem(items[index], item) then itemIndex = index : exit for
        end for
    end if
    if itemIndex >= 40 then itemIndex = 39
    if itemIndex >= items.Count() then itemIndex = items.Count() - 1
    return [rowIndex, itemIndex]
end function

' Native RowList focus can be empty or negative before the first row visit.
' Validate each value before comparison/indexing; do not rely on short circuiting.
function SiloUIHomeFocusPosition(focus as Dynamic, rowCount as Integer, itemCount = -1 as Integer) as Dynamic
    focusType = type(focus)
    if focusType <> "roArray" and focusType <> "roIntArray" then return invalid
    if focus.Count() <> 2 then return invalid
    for each value in focus
        valueType = type(value)
        numeric = valueType = "Integer" or valueType = "roInt" or valueType = "roInteger" or valueType = "LongInteger" or valueType = "roLongInteger" or valueType = "Float" or valueType = "roFloat" or valueType = "Double" or valueType = "roDouble"
        if not numeric then return invalid
        if value < 0 then return invalid
        if value <> Int(value) then return invalid
    end for
    if focus[0] >= rowCount then return invalid
    if itemCount >= 0
        if focus[1] >= itemCount then return invalid
    end if
    return focus
end function

' One in-flight section, at most 24 rows and 40 retained cards per row.
function SiloUIHomeHydration(rows as Object, scope as String) as Object
    state = {rows:[],queue:[],cursor:0,active:-1,scope:scope,errors:0}
    for each row in rows
        if state.rows.Count() >= 24 then exit for
        copy = {}
        copy.Append(row)
        copy.items = []
        if type(row.items) = "roArray"
            for each item in row.items
                if copy.items.Count() >= 40 then exit for
                copy.items.Push(item)
            end for
        end if
        if copy.items.Count() = 0 and type(row.totalCount) <> "Invalid"
            if row.totalCount > 0 and (type(row.rowId) = "String" or type(row.rowId) = "roString") and row.rowId <> "" then state.queue.Push(state.rows.Count())
        end if
        state.rows.Push(copy)
    end for
    return state
end function

function SiloUIHomeHydrationNext(state as Object) as Integer
    if state.active >= 0 or state.cursor >= state.queue.Count() then return -1
    state.active = state.queue[state.cursor]
    state.cursor = state.cursor + 1
    return state.active
end function

sub SiloUIHomeHydrationComplete(state as Object, scope as String, index as Integer, result as Object, data as Object)
    if state.scope <> scope or state.active <> index or index < 0 then return
    state.active = -1
    if result.ok <> true or type(data.items) <> "roArray"
        state.errors = state.errors + 1
        return
    end if
    items = []
    for each item in data.items
        if items.Count() >= 40 then exit for
        items.Push(item)
    end for
    state.rows[index].items = items
end sub

function SiloUIHomeNeedsSynthetic(rows as Object, changes as Dynamic) as Boolean
    for each row in rows
        if row.sectionType = "continue_watching" then return false
    end for
    if type(changes) <> "roArray" then return false
    for each change in changes
        if change.watched <> true and change.resumeMs > 0 then return true
    end for
    return false
end function
