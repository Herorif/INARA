package com.inara.companion

import android.app.Notification
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import org.json.JSONObject
import java.util.UUID

/** New selected events only. Never reads notification actions or sends/dismisses anything. */
class SelectedNotificationListener : NotificationListenerService() {
    private var connected = false
    override fun onListenerConnected() { connected = true }
    override fun onListenerDisconnected() {
        connected = false
        runCatching { NotificationVault(this).stop() }
    }
    override fun onNotificationPosted(sbn: StatusBarNotification) { capture(sbn, "posted") }
    override fun onNotificationRemoved(sbn: StatusBarNotification) { capture(sbn, "removed") }
    private fun capture(sbn: StatusBarNotification, kind: String) {
        if (!BuildConfig.NOTIFICATION_ACCEPTANCE_ENABLED || !connected || sbn.packageName == packageName) return
        runCatching {
            val n = sbn.notification
            if (n.flags and (Notification.FLAG_ONGOING_EVENT or Notification.FLAG_GROUP_SUMMARY) != 0 ||
                n.visibility == Notification.VISIBILITY_SECRET || n.category in listOf(Notification.CATEGORY_CALL, Notification.CATEGORY_ALARM, Notification.CATEGORY_TRANSPORT)) return
            val vault = NotificationVault(this)
            val state = vault.snapshot()
            if (!state.optBoolean("enabled")) return
            val rules = NotificationVault.objects(state.getJSONObject("policy").getJSONArray("rules"))
            if (rules.none { it.getString("package") == sbn.packageName }) return
            val conversation = NotificationVault.digest(sbn.packageName + "\n" + (n.shortcutId ?: sbn.tag ?: "default"))
            val event = JSONObject().put("event_id", UUID.randomUUID().toString())
                .put("source_id", NotificationVault.digest(sbn.key)).put("package", sbn.packageName)
                .put("conversation", conversation).put("timestamp", System.currentTimeMillis() / 1000).put("kind", kind)
            if (kind == "posted" && state.optBoolean("share_text")) {
                event.put("title", redact(n.extras.getCharSequence(Notification.EXTRA_TITLE)?.toString().orEmpty()).take(160))
                event.put("text", redact(n.extras.getCharSequence(Notification.EXTRA_TEXT)?.toString().orEmpty()).take(1000))
            }
            vault.enqueue(event)
        }.onFailure { runCatching { NotificationVault(this).stop() } }
    }
    private fun redact(raw: String): String {
        var text = raw.take(2000).replace(Regex("[\\x00-\\x1f\\x7f]"), " ")
        listOf("(?i)\\b(?:https?://|www\\.)\\S+", "[\\w.+-]+@[\\w.-]+\\.[A-Za-z]{2,}",
            "(?i)\\b(?:bearer\\s+\\S+|(?:password|token|secret|otp|code)\\s*[:=]?\\s*\\S+)",
            "(?<!\\w)\\+?\\d[\\d ()-]{3,}\\d(?!\\w)").forEach { text = text.replace(Regex(it), "[redacted]") }
        return text.trim()
    }
}
