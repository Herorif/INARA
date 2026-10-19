package com.inara.companion

import android.graphics.BitmapFactory
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

private val Cyan = Color(0xFF8ADDD9)
private val Space = Color(0xFF0A1421)

class MainActivity : ComponentActivity() {
    private var model: CompanionModel? = null
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.setFlags(android.view.WindowManager.LayoutParams.FLAG_SECURE, android.view.WindowManager.LayoutParams.FLAG_SECURE)
        setContent {
            val current: CompanionModel = viewModel(); model = current
            MaterialTheme(colorScheme = darkColorScheme(primary = Cyan, background = Space, surface = Color(0xFF142633))) {
                CompanionScreen(current)
            }
        }
    }
    override fun onStop() { model?.pause(); super.onStop() }
}

@Composable
fun CompanionScreen(model: CompanionModel) {
    val state by model.state.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var pastedInvitation by remember { mutableStateOf("") }
    var importError by remember { mutableStateOf("") }
    var confirmForget by remember { mutableStateOf(false) }
    val importer = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) scope.launch {
            try {
                val raw = withContext(Dispatchers.IO) {
                    context.contentResolver.openInputStream(uri)!!.use { input ->
                        val bytes = ByteArray(8193); var size = 0
                        while (size < bytes.size) { val count = input.read(bytes, size, bytes.size - size); if (count < 0) break; size += count }
                        require(size <= 8192); String(bytes, 0, size, Charsets.UTF_8)
                    }
                }
                model.importInvitation(raw)
            } catch (_: Exception) { importError = "Invitation could not be read. Create a fresh invitation on the laptop." }
        }
    }
    Surface(Modifier.fillMaxSize().safeDrawingPadding().imePadding()) {
        BoxWithConstraints(Modifier.fillMaxSize()) {
            val wide = maxWidth >= 720.dp
            val content: @Composable () -> Unit = {
                Column(Modifier.fillMaxWidth().padding(20.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
                    LinkCard(state, { importer.launch(arrayOf("application/json", "text/plain")) }, model::refresh, { confirmForget = true })
                    if (importError.isNotEmpty()) Text(importError, color = MaterialTheme.colorScheme.error)
                    if (state.phase == "unpaired" && !state.recoveryRequired) {
                        OutlinedTextField(value = pastedInvitation, onValueChange = { pastedInvitation = it.take(8192) },
                            label = { Text("Or paste invitation JSON from a QR reader") }, maxLines = 3, modifier = Modifier.fillMaxWidth())
                        TextButton(onClick = { val raw = pastedInvitation; pastedInvitation = ""; model.importInvitation(raw) },
                            enabled = !state.busy && pastedInvitation.isNotBlank()) { Text("Use pasted invitation") }
                    }
                    ChatCard(state, model)
                }
            }
            if (wide) Row(Modifier.fillMaxSize()) {
                Column(Modifier.weight(1f).verticalScroll(rememberScrollState())) { content() }
                Column(Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(20.dp)) { JobsCard(state, model) }
            } else Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState())) {
                content(); Column(Modifier.padding(horizontal = 20.dp, vertical = 8.dp)) { JobsCard(state, model) }
            }
        }
    }
    if (confirmForget) AlertDialog(onDismissRequest = { confirmForget = false }, title = { Text("Forget this laptop link?") },
        text = { Text("This removes the local identity, drafts and cache. Revoke the old device on the laptop as well.") },
        confirmButton = { TextButton(onClick = { confirmForget = false; model.forget() }) { Text("Forget link") } },
        dismissButton = { TextButton(onClick = { confirmForget = false }) { Text("Keep link") } })
}

@Composable
private fun LinkCard(state: CompanionState, importInvitation: () -> Unit, refresh: () -> Unit, forget: () -> Unit) {
    Canvas(Modifier.fillMaxWidth().height(96.dp)) {
        val center = Offset(size.width / 2, size.height / 2)
        drawCircle(Cyan.copy(alpha = .4f), 38.dp.toPx(), center, style = Stroke(1.dp.toPx()))
        drawCircle(Cyan.copy(alpha = .15f), 45.dp.toPx(), center, style = Stroke(1.dp.toPx()))
        drawLine(Cyan, center.copy(y = center.y - 13.dp.toPx()), center.copy(y = center.y + 13.dp.toPx()), 3.dp.toPx())
    }
    Text("INARA / COMPANION", style = MaterialTheme.typography.labelMedium, color = Cyan)
    Text(if (state.phase == "paired") "Within reach." else "Your laptop. Your link.", style = MaterialTheme.typography.headlineMedium)
    Text(state.message, style = MaterialTheme.typography.bodyMedium)
    if (state.busy) LinearProgressIndicator(Modifier.fillMaxWidth())
    if (state.project.isNotEmpty()) Text("PROJECT / ${state.project}", color = Cyan)
    if (state.fingerprint.isNotEmpty()) {
        Text("DEVICE KEY / compare every character with the laptop", style = MaterialTheme.typography.labelSmall)
        Text(state.fingerprint.chunked(8).joinToString(" "), style = MaterialTheme.typography.bodySmall)
    }
    if (state.phase == "unpaired" && !state.recoveryRequired) Button(onClick = importInvitation, enabled = !state.busy) { Text("Import laptop invitation") }
    if (state.phase != "unpaired") Button(onClick = refresh, enabled = !state.busy) { Text(if (state.phase == "pending") "Check laptop approval" else "Refresh laptop") }
    if (state.phase != "unpaired" || state.recoveryRequired) TextButton(onClick = forget, enabled = !state.busy) { Text("Forget local link") }
    Text("No calls, notifications, microphone or tool control. No background polling.", style = MaterialTheme.typography.bodySmall)
}

@Composable
private fun ChatCard(state: CompanionState, model: CompanionModel) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("Direct channel", style = MaterialTheme.typography.titleLarge)
            if ("chat:ask" !in state.grants) Text("Tool-free AI chat needs a separately approved pairing grant. Provider setup remains on the laptop.")
            state.messages.forEach { (sender, text) -> Text("$sender\n$text", style = MaterialTheme.typography.bodyMedium) }
            OutlinedTextField(value = state.draft, onValueChange = model::draft, label = { Text("Message INARA") },
                modifier = Modifier.fillMaxWidth(), enabled = !state.busy && "chat:ask" in state.grants && !state.pending, maxLines = 5)
            Button(onClick = model::send, enabled = !state.busy && !state.pending && state.draft.isNotBlank() && "chat:ask" in state.grants) { Text("Send once") }
            if (state.pending) {
                Text("Unfinished request saved. Reconnecting never sends it automatically.")
                TextButton(onClick = model::receipt, enabled = !state.busy) { Text("Check saved receipt") }
                TextButton(onClick = model::discardPending, enabled = !state.busy) { Text("Discard local pending item") }
            }
        }
    }
}

@Composable
private fun JobsCard(state: CompanionState, model: CompanionModel) {
    Text("STUDIO / READ ONLY", color = Cyan, style = MaterialTheme.typography.labelMedium)
    Spacer(Modifier.height(12.dp))
    if (state.jobs.isEmpty()) Text("Refresh after pairing to see saved job previews.")
    state.jobs.forEach { job ->
        Card(Modifier.fillMaxWidth().padding(bottom = 12.dp)) {
            Column(Modifier.padding(16.dp)) {
                Text(job.getString("name"), style = MaterialTheme.typography.titleMedium)
                Text("${job.getString("kind")} / ${job.getString("state")}")
                TextButton(onClick = { model.preview(job) }, enabled = !state.busy && job.getString("state") == "succeeded") { Text("Inspect preview") }
            }
        }
    }
    val preview = state.preview
    if (preview != null) {
        if (preview.optString("kind") == "image") {
            val bitmap = remember(preview) { val bytes = DeviceSecurity.decode(preview.getString("data"))
                val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
                BitmapFactory.decodeByteArray(bytes, 0, bytes.size, bounds)
                if (bytes.size <= 2097152 && bounds.outWidth in 1..1024 && bounds.outHeight in 1..1024) BitmapFactory.decodeByteArray(bytes, 0, bytes.size) else null }
            if (bitmap != null) Image(bitmap.asImageBitmap(), "Saved image preview", Modifier.fillMaxWidth().heightIn(max = 400.dp))
        } else Text(preview.toString(2), style = MaterialTheme.typography.bodySmall)
    }
}
