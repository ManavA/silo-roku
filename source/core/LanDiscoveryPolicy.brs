' Pure IPv4 discovery policy; callers must confirm identity before authentication.
function LanDnsRecords(packet as Object, sender as String, sourcePort as Integer) as Object
    offers = []
    if sourcePort <> 5353 or not LanDiscoveryPrivate(sender) then return offers
    size = packet.Count()
    if size < 12 or size > 9000 then return offers
    flags = LanDnsWord(packet, 2)
    if (flags and &hF80F) <> &h8000 or (flags and &h0200) <> 0 then return offers
    questions = LanDnsWord(packet, 4)
    count = LanDnsWord(packet, 6) + LanDnsWord(packet, 8) + LanDnsWord(packet, 10)
    if questions > 64 or count > 64 then return offers
    cursor = 12
    for index = 1 to questions
        owner = LanDnsName(packet, cursor)
        if owner = invalid then return offers
        cursor = owner.next + 4
        if cursor > size then return offers
    end for
    records = []
    for index = 1 to count
        owner = LanDnsName(packet, cursor)
        if owner = invalid then return offers
        cursor = owner.next
        if cursor + 10 > size then return offers
        kind = LanDnsWord(packet, cursor)
        class = LanDnsWord(packet, cursor + 2)
        ttl = packet[cursor + 4] * 16777216.0 + packet[cursor + 5] * 65536.0 + packet[cursor + 6] * 256.0 + packet[cursor + 7]
        length = LanDnsWord(packet, cursor + 8)
        cursor = cursor + 10
        finish = cursor + length
        if finish > size then return offers
        rr = {name: owner.name, kind: kind, goodbye: ttl = 0, ttl: ttl, sender: sender, value: invalid}
        if (class and &h7FFF) = 1
            if kind = 12 or kind = 33
                start = cursor
                if kind = 33 then start = start + 6
                if start >= finish then return offers
                target = LanDnsName(packet, start)
                if target = invalid then return offers
                if target.next <> finish then return offers
                rr.value = target.name
                if kind = 33
                    rr.port = LanDnsWord(packet, cursor + 4)
                    if LanDnsWord(packet, cursor) <> 0 or LanDnsWord(packet, cursor + 2) <> 0 then rr.value = invalid
                    if rr.port = 0 then rr.value = invalid
                end if
            else if kind = 16
                rr.value = LanDnsIdentity(packet, cursor, finish)
            else if kind = 1
                if length <> 4 then return offers
                rr.value = StrI(packet[cursor]).Trim() + "." + StrI(packet[cursor + 1]).Trim() + "." + StrI(packet[cursor + 2]).Trim() + "." + StrI(packet[cursor + 3]).Trim()
            end if
            relevant = (kind = 12 and rr.name = "_silo._tcp.local." and rr.value <> invalid)
            if kind = 33 or kind = 16 then relevant = LanDnsInstance(rr.name)
            if kind = 1 then relevant = rr.value = sender and Right(rr.name, 7) = ".local."
            if relevant then records.Push(rr)
        end if
        cursor = finish
    end for
    if cursor <> size then return offers
    return records
end function

function LanDiscoveryPacket(packet as Object, sender as String, sourcePort as Integer) as Object
    return LanDnsCandidates(LanDnsRecords(packet, sender, sourcePort), [])
end function

function LanDnsCandidates(records as Object, conflicts as Object, limit = 16 as Integer) as Object
    offers = []
    for each ptr in records
        if ptr.kind = 12 and not ptr.goodbye and ptr.value <> invalid
            instance = ptr.value
            blocked = false
            for each conflict in conflicts
                if conflict = instance then blocked = true
            end for
            if LanDnsInstance(instance) and not blocked
                srv = LanDnsUnique(records, instance, 33, ptr.sender)
                txt = LanDnsUnique(records, instance, 16, ptr.sender)
                if srv <> invalid and txt <> invalid
                    addr = LanDnsUnique(records, srv.value, 1, ptr.sender)
                    if addr <> invalid
                        offer = {instance: instance, host: srv.value, serverId: txt.value, address: ptr.sender, port: srv.port, goodbye: false}
                        duplicate = false
                        for each prior in offers
                            if prior.instance = instance and prior.address = ptr.sender then duplicate = true
                        end for
                        if not duplicate and offers.Count() < limit then offers.Push(offer)
                    end if
                end if
            end if
        end if
    end for
    return offers
end function

function LanDnsWord(packet as Object, offset as Integer) as Integer
    return packet[offset] * 256 + packet[offset + 1]
end function

function LanDnsName(packet as Object, offset as Integer) as Dynamic
    cursor = offset
    nextOffset = -1
    jumps = 0
    visited = {}
    expanded = 1
    value = ""
    while true
        if cursor < 12 or cursor >= packet.Count() then return invalid
        key = StrI(cursor).Trim()
        if visited.DoesExist(key) then return invalid
        visited[key] = true
        length = packet[cursor]
        if length = 0
            if nextOffset < 0 then nextOffset = cursor + 1
            return {name: value, next: nextOffset}
        else if length >= 192
            if cursor + 1 >= packet.Count() then return invalid
            jumps = jumps + 1
            if jumps > 16 then return invalid
            if nextOffset < 0 then nextOffset = cursor + 2
            cursor = (length - 192) * 256 + packet[cursor + 1]
        else
            if length > 63 or cursor + length >= packet.Count() then return invalid
            expanded = expanded + length + 1
            if expanded > 255 then return invalid
            for index = cursor + 1 to cursor + length
                byte = packet[index]
                if byte = 46 or byte = 92 or byte < 32 or byte > 126
                    value = value + "\" + Right("000" + StrI(byte).Trim(), 3)
                else
                    value = value + LCase(Chr(byte))
                end if
            end for
            value = value + "."
            cursor = cursor + length + 1
        end if
    end while
end function

function LanDnsIdentity(packet as Object, cursor as Integer, finish as Integer) as Dynamic
    version = ""
    identity = ""
    seenVersion = false
    seenIdentity = false
    while cursor < finish
        length = packet[cursor]
        cursor = cursor + 1
        if cursor + length > finish then return invalid
        entry = ""
        for index = cursor to cursor + length - 1
            byte = packet[index]
            if byte < 32 or byte > 126 then return invalid
            entry = entry + Chr(byte)
        end for
        cursor = cursor + length
        if Left(entry, 2) = "v="
            if seenVersion then return invalid
            seenVersion = true
            version = Mid(entry, 3)
        else if Left(entry, 3) = "id="
            if seenIdentity then return invalid
            seenIdentity = true
            identity = Mid(entry, 4)
        end if
    end while
    if version <> "1" or Len(identity) < 1 or Len(identity) > 128 then return invalid
    for index = 1 to Len(identity)
        char = Mid(identity, index, 1)
        if Instr(1, "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_", char) = 0 then return invalid
    end for
    return identity
end function

function LanDnsUnique(records as Object, owner as String, kind as Integer, sender as String) as Dynamic
    found = invalid
    for each rr in records
        if rr.name = owner and rr.kind = kind and rr.sender = sender and not rr.goodbye
            if rr.value = invalid then return invalid
            if found <> invalid
                if rr.value <> found.value or rr.goodbye <> found.goodbye then return invalid
                if kind = 33
                    if rr.port <> found.port then return invalid
                end if
            end if
            found = rr
        end if
    end for
    return found
end function

function LanDnsInstance(value as String) as Boolean
    suffix = "._silo._tcp.local."
    return Len(value) > Len(suffix) and Right(value, Len(suffix)) = suffix
end function

function LanDiscoveryPrivate(address as String) as Boolean
    parts = address.Split(".")
    if parts.Count() <> 4 then return false
    octets = []
    for each part in parts
        if Len(part) = 0 or Len(part) > 3 then return false
        number = Val(part)
        if number < 0 or number > 255 or StrI(number).Trim() <> part then return false
        octets.Push(number)
    end for
    return octets[0] = 10 or (octets[0] = 172 and octets[1] >= 16 and octets[1] <= 31) or (octets[0] = 192 and octets[1] = 168)
end function

function LanDiscoveryCreate(nowMs = 0 as Dynamic) as Object
    return {candidates: [], records: [], conflicts: [], packets: 0, now: nowMs, deadline: nowMs + 5000, closed: false, cancelled: false}
end function

function LanDiscoveryCancel(state as Object) as Object
    return {candidates: [], records: [], conflicts: [], packets: state.packets, now: state.now, deadline: state.deadline, closed: true, cancelled: true}
end function

function LanDiscoveryAdvance(state as Object, nowMs as Dynamic) as Object
    if state.cancelled or nowMs < state.now then return state
    nextState = {candidates: [], records: [], conflicts: [], packets: state.packets, now: nowMs, deadline: state.deadline, closed: state.closed or nowMs >= state.deadline, cancelled: false}
    for each rr in state.records
        if rr.expires > nowMs then nextState.records.Push(rr)
    end for
    for each conflict in state.conflicts
        nextState.conflicts.Push(conflict)
    end for
    nextState.candidates = LanDnsCandidates(nextState.records, nextState.conflicts)
    return nextState
end function

function LanDiscoveryReduce(state as Object, packet as Object, sender as String, sourcePort as Integer, nowMs = 0 as Dynamic) as Object
    if nowMs < state.now then return state
    nextState = LanDiscoveryAdvance(state, nowMs)
    if nextState.closed then return nextState
    nextState.packets = nextState.packets + 1
    for each incoming in LanDnsRecords(packet, sender, sourcePort)
        retained = []
        for each cached in nextState.records
            sameKey = cached.name = incoming.name and cached.kind = incoming.kind and cached.sender = incoming.sender
            if incoming.kind = 12 then sameKey = sameKey and cached.value = incoming.value
            if sameKey
                sameValue = cached.value = incoming.value
                if incoming.kind = 33 then sameValue = sameValue and cached.port = incoming.port
                if incoming.goodbye
                    if not sameValue then retained.Push(cached)
                else
                    if not sameValue then incoming.value = invalid
                end if
            else
                retained.Push(cached)
            end if
        end for
        if not incoming.goodbye
            ' Only expiry within this scan matters; avoid uint32 TTL multiplication.
            lifetime = 6000
            if incoming.ttl < 6 then lifetime = incoming.ttl * 1000
            incoming.expires = nowMs + lifetime
            if retained.Count() < 64 then retained.Push(incoming)
            if incoming.value = invalid and (incoming.kind = 33 or incoming.kind = 16)
                LanDnsBlock(nextState.conflicts, incoming.name)
            end if
        end if
        nextState.records = retained
    end for
    candidates = LanDnsCandidates(nextState.records, nextState.conflicts, 64)
    for each candidate in candidates
        for each other in candidates
            if candidate.instance = other.instance
                if candidate.address <> other.address or candidate.port <> other.port or candidate.serverId <> other.serverId
                    LanDnsBlock(nextState.conflicts, candidate.instance)
                end if
            end if
        end for
    end for
    if nextState.conflicts.Count() >= 16
        nextState.records = []
        nextState.candidates = []
        nextState.closed = true
    else
        nextState.candidates = LanDnsCandidates(nextState.records, nextState.conflicts)
    end if
    if nextState.packets >= 64 then nextState.closed = true
    return nextState
end function

sub LanDnsBlock(conflicts as Object, instance as String)
    for each conflict in conflicts
        if conflict = instance then return
    end for
    if conflicts.Count() < 16 then conflicts.Push(instance)
end sub
