' Source-owned scores only; canonical array (including empty) overrides legacy facts.
function SiloUIRatingChips(item as Object) as Object
    entries = []
    truncated = false
    if item.DoesExist("ratings")
        if type(item.ratings) <> "roArray" then return entries
        count = item.ratings.Count()
        if count > 64 then count = 64 : truncated = true
        for index = 0 to count - 1
            rating = item.ratings[index]
            if type(rating) = "roAssociativeArray"
                source = SiloUIRatingText(rating.source, 32)
                score = SiloUIRatingNumber(rating.score)
                if source <> "" and score <> invalid
                    if score >= 0 and score <= 100
                        entries.Push({source:source,score:score,display:SiloUIRatingText(rating.display,12),name:SiloUIRatingText(rating.name,12)})
                    end if
                end if
            end if
        end for
    else if type(item.badges) = "roAssociativeArray"
        for each key in ["imdb", "tmdb", "rtCritic", "rtAudience"]
            score = SiloUIRatingNumber(item.badges[key])
            if score <> invalid
                source = key : limit = 100
                if key = "imdb" or key = "tmdb" then limit = 10
                if key = "rtCritic" then source = "rt_critic"
                if key = "rtAudience" then source = "rt_audience"
                if score >= 0 and score <= limit
                    if key = "imdb" or key = "tmdb" then score = score * 10
                    entries.Push({source:source,score:score,display:"",name:""})
                end if
            end if
        end for
    end if
    if entries.Count() = 0 then return []
    chips = []
    ' Six slots, with a visible count instead of silently discarding extra sources.
    limit = entries.Count()
    if limit > 6 or truncated then limit = 5
    if entries.Count() < limit then limit = entries.Count()
    for i = 0 to limit - 1
        e = entries[i] : source = e.source : text = e.display : asset = "" : name = e.name
        if source = "imdb" or source = "tmdb"
            if text = "" then text = Str(Int(e.score) / 10.0).Trim()
            if Right(text,3) <> "/10" then text = text + "/10"
            name = "IMDb" : asset = "imdb"
            if source = "tmdb" then name = "TMDB" : asset = "tmdb"
        else if source = "rt_critic" or source = "rt_audience"
            if text = "" then text = Int(e.score).ToStr() + "%"
            asset = "rt-fresh" : name = "RT Critics"
            if e.score < 60 then asset = "rt-rotten"
            if source = "rt_audience"
                name = "RT Audience" : asset = "rt-audience-fresh"
                if e.score < 60 then asset = "rt-audience-rotten"
            end if
        else
            if name = "" then name = Left(source,12)
            if text = "" then text = Int(e.score).ToStr() + "/100"
        end if
        fallback = name + " " + text
        if asset = "" then text = fallback
        chips.Push({source:source,text:text,fallback:fallback,asset:asset})
    end for
    if truncated
        chips.Push({source:"overflow",text:"More ratings",fallback:"",asset:""})
    else if entries.Count() > 6
        chips.Push({source:"overflow",text:"+" + (entries.Count()-5).ToStr() + " more",fallback:"",asset:""})
    end if
    return chips
end function

function SiloUIRatingNumber(value as Dynamic) as Dynamic
    kind = type(value)
    if kind = "Integer" or kind = "LongInteger" or kind = "Float" or kind = "Double" or kind = "roInt" or kind = "roInteger" or kind = "roLongInteger" or kind = "roFloat" or kind = "roDouble" then return value
    return invalid
end function

function SiloUIRatingText(value as Dynamic, limit as Integer) as String
    if type(value) <> "String" and type(value) <> "roString" then return ""
    return Left(value.Trim(),limit)
end function

function SiloUICardImdbLabel(item as Object) as String
    selected = item
    if item.DoesExist("ratings")
        selected = {ratings:[]}
        if type(item.ratings) = "roArray"
            count = item.ratings.Count()
            if count > 64 then count = 64
            for index = 0 to count - 1
                rating = item.ratings[index]
                if type(rating) = "roAssociativeArray"
                    if SiloUIRatingText(rating.source,32) = "imdb"
                        chips = SiloUIRatingChips({ratings:[rating]})
                        if chips.Count() > 0 then return chips[0].fallback
                    end if
                end if
            end for
        end if
    end if
    for each chip in SiloUIRatingChips(selected)
        if chip.source = "imdb" then return chip.fallback
    end for
    return ""
end function
