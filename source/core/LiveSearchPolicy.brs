' One volatile, source/profile/route/dialog/query-owned native Search session.
' Provider windows and the positive cache never establish library-wide absence.
function LiveSearchScope(raw as Dynamic) as Dynamic
    if type(raw)<>"roAssociativeArray" then return invalid
    provider=UiField(raw,"provider","")
    sourceId=UiField(raw,"sourceId",invalid)
    profileId=UiField(raw,"profileId",invalid)
    if not LiveSearchString(provider) then return invalid
    if provider<>"plex" and provider<>"silo" then return invalid
    if not LiveSearchString(sourceId) or not LiveSearchString(profileId) then return invalid
    if Len(sourceId)<6 or Len(sourceId)>2048 or Left(sourceId,5)<>provider+":" or Len(profileId)>256 then return invalid
    generation=UiField(raw,"generation",invalid)
    if not LiveSearchInteger(generation,0,2147483646) then return invalid
    return {provider:provider,sourceId:sourceId,profileId:profileId,generation:generation}
end function

function LiveSearchString(raw as Dynamic) as Boolean
    return type(raw)="String" or type(raw)="roString"
end function

function LiveSearchNumber(raw as Dynamic) as Boolean
    kind=type(raw)
    if kind<>"Integer" and kind<>"roInt" and kind<>"roInteger" and kind<>"LongInteger" and kind<>"roLongInteger" and kind<>"Float" and kind<>"roFloat" and kind<>"Double" and kind<>"roDouble" then return false
    return raw=raw and raw>=-1000000000000000# and raw<=1000000000000000#
end function

function LiveSearchInteger(raw as Dynamic,minimum as Integer,maximum as Integer) as Boolean
    if not LiveSearchNumber(raw) then return false
    return raw>=minimum and raw<=maximum and raw=Int(raw)
end function

function LiveSearchDialog(raw as Dynamic) as Boolean
    if not LiveSearchString(raw) then return false
    return Len(raw)>0 and Len(raw)<=128 and CreateObject("roRegex","^[A-Za-z0-9_.:-]+$","").IsMatch(raw)
end function

function LiveSearchQuery(raw as Dynamic) as String
    if not LiveSearchString(raw) then return ""
    return Left(raw.Trim(),120)
end function

function LiveSearchCopy(raw as Object) as Object
    output={}
    for each key in raw
        output[key]=raw[key]
    end for
    return output
end function

function LiveSearchRecents(raw as Dynamic) as Object
    values=[]
    if type(raw)<>"roArray" then return values
    inspected=0
    for each entry in raw
        inspected++
        if inspected>20 or values.Count()>=10 then exit for
        query=LiveSearchQuery(entry)
        if Len(SearchQueryContext(query).text)>=2
            duplicate=false
            for each value in values
                if LCase(value)=LCase(query) then duplicate=true
            end for
            if not duplicate then values.Push(query)
        end if
    end for
    return values
end function

function LiveSearchCreate(rawScope as Dynamic,dialogId as Dynamic,recents as Dynamic) as Dynamic
    scope=LiveSearchScope(rawScope)
    if scope=invalid or not LiveSearchDialog(dialogId) then return invalid
    return {scope:scope,dialogId:dialogId,queryId:0,query:"",filter:"all",dialogOpen:true,retired:false,
        local:[],items:[],latestItems:invalid,recents:LiveSearchRecents(recents),dueMs:-1,
        requestSent:false,providerPending:false,failed:false,locked:false,base:invalid,nextCursor:""}
end function

function LiveSearchOwner(state as Dynamic) as Dynamic
    if type(state)<>"roAssociativeArray" or UiField(state,"retired",true)=true then return invalid
    return {scope:LiveSearchCopy(state.scope),dialogId:state.dialogId,queryId:state.queryId,query:state.query,filter:state.filter}
end function

function LiveSearchOwnerMatches(state as Object,raw as Dynamic) as Boolean
    if type(raw)<>"roAssociativeArray" or LiveSearchScope(UiField(raw,"scope",invalid))=invalid then return false
    if not RqMatches(state.scope,raw.scope) then return false
    if not LiveSearchDialog(UiField(raw,"dialogId",invalid)) or not LiveSearchInteger(UiField(raw,"queryId",invalid),0,2147483646) then return false
    if not LiveSearchString(UiField(raw,"query",invalid)) or not LiveSearchString(UiField(raw,"filter",invalid)) then return false
    for each field in ["dialogId","queryId","query","filter"]
        if UiField(raw,field,invalid)<>state[field] then return false
    end for
    return true
end function

function LiveSearchKind(raw as Dynamic,filter as String) as Boolean
    kind=UiField(raw,"type","")
    if filter="all" then return true
    if filter="movies" then return kind="movie"
    return kind="show" or kind="series" or kind="episode" or kind="season"
end function

 ' Only consistent, bounded normalized namespaces reach cards or owned caches.
function LiveSearchExternalIds(item as Object) as Dynamic
    external=UiField(item,"externalIds",invalid)
    if external<>invalid and type(external)<>"roAssociativeArray" then return invalid
    guids=UiField(item,"guids",invalid)
    if guids<>invalid and type(guids)<>"roArray" then return invalid
    if type(guids)="roArray"
        if guids.Count()>16 then return invalid
        for each guid in guids
            if not LiveSearchString(guid) then return invalid
            if Len(guid)>256 then return invalid
        end for
    end if
    ids={}
    for each namespace in ["tmdb","imdb","tvdb"]
        values=[UiField(item,namespace+"Id",invalid),UiField(external,namespace,invalid)]
        if type(guids)="roArray"
            prefix=namespace+"://"
            for each guid in guids
                if Left(LCase(guid),Len(prefix))=prefix then values.Push(Mid(guid,Len(prefix)+1))
            end for
        end if
        wanted=""
        for each value in values
            if value<>invalid and value<>""
                identifier=HmNumericId(value)
                if namespace="imdb" then identifier=HmImdbId(value)
                if identifier="" then return invalid
                if wanted<>"" and wanted<>identifier then return invalid
                wanted=identifier
            end if
        end for
        if wanted<>"" then ids[namespace+"Id"]=wanted
    end for
    return ids
end function

' Select kind before the result cap; only compact native owned identities survive.
function LiveSearchFilterCards(raw as Dynamic,scope as Object,filter as String,maximum = 500 as Integer,keepExternalIds = false as Boolean) as Object
    values=[]
    if type(raw)<>"roArray" then return values
    for index=0 to raw.Count()-1
        if index>=maximum then exit for
        item=raw[index]
        if UiField(item,"availability","owned")="owned" and UiField(item,"uiAction","")="" and UiField(item,"profileId",scope.profileId)=scope.profileId
            if LiveSearchKind(item,filter)
                card=SearchIndexCard(item,scope.sourceId)
                if card<>invalid
                    if keepExternalIds
                        ids=LiveSearchExternalIds(item)
                        if ids<>invalid
                            for each field in ids
                                card[field]=ids[field]
                            end for
                        end if
                    end if
                    values.Push(card)
                end if
            end if
        end if
    end for
    return values
end function

sub LiveSearchLocal(state as Object,index as Dynamic)
    filtered=LiveSearchFilterCards(index,state.scope,state.filter,500)
    state["local"]=SearchLocalMatches(filtered,state.query,state.scope.sourceId,100)
    state["items"]=state.local
    state["latestItems"]=invalid
end sub

sub LiveSearchFrame(state as Object,query as String,index as Dynamic,nowMs as Double,resetFilter as Boolean)
    state["queryId"]=state.queryId+1
    state["query"]=query
    if resetFilter then state["filter"]="all"
    state["dueMs"]=-1
    state["requestSent"]=false
    state["providerPending"]=false
    state["failed"]=false
    state["nextCursor"]=""
    state["locked"]=false
    LiveSearchLocal(state,index)
    if Len(SearchQueryContext(query).text)>=2 then state["dueMs"]=nowMs+400
end sub

sub LiveSearchRequest(state as Object,effects as Object)
    if state.requestSent or state.dueMs<0 then return
    state["dueMs"]=-1
    state["requestSent"]=true
    state["providerPending"]=true
    action="search"
    if state.scope.provider="silo" then action="catalog_query"
    effects.Push({kind:"request",action:action,params:{query:state.query,limit:100},owner:LiveSearchOwner(state)})
end sub

function LiveSearchReduce(previous as Dynamic,event as Dynamic,index as Dynamic,nowMs as Dynamic) as Object
    result={state:previous,effects:[],accepted:false}
    if type(previous)<>"roAssociativeArray" or type(event)<>"roAssociativeArray" then return result
    if previous.retired or not LiveSearchNumber(nowMs) or nowMs<0 then return result
    if LiveSearchScope(UiField(event,"scope",invalid))=invalid then return result
    if not RqMatches(previous.scope,event.scope) or UiField(event,"dialogId",invalid)<>previous.dialogId then return result
    kind=UiField(event,"kind","")
    if not LiveSearchString(kind) then return result
    state=LiveSearchCopy(previous)
    if kind="open"
        dialogId=UiField(event,"nextDialogId",invalid)
        if not LiveSearchDialog(dialogId) or dialogId=state.dialogId or state.queryId>=2147483645 then return result
        state["base"]=LiveSearchCopy(state)
        state["dialogId"]=dialogId
        state["queryId"]=state.queryId+1
        state["dialogOpen"]=true
        state["dueMs"]=-1
        state["requestSent"]=false
        state["providerPending"]=false
        state["locked"]=false
    else if kind="cancel"
        if not state.dialogOpen or state.queryId>=2147483645 then return result
        base=UiField(state,"base",invalid)
        if type(base)="roAssociativeArray"
            for each field in ["query","filter","items","local","failed","nextCursor"]
                state[field]=base[field]
            end for
        else
            LiveSearchFrame(state,"",index,nowMs,true)
        end if
        state["queryId"]=state.queryId+1
        state["dialogOpen"]=false
        state["base"]=invalid
        state["dueMs"]=-1
        state["requestSent"]=false
        state["providerPending"]=false
        state["latestItems"]=invalid
        state["locked"]=false
    else if kind="edit"
        if not state.dialogOpen or not LiveSearchString(UiField(event,"value",invalid)) then return result
        query=LiveSearchQuery(event.value)
        if query=state.query then return result
        if state.queryId>=2147483645 then return result
        LiveSearchFrame(state,query,index,nowMs,true)
    else if kind="filter"
        filter=UiField(event,"filter",invalid)
        if not LiveSearchString(filter) then return result
        if filter<>"all" and filter<>"movies" and filter<>"shows" then return result
        if filter=state.filter or state.queryId>=2147483645 then return result
        state["filter"]=filter
        LiveSearchFrame(state,state.query,index,nowMs,false)
    else if kind="submit"
        if not LiveSearchString(UiField(event,"value",invalid)) then return result
        query=LiveSearchQuery(event.value)
        if query<>state.query
            if state.queryId>=2147483645 then return result
            LiveSearchFrame(state,query,index,nowMs,true)
        end if
        state["dialogOpen"]=false
        state["base"]=invalid
        if Len(SearchQueryContext(query).text)>=2
            submitted=[query]
            for each recent in state.recents
                submitted.Push(recent)
            end for
            state["recents"]=LiveSearchRecents(submitted)
            if not state.requestSent
                state["dueMs"]=nowMs
                LiveSearchRequest(state,result.effects)
            end if
        end if
    else if kind="tick"
        if not LiveSearchOwnerMatches(state,UiField(event,"owner",invalid)) then return result
        if state.dueMs<0 or nowMs<state.dueMs then return result
        LiveSearchRequest(state,result.effects)
    else if kind="result"
        if not LiveSearchOwnerMatches(state,UiField(event,"owner",invalid)) or not state.requestSent then return result
        response=UiField(event,"response",invalid)
        if type(response)<>"roAssociativeArray" or not RqMatches(state.scope,response) then return result
        ok=UiField(response,"ok",invalid)
        if type(ok)<>"Boolean" and type(ok)<>"roBoolean" then return result
        state["providerPending"]=false
        state["failed"]=not ok
        state["nextCursor"]=""
        data=UiField(response,"data",{})
        hasMore=UiField(data,"hasMore",false)
        cursor=UiField(data,"nextCursor",invalid)
        if not state.failed and state.scope.provider="silo" and (type(hasMore)="Boolean" or type(hasMore)="roBoolean")
            if hasMore and LiveSearchString(cursor)
                if Len(cursor)>0 and Len(cursor)<=1024 and not CreateObject("roRegex","[\x00-\x1f\x7f]","").IsMatch(cursor) then state["nextCursor"]=cursor
            end if
        end if
        fresh=[]
        if not state.failed then fresh=LiveSearchFilterCards(UiField(UiField(response,"data",{}),"items",invalid),state.scope,state.filter,100,true)
        merged=SearchMergeResults(state.local,fresh,state.scope.sourceId,100,state.query)
        if state.locked
            state["latestItems"]=merged
        else
            state["items"]=merged
        end if
    else if kind="focus"
        value=UiField(event,"contentFocused",invalid)
        if type(value)<>"Boolean" and type(value)<>"roBoolean" then return result
        if state.locked=value then return result
        state["locked"]=value
        if not value and state.latestItems<>invalid
            state["items"]=state.latestItems
            state["latestItems"]=invalid
        end if
    else if kind="retire"
        state["retired"]=true
        state["dialogOpen"]=false
        state["dueMs"]=-1
        state["providerPending"]=false
        state["base"]=invalid
        state["items"]=[]
        state["local"]=[]
        state["latestItems"]=invalid
        state["nextCursor"]=""
    else
        return result
    end if
    result["accepted"]=true
    result["state"]=state
    return result
end function

function LiveSearchProjection(state as Dynamic) as Object
    projection={enabled:false,items:[],status:"",filter:"all",query:"",partial:true,recentsVisible:false,providerPending:false}
    if type(state)<>"roAssociativeArray" or UiField(state,"retired",true)=true then return projection
    projection["enabled"]=true
    projection["query"]=state.query
    projection["filter"]=state.filter
    projection["dialogId"]=state.dialogId
    projection["queryId"]=state.queryId
    projection["providerPending"]=state.providerPending or state.dueMs>=0
    projection["hasNextPage"]=not state.dialogOpen and state.nextCursor<>""
    projection["items"]=state.items
    if state.query=""
        projection["recentsVisible"]=true
        projection["items"]=[]
        for index=0 to state.recents.Count()-1
            query=state.recents[index]
            projection.items.Push({key:"search-recent-"+index.ToStr(),title:query,uiAction:"search_recent",searchQuery:query})
        end for
        projection["status"]="Enter a query or choose a recent search."
    else if Len(SearchQueryContext(state.query).text)<2
        projection["status"]="Enter at least two letters or numbers to search."
    else if state.failed
        projection["status"]="Library search could not refresh. Cached matches remain available."
    else if projection.providerPending
        projection["status"]="Searching your library…"
    else
        projection["status"]="Results from this search window."
        if state.items.Count()=0 then projection["status"]="No matches in this search window. Try another query."
    end if
    return projection
end function
