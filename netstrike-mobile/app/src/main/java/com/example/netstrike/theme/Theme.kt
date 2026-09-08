package com.example.netstrike.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable

private val CyberColorScheme = darkColorScheme(
    primary = NeonGreen,
    onPrimary = CyberBlack,
    secondary = ElectricCyan,
    onSecondary = CyberBlack,
    tertiary = WarningAmber,
    background = CyberBlack,
    onBackground = TextPrimary,
    surface = CyberCard,
    onSurface = TextPrimary,
    error = DangerCrimson,
    onError = CyberBlack
)

@Composable
fun NetstrikeTheme(
    content: @Composable () -> Unit
) {
    MaterialTheme(
        colorScheme = CyberColorScheme,
        typography = Typography,
        content = content
    )
}
