package com.inara.companion

import android.app.NotificationManager
import android.content.ComponentName
import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.security.MessageDigest

/** One cross-instance lock; independent encrypted file/key. No network or idle polling. */
class NotificationVault(private val context: Context) {
    private val storage = DeviceSecurity(context, "notification-queue.enc", "inara-notifications-v1")
    fun access(): Boolean = context.getSystemService(NotificationManager::class.java)
        .isNotificationListenerAccessGranted(ComponentName(context, SelectedNotificationListener::class.java))
    private fun load(): JSONObject {
        val value = storage.read() ?: JSONObject()
        val now = System.currentTimeMillis() / 1000
        if (!BuildConfig.NOTIFICATION_ACCEPTANCE_ENABLED || !access() || now < value.optLong("clock", now) - 30) {
            value.put("enabled", false).put("queue", JSONArray()).put("candidates", JSONArray())
        }
        val policy = value.optJSONObject("policy")
        val ttl = minOf(24, policy?.optInt("retention_hours", 24) ?: 24).coerceIn(1, 24) * 3600L
        value.put("queue", JSONArray(objects(value.optJSONArray("queue")).filter { it.optLong("timestamp") > now - ttl }))
        value.put("clock", now)
        return value
    }
    fun snapshot(): JSONObject = synchronized(lock) { val value = load(); storage.write(value); JSONObject(value.toString()) }
    fun stop() = synchronized(lock) { storage.write(JSONObject().put("enabled", false)) }
    fun forget() = synchronized(lock) { storage.forgetStorage() }
    fun enable(policy: JSONObject, shareText: Boolean) = synchronized(lock) {
        require(BuildConfig.NOTIFICATION_ACCEPTANCE_ENABLED && access() && policy.getBoolean("enabled"))
        require(policy.getJSONArray("rules").length() in 1..16)
        // Explicit review replaces the entire local scope; never migrate an old outbox.
        storage.write(JSONObject().put("enabled", true).put("policy", JSONObject(policy.toString()))
            .put("share_text", shareText && policy.getBoolean("include_text")).put("queue", JSONArray())
            .put("candidates", JSONArray()))
    }
    fun enqueue(event: JSONObject) = synchronized(lock) {
        val value = load()
        if (!value.optBoolean("enabled")) { storage.write(value); return@synchronized }
        val policy = value.getJSONObject("policy")
        val rule = objects(policy.getJSONArray("rules")).firstOrNull { it.getString("package") == event.getString("package") }
            ?: return@synchronized
        val conversation = event.getString("conversation")
        // Conversation discovery stores opaque IDs only, locally; no message snippets.
        val candidate = JSONObject().put("package", event.getString("package")).put("conversation", conversation)
        val candidates = (objects(value.optJSONArray("candidates")) + candidate).distinctBy { it.toString() }.takeLast(32)
        value.put("candidates", JSONArray(candidates))
        val selected = rule.optBoolean("all_conversations") || strings(rule.optJSONArray("conversations")).contains(conversation)
        if (selected) {
            if (!value.optBoolean("share_text") || !policy.optBoolean("include_text")) event.put("title", "").put("text", "")
            val queue = objects(value.optJSONArray("queue"))
            // Backpressure is visible; never silently evict events/tombstones being retried.
            if (queue.size < 100) {
                val sequence = maxOf(value.optLong("sequence") + 1, System.currentTimeMillis())
                event.put("sequence", sequence); value.put("sequence", sequence)
                value.put("queue", JSONArray(queue + event))
            } else value.put("full", true)
        }
        storage.write(value)
    }
    fun batch(remote: JSONObject): JSONObject? = synchronized(lock) {
        val value = load()
        if (!remote.optBoolean("enabled") || remote.optString("revision") != value.optJSONObject("policy")?.optString("revision")) {
            storage.write(JSONObject().put("enabled", false))
            error("Permission changed. Queue discarded. Review and enable again.")
        }
        require(value.optBoolean("enabled")) { "Notification collection is off" }
        storage.write(value)
        val batch = objects(value.optJSONArray("queue")).take(10)
        if (batch.isEmpty()) null else JSONObject().put("revision", remote.getString("revision")).put("events", JSONArray(batch))
    }
    fun acknowledge(revision: String, accepted: List<String>) = synchronized(lock) {
        val value = load()
        if (value.optJSONObject("policy")?.optString("revision") == revision) {
            value.put("queue", JSONArray(objects(value.optJSONArray("queue")).filter { it.getString("event_id") !in accepted }))
            if (value.getJSONArray("queue").length() < 100) value.put("full", false)
            storage.write(value)
        }
    }
    companion object {
        private val lock = Any()
        fun digest(text: String): String = MessageDigest.getInstance("SHA-256").digest(text.toByteArray(Charsets.UTF_8)).joinToString("") { "%02x".format(it.toInt() and 255) }
        fun objects(array: JSONArray?): List<JSONObject> = (0 until (array?.length() ?: 0)).map { array!!.getJSONObject(it) }
        fun strings(array: JSONArray?): List<String> = (0 until (array?.length() ?: 0)).map { array!!.getString(it) }
    }
}
