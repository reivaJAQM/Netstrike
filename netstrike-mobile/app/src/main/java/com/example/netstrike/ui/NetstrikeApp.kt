package com.example.netstrike.ui

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.example.netstrike.R
import com.example.netstrike.network.AuditResult
import com.example.netstrike.network.DiscoveredTarget
import com.example.netstrike.network.NetstrikeClient
import com.example.netstrike.theme.*
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun NetstrikeApp() {
    val context = LocalContext.current
    val coroutineScope = rememberCoroutineScope()

    var targetIp by remember { mutableStateOf("192.168.100.98") }
    var targetPort by remember { mutableIntStateOf(8009) }
    var targetName by remember { mutableStateOf("Alejandro's Fire TV") }

    var youtubeInput by remember { mutableStateOf("") }
    var netflixInput by remember { mutableStateOf("") }

    val logs = remember { mutableStateListOf<String>("> NET-STRIKE Mobile inicializado.", "> Target predeterminado: 192.168.100.98:8009") }
    var isBusy by remember { mutableStateOf(false) }

    var discoveredDevices by remember { mutableStateOf<List<DiscoveredTarget>>(emptyList()) }
    var showDeviceDialog by remember { mutableStateOf(false) }

    fun addLog(msg: String) {
        logs.add(0, "> $msg")
    }

    Scaffold(
        containerColor = CyberBlack,
        topBar = {
            TopAppBar(
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = CyberDark
                ),
                title = {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Image(
                            painter = painterResource(id = R.drawable.app_logo),
                            contentDescription = "Logo",
                            modifier = Modifier
                                .size(36.dp)
                                .clip(CircleShape)
                        )
                        Spacer(modifier = Modifier.width(10.dp))
                        Column {
                            Text(
                                text = "NET-STRIKE",
                                color = NeonGreen,
                                fontWeight = FontWeight.Bold,
                                fontSize = 18.sp,
                                fontFamily = FontFamily.Monospace
                            )
                            Text(
                                text = "TV INJECTOR & AUDIT",
                                color = TextSecondary,
                                fontSize = 10.sp,
                                fontFamily = FontFamily.Monospace
                            )
                        }
                    }
                },
                actions = {
                    Box(
                        modifier = Modifier
                            .padding(end = 12.dp)
                            .clip(RoundedCornerShape(4.dp))
                            .background(CyberCard)
                            .border(1.dp, NeonGreen, RoundedCornerShape(4.dp))
                            .padding(horizontal = 8.dp, vertical = 4.dp)
                    ) {
                        Text("WI-FI ACTIVE", color = NeonGreen, fontSize = 10.sp, fontWeight = FontWeight.Bold)
                    }
                }
            )
        }
    ) { innerPadding ->
        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
                .padding(horizontal = 14.dp, vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            // TARJETA DE TARGET
            item {
                Card(
                    colors = CardDefaults.cardColors(containerColor = CyberCard),
                    shape = RoundedCornerShape(8.dp),
                    modifier = Modifier.fillMaxWidth().border(1.dp, CyberBorder, RoundedCornerShape(8.dp))
                ) {
                    Column(modifier = Modifier.padding(12.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
                            Text(
                                text = "[OBJETIVO ACTIVO]",
                                color = ElectricCyan,
                                fontWeight = FontWeight.Bold,
                                fontSize = 12.sp,
                                fontFamily = FontFamily.Monospace
                            )
                            Spacer(modifier = Modifier.weight(1f))
                            Button(
                                onClick = {
                                    isBusy = true
                                    addLog("Escaneando subred local Wi-Fi...")
                                    coroutineScope.launch {
                                        val devs = NetstrikeClient.discoverDevices(context)
                                        discoveredDevices = devs
                                        isBusy = false
                                        if (devs.isNotEmpty()) {
                                            addLog("Se detectaron ${devs.size} pantallas.")
                                            showDeviceDialog = true
                                        } else {
                                            addLog("No se detectaron objetivos por SSDP.")
                                        }
                                    }
                                },
                                colors = ButtonDefaults.buttonColors(containerColor = CyberBorder),
                                shape = RoundedCornerShape(4.dp),
                                contentPadding = PaddingValues(horizontal = 8.dp, vertical = 2.dp)
                            ) {
                                Text("Escanear Wi-Fi", fontSize = 11.sp, color = TextPrimary)
                            }
                        }

                        Spacer(modifier = Modifier.height(6.dp))
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            OutlinedTextField(
                                value = targetIp,
                                onValueChange = { targetIp = it },
                                label = { Text("IP de la Smart TV", color = TextSecondary, fontSize = 11.sp) },
                                textStyle = androidx.compose.ui.text.TextStyle(color = TextPrimary, fontFamily = FontFamily.Monospace),
                                singleLine = true,
                                modifier = Modifier.weight(1f),
                                colors = OutlinedTextFieldDefaults.colors(
                                    focusedBorderColor = ElectricCyan,
                                    unfocusedBorderColor = CyberBorder
                                )
                            )
                            Spacer(modifier = Modifier.width(8.dp))
                            Text(
                                text = targetName,
                                color = NeonGreen,
                                fontWeight = FontWeight.SemiBold,
                                fontSize = 12.sp,
                                modifier = Modifier.padding(top = 8.dp)
                            )
                        }
                    }
                }
            }

            // CONTROLES DE HARDWARE Y ACCIONES RÁPIDAS
            item {
                Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(
                        onClick = {
                            isBusy = true
                            addLog("Transmitiendo pulso HDMI-CEC a $targetIp...")
                            coroutineScope.launch {
                                val res = NetstrikeClient.turnOn(targetIp, targetPort)
                                isBusy = false
                                addLog(res.getOrElse { "Error: ${it.message}" })
                            }
                        },
                        colors = ButtonDefaults.buttonColors(containerColor = NeonGreenDark),
                        shape = RoundedCornerShape(6.dp),
                        modifier = Modifier.weight(1f)
                    ) {
                        Text("Encender TV", color = CyberBlack, fontWeight = FontWeight.Bold, fontSize = 12.sp)
                    }

                    Button(
                        onClick = {
                            isBusy = true
                            addLog("Enviando señal de aborto a $targetIp...")
                            coroutineScope.launch {
                                val res = NetstrikeClient.stopApp(targetIp, targetPort, "YouTube")
                                isBusy = false
                                addLog(res.getOrElse { "Error: ${it.message}" })
                            }
                        },
                        colors = ButtonDefaults.buttonColors(containerColor = DangerCrimson),
                        shape = RoundedCornerShape(6.dp),
                        modifier = Modifier.weight(1f)
                    ) {
                        Text("Cerrar App", color = Color.White, fontWeight = FontWeight.Bold, fontSize = 12.sp)
                    }

                    Button(
                        onClick = {
                            isBusy = true
                            addLog("Consultando estado en $targetIp...")
                            coroutineScope.launch {
                                val res = NetstrikeClient.checkStatus(targetIp, targetPort, "YouTube")
                                isBusy = false
                                addLog(res.getOrElse { "Error: ${it.message}" })
                            }
                        },
                        colors = ButtonDefaults.buttonColors(containerColor = CyberBorder),
                        shape = RoundedCornerShape(6.dp),
                        modifier = Modifier.weight(1f)
                    ) {
                        Text("Estado", color = TextPrimary, fontWeight = FontWeight.Bold, fontSize = 12.sp)
                    }
                }
            }

            // INYECCIÓN YOUTUBE
            item {
                Card(
                    colors = CardDefaults.cardColors(containerColor = CyberCard),
                    shape = RoundedCornerShape(8.dp),
                    modifier = Modifier.fillMaxWidth().border(1.dp, CyberBorder, RoundedCornerShape(8.dp))
                ) {
                    Column(modifier = Modifier.padding(12.dp)) {
                        Text(
                            text = "[INYECCIÓN YOUTUBE]",
                            color = NeonGreen,
                            fontWeight = FontWeight.Bold,
                            fontSize = 12.sp,
                            fontFamily = FontFamily.Monospace
                        )
                        Spacer(modifier = Modifier.height(6.dp))
                        OutlinedTextField(
                            value = youtubeInput,
                            onValueChange = { youtubeInput = it },
                            placeholder = { Text("Pega enlace (youtu.be, watch?v=...) o ID", color = TextSecondary, fontSize = 12.sp) },
                            singleLine = true,
                            modifier = Modifier.fillMaxWidth(),
                            textStyle = androidx.compose.ui.text.TextStyle(color = TextPrimary, fontFamily = FontFamily.Monospace),
                            colors = OutlinedTextFieldDefaults.colors(
                                focusedBorderColor = NeonGreen,
                                unfocusedBorderColor = CyberBorder
                            )
                        )
                        Spacer(modifier = Modifier.height(8.dp))
                        Button(
                            onClick = {
                                if (youtubeInput.isBlank()) {
                                    addLog("Ingresa un enlace o ID de vídeo.")
                                    return@Button
                                }
                                isBusy = true
                                addLog("Inyectando stream en $targetIp...")
                                coroutineScope.launch {
                                    val res = NetstrikeClient.playYouTube(targetIp, targetPort, youtubeInput)
                                    isBusy = false
                                    addLog(res.getOrElse { "Error: ${it.message}" })
                                }
                            },
                            colors = ButtonDefaults.buttonColors(containerColor = NeonGreen),
                            shape = RoundedCornerShape(6.dp),
                            modifier = Modifier.fillMaxWidth()
                        ) {
                            Text("INJECT & PLAY NOW", color = CyberBlack, fontWeight = FontWeight.ExtraBold)
                        }
                    }
                }
            }

            // INYECCIÓN NETFLIX
            item {
                Card(
                    colors = CardDefaults.cardColors(containerColor = CyberCard),
                    shape = RoundedCornerShape(8.dp),
                    modifier = Modifier.fillMaxWidth().border(1.dp, CyberBorder, RoundedCornerShape(8.dp))
                ) {
                    Column(modifier = Modifier.padding(12.dp)) {
                        Text(
                            text = "[PROYECCIÓN NETFLIX]",
                            color = DangerCrimson,
                            fontWeight = FontWeight.Bold,
                            fontSize = 12.sp,
                            fontFamily = FontFamily.Monospace
                        )
                        Spacer(modifier = Modifier.height(6.dp))
                        OutlinedTextField(
                            value = netflixInput,
                            onValueChange = { netflixInput = it },
                            placeholder = { Text("ID numérico o enlace de película/serie", color = TextSecondary, fontSize = 12.sp) },
                            singleLine = true,
                            modifier = Modifier.fillMaxWidth(),
                            textStyle = androidx.compose.ui.text.TextStyle(color = TextPrimary, fontFamily = FontFamily.Monospace),
                            colors = OutlinedTextFieldDefaults.colors(
                                focusedBorderColor = DangerCrimson,
                                unfocusedBorderColor = CyberBorder
                            )
                        )
                        Spacer(modifier = Modifier.height(8.dp))
                        Button(
                            onClick = {
                                if (netflixInput.isBlank()) {
                                    addLog("Ingresa un ID o enlace de Netflix.")
                                    return@Button
                                }
                                isBusy = true
                                addLog("Inyectando contenido Netflix en $targetIp...")
                                coroutineScope.launch {
                                    val res = NetstrikeClient.playNetflix(targetIp, targetPort, netflixInput)
                                    isBusy = false
                                    addLog(res.getOrElse { "Error: ${it.message}" })
                                }
                            },
                            colors = ButtonDefaults.buttonColors(containerColor = DangerCrimson),
                            shape = RoundedCornerShape(6.dp),
                            modifier = Modifier.fillMaxWidth()
                        ) {
                            Text("PROYECTAR EN NETFLIX", color = Color.White, fontWeight = FontWeight.Bold)
                        }
                    }
                }
            }

            // AUDITORÍA Y TELEMETRÍA
            item {
                Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(
                        onClick = {
                            isBusy = true
                            addLog("Iniciando auditoría DIAL en $targetIp...")
                            coroutineScope.launch {
                                val results = NetstrikeClient.scanDialApps(targetIp, targetPort)
                                isBusy = false
                                addLog("Auditoría completada:")
                                results.forEach {
                                    addLog("  [${it.name}] -> ${it.state}")
                                }
                            }
                        },
                        colors = ButtonDefaults.outlinedButtonColors(contentColor = ElectricCyan),
                        border = androidx.compose.foundation.BorderStroke(1.dp, ElectricCyan),
                        shape = RoundedCornerShape(6.dp),
                        modifier = Modifier.weight(1f)
                    ) {
                        Text("Auditar Apps", fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
                    }

                    OutlinedButton(
                        onClick = {
                            isBusy = true
                            addLog("Consultando ficha técnica en $targetIp...")
                            coroutineScope.launch {
                                val info = NetstrikeClient.getDeviceInfo(targetIp, targetPort)
                                isBusy = false
                                addLog("Ficha Técnica:")
                                info.forEach { (k, v) ->
                                    addLog("  $k: $v")
                                }
                            }
                        },
                        colors = ButtonDefaults.outlinedButtonColors(contentColor = WarningAmber),
                        border = androidx.compose.foundation.BorderStroke(1.dp, WarningAmber),
                        shape = RoundedCornerShape(6.dp),
                        modifier = Modifier.weight(1f)
                    ) {
                        Text("Ficha Técnica", fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
                    }
                }
            }

            // CONSOLA TÁCTICA DE SALIDA EN TIEMPO REAL
            item {
                Card(
                    colors = CardDefaults.cardColors(containerColor = Color(0xFF070A0E)),
                    shape = RoundedCornerShape(8.dp),
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(180.dp)
                        .border(1.dp, CyberBorder, RoundedCornerShape(8.dp))
                ) {
                    Column(modifier = Modifier.padding(8.dp).fillMaxSize()) {
                        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
                            Text("TERMINAL OUTPUT", color = TextSecondary, fontSize = 10.sp, fontFamily = FontFamily.Monospace)
                            Spacer(modifier = Modifier.weight(1f))
                            if (isBusy) {
                                CircularProgressIndicator(modifier = Modifier.size(12.dp), strokeWidth = 2.dp, color = NeonGreen)
                            }
                        }
                        HorizontalDivider(color = CyberBorder, thickness = 1.dp, modifier = Modifier.padding(vertical = 4.dp))
                        LazyColumn(modifier = Modifier.fillMaxSize()) {
                            items(logs) { logMsg ->
                                val color = when {
                                    logMsg.contains("Error", ignoreCase = true) -> DangerCrimson
                                    logMsg.contains("Vídeo", ignoreCase = true) || logMsg.contains("éxito", ignoreCase = true) -> NeonGreen
                                    logMsg.contains("Pulso", ignoreCase = true) -> ElectricCyan
                                    else -> TextPrimary
                                }
                                Text(
                                    text = logMsg,
                                    color = color,
                                    fontSize = 11.sp,
                                    fontFamily = FontFamily.Monospace,
                                    lineHeight = 14.sp
                                )
                            }
                        }
                    }
                }
            }
        }
    }

    // DIÁLOGO SELECTOR DE OBJETIVOS DETECTADOS
    if (showDeviceDialog) {
        AlertDialog(
            onDismissRequest = { showDeviceDialog = false },
            containerColor = CyberDark,
            title = { Text("Pantallas Detectadas en Wi-Fi", color = NeonGreen, fontWeight = FontWeight.Bold, fontSize = 16.sp) },
            text = {
                Column {
                    discoveredDevices.forEach { dev ->
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .clickable {
                                    targetIp = dev.ip
                                    targetPort = dev.port
                                    targetName = dev.name
                                    showDeviceDialog = false
                                    addLog("Objetivo fijado: ${dev.name} (${dev.ip})")
                                }
                                .padding(vertical = 8.dp)
                        ) {
                            Column {
                                Text(dev.name, color = TextPrimary, fontWeight = FontWeight.SemiBold)
                                Text("${dev.ip}:${dev.port}", color = ElectricCyan, fontSize = 12.sp, fontFamily = FontFamily.Monospace)
                            }
                        }
                        HorizontalDivider(color = CyberBorder)
                    }
                }
            },
            confirmButton = {
                TextButton(onClick = { showDeviceDialog = false }) {
                    Text("Cerrar", color = TextSecondary)
                }
            }
        )
    }
}
