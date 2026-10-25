sub init()
    m.bg = m.top.findNode("bg")
    m.art = m.top.findNode("art")
    m.fallback = m.top.findNode("fallback")
    m.chipLeft = m.top.findNode("chipLeft")
    m.chipLeftBg = m.top.findNode("chipLeftBg")
    m.chipRight = m.top.findNode("chipRight")
    m.chipRightBg = m.top.findNode("chipRightBg")
    m.codec = m.top.findNode("codec")
    m.codecBg = m.top.findNode("codecBg")
    m.track = m.top.findNode("progressTrack")
    m.progress = m.top.findNode("progress")
    m.caption = m.top.findNode("caption")
    m.focusBorder = m.top.findNode("focusBorder")
    m.fallback.font = SiloUIFont(18, true)
    m.chipLeft.font = SiloUIFont(13, true)
    m.chipRight.font = SiloUIFont(13, true)
    m.caption.font = SiloUIFont(16, false)
    m.codec.font = SiloUIFont(13, true)
    m.art.observeField("loadStatus", "onArt")
    m.landscape = false
    m.imageH = 0
end sub

function SiloUIFont(size as Integer, bold as Boolean) as Object
    font = CreateObject("roSGNode", "Font")
    font.uri = "pkg:/images/fonts/Roboto-Regular.ttf"
    if bold then font.uri = "pkg:/images/fonts/Roboto-Medium.ttf"
    font.size = size
    return font
end function

sub onLayout()
    CardLayout()
    CardBindContent(false)
end sub

sub CardLayout()
    w = m.top.width
    h = m.top.height
    if w <= 0 or h <= 0 then return
    ' Landscape cards carry a caption under the image.
    imageH = h
    if m.top.itemContent <> invalid and m.top.itemContent.landscape = true then imageH = h - 30
    m.imageH = imageH
    m.bg.width = w : m.bg.height = imageH
    m.art.width = w : m.art.height = imageH
    m.art.loadWidth = w : m.art.loadHeight = imageH
    m.fallback.width = w - 16 : m.fallback.height = imageH
    m.fallback.translation = [8, 0]
    m.track.width = w - 16
    m.track.translation = [8, imageH - 10]
    m.progress.translation = [8, imageH - 10]
    m.caption.width = w
    m.caption.translation = [0, imageH + 6]
    for each id in ["focusTop", "focusBottom"]
        m.top.findNode(id).width = w
    end for
    for each id in ["focusLeft", "focusRight"]
        m.top.findNode(id).height = imageH
    end for
    m.top.findNode("focusBottom").translation = [0, imageH - 2]
    m.top.findNode("focusRight").translation = [w - 2, 0]
    layoutChips()
end sub

sub layoutChips()
    pad = 8
    if m.chipLeft.text <> ""
        lw = Len(m.chipLeft.text) * 8 + 14
        m.chipLeftBg.width = lw : m.chipLeftBg.height = 22
        m.chipLeftBg.translation = [pad, pad]
        m.chipLeft.width = lw : m.chipLeft.height = 22
        m.chipLeft.translation = [pad, pad]
    end if
    if m.chipRight.text <> "" and m.top.width > 0
        rw = Len(m.chipRight.text) * 8 + 14
        m.chipRightBg.width = rw : m.chipRightBg.height = 22
        m.chipRightBg.translation = [m.top.width - rw - pad, pad]
        m.chipRight.width = rw : m.chipRight.height = 22
        m.chipRight.translation = [m.top.width - rw - pad, pad]
    end if
    showCodec = m.codec.text <> "" and m.top.width > 16 and m.imageH >= 90
    if showCodec
        cw = Len(m.codec.text) * 7 + 14
        if cw > m.top.width - 16 then cw = m.top.width - 16
        m.codecBg.width = cw : m.codecBg.height = 22
        m.codecBg.translation = [pad, m.imageH - 38]
        m.codec.width = cw : m.codec.height = 22
        m.codec.translation = [pad, m.imageH - 38]
    end if
    m.codecBg.visible = showCodec
    m.chipLeftBg.visible = m.chipLeft.text <> ""
    m.chipRightBg.visible = m.chipRight.text <> ""
end sub

sub onContent()
    CardBindContent(true)
end sub

sub CardBindContent(retryExhausted as Boolean)
    if m.cardContent <> invalid
        m.cardContent.unobserveField("artCandidates")
        m.cardContent.unobserveField("watched")
        m.cardContent.unobserveField("resumeMs")
    end if
    c = m.top.itemContent
    m.cardContent = c
    m.codec.text = ""
    m.codecBg.visible = false
    if c = invalid then return
    c.observeField("artCandidates", "onContent")
    c.observeField("watched", "onCardProgress")
    c.observeField("resumeMs", "onCardProgress")
    landscape = c.landscape = true
    if landscape <> m.landscape
        m.landscape = landscape
        CardLayout()
    end if
    uri = c.HDPosterUrl
    if uri = invalid then uri = ""
    candidates = c.artCandidates
    if type(candidates) <> "roArray" then candidates = []
    if candidates.Count() = 0 and uri <> "" then candidates = [uri]
    artworkKey = FormatJson(candidates)
    exhausted = retryExhausted and candidates.Count() > 0 and m.art.loadStatus = "failed" and m.artCandidateIndex + 1 >= candidates.Count()
    if m.artworkKey <> artworkKey or exhausted
        m.artworkKey = artworkKey
        m.artCandidates = candidates
        retained = -1
        if m.art.loadStatus = "ready"
            for index = 0 to candidates.Count() - 1
                if candidates[index] = m.art.uri then retained = index
            end for
        end if
        if retained >= 0
            m.artCandidateIndex = retained
        else
            m.artCandidateIndex = 0
            m.art.opacity = 0
            m.art.uri = ""
            if candidates.Count() > 0 then m.art.uri = candidates[0]
        end if
    end if
    m.fallback.text = c.title
    m.fallback.visible = true
    if m.art.loadStatus = "ready" then onArt()
    caption = ""
    if c.landscape = true then caption = c.title
    m.caption.text = caption
    m.caption.visible = caption <> ""
    left = ""
    right = ""
    badges = c.badges
    if type(badges) = "roAssociativeArray"
        if badges.resolution <> invalid then left = ResolutionLabel(badges.resolution)
        if badges.imdb <> invalid then right = "IMDb " + Str(Int(badges.imdb * 10) / 10.0).Trim()
    end if
    m.codec.text = SourceVideoCodecs(badges)
    m.chipLeft.text = left
    m.chipRight.text = right
    layoutChips()
    onCardProgress()
end sub

sub onCardProgress()
    c = m.top.itemContent
    if c = invalid then return
    percent = 0
    if c.durationMs <> invalid and c.resumeMs <> invalid and c.durationMs > 0 then percent = c.resumeMs / c.durationMs
    if percent > 1 then percent = 1
    showProgress = percent > 0.01 and c.watched <> true
    m.track.visible = showProgress
    m.progress.visible = showProgress
    if showProgress then m.progress.width = (m.top.width - 16) * percent
end sub

sub onArt()
    status = m.art.loadStatus
    if status = "ready"
        m.art.opacity = 1
        m.fallback.visible = false
    else if status = "failed"
        m.art.opacity = 0
        m.fallback.visible = true
        if type(m.artCandidates) = "roArray"
            if m.artCandidateIndex + 1 < m.artCandidates.Count()
                m.artCandidateIndex = m.artCandidateIndex + 1
                m.art.uri = m.artCandidates[m.artCandidateIndex]
            end if
        end if
    end if
end sub

sub onFocus()
    ' Keep the outline on the artwork, including landscape cards with captions.
    activeList = m.top.gridHasFocus or (m.top.rowListHasFocus and m.top.rowHasFocus)
    m.focusBorder.visible = activeList and m.top.focusPercent > 0.5
end sub
