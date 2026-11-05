package com.jarvis.companion

import java.security.MessageDigest

object MobileProtocol {
    fun signingBytes(path: String, deviceId: String, requestId: String, timestamp: Long, payload: String): ByteArray {
        val digest = MessageDigest.getInstance("SHA-256").digest(payload.toByteArray(Charsets.UTF_8))
            .joinToString("") { "%02x".format(it.toInt() and 255) }
        return "JARVIS-MOBILE-1\nPOST\n$path\n$deviceId\n$requestId\n$timestamp\n$digest".toByteArray(Charsets.UTF_8)
    }
}
