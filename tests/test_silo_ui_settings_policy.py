import tempfile
from pathlib import Path
import unittest
from tools.brightscript import run_function
ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / 'source/core/SiloUISettingsPolicy.brs'
class SiloUISettingsPolicyTests(unittest.TestCase):
    def call(self, name, *args):
        self.assertTrue(POLICY.exists(), 'settings policy missing')
        with tempfile.TemporaryDirectory() as root:
            return run_function([POLICY], name, list(args), root=Path(root))
    def test_effective_settings_respect_manifest_revision_and_local_fallback(self):
        manifest = {'revision': 3, 'definitions': [
            {'key':'playback.subtitle_mode','introduced_in':1,'persistence':'remote','allowed_scopes':['profile']},
            {'key':'player.passout_threshold','introduced_in':4,'persistence':'remote','allowed_scopes':['profile_device']}]}
        self.assertEqual(self.call('SiloUISettingsKeys', manifest, 3), ['playback.subtitle_mode'])
        self.assertEqual(self.call('SiloUISettingsEffective', {'subtitles':'off','quality':'720p'}, {'items':[{'key':'playback.subtitle_mode','value':'always'}]}), {'subtitles':'always','quality':'720p'})

    def test_subtitle_auto_language_sdh_and_explicit_selection_precedence(self):
        tracks = [{'trackId':'fr','language':'fra','name':'French'}, {'trackId':'sdh','language':'eng','name':'English SDH','caption':True}, {'trackId':'full','language':'eng','name':'English'}, {'trackId':'forced','language':'eng','name':'English Forced'}]
        pref = {'subtitles':'always','subtitleLanguage':'en-US','preferSdh':False}
        self.assertEqual(self.call('SiloUISettingsSelectSubtitle',pref,tracks,''), 'full')
        pref['preferSdh'] = True
        self.assertEqual(self.call('SiloUISettingsSelectSubtitle',pref,tracks,''), 'sdh')
        pref['subtitles'] = 'auto'
        self.assertEqual(self.call('SiloUISettingsSelectSubtitle',pref,tracks,'eng'), 'forced')
        self.assertEqual(self.call('SiloUISettingsSelectSubtitle',pref,tracks,'fra'), 'sdh')
        pref['subtitles'] = 'off'
        self.assertEqual(self.call('SiloUISettingsSelectSubtitle',pref,tracks,'fra'), '')
        self.assertEqual(self.call('SiloUISettingsSelectSubtitle',pref,tracks,'fra','fr'), 'fr')
        self.assertEqual(self.call('SiloUISettingsSelectSubtitle',pref,tracks,'fra','off'), '')

    def test_writes_require_advertised_key_scope_and_supported_revision(self):
        manifest = {'definitions':[{'key':'playback.subtitle_mode','introduced_in':1,'persistence':'remote','allowed_scopes':['profile','profile_device']}]}
        self.assertTrue(self.call('SiloUISettingsCanWrite',manifest,1,'playback.subtitle_mode','profile_device'))
        self.assertFalse(self.call('SiloUISettingsCanWrite',manifest,0,'playback.subtitle_mode','profile_device'))
        self.assertFalse(self.call('SiloUISettingsCanWrite',manifest,1,'playback.subtitle_mode','account'))
        self.assertFalse(self.call('SiloUISettingsCanWrite',manifest,1,'ui.theme','profile'))

    def test_shipping_settings_only_resolve_after_capability_and_manifest(self):
        actual = self.component('SiloUISettings.brs', '''
            m.calls=[]:m.settingsEpoch=2:m.settingsRevision=0:m.settingsKeys=[]:m.settingsManifest={}:m.settingsReady=false
            m.preferences={subtitles:"off"}:m.localPreferences={subtitles:"off"}
            SiloUISettingsResult("settings_caps",{ok:true},{api_version:1,manifest_revision:3,allowed:true,state:"available",scopes:["profile"]},2)
            SiloUISettingsResult("settings_manifest",{ok:true},{revision:3,definitions:[{key:"playback.subtitle_mode",introduced_in:1,persistence:"remote",allowed_scopes:["profile"]}]},2)
            SiloUISettingsResult("settings_values",{ok:true},{revision:3,items:[{key:"playback.subtitle_mode",value:"always"}]},1)
            stale=m.preferences.subtitles
            SiloUISettingsResult("settings_values",{ok:true},{revision:3,items:[{key:"playback.subtitle_mode",value:"always"}]},2)
            print FormatJson({calls:m.calls,stale:stale,current:m.preferences.subtitles})
        ''',helpers='''
            sub Api(action as String, params as Object, purpose as String, extra=invalid as Dynamic, provider="" as String)
                m.calls.Push(action)
            end sub
        ''')
        self.assertEqual(actual, {'calls':['settings_contract','settings_effective'],'stale':'off','current':'always'})

    def test_binge_settings_disable_autoplay_and_bound_still_watching(self):
        self.assertEqual(self.call('SiloUISettingsBinge',{},0), {'autoplay':True,'seconds':10,'ask':False})
        self.assertEqual(self.call('SiloUISettingsBinge',{'autoPlayNext':False,'promptSeconds':30},0), {'autoplay':False,'seconds':30,'ask':False})
        self.assertEqual(self.call('SiloUISettingsBinge',{'stillWatching':3,'promptSeconds':0},3), {'autoplay':True,'seconds':0,'ask':True})
        self.assertFalse(self.call('SiloUISettingsBinge',{'stillWatching':0},100)['ask'])

    def test_shipping_autoplay_respects_disabled_and_still_watching_gate(self):
        actual = self.component('SiloUIPlayer.brs', '''
            m.calls=[]:m.preferences={autoPlayNext:false}:m.bingeAdvances=0:m.view="player"
            PlayerAutoAdvance()
            m.preferences={stillWatching:3}:m.bingeAdvances=3
            PlayerAutoAdvance()
            m.bingeAdvances=2
            PlayerAutoAdvance()
            print FormatJson(m.calls)
        ''', [('PlayerAdvance','sub PlayerAdvance(automatic=false as Boolean)\n m.calls.Push("advance")\nend sub'),('PlayerStillWatching','sub PlayerStillWatching()\n m.calls.Push("ask")\nend sub')])
        self.assertEqual(actual, ['ask','advance'])

    def test_effective_server_quality_keeps_native_supported_quality_fallback(self):
        self.assertEqual(self.call('SiloUISettingsEffective', {'quality':'720p'}, {'items':[{'key':'playback.preferred_quality','value':'1080p'}]})['quality'], '1080p')
        self.assertEqual(self.call('SiloUISettingsEffective', {'quality':'720p'}, {'items':[{'key':'playback.preferred_quality','value':'2160p'}]})['quality'], 'original')

    def test_intro_mode_overrides_legacy_auto_skip_without_enabling_unknown_modes(self):
        self.assertTrue(self.call('SiloUISettingsPreferences', {'autoSkipIntro':False,'introSkipMode':'always'})['autoSkipIntro'])
        self.assertFalse(self.call('SiloUISettingsEffective', {'autoSkipIntro':True}, {'items':[{'key':'playback.intro_skip_mode','value':'never'}]})['autoSkipIntro'])
        self.assertFalse(self.call('SiloUISettingsPreferences', {'autoSkipIntro':False,'introSkipMode':'bogus'})['autoSkipIntro'])

    def test_old_still_watching_dialog_event_cannot_close_new_playback(self):
        actual = self.component('SiloUIPlayer.brs', '''
            m.calls=[]:m.view="player":m.bingeToken=4:m.playToken=4
            m.bingeDialog={isSameNode:function(node)
                return false
            end function}
            oldEvent={getRoSGNode:function()
                return {}
            end function}
            onPlayerStillWatchingClosed(oldEvent)
            print FormatJson({calls:m.calls,dialogPresent:m.bingeDialog<>invalid})
        ''',[('PlayerClose','sub PlayerClose(finished as Boolean, refresh=true as Boolean)\n m.calls.Push("closed")\nend sub')])
        self.assertEqual(actual, {'calls':[],'dialogPresent':True})

    def test_default_effective_quality_does_not_pin_recovery(self):
        actual=self.component('SiloUISettings.brs', '''
            m.settingsEpoch=1:m.settingsRevision=1:m.localPreferences={quality:"original"}:m.qualityExplicit=false
            SiloUISettingsResult("settings_values",{ok:true},{revision:1,items:[{key:"playback.preferred_quality",value:"original",source:"default"}]},1)
            defaultPinned=m.qualityExplicit
            SiloUISettingsResult("settings_values",{ok:true},{revision:1,items:[{key:"playback.preferred_quality",value:"720p",source:"profile_device",scope:"profile_device"}]},1)
            print FormatJson({defaultPinned:defaultPinned,overridePinned:m.qualityExplicit})
        ''')
        self.assertEqual(actual, {'defaultPinned':False,'overridePinned':True})

    def test_offline_new_profile_cache_miss_does_not_inherit_previous_preferences(self):
        import json
        from tools.brightscript import run_brightscript
        with tempfile.TemporaryDirectory() as tmp:
            source=(ROOT/'components/SiloUISettings.brs').read_text().replace('AppRegistrySection("preferences")','FixtureRegistry()')
            fixture=Path(tmp)/'settings.brs';fixture.write_text(source+'''
                function FixtureRegistry() as Object
                    return {Read:function(key)
                        return ""
                    end function}
                end function
                sub Api(action as String,params as Object,purpose as String,extra=invalid as Dynamic)
                end sub
            ''')
            output=run_brightscript([POLICY,fixture],'''
                m.sourceId="silo:synthetic":m.profileId="new-profile"
                m.preferences={quality:"720p",subtitles:"always",subtitleLanguage:"fr",autoPlayNext:false}
                SiloUISettingsLoad()
                print FormatJson(m.preferences)
            ''',root=Path(tmp))
        self.assertEqual(json.loads(output),{'quality':'original','subtitles':'off'})

    def test_scoped_playback_cache_is_bounded_and_does_not_cross_profiles(self):
        rows=[]
        for i in range(8):
            rows=self.call('SiloUISettingsCachePut',rows,'silo:synthetic',str(i),{'quality':'720p','secret':'discard'},True)
        self.assertEqual(len(rows),4)
        self.assertIsNone(self.call('SiloUISettingsCacheGet',rows,'silo:synthetic','0'))
        self.assertIsNone(self.call('SiloUISettingsCacheGet',rows,'silo:other','7'))
        self.assertEqual(self.call('SiloUISettingsCacheGet',rows,'silo:synthetic','7'),{'quality':'720p','subtitles':'off','qualityExplicit':True})

    def test_local_quality_choice_restores_only_its_profile_and_explicit_flag(self):
        import json
        from tools.brightscript import run_brightscript
        with tempfile.TemporaryDirectory() as tmp:
            source=(ROOT/'components/SiloUISettings.brs').read_text().replace('AppRegistrySection("preferences")','FixtureRegistry()')
            fixture=Path(tmp)/'settings.brs';fixture.write_text(source+'''
                function FixtureRegistry() as Object
                    return m.registry
                end function
                sub Api(action as String,params as Object,purpose as String,extra=invalid as Dynamic)
                end sub
            ''')
            output=run_brightscript([POLICY,fixture],'''
                m.cache="":m.provider="silo":m.sourceId="silo:synthetic":m.profileId="one"
                m.registry={Read:function(key)
                    return m.top.cache
                end function,Write:function(key,value)
                    m.top.cache=value
                    return true
                end function,Flush:function()
                    return true
                end function}
                m.registry.top=m
                SiloUISettingsLoad()
                SiloUISettingsChange("quality","720p")
                m.profileId="two":SiloUISettingsLoad()
                other={quality:m.preferences.quality,pinned:m.qualityExplicit}
                m.profileId="one":SiloUISettingsLoad()
                print FormatJson({other:other,own:{quality:m.preferences.quality,pinned:m.qualityExplicit}})
            ''',root=Path(tmp))
        self.assertEqual(json.loads(output),{'other':{'quality':'original','pinned':False},'own':{'quality':'720p','pinned':True}})

    def test_scope_choices_offer_only_capability_and_manifest_supported_destinations(self):
        actual=self.component('SiloUISettings.brs', '''
            m.settingsScopes=["profile","profile_device","profile_client"]:m.settingsRevision=1
            m.settingsManifest={definitions:[{key:"playback.subtitle_mode",introduced_in:1,persistence:"remote",allowed_scopes:["profile_client"]}]}
            print FormatJson(SiloUISettingsScopeChoices())
        ''')
        self.assertEqual(actual,[{'label':'All TVs for this profile','action':'settings_scope_set','scope':'profile_client'},{'label':'Back to Settings','action':'settings'}])

    def test_forced_disabled_filters_always_before_ranking_but_explicit_wins(self):
        tracks=[{'trackId':'forced','language':'eng','name':'English Forced','forced':True}]
        prefs={'subtitles':'always','subtitleLanguage':'en','showForced':False}
        self.assertEqual(self.call('SiloUISettingsSelectSubtitle',prefs,tracks,'eng'),'')
        self.assertEqual(self.call('SiloUISettingsSelectSubtitle',prefs,tracks,'eng','forced'),'forced')
        prefs.update(subtitles='off',showForced=True)
        self.assertEqual(self.call('SiloUISettingsSelectSubtitle',prefs,tracks,'eng'),'forced')

    def test_signout_clears_source_playback_cache_and_legacy_keys_keeps_local_display(self):
        import json
        from tools.brightscript import run_brightscript
        with tempfile.TemporaryDirectory() as tmp:
            source=(ROOT/'components/SiloUISettings.brs').read_text().replace('AppRegistrySection("preferences")','FixtureRegistry()')
            fixture=Path(tmp)/'settings.brs';fixture.write_text(source+'''
                function FixtureRegistry() as Object
                    return m.registry
                end function
            ''')
            output=run_brightscript([POLICY,fixture],'''
                m.provider="silo":m.sourceId="silo:synthetic":m.profileId="one"
                m.store={appearance:"glass",navigation:"left",silo:"legacy","silo.qualityExplicit":"1","playback.legacy":"old"}
                rows=SiloUISettingsCachePut([],m.sourceId,"one",{quality:"720p"},true)
                rows=SiloUISettingsCachePut(rows,"silo:other","two",{quality:"1080p"},true)
                m.store["playbackScopes"]=FormatJson(rows)
                m.registry={Read:function(key)
                    return m.top.store[key]
                end function,Write:function(key,value)
                    m.top.store[key]=value
                    return true
                end function,Delete:function(key)
                    m.top.store.Delete(key)
                    return true
                end function,GetKeyList:function()
                    return m.top.store.Keys()
                end function,Flush:function()
                    return true
                end function}
                m.registry.top=m
                SiloUISettingsClearSignout()
                rows=ParseJson(m.store["playbackScopes"])
                m.store.Delete("playbackScopes")
                print FormatJson({store:m.store,own:SiloUISettingsCacheGet(rows,"silo:synthetic","one"),other:SiloUISettingsCacheGet(rows,"silo:other","two")})
            ''',root=Path(tmp))
        self.assertEqual(json.loads(output),{'store':{'appearance':'glass','navigation':'left'},'own':None,'other':{'quality':'1080p','subtitles':'off','qualityExplicit':True}})

    def test_preferences_validate_whitelist_and_ignore_secrets(self):
        self.assertEqual(self.call('SiloUISettingsPreferences', {'quality':'bogus','subtitles':'bogus','pin':'1234'}), {'quality':'original','subtitles':'off'})
        self.assertEqual(self.call('SiloUISettingsPreferences', {'quality':'1080p','subtitles':'forced'}), {'quality':'1080p','subtitles':'forced'})
    def test_subtitle_defaults_do_not_enable_nonforced_tracks(self):
        tracks = [{'trackId':'a','label':'English'},{'trackId':'b','label':'English (Forced)'}]
        self.assertEqual(self.call('SiloUISettingsSubtitle', 'forced', tracks), 'b')
        self.assertEqual(self.call('SiloUISettingsSubtitle', 'forced', tracks[:1]), '')
        self.assertEqual(self.call('SiloUISettingsSubtitle', 'on', tracks), 'a')
        self.assertEqual(self.call('SiloUISettingsSubtitle', 'off', tracks), '')
    def test_native_forced_flag_and_missing_inventory(self):
        self.assertEqual(self.call('SiloUISettingsSubtitle','forced',[{'trackId':'a','forced':True}]), 'a')
        self.assertEqual(self.call('SiloUISettingsSubtitle','on',None), '')
    def test_wiring_guards_pin_quality_and_avatar(self):
        onboarding = (ROOT/'components/SiloUIOnboarding.brs').read_text()
        player = (ROOT/'components/SiloUIPlayer.brs').read_text()
        scene = (ROOT/'components/SiloUIScene.brs').read_text()
        self.assertIn('keyboard.textEditBox.secureMode = true', onboarding)
        self.assertIn('Api("profile_verify"', onboarding)
        self.assertIn('if choice.profile.hasPin = true', onboarding)
        self.assertIn('SiloUISettingsPreferences(m.preferences).quality', player)
        self.assertIn('SiloUISettingsPlayback(m.provider, m.preferences)', player)
        self.assertIn('if m.zone = "avatar"', scene)
        self.assertIn('m.preferences = SiloUISettingsPreferences', onboarding)
    def test_quality_mapping_caps_plex_only_when_requested(self):
        self.assertEqual(self.call('SiloUISettingsPlayback','plex',{'quality':'original'}), {'qualityPreference':'original'})
        self.assertEqual(self.call('SiloUISettingsPlayback','plex',{'quality':'720p'}), {'qualityPreference':'720p','maxVideoBitrate':4000,'videoResolution':'1280x720'})
        self.assertEqual(self.call('SiloUISettingsPlayback','silo',{'quality':'1080p'}), {'qualityPreference':'1080p'})
    def component(self, component, body, replacements=(), helpers=''):
        import re, json
        from tools.brightscript import run_brightscript
        with tempfile.TemporaryDirectory() as root:
            source = (ROOT/'components'/component).read_text()
            if component == 'SiloUIOnboarding.brs':
                player = (ROOT/'components/SiloUIPlayer.brs').read_text()
                source += '\n' + re.search(r'(?ms)^sub PlayerCloseTracks\(.*?^end sub', player).group(0)
            # Keep the real admission predicate in component-only fixtures;
            # full Scene tests exercise its modal and ownership integration.
            if component == 'SiloUIPlayer.brs':
                robustness = (ROOT/'components/SiloUIRobustness.brs').read_text()
                source += '\n' + re.search(r'(?ms)^function SiloUIPlaybackAdmissionBlocked\(.*?^end function', robustness).group(0)
            if component == 'SiloUIScene.brs':
                source += '\n' + (ROOT/'components/SiloUIAccessibility.brs').read_text()
                onboarding = (ROOT/'components/SiloUIOnboarding.brs').read_text()
                player = (ROOT/'components/SiloUIPlayer.brs').read_text()
                source += '\n' + re.search(r'(?ms)^sub OnboardingProfileMenu\(.*?^end sub', onboarding).group(0)
                source += '\n' + re.search(r'(?ms)^function PlayerFailureBack\(.*?^end function', player).group(0)
            for name, replacement in replacements:
                source = re.sub(r'(?:sub|function) '+name+r'\(.*?\nend (?:sub|function)', replacement, source, count=1, flags=re.S)
            fixture = Path(root)/'fixture.brs'
            fixture.write_text(source+'\n'+helpers+'\nfunction SiloUIBeginTransition(choice as Object) as Boolean\n return false\nend function\nsub SiloUIMemoryPressure()\n PlayerDiscardPrebuffer()\nend sub')
            return json.loads(run_brightscript([POLICY,ROOT/'components/SiloUISubtitleArtifact.brs',ROOT/'source/core/SiloUIFormat.brs',ROOT/'source/core/TrackPreference.brs',ROOT/'components/SiloUIDetail.brs',fixture],body,root=Path(root)).splitlines()[-1])
    def test_new_silo_login_requests_server_address_before_network(self):
        actual = self.component('SiloUIOnboarding.brs', '''
            m.calls=[] : m.pollTimer={control:"start"}
            ObStartSilo()
            print FormatJson({calls:m.calls,mode:m.obMode})
        ''', [('ObScreen','sub ObScreen(a as String,b as String,c as String,d as String,e as Object)\nend sub'),
              ('ObServerAddressDialog','sub ObServerAddressDialog()\n m.calls.Push("address")\nend sub')], '''
            sub Api(action as String, params as Object, purpose as String, extra=invalid as Dynamic, provider="" as String)
                m.calls.Push(action)
            end sub
        ''')
        self.assertEqual(actual, {'calls':['address'],'mode':''})

    def test_server_dialog_submits_only_the_entered_address_and_clears(self):
        actual = self.component('SiloUIOnboarding.brs', '''
            m.calls=[] : m.obServerDialog={buttonSelected:0,text:"  https://silo.example  "}
            dialog=m.obServerDialog
            onObServerSelected()
            print FormatJson({calls:m.calls,closed:dialog.close,cleared:m.obServerDialog=invalid,text:dialog.text})
        ''', [('ObScreen','sub ObScreen(a as String,b as String,c as String,d as String,e as Object)\nend sub')], '''
            sub Api(action as String, params as Object, purpose as String, extra=invalid as Dynamic, provider="" as String)
                m.calls.Push({action:action,url:params.baseUrl,purpose:purpose,provider:provider})
            end sub
        ''')
        self.assertEqual(actual, {'calls':[{'action':'set_server','url':'https://silo.example','purpose':'ob_server','provider':'silo'}], 'closed':True,'cleared':True,'text':''})

    def test_canceling_server_entry_does_not_mutate_session(self):
        actual = self.component('SiloUIOnboarding.brs', '''
            m.calls=[] : m.obServerDialog={buttonSelected:1,text:"https://silo.example"}
            dialog=m.obServerDialog
            onObServerSelected()
            print FormatJson({calls:m.calls,closed:dialog.close,cleared:m.obServerDialog=invalid,text:dialog.text})
        ''', helpers='''
            sub Api(action as String, params as Object, purpose as String, extra=invalid as Dynamic, provider="" as String)
                m.calls.Push(action)
            end sub
        ''')
        self.assertEqual(actual, {'calls':[],'closed':True,'cleared':True,'text':''})

    def test_empty_server_address_keeps_dialog_open_without_request(self):
        actual = self.component('SiloUIOnboarding.brs', '''
            m.calls=[] : m.obServerDialog={buttonSelected:0,text:"   ",close:false}
            onObServerSelected()
            print FormatJson({calls:m.calls,closed:m.obServerDialog.close})
        ''', helpers='''
            sub Toast(message as String)
                m.calls.Push("validation")
            end sub
            sub Api(action as String, params as Object, purpose as String, extra=invalid as Dynamic, provider="" as String)
                m.calls.Push(action)
            end sub
        ''')
        self.assertEqual(actual, {'calls':['validation'],'closed':False})

    def test_refresh_code_reuses_the_chosen_server(self):
        actual = self.component('SiloUIOnboarding.brs', '''
            m.calls=[] : m.obBusy=false : m.obServerUrl="https://silo.example"
            ObChoose({action:"silo_code"})
            print FormatJson(m.calls)
        ''', [('ObScreen','sub ObScreen(a as String,b as String,c as String,d as String,e as Object)\nend sub')], '''
            sub Api(action as String, params as Object, purpose as String, extra=invalid as Dynamic, provider="" as String)
                m.calls.Push({action:action,url:params.baseUrl})
            end sub
        ''')
        self.assertEqual(actual, [{'action':'set_server','url':'https://silo.example'}])

    def test_profile_pin_and_unprotected_selection_take_distinct_paths(self):
        actual = self.component('SiloUIOnboarding.brs','''
            m.calls=[] : m.sourceId="source" : m.profileId="old"
            ObChoose({action:"profile",profile:{profileId:"locked",name:"Locked",hasPin:true}})
            ObChoose({action:"profile",profile:{profileId:"open",name:"Open",hasPin:false}})
            print FormatJson({calls:m.calls,profile:m.profileId})
        ''', [('ObProfilePin','sub ObProfilePin(profile as Object)\n m.calls.Push("keyboard")\nend sub'),
              ('ObResetScope','sub ObResetScope()\n m.calls.Push("reset")\nend sub')], '''
            sub Api(action as String, params as Object, purpose as String, extra=invalid as Dynamic, provider="" as String)
                m.calls.Push(action)
            end sub
        ''')
        self.assertEqual(actual, {'calls':['keyboard','reset','select_profile'],'profile':'old'})
    def test_pin_submit_erases_dialog_and_verification_is_atomic(self):
        actual = self.component('SiloUIOnboarding.brs','''
            m.calls=[] : m.obPinProfile={profileId:"p",name:"Profile"}
            m.obPinDialog={buttonSelected:0,text:"0000"}
            dialog=m.obPinDialog
            onObPinSelected()
            OnboardingResult("ob_profile_set",{ok:true},{profileId:"p"},invalid)
            print FormatJson({calls:m.calls,text:dialog.text,closed:dialog.close,cleared:m.obPinProfile=invalid})
        ''', [('ObResetScope','sub ObResetScope()\n m.calls.Push("reset")\nend sub')], '''
            sub Api(action as String, params as Object, purpose as String, extra=invalid as Dynamic, provider="" as String)
                m.calls.Push(action)
            end sub
            sub EnterSource(provider as String, status as Object)
                m.calls.Push("entered")
            end sub
        ''')
        self.assertEqual(actual, {'calls':['reset','profile_verify','entered'],'text':'','closed':True,'cleared':True})
    def test_forced_default_and_explicit_off_session_precedence(self):
        actual = self.component('SiloUIPlayer.brs','''
            m.view="player" : m.playPlan={} : m.preferences={subtitles:"forced"} : m.trackPref={}
            m.video={availableAudioTracks:[],availableSubtitleTracks:[{TrackName:"full",Description:"English",Language:"eng"}]}
            onPlayerTracks()
            fullMode=m.video.globalCaptionMode
            m.video.availableSubtitleTracks.Push({TrackName:"forced",Description:"English (Forced)",Language:"eng"})
            onPlayerTracks()
            forced=m.video.subtitleTrack : forcedMode=m.video.globalCaptionMode
            m.trackPref.subtitle="off"
            onPlayerTracks()
            print FormatJson([fullMode,forced,forcedMode,m.video.globalCaptionMode])
        ''')
        self.assertEqual(actual, ['Off','forced','On','Off'])
    def test_avatar_reachable_from_nav_and_back_returns_to_nav(self):
        actual=self.component('SiloUIScene.brs','''
            m.view="home" : m.zone="nav" : m.pillGroups={nav:{index:0}} : m.provider="silo":m.top={dialog:invalid}
            onKeyEvent("left",true)
            first=m.zone
            onKeyEvent("OK",true)
            onKeyEvent("back",true)
            print FormatJson([first,m.action,m.zone])
        ''', [('SetZone','sub SetZone(zone as String)\n m.zone=zone\nend sub')], '''
            sub ObScreen(eyebrow as String,title as String,body as String,code as String,choices as Object)
                m.action=choices[0].action
            end sub
        ''')
        self.assertEqual(actual,['avatar','switch_profile','nav'])
    def test_collapsed_sidebar_profile_glyph_opens_profile_picker(self):
        actual=self.component('SiloUINavigation.brs','''
            m.navigationMode="left":m.view="home":m.zone="nav":m.drawerOpen=false:m.provider="silo"
            handled=SiloUINavigationKey("OK")
            print FormatJson([handled,m.action,m.drawerOpen])
        ''', helpers='''
            sub ObChoose(choice as Object)
                m.action=choice.action
            end sub
        ''')
        self.assertEqual(actual,[True,'switch_profile',False])
    def test_back_from_preference_returns_settings_before_home(self):
        actual=self.component('SiloUIOnboarding.brs','''
            m.obPage="preference" : m.obSwitching=false
            handled=OnboardingKey("back")
            print FormatJson([handled,m.obPage])
        ''',[('OnboardingSettings','sub OnboardingSettings()\n m.obPage="settings"\nend sub')])
        self.assertEqual(actual,[True,'settings'])
    def test_busy_profile_switch_rejects_repeated_selection_and_back(self):
        actual=self.component('SiloUIOnboarding.brs','''
            m.calls=[] : m.obBusy=false
            profile={action:"profile",profile:{profileId:"open",name:"Open",hasPin:false}}
            ObChoose(profile)
            ObChoose(profile)
            ObChoose({action:"sources"})
            handled=OnboardingKey("back")
            print FormatJson({calls:m.calls,handled:handled,busy:m.obBusy})
        ''',[('ObResetScope','sub ObResetScope()\n m.calls.Push("reset")\nend sub')],'''
            sub Api(action as String, params as Object, purpose as String, extra=invalid as Dynamic, provider="" as String)
                m.calls.Push(action)
            end sub
        ''')
        self.assertEqual(actual,{'calls':['reset','select_profile'],'handled':True,'busy':True})
    def test_explicit_forced_lane_survives_inventory_event_with_same_language(self):
        actual=self.component('SiloUIPlayer.brs','''
            m.view="player" : m.playPlan={} : m.preferences={subtitles:"on"} : m.trackPref={}
            m.video={setFocus:sub(focused)
            end sub, availableAudioTracks:[],availableSubtitleTracks:[{TrackName:"full",Description:"English",Language:"eng"},{TrackName:"forced",Description:"English (Forced)",Language:"eng"}]}
            m.trackDialog={visible:true} : m.trackList={itemSelected:0}
            m.trackChoices=[{kind:"subtitle",trackId:"forced",language:"eng",name:"English (Forced)"}]
            onPlayerTrackChoice()
            onPlayerTracks()
            print FormatJson([m.video.subtitleTrack,m.video.globalCaptionMode])
        ''')
        self.assertEqual(actual,['forced','On'])
    def test_scope_reset_releases_prebuffer_before_generation_changes(self):
        actual=self.component('SiloUIOnboarding.brs','''
            m.calls=[] : m.generation=4 : m.sourceId="old-source" : m.profileId="old-profile"
            m.searchTimer={control:"start"} : m.keyboard={text:"old query"}
            ObResetScope()
            print FormatJson({calls:m.calls,generation:m.generation,source:m.sourceId,profile:m.profileId,rows:m.homeRows,episodes:m.detailEpisodes,query:m.keyboard.text,timer:m.searchTimer.control})
        ''',helpers='''
            sub HomeCacheRetire()
            end sub
            sub PlayerDiscardPrebuffer()
                m.calls.Push({action:"release",source:m.sourceId,profile:m.profileId,generation:m.generation})
            end sub
            sub PlexClearImages()
                m.calls.Push({action:"clear",generation:m.generation})
            end sub
        ''')
        self.assertEqual(actual,{'calls':[{'action':'release','source':'old-source','profile':'old-profile','generation':4},{'action':'clear','generation':4}],'generation':5,'source':'old-source','profile':'old-profile','rows':[],'episodes':[],'query':'','timer':'stop'})
