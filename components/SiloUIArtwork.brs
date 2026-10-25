' Optional focused artwork shares the existing exact-identity metadata pipeline.
sub SiloUIArtworkInit()
    m.publicArtwork = PublicArtworkCreate()
    m.publicArtworkClock = CreateObject("roTimespan")
    m.publicArtworkTimer = m.top.findNode("publicArtworkTimer")
    m.publicArtworkTimer.observeField("fire", "onPublicArtworkTimer")
end sub

function SiloUIArtworkNow() as Double
    return m.publicArtworkClock.TotalMilliseconds()
end function

sub SiloUIArtworkFocus(node as Dynamic)
    if m.publicArtwork = invalid then return
    if node = invalid or m.memoryHigh = true then SiloUIArtworkRetire():return
    if m.publicArtwork.disabled
        recovered = PublicArtworkReduce(m.publicArtwork,{kind:"recover",nowMs:SiloUIArtworkNow()})
        m.publicArtwork = recovered.state
    end if
    item = node.item
    if type(item) <> "roAssociativeArray" then SiloUIArtworkRetire():return
    scope = {provider:m.provider,sourceId:m.sourceId,profileId:m.profileId,generation:m.generation}
    m.publicArtworkNode = node
    m.publicArtworkView = m.view
    outcome = PublicArtworkReduce(m.publicArtwork,{kind:"focus",active:true,scope:scope,scopeKey:"route-"+m.generation.ToStr(),key:TextOr(item.itemId),item:item,nowMs:SiloUIArtworkNow()})
    SiloUIArtworkApply(outcome)
end sub

sub SiloUIArtworkRetire()
    if m.publicArtwork = invalid then return
    m.publicArtworkNode = invalid
    m.publicArtworkTimer.control = "stop"
    kind = "focus"
    if m.memoryHigh = true then kind = "memory"
    outcome = PublicArtworkReduce(m.publicArtwork,{kind:kind,active:false,nowMs:SiloUIArtworkNow()})
    m.publicArtwork = outcome.state
    viewer = m.publicArtwork.viewer
    if viewer <> invalid
        if viewer.provider <> m.provider or viewer.sourceId <> m.sourceId or viewer.profileId <> m.profileId then m.publicArtwork.cache = []
    end if
end sub

sub SiloUIArtworkFocused()
    if m.publicArtwork = invalid then return
    node = invalid
    if m.view = "home" and m.zone = "rows" and m.rows.content <> invalid
        focus = m.rows.rowItemFocused
        if type(focus) = "roArray" and focus.Count() = 2
            row = m.rows.content.getChild(focus[0])
            if row <> invalid then node = row.getChild(focus[1])
        end if
    else if m.view = "library" and m.zone = "grid" and m.grid.content <> invalid
        node = m.grid.content.getChild(m.grid.itemFocused)
    else if m.view = "search" and m.zone = "searchGrid" and m.searchGrid.content <> invalid
        node = m.searchGrid.content.getChild(m.searchGrid.itemFocused)
    else if m.view = "detail" and m.detailItem <> invalid
        node = {item:m.detailItem}
    end if
    SiloUIArtworkFocus(node)
end sub

sub onPublicArtworkTimer()
    if m.memoryHigh = true or not SiloUIArtworkCurrent() then SiloUIArtworkRetire():return
    outcome = PublicArtworkReduce(m.publicArtwork,{kind:"tick",nowMs:SiloUIArtworkNow()})
    SiloUIArtworkApply(outcome)
end sub

sub SiloUIArtworkResult(result as Object, owner as Object)
    if not SiloUIArtworkCurrent() then SiloUIArtworkRetire()
    outcome = PublicArtworkReduce(m.publicArtwork,{kind:"result",owner:owner,ok:result.ok,data:result.data,nowMs:SiloUIArtworkNow()})
    SiloUIArtworkApply(outcome)
end sub

sub SiloUIArtworkApply(outcome as Object)
    m.publicArtwork = outcome.state
    projection = PublicArtworkProjection(m.publicArtwork)
    node = m.publicArtworkNode
    if projection.active and node <> invalid and SiloUIArtworkCurrent() and m.memoryHigh <> true
        if projection.key = TextOr(node.item.itemId)
            poster = projection.posterUri
            if poster <> "" and node.artCandidates <> invalid
                candidates = []
                for each uri in node.artCandidates
                    if uri <> poster then candidates.Push(uri)
                end for
                candidates.Push(poster)
                if FormatJson(candidates) <> FormatJson(node.artCandidates) then node.artCandidates = candidates
            end if
            if m.view = "home" or m.view = "detail" then SiloUIArtworkBackdrop()
        end if
    end if
    for each effect in outcome.effects
        if effect.type = "timer"
            m.publicArtworkTimer.control = "stop"
            m.publicArtworkTimer.duration = effect.milliseconds / 1000.0
            m.publicArtworkTimer.control = "start"
        else if effect.type = "request"
            owner = ParseJson(FormatJson(effect.scope))
            owner["artworkOwner"] = effect.artworkOwner
            ApiOwned(effect.action,effect.params,effect.purpose,effect.artworkOwner,owner)
        end if
    end for
end sub

sub SiloUIArtworkBackdrop()
    if not SiloUIArtworkCurrent() then return
    projection = PublicArtworkProjection(m.publicArtwork)
    if not projection.active or projection.backdropUri = "" then return
    item = invalid
    if m.view = "home" then item = m.heroItem
    if m.view = "detail" then item = m.detailItem
    if item = invalid then return
    if projection.key <> TextOr(item.itemId) then return
    if m.pendingBackdrop = projection.backdropUri then return
    failedSource = m.backdrop.loadStatus = "failed" and m.backdrop.uri = m.pendingBackdrop
    if m.pendingBackdrop = "" or failedSource then SetBackdrop(projection.backdropUri)
end sub

function SiloUIArtworkCurrent() as Boolean
    if m.publicArtwork = invalid then return false
    wanted = m.publicArtwork.wanted
    if wanted = invalid or m.publicArtworkView <> m.view then return false
    scope = wanted.scope
    return scope.provider = m.provider and scope.sourceId = m.sourceId and scope.profileId = m.profileId and scope.generation = m.generation
end function
