' Enabled only by the native shell. Legacy submitted-only reducers stay usable.
function AppLiveSearchNow(event as Object) as Double
    return UiNumber(UiField(event,"searchNowMs",UiField(event,"nowMs",0)),0)
end function

function AppLiveSearchDialogId(state as Object) as String
    sequence=UiField(state,"searchDialogSequence",0)
    if not LiveSearchInteger(sequence,0,2147483644) then return ""
    sequence++
    state["searchDialogSequence"]=sequence
    return "search-"+sequence.ToStr()
end function

sub AppLiveSearchPaint(state as Object)
    live=UiField(state,"liveSearch",invalid)
    if live=invalid then return
    projection=LiveSearchProjection(live)
    old=UiField(state.view,"searchUi",{})
    if UiField(old,"queryId",-1)<>projection.queryId or UiField(old,"dialogId","")<>projection.dialogId then state.view["selectedIndex"]=0
    state["searchQuery"]=live.query
    state["searchLocal"]=live.local
    state["searchRecents"]=live.recents
    state["nextCursor"]=live.nextCursor
    state["nextOffset"]=-1
    state.view["hasNextPage"]=projection.hasNextPage
    state.view["searchUi"]=projection
    state.view["items"]=projection.items
    state.view["status"]=projection.status
    state.view["title"]="Search"
    if live.query<>"" then state.view["title"]="Search: "+live.query
    state.view["presentation"]="grid"
    if projection.recentsVisible then state.view["presentation"]="list"
end sub

function AppLiveSearchApply(out as Object,event as Object) as Boolean
    previous=out.state.liveSearch
    decision=LiveSearchReduce(previous,event,out.state.searchIndex,AppLiveSearchNow(event))
    if not decision.accepted then return false
    out.state["liveSearch"]=decision.state
    AppLiveSearchPaint(out.state)
    keep=LiveSearchOwner(decision.state)
    out.effects.Push({type:"search_cancel_queued",keepOwner:keep})
    for each effect in decision.effects
        if effect.kind="request"
            out.state["pageRequest"]={action:effect.action,params:effect.params}
            request={type:"request",action:effect.action,params:effect.params,purpose:"search",scope:effect.owner.scope,searchOwner:effect.owner}
            out.effects.Push(request)
        end if
    end for
    delayMs=0
    if decision.state.dueMs>=0 then delayMs=decision.state.dueMs-AppLiveSearchNow(event)
    if delayMs<0 then delayMs=0
    out.effects.Push({type:"search_timer",milliseconds:delayMs,owner:keep})
    return true
end function

sub AppLiveSearchOpen(out as Object,freshRoute as Boolean,event as Object)
    state=out.state
    AppSearchBind(state)
    if freshRoute
        prior=UiField(state,"liveSearch",invalid)
        if prior<>invalid then out.effects.Push({type:"search_retire",scope:prior.scope,dialogId:prior.dialogId})
        state["liveSearch"]=invalid
        state.history=[]
        AppBrowse(out,"Search","search","list",[],"search")
    end if
    previous=UiField(state,"liveSearch",invalid)
    dialogId=AppLiveSearchDialogId(state)
    if dialogId="" then return
    if previous=invalid
        live=LiveSearchCreate(AppScope(state),dialogId,state.searchRecents)
        if live=invalid then return
        state["liveSearch"]=live
        state["pageRequest"]=invalid
        AppLiveSearchPaint(state)
    else
        input={kind:"open",scope:previous.scope,dialogId:previous.dialogId,nextDialogId:dialogId,nowMs:AppLiveSearchNow(event)}
        AppLiveSearchApply(out,input)
    end if
    live=state.liveSearch
    out.effects.Push({type:"keyboard",purpose:"search",title:"Search your library",value:live.query,submitLabel:"Search",dialogId:live.dialogId,scope:live.scope})
end sub

function AppLiveSearchResultMatches(state as Object,event as Object) as Boolean
    current=UiField(state,"liveSearch",invalid)
    if current=invalid or not current.requestSent or UiField(state.view,"listKind","")<>"search" then return false
    if not RqMatches(current.scope,AppScope(state)) then return false
    job=UiField(UiField(event,"pending",{}),"job",invalid)
    response=UiField(event,"result",invalid)
    if type(job)<>"roAssociativeArray" or type(response)<>"roAssociativeArray" then return false
    owner=UiField(job,"searchOwner",invalid)
    if not LiveSearchOwnerMatches(current,owner) then return false
    if LiveSearchScope(job)=invalid or LiveSearchScope(response)=invalid then return false
    if not RqMatches(current.scope,job) or not RqMatches(current.scope,response) then return false
    action="search"
    if current.scope.provider="silo" then action="catalog_query"
    jobAction=UiField(job,"action",invalid)
    responseAction=UiField(response,"action",invalid)
    if not LiveSearchString(jobAction) or not LiveSearchString(responseAction) then return false
    if jobAction<>action or responseAction<>action then return false
    requestId=UiField(job,"requestId",invalid)
    responseId=UiField(response,"requestId",invalid)
    if not LiveSearchDialog(requestId) or not LiveSearchString(responseId) then return false
    if responseId<>requestId then return false
    params=UiField(job,"params",invalid)
    if type(params)<>"roAssociativeArray" then return false
    query=UiField(params,"query",invalid)
    if not LiveSearchString(query) or query<>current.query then return false
    if not LiveSearchInteger(UiField(params,"limit",invalid),100,100) then return false
    planned=UiField(state,"pageRequest",invalid)
    if type(planned)<>"roAssociativeArray" or UiField(planned,"action",invalid)<>action then return false
    if FormatJson(params)<>FormatJson(UiField(planned,"params",invalid)) then return false
    ok=UiField(response,"ok",invalid)
    return type(ok)="Boolean" or type(ok)="roBoolean"
end function

 ' Both cache sanitizers receive only the same bounded identity projection.
function AppLiveSearchObservedItems(state as Object,raw as Dynamic) as Object
    return LiveSearchFilterCards(raw,AppScope(state),"all",100,true)
end function

 ' Local rejection is ID-free; native Task receipts still require their real ID.
function AppLiveSearchAdmissionMatches(state as Object,event as Object) as Boolean
    if UiField(event,"errorCode",invalid) <> "queue_full" then return false
    current = UiField(state,"liveSearch",invalid)
    if type(current) <> "roAssociativeArray" then return false
    currentScope = LiveSearchScope(UiField(current,"scope",invalid))
    if currentScope = invalid or not RqMatches(AppScope(state),currentScope) then return false
    retired = UiField(current,"retired",invalid)
    if type(retired) <> "Boolean" and type(retired) <> "roBoolean" then return false
    if retired then return false
    query = UiField(current,"query",invalid)
    filter = UiField(current,"filter",invalid)
    if not LiveSearchString(query) or query <> LiveSearchQuery(query) or Len(query) > 120 then return false
    if Len(SearchQueryContext(query).text) < 2 then return false
    if not LiveSearchString(filter) then return false
    if filter <> "all" and filter <> "movies" and filter <> "shows" then return false
    for each field in ["requestSent","providerPending"]
        value = UiField(current,field,invalid)
        if type(value) <> "Boolean" and type(value) <> "roBoolean" then return false
        if not value then return false
    end for
    job = UiField(event,"job",invalid)
    if type(job) <> "roAssociativeArray" then return false
    if job.DoesExist("requestId") or UiField(job,"provider",invalid) <> "plex" or UiField(job,"action",invalid) <> "search" then return false
    if LiveSearchScope(job) = invalid or LiveSearchScope(UiField(event,"scope",invalid)) = invalid then return false
    if not RqMatches(AppScope(state),job) or not RqMatches(job,event.scope) then return false
    if not LiveSearchOwnerMatches(current,UiField(job,"searchOwner",invalid)) then return false
    params = UiField(job,"params",invalid)
    if type(params) <> "roAssociativeArray" then return false
    if UiField(params,"query",invalid) <> current.query or not LiveSearchInteger(UiField(params,"limit",invalid),100,100) then return false
    planned = UiField(state,"pageRequest",invalid)
    if type(planned) <> "roAssociativeArray" or UiField(planned,"action",invalid) <> "search" then return false
    return FormatJson(params) = FormatJson(UiField(planned,"params",invalid))
end function

function AppLiveSearchHandle(out as Object,event as Object) as Boolean
    kind=UiField(event,"type","")
    if kind="nav" and UiField(event,"key","")="search"
        AppLiveSearchOpen(out,true,event)
        return true
    end if
    current=UiField(out.state,"liveSearch",invalid)
    if kind="search_admission_failed"
        if not AppLiveSearchAdmissionMatches(out.state,event) then return true
        response=LiveSearchCopy(current.scope)
        response["ok"]=false
        response["errorCode"]="queue_full"
        owner=event.job.searchOwner
        AppLiveSearchApply(out,{kind:"result",scope:owner.scope,dialogId:owner.dialogId,owner:owner,response:response,searchNowMs:AppLiveSearchNow(event)})
        return true
    end if
    if kind="search_input"
        if UiField(out.state.view,"listKind","")<>"search" then return true
        if current<>invalid
            if current.dialogOpen or not RqMatches(current.scope,UiField(event,"scope",invalid)) then return true
            if UiField(event,"dialogId",invalid)<>current.dialogId or UiField(event,"queryId",invalid)<>current.queryId then return true
        end if
        AppLiveSearchOpen(out,false,event)
        return true
    end if
    if kind="result" and UiField(UiField(event,"pending",{}),"purpose","")="search"
        ' Even a retained active reply cannot recreate a retired Search owner.
        if current=invalid then return true
        if not AppLiveSearchResultMatches(out.state,event) then return true
        pending=event.pending
        owner=pending.job.searchOwner
        input={kind:"result",scope:current.scope,dialogId:current.dialogId,owner:owner,response:event.result,nowMs:AppLiveSearchNow(event)}
        if AppLiveSearchApply(out,input)
            if event.result.ok
                observed=AppLiveSearchObservedItems(out.state,UiField(UiField(event.result,"data",{}),"items",[]))
                AppSearchRemember(out.state,observed)
                AppEnrichmentRemember(out.state,observed)
            end if
        end if
        return true
    end if
    if kind="next_page" and current<>invalid and UiField(out.state.view,"listKind","")="search"
        if current.dialogOpen or not RqMatches(current.scope,AppScope(out.state)) or UiField(out.state.view,"hasNextPage",false)<>true then return true
        query=current.query
        filter=current.filter
        AppNextPage(out)
        dialogId=AppLiveSearchDialogId(out.state)
        page=LiveSearchCreate(AppScope(out.state),dialogId,out.state.searchRecents)
        if page=invalid then return true
        page["query"]=query
        page["filter"]=filter
        page["dialogOpen"]=false
        page["requestSent"]=true
        page["providerPending"]=true
        out.state["liveSearch"]=page
        AppLiveSearchPaint(out.state)
        owner=LiveSearchOwner(page)
        for each effect in out.effects
            if effect.type="request" and effect.purpose="search" then effect["searchOwner"]=owner
        end for
        out.effects.Push({type:"search_retire",scope:current.scope,dialogId:current.dialogId,restoreScope:AppScope(out.state)})
        return true
    end if
    if kind="select" and UiField(out.state.view,"listKind","")="search"
        if current=invalid or current.dialogOpen or not RqMatches(current.scope,AppScope(out.state)) then return true
        owner=UiField(event,"searchOwner",invalid)
        if type(owner)<>"roAssociativeArray" then return true
        if UiField(owner,"scopeKey",invalid)<>"route-"+out.state.generation.ToStr() or UiField(owner,"dialogId",invalid)<>current.dialogId or UiField(owner,"queryId",invalid)<>current.queryId then return true
        index=UiNumber(UiField(event,"index",-1),-1)
        items=UiField(out.state.view,"items",[])
        if index>=0 and index<items.Count() and index=Int(index)
            item=items[Int(index)]
            key=UiField(item,"key",UiField(item,"itemId",""))
            if key="" or UiField(event,"key",invalid)<>key then return true
            if UiField(item,"uiAction","")="search_recent"
                input={kind:"submit",scope:current.scope,dialogId:current.dialogId,value:UiField(item,"searchQuery",""),nowMs:AppLiveSearchNow(event)}
                AppLiveSearchApply(out,input)
                return true
            end if
        else
            return true
        end if
    end if
    for each eventKind in ["search_edit","search_submit","search_filter","search_cancel","search_tick","search_focus"]
        if kind=eventKind
            if current=invalid or UiField(out.state.view,"listKind","")<>"search" or not RqMatches(current.scope,AppScope(out.state)) then return true
            if not RqMatches(current.scope,UiField(event,"scope",invalid)) or UiField(event,"dialogId",invalid)<>current.dialogId then return true
            if kind="search_filter" and UiField(event,"queryId",invalid)<>current.queryId then return true
            input=LiveSearchCopy(event)
            input["kind"]=Mid(kind,8)
            if kind="search_tick" then input["kind"]="tick"
            AppLiveSearchApply(out,input)
            if kind="search_submit" or kind="search_cancel" then out.effects.Push({type:"search_restore_focus",scope:current.scope,dialogId:current.dialogId})
            return true
        end if
    end for
    return false
end function

sub AppLiveSearchAfter(out as Object,event as Object)
    state=out.state
    live=UiField(state,"liveSearch",invalid)
    kind=UiField(event,"type","")
    hardRetired=kind="memory_pressure" or (kind="nav" and UiField(event,"key","")="sign_out")
    retired=hardRetired
    if live<>invalid
        retired=retired or UiField(state.view,"listKind","")<>"search" or not RqMatches(live.scope,AppScope(state))
        if retired
            out.effects.Push({type:"search_retire",scope:live.scope,dialogId:live.dialogId,restoreScope:AppScope(state)})
            state["liveSearch"]=invalid
            if hardRetired and UiField(state.view,"listKind","")="search"
                state.view["items"]=[]
                state.view["searchUi"]={enabled:true,query:"",filter:"all",dialogId:"",queryId:-1,recentsVisible:true}
                state.view["status"]="Enter a new query to search."
            end if
        end if
    end if
    if not hardRetired and UiField(state.view,"listKind","")="search" and UiField(state,"liveSearch",invalid)=invalid
        dialogId=AppLiveSearchDialogId(state)
        restored=LiveSearchCreate(AppScope(state),dialogId,state.searchRecents)
        if restored<>invalid
            view=UiField(state.view,"searchUi",{})
            restored["query"]=LiveSearchQuery(UiField(view,"query",state.searchQuery))
            restored["filter"]=UiField(view,"filter","all")
            if restored.filter<>"all" and restored.filter<>"movies" and restored.filter<>"shows" then restored["filter"]="all"
            restored["items"]=LiveSearchFilterCards(UiField(state.view,"items",[]),restored.scope,restored.filter,100,true)
            restored["local"]=restored.items
            restored["dialogOpen"]=false
            restored["nextCursor"]=UiField(state,"nextCursor","")
            state["liveSearch"]=restored
            AppLiveSearchPaint(state)
        end if
    end if
end sub
