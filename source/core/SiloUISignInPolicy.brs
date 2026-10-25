' Saved addresses are origins only: never persist credentials, path tokens or queries.
function SiloUISavedServerAddress(raw as Dynamic) as String
    if type(raw) <> "String" and type(raw) <> "roString" then return ""
    if Len(raw) > 256 then return ""
    pattern = "^https?://([A-Za-z0-9-]+\.)*[A-Za-z0-9-]+(:[0-9]{1,5})?/?$"
    if not CreateObject("roRegex", pattern, "i").IsMatch(raw) then return ""
    if Right(raw,1) = "/" then raw = Left(raw,Len(raw)-1)
    host = Mid(raw,Instr(1,raw,"://")+3)
    colon = Instr(1,host,":")
    if colon > 0
        port = Val(Mid(host,colon+1))
        if port < 1 or port > 65535 then return ""
    end if
    return LCase(raw)
end function

function SiloUISavedServers(raw as Dynamic, newest = "" as String) as Object
    out = []
    candidate = SiloUISavedServerAddress(newest)
    if candidate <> "" then out.Push(candidate)
    if type(raw) <> "roArray" then return out
    for each value in raw
        candidate = SiloUISavedServerAddress(value)
        if candidate <> ""
            duplicate = false
            for each prior in out
                if candidate = prior then duplicate = true
            end for
            if not duplicate and out.Count() < 5 then out.Push(candidate)
        end if
    end for
    return out
end function

' Build the server's code-scoped approval page without putting device or browser
' bearer secrets in the QR. Both v2 and older activation pages accept ?code=.
function SiloUISignInApprovalUri(verificationUri as Dynamic, userCode as Dynamic, completeUri as Dynamic) as String
    if type(verificationUri) <> "String" and type(verificationUri) <> "roString" then return ""
    if not CreateObject("roRegex", "^https?://[A-Za-z0-9.:-]+(/[A-Za-z0-9_./~-]*)?$", "i").IsMatch(verificationUri) then return ""
    if Right(verificationUri,9) <> "/activate" then return verificationUri
    if type(userCode) <> "String" and type(userCode) <> "roString" then return verificationUri
    code = ""
    for index = 1 to Len(userCode)
        character = Mid(userCode,index,1)
        if character <> "-" and character <> " " then code = code + UCase(character)
    end for
    if not CreateObject("roRegex", "^[A-Z0-9]{8}$", "").IsMatch(code) then return verificationUri
    approvalUri = verificationUri + "?code=" + code
    if Len(approvalUri) > 106 then return verificationUri
    if completeUri = approvalUri then return completeUri
    return approvalUri
end function

' Independent QR Model 2 encoder, byte mode, version 5-L, fixed mask 0.
' 108 data bytes / 26 Reed-Solomon bytes in one block. ASCII URI only, <=106 bytes.
function SiloUISignInQr(uri as Dynamic) as Object
    if type(uri) <> "String" and type(uri) <> "roString" then return []
    if Len(uri) > 106 then return []
    base = uri
    question = Instr(1,uri,"?")
    if question > 0
        if not CreateObject("roRegex", "^\?code=[A-Za-z0-9]{8}$", "").IsMatch(Mid(uri,question)) then return []
        base = Left(uri,question-1)
        if Right(base,9) <> "/activate" then return []
    end if
    if not CreateObject("roRegex", "^https?://[A-Za-z0-9.:-]+(/[A-Za-z0-9_./~-]*)?$", "i").IsMatch(base) then return []
    origin = base
    slash = Instr(Instr(1,base,"://")+3,base,"/")
    if slash > 0 then origin = Left(base,slash-1)
    if SiloUISavedServerAddress(origin) = "" then return []
    bits = []
    SiloUIQrBits(bits,4,4)
    SiloUIQrBits(bits,Len(uri),8)
    for i = 1 to Len(uri)
        SiloUIQrBits(bits,Asc(Mid(uri,i,1)),8)
    end for
    for i = 1 to 4
        if bits.Count() < 864 then bits.Push(0)
    end for
    while bits.Count() mod 8 <> 0
        bits.Push(0)
    end while
    data = []
    for i = 0 to bits.Count()-1 step 8
        value = 0
        for j = 0 to 7
            value = value * 2 + bits[i+j]
        end for
        data.Push(value)
    end for
    while data.Count() < 108
        data.Push(236)
        if data.Count() < 108 then data.Push(17)
    end while
    ' Generator polynomial in GF(256), primitive polynomial x^8+x^4+x^3+x^2+1.
    gen = [1]
    root = 1
    for degree = 0 to 25
        nextGen = []
        for i = 0 to gen.Count()
            nextGen.Push(0)
        end for
        for i = 0 to gen.Count()-1
            nextGen[i] = SiloUIQrXor(nextGen[i],gen[i])
            nextGen[i+1] = SiloUIQrXor(nextGen[i+1],SiloUIQrMultiply(gen[i],root))
        end for
        gen = nextGen
        root = SiloUIQrMultiply(root,2)
    end for
    ecc = []
    for i = 0 to 25
        ecc.Push(0)
    end for
    for each value in data
        factor = SiloUIQrXor(value,ecc[0])
        ecc.Shift()
        ecc.Push(0)
        for i = 0 to 25
            ecc[i] = SiloUIQrXor(ecc[i],SiloUIQrMultiply(gen[i+1],factor))
        end for
    end for
    data.Append(ecc)
    bits = []
    for each value in data
        SiloUIQrBits(bits,value,8)
    end for
    matrix = []
    for y = 0 to 36
        row = []
        for x = 0 to 36
            row.Push(-1)
        end for
        matrix.Push(row)
    end for
    SiloUIQrFinder(matrix,0,0)
    SiloUIQrFinder(matrix,30,0)
    SiloUIQrFinder(matrix,0,30)
    for i = 8 to 28
        matrix[6][i] = 1 - (i mod 2)
        matrix[i][6] = 1 - (i mod 2)
    end for
    for y = -2 to 2
        for x = -2 to 2
            distance = Abs(x)
            if Abs(y) > distance then distance = Abs(y)
            value = 1
            if distance = 1 then value = 0
            matrix[30+y][30+x] = value
        end for
    end for
    ' Reserve and set the two format copies (L + mask 0 BCH = 0x77c4).
    for i = 0 to 14
        value = Int(30660 / (2^i)) mod 2
        if i < 6
            matrix[i][8] = value
        else if i < 8
            matrix[i+1][8] = value
        else
            matrix[37-15+i][8] = value
        end if
        if i < 8
            matrix[8][36-i] = value
        else if i < 9
            matrix[8][15-i] = value
        else
            matrix[8][14-i] = value
        end if
    end for
    matrix[29][8] = 1
    index = 0
    upward = true
    right = 36
    while right >= 1
        if right = 6 then right = 5
        for vertical = 0 to 36
            y = vertical
            if upward then y = 36-vertical
            for delta = 0 to 1
                x = right-delta
                if matrix[y][x] = -1
                    value = 0
                    if index < bits.Count() then value = bits[index]
                    index = index + 1
                    if (x+y) mod 2 = 0 then value = 1-value
                    matrix[y][x] = value
                end if
            end for
        end for
        upward = not upward
        right = right - 2
    end while
    return matrix
end function

sub SiloUIQrBits(bits as Object, value as Integer, count as Integer)
    for i = count-1 to 0 step -1
        bits.Push(Int(value / (2^i)) mod 2)
    end for
end sub

function SiloUIQrXor(a as Integer, b as Integer) as Integer
    return (a or b) and not(a and b)
end function

function SiloUIQrMultiply(a as Integer, b as Integer) as Integer
    value = 0
    while b > 0
        if b mod 2 = 1 then value = SiloUIQrXor(value,a)
        b = Int(b/2)
        a = a*2
        if a >= 256 then a = SiloUIQrXor(a,285)
    end while
    return value
end function

sub SiloUIQrFinder(matrix as Object, left as Integer, top as Integer)
    for y = -1 to 7
        for x = -1 to 7
            xx = left+x: yy = top+y
            if xx >= 0 and yy >= 0 and xx < 37 and yy < 37
                value = 0
                if x >= 0 and x <= 6 and y >= 0 and y <= 6
                    if x = 0 or x = 6 or y = 0 or y = 6 or (x >= 2 and x <= 4 and y >= 2 and y <= 4) then value = 1
                end if
                matrix[yy][xx] = value
            end if
        end for
    end for
end sub
