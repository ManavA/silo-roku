"""Single-key inherited settings use the real v2 wire and guarded Scene flow."""
import json
from pathlib import Path
import tempfile
import unittest
from tools.brightscript import run_brightscript
ROOT=Path(__file__).resolve().parents[1]
class SettingsResetTests(unittest.TestCase):
 def test_delete_targets_one_known_key_scope_and_requires_empty_204(self):
  with tempfile.TemporaryDirectory() as d:
   out=run_brightscript([ROOT/'source/adapters/SiloAdapter.brs'],'''
    session={baseUrl:"https://fixture.example",accessToken:"synthetic",profileId:"p",deviceId:"synthetic-device"}
    requests=[]
    for each scope in ["profile","profile_device","profile_client"]
     requests.Push(BuildSiloRequest("settings_reset",session,{key:"playback.subtitle_mode",scope:scope}))
    end for
    invalidRequests=[]
    for each params in [{key:"ui.theme",scope:"profile"},{key:"playback.subtitle_mode",scope:"account"},{key:"playback.subtitle_mode"},{key:"playback.subtitle_mode",scope:"profile",value:"off"},{key:"playback.subtitle_mode",scope:"profile",profile_id:"other"}]
     invalidRequests.Push(BuildSiloRequest("settings_reset",session,params).ok)
    end for
    replies=[]
    for each status in [204,200,202,403]
     replies.Push(DecodeSiloResponse("settings_reset","",{key:"playback.subtitle_mode",scope:"profile",statusCode:status}).ok)
    end for
    bodyReply=DecodeSiloResponse("settings_reset","{}",{key:"playback.subtitle_mode",scope:"profile",statusCode:204}).ok
    print FormatJson({requests:requests,invalid:invalidRequests,replies:replies,bodyReply:bodyReply})
   ''',root=Path(d))
  r=json.loads(out)
  for scope,request in zip(['profile','profile_device','profile_client'],r['requests']):
   self.assertTrue(request['ok']);self.assertEqual(request['method'],'DELETE')
   self.assertEqual(request['url'],'https://fixture.example/api/v2/settings/values/playback.subtitle_mode?scope='+scope)
   self.assertEqual(request['body'],'')
   self.assertEqual(request['headers']['X-Silo-Client-Family'],'tv')
   self.assertEqual(request['headers']['X-Silo-Device-Id'],'synthetic-device')
  self.assertEqual(r['invalid'],[False]*5)
  self.assertEqual(r['replies'],[True,False,False,False]);self.assertFalse(r['bodyReply'])

 def test_worker_uses_transport_receipt_and_preserves_session_owner_fence(self):
  with tempfile.TemporaryDirectory() as d:
   task=Path(d)/'task.brs';task.write_text((ROOT/'components/ApiTask.brs').read_text().replace('CreateObject("roDeviceInfo")','FixtureDevice()'))
   native=Path(d)/'native.brs';native.write_text('''
function SessionRevision(provider)
 return 4
end function
function LoadSession(provider)
 return {baseUrl:"https://fixture.example",accessToken:"synthetic",profileId:"p",sourceId:"silo:fixture"}
end function
function FixtureDevice()
 return {GetChannelClientId:function()
 return "synthetic-device"
 end function,GetModel:function()
 return "fixture"
 end function,GetOSVersion:function()
 return {major:"1",minor:"0",revision:"0"}
 end function}
end function
function HttpRequest(request)
 m.requests.Push(request)
 return m.reply
end function
''')
   http=Path(d)/'http.brs';http.write_text((ROOT/'source/network/Http.brs').read_text().replace('function HttpRequest(', 'function UnusedNativeHttpRequest('))
   out=run_brightscript([ROOT/'source/core/RuntimeIdentity.brs',task,http,ROOT/'source/adapters/SiloAdapter.brs',ROOT/'source/auth/SessionPolicy.brs',native],'''
    m.requests=[]:results=[]
    params={key:"playback.subtitle_mode",scope:"profile_device"}
    owner={sourceId:"silo:fixture",profileId:"p",sessionRevision:4}
    for each action in ["settings_reset","collection_add","collection_remove"]
     actionParams=params
     if action<>"settings_reset" then actionParams={itemId:"movie",collectionId:"list"}
     for each status in [204,200,202,403]
      m.reply={ok:status<>403,statusCode:status,body:"",errorCode:"forbidden"}
      results.Push(ExecuteApiAction("silo",action,actionParams,owner).ok)
     end for
    end for
    created=[]
    for each status in [201,200,204]
     m.reply={ok:true,statusCode:status,body:FormatJson({id:"new",name:"Weekend",creator_profile_id:"p",collection_type:"manual",is_shared:false})}
     created.Push(ExecuteApiAction("silo","collection_create",{name:"Weekend",statusCode:201,profileId:"other"},owner).ok)
    end for
    params.statusCode=204
    m.reply={ok:true,statusCode:200,body:""}
    forged=ExecuteApiAction("silo","settings_reset",params,owner).ok
    stale=ExecuteApiAction("silo","settings_reset",{key:"playback.subtitle_mode",scope:"profile"},{sourceId:"silo:other",profileId:"p",sessionRevision:4}).ok
    print FormatJson({results:results,forged:forged,stale:stale,count:m.requests.Count(),created:created})
   ''',root=Path(d))
  self.assertEqual(json.loads(out),dict(results=[True,False,False,False]*3,forged=False,stale=False,count=15,created=[True,False,False]))

 def scene(self,body):
  with tempfile.TemporaryDirectory() as d:
   settings=Path(d)/'settings.brs';settings.write_text((ROOT/'components/SiloUISettings.brs').read_text().replace('CreateObject("roSGNode", "Dialog")','FixtureDialog()').replace('AppRegistrySection("preferences")','FixtureRegistry()'))
   native=Path(d)/'native.brs';native.write_text('''
function FixtureDialog()
 m.dialogId=m.dialogId+1
 return {id:m.dialogId,observeField:sub(field,handler)
 end sub,isSameNode:function(other)
 return m.id=other.id
 end function}
end function
function FixtureRegistry()
 return m.registry
end function
sub ApiOwned(action,params,purpose,extra,owner)
 m.calls.Push({action:action,params:params,purpose:purpose,extra:extra,owner:owner})
end sub
sub Toast(message)
 m.toasts.Push(message)
end sub
''')
   out=run_brightscript([settings,ROOT/'components/SiloUIOnboarding.brs',ROOT/'components/SiloUIDialogs.brs',ROOT/'components/SiloUIRobustness.brs',ROOT/'source/core/SiloUISettingsPolicy.brs',ROOT/'source/core/SiloUIFormat.brs',ROOT/'source/adapters/SiloAdapter.brs',native],'''
    m.provider="silo":m.sourceId="silo:fixture":m.profileId="p":m.generation=1:m.view="onboarding":m.browseViewToken=2:m.obQrGeneration=3
    m.calls=[]:m.toasts=[]:m.dialogId=0:m.top={}:m.settingsEpoch=4:m.settingsRevision=1:m.settingsScope="profile_device":m.settingsReady=true
    m.settingsScopes=["profile","profile_device","profile_client"]:m.qualityExplicit=true
    m.settingsManifest={definitions:[{key:"playback.preferred_quality",introduced_in:1,persistence:"remote",allowed_scopes:["profile_device"]},{key:"playback.subtitle_mode",introduced_in:1,persistence:"remote",allowed_scopes:["profile_device"]}]}
    m.settingsKeys=["playback.preferred_quality","playback.subtitle_mode"]
    m.localPreferences={quality:"720p",subtitles:"always",autoPlayNext:false}:m.preferences=SiloUISettingsPreferences(m.localPreferences)
    m.registry={values:{appearance:"light",navigation:"rail"},Read:function(key)
     value=m.values[key]
     if value=invalid then return ""
     return value
    end function,Write:sub(key,value)
     m.values[key]=value
    end sub,Flush:sub()
    end sub}
   '''+body,root=Path(d))
  try: return json.loads(out,strict=False)
  except ValueError: raise AssertionError(repr(out))

 def test_real_choice_confirm_receipt_resets_only_key_then_reads_effective(self):
  r=self.scene('''
    choices=SiloUISettingsChoices("quality")
    ObChoose(choices[3])
    before=m.calls.Count():body=m.top.dialog.message
    event={node:m.top.dialog,getRoSGNode:function()
     return m.node
    end function}
    m.top.dialog.buttonSelected=0
    onSiloUISettingsResetConfirm(event)
    onSiloUISettingsResetConfirm(event)
    request=m.calls[0]
    beforeReceipt=m.localPreferences.quality
    receipt=DecodeSiloResponse("settings_reset","",{key:request.params.key,scope:request.params.scope,statusCode:204})
    SiloUISettingsResult("settings_reset",receipt,receipt.data,request.extra)
    fallback=m.preferences.quality
    cached=SiloUISettingsCacheGet(ParseJson(m.registry.values.playbackScopes),m.sourceId,m.profileId)
    SiloUISettingsResult("settings_values",{ok:true},{revision:1,items:[{key:"playback.preferred_quality",value:"1080p",origin:"default"}]},m.settingsEpoch)
    requests=[]
    for each call in m.calls
     requests.Push({action:call.action,params:call.params,owner:{profileId:call.owner.profileId,sourceId:call.owner.sourceId}})
    end for
    print FormatJson({labels:[choices[0].label,choices[2].label,choices[3].label,choices[4].label],before:before,body:body,requests:requests,beforeReceipt:beforeReceipt,fallback:fallback,current:m.preferences.quality,explicit:m.qualityExplicit,cached:cached,appearance:m.registry.values.appearance,navigation:m.registry.values.navigation})
  ''')
  self.assertEqual(r['labels'],['Original','720p','Use inherited value','Back to Settings'])
  self.assertEqual(r['before'],0);self.assertIn('Only this Roku',r['body'])
  self.assertEqual([c['action'] for c in r['requests']],['settings_reset','settings_effective'])
  self.assertEqual(r['requests'][0]['params'],dict(key='playback.preferred_quality',scope='profile_device'))
  self.assertEqual(r['requests'][0]['owner']['profileId'],'p')
  self.assertEqual(r['beforeReceipt'],'720p');self.assertEqual(r['fallback'],'original');self.assertEqual(r['current'],'1080p')
  self.assertFalse(r['explicit']);self.assertFalse(r['cached']['qualityExplicit'])
  self.assertEqual(r['cached']['subtitles'],'always');self.assertFalse(r['cached']['autoPlayNext'])
  self.assertEqual(r['appearance'],'light');self.assertEqual(r['navigation'],'rail')

 def test_reset_is_hidden_without_remote_key_manifest_scope_and_capability(self):
  r=self.scene('''
    counts=[]
    counts.Push(SiloUISettingsChoices("quality").Count())
    counts.Push(SiloUISettingsChoices("preferSdh").Count())
    m.settingsScope="profile_client":counts.Push(SiloUISettingsChoices("quality").Count())
    m.settingsScope="profile_device":m.settingsScopes=["profile"]:counts.Push(SiloUISettingsChoices("quality").Count())
    m.settingsScopes=["profile_device"]:m.settingsReady=false:counts.Push(SiloUISettingsChoices("quality").Count())
    print FormatJson(counts)
  ''')
  self.assertEqual(r,[5,3,4,4,4])

 def test_stale_scope_epoch_profile_visit_emitter_and_cancel_cannot_delete(self):
  r=self.scene('''
    for each change in ["scope","epoch","profile","visit","emitter","cancel"]
     m.settingsScope="profile_device":m.profileId="p":m.settingsEpoch=4:m.obQrGeneration=3
     choices=SiloUISettingsChoices("quality")
     ObChoose(choices[3])
     node=m.top.dialog
     node.buttonSelected=0
     if change="scope" then m.settingsScope="profile"
     if change="epoch" then m.settingsEpoch=5
     if change="profile" then m.profileId="other"
     if change="visit" then m.obQrGeneration=4
     if change="emitter" then node=FixtureDialog()
     if change="cancel" then node.buttonSelected=1
     event={node:node,getRoSGNode:function()
      return m.node
     end function}
     onSiloUISettingsResetConfirm(event)
    end for
    print FormatJson({count:m.calls.Count(),quality:m.localPreferences.quality,explicit:m.qualityExplicit,stored:m.registry.values.playbackScopes<>invalid})
  ''')
  self.assertEqual(r,dict(count=0,quality='720p',explicit=True,stored=False))

 def test_failed_or_wrong_reset_receipt_preserves_cache_and_stale_result_is_ignored(self):
  r=self.scene('''
    for each reply in [{ok:false,data:{}},{ok:true,data:{reset:true,key:"playback.subtitle_mode",scope:"profile_device"}}]
     ObChoose(SiloUISettingsChoices("quality")[3])
     event={node:m.top.dialog,getRoSGNode:function()
      return m.node
     end function}
     m.top.dialog.buttonSelected=0:onSiloUISettingsResetConfirm(event)
     request=m.calls[m.calls.Count()-1]
     SiloUISettingsResult("settings_reset",reply,reply.data,request.extra)
    end for
    ObChoose(SiloUISettingsChoices("quality")[3])
    event={node:m.top.dialog,getRoSGNode:function()
     return m.node
    end function}
    m.top.dialog.buttonSelected=0:onSiloUISettingsResetConfirm(event)
    request=m.calls[m.calls.Count()-1]
    m.profileId="other"
    receipt=DecodeSiloResponse("settings_reset","",{key:request.params.key,scope:request.params.scope,statusCode:204})
    SiloUISettingsResult("settings_reset",receipt,receipt.data,request.extra)
    print FormatJson({count:m.calls.Count(),quality:m.localPreferences.quality,explicit:m.qualityExplicit,stored:m.registry.values.playbackScopes<>invalid,toasts:m.toasts.Count()})
  ''')
  self.assertEqual(r,dict(count=3,quality='720p',explicit=True,stored=False,toasts=2))
