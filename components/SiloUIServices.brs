' Optional scoped server tools; native paged dialogs share the shipping browse UI.
sub ServicesOpen()
    if m.provider <> "silo" then return
    if not ServicesBegin(false) then return
    ServicesMenu()
end sub

sub ServicesShow(title as String, choices as Object)
    if not ServicesCurrent() then return
    m.servicesChoices = choices
    labels = []
    for each choice in choices
        labels.Push(choice.label)
    end for
    BrowsePagedChoices(title, labels, "onServicesChoice")
    if m.browseDialog <> invalid then ServicesBindDialog("choice",m.browseDialog)
end sub

sub ServicesMenu()
    ServicesShow("Server tools", [{label:"Requests",action:"requests_cap"},{label:"Notifications",action:"notification_cap"},{label:"Weekly calendar",action:"calendar_menu"}])
end sub

sub ServicesCall(action as String, params as Object)
    if not ServicesCurrent() or m.servicesBusy = true then return
    m.servicesBusy = true
    m.servicesSerial = NumberOr(m.servicesSerial,0) + 1
    m.servicesLoading = true
    Toast("Loading server tools…")
    m.servicesRequestDialogSequence = m.browseDialogSequence
    m.servicesLastAction = action
    m.servicesLastParams = params
    ApiOwned("service_" + action, params, "services_result", {visit:m.servicesVisit,serial:m.servicesSerial,action:action},m.servicesOwner)
end sub

sub onServicesChoice(event as Object)
    if not ServicesCurrent() then return
    prior = m.browseDialog
    index = BrowseChoiceIndex(event)
    if m.browseDialog <> invalid and not m.browseDialog.isSameNode(prior)
        ServicesBindDialog("choice",m.browseDialog)
    end if
    if index < 0 or index >= m.servicesChoices.Count() or m.servicesBusy = true then return
    choice = m.servicesChoices[index]
    ServicesAction(choice)
end sub

sub ServicesAction(choice as Object)
    if not ServicesCurrent() then return
    action = choice.action
    if action = "subtitle_version" then m.servicesFileVersion = choice.entry : m.servicesFileId = choice.entry.versionId : ServicesSubtitleMenu() : return
    if action = "subtitle_menu" then ServicesSubtitleMenu() : return
    if action = "subtitle_ai_menu" then ServicesAIMenu() : return
    if action = "subtitle_ai_source"
        choices = []
        for each track in m.servicesFileVersion.subtitleTracks
            if track.external <> true and NumberOr(track.index,-1) >= 0 then choices.Push({label:TextOr(track.title) + " " + TextOr(track.language),action:"subtitle_ai_track",entry:track})
        end for
        if choices.Count() = 0 then Toast("No embedded subtitle source is available.") : return
        ServicesShow("Translate source",choices)
        return
    end if
    if action = "subtitle_ai_track" or action = "subtitle_ai_transcribe"
        m.servicesAIParams = {fileId:m.servicesFileId,kind:"transcribe",sourceIndex:-1,sourceLanguage:""}
        if action = "subtitle_ai_track" then m.servicesAIParams.kind = "translate" : m.servicesAIParams.sourceIndex = choice.entry.index : m.servicesAIParams.sourceLanguage = choice.entry.language
        ServicesKeyboard("Target subtitle language code", "subtitle_ai_target", "en")
        return
    end if
    if action = "subtitle_job_detail"
        choices = [{label:"Refresh jobs",action:"subtitle_jobs"}]
        if choice.entry.status = "queued" or choice.entry.status = "pending" or choice.entry.status = "running" then choices.Push({label:"Cancel this job",action:"subtitle_job_cancel",entry:choice.entry})
        ServicesShow(choice.entry.kind + " • " + choice.entry.status,choices)
        return
    end if
    if action = "subtitle_download"
        m.servicesDownloadResult = choice.entry
        m.servicesMutation = choice
        ServicesDialog("Download this subtitle?",["Confirm","Cancel"],"onServicesConfirm")
        return
    end if
    if action = "subtitle_sync_read" then ServicesCall(action,{fileId:m.servicesFileId,key:choice.entry.key}) : return
    if action = "subtitle_delay" or action = "subtitle_reset" or action = "subtitle_sync_start" or action = "subtitle_job_cancel"
        m.servicesMutation = choice
        ServicesDialog("Confirm subtitle change",["Confirm","Cancel"],"onServicesConfirm")
        return
    end if
    if action = "subtitle_jobs" or action = "subtitle_list" then ServicesCall(action,{fileId:m.servicesFileId}) : return
    if action = "notifications_unread" then ServicesCall("notifications",{unread:true}) : return
    if action = "notifications_menu" then ServicesNotificationsMenu() : return
    if action = "notification_open"
        m.servicesSelected = choice.entry
        ServicesShow(choice.entry.title,[{label:"Mark read",action:"notifications_read"},{label:"Inbox",action:"notifications"}])
        m.browseDialog.message = choice.entry.summary + " " + choice.entry.date
        return
    end if
    if action = "notifications_read" or action = "notifications_read_all"
        m.servicesMutation = choice
        ServicesDialog("Mark notifications read?",["Confirm","Cancel"],"onServicesConfirm")
        return
    end if
    if action = "calendar_menu" then ServicesCalendarMenu() : return
    if action = "calendar_load" then ServicesCalendarLoad() : return
    if action = "calendar_previous" or action = "calendar_next"
        delta = 7 * 86400
        if action = "calendar_previous" then delta = -delta
        m.servicesWeekEpoch = m.servicesWeekEpoch + delta
        ServicesCalendarLoad()
        return
    end if
    if action = "calendar_timezone" then ServicesKeyboard("Calendar IANA timezone", "calendar_timezone", m.servicesCalendarZone) : return
    if action = "calendar_filter"
        choices = []
        for each filter in ["all","everything","following","favorites","watchlist","popular","trending"]
            choices.Push({label:filter,action:"calendar_filter_set",value:filter})
        end for
        ServicesShow("Calendar filter",choices)
        return
    end if
    if action = "calendar_filter_set" then m.servicesCalendarFilter = choice.value : ServicesCalendarLoad() : return
    if action = "calendar_item"
        if choice.entry.itemId = "" then Toast("This release is not in the catalog yet.") : return
        DetailOpen({itemId:choice.entry.itemId,type:choice.entry.type,title:choice.entry.title})
        return
    end if
    if action = "requests_menu" then ServicesRequestsMenu() : return
    if action = "main" then ServicesMenu() : return
    if action = "discover_series" then ServicesCall("discover",{page:1,mediaType:"series"}) : return
    if action = "request_search_input" then ServicesKeyboard("Find a movie or show", "request_search", "") : return
    if action = "request_detail" then ServicesCall(action,{mediaType:choice.entry.mediaType,tmdbId:choice.entry.tmdbId}) : return
    if action = "moderation_detail"
        m.servicesSelected = choice.entry
        ServicesShow(choice.entry.title + " • " + choice.entry.state,[{label:"Approve request",action:"moderation_approve"},{label:"Decline request",action:"moderation_decline"},{label:"Cancel as moderator",action:"moderation_cancel"},{label:"Refresh moderation list",action:"moderation_list"}])
        m.browseDialog.message = choice.entry.summary + Chr(10) + TextOr(choice.entry.downloadSummary)
        return
    end if
    if action = "request_status" then m.servicesSelected = choice.entry : ServicesCall(action,{id:choice.entry.id}) : return
    if SiloServicesUiMutation(action)
        m.servicesMutation = choice
        ServicesDialog("Confirm " + choice.label, ["Confirm", "Cancel"], "onServicesConfirm")
        return
    end if
    if action = "refresh_page" then ServicesCall(m.servicesPageAction,m.servicesPageParams) : return
    if action = "next_page"
        params = m.servicesPageParams
        if TextOr(m.servicesPage.nextCursor) <> "" then params.cursor = m.servicesPage.nextCursor else params.page = NumberOr(params.page,1) + 1
        ServicesCall(m.servicesPageAction,params)
        return
    end if
    ServicesCall(action,{page:1})
end sub

sub ServicesRequestsMenu()
    ServicesShow("Requests", [{label:"Discover trending movies",action:"discover"},{label:"Discover trending shows",action:"discover_series"},{label:"Search movies and shows",action:"request_search_input"},{label:"My requests and status",action:"request_mine"},{label:"Moderation (check access)",action:"moderation_cap"},{label:"Server tools",action:"main"}])
end sub

sub ServicesKeyboard(title as String, action as String, initial as String)
    if not ServicesCurrent() then return
    dialog = CreateObject("roSGNode", "KeyboardDialog")
    dialog.title = title
    dialog.text = initial
    dialog.buttons = ["Continue", "Cancel"]
    m.servicesKeyboard = dialog
    m.servicesKeyboardAction = action
    dialog.observeField("buttonSelected", "onServicesKeyboard")
    m.top.dialog = dialog
    ServicesBindDialog("keyboard",dialog)
end sub

sub onServicesKeyboard(event as Object)
    if not ServicesTakeDialog("keyboard",event) then return
    dialog = m.servicesKeyboard
    dialog.close = true
    if dialog.buttonSelected <> 0 then return
    value = Left(dialog.text.Trim(),200)
    dialog.text = ""
    if m.servicesKeyboardAction = "subtitle_search"
        if value = "" or Len(value) > 64 then Toast("Enter a language code.") : return
        ServicesCall("subtitle_search",{fileId:m.servicesFileId,language:value})
        return
    end if
    if m.servicesKeyboardAction = "subtitle_ai_target"
        if value = "" or Len(value) > 64 then Toast("Enter a language code.") : return
        m.servicesAIParams.targetLanguage = value
        m.servicesMutation = {action:"subtitle_ai_create"}
        ServicesDialog("Create subtitle AI job?",["Confirm","Cancel"],"onServicesConfirm")
        return
    end if
    if m.servicesKeyboardAction = "calendar_timezone"
        if value = "" or Len(value) > 100 then Toast("Enter an IANA timezone such as Europe/London.") : return
        m.servicesCalendarZone = value
        ServicesCalendarLoad()
        return
    end if
    if m.servicesKeyboardAction = "request_search"
        if Len(value) < 2 then Toast("Enter at least two letters.") : return
        ServicesCall("request_search",{query:value,page:1})
    end if
end sub

sub onServicesConfirm(event as Object)
    if not ServicesTakeDialog("confirm",event) then return
    index = m.browseDialog.buttonSelected
    m.browseDialog.close = true
    if index <> 0 or m.servicesBusy = true then return
    choice = m.servicesMutation
    entry = m.servicesSelected
    params = {}
    if entry <> invalid then params.id = entry.id
    if choice.action = "notifications_read_all" then params = {through:m.servicesReadCutoff}
    if choice.action = "request_create" then params = {title:entry.title,tmdbId:entry.tmdbId,mediaType:entry.mediaType}
    action = choice.action
    if action = "subtitle_download" then params = {fileId:m.servicesFileId,result:m.servicesDownloadResult}
    if action = "subtitle_ai_create" then params = m.servicesAIParams
    if action = "subtitle_sync_start" then params = {fileId:m.servicesFileId,key:m.servicesSubtitle.key}
    if action = "subtitle_delay" or action = "subtitle_reset"
        offset = m.servicesSubtitle.offsetMs + NumberOr(choice.delta,0)
        scale = m.servicesSubtitle.scale
        if action = "subtitle_reset" then offset = 0 : scale = 1
        params = {fileId:m.servicesFileId,key:m.servicesSubtitle.key,etag:m.servicesSubtitleETag,offsetMs:offset,scale:scale}
        action = "subtitle_timing"
    end if
    if action = "subtitle_job_cancel" then params = {id:choice.entry.id}
    ServicesCall(action,params)
end sub

sub ServicesResult(result as Object, data as Object, extra as Dynamic)
    if not ServicesCurrent() then return
    if type(extra) <> "roAssociativeArray" then return
    if m.servicesRequestDialogSequence <> m.browseDialogSequence then return
    if extra.visit <> m.servicesVisit or extra.serial <> m.servicesSerial or m.servicesGeneration <> m.generation or m.servicesOwnerView <> m.view then return
    m.servicesBusy = false
    if m.servicesLoading = true then Toast("")
    m.servicesLoading = false
    action = extra.action
    if result.ok <> true
        Toast("This server tool is unavailable or the change was not saved.")
        return
    end if
    if Right(action,4) = "_cap"
        m.servicesCaps[action] = data
        if action = "subtitle_sync_cap" then ServicesCall("subtitle_list",{fileId:m.servicesFileId}) : return
        if data.available <> true then Toast("This server does not allow this tool.") : return
        if action = "requests_cap" then ServicesRequestsMenu() : return
        if action = "moderation_cap" then ServicesCall("moderation_list",{}) : return
        if action = "notification_cap" then ServicesNotificationsMenu() : return
        if action = "subtitle_provider_cap" then ServicesKeyboard("Subtitle language code", "subtitle_search", "en") : return
        if action = "subtitle_ai_cap" then ServicesAIMenu() : return
        return
    end if
    if action = "subtitle_sync_read" then ServicesSubtitleDetail(data.entry,data.etag) : return
    if action = "subtitle_quota"
        message = "Used " + NumberOr(data.used,0).ToStr() + " • Remaining " + NumberOr(data.remaining,0).ToStr() + " • " + TextOr(data.period)
        if data.limited = false then message = "No configured quota limit. " + message
        ServicesDialog("Subtitle quota",["Close"],"onServicesClose")
        m.browseDialog.message = message
        return
    end if
    if SiloServicesUiMutation(action)
        Toast("Server confirmed the change.")
        if data.entry <> invalid then m.servicesSelected = data.entry
        if Left(action,9) = "subtitle_"
            m.detailReloadItem = m.detailItem
            if action = "subtitle_timing" or action = "subtitle_sync_start" then ServicesSubtitleDetail(data.entry,data.etag) else ServicesSubtitleMenu()
            return
        end if
        if Left(action,13) = "notifications" then ServicesCall("notifications",{}) else ServicesRequestsMenu()
        return
    end if
    if action = "notifications_count" then Toast("Unread notifications: " + NumberOr(data.unreadCount,0).ToStr()) : ServicesNotificationsMenu() : return
    if action = "notifications" then m.servicesReadCutoff = data.cutoff
    if action = "request_detail" or action = "request_status"
        m.servicesSelected = data.entry
        entry = data.entry
        choices = []
        if action = "request_detail" and entry.requestable = true then choices.Push({label:"Request this title",action:"request_create"})
        if action = "request_status"
            choices.Push({label:"Refresh status",action:"request_status",entry:entry})
            if entry.outcome = "active" and entry.status <> "completed" then choices.Push({label:"Cancel request",action:"request_cancel"})
            cap = m.servicesCaps.moderation_cap
            if cap <> invalid and cap.available = true
                choices.Push({label:"Approve request",action:"moderation_approve"})
                choices.Push({label:"Decline request",action:"moderation_decline"})
                choices.Push({label:"Cancel as moderator",action:"moderation_cancel"})
            end if
        else if entry.requestId <> ""
            choices.Push({label:"Current request status",action:"request_status",entry:{id:entry.requestId}})
        end if
        choices.Push({label:"Requests",action:"requests_menu"})
        ServicesShow(entry.title + " • " + TextOr(entry.state),choices)
        m.browseDialog.message = entry.summary + Chr(10) + TextOr(entry.downloadSummary)
        return
    end if
    ServicesPage(action,data)
end sub

sub ServicesPage(action as String, data as Object)
    m.servicesPage = data
    m.servicesPageAction = action
    m.servicesPageParams = m.servicesLastParams
    choices = []
    if type(data.entries) = "roArray"
        for each entry in data.entries
            entryAction = "request_detail"
            if action = "request_mine" then entryAction = "request_status"
            if action = "moderation_list" then entryAction = "moderation_detail"
            label = entry.title + " " + TextOr(entry.state)
            if action = "notifications"
                entryAction = "notification_open"
                if entry.unread = true then label = "Unread • " + label
            else if action = "subtitle_search"
                entryAction = "subtitle_download"
                label = entry.language + " • " + entry.provider + " • " + entry.releaseName
            else if action = "subtitle_list"
                entryAction = "subtitle_sync_read"
                label = entry.language + " • " + entry.title + " • " + entry.syncStatus
            else if action = "subtitle_jobs"
                entryAction = "subtitle_job_detail"
                label = entry.kind + " • " + entry.status + " • " + (NumberOr(entry.progress,0) * 100).ToStr() + "%"
            else if action = "calendar"
                entryAction = "calendar_item"
                label = entry.date + " • " + entry.title
            end if
            choices.Push({label:label,action:entryAction,entry:entry})
        end for
    end if
    if data.hasMore = true then choices.Push({label:"Next page",action:"next_page"})
    if action = "notifications" and TextOr(data.cutoff) <> "" then choices.Push({label:"Mark inbox read through this snapshot",action:"notifications_read_all"})
    if action = "calendar" then choices.Push({label:"Calendar week/timezone/filter",action:"calendar_menu"})
    choices.Push({label:"Refresh page",action:"refresh_page"})
    choices.Push({label:"Server tools",action:"main"})
    ServicesShow("Server results",choices)
    if type(data.entries) = "roArray" and m.browseDialog <> invalid
        if data.entries.Count() = 0 and ServicesCurrent()
            if action = "notifications" then m.browseDialog.message = "No notifications in this view."
            if action = "calendar" then m.browseDialog.message = "No releases for this week and filter."
        end if
    end if
end sub

function SiloServicesUiMutation(action as String) as Boolean
    return action = "subtitle_download" or action = "subtitle_ai_create" or action = "subtitle_timing" or action = "subtitle_sync_start" or action = "subtitle_job_cancel" or action = "notifications_read" or action = "notifications_read_all" or action = "request_create" or action = "request_cancel" or action = "moderation_approve" or action = "moderation_decline" or action = "moderation_cancel"
end function

sub ServicesNotificationsMenu()
    ServicesShow("Notifications", [{label:"Inbox",action:"notifications"},{label:"Unread only",action:"notifications_unread"},{label:"Unread count",action:"notifications_count"},{label:"Server tools",action:"main"}])
end sub

sub ServicesCalendarMenu()
    if m.servicesWeekEpoch = invalid
        now = CreateObject("roDateTime")
        m.servicesWeekEpoch = now.AsSeconds()
        m.servicesCalendarZone = "UTC"
        m.servicesCalendarFilter = "all"
    end if
    ServicesShow("Calendar • " + m.servicesCalendarZone, [{label:"Show this week",action:"calendar_load"},{label:"Previous week",action:"calendar_previous"},{label:"Next week",action:"calendar_next"},{label:"Timezone: " + m.servicesCalendarZone,action:"calendar_timezone"},{label:"Filter: " + m.servicesCalendarFilter,action:"calendar_filter"},{label:"Server tools",action:"main"}])
end sub

sub ServicesCalendarLoad()
    day = CreateObject("roDateTime")
    day.FromSeconds(m.servicesWeekEpoch)
    startDate = Left(day.ToISOString(),10)
    day.FromSeconds(m.servicesWeekEpoch + 6 * 86400)
    endDate = Left(day.ToISOString(),10)
    ServicesCall("calendar",{start:startDate,end:endDate,timezone:m.servicesCalendarZone,filter:m.servicesCalendarFilter})
end sub

sub ServicesSubtitles()
    if not ServicesBegin(true) then return
    choices = []
    for each version in m.detailVersions
        if TextOr(version.versionId) <> ""
            choices.Push({label:"Version " + (choices.Count() + 1).ToStr() + " • " + TextOr(version.resolution) + " " + TextOr(version.videoCodec),action:"subtitle_version",entry:version})
        end if
    end for
    if choices.Count() = 0 then Toast("No file version is available for subtitle tools.") : return
    ServicesShow("Subtitle tools • Select file",choices)
end sub

sub ServicesSubtitleMenu()
    ServicesShow("Subtitle tools", [{label:"Search subtitle providers",action:"subtitle_provider_cap"},{label:"Stored subtitles, sync and timing",action:"subtitle_sync_cap"},{label:"AI jobs and quota",action:"subtitle_ai_cap"}])
end sub

sub ServicesAIMenu()
    choices = [{label:"Jobs and status",action:"subtitle_jobs"},{label:"Quota",action:"subtitle_quota"},{label:"Translate an embedded subtitle",action:"subtitle_ai_source"}]
    cap = m.servicesCaps.subtitle_ai_cap
    if cap <> invalid and cap.transcribeEnabled = true then choices.Push({label:"Transcribe audio",action:"subtitle_ai_transcribe"})
    choices.Push({label:"Subtitle tools",action:"subtitle_menu"})
    ServicesShow("AI subtitles",choices)
end sub

sub ServicesSubtitleDetail(entry as Object, etag as String)
    m.servicesSubtitle = entry
    m.servicesSubtitleETag = etag
    choices = [{label:"Refresh timing/status",action:"subtitle_sync_read",entry:entry}]
    cap = m.servicesCaps.subtitle_sync_cap
    if cap <> invalid and cap.available = true then choices.Push({label:"Start sync",action:"subtitle_sync_start"})
    if etag <> ""
        choices.Push({label:"Delay subtitles +0.5 seconds",action:"subtitle_delay",delta:500})
        choices.Push({label:"Advance subtitles 0.5 seconds",action:"subtitle_delay",delta:-500})
        choices.Push({label:"Reset timing",action:"subtitle_reset"})
    end if
    choices.Push({label:"Subtitle tools",action:"subtitle_menu"})
    ServicesShow("Timing • " + NumberOr(entry.offsetMs,0).ToStr() + "ms • " + TextOr(entry.syncStatus),choices)
end sub

sub onServicesClose(event as Object)
    if not ServicesTakeDialog("close",event) then return
    m.browseDialog.close = true
end sub

' A visit owns both dispatch and UI; matching a view name alone is insufficient
' when the user returns to another title (or another visit to the same title).
function ServicesBegin(subtitles as Boolean) as Boolean
    if m.provider <> "silo" then return false
    m.servicesDetailContext = invalid
    if subtitles
        if m.view <> "detail" or m.detailItem = invalid then return false
        m.servicesDetailContext = {token:m.detailToken,itemId:TextOr(m.detailItem.itemId)}
    end if
    m.servicesVisit = NumberOr(m.servicesVisit,0)+1
    m.servicesSerial = 0
    m.servicesBusy = false
    m.servicesOwnerView = m.view
    m.servicesScreenToken = m.obQrGeneration
    m.servicesGeneration = m.generation
    m.servicesContext = BrowseCaptureContext()
    m.servicesOwner = m.servicesContext.owner
    m.servicesCaps = {}
    m.servicesDialogTicket = invalid
    m.servicesKeyboardTicket = invalid
    return true
end function

function ServicesCurrent() as Boolean
    return BrowseContextCurrent(m.servicesContext)
end function

sub ServicesDialog(title as String, labels as Object, handler as String)
    if not ServicesCurrent() then return
    BrowseDialog(title,labels,handler)
    kind = "confirm"
    if handler = "onServicesClose" then kind = "close"
    ServicesBindDialog(kind,m.browseDialog)
end sub

sub ServicesBindDialog(kind as String, node as Object)
    ticket = BrowseEventTicket(node,kind)
    ticket.kind = kind
    ticket.visit = m.servicesVisit
    m.servicesDialogTicket = invalid
    m.servicesKeyboardTicket = invalid
    if kind = "keyboard" then m.servicesKeyboardTicket = ticket else m.servicesDialogTicket = ticket
end sub

function ServicesTakeDialog(kind as String, event as Dynamic) as Boolean
    if not ServicesCurrent() or event = invalid then return false
    ticket = m.servicesDialogTicket
    if kind = "keyboard" then ticket = m.servicesKeyboardTicket
    if ticket = invalid then return false
    if ticket.kind <> kind or ticket.visit <> m.servicesVisit then return false
    return BrowseTakeEventTicket(ticket,event)
end function
