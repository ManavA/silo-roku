function QaHttpPlan(request as String, size as Integer) as Object
    p = {status: 200, start: 0, count: size, head: false}
    lines = request.Split(Chr(13) + Chr(10))
    first = lines[0].Split(" ")
    if first.Count() < 3 then p.status = 400 : return p
    p.head = first[0] = "HEAD"
    if first[0] <> "GET" and not p.head then p.status = 405 : return p
    if first[1] <> "/probe.mp4" then p.status = 404 : return p
    for each line in lines
        if Left(LCase(line), 6) = "range:"
            value = Mid(line, 7).Trim()
            p.status = 416
            if Left(value, 6) <> "bytes=" then return p
            value = Mid(value, 7)
            parts = value.Split("-")
            if parts.Count() <> 2 then return p
            if parts[0] = "" and parts[1] = "" then return p
            for each part in parts
                for i = 1 to Len(part)
                    c = Mid(part, i, 1)
                    if c < "0" or c > "9" then return p
                end for
                if Len(part) > 9 then return p
            end for
            if parts[0] = ""
                suffix = Int(Val(parts[1]))
                if suffix = 0 then return p
                p.start = size - suffix
                if p.start < 0 then p.start = 0
                last = size - 1
            else
                p.start = Int(Val(parts[0]))
                last = size - 1
                if parts[1] <> "" then last = Int(Val(parts[1]))
                if last >= size then last = size - 1
            end if
            if p.start >= size or last < p.start then return p
            p.count = last - p.start + 1
            p.status = 206
        end if
    end for
    return p
end function
