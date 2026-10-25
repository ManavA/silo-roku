' Keep only bounded render identity between async catalog updates. Raw cards stay in
' the scene's current list; this state never contains media URLs or tokens.
function BrowseUpdatePlan(previous as Dynamic, incoming as Dynamic, scope as Dynamic, currentIndex as Dynamic, focusOwner as String, reason = "refresh" as String) as Object
    items = []
    if type(incoming) = "roArray"
        for each item in incoming
            if items.Count() >= 101 then exit for
            items.Push(item)
        end for
    end if
    compactScope = BrowseUpdateScope(scope)
    keys = []
    labels = []
    oversized = false
    for index = 0 to items.Count() - 1
        keys.Push(BrowseItemKey(items[index],compactScope))
        label = BrowseItemLabel(items[index])
        if Len(label) > 512 then oversized = true
        labels.Push(Left(label,512))
    end for
    sameScope = false
    previousKeys = []
    previousLabels = []
    if type(previous) = "roAssociativeArray"
        oldScope = BrowseUpdateField(previous,"scope",invalid)
        if type(oldScope) = "roAssociativeArray" then sameScope = BrowseUpdateScopeMatches(oldScope,compactScope,reason = "restore")
        if sameScope
            oldKeys = BrowseUpdateField(previous,"keys",invalid)
            oldLabels = BrowseUpdateField(previous,"labels",invalid)
            if type(oldKeys) = "roArray" and oldKeys.Count() <= 101 then previousKeys = oldKeys
            if type(oldLabels) = "roArray" and oldLabels.Count() <= 101 then previousLabels = oldLabels
        end if
    end if
    chosen = BrowseUpdateIndex(currentIndex)
    selectedKey = ""
    matched = false
    if sameScope and (reason = "refresh" or reason = "restore") and chosen >= 0 and chosen < previousKeys.Count()
        selectedKey = previousKeys[chosen]
    end if
    if type(previous) = "roAssociativeArray" and not sameScope and reason <> "enter" then chosen = 0
    if chosen < 0 then chosen = 0
    if items.Count() = 0
        chosen = 0
    else
        if chosen >= items.Count() then chosen = items.Count() - 1
        if selectedKey <> "" and BrowseUpdateKeyCount(previousKeys,selectedKey) = 1 and BrowseUpdateKeyCount(keys,selectedKey) = 1
            for index = 0 to keys.Count() - 1
                if keys[index] = selectedKey
                    chosen = index
                    matched = true
                    exit for
                end if
            end for
        end if
    end if
    priorOversized = false
    if type(previous) = "roAssociativeArray" then priorOversized = BrowseUpdateField(previous,"oversized",false) = true
    contentChanged = not sameScope or oversized or priorOversized or not BrowseUpdateVectorMatches(previousKeys,keys) or not BrowseUpdateVectorMatches(previousLabels,labels)
    target = "keep"
    if reason = "enter"
        target = "nav"
        if items.Count() > 0 then target = "catalog"
    else if reason = "restore"
        if focusOwner = "nav"
            target = "nav"
        else if focusOwner = "catalog" and items.Count() > 0
            target = "catalog"
        else if items.Count() = 0
            target = "nav"
        end if
    end if
    if focusOwner <> "catalog" and focusOwner <> "nav" then focusOwner = "other"
    return {state:{scope:compactScope,keys:keys,labels:labels,oversized:oversized},items:items,index:chosen,rebuild:contentChanged,contentChanged:contentChanged,focusTarget:target,focusOwner:focusOwner,selectedKey:selectedKey,matched:matched}
end function

function BrowseUpdateIndex(value as Dynamic) as Integer
    if type(value) = "Integer" or type(value) = "roInt" or type(value) = "roInteger"
        if value >= 0 then return value
    end if
    return 0
end function

function BrowseUpdateKeyCount(keys as Object, wanted as String) as Integer
    found = 0
    for each key in keys
        if key = wanted then found++
    end for
    return found
end function

function BrowseUpdateScope(scope as Dynamic) as Object
    return {provider:BrowseUpdateField(scope,"provider",""),sourceId:BrowseUpdateField(scope,"sourceId",""),profileId:BrowseUpdateField(scope,"profileId",""),generation:BrowseUpdateField(scope,"generation",-1),route:BrowseUpdateField(scope,"route",""),listKind:BrowseUpdateField(scope,"listKind","")}
end function

function BrowseUpdateScopeMatches(leftScope as Object, rightScope as Object, ignoreGeneration = false as Boolean) as Boolean
    if BrowseUpdateField(leftScope,"provider","") <> rightScope.provider then return false
    if BrowseUpdateField(leftScope,"sourceId","") <> rightScope.sourceId then return false
    if BrowseUpdateField(leftScope,"profileId","") <> rightScope.profileId then return false
    if BrowseUpdateField(leftScope,"route","") <> rightScope.route then return false
    if BrowseUpdateField(leftScope,"listKind","") <> rightScope.listKind then return false
    if not ignoreGeneration and BrowseUpdateField(leftScope,"generation",-1) <> rightScope.generation then return false
    return true
end function

function BrowseUpdateField(value as Dynamic, key as String, fallback as Dynamic) as Dynamic
    if type(value) <> "roAssociativeArray" then return fallback
    if not value.DoesExist(key) then return fallback
    result = value[key]
    if result = invalid then return fallback
    return result
end function

function BrowseUpdateSafePart(value as Dynamic) as String
    if type(value) <> "String" and type(value) <> "roString" then return ""
    if Len(value) = 0 or Len(value) > 160 then return ""
    allowed = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.:-"
    for position = 1 to Len(value)
        if Instr(1,allowed,Mid(value,position,1)) = 0 then return ""
    end for
    return value
end function

function BrowseItemKey(item as Dynamic, scope as Dynamic) as String
    row = BrowseUpdateSafePart(BrowseUpdateField(item,"rowId",""))
    for each field in ["versionId","catalogId","itemId","uiAction","sectionId","libraryId","profileId","machineId","personId","id"]
        part = BrowseUpdateSafePart(BrowseUpdateField(item,field,""))
        if part <> "" then return Len(row).ToStr() + ":" + row + "|" + field + "|" + Len(part).ToStr() + ":" + part
    end for
    return ""
end function

function BrowseItemLabel(item as Dynamic) as String
    title = BrowseUpdateField(item,"title",BrowseUpdateField(item,"name","Untitled"))
    if type(title) <> "String" and type(title) <> "roString" then title = "Untitled"
    rowTitle = BrowseUpdateField(item,"rowTitle","")
    if type(rowTitle) = "String" or type(rowTitle) = "roString"
        if rowTitle <> "" then title = rowTitle + " · " + title
    end if
    if BrowseUpdateField(item,"hasPin",false) = true then title = title + " (PIN required)"
    return title
end function

function BrowseUpdateVectorMatches(leftValues as Object, rightValues as Object) as Boolean
    if leftValues.Count() <> rightValues.Count() then return false
    for index = 0 to leftValues.Count() - 1
        if leftValues[index] <> rightValues[index] then return false
    end for
    return true
end function
