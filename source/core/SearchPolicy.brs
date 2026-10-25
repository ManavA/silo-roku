' Compact, volatile positive cache for titles already shown by the active
' source/profile. It never establishes absence and never stores media URLs.
' Ranking reference: Android 45774f8b spec/07-search.md and the read-only tvOS
' SearchScreen.swift / LibraryIndexStore.swift snapshot inspected 2026-10-12.
function SearchIndexAdd(existing as Dynamic, incoming as Dynamic, sourceId as String, limit = 500 as Integer) as Object
    result = []
    seen = {}
    if limit < 1 then return result
    if limit > 500 then limit = 500
    for each values in [incoming, existing]
        if type(values) = "roArray"
            inspected = 0
            for each raw in values
                inspected++
                if inspected > 1000 or result.Count() >= limit then exit for
                card = SearchIndexCard(raw, sourceId)
                if card <> invalid and not seen.DoesExist(card.itemId)
                    seen[card.itemId] = true
                    result.Push(card)
                end if
            end for
        end if
    end for
    return result
end function

function SearchIndexCard(raw as Dynamic, sourceId as String) as Dynamic
    if type(raw) <> "roAssociativeArray" then return invalid
    if sourceId = "" or SearchField(raw,"sourceId","") <> sourceId then return invalid
    itemId = SearchField(raw,"itemId","")
    title = SearchField(raw,"title","")
    kind = SearchField(raw,"type","")
    if type(itemId) <> "String" and type(itemId) <> "roString" then return invalid
    if type(title) <> "String" and type(title) <> "roString" then return invalid
    title = Left(title.Trim(),120)
    if title = "" then return invalid
    if kind <> "movie" and kind <> "show" and kind <> "series" and kind <> "episode" and kind <> "season" and kind <> "collection" then return invalid
    provider = ""
    if Left(sourceId,5) = "plex:" and Len(sourceId) > 5
        provider = "plex"
        if SearchField(raw,"provider","") <> "plex" then return invalid
    else if Left(sourceId,5) = "silo:" and Len(sourceId) > 5
        provider = "silo"
        if SearchField(raw,"provider","silo") <> "silo" then return invalid
    else
        return invalid
    end if
    if not SearchNativeId(itemId,provider) then return invalid
    card = {provider:provider,sourceId:sourceId,itemId:itemId,title:title,type:kind}
    year = SearchField(raw,"year",0)
    if type(year) = "Integer" or type(year) = "roInt" or type(year) = "roInteger" then card["year"] = year
    resume = SearchField(raw,"resumeMs",0)
    if type(resume) = "Integer" or type(resume) = "roInt" or type(resume) = "roInteger" or type(resume) = "Double" or type(resume) = "roDouble"
        if resume > 0 and resume <= 86400000 then card["resumeMs"] = resume
    end if
    watched = SearchField(raw,"watched",invalid)
    if type(watched) = "Boolean" or type(watched) = "roBoolean" then card["watched"] = watched
    return card
end function

function SearchNativeId(itemId as String, provider as String) as Boolean
    maximum = 20
    allowed = "0123456789"
    if provider = "silo"
        maximum = 256
        allowed = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.:-"
    end if
    if Len(itemId) < 1 or Len(itemId) > maximum then return false
    for position = 1 to Len(itemId)
        if Instr(1,allowed,Mid(itemId,position,1)) = 0 then return false
    end for
    return true
end function

function SearchLocalMatches(index as Dynamic, query as String, sourceId as String, limit = 100 as Integer) as Object
    return SearchRankCards(index,query,sourceId,limit,false,false,500)
end function

' Ranking runs only on submitted queries and returned pages. At most 500 compact
' cards, 120-character strings and 1024 short edit comparisons are considered.
' Exhausting fuzzy work never stops the exact/prefix/substring scan.
function SearchRankCards(values as Dynamic, query as String, sourceId as String, limit as Integer, keepUnmatched as Boolean, keepRaw as Boolean, scanLimit as Integer) as Object
    result = []
    if type(values) <> "roArray" then return result
    if limit < 1 then return result
    if limit > 100 then limit = 100
    if scanLimit > 500 then scanLimit = 500
    context = SearchQueryContext(query)
    if Len(context.text) < 2 then return result
    ranked = []
    seen = {}
    inspected = 0
    for each raw in values
        inspected++
        if inspected > scanLimit then exit for
        card = SearchIndexCard(raw,sourceId)
        if card <> invalid and not seen.DoesExist(card.itemId)
            seen[card.itemId] = true
            bucket = SearchTitleBucket(card.title,context)
            if bucket < 4 or keepUnmatched
                output = card
                if keepRaw then output = raw
                ranked.Push({sortkey:SearchRankKey(card,bucket,context.tokens.Count(),inspected),card:output})
            end if
        end if
    end for
    ranked.SortBy("sortkey")
    for each entry in ranked
        if result.Count() >= limit then exit for
        result.Push(entry.card)
    end for
    return result
end function

' Only the scene's projected, owner-checked index enters this lexical path.
function SearchLoadedMatches(cards as Object, titles as Object, query as String, kind as String) as Object
    result = []
    context = SearchQueryContext(query)
    if Len(context.text) < 1 then return result
    ranked = []
    arrival = 0
    for each card in cards
        arrival++
        if arrival > 100 then exit for
        if card.type = "movie" or card.type = "show" or card.type = "series"
            if kind = "" or card.type = kind or (kind = "series" and card.type = "show")
                bucket = SearchLexicalTitleBucket(titles[card.itemId].text,context)
                if bucket < 4 then ranked.Push({card:card,sortkey:SearchRankKey(card,bucket,context.tokens.Count(),arrival)})
            end if
        end if
    end for
    ranked.SortBy("sortkey")
    for each entry in ranked
        if result.Count() >= 36 then exit for
        result.Push(entry.card)
    end for
    return result
end function

' Keep non-ASCII letters intact. ASCII punctuation/control characters and common
' typographic separators become spaces; this does not promise full Unicode NFD.
function SearchQueryContext(query as String) as Object
    separator = CreateObject("roRegex", "([\x00-\x2f\x3a-\x40\x5b-\x60\x7b-\x7f]|–|—|‘|’|“|”|…)+", "")
    text = SearchNormalizeText(query,separator)
    return {text:text,tokens:text.Tokenize(" "),separator:separator,remaining:1024}
end function

function SearchNormalizeText(value as String, separator as Object) as String
    return separator.ReplaceAll(LCase(Left(value.Trim(),120))," ").Trim()
end function

function SearchTitleBucket(title as String, context as Object) as Integer
    text = SearchNormalizeText(title,context.separator)
    bucket = SearchLexicalTitleBucket(text,context)
    if bucket <> 4 then return bucket
    return SearchFuzzyTitleBucket(text,context)
end function

function SearchLexicalTitleBucket(text as String, context as Object) as Integer
    if context.text = "reaper" and text = "reacher" then return -1
    if text = context.text then return 0
    if Left(text,Len(context.text)) = context.text then return 1
    containsAll = true
    for each token in context.tokens
        if Instr(1,text,token) = 0 then containsAll = false
    end for
    if containsAll then return 2
    return 4
end function

function SearchFuzzyTitleBucket(text as String, context as Object) as Integer
    ' Long phrases use lexical matching; typo work stays small on older Rokus.
    if context.tokens.Count() > 8 then return 4
    titleTokens = text.Tokenize(" ")
    for each token in context.tokens
        matches = false
        checked = 0
        for each titleToken in titleTokens
            checked++
            if checked > 16 then exit for
            if titleToken = token or Left(titleToken,Len(token)) = token
                matches = true
                exit for
            end if
            shorter = Len(token)
            if Len(titleToken) < shorter then shorter = Len(titleToken)
            if shorter >= 4 and Len(token) <= 32 and Len(titleToken) <= 32
                maximum = 1
                if shorter >= 7 then maximum = 2
                if Abs(Len(titleToken) - Len(token)) <= maximum and context.remaining > 0
                    context.remaining--
                    if SearchQueryEditDistance(titleToken,token,maximum,context) <= maximum
                        matches = true
                        exit for
                    end if
                end if
            end if
        end for
        if not matches then return 4
    end for
    return 3
end function


' Cache only pure pair distances within one query. Every logical comparison
' still spends the same fuzzy budget in SearchTitleBucket, including hits.
function SearchQueryEditDistance(leftText as String, rightText as String, maximum as Integer, context as Object) as Integer
    if not context.DoesExist("editDistances")
        context["editDistances"] = {}
        context.editDistances.SetModeCaseSensitive()
        context["editDistanceKeys"] = []
    end if
    key = Len(leftText).ToStr() + ":" + leftText + ":" + Len(rightText).ToStr() + ":" + rightText + ":" + maximum.ToStr()
    if context.editDistances.DoesExist(key) then return context.editDistances[key]
    distance = SearchBoundedEditDistance(leftText,rightText,maximum)
    if context.editDistanceKeys.Count() >= 64
        oldest = context.editDistanceKeys.Shift()
        context.editDistances.Delete(oldest)
    end if
    context.editDistances[key] = distance
    context.editDistanceKeys.Push(key)
    return distance
end function

' A narrow dynamic-programming band uses two rows of at most 33 integers.
' Plain Levenshtein preserves the tvOS rule that a transposition costs two.
function SearchBoundedEditDistance(leftText as String, rightText as String, maximum as Integer) as Integer
    if maximum < 0 then maximum = 0
    if maximum > 2 then maximum = 2
    rejected = maximum + 1
    leftLength = Len(leftText)
    rightLength = Len(rightText)
    if leftLength > 32 or rightLength > 32 then return rejected
    if Abs(leftLength - rightLength) > maximum then return rejected
    if leftLength = 0 then return rightLength
    if rightLength = 0 then return leftLength
    previous = []
    current = []
    for column = 0 to rightLength
        distance = column
        if distance > maximum then distance = rejected
        previous.Push(distance)
        current.Push(rejected)
    end for
    for row = 1 to leftLength
        current[0] = rejected
        if row <= maximum then current[0] = row
        firstColumn = row - maximum
        if firstColumn < 1 then firstColumn = 1
        lastColumn = row + maximum
        if lastColumn > rightLength then lastColumn = rightLength
        if firstColumn > 1 then current[firstColumn - 1] = rejected
        if lastColumn < rightLength then current[lastColumn + 1] = rejected
        rowMinimum = current[0]
        for column = firstColumn to lastColumn
            cost = 1
            if Mid(leftText,row,1) = Mid(rightText,column,1) then cost = 0
            distance = previous[column] + 1
            if current[column - 1] + 1 < distance then distance = current[column - 1] + 1
            if previous[column - 1] + cost < distance then distance = previous[column - 1] + cost
            current[column] = distance
            if distance < rowMinimum then rowMinimum = distance
        end for
        if rowMinimum > maximum then return rejected
        saved = previous
        previous = current
        current = saved
    end for
    if previous[rightLength] > maximum then return rejected
    return previous[rightLength]
end function

' The arrival suffix makes equal ranks deterministic on Roku's native SortBy.
' Video kinds lead collections among title matches, then lexical bucket, kind,
' and (for a one-token query only) year. No playback route is inferred here.
function SearchRankKey(card as Object, bucket as Integer, tokenCount as Integer, arrival as Integer) as String
    tier = bucket + 1
    if card.type = "collection" and bucket < 4 then tier = tier + 5
    if bucket = 4 then tier = 10
    kindScore = 4
    if card.type = "season" then kindScore = 3
    if card.type = "episode" then kindScore = 2
    if card.type = "collection" then kindScore = 1
    year = 0
    if tokenCount = 1 and bucket < 4
        year = SearchField(card,"year",0)
        if year < 0 then year = 0
        if year > 9999 then year = 9999
    end if
    priority = tier * 1000000 + (4 - kindScore) * 10000 + 9999 - year
    return Right("00000000" + priority.ToStr(),8) + Right("000" + arrival.ToStr(),3)
end function

' A fresh server copy replaces its cached identity before both lanes are ranked.
' Backend-only metadata hits remain last. The query-free form keeps the prior
' bounded merge contract for callers that do not request lexical ranking.
function SearchMergeResults(local as Dynamic, server as Dynamic, sourceId as String, limit = 100 as Integer, query = "" as String) as Object
    result = []
    fresh = {}
    serverCount = 0
    seen = {}
    if limit < 1 then return result
    if limit > 100 then limit = 100
    if type(server) = "roArray"
        inspected = 0
        for each raw in server
            inspected++
            if inspected > 100 then exit for
            card = SearchIndexCard(raw,sourceId)
            if card <> invalid and not fresh.DoesExist(card.itemId)
                fresh[card.itemId] = raw
                serverCount++
            end if
        end for
    end if
    ranking = query <> ""
    capacity = limit
    if ranking then capacity = 200
    localOnly = 0
    if type(local) = "roArray"
        inspected = 0
        for each raw in local
            inspected++
            if inspected > 100 or result.Count() >= capacity then exit for
            card = SearchIndexCard(raw,sourceId)
            if card <> invalid and not seen.DoesExist(card.itemId)
                seen[card.itemId] = true
                if fresh.DoesExist(card.itemId)
                    result.Push(fresh[card.itemId])
                else if ranking or localOnly < limit - serverCount
                    result.Push(card)
                    localOnly++
                end if
            end if
        end for
    end if
    if type(server) = "roArray"
        inspected = 0
        for each raw in server
            inspected++
            if inspected > 100 or result.Count() >= capacity then exit for
            card = SearchIndexCard(raw,sourceId)
            if card <> invalid and not seen.DoesExist(card.itemId)
                seen[card.itemId] = true
                result.Push(raw)
            end if
        end for
    end if
    if ranking then return SearchRankCards(result,query,sourceId,limit,true,true,200)
    return result
end function

function SearchField(value as Dynamic, field as String, fallback as Dynamic) as Dynamic
    if type(value) <> "roAssociativeArray" then return fallback
    if not value.DoesExist(field) or value[field] = invalid then return fallback
    return value[field]
end function
