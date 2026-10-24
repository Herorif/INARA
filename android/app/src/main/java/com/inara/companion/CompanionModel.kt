package com.inara.companion

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import org.json.JSONArray
import org.json.JSONObject
import java.security.MessageDigest
import java.util.UUID

data class CompanionState(
    val phase: String = "unpaired", val busy: Boolean = false, val message: String = "Import an invitation from your laptop.",
    val project: String = "", val fingerprint: String = "", val grants: List<String> = emptyList(),
    val jobs: List<JSONObject> = emptyList(), val messages: List<Pair<String, String>> = emptyList(),
    val draft: String = "", val pending: Boolean = false, val preview: JSONObject? = null,
    val notificationState: JSONObject? = null, val notificationPolicy: JSONObject? = null,
    val recoveryRequired: Boolean = false,
    val callReceipts: List<JSONObject> = emptyList(), val callReceipt: JSONObject? = null,
    val callsSyncedAt: Long = 0
)

class CompanionModel(application: Application) : AndroidViewModel(application) {
    private val security = DeviceSecurity(application)
    private val client = CompanionClient(security)
    private val notifications = NotificationVault(application)
    private var reviewedNotificationPolicy: JSONObject? = null
    private val mutable = MutableStateFlow(CompanionState())
    val state = mutable.asStateFlow()
    private var saved = JSONObject()
    private var work: Job? = null
    private var draftSave: Job? = null
    init {
        try {
            saved = security.read() ?: JSONObject()
            if (saved.has("pending")) saved.getJSONObject("pending").put("state", "uncertain")
            publish("Saved link restored. Refresh the laptop; unfinished messages are never auto-sent.")
        } catch (_: Exception) {
            mutable.value = CompanionState(message = "Protected state could not be unlocked. Existing data is preserved; forget this link explicitly to recover.", recoveryRequired = true)
        }
    }
    private fun jsonList(array: JSONArray?): List<JSONObject> = (0 until (array?.length() ?: 0)).map { array!!.getJSONObject(it) }
    private fun publish(message: String, busy: Boolean = false, preview: JSONObject? = null, persist: Boolean = true) {
        val link = saved.optJSONObject("link")
        val grants = saved.optJSONArray("grants") ?: JSONArray()
        val now = System.currentTimeMillis() / 1000
        val canReadCalls = (0 until grants.length()).any { grants.getString(it) == "calls:read" } && saved.optLong("expires") > now
        if (!canReadCalls) clearCalls()
        else {
            try {
                val old = saved.optJSONArray("call_receipts") ?: JSONArray()
                val retained = JSONArray()
                for (index in 0 until old.length()) {
                    val item = old.getJSONObject(index)
                    if (item.getDouble("started_at") >= now - 7 * 86400) { CallReceiptJson.metadata(item); retained.put(item) }
                }
                require(retained.length() <= 20)
                saved.put("call_receipts", retained)
                saved.optJSONObject("call_receipt")?.let { item ->
                    if (item.getDouble("started_at") < now - 7 * 86400) saved.remove("call_receipt")
                    else CallReceiptJson.detail(JSONObject().put("project", saved.optString("project")).put("read_only", true)
                        .put("raw_audio_retained", false).put("receipt", item), saved.optString("project"), item.getString("id"))
                }
            } catch (_: Exception) { clearCalls() }
        }
        mutable.value = CompanionState(
            phase = saved.optString("phase", "unpaired"), busy = busy, message = message,
            project = saved.optString("project"), fingerprint = saved.optString("fingerprint"),
            grants = (0 until grants.length()).map { grants.getString(it) }, jobs = jsonList(saved.optJSONArray("jobs")),
            messages = jsonList(saved.optJSONArray("messages")).map { it.getString("sender") to it.getString("text") },
            draft = saved.optString("draft"), pending = saved.has("pending"), preview = preview,
            notificationState = if (link != null) notifications.snapshot() else null, notificationPolicy = reviewedNotificationPolicy,
            callReceipts = jsonList(saved.optJSONArray("call_receipts")), callReceipt = saved.optJSONObject("call_receipt"),
            callsSyncedAt = saved.optLong("calls_synced_at")
        )
        if (link != null && persist) security.write(saved)
    }
    private fun clearCalls() {
        saved.remove("call_receipts"); saved.remove("call_receipt"); saved.remove("calls_synced_at")
    }
    private fun action(block: suspend () -> Unit) {
        if (work?.isActive == true || state.value.recoveryRequired) return
        work = viewModelScope.launch {
            publish("Connecting to your paired laptop…", true)
            try { block() }
            catch (cancelled: CancellationException) { throw cancelled }
            catch (failure: MobileFailure) {
                if (failure.code.startsWith("notification_")) { notifications.stop(); reviewedNotificationPolicy = null }
                if (failure.code in listOf("mobile_auth", "mobile_owner", "mobile_scope", "mobile_grant")) {
                    notifications.stop(); reviewedNotificationPolicy = null
                    saved.put("phase", "access_blocked").put("grants", JSONArray()).put("jobs", JSONArray()).put("messages", JSONArray()).put("draft", "")
                }
                publish(failure.message ?: "Mobile authorization changed.")
            }
            catch (_: Exception) { publish("Laptop unavailable or authorization changed. Check the link, refresh, or create a new pairing. Unfinished messages are preserved.") }
        }
    }
    private suspend fun request(operation: String, body: JSONObject = JSONObject()): JSONObject {
        val link = saved.getJSONObject("link")
        return withContext(Dispatchers.IO) { client.request(link, operation, body) }
    }
    fun importInvitation(raw: String) = action {
        require(!saved.has("link")) { "Forget the existing link first" }
        require(raw.toByteArray(Charsets.UTF_8).size <= 8192)
        val invite = JSONObject(raw)
        require(invite.getInt("version") == 1 && invite.getLong("expires") > System.currentTimeMillis() / 1000)
        require(invite.getString("secret").matches(Regex("[A-Za-z0-9_-]{43}")))
        val public = withContext(Dispatchers.IO) { security.publicKey() }
        val fingerprint = MessageDigest.getInstance("SHA-256").digest(DeviceSecurity.decode(public)).joinToString("") { "%02x".format(it.toInt() and 255) }
        saved = JSONObject().put("phase", "pending").put("project", invite.getString("project"))
            .put("fingerprint", fingerprint).put("conversation_id", UUID.randomUUID().toString())
            .put("link", JSONObject().put("endpoint", invite.getString("endpoint"))
                .put("certificate", invite.getString("certificate")).put("device_id", UUID.randomUUID().toString()))
        // Save identity before claiming: after process death Finish can recover a consumed invitation.
        publish("Claiming invitation. The device key remains on this phone.", true)
        val result = request("claim", JSONObject().put("challenge_id", invite.getString("challenge_id"))
            .put("secret", invite.getString("secret")).put("public_key", public).put("name", "Android companion"))
        require(result.getString("fingerprint") == fingerprint)
        publish("Compare the fingerprint below with the laptop and approve there. Then check approval.")
    }
    fun refresh() = action {
        val approval = request("finish")
        if (approval.getString("state") == "pending") {
            publish("Waiting for laptop approval. Compare both fingerprints first.")
        } else {
            saved.put("phase", "paired").put("project", approval.getString("project")).put("grants", approval.getJSONArray("grants"))
                .put("expires", approval.getLong("expires"))
            val status = request("status")
            val jobs = request("jobs")
            require(jobs.getJSONArray("jobs").length() <= 12)
            saved.put("jobs", jobs.getJSONArray("jobs"))
            publish("Connected / ${status.getString("resource_state")} / tool actions disabled")
        }
    }
    fun draft(value: String) {
        if (state.value.recoveryRequired) return
        saved.put("draft", value.take(12000))
        publish(state.value.message, state.value.busy, state.value.preview, persist = false)
        draftSave?.cancel()
        draftSave = viewModelScope.launch { delay(350); if (saved.has("link")) security.write(saved) }
    }
    private fun append(sender: String, text: String) {
        var messages = (jsonList(saved.optJSONArray("messages")) + JSONObject().put("sender", sender).put("text", text.take(12000))).takeLast(20)
        while (messages.size > 1 && JSONArray(messages).toString().toByteArray(Charsets.UTF_8).size > 260000) messages = messages.drop(1)
        saved.put("messages", JSONArray(messages))
    }
    fun send() = action {
        require(state.value.phase == "paired" && "chat:ask" in state.value.grants && !saved.has("pending"))
        val text = saved.optString("draft").trim(); require(text.isNotEmpty())
        val pending = JSONObject().put("conversation_id", saved.getString("conversation_id"))
            .put("request_id", UUID.randomUUID().toString()).put("text", text).put("state", "sending")
        saved.put("pending", pending).put("draft", "")
        append("You", text); publish("Sending once. If interrupted, check the saved receipt.", true)
        try {
            val args = JSONObject(pending.toString()).apply { remove("state") }
            val result = request("chat", args)
            require(result.getString("request_id") == pending.getString("request_id"))
            append("INARA", result.getString("text")); saved.remove("pending")
            publish("Answer saved on this phone.")
        } finally {
            if (saved.has("pending")) {
                pending.put("state", "uncertain")
                security.write(saved)
            }
        }
    }
    fun receipt() = action {
        val pending = saved.getJSONObject("pending")
        val result = request("receipt", JSONObject().put("conversation_id", pending.getString("conversation_id")).put("request_id", pending.getString("request_id")))
        when (result.getString("state")) {
            "succeeded" -> {
                val answer = result.getJSONObject("result")
                require(answer.getString("request_id") == pending.getString("request_id"))
                append("INARA", answer.getString("text")); saved.remove("pending"); publish("Saved reply recovered; no new AI request was sent.")
            }
            "absent" -> publish("The laptop has no receipt. Your message is preserved; discard it before composing a new request.")
            else -> publish("The request is incomplete or failed. No automatic retry will run. You can discard this local pending item.")
        }
    }
    fun discardPending() {
        if (state.value.busy) return
        saved.remove("pending"); publish("Local pending item discarded; no request was sent.")
    }
    fun preview(job: JSONObject) = action {
        val result = request("preview", JSONObject().put("kind", job.getString("kind")).put("request_id", job.getString("request_id")))
        publish("Read-only preview / ${job.getString("name")}", preview = result)
    }
    fun refreshCallReceipts() = action {
        require(state.value.phase == "paired" && "calls:read" in state.value.grants)
        saved.remove("call_receipt")
        val result = request("call_receipts")
        saved.put("call_receipts", CallReceiptJson.list(result, saved.getString("project")))
            .put("calls_synced_at", System.currentTimeMillis() / 1000)
        publish("Saved call receipt list refreshed. Open a receipt explicitly to read its transcript.")
    }
    fun openCallReceipt(id: String) = action {
        require(state.value.phase == "paired" && "calls:read" in state.value.grants)
        require(jsonList(saved.optJSONArray("call_receipts")).any { it.getString("id") == id })
        saved.remove("call_receipt"); publish("Reading the selected call receipt…", true)
        val result = request("call_receipt", JSONObject().put("id", id))
        saved.put("call_receipt", CallReceiptJson.detail(result, saved.getString("project"), id))
        publish("Saved call transcript / caller identity and message confirmation are unverified.")
    }
    fun closeCallReceipt() {
        if (state.value.busy) return
        saved.remove("call_receipt"); publish("Call transcript closed.")
    }
    fun clearCallReceipts() {
        if (state.value.busy) return
        clearCalls(); publish("Local call receipt cache cleared. The laptop copy is unchanged.")
    }
    fun notificationRefresh() = action {
        reviewedNotificationPolicy = request("notification_policy").getJSONObject("policy")
        val local = notifications.snapshot()
        if (!reviewedNotificationPolicy!!.optBoolean("enabled") || (local.optBoolean("enabled") &&
            local.optJSONObject("policy")?.optString("revision") != reviewedNotificationPolicy!!.optString("revision"))) notifications.stop()
        publish("Review the selected application/conversation rules below. No collection or sync starts automatically.")
    }
    fun notificationEnable(shareText: Boolean) {
        if (state.value.busy || state.value.phase != "paired") return
        try {
            notifications.enable(reviewedNotificationPolicy ?: error("Review laptop permission first"), shareText)
            android.service.notification.NotificationListenerService.requestRebind(android.content.ComponentName(getApplication<Application>(), SelectedNotificationListener::class.java))
            publish("Selected new notifications can now queue locally. Sync remains manual.")
        } catch (_: Exception) { publish("Collection requires native/device acceptance, system access, and a reviewed laptop permission.") }
    }
    fun notificationStop() {
        notifications.stop(); reviewedNotificationPolicy = null
        publish("Local collection stopped and queue cleared. Revoke/clear the separate laptop copy on your laptop.")
    }
    fun notificationSync() = action {
        require(BuildConfig.NOTIFICATION_ACCEPTANCE_ENABLED)
        val remote = request("notification_policy").getJSONObject("policy")
        val batch = notifications.batch(remote)
        if (batch == null) publish("No selected notifications are queued.") else {
            val result = request("notification_sync", batch)
            val accepted = NotificationVault.strings(result.getJSONArray("accepted"))
            val ids = NotificationVault.objects(batch.getJSONArray("events")).map { it.getString("event_id") }
            require(result.getString("revision") == batch.getString("revision") && accepted == ids)
            notifications.acknowledge(result.getString("revision"), accepted)
            publish("Synced ${accepted.size} selected events. Retry is explicit and duplicate-safe; no message actions ran.")
        }
    }
    fun notificationResume() {
        if (!state.value.recoveryRequired && saved.has("link")) {
            try { publish(state.value.message, state.value.busy, state.value.preview) }
            catch (_: Exception) { notifications.stop() }
        }
    }
    fun pause() {
        draftSave?.cancel()
        if (saved.has("pending")) { saved.getJSONObject("pending").put("state", "uncertain"); security.write(saved) }
        client.cancel(); work?.cancel()
        if (saved.has("link")) publish("Paused. Refresh explicitly when the laptop is available.")
    }
    fun forget() {
        draftSave?.cancel(); client.cancel(); work?.cancel(); notifications.forget(); reviewedNotificationPolicy = null; security.forget(); saved = JSONObject()
        mutable.value = CompanionState(message = "Local identity removed. Revoke the old device on the laptop too.")
    }
    override fun onCleared() { client.cancel(); super.onCleared() }
}
