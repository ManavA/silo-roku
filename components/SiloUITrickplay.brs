sub TransportTrickplayInit()
    m.tpClip = m.top.findNode("transportThumbnailClip")
    m.tpPoster = m.top.findNode("transportThumbnail")
    m.tpPoster.observeField("loadStatus","onTransportTrickplayLoad")
    m.tpSequence = 0
end sub

sub TransportTrickplayClear()
    if m.tpPoster = invalid then return
    m.tpClip.visible = false
    m.tpPoster.uri = ""
    m.tpAttempted = false
    m.tpSequence = NumberOr(m.tpSequence,0) + 1
    if m.tpTask <> invalid then m.tpTask.cancelled = true
end sub

function TransportTrickplayEligible() as Boolean
    if m.memoryHigh = true or m.view <> "player" or m.provider <> "silo" then return false
    if m.transportPreviewMs = invalid or m.transportEnabled <> true or not m.transport.visible then return false
    if type(m.playPlan) <> "roAssociativeArray" or type(m.playItem) <> "roAssociativeArray" then return false
    if m.playPlan.provider <> "silo" or ArtworkText(m.playPlan,"itemId") <> ArtworkText(m.playItem,"itemId") or ArtworkText(m.playItem,"itemId") = "" then return false
    if not CreateObject("roRegex","^[1-9][0-9]{0,17}$","").IsMatch(ArtworkText(m.playPlan,"versionId")) then return false
    owner = m.nativePlaybackOwner
    if type(owner) <> "roAssociativeArray" or m.nativePlaybackToken <> m.playToken then return false
    return owner.sourceId = m.sourceId and owner.profileId = m.profileId and owner.generation = m.generation
end function

function TransportTrickplayOwned(job as Object) as Boolean
    if not TransportTrickplayEligible() then return false
    return job.sourceId = m.sourceId and job.profileId = m.profileId and job.generation = m.generation and job.playToken = m.playToken and job.itemId = m.playPlan.itemId and job.fileId = m.playPlan.versionId and job.sequence = m.tpSequence and job.sessionRevision = DetailPhotoSessionRevision()
end function

function TransportTrickplayCreateTask() as Object
    return CreateObject("roSGNode","SiloUITrickplayTask")
end function

sub TransportTrickplayUpdate()
    if m.tpPoster = invalid then return
    if not TransportTrickplayEligible() then TransportTrickplayClear():return
    if m.tpTask <> invalid
        if m.tpTask.cancelled
            if m.tpTask.state <> "stop" and m.tpTask.state <> "STOP" then return
            m.tpTask = invalid
        else if not TransportTrickplayOwned(m.tpTask.job)
            TransportTrickplayClear()
            return
        end if
    end if
    if m.tpTask = invalid and m.tpAttempted <> true
        revision = DetailPhotoSessionRevision()
        if revision < 0 then return
        m.tpAttempted = true
        m.tpSequence = NumberOr(m.tpSequence,0) + 1
        task = TransportTrickplayCreateTask()
        if task = invalid then return
        task.job = {sourceId:m.sourceId,profileId:m.profileId,generation:m.generation,playToken:m.playToken,itemId:m.playPlan.itemId,fileId:m.playPlan.versionId,sequence:m.tpSequence,sessionRevision:revision}
        task.targetMs = m.transportPreviewMs
        task.observeField("result","onTransportTrickplayResult")
        m.tpTask = task
        task.control = "RUN"
    end if
    if m.tpTask = invalid then return
    m.tpTask.targetMs = m.transportPreviewMs
    result = m.tpTask.result
    m.tpClip.visible = false
    if ArtworkField(result,"ok",false) <> true then m.tpPoster.uri = "":return
    if result.expires <= CreateObject("roDateTime").AsSeconds() + 5 then m.tpPoster.uri = "":return
    tile = SiloUITrickplayTile(result,m.transportPreviewMs)
    if tile.ok <> true or tile.sheet <> result.sheet then m.tpPoster.uri = "":return
    scale = 240.0 / result.width
    if result.height * scale > 136 then scale = 136.0 / result.height
    m.tpClip.clippingRect = [0,0,result.width*scale,result.height*scale]
    m.tpPoster.width = result.sheetWidth * scale
    m.tpPoster.height = result.sheetHeight * scale
    m.tpPoster.loadWidth = m.tpPoster.width
    m.tpPoster.loadHeight = m.tpPoster.height
    m.tpPoster.translation = [-tile.x*scale,-tile.y*scale]
    if m.tpPoster.uri <> result.uri then m.tpPoster.uri = result.uri:return
    m.tpClip.visible = m.tpPoster.loadStatus = "ready"
end sub

sub onTransportTrickplayResult(event as Object)
    if m.tpTask = invalid then return
    if not event.GetRoSGNode().isSameNode(m.tpTask) then return
    TransportTrickplayUpdate()
end sub

sub onTransportTrickplayLoad()
    TransportTrickplayUpdate()
end sub
