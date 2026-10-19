package com.inara.companion

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.AtomicFile
import android.util.Base64
import org.json.JSONObject
import java.io.File
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.Signature
import java.security.spec.ECGenParameterSpec
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** Non-exported signing key plus independently encrypted, non-backed-up local state. */
class DeviceSecurity(context: Context) {
    private val keys = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
    private val file = AtomicFile(File(context.noBackupFilesDir, "companion-state.enc"))
    private val signingAlias = "inara-device-signing-v1"
    private val storageAlias = "inara-device-storage-v1"
    private fun signingKey() {
        if (!keys.containsAlias(signingAlias)) {
            KeyPairGenerator.getInstance(KeyProperties.KEY_ALGORITHM_EC, "AndroidKeyStore").apply {
                initialize(KeyGenParameterSpec.Builder(signingAlias, KeyProperties.PURPOSE_SIGN or KeyProperties.PURPOSE_VERIFY)
                    .setAlgorithmParameterSpec(ECGenParameterSpec("secp256r1"))
                    .setDigests(KeyProperties.DIGEST_SHA256).build())
            }.generateKeyPair()
        }
    }
    fun publicKey(): String {
        signingKey()
        return encode(keys.getCertificate(signingAlias).publicKey.encoded)
    }
    fun sign(bytes: ByteArray): String {
        signingKey()
        return encode(Signature.getInstance("SHA256withECDSA").run {
            initSign(keys.getKey(signingAlias, null) as java.security.PrivateKey)
            update(bytes); sign()
        })
    }
    private fun storageKey(): SecretKey {
        if (!keys.containsAlias(storageAlias)) {
            KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
                init(KeyGenParameterSpec.Builder(storageAlias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                    .setKeySize(256).setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
            }.generateKey()
        }
        return keys.getKey(storageAlias, null) as SecretKey
    }
    fun read(): JSONObject? {
        if (!file.baseFile.exists()) return null
        // Missing key or corrupted ciphertext is an explicit recovery state, never plaintext fallback.
        require(keys.containsAlias(storageAlias)) { "Protected state key is unavailable. Forget this link explicitly to recover." }
        val raw = file.readFully()
        require(raw.size in 29..524288)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, storageKey(), GCMParameterSpec(128, raw.copyOfRange(0, 12)))
        cipher.updateAAD("INARA-ANDROID-1".toByteArray(Charsets.UTF_8))
        return JSONObject(String(cipher.doFinal(raw.copyOfRange(12, raw.size)), Charsets.UTF_8))
    }
    fun write(value: JSONObject) {
        val raw = value.toString().toByteArray(Charsets.UTF_8)
        require(raw.size <= 500000)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, storageKey())
        cipher.updateAAD("INARA-ANDROID-1".toByteArray(Charsets.UTF_8))
        val output = file.startWrite()
        try { output.write(cipher.iv + cipher.doFinal(raw)); file.finishWrite(output) }
        catch (failure: Exception) { file.failWrite(output); throw failure }
    }
    fun forget() {
        file.delete()
        keys.deleteEntry(signingAlias); keys.deleteEntry(storageAlias)
    }
    companion object {
        fun encode(bytes: ByteArray) = Base64.encodeToString(bytes, Base64.NO_WRAP)
        fun decode(text: String): ByteArray = Base64.decode(text, Base64.DEFAULT)
    }
}
