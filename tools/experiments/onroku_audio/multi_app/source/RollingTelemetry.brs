' Optional numeric-only experiment packet. Phase codes: 1 descriptor, 2 init,
' 3 fragment/idle, 4 probe, 5 admit, 6 download, 7 source hash,
' 8 extract, 9 audio hash. Kind: 1 append, 2 refill. Outcome: 1 done,
' 2 failed, 3 cancelled. Phase elapsed includes waiting; tick samples are
' callback wall time, not CPU time. No arbitrary strings or media identity print.
function QaRollingPhaseCode(phase as String) as Integer
    if phase="descriptor" then return 1
    if phase="init" then return 2
    if phase="fragment" then return 3
    if phase="probe" then return 4
    if phase="admit" then return 5
    if phase="download" then return 6
    if phase="hash-source" then return 7
    if phase="extract" then return 8
    if phase="hash-audio" then return 9
    return 0
end function
function QaRollingKindCode(r as Object) as Integer
    if r.workKind="refill" then return 2
    return 1
end function
sub QaRollingTelemetryInit(r as Object, enabled as Boolean)
    if not enabled then return
    now=m.clock.TotalMilliseconds()
    r.telemetry={phaseAt:now,queued:{},tickCount:0,tickTotal:0,tickMax:0,hashSource:0#,hashAudio:0#,cancelReported:false,cancelledWriter:false,terminalReported:false,inTick:false,pending:invalid}
end sub
sub QaRollingPhase(r as Object, nextPhase as String)
    if r.phase=nextPhase then return
    t=r.telemetry
    if t<>invalid
        now=m.clock.TotalMilliseconds()
        if r.phase<>"fragment" then QaRollingTelemetryEmitPhase(r,now)
        t.phaseAt=now
        if r.phase="fragment"
            t.tickCount=0:t.tickTotal=0:t.tickMax=0
        end if
    end if
    r.phase=nextPhase
end sub
sub QaRollingTelemetryEmitPhase(r as Object, now as Integer)
    t=r.telemetry
    elapsed=now-t.phaseAt
    if elapsed<0 then elapsed=0
    print "qa_roll_phase g=";r.generation;" src=";QaRollingSourceIndex(r,r.workIndex);" local=";r.workIndex;" kind=";QaRollingKindCode(r);" phase=";QaRollingPhaseCode(r.phase);" start=";t.phaseAt;" end=";now;" ms=";elapsed
end sub
sub QaRollingTelemetryEndPhase(r as Object)
    if r.telemetry=invalid or r.phase="fragment" then return
    QaRollingTelemetryEmitPhase(r,m.clock.TotalMilliseconds())
end sub
sub QaRollingTelemetryTick(r as Object, started as Integer)
    t=r.telemetry
    if t=invalid then return
    elapsed=m.clock.TotalMilliseconds()-started
    if elapsed<0 then elapsed=0
    t.tickCount+=1:t.tickTotal+=elapsed
    if elapsed>t.tickMax then t.tickMax=elapsed
end sub
function QaRollingTelemetryBeginTick(r as Object) as Integer
    r.telemetry.inTick=true
    return m.clock.TotalMilliseconds()
end function
sub QaRollingTelemetryEndTick(r as Object, started as Integer)
    QaRollingTelemetryTick(r,started)
    r.telemetry.inTick=false
    QaRollingTelemetryFlushWork(r)
end sub
sub QaRollingTelemetryWork(r as Object, outcome as Integer, sourceBytes as Double, audioBytes as Double)
    t=r.telemetry
    if t=invalid then return
    if t.terminalReported then return
    if outcome=2 or outcome=3 then t.terminalReported=true
    t.pending={generation:r.generation,sourceIndex:QaRollingSourceIndex(r,r.workIndex),localIndex:r.workIndex,kind:QaRollingKindCode(r),outcome:outcome,at:m.clock.TotalMilliseconds(),sourceBytes:sourceBytes,audioBytes:audioBytes,hashSource:t.hashSource,hashAudio:t.hashAudio}
    if not t.inTick then QaRollingTelemetryFlushWork(r)
end sub
sub QaRollingTelemetryFlushWork(r as Object)
    t=r.telemetry
    if t=invalid or t.pending=invalid then return
    p=t.pending
    print "qa_roll_work g=";p.generation;" src=";p.sourceIndex;" local=";p.localIndex;" kind=";p.kind;" outcome=";p.outcome;" at=";p.at
    print "qa_roll_bytes source=";p.sourceBytes;" audio=";p.audioBytes;" hash_source=";p.hashSource;" hash_audio=";p.hashAudio
    print "qa_roll_ticks count=";t.tickCount;" total_ms=";t.tickTotal;" max_ms=";t.tickMax
    t.pending=invalid
    t.tickCount=0:t.tickTotal=0:t.tickMax=0:t.hashSource=0#:t.hashAudio=0#
end sub
sub QaRollingTelemetryDemandQueued(r as Object, index as Integer)
    if r.telemetry=invalid then return
    r.telemetry.queued[index.ToStr()]={queued:m.clock.TotalMilliseconds(),started:-1}
end sub
sub QaRollingTelemetryDemandStarted(r as Object, index as Integer)
    if r.telemetry=invalid then return
    item=r.telemetry.queued.Lookup(index.ToStr())
    if item<>invalid then item.started=m.clock.TotalMilliseconds()
end sub
sub QaRollingTelemetryDemandDone(r as Object, index as Integer, outcome as Integer)
    if r.telemetry=invalid then return
    key=index.ToStr():item=r.telemetry.queued.Lookup(key)
    if item=invalid then return
    now=m.clock.TotalMilliseconds()
    queueMs=-1:workMs=-1
    if item.started>=0
        queueMs=item.started-item.queued
        workMs=now-item.started
    end if
    print "qa_roll_demand g=";r.generation;" src=";QaRollingSourceIndex(r,index);" local=";index;" outcome=";outcome;" queued_ms=";queueMs;" work_ms=";workMs
    r.telemetry.queued.Delete(key)
end sub
sub QaRollingTelemetryAdmission(r as Object, visits as Integer, evicted as Integer)
    ' Gate: 1 enabled, 2 refill, 3 not ready, 4 insufficient published lead.
    ' Signed millisecond offsets are relative to this admission's native position.
    ' Request end is known only for a refill of an existing parsed entry.
    ' Protected candidate count is the existing protected field.
    ' Missing request/victim timing stays absent, never a fabricated zero.
    if r.telemetry=invalid then return
    deferred=0
    if r.admissionDeferred then deferred=1
    minimumLead=12#
    if r.targets<>invalid
        if 3*r.targets.audio>minimumLead then minimumLead=3*r.targets.audio
    end if
    gate=1
    if r.workKind<>"append"
        gate=2
    else if not r.ready
        gate=3
    else if r.endSeconds-r.position<minimumLead
        gate=4
    end if
    timing=""
    if r.workKind="refill"
        if r.workIndex>=0 and r.workIndex<r.entries.Count()
            e=r.entries[r.workIndex]
            if e.DoesExist("endSeconds") then timing=" request_end_ms="+Fix((e.endSeconds-r.position)*1000#).ToStr()
        end if
    end if
    for each label in ["first","last"]
        victim=r.admissionVictimFirst
        if label="last" then victim=r.admissionVictimLast
        localIndex=victim-r.startIndex
        if victim>=0 and localIndex>=0 and localIndex<r.entries.Count()
            e=r.entries[localIndex]
            if e.DoesExist("endSeconds") then timing+=" victim_"+label+"_end_ms="+Fix((e.endSeconds-r.position)*1000#).ToStr()
        end if
    end for
    extra=" kind="+QaRollingKindCode(r).ToStr()+" gate="+gate.ToStr()
    extra+=" lead_ms="+Fix((r.endSeconds-r.position)*1000#).ToStr()
    extra+=" min_lead_ms="+Fix(minimumLead*1000#).ToStr()+" window_ms=24000"+timing
    packet="qa_roll_admit g="+r.generation.ToStr()+" src="+QaRollingSourceIndex(r,r.workIndex).ToStr()
    packet+=" local="+r.workIndex.ToStr()+" visits="+visits.ToStr()
    packet+=" evicted="+evicted.ToStr()+" resident="+QaRollingLiveBytes(r).ToStr()
    packet+=" protected="+r.admissionProtected.ToStr()+" deferred="+deferred.ToStr()
    packet+=" victim_first="+r.admissionVictimFirst.ToStr()+" victim_last="+r.admissionVictimLast.ToStr()
    packet+=extra
    print packet
end sub
sub QaRollingTelemetryFlushDemand(r as Object, outcome as Integer)
    if r.telemetry=invalid then return
    indices=[]
    for each key in r.telemetry.queued
        indices.Push(Val(key))
    end for
    for each index in indices
        QaRollingTelemetryDemandDone(r,index,outcome)
    end for
end sub
sub QaRollingTelemetryCancel(r as Object)
    t=r.telemetry
    if t=invalid then return
    if t.cancelReported or t.terminalReported then return
    t.cancelReported=true
    QaRollingTelemetryEndPhase(r)
    QaRollingTelemetryFlushDemand(r,3)
    if r.transfer<>invalid or r.job<>invalid or r.hashJob<>invalid or r.phase="admit" or t.cancelledWriter then QaRollingTelemetryWork(r,3,0#,0#)
end sub
sub QaRollingTelemetryFail(r as Object)
    if r.telemetry=invalid then return
    if r.telemetry.terminalReported then return
    QaRollingTelemetryEndPhase(r)
    QaRollingTelemetryFlushDemand(r,2)
    sourceBytes=0#:audioBytes=0#
    if r.phase="hash-source" or r.phase="extract" or r.phase="hash-audio"
        if r.DoesExist("sourceSize") then sourceBytes=r.sourceSize
    end if
    if r.phase="hash-audio" and r.hashJob<>invalid then audioBytes=r.hashJob.size
    QaRollingTelemetryWork(r,2,sourceBytes,audioBytes)
end sub
