' Private finite QA. Parses ISO BMFF; copies AC3/EAC3 samples without decoding.
function QaU32(b as Object, p as Integer) as Double
    if p < 0 or p+4 > b.Count() then return -1
    return b[p]*16777216# + b[p+1]*65536# + b[p+2]*256# + b[p+3]
end function
' Byte counts and positions must bypass Int's native Float argument coercion.
function QaByteInteger(value as Double) as Integer
    if value < 0 or value > 2147483647# then return -1
    exact% = value
    if exact% <> value then return -1
    return exact%
end function
function QaU64Small(b as Object, p as Integer) as Double
    if QaU32(b,p) <> 0 then return -1
    return QaU32(b,p+4)
end function
function QaFour(b as Object, p as Integer) as String
    if p < 0 or p+4 > b.Count() then return ""
    return Chr(b[p])+Chr(b[p+1])+Chr(b[p+2])+Chr(b[p+3])
end function
function QaBoxes(b as Object, first as Integer, limit as Integer) as Dynamic
    result = []
    at = first
    while at < limit
        if at+8 > limit then return invalid
        length = QaU32(b,at)
        header = 8
        if length = 1
            length = QaU64Small(b,at+8)
            header = 16
        else if length = 0
            length = limit-at
        end if
        if length < header or length > 25165824 or at+length > limit then return invalid
        last = at+QaByteInteger(length)
        result.Push({kind:QaFour(b,at+4), pos:at, body:at+header, finish:last})
        if result.Count() > 4096 then return invalid
        at = last
    end while
    return result
end function
function QaFind(b as Object, first as Integer, limit as Integer, kind as String) as Dynamic
    boxes = QaBoxes(b,first,limit)
    if boxes = invalid then return invalid
    for each atom in boxes
        if atom.kind = kind then return atom
    end for
    return invalid
end function
function QaAudioTrack(init as Object) as Dynamic
    moov = QaFind(init,0,init.Count(),"moov")
    if moov = invalid then return invalid
    tracks = QaBoxes(init,moov.body,moov.finish)
    if tracks = invalid then return invalid
    for each track in tracks
        if track.kind = "trak"
            mdia = QaFind(init,track.body,track.finish,"mdia")
            if mdia = invalid then return invalid
            handler = QaFind(init,mdia.body,mdia.finish,"hdlr")
            if handler = invalid then return invalid
            if handler.finish-handler.body < 12 then return invalid
            if init[handler.body] <> 0 then return invalid
            if QaFour(init,handler.body+8) = "soun"
                tkhd = QaFind(init,track.body,track.finish,"tkhd")
                mdhd = QaFind(init,mdia.body,mdia.finish,"mdhd")
                minf = QaFind(init,mdia.body,mdia.finish,"minf")
                if tkhd = invalid or mdhd = invalid or minf = invalid then return invalid
                if tkhd.finish-tkhd.body < 16 or mdhd.finish-mdhd.body < 16 then return invalid
                if init[tkhd.body] > 1 or init[mdhd.body] > 1 then return invalid
                if init[tkhd.body] = 1 and tkhd.finish-tkhd.body < 24 then return invalid
                if init[mdhd.body] = 1 and mdhd.finish-mdhd.body < 24 then return invalid
                stbl = QaFind(init,minf.body,minf.finish,"stbl")
                if stbl = invalid then return invalid
                stsd = QaFind(init,stbl.body,stbl.finish,"stsd")
                if stsd = invalid then return invalid
                if stsd.finish-stsd.body < 44 then return invalid
                if init[stsd.body] <> 0 or QaU32(init,stsd.body+4) <> 1 then return invalid
                entryLength = QaU32(init,stsd.body+8)
                if entryLength < 36 or stsd.body+8+entryLength > stsd.finish then return invalid
                codec = QaFour(init,stsd.body+12)
                if codec <> "ec-3" and codec <> "ac-3" then return invalid
                idAt = tkhd.body+12
                scaleAt = mdhd.body+12
                if init[tkhd.body] = 1 then idAt = tkhd.body+20
                if init[mdhd.body] = 1 then scaleAt = mdhd.body+20
                id = QaByteInteger(QaU32(init,idAt))
                scale = QaByteInteger(QaU32(init,scaleAt))
                if id < 1 or scale < 1 then return invalid
                answer = {id:id, scale:scale, duration:0, size:0, codec:codec}
                mvex = QaFind(init,moov.body,moov.finish,"mvex")
                if mvex <> invalid
                    defaults = QaBoxes(init,mvex.body,mvex.finish)
                    if defaults = invalid then return invalid
                    for each entry in defaults
                        if entry.kind = "trex"
                            if entry.finish-entry.body < 24 then return invalid
                            if init[entry.body] <> 0 then return invalid
                            if QaU32(init,entry.body+4) = id
                                answer.duration = QaByteInteger(QaU32(init,entry.body+12))
                                answer.size = QaByteInteger(QaU32(init,entry.body+16))
                            end if
                        end if
                    end for
                end if
                return answer
            end if
        end if
    end for
    return invalid
end function
function QaAudioSamples(init as Object, fragment as Object, fileTop = invalid as Dynamic, origin = 0 as Integer) as Object
    fail = {ok:false}
    if init.Count() > 1048576 or fragment.Count() > 25165824 then return fail
    track = QaAudioTrack(init)
    top = QaBoxes(fragment,0,fragment.Count())
    if track = invalid or top = invalid then return fail
    extents = top
    if fileTop <> invalid then extents = fileTop
    result = {ok:true, timescale:track.scale, trackid:track.id, codec:track.codec, samples:[], bytes:0}
    for each moof in top
        if moof.kind = "moof"
            children = QaBoxes(fragment,moof.body,moof.finish)
            if children = invalid then return fail
            for each traf in children
                if traf.kind = "traf"
                    tfhd = QaFind(fragment,traf.body,traf.finish,"tfhd")
                    if tfhd = invalid then return fail
                    if tfhd.finish-tfhd.body < 8 then return fail
                    if fragment[tfhd.body] <> 0 then return fail
                    if QaU32(fragment,tfhd.body+4) = track.id
                        flags = QaByteInteger(QaU32(fragment,tfhd.body)) and &hffffff
                        cursor = tfhd.body+8
                        base = -1
                        if (flags and 1) <> 0
                            base = QaU64Small(fragment,cursor)
                            cursor += 8
                        else if (flags and &h20000) <> 0
                            base = moof.pos+origin
                        end if
                        if base < 0 then return fail
                        if (flags and 2) <> 0 then cursor += 4
                        duration = track.duration
                        size = track.size
                        if (flags and 8) <> 0
                            duration = QaByteInteger(QaU32(fragment,cursor))
                            cursor += 4
                        end if
                        if (flags and 16) <> 0
                            size = QaByteInteger(QaU32(fragment,cursor))
                            cursor += 4
                        end if
                        if (flags and 32) <> 0 then cursor += 4
                        if cursor > tfhd.finish then return fail
                        tfdt = QaFind(fragment,traf.body,traf.finish,"tfdt")
                        if tfdt = invalid then return fail
                        if tfdt.finish-tfdt.body < 8 then return fail
                        if fragment[tfdt.body] > 1 then return fail
                        if fragment[tfdt.body] = 1 and tfdt.finish-tfdt.body < 12 then return fail
                        decode = QaU32(fragment,tfdt.body+4)
                        if fragment[tfdt.body] = 1 then decode = QaU64Small(fragment,tfdt.body+4)
                        if decode < 0 or decode > 2147483647# then return fail
                        runs = QaBoxes(fragment,traf.body,traf.finish)
                        if runs = invalid then return fail
                        dataAt = -1
                        for each sampleRun in runs
                            if sampleRun.kind = "trun"
                                if sampleRun.finish-sampleRun.body < 8 then return fail
                                if fragment[sampleRun.body] > 1 then return fail
                                f = QaByteInteger(QaU32(fragment,sampleRun.body)) and &hffffff
                                count = QaByteInteger(QaU32(fragment,sampleRun.body+4))
                                if count < 0 or count > 4096 then return fail
                                cursor = sampleRun.body+8
                                if (f and 1) <> 0
                                    offset = QaU32(fragment,cursor)
                                    if offset >= 2147483648# then offset -= 4294967296#
                                    if base+offset < 0 or base+offset > 2147483647# then return fail
                                    dataAt = QaByteInteger(base+offset)
                                    cursor += 4
                                end if
                                if dataAt < 0 then return fail
                                if (f and 4) <> 0 then cursor += 4
                                for n = 1 to count
                                    sampleDuration = duration
                                    sampleSize = size
                                    if (f and &h100) <> 0
                                        sampleDuration = QaByteInteger(QaU32(fragment,cursor))
                                        cursor += 4
                                    end if
                                    if (f and &h200) <> 0
                                        sampleSize = QaByteInteger(QaU32(fragment,cursor))
                                        cursor += 4
                                    end if
                                    if (f and &h400) <> 0 then cursor += 4
                                    composition = 0
                                    if (f and &h800) <> 0
                                        composition = QaU32(fragment,cursor)
                                        if fragment[sampleRun.body] = 1 and composition >= 2147483648# then composition -= 4294967296#
                                        cursor += 4
                                    end if
                                    if cursor > sampleRun.finish or sampleDuration < 1 or sampleSize < 1 or sampleSize > 65500 then return fail
                                    contained = false
                                    for each dataBox in extents
                                        if dataBox.kind = "mdat" and dataAt >= dataBox.body and dataAt+sampleSize <= dataBox.finish then contained = true
                                    end for
                                    if not contained then return fail
                                    if decode+composition < 0 or decode+composition > 2147483647# then return fail
                                    result.samples.Push({offset:dataAt, size:sampleSize, duration:sampleDuration, pts:decode+composition})
                                    if result.samples.Count() > 4096 then return fail
                                    result.bytes += sampleSize
                                    if result.bytes > 4194304 then return fail
                                    dataAt += sampleSize
                                    decode += sampleDuration
                                end for
                            end if
                        end for
                    end if
                end if
            end for
        end if
    end for
    ' A file job aggregates one validated moof at a time; other-track moofs
    ' may be empty here. The job still rejects an empty aggregate.
    if result.samples.Count() = 0 and fileTop = invalid then return fail
    return result
end function
function QaU32Octets(n as Double) as Dynamic
    if n < 0 or n > 4294967295# then return invalid
    bytes = []
    remaining = n
    for each divisor in [16777216#,65536#,256#,1#]
        ' Convert only a byte-sized quotient. Correct any conversion rounding
        ' against the original Double before removing its exact contribution.
        digit% = remaining/divisor
        if digit%*divisor > remaining then digit% -= 1
        if digit% < 0 or digit% > 255 then return invalid
        bytes.Push(digit%)
        remaining -= digit%*divisor
    end for
    if remaining <> 0 then return invalid
    return bytes
end function
sub QaPush32(a as Object, n as Double)
    bytes = QaU32Octets(n)
    if bytes = invalid then return
    for each digit in bytes
        a.Push(digit)
    end for
end sub
sub QaSet32(a as Object, at as Integer, n as Double)
    bytes = QaU32Octets(n)
    if bytes = invalid then return
    for i=0 to 3
        a[at+i] = bytes[i]
    end for
end sub
function QaBox(kind as String, payload as Object) as Object
    atom = CreateObject("roByteArray")
    QaPush32(atom,payload.Count()+8)
    name = CreateObject("roByteArray")
    name.FromAsciiString(kind)
    atom.Append(name)
    atom.Append(payload)
    return atom
end function
function QaMakeMoof(tfhd as Object, tfdt as Object, trun as Object) as Object
    mfhd = CreateObject("roByteArray")
    mfhd.FromHexString("0000000000000001")
    traf = CreateObject("roByteArray")
    traf.Append(QaBox("tfhd",tfhd))
    traf.Append(QaBox("tfdt",tfdt))
    traf.Append(QaBox("trun",trun))
    body = QaBox("mfhd",mfhd)
    body.Append(QaBox("traf",traf))
    return QaBox("moof",body)
end function
function QaAudioFmp4(init as Object, fragment as Object, plan as Object, headersOnly = false as Boolean) as Object
    fail = {ok:false}
    if not plan.ok then return fail
    if plan.samples.Count() = 0 then return fail
    moov = QaFind(init,0,init.Count(),"moov")
    ftyp = QaFind(init,0,init.Count(),"ftyp")
    if moov = invalid or ftyp = invalid then return fail
    children = QaBoxes(init,moov.body,moov.finish)
    if children = invalid then return fail
    movie = CreateObject("roByteArray")
    for each child in children
        keep = true
        if child.kind = "trak"
            tkhd = QaFind(init,child.body,child.finish,"tkhd")
            if tkhd = invalid then return fail
            idAt = tkhd.body+12
            if init[tkhd.body] = 1 then idAt = tkhd.body+20
            keep = QaU32(init,idAt) = plan.trackid
        else if child.kind = "mvex"
            entries = QaBoxes(init,child.body,child.finish)
            if entries = invalid then return fail
            defaults = CreateObject("roByteArray")
            for each entry in entries
                if entry.kind <> "trex" or QaU32(init,entry.body+4) = plan.trackid
                    defaults.Append(init.Slice(entry.pos,entry.finish))
                end if
            end for
            movie.Append(QaBox("mvex",defaults))
            keep = false
        end if
        if keep then movie.Append(init.Slice(child.pos,child.finish))
    end for
    audioInit = init.Slice(ftyp.pos,ftyp.finish)
    audioInit.Append(QaBox("moov",movie))
    tfhd = CreateObject("roByteArray")
    tfhd.FromHexString("00020000")
    QaPush32(tfhd,plan.trackid)
    tfdt = CreateObject("roByteArray")
    tfdt.FromHexString("0100000000000000")
    QaPush32(tfdt,plan.samples[0].pts)
    trun = CreateObject("roByteArray")
    trun.FromHexString("00000301")
    QaPush32(trun,plan.samples.Count())
    QaPush32(trun,0)
    payload = CreateObject("roByteArray")
    nextPts = plan.samples[0].pts
    for each sample in plan.samples
        if sample.pts <> nextPts then return fail
        QaPush32(trun,sample.duration)
        QaPush32(trun,sample.size)
        if not headersOnly then payload.Append(fragment.Slice(sample.offset,sample.offset+sample.size))
        nextPts += sample.duration
    end for
    moof = QaMakeMoof(tfhd,tfdt,trun)
    QaSet32(trun,8,moof.Count()+8)
    audioFragment = QaMakeMoof(tfhd,tfdt,trun)
    if headersOnly
        QaPush32(audioFragment,plan.bytes+8)
        name = CreateObject("roByteArray")
        name.FromAsciiString("mdat")
        audioFragment.Append(name)
    else
        audioFragment.Append(QaBox("mdat",payload))
    end if
    return {ok:true, init:audioInit, fragment:audioFragment}
end function
