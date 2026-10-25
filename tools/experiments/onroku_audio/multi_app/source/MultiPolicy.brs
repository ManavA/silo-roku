function QaMultiAccept(previous as Object, plan as Object, sourceBytes as Integer, audioBytes as Integer) as Object
    fail = {ok:false}
    if not previous.ok then return fail
    if not plan.ok then return fail
    if previous.count >= 16 or sourceBytes < 1 or audioBytes < 1 then return fail
    if previous.sourceBytes+sourceBytes > 25165824 or previous.audioBytes+audioBytes > 4194304 then return fail
    if plan.samples.Count() = 0 or plan.timescale < 1 or plan.trackid < 1 then return fail
    firstPts = plan.samples[0].pts
    if previous.count > 0
        if plan.timescale <> previous.timescale or plan.trackid <> previous.trackid then return fail
        if firstPts <> previous.nextPts then return fail
    end if
    nextPts = firstPts
    for each sample in plan.samples
        if sample.pts <> nextPts or sample.duration < 1 then return fail
        nextPts += sample.duration
    end for
    return {ok:true,count:previous.count+1,sourceBytes:previous.sourceBytes+sourceBytes,audioBytes:previous.audioBytes+audioBytes,nextPts:nextPts,timescale:plan.timescale,trackid:plan.trackid}
end function

function QaMultiContinuity(previous as Object, plan as Object, sourceBytes as Double, audioBytes as Double) as Object
    fail={ok:false}
    if not previous.ok or not plan.ok or sourceBytes<1 or audioBytes<1 then return fail
    if plan.samples.Count() = 0 or plan.timescale < 1 or plan.trackid < 1 then return fail
    firstPts = plan.samples[0].pts
    if previous.count > 0
        if plan.timescale <> previous.timescale or plan.trackid <> previous.trackid then return fail
        if firstPts <> previous.nextPts then return fail
    end if
    nextPts = firstPts
    for each sample in plan.samples
        if sample.pts <> nextPts or sample.duration < 1 then return fail
        nextPts += sample.duration
    end for
    return {ok:true,count:previous.count+1,sourceBytes:previous.sourceBytes+sourceBytes,audioBytes:previous.audioBytes+audioBytes,nextPts:nextPts,timescale:plan.timescale,trackid:plan.trackid}
end function
