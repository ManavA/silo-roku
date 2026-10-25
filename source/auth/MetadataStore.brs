' Optional metadata uses its own explicit setting, never provider or legacy config.
function MetadataRequestConfig(version as String) as Object
    section = CreateObject("roRegistrySection", "silo.metadata")
    return {baseUrl:section.Read("baseUrl"),appVersion:version}
end function

function SaveMetadataUrl(value as String) as Boolean
    normalized = ""
    if value <> ""
        if Len(value) > 1024 then return false
        normalized = HmBaseUrl(value)
        if normalized = "" then return false
    end if
    section = CreateObject("roRegistrySection", "silo.metadata")
    if not section.Write("baseUrl",normalized) then return false
    return section.Flush()
end function
