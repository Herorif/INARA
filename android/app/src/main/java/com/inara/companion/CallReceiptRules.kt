package com.inara.companion

import java.util.UUID

/** Pure protocol rules, also exercised by JVM tests without Android stubs. */
object CallReceiptRules {
    fun metadata(id: String, source: String, state: String, started: Double, finished: Double,
                 identityVerified: Boolean, messageConfirmed: Boolean, now: Double) {
        require(UUID.fromString(id).toString() == id.lowercase())
        require(source in setOf("sim", "whatsapp_personal"))
        require(state in setOf("completed", "interrupted", "failed", "uncertain"))
        require(started.isFinite() && finished.isFinite() && now.isFinite())
        require(started >= now - 7 * 86400 && started <= finished && finished <= now + 30)
        require(!identityVerified && !messageConfirmed)
    }
    fun transcript(segments: List<Pair<String, String>>) {
        require(segments.size <= 200)
        require(segments.all { it.first in setOf("caller", "assistant") && it.second.length <= 12000 })
        require(segments.sumOf { it.second.length } <= 12000)
    }
}
