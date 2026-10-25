' Small immutable local action models. No provider identity reaches native labels.
function DapField(value as Dynamic,key as String,fallback as Dynamic) as Dynamic
    if type(value)<>"roAssociativeArray" then return fallback
    if not value.DoesExist(key) or value[key]=invalid then return fallback
    return value[key]
end function

function DapInteger(value as Dynamic,minimum as Integer,maximum as Integer) as Boolean
    kind=type(value)
    if kind<>"Integer" and kind<>"roInt" and kind<>"roInteger" and kind<>"LongInteger" and kind<>"roLongInteger" and kind<>"Float" and kind<>"roFloat" and kind<>"Double" and kind<>"roDouble" then return false
    return value=value and value>=minimum and value<=maximum and value=Int(value)
end function

function DapString(value as Dynamic) as Boolean
    return type(value)="String" or type(value)="roString"
end function

function DapButtons(raw as Dynamic) as Dynamic
    if type(raw)<>"roArray" then return invalid
    if raw.Count()<1 or raw.Count()>32 then return invalid
    buttons=[]
    for each label in raw
        if not DapString(label) then return invalid
        if Len(label)<1 or Len(label)>80 then return invalid
        if CreateObject("roRegex","[\x00-\x1f\x7f]","").IsMatch(label) then return invalid
        for each existing in buttons
            if existing=label then return invalid
        end for
        buttons.Push(label)
    end for
    return buttons
end function

function DapOwner(raw as Dynamic) as Dynamic
    scopeKey=DapField(raw,"scopeKey",invalid)
    epoch=DapField(raw,"actionEpoch",invalid)
    if not DapString(scopeKey) or not DapInteger(epoch,1,2147483646) then return invalid
    if not CreateObject("roRegex","^detail-[0-9]{1,10}$","").IsMatch(scopeKey) then return invalid
    return {scopeKey:scopeKey,actionEpoch:Int(epoch)}
end function

function DapSameOwner(leftOwner as Dynamic,rightOwner as Dynamic) as Boolean
    left=DapOwner(leftOwner)
    right=DapOwner(rightOwner)
    if left=invalid or right=invalid then return false
    return left.scopeKey=right.scopeKey and left.actionEpoch=right.actionEpoch
end function

function DapSameButtons(leftButtons as Dynamic,rightButtons as Dynamic) as Boolean
    left=DapButtons(leftButtons)
    right=DapButtons(rightButtons)
    if left=invalid or right=invalid then return false
    if left.Count()<>right.Count() then return false
    for index=0 to left.Count()-1
        if left[index]<>right[index] then return false
    end for
    return true
end function

function DapModel(raw as Dynamic) as Dynamic
    owner=DapOwner(DapField(raw,"owner",invalid))
    buttons=DapButtons(DapField(raw,"buttons",invalid))
    if owner=invalid or buttons=invalid then return invalid
    return {owner:owner,buttons:buttons}
end function

function DapSignal(model as Dynamic,capturedOwner as Dynamic,capturedButtons as Dynamic,index as Dynamic) as Dynamic
    if model=invalid or not DapSameOwner(model.owner,capturedOwner) or not DapSameButtons(model.buttons,capturedButtons) then return invalid
    if not DapInteger(index,0,31) then return invalid
    if index>=model.buttons.Count() then return invalid
    return {scopeKey:model.owner.scopeKey,actionEpoch:model.owner.actionEpoch,index:Int(index),action:model.buttons[Int(index)]}
end function
