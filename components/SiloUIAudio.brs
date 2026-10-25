' Foreground native Audio. Queues contain IDs/timelines only, never signed URLs.
sub SiloUIAudioInit()
    m.audioNode = m.top.findNode("audioNode")
    m.audioNode.observeField("state","onSiloUIAudioState")
    m.audioTimer = m.top.findNode("audioTimer")
    m.audioTimer.observeField("fire","onSiloUIAudioTick")
    m.top.observeField("appFocused","onSiloUIAudioAppFocus")
    m.audioGrid = m.top.findNode("audioBrowseGrid")
    m.audioGrid.observeField("itemSelected","onSiloUIAudioGridSelect")
    m.audioGrid.observeField("itemFocused","onSiloUIAudioGridFocus")
    m.audioBrowseStatus = m.top.findNode("audioBrowseStatus")
    m.audioBrowseStatus.font = SiloUIFont(20,false)
    m.audioBrowseTitle = m.top.findNode("audioBrowseTitle")
    m.audioBrowseTitle.font = SiloUIFont(30,true)
    BuildPills(m.top.findNode("audioBrowseButtons"),"audioBrowseButtons",["Library","Retry","Next page"],10,36,16)
    m.audioToken = 0
    m.audioBrowseToken = 0
    m.audioQueue = []
    m.audioPlan = invalid
    m.audioNext = invalid
    m.audioSleepMs = 0
    m.top.findNode("audioTitle").font = SiloUIFont(36,true)
    m.top.findNode("audioStatus").font = SiloUIFont(23,false)
    m.top.findNode("audioHint").font = SiloUIFont(21,false)
end sub

sub SiloUIAudioBrowse()
    m.audioBrowseReturn = invalid
    m.audioBrowseRestore = invalid
    m.audioBrowseTitle.text = "Audiobooks"
    ShowView("audioBrowse")
    SetZone("audioBrowseButtons")
    m.audioBrowseToken = NumberOr(m.audioBrowseToken,0)+1
    m.audioBrowseScope = HomeProgressScope()
    m.audioBrowseLibrary = ""
    m.audioBrowseLibraries = []
    m.audioBrowsePages = 0
    m.audioBrowseCursors = []
    m.audioBrowseCursor = ""
    m.audioBrowseMore = false
    m.audioBrowseError = false
    m.audioGrid.content = CreateObject("roSGNode","ContentNode")
    if m.provider <> "silo"
        m.audioBrowseStatus.text = "Audiobooks require a Silo source."
        return
    end if
    m.audioBrowseStatus.text = "Loading audiobook libraries…"
    m.audioBrowseLoading = true
    Api("audio_libraries",{},"audio_libraries",m.audioBrowseToken)
end sub

sub SiloUIAudioResult(purpose as String, result as Object, data as Object, extra as Dynamic)
    if purpose = "audio_libraries" or purpose = "audio_catalog"
        if extra <> m.audioBrowseToken or m.audioBrowseScope <> HomeProgressScope() or m.view <> "audioBrowse" then return
        m.audioBrowseLoading = false
        m.audioBrowseError = result.ok <> true
        if result.ok <> true
            m.audioBrowseStatus.text = "Audiobooks are unavailable. Select Retry to try again."
            return
        end if
        if purpose = "audio_libraries"
            m.audioBrowseLibraries = data.entries
            if m.audioBrowseLibraries.Count() = 0
                m.audioBrowseStatus.text = "No audiobook libraries are available for this profile."
                m.pillGroups.audioBrowseButtons.index = 1
                PaintPills("audioBrowseButtons",m.zone = "audioBrowseButtons")
                return
            end if
            if m.audioBrowseLibraries.Count() > 1
                m.audioBrowseStatus.text = "Choose an audiobook library."
                SiloUIAudioBrowseKey("options")
            else
                SiloUIAudioBrowseLibrary(0)
            end if
            return
        end if
        m.audioBrowsePages = m.audioBrowsePages+1
        for each entry in data.entries
            if m.audioGrid.content.getChildCount() >= 300 then exit for
            found = false
            for i = 0 to m.audioGrid.content.getChildCount()-1
                if m.audioGrid.content.getChild(i).item.itemId = entry.id then found = true : exit for
            end for
            if not found then m.audioGrid.content.appendChild(ItemNode(entry.item))
        end for
        cursor = TextOr(data.nextCursor)
        repeated = false
        for each seen in m.audioBrowseCursors
            if seen = cursor then repeated = true
        end for
        m.audioBrowseCursor = cursor
        m.audioBrowseMore = cursor <> "" and not repeated and m.audioBrowsePages < 5 and m.audioGrid.content.getChildCount() < 300
        m.audioBrowseStatus.text = ""
        if m.audioGrid.content.getChildCount() = 0 then m.audioBrowseStatus.text = "No audiobooks in this library."
        SiloUIAudioBrowseRestoreFocus()
        return
    end if
    if purpose = "audio_sync"
        SiloUIAudioSyncResult(result,extra)
        return
    end if
    if extra <> m.audioToken then return
    if purpose = "audio_detail"
        if m.audioScope <> HomeProgressScope() or m.view <> "audio" then return
        if result.ok <> true then m.audioLoading = false : Toast("Audio parts are unavailable.") : return
        m.audioQueue = data.queue
        m.audioBook = data
        m.top.findNode("audioTitle").text = data.title
        target = SiloUIAudioTarget(data.queue,data.resumeMs)
        if target <> invalid then SiloUIAudioRequestPart(target.index,target.localMs)
    else if purpose = "audio_start"
        m.audioLoading = false
        if result.ok <> true then Toast("This source has no supported Audio route.") : return
        m.audioPlan = result.plan
        m.audioOwner = result.plan.cleanupOwner
        m.audioSequence = 0
        m.audioLocalMs = result.plan.startPositionMs
        m.audioDidSeek = false
        m.audioStarted = false
        m.audioPositionReady = false
        m.audioSeekTargetMs = result.plan.startPositionMs
        if m.audioPartPaused = true then SiloUIAudioCapturePausedSeek(result.plan.startPositionMs)
        m.audioPartPaused = false
        m.audioWait = CreateObject("roTimespan")
        content = CreateObject("roSGNode","ContentNode")
        content.url = result.plan.url
        content.streamFormat = result.plan.streamFormat
        content.title = m.audioBook.title
        agent = CreateObject("roHttpAgent")
        agent.SetCertificatesFile("common:/certs/ca-bundle.crt")
        for each key in result.plan.headers
            agent.AddHeader(key,result.plan.headers[key])
        end for
        m.audioNode.setHttpAgent(agent)
        m.audioNode.content = content
        m.audioNode.control = "play"
    else if purpose = "audio_progress"
        m.audioProgressBusy = false

    end if
end sub

sub SiloUIAudioBrowseRetire()
    m.audioBrowseRestore = invalid
    m.audioBrowseToken = NumberOr(m.audioBrowseToken,0)+1
    m.audioBrowseLoading = false
    if m.audioGrid <> invalid then m.audioGrid.content = invalid
end sub

sub SiloUIAudioBrowseLibrary(index as Integer)
    m.audioBrowseRestore = invalid
    if index < 0 or index >= m.audioBrowseLibraries.Count() then return
    m.audioBrowseLibraryIndex = index
    selected = m.audioBrowseLibraries[index]
    m.audioBrowseLibrary = selected.id
    m.audioBrowseTitle.text = "Audiobooks · "+selected.title
    m.audioBrowseToken = m.audioBrowseToken+1
    m.audioBrowsePages = 0
    m.audioBrowseCursors = []
    m.audioBrowseCursor = ""
    m.audioBrowseMore = false
    m.audioBrowseLoading = false
    m.audioGrid.content = CreateObject("roSGNode","ContentNode")
    SiloUIAudioBrowsePage()
end sub

' Restore only within the captured visit; replay at most the previously loaded
' pages (and the catalog's five-page/300-card cap), never scan a new library.
sub SiloUIAudioBrowseRestoreFocus()
    saved = m.audioBrowseRestore
    if saved = invalid then return
    if saved.scope <> HomeProgressScope() or saved.libraryId <> m.audioBrowseLibrary then m.audioBrowseRestore = invalid : return
    count = m.audioGrid.content.getChildCount()
    target = -1
    for i = 0 to count-1
        if m.audioGrid.content.getChild(i).item.itemId = saved.itemId then target = i : exit for
    end for
    if target < 0 and m.audioBrowseMore and m.audioBrowsePages < saved.pages
        SiloUIAudioBrowsePage()
        return
    end if
    m.audioBrowseRestore = invalid
    if count = 0 then return
    if target < 0 then target = Int(NumberOr(saved.index,0))
    if target < 0 then target = 0
    if target >= count then target = count-1
    m.audioGrid.jumpToItem = target
    SetZone("audioBrowseGrid")
end sub

sub SiloUIAudioBrowsePage()
    if m.audioBrowseLoading = true or m.audioBrowseLibrary = "" then return
    m.audioBrowseError = false
    m.audioBrowseLoading = true
    m.audioBrowseStatus.text = "Loading audiobooks…"
    params = {libraryId:m.audioBrowseLibrary}
    if m.audioBrowseCursor <> ""
        params.cursor = m.audioBrowseCursor
        m.audioBrowseCursors.Push(m.audioBrowseCursor)
    end if
    Api("audio_catalog",params,"audio_catalog",m.audioBrowseToken)
end sub

sub onSiloUIAudioGridFocus()
    if m.view <> "audioBrowse" or m.audioBrowseScope <> HomeProgressScope() then return
    if m.audioGrid.content = invalid then return
    if m.audioBrowseMore and m.audioGrid.itemFocused >= m.audioGrid.content.getChildCount()-14 then SiloUIAudioBrowsePage()
end sub

sub onSiloUIAudioGridSelect()
    if m.view <> "audioBrowse" or m.audioBrowseScope <> HomeProgressScope() then return
    if m.audioGrid.content = invalid then return
    node = m.audioGrid.content.getChild(m.audioGrid.itemSelected)
    if node <> invalid then SiloUIAudioOpen(node.item.itemId)
end sub

function SiloUIAudioBrowseKey(key as String) as Boolean
    m.audioBrowseRestore = invalid
    if key = "options"
        if m.audioBrowseLibraries.Count() = 0 then return true
        labels = []
        for each library in m.audioBrowseLibraries
            labels.Push(library.title)
        end for
        m.audioBrowseChoiceToken = m.audioBrowseToken
        BrowsePagedChoices("Audiobook library",labels,"onSiloUIAudioChoice")
        return true
    end if
    if m.zone = "audioBrowseButtons"
        if key = "left" then return PillMove("audioBrowseButtons",-1)
        if key = "right" then return PillMove("audioBrowseButtons",1)
        if key = "up" then SetZone("nav") : return true
        if key = "down"
            if m.audioGrid.content.getChildCount() > 0 then SetZone("audioBrowseGrid")
            return true
        end if
        if key = "OK"
            if m.pillGroups.audioBrowseButtons.index = 0
                SiloUIAudioBrowseKey("options")
            else if m.audioBrowseLoading <> true
                if m.pillGroups.audioBrowseButtons.index = 1
                    if m.audioBrowseLibrary = ""
                        SiloUIAudioBrowse()
                    else if m.audioBrowseError = true
                        SiloUIAudioBrowsePage()
                    else
                        SiloUIAudioBrowseLibrary(m.audioBrowseLibraryIndex)
                    end if
                else if m.audioBrowseMore
                    SiloUIAudioBrowsePage()
                end if
            end if
            return true
        end if
    end if
    if m.zone = "audioBrowseGrid" and key = "up" then SetZone("audioBrowseButtons") : return true
    return false
end function

sub onSiloUIAudioChoice(event as Object)
    index = BrowseChoiceIndex(event)
    if m.view <> "audioBrowse" or m.audioBrowseScope <> HomeProgressScope() or m.audioBrowseChoiceToken <> m.audioBrowseToken then return
    SiloUIAudioBrowseLibrary(index)
end sub

sub SiloUIAudioOpen(itemId as String)
    if SiloUIPlaybackAdmissionBlocked() then SiloUIShowPlaybackAdmissionFailure() : return
    if m.compatPreparation <> invalid then return
    if m.transitionIntent <> invalid then return
    m.audioReturnBrowse = m.view = "audioBrowse"
    m.audioBrowseReturn = invalid
    if m.audioReturnBrowse and m.audioBrowseScope = HomeProgressScope()
        m.audioBrowseReturn = {scope:m.audioBrowseScope,libraryId:m.audioBrowseLibrary,itemId:itemId,index:m.audioGrid.itemSelected,pages:m.audioBrowsePages}
    end if
    PlayerDiscardPrebuffer()
    SiloUIAudioRelease()
    m.audioToken = m.audioToken+1
    m.audioScope = HomeProgressScope()
    m.audioQueue = []
    m.audioBook = invalid
    m.audioLoading = true
    m.audioSleepMs = 0
    m.audioSleepClock = CreateObject("roTimespan")
    m.audioSyncWarning = false
    m.top.findNode("audioTitle").text = "Loading audiobook…"
    m.top.findNode("audioStatus").text = ""
    ShowView("audio")
    SetZone("audio")
    m.audioTimer.control = "start"
    Api("audio_detail",{itemId:itemId},"audio_detail",m.audioToken)
end sub

sub SiloUIAudioRequestPart(index as Integer, localMs as Dynamic)
    if SiloUIPlaybackAdmissionBlocked() then SiloUIShowPlaybackAdmissionFailure() : return
    if m.compatPreparation <> invalid then return
    if index < 0 or index >= m.audioQueue.Count() then return
    keepPaused = m.audioNode.state = "paused" or SiloUIAudioPausedSeekCurrent()
    SiloUIAudioRelease(true)
    m.audioPartPaused = keepPaused
    m.audioIndex = index
    m.audioLocalMs = localMs
    m.audioScope = HomeProgressScope()
    m.audioNext = {index:index,localMs:localMs}
    m.audioLoading = true
    m.top.findNode("audioStatus").text = "Loading audio part…"
    m.audioTimer.control = "start"
end sub

sub SiloUIAudioRelease(preserveFixedSleep = false as Boolean)
    m.audioChapterSleep = invalid
    m.audioChapterFinished = false
    m.audioChapterPaused = false
    if not preserveFixedSleep then m.audioSleepMs = 0
    m.audioPausedSeek = invalid
    m.audioPartPaused = false
    if m.audioNode = invalid then return
    if m.audioPlan <> invalid then SiloUIAudioSendProgress(true)
    m.audioToken = NumberOr(m.audioToken,0)+1
    m.audioNext = invalid
    m.audioLoading = false
    m.audioSeekTargetMs = invalid
    m.audioNode.control = "stop"
    m.audioNode.content = invalid
    m.audioNode.setHttpAgent(CreateObject("roHttpAgent"))
    if m.audioPlan <> invalid
        SiloUIQueueCleanup(m.audioPlan,m.audioOwner)
        m.audioPlan = invalid
    end if
    m.audioProgressBusy = false
    if m.audioTimer <> invalid then m.audioTimer.control = "stop"
    if m.view = "audio" then m.top.findNode("audioStatus").text = "Stopped"
end sub

sub onSiloUIAudioState()
    if m.view <> "audio" or m.audioPlan = invalid or m.audioScope <> HomeProgressScope() then return
    state = m.audioNode.state
    if m.audioChapterFinished = true then return
    if state = "playing"
        m.audioStarted = true
        m.audioWait = invalid
        if m.audioDidSeek <> true
            m.audioDidSeek = true
            targetMs = NumberOr(m.audioSeekTargetMs,m.audioPlan.startPositionMs)
            if targetMs > 0 then SiloUIAudioSeek(targetMs)
        end if
        SiloUIAudioRestoreSeekPause()
    else if state = "paused"
        SiloUIAudioRestoreSeekPause()
    else if state = "finished"
        if m.audioChapterPaused = true
            m.audioChapterFinished = true
            return
        end if
        m.audioLocalMs = m.audioQueue[m.audioIndex].durationMs
        if SiloUIAudioChapterSleepDue() then return
        nextIndex = m.audioIndex+1
        if nextIndex < m.audioQueue.Count()
            SiloUIAudioRequestPart(nextIndex,0)
        else
            SiloUIAudioRelease()
            m.top.findNode("audioStatus").text = "Book finished"
        end if
    else if state = "error"
        SiloUIAudioRelease()
        m.top.findNode("audioStatus").text = "Audio could not play. Press Back to return."
    end if
end sub

sub onSiloUIAudioTick()
    if m.compatPreparation <> invalid then return
    if m.view <> "audio" or m.audioScope <> HomeProgressScope() then SiloUIAudioRelease() : return
    if m.audioSleepMs > 0 and m.audioSleepClock.TotalMilliseconds() >= m.audioSleepMs
        SiloUIAudioRelease()
        m.top.findNode("audioStatus").text = "Sleep timer ended playback"
        return
    end if
    if m.audioNext <> invalid
        if SiloUIPlaybackAdmissionBlocked() then return
        if m.audioSyncFlight <> invalid or m.audioSyncPending <> invalid then return
        nextPart = m.audioNext
        m.audioNext = invalid
        m.audioLoading = true
        part = m.audioQueue[nextPart.index]
        Api("audio_start",{itemId:m.audioBook.itemId,fileId:part.fileId,startPositionMs:nextPart.localMs},"audio_start",m.audioToken)
        return
    end if
    if m.audioPlan = invalid or m.audioChapterFinished = true then return
    state = m.audioNode.state
    if state = "playing" or state = "paused"
        observedMs = NumberOr(m.audioNode.position,0)*1000#
        expectedMs = NumberOr(m.audioSeekTargetMs,m.audioPlan.startPositionMs)
        if Abs(observedMs-expectedMs) < 3000 then m.audioPositionReady = true
        if m.audioPositionReady = true then m.audioLocalMs = observedMs
        SiloUIAudioRestoreSeekPause()
        if SiloUIAudioChapterSleepDue() then return
        globalMs = SiloUIAudioGlobal(m.audioQueue,m.audioIndex,m.audioLocalMs)
        m.top.findNode("audioStatus").text = UCase(Left(state,1))+Mid(state,2)+" · Part "+(m.audioIndex+1).ToStr()+" of "+m.audioQueue.Count().ToStr()+Chr(10)+SiloUIAudioTime(globalMs)+" / "+SiloUIAudioTime(m.audioBook.durationMs)
        m.audioTicks = NumberOr(m.audioTicks,0)+1
        if m.audioTicks mod 15 = 0 then SiloUIAudioSendProgress(false)
    else
        if m.audioWait = invalid then m.audioWait = CreateObject("roTimespan")
        if m.audioWait.TotalMilliseconds() >= 120000
            SiloUIAudioRelease()
            Toast("Audio startup timed out. Return and retry this title.")
        end if
    end if
end sub

sub SiloUIAudioSendProgress(final as Boolean)
    if m.audioPlan = invalid or m.audioStarted <> true or m.audioPositionReady <> true then return
    if m.expiredGeneration <> invalid
        if m.audioOwner.generation <= m.expiredGeneration then return
    end if
    globalMs = SiloUIAudioGlobal(m.audioQueue,m.audioIndex,NumberOr(m.audioLocalMs,0))
    SiloUIAudioQueueSync({itemId:m.audioBook.itemId,positionMs:globalMs,durationMs:m.audioBook.durationMs},m.audioOwner)
    if m.audioProgressBusy = true and not final then return
    m.audioProgressBusy = true
    m.audioSequence = m.audioSequence+1
    ApiOwned("playback_progress",{sessionId:m.audioPlan.sessionId,installationId:m.audioPlan.installationId,sequence:m.audioSequence,positionMs:m.audioLocalMs,isPaused:m.audioNode.state = "paused" or SiloUIAudioPausedSeekCurrent()},"audio_progress",m.audioToken,m.audioOwner)
end sub

function SiloUIAudioKey(key as String) as Boolean
    if key = "back"
        if m.audioReturnBrowse = true and m.audioBrowseScope = HomeProgressScope()
            ShowView("audioBrowse")
            SiloUIAudioBrowseLibrary(m.audioBrowseLibraryIndex)
            m.pillGroups.audioBrowseButtons.index = 1
            SetZone("audioBrowseButtons")
            saved = m.audioBrowseReturn
            if saved <> invalid
                if saved.scope = HomeProgressScope() and saved.libraryId = m.audioBrowseLibrary then m.audioBrowseRestore = saved
            end if
            return true
        end if
        if m.libraryReload = true then LibraryOpen(m.libraryType) else ShowView("library")
        SetZone("libraryTabs")
        return true
    end if
    if key = "up" or key = "down" or key = "options" then SiloUIAudioOptions() : return true
    if (key = "OK" or key = "play") and m.audioChapterFinished = true
        nextIndex = m.audioIndex+1
        m.audioChapterFinished = false
        m.audioPausedSeek = invalid
        if nextIndex < m.audioQueue.Count()
            SiloUIAudioRequestPart(nextIndex,0)
            m.audioPartPaused = false
        else
            SiloUIAudioRequestPart(m.audioIndex,0)
            m.audioPartPaused = false
        end if
        return true
    end if
    if (key = "OK" or key = "play") and (SiloUIAudioPausedSeekCurrent() or m.audioPartPaused = true)
        m.audioChapterPaused = false
        m.audioPausedSeek = invalid
        m.audioPartPaused = false
        if m.audioPlan <> invalid then m.audioNode.control = "resume"
        return true
    end if
    if m.audioPlan = invalid then return true
    if key = "OK" or key = "play"
        if m.audioNode.state = "paused" then m.audioNode.control = "resume" else m.audioNode.control = "pause"
    else if key = "left" or key = "right" or key = "rewind" or key = "fastforward"
        delta = 30000
        if key = "left" or key = "rewind" then delta = -30000
        target = SiloUIAudioTarget(m.audioQueue,SiloUIAudioGlobal(m.audioQueue,m.audioIndex,m.audioLocalMs)+delta)
        if target <> invalid
            if target.index = m.audioIndex
                SiloUIAudioSeek(target.localMs)
            else
                SiloUIAudioRequestPart(target.index,target.localMs)
            end if
        end if
    end if
    return true
end function

sub SiloUIAudioOptions()
    labels = ["Sleep timer: Off","Sleep timer: 15 minutes","Sleep timer: 30 minutes","Sleep timer: 60 minutes","Stop playback","Sleep timer: End of chapter","Previous chapter / part","Next chapter / part"]
    m.audioOptionChapters = []
    if m.audioPlan <> invalid
        m.audioOptionChapters = m.audioQueue[m.audioIndex].chapters
        for each chapter in m.audioOptionChapters
            labels.Push(Left(TextOr(chapter.title),90))
        end for
    end if
    m.audioOptionsToken = m.audioToken
    BrowsePagedChoices("Audio controls and current-part chapters",labels,"onSiloUIAudioOption")
end sub

sub onSiloUIAudioOption(event as Object)
    index = BrowseChoiceIndex(event)
    if index < 0 or m.view <> "audio" or m.audioOptionsToken <> m.audioToken then return
    if index <= 3
        durations = [0,900000,1800000,3600000]
        m.audioChapterSleep = invalid
        m.audioSleepMs = durations[index]
        m.audioSleepClock = CreateObject("roTimespan")
        Toast("Sleep timer updated.")
    else if index = 4
        SiloUIAudioRelease()
    else if index = 5
        target = invalid
        if m.audioPlan <> invalid and m.audioPositionReady = true and m.audioScope = HomeProgressScope()
            for each chapter in m.audioQueue[m.audioIndex].chapters
                if m.audioLocalMs >= chapter.start_seconds*1000# and m.audioLocalMs < chapter.end_seconds*1000#
                    target = {token:m.audioToken,scope:m.audioScope,endMs:chapter.end_seconds*1000#}
                    exit for
                end if
            end for
        end if
        if target = invalid then Toast("No current chapter is available.") : return
        m.audioChapterSleep = target
        m.audioSleepMs = 0
        Toast("Sleep timer set to end of chapter.")
    else if index = 6 or index = 7
        SiloUIAudioJumpChapter(index-6)
    else if m.audioPlan <> invalid and index-8 >= 0 and index-8 < m.audioOptionChapters.Count()
        SiloUIAudioSeek(m.audioOptionChapters[index-8].start_seconds*1000#)
    end if
end sub

sub SiloUIAudioJumpChapter(forward as Integer)
    if m.audioPlan = invalid or m.audioScope <> HomeProgressScope() then return
    positionMs = m.audioLocalMs
    if m.audioPositionReady <> true
        if not SiloUIAudioNumber(m.audioSeekTargetMs,m.audioQueue[m.audioIndex].durationMs) then Toast("Audio position is not ready.") : return
        positionMs = m.audioSeekTargetMs
    end if
    direction = -1
    if forward = 1 then direction = 1
    target = SiloUIAudioChapterTarget(m.audioQueue,m.audioIndex,positionMs,direction)
    if target = invalid then Toast("No chapter or part is available in that direction.") : return
    if target.index = m.audioIndex and m.audioNode.state <> "finished"
        SiloUIAudioSeek(target.localMs)
    else
        if m.audioChapterFinished = true then SiloUIAudioCapturePausedSeek(positionMs)
        SiloUIAudioRequestPart(target.index,target.localMs)
    end if
end sub

sub onSiloUIAudioAppFocus()
    if m.top.appFocused = false and m.view = "audio"
        SiloUIAudioRelease()
        m.top.findNode("audioStatus").text = "Playback stopped while app was inactive." + Chr(10) + "Press Back to return."
    end if
end sub

' One in-flight write plus the newest immutable pending sample. Release never
' clears these: part starts and source transitions drain them before proceeding.
sub SiloUIAudioQueueSync(params as Object, owner as Object)
    capturedParams = {}: capturedParams.Append(params)
    capturedOwner = {}: capturedOwner.Append(owner)
    m.audioSyncSerial = NumberOr(m.audioSyncSerial,0)+1
    ticket = {serial:m.audioSyncSerial,params:capturedParams,owner:capturedOwner}
    if m.audioSyncFlight <> invalid
        m.audioSyncPending = ticket
    else
        SiloUIAudioDispatchSync(ticket)
    end if
end sub

sub SiloUIAudioDispatchSync(ticket as Object)
    m.audioSyncFlight = ticket
    ApiOwned("audio_sync",ticket.params,"audio_sync",ticket.serial,ticket.owner)
end sub

sub SiloUIAudioSyncResult(result as Object, serial as Dynamic)
    ticket = m.audioSyncFlight
    if ticket = invalid then return
    if serial <> ticket.serial then return
    m.audioSyncFlight = invalid
    ownerCurrent = ticket.owner.provider = m.provider and ticket.owner.sourceId = m.sourceId and ticket.owner.profileId = m.profileId and ticket.owner.generation = m.generation
    if result.ok <> true and ownerCurrent
        if m.audioSyncWarning <> true then Toast("Book progress could not be confirmed by this server.")
        m.audioSyncWarning = true
    end if
    ' Expired credentials cannot authorize another write. Report failure rather
    ' than silently rebinding the final sample to a newly selected profile.
    if result.errorCode = "auth_required" then m.audioSyncPending = invalid
    pending = m.audioSyncPending
    m.audioSyncPending = invalid
    if pending <> invalid then SiloUIAudioDispatchSync(pending)
    SiloUIDrainMaybeDone()
end sub

' Readiness belongs to the latest requested seek, including one made before
' native playback or the first timer tick. Old clock samples cannot acknowledge it.
sub SiloUIAudioSeek(targetMs as Dynamic)
    if m.view <> "audio" or m.audioPlan = invalid or m.audioScope <> HomeProgressScope() then return
    if not SiloUIAudioNumber(targetMs,m.audioQueue[m.audioIndex].durationMs) then return
    if m.audioChapterSleep <> invalid
        if targetMs >= m.audioChapterSleep.endMs then m.audioChapterSleep = invalid
    end if
    m.audioChapterFinished = false
    m.audioChapterPaused = false
    if m.audioNode.state = "paused" or SiloUIAudioPausedSeekCurrent() then SiloUIAudioCapturePausedSeek(targetMs)
    m.audioSeekTargetMs = targetMs
    m.audioPositionReady = false
    m.audioLocalMs = targetMs
    m.audioDidSeek = m.audioNode.state = "playing" or m.audioNode.state = "paused"
    m.audioNode.seek = targetMs/1000#
end sub

' This intent belongs to the current lease visit and latest target, never the
' transient native state after assigning seek (Audio may resume on its own).
' Keep the desired pause until explicit Play, release or replacement seek; a
' paused sample can arrive before the native seek-induced playing notification.
sub SiloUIAudioCapturePausedSeek(targetMs as Dynamic)
    m.audioPausedSeek = {token:m.audioToken,scope:m.audioScope,targetMs:targetMs}
end sub

function SiloUIAudioPausedSeekCurrent() as Boolean
    intent = m.audioPausedSeek
    if intent = invalid then return false
    return m.view = "audio" and intent.token = m.audioToken and intent.scope = m.audioScope and m.audioScope = HomeProgressScope()
end function

sub SiloUIAudioRestoreSeekPause()
    if not SiloUIAudioPausedSeekCurrent() then return
    if m.audioPlan = invalid then return
    if Abs(NumberOr(m.audioNode.position,0)*1000#-m.audioPausedSeek.targetMs) >= 3000 then return
    if m.audioNode.state = "playing"
        m.audioNode.control = "pause"
    end if
end sub

function SiloUIAudioChapterSleepDue() as Boolean
    target = m.audioChapterSleep
    if target = invalid then return false
    if target.token <> m.audioToken or target.scope <> HomeProgressScope() then return false
    if m.audioPositionReady <> true or m.audioLocalMs < target.endMs then return false
    if m.audioNode.state <> "playing" and m.audioNode.state <> "finished" then return false
    m.audioChapterSleep = invalid
    m.audioChapterFinished = m.audioNode.state = "finished"
    m.audioChapterPaused = true
    m.audioNode.control = "pause"
    SiloUIAudioCapturePausedSeek(m.audioLocalMs)
    SiloUIAudioSendProgress(true)
    m.top.findNode("audioStatus").text = "Sleep timer reached end of chapter"
    return true
end function
