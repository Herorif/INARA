package com.inara.companion

import android.content.Intent
import android.provider.Settings
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp

@Composable
fun NotificationCard(state: CompanionState, model: CompanionModel) {
    val context = LocalContext.current
    var shareText by remember { mutableStateOf(false) }
    val local = state.notificationState
    val policy = state.notificationPolicy
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("Selected signals / read only", style = MaterialTheme.typography.titleLarge)
            Text("No replies, WhatsApp drafts, acknowledgements or notification actions. Only new selected events; no notification history scan. Local queue: at most 100 events / 24 hours, encrypted on this phone. Sync sends up to 10 events per tap to the paired project.")
            if (!BuildConfig.NOTIFICATION_ACCEPTANCE_ENABLED) Text("Collection and access settings are disabled in this build. Native compilation and device acceptance must be completed separately.")
            Text("Collection: ${if (local?.optBoolean("enabled") == true) "on" else "off"} / queued: ${local?.optJSONArray("queue")?.length() ?: 0}")
            if (local?.optBoolean("full") == true) Text("Queue full. New events are paused until you sync or clear it.")
            TextButton(onClick = model::notificationRefresh, enabled = !state.busy) { Text("Review laptop permission") }
            if (policy != null) {
                Text("Laptop rules / ${policy.optInt("retention_hours")} hours / ${if (policy.optBoolean("include_text")) "redacted text permitted" else "metadata only"}")
                NotificationVault.objects(policy.optJSONArray("rules")).forEach { rule ->
                    Text("${rule.getString("package")} / ${if (rule.optBoolean("all_conversations")) "ALL conversations explicitly selected" else rule.getJSONArray("conversations").toString()}", style = MaterialTheme.typography.bodySmall)
                }
            }
            Text("System notification access can expose all notifications to this app. INARA filters locally before queuing; select packages/conversations on the laptop first. Turning off system access stops collection and clears the local queue when detected. An offline phone learns laptop revocation on its next manual refresh/sync.", style = MaterialTheme.typography.bodySmall)
            Button(onClick = { context.startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS)) },
                enabled = !state.busy && BuildConfig.NOTIFICATION_ACCEPTANCE_ENABLED) { Text("Open system access settings") }
            Row {
                Checkbox(checked = shareText, onCheckedChange = { shareText = it }, enabled = !state.busy && policy?.optBoolean("include_text") == true)
                Text("Also share redacted text. Free text may still contain personal details.", Modifier.weight(1f))
            }
            Button(onClick = { model.notificationEnable(shareText) }, enabled = !state.busy && BuildConfig.NOTIFICATION_ACCEPTANCE_ENABLED && policy?.optBoolean("enabled") == true) { Text("Enable reviewed selection on this phone") }
            Button(onClick = model::notificationSync, enabled = !state.busy && BuildConfig.NOTIFICATION_ACCEPTANCE_ENABLED && local?.optBoolean("enabled") == true) { Text("Sync next batch explicitly") }
            TextButton(onClick = model::notificationStop, enabled = !state.busy) { Text("Stop collection / clear local queue") }
            val candidates = NotificationVault.objects(local?.optJSONArray("candidates"))
            if (candidates.isNotEmpty()) Text("Local conversation IDs / copy a selected ID into the laptop rule. Some apps expose only a shared default conversation ID; choose all conversations only deliberately.")
            candidates.forEach { SelectionContainer { Text("${it.getString("package")}\n${it.getString("conversation")}", style = MaterialTheme.typography.bodySmall) } }
            Text("Changing laptop rules clears the server inbox and invalidates this queue. Clear/revoke the laptop copy separately; stopping locally does not dismiss notifications.", style = MaterialTheme.typography.bodySmall)
        }
    }
}
