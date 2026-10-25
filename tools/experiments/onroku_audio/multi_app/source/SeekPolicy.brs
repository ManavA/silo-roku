' Pure title-time policy for already validated StockDescriptor snapshots.
' No transport, player seek, clock inference, generation routes, or cache ownership.
' All microseconds are nonnegative exact integers; stored values and arithmetic use explicit LongInteger values.
function QaSeekWhole(value as Dynamic) as Boolean
    kind=Type(value)
    if kind<>"Integer" and kind<>"roInt" and kind<>"roInteger" and kind<>"LongInteger" and kind<>"roLongInteger" and kind<>"Float" and kind<>"roFloat" and kind<>"Double" and kind<>"roDouble" then return false
    if not (value>=0 and value<=9007199254740991&) then return false
    ' A float32 value above this point cannot preserve every microsecond.
    if (kind="Float" or kind="roFloat") and value>16777216# then return false
    whole#=value
    remainder#=whole#-Int(whole#/1000000000#)*1000000000#
    return remainder#=Int(remainder#)
end function

' Caller must validate with QaSeekWhole before converting.
function QaSeekExactInteger(value as Dynamic) as LongInteger
    exact&=value
    return exact&
end function

' Only builtin runtime type metadata may cross this diagnostic boundary.
function QaSeekDiagnosticTypeName(value as Dynamic) as String
    name=Type(value)
    if Len(name)<1 or Len(name)>32 then return "Other"
    for i=1 to Len(name)
        code=Asc(Mid(name,i,1))
        letter=(code>=65 and code<=90) or (code>=97 and code<=122)
        digit=code>=48 and code<=57
        if not letter and (i=1 or not digit) then return "Other"
    end for
    return name
end function

sub QaSeekDurationDiagnostic(diagnostic as Dynamic, index as Integer, duration as Dynamic)
    if Type(diagnostic)<>"roAssociativeArray" then return
    kind=Type(duration):code=0:value=-1#
    if kind="Integer" or kind="roInt" or kind="roInteger" then code=1
    if kind="LongInteger" or kind="roLongInteger" then code=2
    if kind="Float" or kind="roFloat" then code=3
    if kind="Double" or kind="roDouble" then code=4
    if code<>0
        if duration>=-9007199254740991& and duration<=9007199254740991& then value=0#+duration
    end if
    diagnostic.durationIndex=index:diagnostic.durationKind=code:diagnostic.durationValue=value
    diagnostic.durationType=QaSeekDiagnosticTypeName(duration)
end sub

function QaSeekIndexRejected(diagnostic as Dynamic, gate as Integer) as Dynamic
    if Type(diagnostic)="roAssociativeArray" then diagnostic.gate=gate
    return invalid
end function

' Return a detached snapshot, or invalid. Revision is caller-owned and monotonic;
' a repeated revision must be identical. URL bytes are copied without rewriting.
function QaSeekIndex(previous as Dynamic, descriptor as Dynamic, revision as Dynamic, diagnostic=invalid as Dynamic) as Dynamic
    if Type(diagnostic)="roAssociativeArray" then diagnostic.gate=0
    if Type(descriptor)<>"roAssociativeArray" or not QaSeekWhole(revision) then return QaSeekIndexRejected(diagnostic,1)
    if Type(descriptor.binding)<>"String" and Type(descriptor.binding)<>"roString" then return QaSeekIndexRejected(diagnostic,2)
    if descriptor.binding="" or Type(descriptor.fragments)<>"roArray" or Type(descriptor.durationMicros)<>"roArray" then return QaSeekIndexRejected(diagnostic,3)
    if Type(descriptor.ended)<>"Boolean" and Type(descriptor.ended)<>"roBoolean" then return QaSeekIndexRejected(diagnostic,4)
    if descriptor.fragments.Count()<>descriptor.durationMicros.Count() then return QaSeekIndexRejected(diagnostic,5)
    if previous<>invalid
        if previous.binding<>descriptor.binding or previous.sequence<>descriptor.sequence then return QaSeekIndexRejected(diagnostic,6)
        ' Stock EVENT metadata can grow while published fragment timing stays fixed.
        ' Only a newer, still-growing snapshot may raise the validated target.
        if previous.targetDuration<>descriptor.targetDuration
            if not QaSeekWhole(descriptor.targetDuration) then return QaSeekIndexRejected(diagnostic,6)
            if descriptor.targetDuration>30 or descriptor.targetDuration<previous.targetDuration or previous.ended or revision<=previous.revision then return QaSeekIndexRejected(diagnostic,6)
        end if
        if previous.init<>invalid and previous.init<>descriptor.init then return QaSeekIndexRejected(diagnostic,7)
        if revision<previous.revision or descriptor.fragments.Count()<previous.urls.Count() then return QaSeekIndexRejected(diagnostic,8)
        if previous.ended and (not descriptor.ended or descriptor.fragments.Count()<>previous.urls.Count()) then return QaSeekIndexRejected(diagnostic,9)
        if revision=previous.revision and (descriptor.fragments.Count()<>previous.urls.Count() or descriptor.ended<>previous.ended or descriptor.init<>previous.init) then return QaSeekIndexRejected(diagnostic,10)
    end if
    urls=[]:durations=[]:starts=[]:total&=0&
    for n=0 to descriptor.fragments.Count()-1
        duration=descriptor.durationMicros[n]:url=descriptor.fragments[n]
        if not QaSeekWhole(duration)
            QaSeekDurationDiagnostic(diagnostic,n,duration)
            return QaSeekIndexRejected(diagnostic,11)
        end if
        if duration=0 or duration>9007199254740991&-total& then return QaSeekIndexRejected(diagnostic,12)
        if Type(url)<>"String" and Type(url)<>"roString" then return QaSeekIndexRejected(diagnostic,13)
        if url="" then return QaSeekIndexRejected(diagnostic,14)
        if previous<>invalid
            if n<previous.urls.Count()
                if previous.urls[n]<>url or previous.durations[n]<>duration then return QaSeekIndexRejected(diagnostic,15)
            end if
        end if
        duration&=duration
        starts.Push(total&):urls.Push(url):durations.Push(duration&):total&=total&+duration&
    end for
    return {binding:descriptor.binding,revision:QaSeekExactInteger(revision),init:descriptor.init,sequence:descriptor.sequence,targetDuration:descriptor.targetDuration,ended:descriptor.ended,urls:urls,durations:durations,starts:starts,indexedEndUs:total&}
end function

' Half-open ranges: a shared boundary selects the following source fragment.
' Unknown EVENT time waits; only the exact completed title edge is an end.
function QaSeekLookup(index as Dynamic, titleUs as Dynamic) as Object
    result={status:"invalid"}
    if index=invalid or not QaSeekWhole(titleUs) then return result
    result={status:"invalid",binding:index.binding,revision:index.revision,indexedEndUs:index.indexedEndUs}
    if titleUs>=index.indexedEndUs
        if not index.ended
            result.status="waiting_index"
        else if titleUs=index.indexedEndUs
            result.status="end"
        end if
        return result
    end if
    for n=0 to index.urls.Count()-1
        if titleUs<index.starts[n]+index.durations[n]
            result.status="indexed":result.sourceIndex=n:result.fragmentStartUs=index.starts[n]
            offset&=QaSeekExactInteger(titleUs)-index.starts[n]
            result.offsetUs=offset&:result.url=index.urls[n]
            return result
        end if
    end for
    return result
end function

' Plans are detached immutable values by contract; never mutate a published plan.
' sourceStartIndex addresses the source, not local fragment zero of a generation.
function QaSeekPlan(index as Dynamic, titleUs as Dynamic, generationId as Dynamic, requestId as Dynamic) as Dynamic
    if not QaSeekWhole(generationId) or not QaSeekWhole(requestId) then return invalid
    if generationId=0 or requestId=0 then return invalid
    found=QaSeekLookup(index,titleUs)
    if found.status<>"indexed" then return invalid
    return {generationId:QaSeekExactInteger(generationId),requestId:QaSeekExactInteger(requestId),binding:found.binding,revision:found.revision,sourceStartIndex:found.sourceIndex,titleOriginUs:found.fragmentStartUs,requestedTitleUs:QaSeekExactInteger(titleUs),offsetUs:found.offsetUs}
end function

' Caller supplies the qualified native origin for this exact plan/epoch.
' Subtract first: adding two large clocks first can lose a microsecond.
function QaSeekPosition(plan as Dynamic, requestId as Dynamic, generationId as Dynamic, nativeUs as Dynamic, nativeOriginUs as Dynamic) as Dynamic
    if plan=invalid then return invalid
    if not QaSeekWhole(requestId) or not QaSeekWhole(generationId) then return invalid
    if plan.requestId<>requestId or plan.generationId<>generationId then return invalid
    if not QaSeekWhole(nativeUs) or not QaSeekWhole(nativeOriginUs) then return invalid
    delta&=QaSeekExactInteger(nativeUs)-QaSeekExactInteger(nativeOriginUs)
    if delta&>9007199254740991&-plan.titleOriginUs or delta&<0&-plan.titleOriginUs then return invalid
    position&=plan.titleOriginUs+delta&
    return position&
end function

function QaSeekCopyPlan(plan as Dynamic) as Dynamic
    if plan=invalid then return invalid
    return {generationId:plan.generationId,requestId:plan.requestId,binding:plan.binding,revision:plan.revision,sourceStartIndex:plan.sourceStartIndex,titleOriginUs:plan.titleOriginUs,requestedTitleUs:plan.requestedTitleUs,offsetUs:plan.offsetUs}
end function

function QaSeekCopyRequest(state as Object) as Object
    return {status:state.status,requestId:state.requestId,generationId:state.generationId,binding:state.binding,revision:state.revision,requestedTitleUs:state.requestedTitleUs,plan:QaSeekCopyPlan(state.plan),activePlan:QaSeekCopyPlan(state.activePlan)}
end function

' IDs are positive exact integers, strictly increasing for new requests/generations.
' Repeating the latest ID is idempotent only for the identical request. A waiting
' request is resolved explicitly after a validated index append, never clamped.
function QaSeekRequest(previous as Dynamic, index as Dynamic, titleUs as Dynamic, requestId as Dynamic, generationId as Dynamic) as Dynamic
    if not QaSeekWhole(requestId) or not QaSeekWhole(generationId) then return invalid
    if requestId=0 or generationId=0 or index=invalid then return invalid
    if not QaSeekWhole(titleUs) then return invalid
    if previous<>invalid
        if previous.binding<>index.binding then return invalid
        if requestId=previous.requestId
            if generationId<>previous.generationId or titleUs<>previous.requestedTitleUs then return invalid
            return QaSeekCopyRequest(previous)
        end if
        if requestId<previous.requestId or generationId<=previous.generationId or index.revision<previous.revision then return invalid
    end if
    found=QaSeekLookup(index,titleUs)
    if found.status="invalid" then return invalid
    active=invalid
    if previous<>invalid then active=QaSeekCopyPlan(previous.activePlan)
    return {status:found.status,requestId:QaSeekExactInteger(requestId),generationId:QaSeekExactInteger(generationId),binding:index.binding,revision:index.revision,requestedTitleUs:QaSeekExactInteger(titleUs),plan:QaSeekPlan(index,titleUs,generationId,requestId),activePlan:active}
end function

function QaSeekResolve(previous as Dynamic, index as Dynamic) as Dynamic
    if previous=invalid or index=invalid then return invalid
    if previous.binding<>index.binding or index.revision<previous.revision then return invalid
    result=QaSeekCopyRequest(previous)
    if previous.status<>"waiting_index" then return result
    found=QaSeekLookup(index,previous.requestedTitleUs)
    result.status=found.status:result.revision=index.revision
    result.plan=QaSeekPlan(index,previous.requestedTitleUs,previous.generationId,previous.requestId)
    return result
end function

' An acknowledgement is policy state only; the Task owns actual activation.
function QaSeekAcknowledge(previous as Dynamic, requestId as Dynamic, generationId as Dynamic) as Dynamic
    if previous=invalid then return invalid
    if not QaSeekWhole(requestId) or not QaSeekWhole(generationId) then return invalid
    if previous.requestId<>requestId or previous.generationId<>generationId or previous.plan=invalid then return invalid
    result=QaSeekCopyRequest(previous)
    result.status="active":result.activePlan=QaSeekCopyPlan(previous.plan)
    return result
end function
