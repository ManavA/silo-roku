' Account keys are mutation targets; native server rating keys remain playback IDs.
function AdBoolean(value as Dynamic) as Boolean
    return type(value)="Boolean" or type(value)="roBoolean"
end function

function AdWhole(value as Dynamic) as Boolean
    number=UiNumber(value,-1)
    if number<>number or number<0 or number>2147483646 then return false
    return number=Int(number)
end function

function AdScope(value as Dynamic) as Boolean
    if type(value)<>"roAssociativeArray" then return false
    for each field in ["provider","sourceId","profileId"]
        text=UiField(value,field,invalid)
        if type(text)<>"String" and type(text)<>"roString" then return false
    end for
    if Len(value.sourceId)>512 or Len(value.profileId)>256 then return false
    if value.provider<>"plex" then return false
    if not HmUiProviderScope(value.provider,value.sourceId) then return false
    return AdWhole(UiField(value,"generation",invalid))
end function

function AdScopeMatches(left as Dynamic,right as Dynamic,viewer = false as Boolean) as Boolean
    if not AdScope(left) or not AdScope(right) then return false
    fields=["provider","sourceId","profileId","generation"]
    if viewer then fields=["provider","sourceId","profileId"]
    for each field in fields
        if left[field]<>right[field] then return false
    end for
    return true
end function

function AdOperation(state as Object) as String
    sequence=UiField(state,"detailOperationSequence",0)
    if not AdWhole(sequence) or sequence>=2147483646 then return ""
    state["detailOperationSequence"]=sequence+1
    return "detail-"+(sequence+1).ToStr()
end function

function AdSeed(raw as Dynamic) as Dynamic
    if type(raw)<>"roAssociativeArray" then return invalid
    if UiField(raw,"provider","")<>"plex" then return invalid
    source=UiField(raw,"sourceId",invalid)
    if type(source)<>"String" and type(source)<>"roString" then return invalid
    if Len(source)>143 or Left(source,15)<>"plex-watchlist:" then return invalid
    if not PwIdentifier(Mid(source,16)) then return invalid
    kind=UiField(raw,"type","")
    if kind<>"movie" and kind<>"show" then return invalid
    member=UiField(raw,"inWatchlist",invalid)
    if not AdBoolean(member) then return invalid
    if not member then return invalid
    params=UiWatchlistMutationParams(raw,true)
    if params=invalid then return invalid
    key=params.watchlistRatingKey
    id=UiField(raw,"itemId","")
    if id<>"plex-watchlist:"+kind+":"+key then return invalid
    canonical=UiField(raw,"plexGuid","")
    if type(canonical)<>"String" and type(canonical)<>"roString" then return invalid
    if Len(canonical)>160 then return invalid
    if canonical<>""
        if Left(canonical,Len("plex://"+kind+"/"))<>"plex://"+kind+"/" then return invalid
        if PlexWatchlistRatingKeyFromGuid(canonical)<>key then return invalid
    end if
    incoming=UiField(raw,"guids",invalid)
    if type(incoming)<>"roArray" or incoming.Count()=0 or incoming.Count()>16 then return invalid
    guids=[]
    found=canonical=""
    for each guid in incoming
        if type(guid)<>"String" and type(guid)<>"roString" then return invalid
        if Len(guid)>160 then return invalid
        if not CreateObject("roRegex","^plex://(movie|show)/[A-Za-z0-9_-]+$|^(tmdb|tvdb)://[0-9]+$|^imdb://tt[0-9]+$","").IsMatch(guid) then return invalid
        if guid=canonical then found=true
        guids.Push(guid)
    end for
    if not found then return invalid
    return {provider:"plex",sourceId:source,itemId:id,type:kind,watchlistRatingKey:key,plexGuid:canonical,guids:guids,inWatchlist:true}
end function

function AdSeedMatches(left as Dynamic,right as Dynamic) as Boolean
    first=AdSeed(left)
    second=AdSeed(right)
    if first=invalid or second=invalid then return false
    return FormatJson(first)=FormatJson(second)
end function

function AdOwnedSeed(item as Dynamic,seed as Object,sourceId as String) as Boolean
    if type(item)<>"roAssociativeArray" then return false
    id=UiField(item,"itemId",invalid)
    if type(id)<>"String" and type(id)<>"roString" then return false
    if not CreateObject("roRegex","^[0-9]{1,128}$","").IsMatch(id) then return false
    if UiField(item,"provider","")<>"plex" or UiField(item,"sourceId","")<>sourceId then return false
    guids=UiField(item,"guids",invalid)
    if type(guids)<>"roArray" or guids.Count()>16 then return false
    native=UiWatchlistMutationParams(item,false)
    if seed.plexGuid<>"" and native<>invalid
        if native.plexGuid<>seed.plexGuid then return false
    end if
    return MatchOwnedWatchlistItem(seed,[item],sourceId)<>invalid
end function

function AdEnvelope(state as Object,owner as Dynamic,pending as Dynamic,result as Dynamic) as Boolean
    if type(owner)<>"roAssociativeArray" then return false
    job=UiField(pending,"job",invalid)
    if type(job)<>"roAssociativeArray" or type(result)<>"roAssociativeArray" then return false
    current=AppScope(state)
    if not AdScopeMatches(owner.scope,current) or not AdScopeMatches(job,current) or not AdScopeMatches(result,current) then return false
    if UiField(job,"action","")<>owner.action or UiField(result,"action","")<>owner.action then return false
    id=UiField(job,"requestId",invalid)
    if type(id)<>"String" and type(id)<>"roString" then return false
    if Len(id)=0 or Len(id)>128 or UiField(result,"requestId",invalid)<>id then return false
    return UiField(UiField(job,"detailOwner",invalid),"operationId","")=owner.operationId
end function

function AdContext(state as Object) as Dynamic
    if state.provider<>"plex" or not AppDetailOwned(state) then return invalid
    context=UiField(state.detail,"watchlistContext",invalid)
    if type(context)<>"roAssociativeArray" then return invalid
    if not AdScopeMatches(context.scope,AppScope(state),true) then return invalid
    item=state.detail.item
    member=UiField(item,"inWatchlist",invalid)
    if not AdBoolean(member) then return invalid
    if not member or UiField(item,"itemId","")<>context.itemId then return invalid
    params=UiWatchlistMutationParams(item,true)
    if params=invalid or params.watchlistRatingKey<>context.watchlistRatingKey then return invalid
    if UiField(context,"origin","")="watchlist"
        seed=AdSeed(UiField(context,"seed",invalid))
        if seed=invalid or seed.watchlistRatingKey<>context.watchlistRatingKey then return invalid
        if not AdOwnedSeed(item,seed,state.sourceId) then return invalid
    else if UiField(context,"origin","")="mutation"
        guids=UiField(item,"guids",[])
        if type(guids)<>"roArray" or guids.Count()>16 then return invalid
        native=UiWatchlistMutationParams(item,false)
        if native=invalid or native.plexGuid<>context.plexGuid then return invalid
        if PlexWatchlistRatingKeyFromGuid(native.plexGuid)<>context.watchlistRatingKey then return invalid
    else
        return invalid
    end if
    return context
end function

sub AdRetireWatchlistSeed(state as Object,context as Object)
    if UiField(context,"origin","")<>"watchlist" or not AdScopeMatches(context.scope,AppScope(state),true) then return
    seed=AdSeed(UiField(context,"seed",invalid))
    if seed=invalid or type(state.history)<>"roArray" then return
    for index=0 to state.history.Count()-1
        if index>=8 then exit for
        view=UiField(state.history[index],"view",invalid)
        if type(view)="roAssociativeArray" and UiField(view,"listKind","")="watchlist"
            rows=UiField(view,"items",invalid)
            if type(rows)="roArray" and rows.Count()<=100
                kept=[]
                changed=false
                for each row in rows
                    same=UiField(row,"itemId",invalid)=seed.itemId and UiField(row,"sourceId",invalid)=seed.sourceId
                    if same then same=AdSeedMatches(seed,row)
                    if same
                        changed=true
                    else
                        kept.Push(row)
                    end if
                end for
                if changed
                    view["items"]=kept
                    selected=UiNumber(UiField(view,"selectedIndex",0),0)
                    if not AdWhole(selected) then selected=0
                    if selected>=kept.Count() then selected=kept.Count()-1
                    if selected<0 then selected=0
                    view["selectedIndex"]=Int(selected)
                end if
            end if
        end if
    end for
end sub

sub AdTagRequest(out as Object,operationId as String)
    out.effects[out.effects.Count()-1]["detailOwner"]={operationId:operationId}
end sub

function AdWatchlistRoute(out as Object,event as Object) as Boolean
    state=out.state
    kind=UiField(event,"type","")
    if kind="select" and UiField(state.view,"listKind","")="watchlist"
        if not AdScope(AppScope(state)) or state.playerPending then return true
        index=UiField(event,"index",invalid)
        rows=UiField(state.view,"items",invalid)
        if not AdWhole(index) or type(rows)<>"roArray" then return true
        if index>=rows.Count() then return true
        row=rows[Int(index)]
        seed=AdSeed(row)
        if seed=invalid then return true
        old=UiField(state,"detailWatchlistResolve",invalid)
        if type(old)="roAssociativeArray"
            if AdScopeMatches(old.scope,AppScope(state)) and AdSeedMatches(old.seed,seed) then return true
        end if
        operation=AdOperation(state)
        if operation="" then return true
        state["watchlistSeed"]=row
        state["detailWatchlistResolve"]={scope:AppScope(state),operationId:operation,action:"watchlist_resolve",seed:seed,index:Int(index)}
        state.view.selectedIndex=Int(index)
        state.view.status="Checking your library…"
        AppRequest(out,"watchlist_resolve",{item:row},"watchlist_resolve")
        AdTagRequest(out,operation)
        return true
    end if
    if kind<>"result" then return false
    pending=UiField(event,"pending",{})
    purpose=UiField(pending,"purpose","")
    result=UiField(event,"result",{})
    job=UiField(pending,"job",{})
    params=UiField(job,"params",{})
    if purpose="watchlist_resolve"
        owner=UiField(state,"detailWatchlistResolve",invalid)
        if not AdEnvelope(state,owner,pending,result) then return true
        if state.view.kind<>"browse" or UiField(state.view,"listKind","")<>"watchlist" then return true
        if not AdSeedMatches(owner.seed,UiField(params,"item",invalid)) or not AdSeedMatches(owner.seed,UiField(state,"watchlistSeed",invalid)) then return true
        rows=UiField(state.view,"items",[])
        if owner.index>=rows.Count() or not AdSeedMatches(owner.seed,rows[owner.index]) then return true
        ok=UiField(result,"ok",invalid)
        if not AdBoolean(ok) then return true
        if not ok
            state["detailWatchlistResolve"]=invalid
            state.view.status=UiErrorMessage(UiField(result,"errorCode","task_failed"))
            return true
        end if
        data=UiField(result,"data",{})
        availability=UiField(data,"availability","")
        if availability="not_in_library"
            state["detailWatchlistResolve"]=invalid
            state.view.status="This title is not available in the selected Plex library."
            return true
        end if
        if availability<>"owned" then return true
        raw=UiField(data,"item",invalid)
        if not AdOwnedSeed(raw,owner.seed,state.sourceId) then return true
        item=UiWatchlistOwnedItem(data,owner.seed,state.sourceId)
        if item=invalid then return true
        state["detailWatchlistResolve"]=invalid
        AppRemember(state,owner.index)
        AppOpenDetail(out,item)
        request=out.effects[out.effects.Count()-1]
        request.params["inWatchlist"]=true
        request.params["watchlistRatingKey"]=owner.seed.watchlistRatingKey
        request.params["plexGuid"]=owner.seed.plexGuid
        request["detailOwner"]={operationId:owner.operationId}
        state["detailWatchlistRead"]={scope:AppScope(state),action:"detail",operationId:owner.operationId,
            itemId:item.itemId,seed:owner.seed,watchlistRatingKey:owner.seed.watchlistRatingKey,plexGuid:owner.seed.plexGuid}
        return true
    else if purpose="detail"
        tagged=type(UiField(job,"detailOwner",invalid))="roAssociativeArray" or type(UiField(state,"detailWatchlistRead",invalid))="roAssociativeArray"
        if type(params)="roAssociativeArray"
            if params.DoesExist("inWatchlist") or params.DoesExist("watchlistRatingKey") then tagged=true
        end if
        if not tagged then return false
        if type(params)<>"roAssociativeArray" then return true
        owner=UiField(state,"detailWatchlistRead",invalid)
        if not AdEnvelope(state,owner,pending,result) then return true
        if state.view.kind<>"detail" then return true
        member=UiField(params,"inWatchlist",invalid)
        if not AdBoolean(member) then return true
        if not member or UiField(params,"itemId","")<>owner.itemId or UiField(params,"watchlistRatingKey","")<>owner.watchlistRatingKey or UiField(params,"plexGuid","")<>owner.plexGuid then return true
        ok=UiField(result,"ok",invalid)
        if not AdBoolean(ok) then return true
        if not ok
            state["detailWatchlistRead"]=invalid
            state.view.status=UiErrorMessage(UiField(result,"errorCode","task_failed"))
            return true
        end if
        data=UiField(result,"data",{})
        item=UiField(data,"item",invalid)
        if UiField(item,"itemId","")<>owner.itemId or not AdOwnedSeed(item,owner.seed,state.sourceId) then return true
        data=UiDetailWithWatchlistContext(data,params,state.sourceId)
        data.item["watchlistRatingKey"]=owner.watchlistRatingKey
        data["watchlistContext"]={scope:owner.scope,itemId:owner.itemId,watchlistRatingKey:owner.watchlistRatingKey,
            plexGuid:owner.plexGuid,seed:owner.seed,origin:"watchlist"}
        state.detail=data
        state["detailWatchlistRead"]=invalid
        state.view.status=""
        AppSearchRemember(state,[data.item])
        AppEnrichmentRemember(state,[data.item])
        return true
    end if
    return false
end function

' Detail-only capabilities reuse normalized provider facts and ordinary routes.
' Choosing an extra loads its own Detail; neither parent IDs nor plans transfer.
function AppDetailOwned(state as Object) as Boolean
    if not HmUiProviderScope(state.provider,state.sourceId) then return false
    item=UiField(state.detail,"item",invalid)
    if type(item)<>"roAssociativeArray" then return false
    if UiField(item,"provider","")<>state.provider or UiField(item,"sourceId","")<>state.sourceId then return false
    id=UiField(item,"itemId",invalid)
    if type(id)<>"String" and type(id)<>"roString" then return false
    pattern="^[A-Za-z0-9_.:-]{1,256}$"
    if state.provider="plex" then pattern="^[0-9]{1,128}$"
    return CreateObject("roRegex",pattern,"").IsMatch(id)
end function

function AppDetailCapabilities(state as Object) as Object
    actions=AppDetailActions(state)
    if not AppDetailOwned(state) then return actions
    extraActions=[]
    scope=AppScope(state)
    playlist=BuildExtrasPlaylist(state.detail,scope,scope)
    if playlist.ok and playlist.items.Count()>0 then extraActions.Push("Extras")
    item=state.detail.item
    if state.provider="plex"
        if AdContext(state)<>invalid
            extraActions.Push("Remove from Watchlist")
        else if UiField(item,"inWatchlist",false)<>true
            if UiWatchlistMutationParams(item,false)<>invalid then extraActions.Push("Add to Watchlist")
        end if
    end if
    people=UiCreditEntries(state.detail,state.provider,state.sourceId,32)
    if people.Count()>0 then extraActions.Push("Cast & crew")
    result=[]
    for each action in actions
        if action="Back"
            for each extra in extraActions
                result.Push(extra)
            end for
        end if
        result.Push(action)
    end for
    return result
end function

sub AppDetailDecorate(state as Object)
    mutation=UiField(state,"detailMutation",invalid)
    if type(mutation)="roAssociativeArray"
        if not AdScopeMatches(UiField(mutation,"scope",{}),AppScope(state)) then state["detailMutation"]=invalid
    end if
    for each field in ["detailWatchlistResolve","detailWatchlistRead"]
        owner=UiField(state,field,invalid)
        if type(owner)="roAssociativeArray"
            if not AdScopeMatches(owner.scope,AppScope(state)) then state[field]=invalid
        end if
    end for
    if state.view.kind="detail" and AppDetailOwned(state) then state.view["actions"]=AppDetailCapabilities(state)
end sub

function AppDetailHandle(out as Object, event as Object) as Boolean
    state=out.state
    if AdWatchlistRoute(out,event) then return true
    kind=UiField(event,"type","")
    if kind="detail_action"
        action=UiField(event,"action","")
        if action<>"Cast & crew" and action<>"Extras" and action<>"Add to Watchlist" and action<>"Remove from Watchlist" then return false
        if state.view.kind<>"detail" or state.playerPending or not AppDetailOwned(state) then return true
        available=false
        for each candidate in AppDetailCapabilities(state)
            if candidate=action then available=true
        end for
        if not available then return true
        item=state.detail.item
        if action="Cast & crew"
            people=UiCreditEntries(state.detail,state.provider,state.sourceId,32)
            AppRemember(state,Int(UiNumber(UiField(state.view,"selectedIndex",0),0)))
            AppBrowse(out,"Cast & crew","credits","list",people,"library")
        else if action="Extras"
            scope=AppScope(state)
            playlist=BuildExtrasPlaylist(state.detail,scope,scope)
            AppRemember(state,Int(UiNumber(UiField(state.view,"selectedIndex",0),0)))
            AppBrowse(out,"Extras for "+Left(UiField(item,"title","this title"),120),"extras","list",playlist.items,"library")
        else
            if not AdScope(AppScope(state)) then return true
            mutation=UiField(state,"detailMutation",invalid)
            if type(mutation)="roAssociativeArray"
                if RqMatches(UiField(mutation,"scope",{}),AppScope(state)) then return true
            end if
            remove=action="Remove from Watchlist"
            params=UiWatchlistMutationParams(item,remove)
            if params=invalid then return true
            operation=AdOperation(state)
            if operation="" then return true
            requestAction="watchlist_add"
            expected=true
            if remove
                requestAction="watchlist_remove"
                expected=false
            end if
            state["detailMutation"]={scope:AppScope(state),itemId:item.itemId,params:params,
                operationId:operation,action:requestAction,expected:expected}
            state.view.status="Adding to your Plex Watchlist…"
            if remove then state.view.status="Removing from your Plex Watchlist…"
            AppRequest(out,requestAction,params,requestAction)
            AdTagRequest(out,operation)
        end if
        return true
    else if kind="select"
        listKind=UiField(state.view,"listKind","")
        if listKind<>"credits" and listKind<>"extras" then return false
        if not AppDetailOwned(state) or state.playerPending then return true
        index=UiNumber(UiField(event,"index",-1),-1)
        items=UiField(state.view,"items",[])
        if index<0 or index<>Int(index) or index>=items.Count() then return true
        item=items[Int(index)]
        if UiField(item,"provider","")<>state.provider or UiField(item,"sourceId","")<>state.sourceId then return true
        if listKind="extras"
            scope=AppScope(state)
            playlist=BuildExtrasPlaylist(state.detail,scope,scope)
            selected=ExtrasPlaylistItem(playlist,Int(index),scope)
            if not selected.ok or UiField(item,"itemId","")<>selected.item.itemId then return true
            AppRemember(state,Int(index))
            AppOpenDetail(out,selected.item)
        else
            ' Revalidate the visible person against the same owned Detail.
            people=UiCreditEntries(state.detail,state.provider,state.sourceId,32)
            if index>=people.Count() then return true
            person=people[Int(index)]
            if UiField(item,"personId","")<>person.personId or UiField(item,"name","")<>person.name then return true
            params={query:person.name,limit:100}
            action="search"
            if state.provider="silo"
                params={personId:person.personId,limit:100}
                action="person_items"
            end if
            AppRemember(state,Int(index))
            AppBrowse(out,"Titles for "+person.name,"person_items","grid",[],"library")
            state.view["personQuery"]=person.name
            state.view["personId"]=person.personId
            state.view.status="Checking your library…"
            AppRequest(out,action,params,"person_items")
        end if
        return true
    else if kind="result"
        pending=UiField(event,"pending",{})
        purpose=UiField(pending,"purpose","")
        if purpose<>"person_items" and purpose<>"watchlist_add" and purpose<>"watchlist_remove" then return false
        job=UiField(pending,"job",{})
        result=UiField(event,"result",{})
        if not RqMatches(AppScope(state),result) or not RqMatches(AppScope(state),job) then return true
        action=purpose
        if purpose="person_items"
            action="search"
            if state.provider="silo" then action="person_items"
        end if
        if UiField(job,"action","")<>action or UiField(result,"action","")<>action then return true
        params=UiField(job,"params",{})
        if purpose="person_items"
            if UiField(state.view,"listKind","")<>"person_items" then return true
            if state.provider="plex"
                if UiField(params,"query","")<>UiField(state.view,"personQuery","") then return true
            else
                if UiField(params,"personId","")<>UiField(state.view,"personId","") then return true
            end if
            if UiField(result,"ok",false)<>true
                state.view.status=UiErrorMessage(UiField(result,"errorCode","task_failed"))
                return true
            end if
            items=UiMetadataLibraryCandidates(UiField(UiField(result,"data",{}),"items",[]),state.sourceId,100)
            state.view.items=items
            state.view.status="Choose a title from your library. More titles may be available."
            if items.Count()=0 then state.view.status="No titles were found on this page."
            AppSearchRemember(state,items)
            AppEnrichmentRemember(state,items)
        else
            if state.view.kind<>"detail" or state.provider<>"plex" or not AppDetailOwned(state) then return true
            mutation=UiField(state,"detailMutation",invalid)
            if not AdEnvelope(state,mutation,pending,result) then return true
            if mutation.action<>purpose or mutation.itemId<>state.detail.item.itemId then return true
            if FormatJson(params)<>FormatJson(mutation.params) then return true
            if purpose="watchlist_remove"
                context=AdContext(state)
                if context=invalid or context.watchlistRatingKey<>mutation.params.watchlistRatingKey then return true
            else
                native=UiWatchlistMutationParams(state.detail.item,false)
                if native=invalid or native.plexGuid<>mutation.params.plexGuid then return true
            end if
            ok=UiField(result,"ok",invalid)
            if not AdBoolean(ok) then return true
            if not ok
                state["detailMutation"]=invalid
                state.view.status=UiErrorMessage(UiField(result,"errorCode","task_failed"))
                return true
            end if
            value=UiField(UiField(result,"data",{}),"inWatchlist",invalid)
            if not AdBoolean(value) or value<>mutation.expected then return true
            state["detailMutation"]=invalid
            state.detail.item["inWatchlist"]=value
            if value
                key=PlexWatchlistRatingKeyFromGuid(mutation.params.plexGuid)
                if key<>""
                    state.detail.item["watchlistRatingKey"]=key
                    state.detail["watchlistContext"]={scope:mutation.scope,itemId:mutation.itemId,watchlistRatingKey:key,
                        plexGuid:mutation.params.plexGuid,origin:"mutation"}
                end if
                state.view.status="Added to your Plex Watchlist."
            else
                AdRetireWatchlistSeed(state,context)
                state.view.status="Removed from your Plex Watchlist."
            end if
        end if
        return true
    end if
    return false
end function
