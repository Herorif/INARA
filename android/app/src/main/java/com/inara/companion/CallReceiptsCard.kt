package com.inara.companion

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import java.text.DateFormat
import java.util.Date

@Composable
fun CallReceiptsCard(state: CompanionState, model: CompanionModel) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("Call receipts", style = MaterialTheme.typography.titleLarge)
            Text("Saved copies from this project's laptop. Caller identity and message confirmation are unverified. No call or reply actions.",
                style = MaterialTheme.typography.bodySmall)
            val allowed = "calls:read" in state.grants
            if (!allowed) Text("Needs a new pairing with the separate read-only call receipt grant enabled on the laptop.")
            Button(onClick = model::refreshCallReceipts, enabled = allowed && !state.busy) { Text("Refresh saved call list") }
            if (state.callsSyncedAt > 0) Text("Last fetched: ${DateFormat.getDateTimeInstance().format(Date(state.callsSyncedAt * 1000))}",
                style = MaterialTheme.typography.labelSmall)
            if (state.callReceipts.isEmpty()) Text("No saved call receipts. Simulated bridge checks are excluded.")
            state.callReceipts.forEach { receipt ->
                HorizontalDivider()
                Text(if (receipt.getString("source") == "sim") "SIM call" else "Personal WhatsApp call", style = MaterialTheme.typography.titleMedium)
                Text("${receipt.getString("state")} / ${DateFormat.getDateTimeInstance().format(Date((receipt.getDouble("started_at") * 1000).toLong()))}")
                TextButton(onClick = { model.openCallReceipt(receipt.getString("id")) }, enabled = allowed && !state.busy) { Text("Read saved transcript") }
            }
            state.callReceipt?.let { receipt ->
                HorizontalDivider()
                Text("Caller transcript / unverified", style = MaterialTheme.typography.titleMedium)
                val transcript = receipt.getJSONArray("transcript")
                for (index in 0 until transcript.length()) {
                    val segment = transcript.getJSONObject(index)
                    Text(if (segment.getString("role") == "caller") "Caller" else "INARA", style = MaterialTheme.typography.labelMedium)
                    Text(segment.getString("text"))
                }
                if (transcript.length() == 0) Text("No transcript was saved before this attempt ended.")
                TextButton(onClick = model::closeCallReceipt, enabled = !state.busy) { Text("Close transcript") }
            }
            TextButton(onClick = model::clearCallReceipts, enabled = !state.busy) { Text("Clear phone's receipt cache") }
            Text("Manual reads only. Offline copies remain until cleared, expired or a response reports changed access.", style = MaterialTheme.typography.bodySmall)
        }
    }
}
