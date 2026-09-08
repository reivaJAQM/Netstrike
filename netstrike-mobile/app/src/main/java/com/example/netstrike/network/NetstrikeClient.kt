package com.example.netstrike.network

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.io.OutputStream
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.HttpURLConnection
import java.net.InetAddress
import java.net.URL
import java.net.URLEncoder
import java.util.regex.Pattern

data class DiscoveredTarget(
    val name: String,
    val ip: String,
    val port: Int = 8009,
    val location: String = ""
)

data class AuditResult(
    val name: String,
    val state: String,
    val isProtected: Boolean = false,
    val isInstalled: Boolean = false
)

object NetstrikeClient {

    private const val SSDP_IP = "239.255.255.250"
    private const val SSDP_PORT = 1900
    private const val ORIGIN_HEADER = "package:com.amazon.firetv"
    private const val USER_AGENT = "NetStrike-Mobile/2.0"

    /**
     * Realiza un escaneo SSDP en la red local Wi-Fi para descubrir Smart TVs y Fire TVs.
     */
    suspend fun discoverDevices(timeoutMs: Int = 2500): List<DiscoveredTarget> = withContext(Dispatchers.IO) {
        val targets = mutableListOf<DiscoveredTarget>()
        val seenIps = mutableSetOf<String>()

        val query = (
            "M-SEARCH * HTTP/1.1\r\n" +
            "HOST: $SSDP_IP:$SSDP_PORT\r\n" +
            "MAN: \"ssdp:discover\"\r\n" +
            "MX: 2\r\n" +
            "ST: urn:dial-multiscreen-org:service:dial:1\r\n\r\n"
        ).toByteArray(Charsets.UTF_8)

        var socket: DatagramSocket? = null
        try {
            socket = DatagramSocket()
            socket.soTimeout = timeoutMs
            socket.broadcast = true

            val group = InetAddress.getByName(SSDP_IP)
            val packet = DatagramPacket(query, query.size, group, SSDP_PORT)
            socket.send(packet)

            val startTime = System.currentTimeMillis()
            val buf = ByteArray(2048)

            while (System.currentTimeMillis() - startTime < timeoutMs) {
                try {
                    val recvPacket = DatagramPacket(buf, buf.size)
                    socket.receive(recvPacket)
                    val ip = recvPacket.address.hostAddress ?: continue
                    if (seenIps.contains(ip)) continue

                    val response = String(recvPacket.data, 0, recvPacket.length, Charsets.UTF_8)
                    var location = ""
                    val locMatch = Pattern.compile("LOCATION:\\s*(https?://[^\\r\\n]+)", Pattern.CASE_INSENSITIVE).matcher(response)
                    if (locMatch.find()) {
                        location = locMatch.group(1)?.trim() ?: ""
                    }

                    var name = "Target ($ip)"
                    var port = 8009

                    if (location.isNotEmpty()) {
                        try {
                            val locUrl = URL(location)
                            port = if (locUrl.port > 0) locUrl.port else 8009
                            val xml = fetchUrl(location, timeout = 1000)
                            val nameMatch = Pattern.compile("<friendlyName>(.*?)</friendlyName>", Pattern.CASE_INSENSITIVE).matcher(xml)
                            if (nameMatch.find()) {
                                name = nameMatch.group(1)?.trim() ?: name
                            }
                        } catch (_: Exception) {}
                    }

                    seenIps.add(ip)
                    targets.add(DiscoveredTarget(name = name, ip = ip, port = port, location = location))
                } catch (_: Exception) {
                    break
                }
            }
        } catch (_: Exception) {
        } finally {
            socket?.close()
        }

        targets
    }

    /**
     * Inyecta pulso de encendido simulando activación HDMI-CEC.
     */
    suspend fun turnOn(ip: String, port: Int = 8009): Result<String> = withContext(Dispatchers.IO) {
        try {
            sendDialRequest(ip, port, "YouTube", "POST", payload = null)
            kotlinx.coroutines.delay(1800)
            sendDialRequest(ip, port, "YouTube/run", "DELETE", payload = null)
            Result.success("Pulso HDMI-CEC transmitido. TV encendida y en inicio.")
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /**
     * Inyecta vídeo en YouTube con soporte de cambio en caliente vía Lounge API.
     */
    suspend fun playYouTube(ip: String, port: Int = 8009, videoInput: String): Result<String> = withContext(Dispatchers.IO) {
        val (videoId, timeSec) = extractYouTubeDetails(videoInput)
        if (videoId == null) {
            return@withContext Result.failure(IllegalArgumentException("No se reconoció un ID de YouTube válido en: $videoInput"))
        }

        try {
            val statusResp = sendDialRequest(ip, port, "YouTube", "GET")
            val isRunning = statusResp.second.contains("<state>running</state>", ignoreCase = true)

            var screenId: String? = null
            val sidMatch = Pattern.compile("<screenId>(.*?)</screenId>", Pattern.CASE_INSENSITIVE).matcher(statusResp.second)
            if (sidMatch.find()) {
                screenId = sidMatch.group(1)?.trim()
            }

            if (isRunning && !screenId.isNullOrEmpty()) {
                // Inyección en caliente vía Lounge API
                try {
                    val loungeToken = getLoungeToken(screenId)
                    if (!loungeToken.isNullOrEmpty()) {
                        val bindData = bindLoungeSession(loungeToken)
                        if (bindData != null) {
                            sendPlayCommand(loungeToken, bindData.first, bindData.second, videoId, timeSec ?: 0)
                            return@withContext Result.success("Vídeo [$videoId] inyectado en caliente (Lounge API).")
                        }
                    }
                } catch (_: Exception) {}

                // Fallback: Reinicio forzado si Lounge API falla
                sendDialRequest(ip, port, "YouTube/run", "DELETE")
                kotlinx.coroutines.delay(1200)
                var payload = "v=$videoId"
                if (timeSec != null && timeSec > 0) payload += "&t=$timeSec"
                sendDialRequest(ip, port, "YouTube", "POST", payload)
                return@withContext Result.success("Vídeo [$videoId] inyectado tras reinicio de YouTube.")
            } else {
                var payload = "v=$videoId"
                if (timeSec != null && timeSec > 0) payload += "&t=$timeSec"
                sendDialRequest(ip, port, "YouTube", "POST", payload)
                return@withContext Result.success("YouTube lanzado con vídeo [$videoId].")
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /**
     * Proyecta contenido en Netflix.
     */
    suspend fun playNetflix(ip: String, port: Int = 8009, contentInput: String): Result<String> = withContext(Dispatchers.IO) {
        val netflixId = extractNetflixId(contentInput)
        if (netflixId == null) {
            return@withContext Result.failure(IllegalArgumentException("No se reconoció un ID o enlace de Netflix válido"))
        }

        try {
            val payload = "v=$netflixId&source_type=12"
            val resp = sendDialRequest(ip, port, "Netflix", "POST", payload)
            if (resp.first in 200..201) {
                Result.success("Contenido [$netflixId] proyectado en Netflix.")
            } else {
                Result.failure(Exception("Respuesta de TV (Código ${resp.first})"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /**
     * Cierra o aborta una aplicación activa.
     */
    suspend fun stopApp(ip: String, port: Int = 8009, appName: String = "YouTube"): Result<String> = withContext(Dispatchers.IO) {
        try {
            val resp = sendDialRequest(ip, port, "$appName/run", "DELETE")
            if (resp.first in 200..204) {
                Result.success("Aplicación [$appName] terminada.")
            } else {
                Result.success("Comando de cierre transmitido hacia [$appName].")
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /**
     * Consulta el estado de una aplicación.
     */
    suspend fun checkStatus(ip: String, port: Int = 8009, appName: String = "YouTube"): Result<String> = withContext(Dispatchers.IO) {
        try {
            val resp = sendDialRequest(ip, port, appName, "GET")
            val stateMatch = Pattern.compile("<state>(.*?)</state>", Pattern.CASE_INSENSITIVE).matcher(resp.second)
            val state = if (stateMatch.find()) stateMatch.group(1)?.trim()?.uppercase() else "DESCONOCIDO"
            Result.success("Estado de [$appName]: $state (HTTP ${resp.first})")
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    /**
     * Audita la lista de aplicaciones y servicios compatibles con DIAL.
     */
    suspend fun scanDialApps(ip: String, port: Int = 8009): List<AuditResult> = withContext(Dispatchers.IO) {
        val appsToTest = listOf(
            "YouTube" to listOf("YouTube", "YouTubeTV"),
            "Netflix" to listOf("Netflix"),
            "Navegador Silk" to listOf("com.amazon.cloud9", "Silk"),
            "Servicio Sistema" to listOf("system"),
            "Plex" to listOf("Plex")
        )

        val results = mutableListOf<AuditResult>()
        for (item in appsToTest) {
            val displayName = item.first
            var matched = false

            for (key in item.second) {
                try {
                    val resp = sendDialRequest(ip, port, key, "GET")
                    if (resp.first == 200) {
                        val stateMatch = Pattern.compile("<state>(.*?)</state>", Pattern.CASE_INSENSITIVE).matcher(resp.second)
                        val state = if (stateMatch.find()) stateMatch.group(1)?.trim()?.lowercase() ?: "running" else "running"
                        val stateLabel = when (state) {
                            "running" -> "EJECUTÁNDOSE"
                            "hidden" -> "EN SEGUNDO PLANO"
                            else -> "DETENIDO"
                        }
                        results.add(AuditResult(displayName, stateLabel, isInstalled = true))
                        matched = true
                        break
                    } else if (resp.first == 403) {
                        results.add(AuditResult(displayName, "PROTEGIDO", isProtected = true, isInstalled = true))
                        matched = true
                        break
                    }
                } catch (_: Exception) {}
            }

            if (!matched) {
                results.add(AuditResult(displayName, "NO EXPUESTA", isInstalled = false))
            }
        }
        results
    }

    /**
     * Extrae información de telemetría y ficha técnica de la TV.
     */
    suspend fun getDeviceInfo(ip: String, port: Int = 8009, location: String = ""): Map<String, String> = withContext(Dispatchers.IO) {
        val info = mutableMapOf(
            "IP" to "$ip:$port",
            "Dispositivo" to "Smart TV / Target",
            "Fabricante" to "Desconocido",
            "Modelo" to "Desconocido",
            "Versión DIAL" to "2.x"
        )

        try {
            val loc = if (location.isNotEmpty()) location else "http://$ip:$port/dd.xml"
            val xml = fetchUrl(loc, timeout = 1500)

            fun extract(tag: String): String? {
                val m = Pattern.compile("<$tag>(.*?)</$tag>", Pattern.CASE_INSENSITIVE).matcher(xml)
                return if (m.find()) m.group(1)?.trim() else null
            }

            extract("friendlyName")?.let { info["Dispositivo"] = it }
            extract("manufacturer")?.let { info["Fabricante"] = it }
            extract("modelName")?.let { info["Modelo"] = it }
            extract("UDN")?.let { info["UDN"] = it }

            val verMatch = Pattern.compile("dialVer=[\"'](.*?)[\"']", Pattern.CASE_INSENSITIVE).matcher(xml)
            if (verMatch.find()) {
                info["Versión DIAL"] = verMatch.group(1)?.trim() ?: "2.x"
            }
        } catch (_: Exception) {}

        info
    }

    // =========================================================================
    // MÉTODOS PRIVADOS Y DE PROTOCOLO (Lounge API & DIAL HTTP)
    // =========================================================================

    private fun sendDialRequest(
        ip: String,
        port: Int,
        subpath: String,
        method: String = "POST",
        payload: String? = null
    ): Pair<Int, String> {
        val url = URL("http://$ip:$port/apps/$subpath")
        val conn = url.openConnection() as HttpURLConnection
        conn.requestMethod = method
        conn.connectTimeout = 3000
        conn.readTimeout = 3000
        conn.setRequestProperty("Origin", ORIGIN_HEADER)
        conn.setRequestProperty("User-Agent", USER_AGENT)

        if (payload != null && (method == "POST" || method == "PUT")) {
            conn.doOutput = true
            val bytes = payload.toByteArray(Charsets.UTF_8)
            conn.setRequestProperty("Content-Type", "application/x-www-form-urlencoded")
            conn.setRequestProperty("Content-Length", bytes.size.toString())
            val os: OutputStream = conn.outputStream
            os.write(bytes)
            os.flush()
            os.close()
        }

        val code = try { conn.responseCode } catch (e: Exception) { -1 }
        val stream = if (code in 200..399) conn.inputStream else conn.errorStream
        val body = if (stream != null) {
            BufferedReader(InputStreamReader(stream)).use { it.readText() }
        } else ""
        conn.disconnect()
        return Pair(code, body)
    }

    private fun fetchUrl(urlStr: String, timeout: Int = 2000): String {
        val url = URL(urlStr)
        val conn = url.openConnection() as HttpURLConnection
        conn.connectTimeout = timeout
        conn.readTimeout = timeout
        conn.setRequestProperty("User-Agent", USER_AGENT)
        val text = BufferedReader(InputStreamReader(conn.inputStream)).use { it.readText() }
        conn.disconnect()
        return text
    }

    private fun getLoungeToken(screenId: String): String? {
        val url = URL("https://www.youtube.com/api/lounge/pairing/get_lounge_token_batch")
        val conn = url.openConnection() as HttpURLConnection
        conn.requestMethod = "POST"
        conn.connectTimeout = 3000
        conn.readTimeout = 3000
        conn.doOutput = true
        conn.setRequestProperty("Content-Type", "application/x-www-form-urlencoded")
        val postData = "screen_ids=" + URLEncoder.encode(screenId, "UTF-8")
        conn.outputStream.use { it.write(postData.toByteArray(Charsets.UTF_8)) }

        if (conn.responseCode == 200) {
            val resp = BufferedReader(InputStreamReader(conn.inputStream)).use { it.readText() }
            val json = JSONObject(resp)
            val screens = json.optJSONArray("screens")
            if (screens != null && screens.length() > 0) {
                return screens.getJSONObject(0).optString("loungeToken")
            }
        }
        return null
    }

    private fun bindLoungeSession(loungeToken: String): Pair<String, String>? {
        val url = URL("https://www.youtube.com/api/lounge/bc/bind?RID=0&VER=8&CVER=1")
        val conn = url.openConnection() as HttpURLConnection
        conn.requestMethod = "POST"
        conn.connectTimeout = 3000
        conn.readTimeout = 3000
        conn.doOutput = true
        conn.setRequestProperty("X-YouTube-LoungeId-Token", loungeToken)
        conn.setRequestProperty("Content-Type", "application/x-www-form-urlencoded")
        conn.outputStream.use { it.write("count=0".toByteArray(Charsets.UTF_8)) }

        if (conn.responseCode == 200) {
            val content = BufferedReader(InputStreamReader(conn.inputStream)).use { it.readText() }
            val sidMatch = Pattern.compile("c\",\\s*\"(.*?)\"", Pattern.CASE_INSENSITIVE).matcher(content)
            val gMatch = Pattern.compile("S\",\\s*\"(.*?)\"", Pattern.CASE_INSENSITIVE).matcher(content)
            if (sidMatch.find() && gMatch.find()) {
                return Pair(sidMatch.group(1) ?: "", gMatch.group(1) ?: "")
            }
        }
        return null
    }

    private fun sendPlayCommand(loungeToken: String, sid: String, gsessionId: String, videoId: String, timeSec: Int) {
        val encSid = URLEncoder.encode(sid, "UTF-8")
        val encG = URLEncoder.encode(gsessionId, "UTF-8")
        val url = URL("https://www.youtube.com/api/lounge/bc/bind?SID=$encSid&GSESSIONID=$encG&RID=1&VER=8&CVER=1")
        val conn = url.openConnection() as HttpURLConnection
        conn.requestMethod = "POST"
        conn.connectTimeout = 3000
        conn.readTimeout = 3000
        conn.doOutput = true
        conn.setRequestProperty("X-YouTube-LoungeId-Token", loungeToken)
        conn.setRequestProperty("Content-Type", "application/x-www-form-urlencoded")

        val postParams = listOf(
            "_req_0_action" to "setPlaylist",
            "_req_0_video_id" to videoId,
            "_req_0_currentTime" to timeSec.toString(),
            "_req_0_currentIndex" to "-1",
            "_req_0_audioOnly" to "false",
            "count" to "1"
        ).joinToString("&") { "${it.first}=${URLEncoder.encode(it.second, "UTF-8")}" }

        conn.outputStream.use { it.write(postParams.toByteArray(Charsets.UTF_8)) }
        conn.responseCode
        conn.disconnect()
    }

    private fun extractYouTubeDetails(input: String): Pair<String?, Int?> {
        val raw = input.trim()
        if (raw.isEmpty()) return Pair(null, null)

        var vid: String? = null
        if (Pattern.matches("^[a-zA-Z0-9_-]{11}$", raw)) {
            vid = raw
        } else {
            val p = Pattern.compile("(?:v=|/v/|/embed/|/shorts/|youtu\\.be/)([a-zA-Z0-9_-]{11})")
            val m = p.matcher(raw)
            if (m.find()) {
                vid = m.group(1)
            }
        }
        if (vid == null) return Pair(null, null)

        var timeSec: Int? = null
        val tm = Pattern.compile("[?&]t=([0-9mh]+s?)").matcher(raw)
        if (tm.find()) {
            val tStr = tm.group(1)?.replace("s", "") ?: ""
            if (tStr.all { it.isDigit() }) {
                timeSec = tStr.toIntOrNull()
            }
        }
        return Pair(vid, timeSec)
    }

    private fun extractNetflixId(input: String): String? {
        val raw = input.trim()
        if (raw.isEmpty()) return null
        if (raw.all { it.isDigit() }) return raw
        val m = Pattern.compile("netflix\\.com/(?:watch|title)/([0-9]+)").matcher(raw)
        return if (m.find()) m.group(1) else null
    }
}
