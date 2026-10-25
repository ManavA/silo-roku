' Home uses a native RowList, while browse identity and history remain flat.
' This projection carries only row labels and positions, never media URLs.
function HomeRowsPlan(items as Dynamic) as Object
    rows = []
    positions = []
    if type(items) <> "roArray" then return {rows:rows,positions:positions}
    for each item in items
        if positions.Count() >= 101 then exit for
        rowId = HomeRowsText(item,"rowId","")
        title = HomeRowsText(item,"rowTitle","Home")
        if Len(title) > 80 then title = "Home"
        if Len(rowId) > 160 then rowId = ""
        if rowId = "" then rowId = title
        newRow = rows.Count() = 0
        if not newRow
            last = rows[rows.Count() - 1]
            newRow = last.id <> rowId or last.title <> title
        end if
        if newRow then rows.Push({id:rowId,title:title,start:positions.Count(),count:0,cardStyle:HomeRowsCardStyle(item)})
        rowIndex = rows.Count() - 1
        if HomeRowsCardStyle(item)="wide" then rows[rowIndex]["cardStyle"]="wide"
        column = rows[rowIndex].count
        rows[rowIndex].count = column + 1
        positions.Push([rowIndex,column])
    end for
    for each row in rows
        row["itemSize"]=[236,176]:row["rowHeight"]=210
        if row.cardStyle="poster" then row["itemSize"]=[112,198]:row["rowHeight"]=230
    end for
    return {rows:rows,positions:positions}
end function

function HomeRowsCardStyle(item as Dynamic) as String
    rowId=HomeRowsText(item,"rowId","")
    section=HomeRowsText(item,"sectionType","")
    if rowId="home.continue" or rowId="home.ondeck" or rowId="continue.overlay" or section="continue_watching" or section="on_deck" then return "wide"
    if HomeRowsText(item,"uiAction","")<>"" then return "wide"
    if type(item)="roAssociativeArray"
        if item.DoesExist("isAction")
            action=item.isAction
            if type(action)="Boolean" or type(action)="roBoolean"
                if action then return "wide"
            end if
        end if
    end if
    kind=HomeRowsText(item,"type","")
    if kind="movie" or kind="show" or kind="series" then return "poster"
    return "wide"
end function

function HomeRowsText(item as Dynamic, key as String, fallback as String) as String
    if type(item) <> "roAssociativeArray" or not item.DoesExist(key) then return fallback
    value = item[key]
    if type(value) <> "String" and type(value) <> "roString" then return fallback
    value = value.Trim()
    if value = "" then return fallback
    return value
end function

function HomeRowsIndexAt(plan as Dynamic, position as Dynamic) as Integer
    if type(plan) <> "roAssociativeArray" or type(position) <> "roArray" then return -1
    if position.Count() <> 2 then return -1
    rowIndex = position[0]
    column = position[1]
    if type(rowIndex) <> "Integer" and type(rowIndex) <> "roInt" and type(rowIndex) <> "roInteger" then return -1
    if type(column) <> "Integer" and type(column) <> "roInt" and type(column) <> "roInteger" then return -1
    rows = plan.rows
    if type(rows) <> "roArray" or rowIndex < 0 or rowIndex >= rows.Count() then return -1
    row = rows[rowIndex]
    if column < 0 or column >= row.count then return -1
    return row.start + column
end function

function HomeRowsPositionFor(plan as Dynamic, index as Dynamic) as Object
    missing = [-1,-1]
    if type(plan) <> "roAssociativeArray" then return missing
    if type(index) <> "Integer" and type(index) <> "roInt" and type(index) <> "roInteger" then return missing
    positions = plan.positions
    if type(positions) <> "roArray" or index < 0 or index >= positions.Count() then return missing
    return positions[index]
end function
