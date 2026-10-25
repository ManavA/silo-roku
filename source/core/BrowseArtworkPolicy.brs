' One public poster at a time. Owned Services cards must carry provenance from
' an exact catalog match; raw private provider artwork stays excluded.
function BrowseArtworkPlan(item as Dynamic, activeScope as Dynamic, renderedScope as Dynamic, currentUri as Dynamic) as Object
    uri = ""
    if BrowseArtworkScopeMatches(activeScope,renderedScope) and type(item) = "roAssociativeArray"
        eligible = false
        if BrowseArtworkField(item,"uiAction","") = ""
            kind = BrowseArtworkField(item,"type","")
            if BrowseArtworkField(item,"provider","") = "metadata" and (kind = "movie" or kind = "show" or kind = "series")
                catalogId = BrowseArtworkField(item,"catalogId","")
                if type(catalogId) = "String" or type(catalogId) = "roString"
                    eligible = Left(catalogId,9) = "metadata:"
                end if
            else if kind = "movie" or kind = "show"
                eligible = BrowseArtworkOwnedService(item,activeScope)
            end if
        end if
        if eligible
            candidate = BrowseArtworkField(item,"thumbKey","")
            if type(candidate) = "String" or type(candidate) = "roString"
                if Len(candidate) <= 256
                    pattern = "^https://image[.]tmdb[.]org/t/p/(w342|w780)/[A-Za-z0-9_-]+[.](jpg|jpeg|png|webp)$"
                    if CreateObject("roRegex",pattern,"").IsMatch(candidate) then uri = candidate
                end if
            end if
        end if
    end if
    if type(currentUri) <> "String" and type(currentUri) <> "roString" then currentUri = ""
    return {uri:uri,changed:uri <> currentUri,visible:uri <> ""}
end function

function BrowseArtworkOwnedService(item as Object, scope as Object) as Boolean
    if BrowseArtworkField(scope,"route","") <> "service_catalog" or BrowseArtworkField(scope,"listKind","") <> "items" then return false
    for each field in ["provider","sourceId","itemId","artworkProvenance","artworkProfileId"]
        value = BrowseArtworkField(item,field,invalid)
        if type(value) <> "String" and type(value) <> "roString" then return false
    end for
    for each field in ["provider","sourceId","profileId"]
        value = BrowseArtworkField(scope,field,invalid)
        if type(value) <> "String" and type(value) <> "roString" then return false
    end for
    if item.artworkProvenance <> "metadata_owned_match" or item.artworkProfileId <> scope.profileId then return false
    provider = item.provider
    if provider <> "plex" and provider <> "silo" then return false
    if provider <> scope.provider or item.sourceId <> scope.sourceId then return false
    if Len(item.sourceId) <= 5 or Len(item.sourceId) > 512 or Left(item.sourceId,5) <> provider + ":" then return false
    pattern = "^[0-9]{1,128}$"
    if provider = "silo" then pattern = "^[A-Za-z0-9_.:-]{1,256}$"
    if not CreateObject("roRegex",pattern,"").IsMatch(item.itemId) then return false
    owned = BrowseArtworkField(item,"owned",invalid)
    if type(owned) <> "Boolean" and type(owned) <> "roBoolean" then return false
    return owned = true
end function

function BrowseArtworkScopeMatches(activeScope as Dynamic, renderedScope as Dynamic) as Boolean
    if type(activeScope) <> "roAssociativeArray" or type(renderedScope) <> "roAssociativeArray" then return false
    for each field in ["provider","sourceId","profileId","generation","route","listKind"]
        if BrowseArtworkField(activeScope,field,invalid) <> BrowseArtworkField(renderedScope,field,invalid) then return false
    end for
    return true
end function

function BrowseArtworkField(value as Dynamic, field as String, fallback as Dynamic) as Dynamic
    if type(value) <> "roAssociativeArray" then return fallback
    if not value.DoesExist(field) then return fallback
    result = value[field]
    if result = invalid then return fallback
    return result
end function
