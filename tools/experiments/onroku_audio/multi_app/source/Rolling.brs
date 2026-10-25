' Opt-in cooperative linear pipeline. Disk reservations/overshoot headroom are
' admission policy, not a hard bound on native asynchronous writes.
function QaRollingState(url as String) as Object
    return {url:url,generation:1,startIndex:0,lifecycle:"active",phase:"descriptor",index:0,ready:false,job:invalid,transfer:invalid,cancelledIdentity:invalid,cancelCensusDone:false,sourceBytes:0#,diskCap:134217728#,lead:3,liveBytes:0#,window:{ok:true,count:0,sourceBytes:0#,audioBytes:0#,nextPts:-1,timescale:0,trackid:0},entries:[],snapshots:[],publication:0,targets:invalid,owned:{},first:0,eviction:0,position:0#,endSeconds:0#,failed:false,pendingCleanup:false,stock:invalid,descriptor:invalid,initPath:invalid,descriptorSerial:0,nextPoll:0,pollMs:1000,started:0,workKind:"append",workIndex:0,sourceLength:0#,hashJob:invalid,admissionAt:-1,nextAdmission:0,nextAppend:0,deferredAppendIndex:-1,deferredAppendLength:0#,admissionDeferred:false,demand:[],recoveryMs:20000,telemetry:invalid}
end function
function QaRollingPrefix(r as Object) as String
    return "/g"+r.generation.ToStr()+"/"
end function
function QaRollingTemp(r as Object) as String
    return "tmp:/g"+r.generation.ToStr()+"-"
end function
function QaRollingSourceIndex(r as Object, localIndex as Integer) as Integer
    return r.startIndex+localIndex
end function
sub QaRollingSetPhase(r as Object, phase as String)
    if r.telemetry=invalid
        r.phase=phase
    else
        QaRollingPhase(r,phase)
    end if
end sub
function QaRollingLiveBytes(r as Object) as Double
    if m.rollingSession=invalid then return r.liveBytes
    total=0#
    for each generation in m.rollingSession.generations
        total+=generation.liveBytes
    end for
    return total
end function
function QaRollingDiskCap(r as Object) as Double
    if m.rollingSession=invalid then return r.diskCap
    return m.rollingSession.cap
end function
sub QaRollingCancelWriter(r as Object)
    if r.transfer=invalid then return
    if r.telemetry<>invalid then r.telemetry.cancelledWriter=true
    r.cancelledIdentity=r.transfer.GetIdentity()
    transfer=r.transfer
    r.transfer=invalid
    r.pendingCleanup=true
    r.cancelAt=0
    if m.clock<>invalid then r.cancelAt=m.clock.TotalMilliseconds()
    transfer.AsyncCancel()
    transfer=invalid
end sub
function QaRollingSettleWriter(r as Object) as Boolean
    if r.cancelledIdentity=invalid then return true
    event=m.upstreamPort.GetMessage()
    if QaRemoteEventType(event)="roUrlEvent"
        if event.GetSourceIdentity()=r.cancelledIdentity
            r.cancelledIdentity=invalid:r.pendingCleanup=false
            return true
        end if
    end if
    if m.clock<>invalid
        if m.clock.TotalMilliseconds()-r.cancelAt>=250 then return QaRollingWriterCensus(r)
    end if
    return false
end function
function QaRollingWriterCensus(r as Object) as Boolean
    if r.cancelCensusDone then return not r.pendingCleanup
    r.cancelCensusDone=true
    if r.path=invalid then return false
    stable=0
    for pass=0 to 24
        remaining=0
        for each path in [r.path,r.path+".tmp"]
            stat=m.fs.Stat(path)
            if stat<>invalid
                if stat.DoesExist("size")
                    if not m.fs.Delete(path) then remaining+=1
                end if
            end if
        end for
        for each path in [r.path,r.path+".tmp"]
            stat=m.fs.Stat(path)
            if stat<>invalid
                if stat.DoesExist("size") then remaining+=1
            end if
        end for
        if remaining=0 then stable+=1 else stable=0
        if pass<24 then QaRollingCleanupYield()
    end for
    if stable<3
        if not r.failed and r.telemetry<>invalid then QaRollingTelemetryFail(r)
        r.failed=true
        if r.lifecycle="active" or m.stopLocal then m.top.failed=true
        return false
    end if
    r.cancelledIdentity=invalid:r.pendingCleanup=false
    ' Keep both names owned for the final census: a late native recreation can
    ' appear after this writer-only settlement pass.
    return true
end function
sub QaRollingStart(url as String, stock=invalid as Dynamic)
    m.top.rollingMode = true
    m.rolling = QaRollingState(url)
    if m.rollingTelemetryEnabled=true then QaRollingTelemetryInit(m.rolling,true)
    m.rollingSession={cap:m.rolling.diskCap,generations:[m.rolling],maxGeneration:1}
    m.rolling.stock = stock
    if stock<>invalid then m.rolling.started=m.clock.TotalMilliseconds()
    m.upstreamPort = QaRemotePort()
    m.routes = {}
end sub
' Preparation preserves the active route table and credentials. A replacement
' begins from a source fragment boundary and earns readiness from its own pairs.
function QaRollingPrepare(plan as Object) as Dynamic
    active=m.rolling
    if active=invalid or active.descriptor=invalid or m.preparing<>invalid then return invalid
    if m.rollingSession=invalid then m.rollingSession={cap:active.diskCap,generations:[active],maxGeneration:active.generation}
    if m.rollingSession.maxGeneration=invalid
        m.rollingSession.maxGeneration=active.generation
        for each generation in m.rollingSession.generations
            if generation.generation>m.rollingSession.maxGeneration then m.rollingSession.maxGeneration=generation.generation
        end for
    end if
    if plan.generationId<=m.rollingSession.maxGeneration or plan.sourceStartIndex<0 or plan.sourceStartIndex>=active.descriptor.fragments.Count() then return invalid
    if active.descriptor.DoesExist("binding")
        if plan.binding<>active.descriptor.binding then return invalid
    end if
    r=QaRollingState(active.url)
    r.generation=plan.generationId:r.startIndex=plan.sourceStartIndex
    r.lifecycle="preparing":r.stock=active.stock:r.descriptor=active.descriptor
    QaRollingSetPhase(r,"init"):r.endSeconds=plan.titleOriginUs/1000000#:r.position=r.endSeconds
    if m.rollingTelemetryEnabled=true then QaRollingTelemetryInit(r,true)
    if m.clock<>invalid then r.started=m.clock.TotalMilliseconds()
    m.rollingSession.generations.Push(r)
    m.rollingSession.maxGeneration=r.generation
    m.preparing=r
    return r
end function
function QaRollingActivate(generationId as Integer) as Boolean
    r=m.preparing
    if r=invalid then return false
    if r.generation<>generationId or not r.ready or r.failed then return false
    if m.rolling.transfer<>invalid or m.rolling.cancelledIdentity<>invalid or m.rolling.job<>invalid or m.rolling.hashJob<>invalid then return false
    if m.rolling.lifecycle<>"retired" then m.rolling.lifecycle="draining"
    r.lifecycle="active":m.rolling=r:m.preparing=invalid
    m.top.ready=true
    return true
end function
function QaRollingAbortPreparation() as Boolean
    r=m.preparing
    if r=invalid then return false
    if r.transfer<>invalid
        QaRollingCancelWriter(r)
        return false
    end if
    if r.cancelledIdentity<>invalid
        if not QaRollingSettleWriter(r) then return false
    end if
    if QaRollingHasPins(r) then return false
    QaRollingCleanup(r)
    if r.pendingCleanup then return false
    QaRollingReleaseGeneration(r)
    m.preparing=invalid
    return true
end function
' Current routes and historical playlist snapshots can both own live responses.
function QaRollingHasPins(r as Object) as Boolean
    if m.routes<>invalid
        for each path in m.routes
            route=m.routes[path]
            if route.DoesExist("owner")
                if route.owner.generation=r.generation and route.pins>0 then return true
            end if
        end for
    end if
    for each snapshot in r.snapshots
        if snapshot.pins>0 then return true
    end for
    return false
end function
' Session high-water identifies retired URLs without retaining their route table.
sub QaRollingReleaseGeneration(r as Object, preserveSource=false as Boolean)
    if m.routes<>invalid
        expired=[]
        for each path in m.routes
            route=m.routes[path]
            if route.DoesExist("owner")
                if route.owner.generation=r.generation then expired.Push(path)
            end if
        end for
        for each path in expired
            m.routes.Delete(path)
        end for
    end if
    if m.rollingSession<>invalid
        keep=[]
        for each generation in m.rollingSession.generations
            if generation.generation<>r.generation then keep.Push(generation)
        end for
        m.rollingSession.generations=keep
    end if
    r.liveBytes=0#:r.lifecycle="retired":r.ready=false
    r.entries=[]:r.snapshots=[]:r.owned={}:r.demand=[]
    if not preserveSource then r.stock=invalid:r.descriptor=invalid
    r.init=invalid:r.initPath=invalid
    r.window=invalid:r.targets=invalid:r.completedJob=invalid:r.source=invalid
    r.path=invalid
    if not preserveSource then r.url=""
    r.telemetry=invalid
end sub
' The caller explicitly ends native use of a drained generation. High-water
' rejects late URLs, so no old route or payload must remain reachable.
function QaRollingRetireGeneration(generationId as Integer, preserveSource=false as Boolean) as Boolean
    if m.rollingSession=invalid then return false
    for each r in m.rollingSession.generations
        if r.generation=generationId
            if r.lifecycle="retired" then return true
            if r.lifecycle<>"draining" or r.transfer<>invalid or r.cancelledIdentity<>invalid or r.job<>invalid or r.hashJob<>invalid or r.pendingCleanup then return false
            if QaRollingHasPins(r) then return false
            QaRollingCleanup(r)
            if r.pendingCleanup then return false
            QaRollingReleaseGeneration(r,preserveSource)
            return true
        end if
    end for
    return false
end function
function QaRollingBegin(r as Object, url as String, path as String, cap as Double, probe=false as Boolean) as Boolean
    if cap < 1 then return false
    if r.cancelledIdentity<>invalid then return false
    if r.stock=invalid
        if QaRemoteReference(url,"probe")=invalid then return false
    else
        c=r.stock
        if not QaStockContextValid(c) then return false
        if QaStockMediaReference(r.url,url,c.origin,c.routeItemId,c.mediaSourceId,c.sessionId)=invalid then return false
    end if
    transfer = QaRemoteTransfer()
    transfer.SetMessagePort(m.upstreamPort)
    transfer.SetUrl(url)
    transfer.RetainBodyOnError(false)
    ' Header is added only after exact binding validation, on a fresh transfer.
    ' Qualified native bearer contexts allow trusted-server response delegation.
    if r.stock<>invalid
        auth=QaStockAuthHeader(r.stock)
        if auth=invalid then return false
        if not transfer.AddHeader(auth.name,auth.value) then return false
    end if
    if probe then transfer.AddHeader("Range","bytes=0-0")
    tls = true
    if Left(url,8) = "https://"
        tls = transfer.SetCertificatesFile("common:/certs/ca-bundle.crt")
        tls = transfer.EnablePeerVerification(true) and tls
        tls = transfer.EnableHostVerification(true) and tls
    end if
    ' Ownership precedes launch; failed launch is conservatively unsettled.
    r.path = path
    r.cap = cap
    r.transfer = transfer
    r.timer = QaRemoteTimer()
    r.cancelling = false
    r.probing=probe
    r.owned[path]=true
    r.owned[path+".tmp"]=true
    if not tls
        r.transfer = invalid
        return false
    end if
    return transfer.AsyncGetToFile(path)
end function
sub QaRollingFail(r as Object)
    firstFailure=not r.failed
    if firstFailure and r.telemetry<>invalid then QaRollingTelemetryFail(r)
    r.failed = true
    if r.transfer<>invalid then QaRollingCancelWriter(r)
    r.ready = false
    if r.lifecycle="active"
        QaRollingClearContext(r)
        m.top.ready = false
        m.top.failed = true
    end if
    if r.job <> invalid
        QaFileAudioCancel(r.job)
        r.job=invalid
    end if
    if r.hashJob<>invalid
        r.hashJob.digest=invalid
        r.hashJob=invalid
    end if
end sub
sub QaRollingTick()
    if m.seek<>invalid then QaSeekTick()
    r=QaRollingNextWork()
    if r = invalid then return
    tickStart=0
    if r.telemetry<>invalid then tickStart=QaRollingTelemetryBeginTick(r)
    QaRollingTickOne(r)
    if r.telemetry<>invalid then QaRollingTelemetryEndTick(r,tickStart)
end sub
function QaRollingNextWork() as Dynamic
    if m.rollingSession=invalid then return m.rolling
    ' One transfer or extractor owns the work slot across all generations.
    for each generation in m.rollingSession.generations
        if generation.transfer<>invalid or generation.cancelledIdentity<>invalid or generation.job<>invalid or generation.hashJob<>invalid then return generation
    end for
    if m.seek<>invalid
        if m.seek.request<>invalid
            if m.seek.request.status="quiesce" then return invalid
        end if
    end if
    for each generation in m.rollingSession.generations
        if generation.lifecycle="draining" and generation.demand.Count()>0 then return generation
    end for
    if m.preparing<>invalid and not m.preparing.ready and not m.preparing.failed then return m.preparing
    if m.seek<>invalid
        if m.seek.intent then return invalid
    end if
    if m.rolling.lifecycle="retired" then return invalid
    return m.rolling
end function
sub QaRollingTickOne(r as Object)
    if r.cancelledIdentity<>invalid
        QaRollingSettleWriter(r)
        return
    end if
    if r.transfer <> invalid
        ' One message per loop; stale URL identities cannot complete a new write.
        event = m.upstreamPort.GetMessage()
        complete = false
        success = false
        if QaRemoteEventType(event) = "roUrlEvent"
            if event.GetSourceIdentity() = r.transfer.GetIdentity()
                complete = true
                code=event.GetResponseCode()
                success = code = 200 and not r.cancelling and r.timer.TotalMilliseconds()<10000
                if r.probing then success=code=206 and r.timer.TotalMilliseconds()<10000
                success = success and QaRemoteWithin(r.path,r.cap) and QaRemoteSize(r.path)>0 and QaRemoteSize(r.path+".tmp")=0
            end if
        end if
        if complete
            r.transfer = invalid
            r.pendingCleanup = false
            if m.stopLocal then return
            if not success
                QaRollingFail(r)
                return
            end if
            ' Matching completion settles this writer. Native Stat may return
            ' an empty AA for missing paths; size presence establishes existence.
            companion=m.fs.Stat(r.path+".tmp")
            if companion<>invalid
                if companion.DoesExist("size")
                    if not m.fs.Delete(r.path+".tmp")
                        QaRollingFail(r)
                        return
                    end if
                end if
            end if
            r.owned.Delete(r.path+".tmp")
            if r.probing
                length=QaRollingProbeLength(event,QaRemoteSize(r.path))
                r.liveBytes+=QaRemoteSize(r.path)
                QaRollingDelete(r,r.path)
                if length<1 or r.failed
                    QaRollingFail(r)
                    return
                end if
                if r.workKind="refill"
                    if length<>r.entries[r.workIndex].sourceSize
                        QaRollingFail(r)
                        return
                    end if
                end if
                r.sourceLength=length
                QaRollingSetPhase(r,"admit")
                r.admissionAt=m.clock.TotalMilliseconds()
                return
            end if
            r.liveBytes += QaRemoteSize(r.path)
            if r.phase = "descriptor"
                text=ReadAsciiFile(r.path)
                if r.stock=invalid
                    descriptor=QaRemotePlaylist(text,r.url,true)
                else
                    c=r.stock
                    descriptor=QaStockDescriptor(text,r.url,c.origin,c.routeItemId,c.mediaSourceId,c.sessionId)
                    if r.descriptor<>invalid then descriptor=QaStockDescriptorRefresh(r.descriptor,descriptor)
                end if
                ' Descriptor staging never becomes a route or extraction input.
                QaRollingDelete(r,r.path)
                if descriptor=invalid or r.failed
                    QaRollingFail(r)
                    return
                end if
                if r.stock<>invalid
                    if r.descriptor<>invalid
                        if descriptor.fragments.Count()=r.descriptor.fragments.Count() and descriptor.ended=r.descriptor.ended
                            r.pollMs=2000
                        else
                            r.pollMs=1000
                        end if
                    end if
                    r.nextPoll=m.clock.TotalMilliseconds()+r.pollMs
                end if
                r.descriptor=descriptor
                if m.seek<>invalid then QaSeekDescriptorAccepted(r,descriptor)
                if r.DoesExist("seekRefresh") then return
                if r.initPath=invalid
                    QaRollingSetPhase(r,"init")
                else
                    QaRollingSetPhase(r,"fragment")
                    ' Completion can arrive without another fragment to publish.
                    if descriptor.ended and QaRollingSourceIndex(r,r.index)=descriptor.fragments.Count()
                        if not QaRollingPublish(r)
                            QaRollingFail(r)
                            return
                        end if
                        QaRollingSetReady(r)
                    end if
                end if
            else if r.phase = "init"
                r.initPath = r.path
                r.init = CreateObject("roByteArray")
                if not r.init.ReadFile(r.path) or QaAudioTrack(r.init)=invalid
                    QaRollingFail(r)
                    return
                end if
                QaRollingSetPhase(r,"fragment")
            else
                r.source = r.path
                r.sourceSize = QaRemoteSize(r.path)
                if r.sourceSize<>r.sourceLength
                    QaRollingFail(r)
                    return
                end if
                r.hashJob=QaRollingHashStart(r.source,r.sourceSize)
                QaRollingSetPhase(r,"hash-source")
            end if
        else
            if m.stopLocal or r.timer.TotalMilliseconds()>=10000 or not QaRemoteWithin(r.path,r.cap)
                if not r.cancelling
                    QaRollingCancelWriter(r)
                    r.cancelling = true
                    r.cancelAt = m.clock.TotalMilliseconds()
                end if
                if not m.stopLocal then QaRollingFail(r)
            end if
            return
        end if
    end if
    if m.stopLocal or r.failed then return
    if r.stock<>invalid and not r.ready and m.clock.TotalMilliseconds()-r.started>=120000
        QaRollingFail(r)
        return
    end if
    if r.hashJob<>invalid
        hashBefore=0
        if r.telemetry<>invalid then hashBefore=r.hashJob.at
        QaRollingHashStep(r.hashJob)
        if r.telemetry<>invalid
            hashed=r.hashJob.at-hashBefore
            if r.phase="hash-source" then r.telemetry.hashSource+=hashed
            if r.phase="hash-audio" then r.telemetry.hashAudio+=hashed
        end if
        if not r.hashJob.done then return
        if not r.hashJob.ok
            QaRollingFail(r)
            return
        end if
        digest=r.hashJob.value:r.hashJob=invalid
        if r.phase="hash-source"
            if r.workKind="refill"
                if digest<>r.entries[r.workIndex].sourceDigest
                    QaRollingFail(r)
                    return
                end if
            end if
            r.sourceDigest=digest
            target=QaRollingTemp(r)+"audio-"+QaRollingSourceIndex(r,r.workIndex).ToStr()+".m4s"
            r.owned[target]=true
            r.job=QaFileAudioStart(r.init,r.source,target,r.sourceSize,r.diskCap)
            QaRollingSetPhase(r,"extract")
        else
            r.audioDigest=digest
            QaRollingFinishPair(r)
        end if
        return
    end if
    if r.lifecycle="active" then QaRollingRetire(r)
    if r.failed then return
    if r.job <> invalid
        if r.job.phase="header"
            moof=QaFind(r.job.header,0,Int(QaU32(r.job.header,0)),"moof")
            mfhd=QaFind(r.job.header,moof.body,moof.finish,"mfhd")
            QaSet32(r.job.header,mfhd.body+4,QaRollingSourceIndex(r,r.workIndex)+1)
        end if
        QaFileAudioStep(r.job)
        if not r.job.done then return
        if not r.job.ok
            QaRollingFail(r)
            return
        end if
        j = r.job
        size = QaRemoteSize(j.target)
        nextWindow = QaMultiContinuity(r.window,j.plan,r.sourceSize,size)
        if r.workKind="refill" then nextWindow=QaMultiContinuity({ok:true,count:0,sourceBytes:0#,audioBytes:0#},j.plan,r.sourceSize,size)
        if not nextWindow.ok or QaRollingLiveBytes(r)+size+1048576>QaRollingDiskCap(r)
            QaFileAudioCancel(j)
            r.owned[j.target]=true
            QaRollingFail(r)
            return
        end if
        r.owned[j.target]=true
        if r.workKind="append" and r.index=0
            audioInitPath=QaRollingTemp(r)+"audio-init.mp4"
            r.owned[audioInitPath]=true
            if not j.audioInit.WriteFile(audioInitPath)
                QaRollingFail(r)
                return
            end if
            r.liveBytes += j.audioInit.Count()
        end if
        r.liveBytes += size
        duration = (nextWindow.nextPts-j.plan.samples[0].pts)/j.plan.timescale
        if QaRollingLiveBytes(r)+1048576#>QaRollingDiskCap(r)
            QaRollingFail(r)
            return
        end if
        r.completedJob=j:r.nextWindow=nextWindow:r.completedDuration=duration
        r.job=invalid
        r.hashJob=QaRollingHashStart(j.target,size)
        QaRollingSetPhase(r,"hash-audio")
        return
    end if
    if r.lifecycle="draining" and r.phase="fragment" and r.demand.Count()=0 then return
    ' A demanded old route wins over prefetch, once active work has yielded.
    if r.phase="fragment" and r.demand.Count()>0
        i=r.demand.Shift()
        if not r.entries[i].resident
            r.workKind="refill":r.workIndex=i:r.sourceLength=0#
            if r.telemetry<>invalid then QaRollingTelemetryDemandStarted(r,i)
            QaRollingSetPhase(r,"probe")
        end if
    end if
    if r.stock<>invalid and r.job=invalid
        if r.descriptor<>invalid
            if (r.phase="fragment" or r.phase="init") and not r.descriptor.ended and m.clock.TotalMilliseconds()>=r.nextPoll then QaRollingSetPhase(r,"descriptor")
            if r.phase="init" and r.descriptor.init=invalid then return
        end if
    end if
    if r.phase="fragment"
        if m.clock.TotalMilliseconds()<r.nextAppend then return
        if QaRollingSourceIndex(r,r.index)=r.descriptor.fragments.Count() then return
        if r.index-r.first>=64 then return
        if r.index>=r.lead and r.endSeconds-r.position>=24 then return
    end if
    if r.phase="fragment"
        r.workKind="append":r.workIndex=r.index
        if r.deferredAppendIndex=r.index and r.deferredAppendLength>0
            ' Descriptor fragment identity is immutable in this generation.
            ' Reuse the validated probe length while optional append is paused.
            r.sourceLength=r.deferredAppendLength:r.admissionAt=m.clock.TotalMilliseconds()
            QaRollingSetPhase(r,"admit")
        else
            QaRollingSetPhase(r,"probe")
        end if
    end if
    if r.phase="probe"
        url=r.descriptor.fragments[QaRollingSourceIndex(r,r.workIndex)]
        path=QaRollingTemp(r)+"probe.m4s"
        if not QaRollingBegin(r,url,path,1#,true) then QaRollingFail(r)
        return
    end if
    if r.phase="admit"
        if r.workKind="append" and r.demand.Count()>0
            r.deferredAppendIndex=r.index:r.deferredAppendLength=r.sourceLength
            QaRollingSetPhase(r,"fragment")
            return
        end if
        now=m.clock.TotalMilliseconds()
        if now-r.admissionAt>=r.recoveryMs
            QaRollingFail(r)
            return
        end if
        if now<r.nextAdmission then return
        if not QaRollingReserve(r,r.sourceLength)
            if r.failed then return
            if r.admissionDeferred
                ' Speculation is optional: leave the recovery deadline and yield
                ' the work slot so queued HTTP demand wins on the next tick.
                r.nextAppend=now+1000
                r.deferredAppendIndex=r.index:r.deferredAppendLength=r.sourceLength
                QaRollingSetPhase(r,"fragment")
                return
            end if
            r.nextAdmission=now+100
            return
        end if
        r.nextAdmission=0
        if r.workKind="append" then r.deferredAppendIndex=-1:r.deferredAppendLength=0#
        QaRollingSetPhase(r,"download")
    end if
    if r.phase="descriptor"
        r.descriptorSerial+=1
        url=r.url:path=QaRollingTemp(r)+"upstream-"+r.descriptorSerial.ToStr()+".m3u8":cap=1048576#
    else if r.phase="init"
        url=r.descriptor.init:path=QaRollingTemp(r)+"source-init.mp4":cap=1048576#
    else
        url=r.descriptor.fragments[QaRollingSourceIndex(r,r.workIndex)]:path=QaRollingTemp(r)+"source-"+QaRollingSourceIndex(r,r.workIndex).ToStr()+".m4s"
        cap=r.sourceLength
    end if
    if not QaRollingBegin(r,url,path,cap) then QaRollingFail(r)
end sub
sub QaRollingSetTargets(r as Object)
    if r.targets=invalid
        if r.stock<>invalid
            ' RFC 8216 4.3.3.1 permits EXTINF rounded to the nearest integer.
            ' Reserve its ceiling once, while keeping the original audio cap.
            r.targets={video:r.descriptor.targetDuration+1,audio:r.descriptor.targetDuration+1}
            return
        else
        maximum=0#
        for each seconds in r.descriptor.durations
            if seconds>maximum then maximum=seconds
        end for
        videoTarget=Int(maximum)
        if videoTarget<maximum then videoTarget+=1
        end if
        ' Fixed for this generation. Admit at most one second of derived-audio
        ' boundary padding beyond the descriptor's rounded video maximum.
        r.targets={video:videoTarget,audio:videoTarget+1}
    end if
end sub
function QaRollingVideoDurationAllowed(r as Object, sourceIndex as Integer) as Boolean
    if r.stock<>invalid
        ' Exact decimal microseconds avoid rounding 2.499999 to 2.5 on Roku.
        if r.descriptor.DoesExist("durationMicros")
            if r.descriptor.durationMicros[sourceIndex]>=r.descriptor.targetDuration*1000000+500000 then return false
        else
            if r.descriptor.durations[sourceIndex]>=r.descriptor.targetDuration+0.5# then return false
        end if
    end if
    return r.descriptor.durations[sourceIndex]<=r.targets.video
end function
function QaRollingPublish(r as Object) as Boolean
    QaRollingSetTargets(r)
    prefix=QaRollingPrefix(r):staging=QaRollingTemp(r)
    for i=r.first to r.entries.Count()-1
        e=r.entries[i]
        if e.videoDuration>r.targets.video or e.audioDuration>r.targets.audio then return false
    end for
    r.publication+=1
    lf=Chr(10):q=Chr(34):video="":audio=""
    for i=r.first to r.entries.Count()-1
        e=r.entries[i]
        sourceIndex=QaRollingSourceIndex(r,i)
        video+="#EXTINF:"+e.videoDuration.ToStr().Trim()+","+lf+"video-"+sourceIndex.ToStr()+".m4s"+lf
        audio+="#EXTINF:"+e.audioDuration.ToStr().Trim()+","+lf+"audio-"+sourceIndex.ToStr()+".m4s"+lf
    end for
    ' Explicit initial playback position; an open playlist otherwise starts at its live edge.
    header="#EXTM3U"+lf+"#EXT-X-VERSION:7"+lf+"#EXT-X-START:TIME-OFFSET=0,PRECISE=YES"+lf
    sequence="#EXT-X-MEDIA-SEQUENCE:"+QaRollingSourceIndex(r,r.first).ToStr()+lf
    video=header+"#EXT-X-TARGETDURATION:"+r.targets.video.ToStr()+lf+sequence+"#EXT-X-MAP:URI="+q+"init.mp4"+q+lf+video
    audio=header+"#EXT-X-TARGETDURATION:"+r.targets.audio.ToStr()+lf+sequence+"#EXT-X-MAP:URI="+q+"audio-init.mp4"+q+lf+audio
    if QaRollingEnded(r) and QaRollingSourceIndex(r,r.index)=r.descriptor.fragments.Count()
        video+="#EXT-X-ENDLIST"+lf:audio+="#EXT-X-ENDLIST"+lf
    end if
    track=QaAudioTrack(r.init)
    master="#EXTM3U"+lf+"#EXT-X-VERSION:7"+lf+"#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="+q+"qa_audio"+q+",NAME="+q+"qa_audio"+q+",DEFAULT=YES,AUTOSELECT=YES,URI="+q+"audio.m3u8"+q+lf+"#EXT-X-STREAM-INF:BANDWIDTH=12000000,CODECS="+q+"hvc1.2.4.L150.90,"+track.codec+q+",AUDIO="+q+"qa_audio"+q+",VIDEO-RANGE=PQ"+lf+"video.m3u8"+lf
    ' Each response retains its selected immutable path, even across publication.
    for each name in ["master","video","audio"]
        path=staging+name+"-"+r.publication.ToStr()+".m3u8"
        text=master
        if name="video" then text=video
        if name="audio" then text=audio
        r.owned[path]=true
        if not WriteAsciiFile(path,text) then return false
        r.liveBytes += Len(text)
    end for
    for i=r.first to r.entries.Count()-1
        e=r.entries[i]
        sourceIndex=QaRollingSourceIndex(r,i)
        videoKey=prefix+"video-"+sourceIndex.ToStr()+".m4s"
        audioKey=prefix+"audio-"+sourceIndex.ToStr()+".m4s"
        if not m.routes.DoesExist(videoKey)
        m.routes[videoKey]={id:100+sourceIndex,path:e.video,mime:"video/mp4",entry:i,sourceIndex:sourceIndex,owner:r,pins:0}
        m.routes[audioKey]={id:200+sourceIndex,path:e.audio,mime:"audio/mp4",pins:0,entry:i,sourceIndex:sourceIndex,owner:r}
        end if
    end for
    members=[]
    for i=r.first to r.entries.Count()-1
        sourceIndex=QaRollingSourceIndex(r,i)
        members.Push(m.routes[prefix+"video-"+sourceIndex.ToStr()+".m4s"])
        members.Push(m.routes[prefix+"audio-"+sourceIndex.ToStr()+".m4s"])
    end for
    for each name in ["master","video","audio"]
        old=m.routes.Lookup(prefix+name+".m3u8")
        if old<>invalid then r.snapshots.Push(old)
        m.routes[prefix+name+".m3u8"]={pins:0,id:1,path:staging+name+"-"+r.publication.ToStr()+".m3u8",mime:"application/vnd.apple.mpegurl",owner:r}
        if name<>"master" then m.routes[prefix+name+".m3u8"].members=members
    end for
    if not m.routes.DoesExist(prefix+"init.mp4")
        m.routes[prefix+"init.mp4"]={id:4,path:r.initPath,mime:"video/mp4",pins:0,owner:r}
        m.routes[prefix+"audio-init.mp4"]={id:6,path:staging+"audio-init.mp4",mime:"audio/mp4",pins:0,owner:r}
    end if
    return true
end function

sub QaRollingDelete(r as Object, path as String)
    if not r.owned.DoesExist(path) then return
    size=QaRemoteSize(path)
    if m.fs.Delete(path)
        r.owned.Delete(path)
        r.liveBytes-=size
    else
        QaRollingFail(r)
    end if
end sub
sub QaRollingRetire(r as Object)
    ' Position is an explicit native timeline input, never inferred from HTTP.
    first=r.first
    while r.first<r.entries.Count()-1
        if r.entries[r.first].endSeconds>=r.position-12 then exit while
        if r.targets<>invalid
            videoLeft=0#:audioLeft=0#
            for i=r.first+1 to r.entries.Count()-1
                videoLeft+=r.entries[i].videoDuration
                audioLeft+=r.entries[i].audioDuration
            end for
            ' Both live renditions retain three times the larger fixed target.
            minimum=3*r.targets.audio
            if videoLeft<minimum or audioLeft<minimum then exit while
        end if
        r.first+=1
    end while
    if r.first<>first
        if not QaRollingPublish(r)
            QaRollingFail(r)
            return
        end if
    end if
    if r.eviction<r.first
        i=r.eviction
        e=r.entries[i]
        if e.evicted
            ' Pressure admission may already have removed this pair.
            r.eviction+=1
        else if e.endSeconds<r.position-30
            sourceIndex=QaRollingSourceIndex(r,i)
            v=m.routes.Lookup(QaRollingPrefix(r)+"video-"+sourceIndex.ToStr()+".m4s")
            a=m.routes.Lookup(QaRollingPrefix(r)+"audio-"+sourceIndex.ToStr()+".m4s")
            if v<>invalid and a<>invalid
                if v.pins=0 and a.pins=0
                    QaRollingDelete(r,e.video)
                    if r.failed then return
                    QaRollingDelete(r,e.audio)
                    if r.failed then return
                    e.evicted=true:e.resident=false
                    r.eviction+=1
                end if
            end if
        end if
    end if
    keep=[]
    for each snapshot in r.snapshots
        if snapshot.pins=0
            QaRollingDelete(r,snapshot.path)
            if r.failed then return
        else
            keep.Push(snapshot)
        end if
    end for
    r.snapshots=keep
end sub

' Generic owned fixtures are finite; stock completion is explicit upstream policy.
function QaRollingEnded(r as Object) as Boolean
    if r.stock=invalid then return true
    return r.descriptor.ended
end function

sub QaRollingClearContext(r as Object)
    if r.stock<>invalid
        if Type(r.stock)="roAssociativeArray" then r.stock.token=""
    end if
    m.top.stockContext=invalid
end sub

sub QaRollingSetReady(r as Object)
    enough=r.index>=r.lead
    if r.stock<>invalid
        if r.descriptor.ended and r.index>0 and QaRollingSourceIndex(r,r.index)=r.descriptor.fragments.Count() then enough=true
    end if
    if enough and not r.failed
        r.ready=true
        if r.lifecycle="active" then m.top.ready=true
    end if
end sub

' Physical cache membership is independent of immutable logical route membership.
' At most 8192 source entries are admitted by StockDescriptor.
function QaRollingReserve(r as Object, sourceSize as Double) as Boolean
    ' 4MiB selected payload + 2MiB generated headers/init/descriptor snapshots
    ' + 6MiB observed-write headroom. Native async overshoot is still not a hard cap.
    r.admissionSharedBlocked=false
    r.admissionDeferred=false:r.admissionProtected=0:r.admissionVictimFirst=-1:r.admissionVictimLast=-1
    reserve=sourceSize+12582912#
    cap=QaRollingDiskCap(r)
    if sourceSize<1 or sourceSize>67108864# or reserve>cap then return false
    if QaRollingLiveBytes(r)+reserve<=cap
        if r.telemetry<>invalid then QaRollingTelemetryAdmission(r,0,0)
        return true
    end if
    ' Preserve the recovery working set only when forward production can wait.
    ' Published lead, rather than HTTP demand, prevents a frontier deadlock:
    ' unpublished routes cannot yet generate demand. Refills always make progress.
    minimumLead=12#
    if r.targets<>invalid
        if 3*r.targets.audio>minimumLead then minimumLead=3*r.targets.audio
    end if
    protect=r.workKind="append" and r.ready and r.endSeconds-r.position>=minimumLead
    visits=0:evictions=0:protected=0
    ' Prefer other spent slices over a refill still near the playhead. The
    ' second pass keeps pressure admission live when that set cannot fit.
    for pass=0 to 1
      for i=0 to r.entries.Count()-1
        visits+=1
        e=r.entries[i]
        resident=not e.evicted
        if e.DoesExist("resident") then resident=e.resident
        if resident and protect
            if e.endSeconds>=r.position-24
                if pass=0 then protected+=1
                resident=false
            end if
        end if
        if resident and pass=0 and e.DoesExist("endSeconds")
            if e.endSeconds>=r.position then resident=false
            if e.DoesExist("refilled")
                if e.refilled and e.endSeconds>=r.position-24 then resident=false
            end if
        end if
        if resident
            sourceIndex=QaRollingSourceIndex(r,i)
            v=m.routes.Lookup(QaRollingPrefix(r)+"video-"+sourceIndex.ToStr()+".m4s")
            a=m.routes.Lookup(QaRollingPrefix(r)+"audio-"+sourceIndex.ToStr()+".m4s")
            if v<>invalid and a<>invalid
                if v.pins=0 and a.pins=0
                    QaRollingDelete(r,e.video)
                    if r.failed then return false
                    QaRollingDelete(r,e.audio)
                    if r.failed then return false
                    e.resident=false:e.evicted=true
                    evictions+=1
                    if r.admissionVictimFirst<0 then r.admissionVictimFirst=QaRollingSourceIndex(r,i)
                    r.admissionVictimLast=QaRollingSourceIndex(r,i)
                    if QaRollingLiveBytes(r)+reserve<=cap
                        r.admissionProtected=protected
                        if r.telemetry<>invalid then QaRollingTelemetryAdmission(r,visits,evictions)
                        return true
                    end if
                end if
            end if
        end if
      end for
    end for
    r.admissionProtected=protected
    r.admissionDeferred=protected>0
    ' A replacement with no safe local victims can request explicit native
    ' retirement. This reports pressure only; it never releases another owner.
    if r.lifecycle="preparing" and QaRollingLiveBytes(r)>r.liveBytes
        if r.liveBytes+reserve<=cap then r.admissionSharedBlocked=true
    end if
    if r.telemetry<>invalid then QaRollingTelemetryAdmission(r,visits,evictions)
    return false
end function

function QaRollingProbeLength(event as Object, bytes as Double) as Double
    if bytes<>1 then return -1
    headers=event.GetResponseHeaders()
    if headers=invalid then return -1
    value=invalid
    for each key in headers
        if LCase(key)="content-range" then value=headers[key]
    end for
    if Type(value)<>"roString" and Type(value)<>"String" then return -1
    prefix="bytes 0-0/"
    if Left(value,Len(prefix))<>prefix then return -1
    digits=Mid(value,Len(prefix)+1)
    if Len(digits)<1 or Len(digits)>8 then return -1
    size=0#
    for i=1 to Len(digits)
        ch=Mid(digits,i,1)
        if ch<"0" or ch>"9" then return -1
        size=size*10#+Asc(ch)-48
    end for
    if size<1 or size>67108864# then return -1
    return size
end function

function QaRollingDigest() as Dynamic
    return CreateObject("roEVPDigest")
end function
function QaRollingHashStart(path as String, size as Double) as Object
    d=QaRollingDigest()
    j={path:path,size:size,at:0,done:false,ok:false,value:"",digest:d,io:QaFileAudioIO()}
    if d=invalid
        j.done=true
    else if d.Setup("sha256")<>0
        j.done=true
    end if
    return j
end function
sub QaRollingHashStep(j as Object)
    if j.done then return
    for chunk=1 to 4
        amount=j.size-j.at
        if amount>65536 then amount=65536
        if amount<1
            j.value=j.digest.Final()
            j.ok=Len(j.value)=64
            j.digest=invalid:j.done=true
            return
        end if
        data=j.io.read(j.path,j.at,QaByteInteger(amount))
        if data=invalid
            j.done=true:j.digest=invalid
            return
        end if
        if data.Count()<>amount
            j.done=true:j.digest=invalid
            return
        end if
        j.digest.Update(data)
        ' Integer cursor never passes through single-precision Int(Float).
        j.at+=QaByteInteger(amount)
        if j.at>=j.size then return
    end for
end sub
function QaRollingPlanIdentity(plan as Object) as String
    ' Digest checks exact bytes; this bounded plan summary also guards timeline policy.
    return plan.timescale.ToStr()+":"+plan.trackid.ToStr()+":"+plan.samples.Count().ToStr()+":"+plan.samples[0].pts.ToStr()+":"+plan.bytes.ToStr()
end function
sub QaRollingFinishPair(r as Object)
    j=r.completedJob:size=QaRemoteSize(j.target)
    identity=QaRollingPlanIdentity(j.plan)
    if r.workKind="refill"
        e=r.entries[r.workIndex]
        if r.audioDigest<>e.audioDigest or size<>e.audioSize or r.sourceSize<>e.sourceSize or identity<>e.planIdentity or r.completedDuration<>e.audioDuration
            QaRollingFail(r)
            return
        end if
        e.resident=true:e.evicted=false:e.fetching=false:e.refilled=true
        ' A late refill becomes eligible for ordinary age retirement again.
        if r.workIndex<r.eviction then r.eviction=r.workIndex
    else
        ' Reject new timing before mutating lifetime counters or immutable history.
        QaRollingSetTargets(r)
        sourceIndex=QaRollingSourceIndex(r,r.index)
        if not QaRollingVideoDurationAllowed(r,sourceIndex) or r.completedDuration>r.targets.audio
            QaRollingFail(r)
            return
        end if
        r.endSeconds+=r.descriptor.durations[sourceIndex]
        r.entries.Push({video:r.source,audio:j.target,sourceIndex:sourceIndex,videoDuration:r.descriptor.durations[sourceIndex],audioDuration:r.completedDuration,endSeconds:r.endSeconds,evicted:false,resident:true,fetching:false,sourceSize:r.sourceSize,audioSize:size,sourceDigest:r.sourceDigest,audioDigest:r.audioDigest,planIdentity:identity})
        r.sourceBytes+=r.sourceSize
        r.window=r.nextWindow:r.index+=1
        if not QaRollingPublish(r)
            QaRollingFail(r)
            return
        end if
        QaRollingSetReady(r)
    end if
    if r.telemetry<>invalid
        if r.workKind="refill" then QaRollingTelemetryDemandDone(r,r.workIndex,1)
        QaRollingTelemetryWork(r,1,r.sourceSize,size)
    end if
    r.completedJob=invalid:QaRollingSetPhase(r,"fragment"):r.workKind="append"
end sub

' Four admitted sockets bound both pending demand and the coalesced queue.
function QaRollingDemand(r as Object, index as Integer) as Boolean
    if r.failed then return false
    e=r.entries[index]
    if e.resident then return true
    if e.fetching then return true
    if r.demand.Count()>=4 then return false
    e.fetching=true:r.demand.Push(index)
    if r.telemetry<>invalid then QaRollingTelemetryDemandQueued(r,index)
    return true
end function

' Cancellation has no guaranteed completion event. Keep unsettled transfer
' identity and owned paths; only settled generations can enter delete census.
function QaRollingCleanupOwners() as Object
    owners=[]:hasActive=false
    if m.rollingSession<>invalid
        for each generation in m.rollingSession.generations
            owners.Push(generation)
            if m.rolling<>invalid
                if generation.generation=m.rolling.generation then hasActive=true
            end if
        end for
    end if
    ' Pressure retirement retains only a detached source control record. It
    ' still participates in terminal token cleanup and the drained census.
    if m.rolling<>invalid and not hasActive then owners.Push(m.rolling)
    return owners
end function
sub QaRollingCleanupSession()
    for each generation in QaRollingCleanupOwners()
        QaRollingCleanup(generation)
    end for
end sub
sub QaRollingCleanup(r as Object)
    if not r.failed and r.telemetry<>invalid then QaRollingTelemetryCancel(r)
    if r.transfer<>invalid then QaRollingCancelWriter(r)
    if r.job<>invalid
        QaFileAudioCancel(r.job)
        r.job=invalid
    end if
    if r.cancelledIdentity<>invalid
        if not QaRollingWriterCensus(r)
            r.pendingCleanup=true
            if r.lifecycle="active" or m.stopLocal then m.top.failed=true
            print "qa_cleanup clean=0 pending_writer=true"
            return
        end if
    end if
    if r.hashJob<>invalid
        r.hashJob.digest=invalid:r.hashJob=invalid
    end if
    stable=0:clean=false
    for pass=0 to 24
        remaining=0
        for each path in r.owned
            stat=m.fs.Stat(path)
            if stat<>invalid
                if stat.DoesExist("size")
                    if not m.fs.Delete(path) then remaining+=1
                end if
            end if
        end for
        ' A separate census catches a failed delete and late writer recreation.
        for each path in r.owned
            stat=m.fs.Stat(path)
            if stat<>invalid
                if stat.DoesExist("size") then remaining+=1
            end if
        end for
        if remaining=0
            stable+=1
        else
            stable=0
        end if
        if pass=24 then clean=stable>=3
        if pass<24 then QaRollingCleanupYield()
    end for
    r.pendingCleanup=not clean
    if not clean
        r.failed=true
        if r.lifecycle="active" or m.stopLocal then m.top.failed=true
    end if
    cleanValue=0
    if clean then cleanValue=1
    print "qa_cleanup clean="; cleanValue; " pending_writer="; r.pendingCleanup
end sub
sub QaRollingCleanupYield()
    ' Dedicated bounded cleanup pause after sockets close, not the serving loop.
    port=CreateObject("roMessagePort")
    ignored=Wait(10,port)
end sub
