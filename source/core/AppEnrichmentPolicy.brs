' Optional catalog routes compose around the core app reducer. Provider-owned
' identities remain authoritative; public metadata never supplies a native ID.
function AppShellReduce(state as Object, event as Object) as Object
    AppEnrichmentBind(state)
    out = {state:state,effects:[]}
    if UiField(state,"liveSearchEnabled",false)=true
        if AppLiveSearchHandle(out,event)
            AppDetailDecorate(out.state)
            return out
        end if
    end if
    if AppDetailHandle(out,event)
        if UiField(out.state,"liveSearchEnabled",false)=true then AppLiveSearchAfter(out,event)
        AppDetailDecorate(out.state)
        return out
    end if
    if AppEnrichmentHandle(out,event)
        if UiField(out.state,"liveSearchEnabled",false)=true then AppLiveSearchAfter(out,event)
        AppDetailDecorate(out.state)
        return out
    end if
    out = AppReduce(state,event)
    AppEnrichmentBind(out.state)
    kind = UiField(event,"type","")
    if kind = "memory_pressure" or (kind="nav" and UiField(event,"key","")="sign_out")
        out.state.enrichment["owned"] = invalid
        out.state.enrichment["ava"] = invalid
        if kind="memory_pressure" then out.state.enrichment["cacheEnabled"]=false
    else if kind="memory_recovered"
        out.state.enrichment["cacheEnabled"]=true
    else if kind = "result"
        result = UiField(event,"result",{})
        if UiField(result,"ok",false)=true and RqMatches(AppScope(out.state),result)
            purpose = UiField(UiField(event,"pending",{}),"purpose","")
            items = invalid
            if purpose="plex_home" or purpose="home" then items=UiField(out.state.view,"items",[])
            if purpose="items" or purpose="search" then items=UiField(UiField(result,"data",{}),"items",[])
            if purpose="detail" then items=[UiField(UiField(result,"data",{}),"item",invalid)]
            if items<>invalid then AppEnrichmentRemember(out.state,items)
        end if
    end if
    if UiField(out.state,"liveSearchEnabled",false)=true then AppLiveSearchAfter(out,event)
    AppDetailDecorate(out.state)
    return out
end function

sub AppEnrichmentBind(state as Object)
    scope=AppScope(state)
    previous=UiField(state,"enrichment",invalid)
    same=type(previous)="roAssociativeArray"
    for each key in ["provider","sourceId","profileId"]
        if UiField(previous,key,invalid)<>scope[key] then same=false
    end for
    if same then return
    state["enrichment"]={provider:scope.provider,sourceId:scope.sourceId,profileId:scope.profileId,owned:invalid,ava:invalid,cacheEnabled:true}
end sub

sub AppEnrichmentRemember(state as Object, items as Dynamic)
    if UiField(state.enrichment,"cacheEnabled",true)<>true then return
    scope=AppScope(state)
    state.enrichment["owned"]=ServiceOwnedIndexAdd(state.enrichment.owned,items,scope,500)
    state.enrichment["ava"]=AvaCandidateCacheAdd(state.enrichment.ava,items,scope,180)
end sub

sub AppEnrichmentDiscover(out as Object, page as Integer)
    AppBrowse(out,"Discover","discover","grid",[],"discover")
    out.state["pageRequest"]=invalid
    out.state.view["catalogPage"]=page
    out.state.view["catalogNextPage"]=0
    out.state.view.status="Loading trending titles…"
    AppRequest(out,"discover_trending",{page:page},"discover")
end sub

sub AppEnrichmentAsk(out as Object)
    out.effects.Push({type:"keyboard",purpose:"ava",title:"Ask AVA",value:"",submitLabel:"Ask"})
end sub

function AppEnrichmentHandle(out as Object, event as Object) as Boolean
    state=out.state
    kind=UiField(event,"type","")
    if kind="nav"
        key=UiField(event,"key","")
        if key<>"discover" and key<>"services" and key<>"ava" then return false
        if ServiceScope(AppScope(state))=invalid then return true
        state.history=[]
        state["pageRequest"]=invalid
        if key="discover"
            AppEnrichmentDiscover(out,1)
        else if key="services"
            entries=UiServiceEntries()
            for each item in entries
                item["key"]="service:"+item.slug
            end for
            AppBrowse(out,"Services","services","list",entries,"services")
        else
            AppBrowse(out,"AVA","ava","grid",[{title:"Ask AVA",uiAction:"ask_ava",key:"ask_ava"}],"ava")
            AppEnrichmentAsk(out)
        end if
        return true
    else if kind="keyboard" and UiField(event,"purpose","")="ava"
        if UiField(state.view,"listKind","")<>"ava" then return true
        value=UiField(event,"value",invalid)
        if type(value)<>"String" and type(value)<>"roString" then return true
        prompt=Left(value.Trim(),1000)
        if prompt="" then return true
        candidates=AvaCandidateCacheItems(state.enrichment.ava,AppScope(state))
        AppBrowse(out,"AVA","ava","grid",[],"ava")
        state.view["avaPrompt"]=prompt
        state.view.status="Finding recommendations…"
        AppRequest(out,"ava_recommend",{prompt:prompt,libraryCandidates:candidates,limit:30},"ava")
        return true
    else if kind="next_page" and UiField(state.view,"listKind","")="discover"
        nextPage=UiNumber(UiField(state.view,"catalogNextPage",0),0)
        if nextPage>=2 and nextPage<=20 and nextPage=Int(nextPage)
            AppRemember(state,UiField(state.view,"selectedIndex",0))
            AppEnrichmentDiscover(out,Int(nextPage))
        end if
        return true
    else if kind="select"
        listKind=UiField(state.view,"listKind","")
        if listKind<>"discover" and listKind<>"services" and listKind<>"service_catalog" and listKind<>"ava" then return false
        index=Int(UiNumber(UiField(event,"index",-1),-1))
        items=UiField(state.view,"items",[])
        if index<0 or index>=items.Count() then return true
        state.view["selectedIndex"]=index
        item=items[index]
        action=UiField(item,"uiAction","")
        if action="service_search"
            out.effects.Push({type:"keyboard",purpose:"search",title:"Search your library",value:"",submitLabel:"Search"})
        else if action="ask_ava"
            AppEnrichmentAsk(out)
        else if listKind="services"
            request=UiServiceCatalogRequest(item)
            if not request.ok then return true
            AppRemember(state,index)
            fallback=ServiceViewEntries(invalid,state.enrichment.owned,AppScope(state),100)
            AppBrowse(out,request.title+" in your library","service_catalog","grid",fallback.items,"services")
            state.view["serviceSlug"]=request.params.slug
            state.view.status="Loading service titles… More titles may be available in your source."
            AppRequest(out,request.action,request.params,"service_catalog")
        else if listKind="service_catalog"
            if UiField(item,"provider","")<>state.provider or UiField(item,"sourceId","")<>state.sourceId then return true
            AppRemember(state,index)
            AppOpenDetail(out,item)
        else
            request=invalid
            if listKind="ava"
                resolved=UiAvaResolveOwned(item,state.enrichment.ava,AppScope(state))
                if resolved.ok and UiField(resolved,"state","")="owned"
                    AppRemember(state,index)
                    AppOpenDetail(out,resolved.item)
                    return true
                end if
                request=UiAvaSearchRequest(item,state.provider,AppScope(state))
            else
                request=UiMetadataSearchRequest(item,state.provider,state.sourceId)
            end if
            if UiField(request,"ok",false)<>true then return true
            AppRemember(state,index)
            navKey=state.view.navKey
            AppBrowse(out,"Library matches for "+Left(UiField(item,"title","Title"),120),"owned_matches","grid",[],navKey)
            state.view["catalogQuery"]=request.params.query
            state.view["catalogType"]=UiField(request.params,"type","")
            state.view.status="Checking your library… Choose a title from your source."
            AppRequest(out,request.action,request.params,"catalog_owned_search")
        end if
        return true
    else if kind="result"
        pending=UiField(event,"pending",{})
        purpose=UiField(pending,"purpose","")
        if purpose<>"discover" and purpose<>"service_catalog" and purpose<>"ava" and purpose<>"catalog_owned_search" then return false
        result=UiField(event,"result",{})
        if not RqMatches(AppScope(state),result) then return true
        expectedKind=purpose
        if purpose="catalog_owned_search" then expectedKind="owned_matches"
        if UiField(state.view,"listKind","")<>expectedKind then return true
        expectedAction=purpose
        if purpose="discover" then expectedAction="discover_trending"
        if purpose="ava" then expectedAction="ava_recommend"
        if purpose="catalog_owned_search"
            expectedAction="search"
            if state.provider="silo" then expectedAction="catalog_query"
        end if
        if UiField(result,"action","")<>expectedAction then return true
        if UiField(UiField(pending,"job",{}),"action","")<>expectedAction then return true
        params=UiField(UiField(pending,"job",{}),"params",{})
        if purpose="discover"
            page=UiField(state.view,"catalogPage",0)
            if UiField(params,"page",0)<>page then return true
        else if purpose="service_catalog"
            if UiField(params,"slug","")<>UiField(state.view,"serviceSlug","") then return true
        else if purpose="ava"
            if UiField(params,"prompt","")<>UiField(state.view,"avaPrompt","") then return true
        else
            if UiField(params,"query","")<>UiField(state.view,"catalogQuery","") then return true
            if UiField(params,"type","")<>UiField(state.view,"catalogType","") then return true
        end if
        if UiField(result,"ok",false)<>true
            state.view.status=UiErrorMessage(UiField(result,"errorCode","task_failed"))
            return true
        end if
        data=UiField(result,"data",{})
        if purpose="discover"
            if UiField(data,"page",0)<>state.view.catalogPage then return true
            entries=UiMetadataEntries(data,20)
            for each item in entries
                item["key"]=item.catalogId
            end for
            nextPage=UiNumber(UiField(data,"nextPage",0),0)
            state.view["hasNextPage"]=entries.Count()>0 and nextPage>state.view.catalogPage and nextPage<=20 and nextPage=Int(nextPage)
            state.view["catalogNextPage"]=0
            if state.view.hasNextPage then state.view["catalogNextPage"]=Int(nextPage)
            state.view.items=entries
            state.view.status="OK checks your library for this title."
            if entries.Count()=0 then state.view.status="No trending titles are available right now."
        else if purpose="service_catalog"
            matched=ServiceViewEntries(data,state.enrichment.owned,AppScope(state),100)
            state.view.items=matched.items
            state.view.status="Verified library matches. More titles may be available in your source."
        else if purpose="ava"
            entries=UiAvaEntries(data,state.enrichment.ava,AppScope(state),30)
            for each item in entries
                item["key"]=item.catalogId
            end for
            entries.Push({title:"Ask AVA again",uiAction:"ask_ava",key:"ask_ava"})
            state.view.items=entries
            state.view.status=Left(UiField(data,"reply","Choose a recommendation to check your library."),180)
        else
            items=UiMetadataLibraryCandidates(UiField(data,"items",[]),state.sourceId,100)
            state.view.items=items
            AppEnrichmentRemember(state,items)
            state.view.status="Choose a title from your source."
            if items.Count()=0 then state.view.status="No titles were found on this search page. More titles may be available."
        end if
        return true
    end if
    return false
end function
