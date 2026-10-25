' Owned stock-generation handoff shared by the app and host runtime tests.
' All offers are detached, sanitized values; only Task state owns source URLs.
sub QaSeekInit()
    if m.seek<>invalid then return
    m.seek={index:invalid,revision:0,request:invalid,latest:0,lastTarget:invalid,intent:false,abort:false,deadline:0#,indexTimeoutMs:30000,offerTimeoutMs:10000,previous:invalid,release:false,committed:invalid,clock:invalid,replaced:false,refresh:invalid}
end sub
' Numeric-only diagnostics share one bounded budget for this engine lifetime.
sub QaSeekDiagnostic(label as String, values as String)
    if m.rollingTelemetryEnabled<>true then return
    if m.seek.diagnosticCount=invalid then m.seek.diagnosticCount=0
    if m.seek.diagnosticCount>=64 then return
    m.seek.diagnosticCount+=1
    print label;" ";values
end sub
function QaSeekDiagnosticFlag(value as Boolean) as String
    if value then return "1"
    return "0"
end function
sub QaSeekRequestDiagnostic(data as Dynamic)
    if m.rollingTelemetryEnabled<>true then return
    aa=Type(data)="roAssociativeArray":idValid=false:targetValid=false:newer=false
    if aa
        idValid=QaSeekId(data.requestId):targetValid=QaSeekWhole(data.targetTitleUs)
        if idValid then newer=data.requestId>m.seek.latest
    end if
    QaSeekDiagnostic("qa_seek_request","aa="+QaSeekDiagnosticFlag(aa)+" id="+QaSeekDiagnosticFlag(idValid)+" target="+QaSeekDiagnosticFlag(targetValid)+" newer="+QaSeekDiagnosticFlag(newer)+" rolling="+QaSeekDiagnosticFlag(m.rolling<>invalid))
end sub
' Numeric kind codes: 0 other, 1 integer, 2 long, 3 float, 4 double.
function QaSeekDiagnosticNumberKind(value as Dynamic) as Integer
    kind=Type(value)
    if kind="Integer" or kind="roInt" or kind="roInteger" then return 1
    if kind="LongInteger" or kind="roLongInteger" then return 2
    if kind="Float" or kind="roFloat" then return 3
    if kind="Double" or kind="roDouble" then return 4
    return 0
end function
' Rejected lookup status: 0 invalid, 1 exact completed-title edge.
sub QaSeekLookupRejectedDiagnostic(found as Object, titleUs as Dynamic, index as Object)
    if m.rollingTelemetryEnabled<>true then return
    status=0
    if found.status="end" then status=1
    targetKind=QaSeekDiagnosticNumberKind(titleUs):endKind=QaSeekDiagnosticNumberKind(index.indexedEndUs)
    QaSeekDiagnostic("qa_seek_lookup","status="+status.ToStr()+" target_valid="+QaSeekDiagnosticFlag(QaSeekWhole(titleUs))+" target_kind="+targetKind.ToStr()+" end_kind="+endKind.ToStr())
end sub
sub QaSeekStateDiagnostic()
    if m.rollingTelemetryEnabled<>true then return
    s=m.seek:status=0
    if s.diagnosticCount<>invalid then if s.diagnosticCount>=64 then return
    busy=false
    if m.rollingSession<>invalid then busy=QaSeekBusy()
    if s.request<>invalid
        if s.request.status="waiting_index" then status=1
        if s.request.status="preparing" then status=2
        if s.request.status="offered" then status=3
        if s.request.status="active" then status=4
        if s.request.status="failed" then status=5
        if s.request.status="cancelled" then status=6
    end if
    snapshot="status="+status.ToStr()+" index="+QaSeekDiagnosticFlag(s.index<>invalid)+" previous="+QaSeekDiagnosticFlag(s.previous<>invalid)+" busy="+QaSeekDiagnosticFlag(busy)+" preparing="+QaSeekDiagnosticFlag(m.preparing<>invalid)
    if s.diagnosticSnapshot=snapshot then return
    s.diagnosticSnapshot=snapshot
    QaSeekDiagnostic("qa_seek_state",snapshot)
end sub
function QaSeekId(value as Dynamic) as Boolean
    return QaSeekWhole(value) and value>0 and value<=2147483647#
end function
sub QaSeekPublish(status as String)
    s=m.seek:r=s.request
    if r=invalid then return
    r.status=status
    offer={status:status,requestId:r.requestId,generationId:r.generationId,deadlineMs:s.deadline,plan:QaSeekCopyPlan(r.plan)}
    offer.previousRetired=r.previousRetired=true
    if status="quiesce" or status="offered" or status="active"
        offer.previousGenerationId=s.previous
        if status="offered" or status="quiesce" then offer.previousGenerationId=m.rolling.generation
        if r.previousRetired=true then offer.previousGenerationId=r.previousGenerationId
        offer.localMasterUrl="http://127.0.0.1:34831/g"+r.generationId.ToStr()+"/master.m3u8"
    end if
    m.top.seekOffer=offer
end sub
' Called only at the validated descriptor acceptance boundary.
sub QaSeekDescriptorAccepted(owner as Object, descriptor as Object)
    QaSeekInit()
    s=m.seek
    if owner.lifecycle<>"active" and not owner.DoesExist("seekRefresh")
        QaSeekDiagnostic("qa_seek_index","valid=0 reason=1")
        return
    end if
    diagnostic=invalid
    if m.rollingTelemetryEnabled=true then diagnostic={}
    nextIndex=QaSeekIndex(s.index,descriptor,s.revision+1,diagnostic)
    if nextIndex=invalid
        if diagnostic<>invalid
            detail="valid=0 reason=2 gate="+diagnostic.gate.ToStr()
            if diagnostic.gate=11 then detail+=" duration_index="+diagnostic.durationIndex.ToStr()+" duration_kind="+diagnostic.durationKind.ToStr()+" duration_us="+diagnostic.durationValue.ToStr()+" duration_type="+diagnostic.durationType
            QaSeekDiagnostic("qa_seek_index",detail)
        end if
        if owner.DoesExist("seekRefresh") then owner.failed=true
        return
    end if
    QaSeekDiagnostic("qa_seek_index","valid=1 reason=0")
    s.index=nextIndex:s.revision+=1
    if s.request<>invalid
        if s.request.status="waiting_index" and s.request.binding=invalid
            s.request.binding=nextIndex.binding:s.request.revision=nextIndex.revision
        end if
    end if
    if owner.DoesExist("seekRefresh")
        m.rolling.descriptor=descriptor
        m.rolling.nextPoll=owner.nextPoll
        owner.phase="seek-wait":s.refresh=invalid
        s.abort=true
    end if
end sub
' Single reached dispatch for atomic Scene fields, including the legacy sample.
sub QaSeekHandleField(name as String, data as Dynamic)
    name=LCase(name)
    QaSeekInit():s=m.seek
    if name="stoprequested"
        if data=true
            m.stopLocal=true:s.intent=false:s.abort=true
            if s.request<>invalid then QaSeekPublish("cancelled")
        end if
        return
    end if
    if name="seekrequest" then QaSeekRequestDiagnostic(data)
    if m.stopLocal then return
    if name="playbackposition"
        if m.rolling=invalid or s.replaced then return
        if m.rolling.generation<>1 then return
        if Type(data)="Float" or Type(data)="roFloat" or Type(data)="Double" or Type(data)="roDouble" or Type(data)="Integer" or Type(data)="roInt" or Type(data)="roInteger"
            if data>=m.rolling.position and data<=m.rolling.endSeconds then m.rolling.position=data
        end if
        return
    end if
    if Type(data)<>"roAssociativeArray" then return
    if name="seekrequest"
        if not QaSeekId(data.requestId) or not QaSeekWhole(data.targetTitleUs) then return
        if data.requestId<=s.latest then return
        if m.rolling=invalid then return
        s.latest=data.requestId:s.lastTarget=data.targetTitleUs
        s.intent=false
        if s.request<>invalid
            if s.request.status<>"active" then QaSeekPublish("cancelled")
        end if
        if m.preparing<>invalid then s.abort=true
        ' Generation is allocated only when preparation actually begins.
        binding=invalid:revision=0#
        if s.index<>invalid then binding=s.index.binding:revision=s.index.revision
        s.request={requestId:data.requestId,generationId:0#,requestedTitleUs:QaSeekExactInteger(data.targetTitleUs),plan:invalid,activePlan:invalid,status:"waiting_index",binding:binding,revision:revision}
        s.deadline=m.clock.TotalMilliseconds()+s.indexTimeoutMs
        QaSeekPublish("waiting_index")
    else if name="seekack"
        if not QaSeekId(data.requestId) or not QaSeekId(data.generationId) then return
        if data.action="release_previous"
            c=s.committed
            if c=invalid or s.previous=invalid then return
            if c.requestId=data.requestId and c.generationId=data.generationId and data.previousGenerationId=s.previous then s.release=true
            return
        end if
        if data.action="bind_clock"
            c=s.committed
            if c=invalid then return
            if c.requestId<>data.requestId or c.generationId<>data.generationId then return
            if not QaSeekId(data.epoch) or not QaSeekWhole(data.nativeOriginUs) then return
            if s.clock=invalid then s.clock={epoch:data.epoch,origin:QaSeekExactInteger(data.nativeOriginUs),sequence:-1#}
            return
        end if
        r=s.request
        if r=invalid then return
        if r.requestId<>data.requestId or r.generationId<>data.generationId then return
        if data.action="quiesced" and r.status="quiesce"
            if data.previousGenerationId=r.previousGenerationId then r.quiesced=true
        end if
        if data.action="accept" and r.status="offered" then s.intent=true
        if data.action="cancel" and r.status<>"active"
            s.intent=false:s.abort=true:QaSeekPublish("cancelled")
        end if
    else if name="playbackupdate"
        c=s.committed:k=s.clock
        if c=invalid or k=invalid then return
        if data.requestId<>c.requestId or data.generationId<>c.generationId or data.epoch<>k.epoch then return
        if not QaSeekWhole(data.sequence) then return
        if data.sequence<=k.sequence then return
        title=QaSeekPosition(c,data.requestId,data.generationId,data.nativeUs,k.origin)
        if title=invalid then return
        seconds=title/1000000#
        if seconds<m.rolling.position or seconds>m.rolling.endSeconds then return
        m.rolling.position=seconds:k.sequence=data.sequence
    end if
end sub
function QaSeekBusy() as Boolean
    for each owner in m.rollingSession.generations
        if owner.transfer<>invalid or owner.cancelledIdentity<>invalid or owner.job<>invalid or owner.hashJob<>invalid then return true
    end for
    return false
end function
' Before scheduler work: retire only on the explicit exact release assertion;
' settle cancelled writers before honoring the latest pending intent.
sub QaSeekTick()
    QaSeekInit():s=m.seek
    QaSeekStateDiagnostic()
    if m.stopLocal then return
    if s.release and s.previous<>invalid
        if QaRollingRetireGeneration(s.previous) then s.previous=invalid:s.release=false
    end if
    r=s.request
    if r=invalid then return
    if r.status="waiting_index" or r.status="preparing" or r.status="quiesce" or r.status="offered"
        if m.clock.TotalMilliseconds()>=s.deadline
            s.intent=false:s.abort=true:QaSeekPublish("failed")
        end if
    end if
    if s.abort
        if m.preparing<>invalid
            if not QaRollingAbortPreparation() then return
        end if
        s.abort=false:s.refresh=invalid
    end if
    if r.status="failed" or r.status="cancelled" or r.status="active" then return
    ' Failure gates: 1 active failure, 2 generation allocation, 3 preparation.
    if m.rolling.failed then QaSeekDiagnostic("qa_seek_failure","gate=1"):s.intent=false:s.abort=true:QaSeekPublish("failed"):return
    if r.status="waiting_index"
        if s.index=invalid then return
        if s.previous<>invalid then return
        found=QaSeekLookup(s.index,r.requestedTitleUs)
        if found.status="invalid" or found.status="end"
            QaSeekLookupRejectedDiagnostic(found,r.requestedTitleUs,s.index)
            QaSeekPublish("failed"):return
        end if
        if found.status="waiting_index"
            if m.preparing<>invalid
                if m.preparing.failed then s.abort=true:QaSeekPublish("failed")
                return
            end if
            if QaSeekBusy() or m.clock.TotalMilliseconds()<m.rolling.nextPoll then return
            generation=m.rollingSession.maxGeneration+1
            if not QaSeekId(generation) then QaSeekDiagnostic("qa_seek_failure","gate=2"):QaSeekPublish("failed"):return
            refresh=QaRollingState(m.rolling.url)
            refresh.generation=generation:refresh.lifecycle="preparing":refresh.seekRefresh=true
            refresh.stock=m.rolling.stock:refresh.descriptor=m.rolling.descriptor
            m.rollingSession.maxGeneration=generation:m.rollingSession.generations.Push(refresh)
            m.preparing=refresh:s.refresh=refresh
            return
        end if
        if m.preparing<>invalid or QaSeekBusy() then return
        generation=m.rollingSession.maxGeneration+1
        if not QaSeekId(generation) then QaSeekDiagnostic("qa_seek_failure","gate=2"):QaSeekPublish("failed"):return
        plan=QaSeekPlan(s.index,r.requestedTitleUs,generation,r.requestId)
        prepared=QaRollingPrepare(plan)
        if prepared=invalid then QaSeekDiagnostic("qa_seek_failure","gate=3"):QaSeekPublish("failed"):return
        r.plan=plan:r.generationId=generation:r.previousGenerationId=m.rolling.generation:r.previousRetired=m.rolling.lifecycle="retired"
        QaSeekPublish("preparing")
    else if r.status="preparing"
        if m.preparing=invalid then QaSeekPublish("failed"):return
        if m.preparing.failed
            s.abort=true:QaSeekPublish("failed"):return
        end if
        if m.preparing.admissionSharedBlocked=true
            QaSeekPublish("quiesce"):return
        end if
        if m.preparing.ready
            s.deadline=m.clock.TotalMilliseconds()+s.offerTimeoutMs
            QaSeekPublish("offered")
        end if
    else if r.status="quiesce"
        if r.quiesced<>true then return
        ' The Scene has observed native stop. Pins and writers still own bytes
        ' until the existing guarded retirement actually completes.
        old=m.rolling
        old.lifecycle="draining"
        if not QaRollingRetireGeneration(old.generation,true) then return
        r.previousRetired=true:s.replaced=true
        m.preparing.admissionSharedBlocked=false
        m.preparing.admissionAt=m.clock.TotalMilliseconds()
        m.preparing.nextAdmission=0
        QaSeekPublish("preparing")
    else if r.status="offered" and s.intent
        if QaSeekBusy() then return
        previous=m.rolling.generation
        if QaRollingActivate(r.generationId)
            s.previous=previous
            if r.previousRetired=true then s.previous=invalid
            s.request=QaSeekAcknowledge(r,r.requestId,r.generationId)
            s.request.previousRetired=r.previousRetired=true
            s.request.previousGenerationId=r.previousGenerationId
            s.committed=QaSeekCopyPlan(r.plan):s.clock=invalid:s.replaced=true:s.intent=false
            QaSeekPublish("active")
        end if
    end if
end sub
