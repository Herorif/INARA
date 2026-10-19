package com.inara.companion

import org.junit.Assert.assertEquals
import org.junit.Test

class MobileProtocolTest {
    @Test fun utf8PayloadHasStableSigningBytes() {
        val actual = MobileProtocol.signingBytes("/v1/status", "device", "request", 123L, "{\"text\":\"\u4f60\u597d\"}")
        assertEquals("INARA-MOBILE-1\nPOST\n/v1/status\ndevice\nrequest\n123\nac72dedbe8e0d53dda6f5cbfd5e1c9e6f7f8bac70c7423177e450174b1c09d83", String(actual, Charsets.UTF_8))
    }
}
