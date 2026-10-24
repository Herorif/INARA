package com.inara.companion

import org.json.JSONArray
import org.json.JSONObject

/** The paired server supplies literal content, never instructions or actions. */
object CallReceiptJson {
    fun metadata(value: JSONObject) {
        require(value.get("identity_verified") == false && value.get("message_confirmed") == false)
        CallReceiptRules.metadata(value.getString("id"), value.getString("source"), value.getString("state"),
            value.getDouble("started_at"), value.getDouble("finished_at"), false, false, System.currentTimeMillis() / 1000.0)
    }
    fun list(result: JSONObject, project: String): JSONArray {
        boundary(result, project)
        val values = result.getJSONArray("receipts")
        require(values.length() <= 20)
        val ids = mutableSetOf<String>()
        for (index in 0 until values.length()) {
            val item = values.getJSONObject(index)
            metadata(item); require(ids.add(item.getString("id")))
        }
        return values
    }
    fun detail(result: JSONObject, project: String, expectedId: String): JSONObject {
        boundary(result, project)
        val value = result.getJSONObject("receipt")
        metadata(value); require(value.getString("id") == expectedId)
        val transcript = value.getJSONArray("transcript")
        require(transcript.length() <= 200)
        val segments = (0 until transcript.length()).map {
            val segment = transcript.getJSONObject(it)
            require(segment.get("role") is String && segment.get("text") is String)
            segment.getString("role") to segment.getString("text")
        }
        CallReceiptRules.transcript(segments)
        return value
    }
    private fun boundary(value: JSONObject, project: String) {
        require(value.getString("project") == project)
        require(value.get("read_only") == true && value.get("raw_audio_retained") == false)
    }
}
