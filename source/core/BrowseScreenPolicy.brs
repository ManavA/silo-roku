' Fresh screen projection: only bounded display facts reach its native nodes.
function BrowseScreenPlan(previous as Dynamic, model as Dynamic, focusedIndex as Dynamic, owner as String, restore = false as Boolean) as Object
    presentation = BrowseScreenText(BrowseScreenField(model,"presentation","list"),"list",8)
    if presentation <> "rows" and presentation <> "grid" then presentation = "list"
    scope = BrowseScreenField(model,"scopeKey","")
    scopeValid = false
    if type(scope) = "String" or type(scope) = "roString" then scopeValid = Len(scope) > 0 and Len(scope) <= 2048
    if not scopeValid then scope = ""
    hasNextPage = BrowseScreenField(model,"hasNextPage",false) = true
    items = []
    keys = []
    titles = []
    rowIds = []
    rowTitles = []
    rowKinds = []
    incoming = BrowseScreenField(model,"items",[])
    if type(incoming) = "roArray"
        for each item in incoming
            if items.Count() >= 100 then exit for
            key = BrowseScreenKey(BrowseScreenField(item,"key",BrowseScreenField(item,"itemId","")))
            title = BrowseScreenText(BrowseScreenField(item,"title",BrowseScreenField(item,"name","Untitled")),"Untitled",256)
            rowId = BrowseScreenKey(BrowseScreenField(item,"rowId",""))
            rowTitle = BrowseScreenText(BrowseScreenField(item,"rowTitle","Home"),"Home",80)
            kind=BrowseScreenField(item,"type","")
            if kind<>"movie" and kind<>"show" and kind<>"series" and kind<>"episode" and kind<>"season" and kind<>"collection" then kind=""
            section=BrowseScreenKey(BrowseScreenField(item,"sectionType",""))
            if Len(section)>64 then section=""
            isAction=BrowseScreenText(BrowseScreenField(item,"uiAction",""),"",64)<>""
            items.Push({title:title,key:key,nativeIndex:items.Count(),rowId:rowId,rowTitle:rowTitle,
                type:kind,sectionType:section,isAction:isAction,progress:BrowseScreenProgress(item)})
            rowKinds.Push(HomeRowsCardStyle(items[items.Count()-1]))
            keys.Push(key)
            titles.Push(title)
            rowIds.Push(rowId)
            rowTitles.Push(rowTitle)
        end for
    end if
    previousKeys = BrowseScreenField(previous,"keys",[])
    if type(previousKeys) <> "roArray" then previousKeys = []
    sameScope = scopeValid and BrowseScreenField(previous,"scopeValid",false) = true and BrowseScreenField(previous,"scopeKey",invalid) = scope
    index = BrowseScreenIndex(focusedIndex)
    anchor = ""
    if sameScope
        if previousKeys.Count() > 0
            if index >= previousKeys.Count() then index = previousKeys.Count() - 1
            oldKey = previousKeys[index]
            if type(oldKey) = "String" or type(oldKey) = "roString"
                if oldKey <> "" and BrowseScreenKeyCount(previousKeys,oldKey) = 1 then anchor = oldKey
            end if
        else
            anchor = BrowseScreenKey(BrowseScreenField(previous,"anchorKey",""))
        end if
    else
        index = 0
        if previous = invalid then index = BrowseScreenIndex(BrowseScreenField(model,"selectedIndex",0))
    end if
    if restore
        index = BrowseScreenIndex(BrowseScreenField(model,"selectedIndex",0))
        anchor = ""
    end if
    if items.Count() = 0
        index = 0
    else
        if index >= items.Count() then index = items.Count() - 1
        if anchor <> "" and BrowseScreenKeyCount(keys,anchor) = 1
            for position = 0 to keys.Count() - 1
                if keys[position] = anchor
                    index = position
                    exit for
                end if
            end for
        end if
        anchor = ""
        if keys[index] <> "" and BrowseScreenKeyCount(keys,keys[index]) = 1 then anchor = keys[index]
    end if
    rebuild = not sameScope or BrowseScreenField(previous,"presentation","") <> presentation
    if not rebuild
        rebuild = not BrowseScreenVectorMatches(previousKeys,keys) or not BrowseScreenVectorMatches(BrowseScreenField(previous,"titles",[]),titles)
        if presentation = "rows" then rebuild = rebuild or not BrowseScreenVectorMatches(BrowseScreenField(previous,"rowIds",[]),rowIds) or not BrowseScreenVectorMatches(BrowseScreenField(previous,"rowTitles",[]),rowTitles) or not BrowseScreenVectorMatches(BrowseScreenField(previous,"rowKinds",[]),rowKinds)
    end if
    focusTarget = "keep"
    if owner = "content"
        if items.Count() = 0
            focusTarget = "nav"
        else if BrowseScreenField(previous,"presentation",presentation) <> presentation
            focusTarget = "content"
        end if
    else if owner = "next" and not hasNextPage
        focusTarget = "nav"
        if items.Count() > 0 then focusTarget = "content"
    end if
    state = {scopeKey:scope,scopeValid:scopeValid,presentation:presentation,keys:keys,titles:titles,rowIds:rowIds,rowTitles:rowTitles,rowKinds:rowKinds,anchorKey:anchor}
    return {state:state,items:items,index:index,rebuild:rebuild,focusTarget:focusTarget,
        presentation:presentation,title:BrowseScreenText(BrowseScreenField(model,"title","Browse"),"Browse",160),
        status:BrowseScreenText(BrowseScreenField(model,"status",""),"",512),
        navKey:BrowseScreenText(BrowseScreenField(model,"navKey","home"),"home",24),hasNextPage:hasNextPage}
end function

function BrowseScreenField(value as Dynamic, key as String, fallback as Dynamic) as Dynamic
    if type(value) <> "roAssociativeArray" then return fallback
    if not value.DoesExist(key) then return fallback
    result = value[key]
    if result = invalid then return fallback
    return result
end function

function BrowseScreenText(value as Dynamic, fallback as String, maximum as Integer) as String
    if type(value) <> "String" and type(value) <> "roString" then return fallback
    value = value.Trim()
    if value = "" then return fallback
    return Left(value,maximum)
end function

function BrowseScreenKey(value as Dynamic) as String
    if type(value) <> "String" and type(value) <> "roString" then return ""
    if Len(value) = 0 or Len(value) > 160 then return ""
    allowed = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.:-"
    for position = 1 to Len(value)
        if Instr(1,allowed,Mid(value,position,1)) = 0 then return ""
    end for
    return value
end function

function BrowseScreenIndex(value as Dynamic) as Integer
    if type(value) = "Integer" or type(value) = "roInt" or type(value) = "roInteger"
        if value >= 0 then return value
    end if
    return 0
end function

function BrowseScreenKeyCount(keys as Object, key as String) as Integer
    count = 0
    for each candidate in keys
        if candidate = key then count++
    end for
    return count
end function

function BrowseScreenVectorMatches(leftValues as Dynamic, rightValues as Object) as Boolean
    if type(leftValues) <> "roArray" then return false
    if leftValues.Count() <> rightValues.Count() then return false
    for index = 0 to rightValues.Count() - 1
        if leftValues[index] <> rightValues[index] then return false
    end for
    return true
end function

function BrowseScreenNavigationKeys() as Object
    return ["home","library","search","discover","services","ava","watchlist","settings"]
end function

function BrowseScreenLeftEdge(presentation as String, index as Integer, position as Dynamic) as Boolean
    if presentation = "grid" then return index >= 0 and index mod BrowseScreenColumns() = 0
    if presentation = "rows"
        if type(position) <> "roArray" then return false
        if position.Count() <> 2 then return false
        return position[1] = 0
    end if
    return true
end function

function BrowseScreenBottomEdge(presentation as String, index as Integer, count as Integer, position as Dynamic, plan as Object) as Boolean
    if index < 0 or index >= count then return false
    if presentation = "grid" then return Int(index / BrowseScreenColumns()) = Int((count - 1) / BrowseScreenColumns())
    if presentation = "rows"
        if type(position) <> "roArray" then return false
        if position.Count() <> 2 then return false
        return position[0] = plan.rows.Count() - 1
    end if
    return index = count - 1
end function

function BrowseScreenColumns() as Integer
    return 6
end function

function BrowseScreenProgress(item as Dynamic) as Object
    position=BrowseScreenField(item,"resumeMs",invalid):duration=BrowseScreenField(item,"durationMs",invalid)
    if not BrowseScreenFiniteNumber(position) or not BrowseScreenFiniteNumber(duration) then return {}
    if duration<=0 or position>duration then return {}
    return {positionMs:position,durationMs:duration}
end function

function BrowseScreenFiniteNumber(value as Dynamic) as Boolean
    kind=type(value)
    if kind<>"Integer" and kind<>"roInt" and kind<>"roInteger" and kind<>"LongInteger" and kind<>"roLongInteger" and kind<>"Float" and kind<>"roFloat" and kind<>"Double" and kind<>"roDouble" then return false
    return value=value and value>=0 and value<=86400000
end function
