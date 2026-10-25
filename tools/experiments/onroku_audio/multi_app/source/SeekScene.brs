' One-shot, opt-in native replacement measurement. No title clock is inferred.
sub QaSeekSceneInit(config as Dynamic)
    m.seekScene={enabled:false,applyNativeOffset:false,accurateSeek:false,nativeSeekField:false,triggerAfterSeconds:0#,readySeen:false,stage:"off",requestId:0,generationId:0,previousGenerationId:1,playbackEpoch:1,targetTitleUs:invalid,timeoutMs:15000,deadlineMs:0#,plan:invalid,url:""}
    if Type(config)<>"roAssociativeArray" then return
    setting=config.nativeSeekMeasurement
    if Type(setting)<>"roAssociativeArray" then return
    if setting.enabled<>true or not QaSeekWhole(setting.targetTitleUs) then return
    trigger=0#
    if setting.DoesExist("triggerAfterSeconds")
        if not QaClockNumber(setting.triggerAfterSeconds) then return
        trigger=setting.triggerAfterSeconds
        if not (trigger>=0 and trigger<=86400) then return
    end if
    m.seekScene.triggerAfterSeconds=trigger
    timeout=15000
    if QaSeekWhole(setting.transitionTimeoutMs)
        if setting.transitionTimeoutMs>=1000 and setting.transitionTimeoutMs<=30000 then timeout=setting.transitionTimeoutMs
    end if
    m.seekScene.enabled=true
    m.seekScene.stage="idle"
    m.seekScene.targetTitleUs=QaSeekExactInteger(setting.targetTitleUs)
    m.seekScene.timeoutMs=timeout
    m.seekScene.applyNativeOffset=(setting.applyNativeOffset=true)
    m.seekScene.accurateSeek=(setting.accurateSeek=true and m.seekScene.applyNativeOffset)
    m.seekScene.nativeSeekField=(setting.nativeSeekField=true and m.seekScene.applyNativeOffset)
end sub

sub QaSeekSceneReady()
    s=m.seekScene
    if s=invalid or not s.enabled or s.stage<>"idle" then return
    if m.task.rollingMode<>true then return
    s.readySeen=true
    priorPosition=-1#
    if QaClockNumber(m.video.position) then priorPosition=m.video.position
    if s.triggerAfterSeconds>0
        if not (priorPosition>=s.triggerAfterSeconds) then return
    end if
    s.requestId=1
    s.stage="waiting_offer"
    s.deadlineMs=m.seekClock.TotalMilliseconds()+s.timeoutMs
    ' Keep exact microseconds as an integer across the SceneGraph AA boundary.
    ' A transported Double may arrive as Float and lose precision above 2^24.
    target&=s.targetTitleUs
    m.task.seekRequest={requestId:s.requestId,targetTitleUs:target&}
    print "qa_seek_scene event=1 request="; s.requestId; " target_us="; s.targetTitleUs; " playback_epoch="; s.playbackEpoch; " prior_position_s="; priorPosition
end sub

function QaSeekScenePlanValid(offer as Dynamic, s as Object) as Boolean
    if Type(offer)<>"roAssociativeArray" or Type(offer.plan)<>"roAssociativeArray" then return false
    p=offer.plan
    if offer.requestId<>s.requestId or not QaSeekWhole(offer.generationId) then return false
    if offer.generationId<=s.previousGenerationId or offer.generationId>2147483647# then return false
    if offer.previousGenerationId<>s.previousGenerationId then return false
    if p.requestId<>offer.requestId or p.generationId<>offer.generationId then return false
    if not QaSeekWhole(p.requestedTitleUs) or p.requestedTitleUs<>s.targetTitleUs then return false
    if not QaSeekWhole(p.titleOriginUs) or not QaSeekWhole(p.offsetUs) then return false
    if p.titleOriginUs+p.offsetUs<>s.targetTitleUs then return false
    if not QaSeekWhole(p.sourceStartIndex) or not QaSeekWhole(p.revision) then return false
    if Type(p.binding)<>"String" and Type(p.binding)<>"roString" then return false
    if p.binding="" then return false
    expected="http://127.0.0.1:34831/g"+offer.generationId.ToStr()+"/master.m3u8"
    return offer.localMasterUrl=expected
end function

function QaSeekSceneExactActive(offer as Dynamic, s as Object) as Boolean
    if not QaSeekScenePlanValid(offer,s) then return false
    p=offer.plan:q=s.plan
    return offer.generationId=s.generationId and offer.localMasterUrl=s.url and p.binding=q.binding and p.revision=q.revision and p.sourceStartIndex=q.sourceStartIndex and p.titleOriginUs=q.titleOriginUs and p.offsetUs=q.offsetUs
end function

sub QaSeekSceneOffer(offer as Dynamic)
    s=m.seekScene
    if s=invalid or not s.enabled then return
    if Type(offer)<>"roAssociativeArray" then return
    if offer.requestId<>s.requestId then return
    if s.stage="waiting_offer"
        if offer.status="failed" or offer.status="cancelled" then QaSeekSceneFail(2):return
        if offer.status<>"offered" or not QaSeekScenePlanValid(offer,s) then return
        s.generationId=offer.generationId:s.plan=QaSeekCopyPlan(offer.plan):s.url=offer.localMasterUrl
        s.stage="await_active":s.deadlineMs=m.seekClock.TotalMilliseconds()+s.timeoutMs
        m.task.seekAck={action:"accept",requestId:s.requestId,generationId:s.generationId}
        print "qa_seek_scene event=2 request="; s.requestId; " generation="; s.generationId; " src_index="; s.plan.sourceStartIndex; " title_origin_us="; s.plan.titleOriginUs; " offset_us="; s.plan.offsetUs
    else if s.stage="await_active"
        if offer.generationId<>s.generationId then return
        if offer.status="failed" or offer.status="cancelled" then QaSeekSceneFail(3):return
        if offer.status<>"active" or not QaSeekSceneExactActive(offer,s) then return
        s.stage="stopping":s.deadlineMs=m.seekClock.TotalMilliseconds()+s.timeoutMs
        m.video.control="stop"
        print "qa_seek_scene event=3 request="; s.requestId; " generation="; s.generationId; " playback_epoch="; s.playbackEpoch
    end if
end sub

sub QaSeekSceneState(state as String)
    s=m.seekScene
    if s=invalid or not s.enabled then return
    if s.stage="stopping" and state="stopped"
        ' Completion is the observed state event after our stop command.
        m.video.content=invalid
        content=CreateObject("roSGNode","ContentNode")
        content.streamFormat="hls":content.url=s.url:content.title="Native seek measurement"
        applied=0
        if s.applyNativeOffset and not s.nativeSeekField
            content.playStart=s.plan.offsetUs/1000000#
            applied=1
        end if
        print "qa_seek_offset request="; s.requestId; " generation="; s.generationId; " offset_us="; s.plan.offsetUs; " applied="; applied
        requested=0:supported=0:modeApplied=0
        if s.accurateSeek
            requested=1
            ' seekMode is optional (Roku OS 15.1+); probe the node, not its model.
            if m.video.hasField("seekMode")
                supported=1
                m.video.seekMode="accurate"
                if m.video.seekMode="accurate" then modeApplied=1
            end if
        end if
        print "qa_seek_mode requested="; requested; " supported="; supported; " applied="; modeApplied; " qualified=0"
        m.video.content=content
        route=0:requestedSeconds=-1#:playStartSeconds=-1#
        if s.applyNativeOffset
            requestedSeconds=s.plan.offsetUs/1000000#
            if s.nativeSeekField
                ' seek is write-only: this records the requested value, not acceptance.
                route=1
                m.video.seek=requestedSeconds
            else
                playStartSeconds=m.video.content.playStart
            end if
        end if
        print "qa_seek_offset_readback route="; route; " requested_s="; requestedSeconds; " play_start_s="; playStartSeconds; " qualified=0"
        s.playbackEpoch+=1:s.stage="loading":s.deadlineMs=m.seekClock.TotalMilliseconds()+s.timeoutMs
        m.video.control="play"
        print "qa_seek_scene event=4 request="; s.requestId; " generation="; s.generationId; " playback_epoch="; s.playbackEpoch
    else if s.stage="loading" and state="playing"
        s.stage="running"
        print "qa_seek_scene event=5 request="; s.requestId; " generation="; s.generationId; " playback_epoch="; s.playbackEpoch; " landed=0"
    else if (s.stage="stopping" or s.stage="loading" or s.stage="running") and state="error"
        QaSeekSceneFail(4)
    end if
end sub

sub QaSeekSceneTick()
    s=m.seekScene
    if s=invalid or not s.enabled then return
    if s.stage="idle" and s.readySeen then QaSeekSceneReady()
    if s.stage="waiting_offer" or s.stage="await_active" or s.stage="stopping" or s.stage="loading"
        if m.seekClock.TotalMilliseconds()>=s.deadlineMs then QaSeekSceneFail(5):return
    end if
    if s.stage<>"loading" and s.stage<>"running" then return
    info=m.video.positionInfo
    if Type(info)="roAssociativeArray"
        if QaClockNumber(info.audio) and QaClockNumber(info.video) and QaClockNumber(info.epoch)
            print "qa_seek_position request="; s.requestId; " generation="; s.generationId; " playback_epoch="; s.playbackEpoch; " native_epoch="; info.epoch; " native_position_s="; m.video.position
            print "qa_seek_av request="; s.requestId; " generation="; s.generationId; " audio_s="; info.audio; " video_s="; info.video; " qualified=0 landed=0"
        end if
    end if
end sub

sub QaSeekSceneBuffer(status as Dynamic)
    s=m.seekScene
    if s=invalid or not s.enabled or s.stage<>"loading" and s.stage<>"running" then return
    if Type(status)<>"roAssociativeArray" then return
    actual=-1#:done=-1
    if QaClockNumber(status.actualStart) then actual=status.actualStart
    if status.prebufferDone=true then done=1
    if status.prebufferDone=false then done=0
    print "qa_seek_buffer request="; s.requestId; " generation="; s.generationId; " playback_epoch="; s.playbackEpoch
    print "qa_seek_buffer_value request="; s.requestId; " actual_start_s="; actual; " prebuffer_done="; done; " qualified=0"
end sub

sub QaSeekSceneSegment(segment as Dynamic)
    s=m.seekScene
    if s=invalid or not s.enabled or s.stage<>"loading" and s.stage<>"running" then return
    if Type(segment)<>"roAssociativeArray" then return
    encodedWidth=-1:encodedHeight=-1:hdr=-1
    if QaClockNumber(segment.width) then encodedWidth=segment.width
    if QaClockNumber(segment.height) then encodedHeight=segment.height
    if segment.hdrModeStr="none" then hdr=0
    if segment.hdrModeStr="hdr10" then hdr=1
    if segment.hdrModeStr="dolby_vision" then hdr=2
    if segment.hdrModeStr="hlg10" then hdr=3
    if segment.hdrModeStr="hdr10+" then hdr=4
    if segment.hdrModeStr="sl-hdr2" then hdr=5
    print "qa_seek_segment request="; s.requestId; " generation="; s.generationId; " playback_epoch="; s.playbackEpoch
    print "qa_seek_segment_value request="; s.requestId; " encoded_width="; encodedWidth; " encoded_height="; encodedHeight; " hdr="; hdr; " qualified=0"
end sub

sub QaSeekSceneFail(code as Integer)
    s=m.seekScene
    if s=invalid or s.stage="failed" then return
    s.stage="failed"
    m.autoTimer.control="stop":m.video.control="stop":m.task.stopRequested=true
    m.label.text="Native seek measurement stopped; inspect numerical QA logs"
    print "qa_seek_scene event=6 reason="; code; " request="; s.requestId; " generation="; s.generationId; " playback_epoch="; s.playbackEpoch
end sub

sub QaSeekSceneCancel()
    s=m.seekScene
    if s=invalid or not s.enabled or s.stage="cancelled" then return
    s.stage="cancelled"
    print "qa_seek_scene event=7 request="; s.requestId; " generation="; s.generationId; " playback_epoch="; s.playbackEpoch
end sub
