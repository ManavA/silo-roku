function SiloUINavigationMode(value as Dynamic) as String
    if Type(value) = "String" or Type(value) = "roString"
        if value = "left" then return "left"
    end if
    return "top"
end function

function SiloUINavigationChoices() as Object
    return [{label:"Top navigation",action:"navigation_select",value:"top"},{label:"Left overlay",action:"navigation_select",value:"left"},{label:"Back to Settings",action:"settings"}]
end function

function SiloUINavigationContentZone(view as String, zone as String) as Boolean
    zones = []
    if view = "home" then zones = ["heroButtons", "rows", "homeRetry"]
    if view = "detail" then zones = ["detailButtons", "seasons", "episodes", "detailCast", "detailSimilar"]
    if view = "libraries" then zones = ["librariesButtons","librariesList"]
    if view = "libraryShelves" then zones = ["librariesButtons","librariesRows"]
    if view = "library" then zones = ["libraryTabs", "grid", "libraryRetry"]
    if view = "audioBrowse" then zones = ["audioBrowseButtons", "audioBrowseGrid"]
    if view = "ebookBrowse" then zones = ["ebookBrowseButtons", "ebookBrowseGrid"]
    if view = "streaming" then zones = ["streamingButtons", "streamingGrid"]
    if view = "search" then zones = ["keyboard", "searchGrid"]
    for each allowed in zones
        if zone = allowed then return true
    end for
    return false
end function
