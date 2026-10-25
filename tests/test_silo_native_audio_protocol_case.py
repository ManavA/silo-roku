"""Adapter-accepted HLS spelling must reach delivered-audio device validation."""
import unittest
from tests import test_silo_native_audio_channel_receipt as receipts


class NativeAudioProtocolCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        receipts.NativeAudioChannelReceipt.setUpClass()

    def test_uppercase_hls_cannot_bypass_exact_negative_ac3_six_output(self):
        def uppercase(wire,decision):
            decision['playback_plan']['stream']['protocol']='HLS'
        answer='return {result:format.chcnt=invalid and format.codec="ac3" and format.passthru=0}'
        bridge=receipts.NativeAudioChannelReceipt()
        result=bridge.receipt(answer,mutate=uppercase)
        bridge.assert_owned_refusal(result)
