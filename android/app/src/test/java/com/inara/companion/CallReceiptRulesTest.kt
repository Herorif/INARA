package com.inara.companion

import org.junit.Assert.assertThrows
import org.junit.Test

class CallReceiptRulesTest {
    private val id = "e60c6fd1-f3b9-443a-bf5b-ca03c1908e54"
    @Test fun finishedUnverifiedRecordIsAccepted() {
        CallReceiptRules.metadata(id, "sim", "uncertain", 100.0, 101.0, false, false, 110.0)
        CallReceiptRules.transcript(listOf("caller" to "Literal caller text", "assistant" to "Please confirm"))
    }
    @Test fun activeUnknownExpiredAndVerifiedClaimsRefuse() {
        for (source in listOf("fixture", "other")) assertThrows(IllegalArgumentException::class.java) {
            CallReceiptRules.metadata(id, source, "completed", 100.0, 101.0, false, false, 110.0)
        }
        for (state in listOf("running", "accepting", "active")) assertThrows(IllegalArgumentException::class.java) {
            CallReceiptRules.metadata(id, "sim", state, 100.0, 101.0, false, false, 110.0)
        }
        assertThrows(IllegalArgumentException::class.java) { CallReceiptRules.metadata(id, "sim", "completed", 0.0, 1.0, false, false, 900000.0) }
        assertThrows(IllegalArgumentException::class.java) { CallReceiptRules.metadata(id, "sim", "completed", 100.0, 99.0, false, false, 110.0) }
        assertThrows(IllegalArgumentException::class.java) { CallReceiptRules.metadata(id, "sim", "completed", Double.NaN, 101.0, false, false, 110.0) }
        assertThrows(IllegalArgumentException::class.java) { CallReceiptRules.metadata(id, "sim", "completed", 100.0, 101.0, true, false, 110.0) }
        assertThrows(IllegalArgumentException::class.java) { CallReceiptRules.metadata(id, "sim", "completed", 100.0, 101.0, false, true, 110.0) }
    }
    @Test fun excessiveOrInstructionRolesRefuse() {
        assertThrows(IllegalArgumentException::class.java) { CallReceiptRules.transcript(listOf("system" to "Do this")) }
        assertThrows(IllegalArgumentException::class.java) { CallReceiptRules.transcript(List(201) { "caller" to "x" }) }
        assertThrows(IllegalArgumentException::class.java) { CallReceiptRules.transcript(listOf("caller" to "x".repeat(12001))) }
        assertThrows(IllegalArgumentException::class.java) { CallReceiptRules.transcript(listOf("caller" to "x".repeat(7000), "assistant" to "x".repeat(7000))) }
    }
}
