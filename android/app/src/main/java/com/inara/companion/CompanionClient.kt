package com.inara.companion

import org.json.JSONObject
import java.net.URI
import java.security.KeyStore
import java.security.cert.CertificateFactory
import java.security.cert.X509Certificate
import java.util.UUID
import javax.net.ssl.HttpsURLConnection
import javax.net.ssl.SSLContext
import javax.net.ssl.TrustManagerFactory

class MobileFailure(val code: String, message: String): Exception(message)

/** Dedicated HTTPS connection; no trust-all manager, redirects, cookie/token reuse or retries. */
class CompanionClient(private val security: DeviceSecurity) {
    @Volatile private var connection: HttpsURLConnection? = null
    fun cancel() { connection?.disconnect(); connection = null }
    fun request(link: JSONObject, operation: String, payload: JSONObject): JSONObject {
        val endpoint = URI(link.getString("endpoint"))
        require(endpoint.scheme == "https" && endpoint.rawPath.isNullOrEmpty() && endpoint.userInfo == null && endpoint.query == null && endpoint.fragment == null)
        val host = endpoint.host ?: error("Missing laptop address")
        val parts = host.split('.').map { it.toIntOrNull() ?: -1 }
        require(parts.size == 4 && parts.all { it in 0..255 } && (parts[0] == 10 || (parts[0] == 172 && parts[1] in 16..31) || (parts[0] == 192 && parts[1] == 168) || parts[0] == 127))
        require(endpoint.port in 1024..65535)
        val cert = CertificateFactory.getInstance("X.509").generateCertificate(DeviceSecurity.decode(link.getString("certificate")).inputStream()) as X509Certificate
        cert.checkValidity()
        val trustStore = KeyStore.getInstance(KeyStore.getDefaultType()).apply { load(null); setCertificateEntry("paired-laptop", cert) }
        val managers = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm()).apply { init(trustStore) }
        val tls = SSLContext.getInstance("TLS").apply { init(null, managers.trustManagers, null) }
        val path = "/v1/$operation"
        val body = payload.toString()
        val requestId = UUID.randomUUID().toString()
        val timestamp = System.currentTimeMillis() / 1000
        val signed = MobileProtocol.signingBytes(path, link.getString("device_id"), requestId, timestamp, body)
        val envelope = JSONObject().put("device_id", link.getString("device_id")).put("request_id", requestId)
            .put("timestamp", timestamp).put("payload", body).put("signature", security.sign(signed))
        val bytes = envelope.toString().toByteArray(Charsets.UTF_8)
        require(bytes.size <= 65536)
        val active = endpoint.resolve(path).toURL().openConnection() as HttpsURLConnection
        connection = active
        try {
            active.sslSocketFactory = tls.socketFactory // Default hostname/SAN validation remains enabled.
            active.instanceFollowRedirects = false
            active.connectTimeout = 5000; active.readTimeout = if (operation == "chat") 60000 else 10000
            active.requestMethod = "POST"; active.doOutput = true; active.useCaches = false
            active.setRequestProperty("Content-Type", "application/json")
            active.setFixedLengthStreamingMode(bytes.size)
            active.outputStream.use { it.write(bytes) }
            val status = active.responseCode
            val input = if (status in 200..299) active.inputStream else active.errorStream
            val raw = input?.use { stream ->
                val output = java.io.ByteArrayOutputStream()
                val buffer = ByteArray(8192)
                while (true) {
                    val count = stream.read(buffer); if (count < 0) break
                    require(output.size() + count <= 3000000) { "Mobile response exceeded its limit" }
                    output.write(buffer, 0, count)
                }
                output.toByteArray()
            } ?: error("Laptop did not return a response")
            val result = JSONObject(String(raw, Charsets.UTF_8))
            if (status !in 200..299 || !result.optBoolean("ok")) throw MobileFailure(result.optString("code"), result.optString("message", "Mobile request failed"))
            return result
        } finally { active.disconnect(); if (connection === active) connection = null }
    }
}
