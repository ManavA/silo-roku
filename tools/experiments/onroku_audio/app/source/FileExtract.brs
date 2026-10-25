' Optional file-backed extraction. No listener/scheduler integration; finite mode unchanged.
' One Step performs at most one 64KiB metadata read/parse or 32KiB sample copy.
' Admission limits are experiment policy, not measured device-capacity guarantees.
function QaFileAudioIO() as Object
    return {read:QaFileRead, write:QaFileWrite, remove:QaFileRemove, size:QaFileSize}
end function
function QaFileRead(path as String, at as Integer, count as Integer) as Dynamic
    b = CreateObject("roByteArray")
    if not b.ReadFile(path,at,count) then return invalid
    return b
end function
function QaFileWrite(path as String, b as Object, append as Boolean) as Boolean
    if append then return b.AppendFile(path)
    return b.WriteFile(path)
end function
function QaFileRemove(path as String) as Boolean
    return DeleteFile(path)
end function
function QaFileSize(path as String) as Double
    stat = CreateObject("roFileSystem").Stat(path)
    if stat = invalid then return -1
    if not stat.DoesExist("size") then return -1
    return stat.size
end function
function QaFileAudioStart(init as Object, source as String, target as String, size as Double, diskCap as Double, io = invalid as Dynamic) as Object
    j = {ok:false,done:true,phase:"rejected",owned:false,plan:{ok:false}}
    if io = invalid then io = QaFileAudioIO()
    ' Restrict output ownership to a distinct tmp staging path; source is read-only.
    if Left(target,5) <> "tmp:/" or target = source then return j
    if size < 8 or diskCap < 8 or diskCap > 1073741824# or size > diskCap then return j
    if io.size(source) <> size or io.size(target) >= 0 then return j
    if init.Count() > 1048576 or QaAudioTrack(init) = invalid then return j
    j = {ok:false,done:false,phase:"scan",owned:false,init:init,source:source,target:target,size:size,io:io,at:0,top:[],moofs:[],metadata:0,index:0,part:0,plan:{ok:true,samples:[],bytes:0}}
    return j
end function
sub QaFileAudioCancel(j as Object)
    if j.done then return
    if j.owned
        if not j.io.remove(j.target)
            j.cleanupFailed = true
        end if
        j.owned = false
    end if
    j.ok = false
    j.done = true
    j.phase = "cancelled"
end sub
sub QaFileAudioFail(j as Object)
    QaFileAudioCancel(j)
    j.phase = "failed"
end sub
function QaFileAudioRead(j as Object, at as Integer, count as Integer) as Dynamic
    if at < 0 or count < 1 or count > 65536 or at+count > j.size then return invalid
    b = j.io.read(j.source,at,count)
    if b = invalid then return invalid
    if b.Count() <> count then return invalid
    return b
end function
sub QaFileAudioStep(j as Object)
    if j.done then return
    if j.phase = "scan"
        ' Read 16 bytes only when available; atom length is checked against actual stat.
        count = 16
        if j.size-j.at < 16 then count = Int(j.size-j.at)
        b = QaFileAudioRead(j,j.at,count)
        if b = invalid
            QaFileAudioFail(j)
            return
        end if
        length = QaU32(b,0)
        header = 8
        if length = 1
            length = QaU64Small(b,8)
            header = 16
        else if length = 0
            length = j.size-j.at
        end if
        if length < header or j.at+length > j.size
            QaFileAudioFail(j)
            return
        end if
        atom = {kind:QaFour(b,4),pos:j.at,body:j.at+header,finish:j.at+QaByteInteger(length)}
        j.top.Push(atom)
        if j.top.Count() > 4096
            QaFileAudioFail(j)
            return
        end if
        if atom.kind = "moof"
            j.metadata += length
            if length > 65536 or j.metadata > 1048576
                QaFileAudioFail(j)
                return
            end if
            j.moofs.Push(atom)
        end if
        j.at = atom.finish
        if j.at = j.size
            j.phase = "parse"
            j.index = 0
        end if
        return
    end if
    if j.phase = "parse"
        if j.index < j.moofs.Count()
            atom = j.moofs[j.index]
            b = QaFileAudioRead(j,atom.pos,atom.finish-atom.pos)
            if b = invalid
                QaFileAudioFail(j)
                return
            end if
            plan = QaAudioSamples(j.init,b,j.top,atom.pos)
            if not plan.ok
                QaFileAudioFail(j)
                return
            end if
            if j.plan.samples.Count()+plan.samples.Count() > 4096 or j.plan.bytes+plan.bytes > 4194304
                QaFileAudioFail(j)
                return
            end if
            j.plan.timescale = plan.timescale
            j.plan.trackid = plan.trackid
            j.plan.codec = plan.codec
            j.plan.bytes += plan.bytes
            for each sample in plan.samples
                j.plan.samples.Push(sample)
            end for
            j.index += 1
            return
        end if
        if j.plan.samples.Count() = 0
            QaFileAudioFail(j)
            return
        end if
        empty = CreateObject("roByteArray")
        output = QaAudioFmp4(j.init,empty,j.plan,true)
        if not output.ok
            QaFileAudioFail(j)
            return
        end if
        j.audioInit = output.init
        j.header = output.fragment
        j.phase = "header"
        return
    end if
    if j.phase = "header"
        ' The caller reserves this unique staging path exclusively for this job.
        j.owned = true
        if not j.io.write(j.target,j.header,false)
            QaFileAudioFail(j)
            return
        end if
        j.Delete("header")
        j.phase = "copy"
        j.index = 0
        return
    end if
    if j.phase = "copy"
        sample = j.plan.samples[j.index]
        count = sample.size-j.part
        if count > 32768 then count = 32768
        b = QaFileAudioRead(j,sample.offset+j.part,count)
        if b = invalid
            QaFileAudioFail(j)
            return
        end if
        if not j.io.write(j.target,b,true)
            QaFileAudioFail(j)
            return
        end if
        j.part += count
        if j.part = sample.size
            j.part = 0
            j.index += 1
        end if
        if j.index = j.plan.samples.Count()
            j.done = true
            j.ok = true
            j.phase = "complete"
        end if
    end if
end sub
