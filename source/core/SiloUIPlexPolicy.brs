' SiloUIScene Plex presentation policies. No credentials enter these helpers.
function SiloUIPlexArt(base as String, key as String, kind as String) as String
    if base = "" or Left(key, 1) <> "/" or Left(key, 2) = "//" then return ""
    if Instr(1, key, "?") > 0 or Instr(1, key, "#") > 0 or Instr(1, key, Chr(92)) > 0 then return ""
    if not CreateObject("roRegex", "^/library/[A-Za-z0-9/_:.-]+$", "").IsMatch(key) then return ""
    dimensions = "width=300&height=450"
    if kind = "backdrop" then dimensions = "width=1280&height=720"
    if kind = "still" then dimensions = "width=560&height=316"
    return base + "/photo/:/transcode?" + dimensions + "&url=" + key.EncodeUriComponent()
end function

function SiloUIPlexSection(sections as Dynamic, kind as String) as String
    if type(sections) <> "roArray" then return ""
    if kind = "series" then kind = "show"
    for each section in sections
        if section.type = kind then return section.sectionId
    end for
    return ""
end function

function SiloUIPlexSort(sort as String, order as String) as String
    field = "titleSort"
    if sort = "added_at" then field = "addedAt"
    if sort = "release_date" then field = "originallyAvailableAt"
    return field + ":" + order
end function

function SiloUIPlexChildren(season as Object, limit as Integer, offset as Integer) as Object
    return {itemId: season.itemId, limit: limit, offset: offset}
end function

function SiloUIPlexReport(plan as Object, positionMs as Integer, paused as Boolean) as Object
    state = "playing"
    if paused then state = "paused"
    transcodeId = ""
    if plan.transcodeSessionId <> invalid then transcodeId = plan.transcodeSessionId
    return {itemId: plan.itemId, durationMs: plan.durationMs, positionMs: positionMs, state: state, transcodeSessionId: transcodeId}
end function
