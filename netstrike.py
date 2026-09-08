#!/usr/bin/env python3

import argparse
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import warnings
from typing import Dict, List, Optional, Tuple

# Silenciar advertencias de LibreSSL/urllib3 en la terminal
warnings.filterwarnings("ignore")

# Soporte para Google Cast / Android TV / Chromecast
try:
    import pychromecast
    from pychromecast.controllers.youtube import YouTubeController
    HAS_PYCHROMECAST = True
except ImportError:
    HAS_PYCHROMECAST = False

# Soporte para YouTube Lounge API (inyección en caliente en Smart TVs y Fire TV)
try:
    import casttube
    HAS_CASTTUBE = True
except ImportError:
    HAS_CASTTUBE = False

# ==============================================================================
# CONSTANTES DE RED Y PROTOCOLOS
# ==============================================================================
DEFAULT_DIAL_PORT = 8009
SSDP_ADDR = "239.255.255.250"
SSDP_PORT = 1900

# ==============================================================================
# ESTILOS Y COLORES ANSI PARA TERMINAL
# ==============================================================================
class Style:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"

    @classmethod
    def disable_if_unsupported(cls):
        if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
            for attr in dir(cls):
                if not attr.startswith("_") and isinstance(getattr(cls, attr), str):
                    setattr(cls, attr, "")

Style.disable_if_unsupported()

def log_success(msg: str):
    print(f" {Style.GREEN}{Style.BOLD}[+]{Style.RESET} {msg}")

def log_info(msg: str):
    print(f" {Style.CYAN}{Style.BOLD}[*]{Style.RESET} {msg}")

def log_warn(msg: str):
    print(f" {Style.YELLOW}{Style.BOLD}[!]{Style.RESET} {msg}")

def log_error(msg: str):
    print(f" {Style.RED}{Style.BOLD}[-]{Style.RESET} {msg}")

# ==============================================================================
# UTILIDADES Y NORMALIZACIÓN
# ==============================================================================
def normalize_app_name(name: str) -> str:
    """Normaliza nombres de apps comunes para evitar errores de mayúsculas (case-sensitive)."""
    mapping = {
        "youtube": "YouTube",
        "netflix": "Netflix",
        "plex": "Plex"
    }
    return mapping.get(name.strip().lower(), name.strip())

def extract_youtube_id(url_or_id: str) -> Optional[str]:
    """
    Extrae el ID de 11 caracteres de un vídeo de YouTube a partir de un enlace o ID directo.
    Soporta enlaces estándar, cortos (youtu.be), Shorts, embeds e IDs directos.
    """
    raw = url_or_id.strip()
    if not raw:
        return None

    if re.fullmatch(r"[a-zA-Z0-9_-]{11}", raw):
        return raw

    patterns = [
        r"(?:v=|\/v\/|\/embed\/|\/shorts\/|youtu\.be\/)([a-zA-Z0-9_-]{11})",
        r"^([a-zA-Z0-9_-]{11})$"
    ]
    for pattern in patterns:
        match = re.search(pattern, raw)
        if match:
            return match.group(1)

    return None

def extract_youtube_details(url_or_id: str) -> Tuple[Optional[str], Optional[int]]:
    """
    Extrae el ID de 11 caracteres de YouTube y un posible timestamp en segundos (t=...).
    """
    raw = url_or_id.strip()
    if not raw:
        return None, None

    vid = extract_youtube_id(raw)
    if not vid:
        return None, None

    t_sec = None
    t_match = re.search(r"[?&]t=([0-9mh]+s?)", raw)
    if t_match:
        t_str = t_match.group(1).rstrip("s")
        if t_str.isdigit():
            t_sec = int(t_str)
        else:
            total = 0
            m_h = re.search(r"(\d+)h", t_str)
            m_m = re.search(r"(\d+)m", t_str)
            m_s = re.search(r"(\d+)s?", t_str)
            if m_h:
                total += int(m_h.group(1)) * 3600
            if m_m:
                total += int(m_m.group(1)) * 60
            if m_s and not m_m and not m_h:
                total += int(m_s.group(1))
            if total > 0:
                t_sec = total

    return vid, t_sec

def extract_netflix_id(url_or_id: str) -> Optional[str]:
    """
    Extrae el ID numérico de un título de Netflix a partir de una URL o ID directo.
    Soporta: netflix.com/watch/80057281, netflix.com/title/80057281 o ID numérico.
    """
    raw = url_or_id.strip()
    if not raw:
        return None
    if raw.isdigit():
        return raw
    match = re.search(r"netflix\.com/(?:watch|title)/([0-9]+)", raw)
    if match:
        return match.group(1)
    return None

DIAL_AUDIT_APPS = [
    ("YouTube", ["YouTube", "YouTubeTV"]),
    ("Netflix", ["Netflix"]),
    ("Navegador Web / Silk", ["com.amazon.cloud9", "Silk"]),
    ("Servicio Sistema", ["system"]),
    ("Plex", ["Plex"])
]

def is_google_cast_device(ip: str, timeout: float = 1.0) -> bool:
    """Detecta si el dispositivo en la IP dada es un Chromecast / Android TV."""
    try:
        req = urllib.request.Request(f"http://{ip}:8008/setup/eureka_info")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.getcode() == 200
    except Exception:
        return False

# ==============================================================================
# DESCUBRIMIENTO DE DISPOSITIVOS (SSDP / UPnP)
# ==============================================================================
def discover_devices(timeout: float = 2.5) -> List[Dict[str, any]]:
    """
    Escanea la red local y detecta Smart TVs, Fire TVs y dispositivos Chromecast/Android TV.
    """
    query = (
        "M-SEARCH * HTTP/1.1\r\n"
        f"HOST: {SSDP_ADDR}:{SSDP_PORT}\r\n"
        'MAN: "ssdp:discover"\r\n'
        "MX: 2\r\n"
        "ST: urn:dial-multiscreen-org:service:dial:1\r\n"
        "\r\n"
    ).encode("utf-8")

    devices: List[Dict[str, any]] = []
    seen_ips = set()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.settimeout(timeout)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    try:
        sock.sendto(query, (SSDP_ADDR, SSDP_PORT))
        while True:
            try:
                data, addr = sock.recvfrom(4096)
                ip = addr[0]
                if ip in seen_ips:
                    continue
                seen_ips.add(ip)

                response_text = data.decode("utf-8", errors="ignore")
                location = ""
                for line in response_text.splitlines():
                    if line.upper().startswith("LOCATION:"):
                        location = line.split(":", 1)[1].strip()
                        break

                port = DEFAULT_DIAL_PORT
                friendly_name = f"Dispositivo ({ip})"
                is_cast = is_google_cast_device(ip, timeout=0.8)

                if location:
                    try:
                        req = urllib.request.Request(location, headers={"User-Agent": "SmartTV-Remote/2.5"})
                        with urllib.request.urlopen(req, timeout=1.5) as resp:
                            app_header = resp.headers.get("Application-URL")
                            if app_header:
                                parsed_app = urllib.parse.urlparse(app_header)
                                if parsed_app.port:
                                    port = parsed_app.port
                                if parsed_app.hostname:
                                    ip = parsed_app.hostname

                            xml_data = resp.read().decode("utf-8", errors="ignore")
                            fn_match = re.search(r"<friendlyName>(.*?)</friendlyName>", xml_data, re.IGNORECASE)
                            if fn_match:
                                friendly_name = fn_match.group(1).strip()
                            else:
                                model_match = re.search(r"<modelName>(.*?)</modelName>", xml_data, re.IGNORECASE)
                                if model_match:
                                    friendly_name = model_match.group(1).strip()
                    except Exception:
                        pass

                device_type = "Chromecast / Android TV" if is_cast else "Fire TV / DIAL"

                devices.append({
                    "name": friendly_name,
                    "ip": ip,
                    "port": str(port),
                    "is_cast": is_cast,
                    "type": device_type,
                    "location": location
                })
            except socket.timeout:
                break
    except Exception as e:
        log_warn(f"Error en escaneo de red: {e}")
    finally:
        sock.close()

    return devices

# ==============================================================================
# CONTROLADOR UNIVERSAL (DIAL + GOOGLE CAST)
# ==============================================================================
class SmartTVRemote:
    def __init__(self, ip: str, port: int = DEFAULT_DIAL_PORT, name: str = "Dispositivo", is_cast: Optional[bool] = None, location: Optional[str] = None):
        self.ip = ip
        self.port = port
        self.name = name
        self.is_cast = is_cast if is_cast is not None else is_google_cast_device(ip, timeout=1.0)
        self.location = location
        self._cast_client = None
        self._app_instances: Dict[str, str] = {}
        self._rendering_control_url: Optional[str] = None
        self._av_transport_url: Optional[str] = None
        self._is_roku: Optional[bool] = None
        self._dial_volume_estimate: int = 50
        self._dial_mute_estimate: bool = False

    @property
    def protocol_label(self) -> str:
        return "Google Cast v2" if self.is_cast else "DIAL"

    @property
    def base_dial_url(self) -> str:
        return f"http://{self.ip}:{self.port}/apps"

    def _get_cast_connection(self, timeout: float = 4.0):
        """Inicializa y retorna el cliente de conexión Google Cast si está disponible."""
        if not HAS_PYCHROMECAST:
            log_warn("pychromecast no está instalado. Ejecuta: python3 -m pip install --break-system-packages pychromecast")
            return None

        if self._cast_client is None or not self._cast_client.socket_client.is_connected:
            try:
                # Conectar directamente por host IP al puerto Cast (8009)
                self._cast_client = pychromecast.get_chromecast_from_host(
                    (self.ip, 8009, None, None, self.name),
                    timeout=timeout
                )
                self._cast_client.wait(timeout=timeout)
            except Exception as e:
                log_error(f"No se pudo conectar a {self.name} vía Google Cast: {e}")
                self._cast_client = None

        return self._cast_client

    def send_dial_request(self, app_name: str, method: str = "POST", data: Optional[str] = None, subpath: str = "", full_url: Optional[str] = None) -> Tuple[Optional[int], str, Dict[str, str]]:
        """Envía peticiones HTTP al endpoint DIAL del dispositivo objetivo."""
        norm_name = normalize_app_name(app_name)
        if full_url:
            url = full_url
        else:
            url = f"{self.base_dial_url}/{norm_name}"
            if subpath:
                url = f"{url}/{subpath.lstrip('/')}"
        payload = data.encode("utf-8") if data else None

        headers = {
            "Origin": "package:com.amazon.firetv",
            "User-Agent": "NetStrike-TV-Injector/3.0",
            "Content-Length": str(len(payload)) if payload else "0"
        }
        if payload:
            headers["Content-Type"] = "application/x-www-form-urlencoded"

        req = urllib.request.Request(url, data=payload, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                status = response.getcode()
                body = response.read().decode("utf-8", errors="ignore")
                resp_headers = dict(response.headers)
                loc = resp_headers.get("Location") or resp_headers.get("location")
                if loc and method == "POST":
                    self._app_instances[norm_name] = loc
                return status, body, resp_headers
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="ignore")
            resp_headers = dict(e.headers) if hasattr(e, "headers") and e.headers else {}
            return e.code, body, resp_headers
        except urllib.error.URLError as e:
            return None, str(e.reason), {}
        except Exception as e:
            return None, str(e), {}

    def launch_app(self, app_name: str, video_input: Optional[str] = None, timestamp: Optional[int] = None) -> bool:
        """Inicia una aplicación en el dispositivo (usa Google Cast o DIAL según corresponda)."""
        norm_app = normalize_app_name(app_name)

        # Caso YouTube en Chromecast / Android TV
        if self.is_cast and norm_app == "YouTube":
            log_info(f"Desplegando YouTube en {Style.BOLD}{self.name}{Style.RESET} vía Google Cast...")
            cast = self._get_cast_connection()
            if not cast:
                return False

            try:
                yt = YouTubeController()
                cast.register_handler(yt)
                if video_input:
                    vid = extract_youtube_id(video_input)
                    if not vid:
                        log_error(f"Payload ID inválido: {video_input}")
                        return False
                    log_info(f"Inyectando stream {Style.BOLD}{vid}{Style.RESET}...")
                    yt.play_video(vid)
                else:
                    yt.launch()
                log_success(f"Payload transmitido con éxito a {self.name}.")
                return True
            except Exception as e:
                log_error(f"Fallo al inyectar YouTube en Cast: {e}")
                return False

        # Caso DIAL (Fire TV, Roku, o apps DIAL en Android TV como Netflix)
        log_info(f"Inyectando [{Style.BOLD}{norm_app}{Style.RESET}] en {self.ip} ({self.protocol_label})...")

        if norm_app == "YouTube" and video_input:
            vid = extract_youtube_id(video_input) or video_input
            t_start = str(timestamp or 0)

            # Consultar si YouTube ya se encuentra ejecutándose en la TV
            status_check, body_check, _ = self.send_dial_request("YouTube", method="GET")
            is_running = False
            screen_id = None
            if status_check == 200:
                if "<state>running</state>" in body_check.lower():
                    is_running = True
                sid_match = re.search(r"<screenId>(.*?)</screenId>", body_check, re.IGNORECASE)
                if sid_match:
                    screen_id = sid_match.group(1).strip()

            if is_running:
                log_info("YouTube ya está activo en pantalla. Iniciando inyección en caliente...")
                # 1. Intentar Lounge API (cambia el vídeo sin cerrar la app)
                if screen_id and HAS_CASTTUBE:
                    try:
                        log_info(f"Sincronizando sesión Lounge con la TV...")
                        session = casttube.YouTubeSession(screen_id)
                        session.play_video(vid, start_time=t_start)
                        log_success(f"Vídeo [{vid}] inyectado en vivo en la pantalla.")
                        return True
                    except Exception as e:
                        log_warn(f"Lounge API no respondió ({e}). Aplicando reinyección por reinicio rápido...")

                # 2. Fallback: Abortar y relanzar con el nuevo vídeo
                log_info("Reiniciando YouTube para forzar carga del nuevo stream...")
                self.stop_app("YouTube")
                time.sleep(1.2)
                payload = f"v={vid}"
                if timestamp:
                    payload += f"&t={timestamp}"
                status_post, _, _ = self.send_dial_request("YouTube", method="POST", data=payload)
                if status_post in (200, 201):
                    log_success(f"Vídeo [{vid}] inyectado tras reinicio de YouTube.")
                    return True
                else:
                    log_error(f"Fallo al relanzar YouTube (Código {status_post}).")
                    return False

        # Caso normal DIAL (app cerrada o Netflix o apertura de app sin vídeo)
        payload = None
        if norm_app == "YouTube" and video_input:
            vid = extract_youtube_id(video_input) or video_input
            payload = f"v={vid}"
            if timestamp:
                payload += f"&t={timestamp}"
        elif norm_app == "Netflix" and video_input:
            nid = extract_netflix_id(video_input) or video_input
            payload = f"v={nid}&source_type=12"
        elif video_input:
            payload = video_input

        status, body, _ = self.send_dial_request(norm_app, method="POST", data=payload)

        if status in (200, 201):
            log_success(f"Proceso [{norm_app}] desplegado con éxito.")
            return True
        elif status == 404:
            log_warn(f"El endpoint [{norm_app}] no responde o no está disponible en este target.")
            return False
        elif status is None:
            log_error(f"Fallo de conexión con {self.ip}:{self.port} -> {body}")
            return False
        else:
            log_error(f"Respuesta del target (Código {status}): {body or 'Sin detalles'}")
            return False

    def turn_on(self) -> bool:
        """Inyecta pulso HDMI-CEC para despertar target (inicia señuelo YouTube y aborta proceso)."""
        log_info(f"Inyectando pulso de encendido (HDMI-CEC) hacia {Style.BOLD}{self.name}{Style.RESET}...")

        # 1. Iniciar YouTube para disparar el encendido HDMI-CEC del hardware
        ok = self.launch_app("YouTube")
        if not ok:
            log_error(f"Fallo al transmitir payload de activación hacia {self.name}.")
            return False

        # 2. Pausa para dar tiempo a que el hardware despierte la pantalla
        log_info("Hardware activado. Abortando proceso señuelo...")
        time.sleep(2.0)

        # 3. Cerrar YouTube inmediatamente
        self.stop_app("YouTube")
        log_success(f"Target {Style.BOLD}{self.name}{Style.RESET} encendido y en pantalla de inicio.")
        return True

    def play_youtube(self, video_input: str) -> bool:
        """Lanza o proyecta un vídeo de YouTube reconociendo URL completa o ID con timestamp."""
        vid, t_sec = extract_youtube_details(video_input)
        if not vid:
            log_error(f"No se pudo reconocer un ID de vídeo válido en: '{video_input}'")
            return False
        return self.launch_app("YouTube", video_input=vid, timestamp=t_sec)

    def play_netflix(self, content_input: str) -> bool:
        """Lanza o proyecta una película/serie de Netflix reconociendo ID o URL."""
        nid = extract_netflix_id(content_input)
        if not nid:
            log_error(f"No se pudo reconocer un ID o enlace de Netflix válido en: '{content_input}'")
            return False
        return self.launch_app("Netflix", video_input=nid)

    def stop_app(self, app_name: str = "YouTube") -> bool:
        """Detiene la aplicación activa en el dispositivo objetivo."""
        norm_app = normalize_app_name(app_name)
        log_info(f"Enviando señal de terminación a [{norm_app}]...")

        if self.is_cast:
            cast = self._get_cast_connection()
            if cast:
                try:
                    cast.quit_app()
                    log_success(f"Proceso [{norm_app}] abortado en {self.name}. Retorno a Shell.")
                    return True
                except Exception as e:
                    log_error(f"Fallo al abortar app en Cast: {e}")
                    return False

        # 1. Si tenemos la URL exacta de instancia obtenida en el POST (Location header)
        if norm_app in self._app_instances:
            instance_url = self._app_instances[norm_app]
            status, body, _ = self.send_dial_request(norm_app, method="DELETE", full_url=instance_url)
            if status in (200, 204):
                self._app_instances.pop(norm_app, None)
                log_success(f"Proceso [{norm_app}] terminado con éxito mediante instancia DIAL (Status: {status}).")
                return True

        # 2. DIAL DELETE: En Fire TV y DIAL 2.2+, el recurso de ejecución reside en /apps/{app}/run
        status, body, _ = self.send_dial_request(norm_app, method="DELETE", subpath="run")
        if status in (200, 204):
            self._app_instances.pop(norm_app, None)
            log_success(f"Proceso [{norm_app}] terminado con éxito (Status: {status}).")
            return True

        # 3. Fallback a DELETE directo en /apps/{app} si el target no usa /run
        status, body, _ = self.send_dial_request(norm_app, method="DELETE")
        if status in (200, 204):
            self._app_instances.pop(norm_app, None)
            log_success(f"Proceso [{norm_app}] terminado con éxito (Status: {status}).")
            return True
        elif status == 404:
            log_warn(f"El proceso [{norm_app}] no se encuentra activo o no admite cierre remoto.")
            return False
        elif status is None:
            log_error(f"Fallo de conexión con {self.ip} ({body})")
            return False
        else:
            log_error(f"Error al terminar [{norm_app}] (Código {status}): {body}")
            return False

    def check_status(self, app_name: str = "YouTube") -> Optional[str]:
        """Consulta el estado detallado de una aplicación."""
        norm_app = normalize_app_name(app_name)

        if self.is_cast:
            cast = self._get_cast_connection()
            if cast:
                active_app = cast.app_display_name or (cast.status.display_name if hasattr(cast.status, 'display_name') else None)
                if active_app and active_app.lower() == norm_app.lower():
                    log_success(f"Estado de {Style.BOLD}{norm_app}{Style.RESET}: {Style.GREEN}EN EJECUCIÓN (RUNNING){Style.RESET}")
                    return "running"
                elif active_app:
                    log_info(f"App activa en {self.name}: {Style.YELLOW}{active_app}{Style.RESET} (No {norm_app})")
                    return "other_app"
                else:
                    log_info(f"Estado en {self.name}: {Style.YELLOW}INACTIVO / PANTALLA PRINCIPAL{Style.RESET}")
                    return "stopped"

        # DIAL GET
        status, body, _ = self.send_dial_request(norm_app, method="GET")
        if status == 200:
            state = "unknown"
            state_match = re.search(r"<state>(.*?)</state>", body, re.IGNORECASE)
            if state_match:
                state = state_match.group(1).strip().lower()

            allow_stop = "options allowstop=\"true\"" in body.lower()
            run_link_match = re.search(r"<link\s+rel=[\"']run[\"']\s+href=[\"'](.*?)[\"']", body, re.IGNORECASE)
            run_link = run_link_match.group(1).strip() if run_link_match else None

            if state == "running":
                log_success(f"Estado de {Style.BOLD}{norm_app}{Style.RESET}: {Style.GREEN}EN EJECUCIÓN (RUNNING){Style.RESET}")
            elif state == "stopped":
                log_info(f"Estado de {Style.BOLD}{norm_app}{Style.RESET}: {Style.YELLOW}DETENIDA (STOPPED){Style.RESET}")
            elif state == "hidden":
                log_info(f"Estado de {Style.BOLD}{norm_app}{Style.RESET}: {Style.CYAN}EN SEGUNDO PLANO (HIDDEN){Style.RESET}")
            else:
                log_info(f"Estado de {Style.BOLD}{norm_app}{Style.RESET}: {state.upper()}")

            stop_badge = f"{Style.GREEN}SÍ (allowStop=true){Style.RESET}" if allow_stop else f"{Style.RED}NO (allowStop=false){Style.RESET}"
            print(f"   {Style.DIM}├─ Cierre remoto admitido:{Style.RESET} {stop_badge}")
            if run_link:
                print(f"   {Style.DIM}└─ Instancia de ejecución:{Style.RESET} {run_link}")
            return state
        elif status == 404:
            log_warn(f"La app '{norm_app}' no parece estar instalada o no soporta DIAL en este dispositivo.")
            return "not_found"
        elif status is None:
            log_error(f"Fallo de conexión con {self.ip}: {body}")
            return None
        else:
            log_error(f"Error al consultar '{norm_app}' (Código {status}): {body}")
            return None

    def get_device_info(self) -> Dict[str, str]:
        """Extrae la ficha técnica y metadatos del dispositivo mediante UPnP / DIAL Recon."""
        info = {
            "friendly_name": self.name,
            "manufacturer": "Desconocido",
            "model_name": "Dispositivo Genérico",
            "model_number": "N/A",
            "model_description": "N/A",
            "udn": "N/A",
            "dial_ver": "N/A",
            "app_url": self.base_dial_url,
            "ip": self.ip,
            "port": str(self.port),
            "protocol": self.protocol_label
        }

        xml_data = None
        urls_to_try = []
        if getattr(self, "location", None):
            urls_to_try.append(self.location)
        urls_to_try.extend([
            f"http://{self.ip}:{self.port}/dd.xml",
            f"http://{self.ip}:8008/ssdp/device-desc.xml",
            f"http://{self.ip}:8008/setup/eureka_info"
        ])

        for u in urls_to_try:
            try:
                req = urllib.request.Request(u, headers={"User-Agent": "NetStrike-TV-Injector/3.0"})
                with urllib.request.urlopen(req, timeout=1.8) as resp:
                    app_h = resp.headers.get("Application-URL")
                    if app_h:
                        info["app_url"] = app_h
                    content = resp.read().decode("utf-8", errors="ignore")
                    if "<device>" in content or "<root" in content or "eureka_info" in u:
                        xml_data = content
                        break
            except Exception:
                continue

        if xml_data:
            def extract_tag(tag: str) -> Optional[str]:
                m = re.search(rf"<{tag}>(.*?)</{tag}>", xml_data, re.IGNORECASE)
                return m.group(1).strip() if m else None

            fn = extract_tag("friendlyName")
            if fn: info["friendly_name"] = fn
            man = extract_tag("manufacturer")
            if man: info["manufacturer"] = man
            mn = extract_tag("modelName")
            if mn: info["model_name"] = mn
            mnum = extract_tag("modelNumber")
            if mnum: info["model_number"] = mnum
            desc = extract_tag("modelDescription")
            if desc: info["model_description"] = desc
            udn = extract_tag("UDN")
            if udn: info["udn"] = udn
            dial_ver_match = re.search(r"(?:dial:dialVer|dialVer)=[\"'](.*?)[\"']", xml_data, re.IGNORECASE)
            if dial_ver_match:
                info["dial_ver"] = dial_ver_match.group(1).strip()

        return info

    def print_device_info(self):
        """Muestra una ficha técnica estructurada y táctica en terminal."""
        log_info("Extrayendo telemetría y ficha técnica del objetivo...")
        data = self.get_device_info()
        print(f"\n{Style.CYAN}{'─'*52}{Style.RESET}")
        print(f" {Style.BOLD}[FICHA TÉCNICA // DIAL & HARDWARE RECON]{Style.RESET}")
        print(f"{Style.CYAN}{'─'*52}{Style.RESET}")
        print(f"  {Style.BOLD}Dispositivo    :{Style.RESET} {Style.WHITE}{data['friendly_name']}{Style.RESET}")
        print(f"  {Style.BOLD}Fabricante     :{Style.RESET} {data['manufacturer']}")
        print(f"  {Style.BOLD}Modelo         :{Style.RESET} {data['model_name']} ({data['model_number']})")
        print(f"  {Style.BOLD}Descripción    :{Style.RESET} {data['model_description']}")
        print(f"  {Style.BOLD}Dirección IP   :{Style.RESET} {Style.GREEN}{data['ip']}:{data['port']}{Style.RESET}")
        print(f"  {Style.BOLD}Protocolo      :{Style.RESET} {data['protocol']}")
        print(f"  {Style.BOLD}Versión DIAL   :{Style.RESET} {Style.YELLOW}{data['dial_ver']}{Style.RESET}")
        print(f"  {Style.BOLD}DIAL Endpoint  :{Style.RESET} {data['app_url']}")
        print(f"  {Style.BOLD}Identificador  :{Style.RESET} {Style.DIM}{data['udn']}{Style.RESET}")
        print(f"{Style.CYAN}{'─'*52}{Style.RESET}\n")

    def scan_dial_apps(self) -> List[Dict[str, any]]:
        """Audita las aplicaciones DIAL instaladas y activas en el dispositivo objetivo."""
        log_info(f"Iniciando auditoría de endpoints DIAL en {Style.BOLD}{self.name}{Style.RESET} ({self.ip})...")
        print(f" {Style.DIM}Nota: DIAL solo reporta apps con receptor multiscreen activo en el puerto 8009.{Style.RESET}\n")
        results = []
        for item in DIAL_AUDIT_APPS:
            display_name = item[0]
            app_keys = item[1] if isinstance(item[1], list) else [item[1]]

            matched = False
            for app_key in app_keys:
                status, body, _ = self.send_dial_request(app_key, method="GET")
                if status == 200:
                    state = "unknown"
                    state_match = re.search(r"<state>(.*?)</state>", body, re.IGNORECASE)
                    if state_match:
                        state = state_match.group(1).strip().lower()
                    allow_stop = "options allowstop=\"true\"" in body.lower()
                    results.append({
                        "name": display_name,
                        "key": app_key,
                        "installed": True,
                        "state": state,
                        "allow_stop": allow_stop
                    })
                    if state == "running":
                        state_label = f"{Style.GREEN}[EJECUTÁNDOSE]{Style.RESET}"
                    elif state == "hidden":
                        state_label = f"{Style.CYAN}[EN SEGUNDO PLANO / SISTEMA]{Style.RESET}"
                    else:
                        state_label = f"{Style.YELLOW}[DETENIDO / DISPONIBLE]{Style.RESET}"
                    stop_str = " (Admite cierre)" if allow_stop else ""
                    print(f"  {Style.GREEN}[+]{Style.RESET} {Style.BOLD}{display_name:18}{Style.RESET} -> {state_label}{stop_str}")
                    matched = True
                    break
                elif status == 403:
                    results.append({
                        "name": display_name,
                        "key": app_key,
                        "installed": True,
                        "state": "protected",
                        "allow_stop": False
                    })
                    print(f"  {Style.YELLOW}[~]{Style.RESET} {Style.BOLD}{display_name:18}{Style.RESET} -> {Style.YELLOW}[PROTEGIDO / REGISTRADO EN TV]{Style.RESET}")
                    matched = True
                    break
                time.sleep(0.04)

            if not matched:
                results.append({
                    "name": display_name,
                    "key": app_keys[0],
                    "installed": False,
                    "state": "not_exposed",
                    "allow_stop": False
                })
                print(f"  {Style.DIM}[-] {display_name:18} -> Sin soporte DIAL / No expuesta en red{Style.RESET}")
            time.sleep(0.04)

        installed_count = sum(1 for r in results if r["installed"])
        print(f"\n{Style.CYAN}{'─'*52}{Style.RESET}")
        log_success(f"Auditoría completada: {Style.BOLD}{installed_count}{Style.RESET} servicio(s) DIAL registrado(s).")
        print(f"{Style.CYAN}{'─'*52}{Style.RESET}\n")
        return results

    def get_now_playing_title(self) -> Optional[str]:
        """Obtiene el título del contenido en reproducción (en dispositivos Cast)."""
        if self.is_cast:
            try:
                cast = self._get_cast_connection(timeout=2.0)
                if cast:
                    cast.media_controller.update_status()
                    time.sleep(0.3)
                    return cast.media_controller.status.title
            except Exception:
                pass
        return None

    def _check_roku(self) -> bool:
        """Verifica si el dispositivo responde como Roku (puerto 8060)."""
        if self._is_roku is not None:
            return self._is_roku
        try:
            req = urllib.request.Request(f"http://{self.ip}:8060/", method="GET")
            with urllib.request.urlopen(req, timeout=0.8) as resp:
                self._is_roku = (resp.getcode() == 200)
                return self._is_roku
        except Exception:
            self._is_roku = False
            return False

    def _send_roku_keypress(self, key: str) -> bool:
        """Envía comandos de tecla a Roku mediante External Control Protocol (ECP)."""
        url = f"http://{self.ip}:8060/keypress/{key}"
        try:
            req = urllib.request.Request(url, data=b"", method="POST")
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                return resp.getcode() == 200
        except Exception:
            return False

    def _resolve_upnp_urls(self):
        """Descubre las controlURLs de RenderingControl y AVTransport en el descriptor UPnP."""
        if self._rendering_control_url and self._av_transport_url:
            return

        xml_data = None
        base_url = f"http://{self.ip}:{self.port}"
        if self.location:
            try:
                parsed = urllib.parse.urlparse(self.location)
                base_url = f"{parsed.scheme}://{parsed.netloc}"
                req = urllib.request.Request(self.location, headers={"User-Agent": "NetStrike-TV-Injector/3.0"})
                with urllib.request.urlopen(req, timeout=1.5) as resp:
                    xml_data = resp.read().decode("utf-8", errors="ignore")
            except Exception:
                pass

        if not xml_data:
            candidates = [
                f"http://{self.ip}:{self.port}/dd.xml",
                f"http://{self.ip}:8008/ssdp/device-desc.xml",
                f"http://{self.ip}:8080/description.xml",
                f"http://{self.ip}:7676/smp_2_"
            ]
            for test_u in candidates:
                try:
                    req = urllib.request.Request(test_u, headers={"User-Agent": "NetStrike-TV-Injector/3.0"})
                    with urllib.request.urlopen(req, timeout=0.8) as resp:
                        xml_data = resp.read().decode("utf-8", errors="ignore")
                        parsed = urllib.parse.urlparse(test_u)
                        base_url = f"{parsed.scheme}://{parsed.netloc}"
                        break
                except Exception:
                    continue

        if xml_data:
            rc_match = re.search(r"<serviceType>(?:urn:schemas-upnp-org:service:RenderingControl:1|RenderingControl)</serviceType>.*?<controlURL>(.*?)</controlURL>", xml_data, re.DOTALL | re.IGNORECASE)
            if rc_match:
                ctrl = rc_match.group(1).strip()
                self._rendering_control_url = ctrl if ctrl.startswith("http") else urllib.parse.urljoin(base_url, ctrl)

            av_match = re.search(r"<serviceType>(?:urn:schemas-upnp-org:service:AVTransport:1|AVTransport)</serviceType>.*?<controlURL>(.*?)</controlURL>", xml_data, re.DOTALL | re.IGNORECASE)
            if av_match:
                ctrl = av_match.group(1).strip()
                self._av_transport_url = ctrl if ctrl.startswith("http") else urllib.parse.urljoin(base_url, ctrl)

        if not self._rendering_control_url:
            self._rendering_control_url = f"http://{self.ip}:{self.port}/upnp/control/RenderingControl1"
        if not self._av_transport_url:
            self._av_transport_url = f"http://{self.ip}:{self.port}/upnp/control/AVTransport1"

    def _send_soap_action(self, control_url: str, service_type: str, action: str, body_xml: str) -> Tuple[bool, str]:
        """Envía una llamada SOAP UPnP a una Smart TV."""
        soap_req = (
            '<?xml version="1.0" encoding="utf-8"?>\r\n'
            '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">\r\n'
            f'<s:Body>\r\n{body_xml}\r\n</s:Body>\r\n'
            '</s:Envelope>'
        ).encode("utf-8")

        headers = {
            "Content-Type": 'text/xml; charset="utf-8"',
            "SOAPAction": f'"{service_type}#{action}"',
            "Content-Length": str(len(soap_req)),
            "User-Agent": "NetStrike-TV-Injector/3.0"
        }

        req = urllib.request.Request(control_url, data=soap_req, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                resp_text = resp.read().decode("utf-8", errors="ignore")
                return True, resp_text
        except urllib.error.HTTPError as e:
            return False, e.read().decode("utf-8", errors="ignore")
        except Exception as e:
            return False, str(e)

    def get_volume_status(self) -> Tuple[int, bool]:
        """Retorna (porcentaje_0_100, muted_bool) consultando Google Cast o UPnP/DIAL."""
        if self.is_cast:
            try:
                cast = self._get_cast_connection(timeout=2.0)
                if cast and hasattr(cast, 'status') and cast.status:
                    pct = int(round((cast.status.volume_level or 0.0) * 100))
                    muted = bool(cast.status.volume_muted)
                    return pct, muted
            except Exception:
                pass
            return 0, False

        # Modo DIAL: UPnP RenderingControl
        self._resolve_upnp_urls()
        if self._rendering_control_url:
            body = (
                '<u:GetVolume xmlns:u="urn:schemas-upnp-org:service:RenderingControl:1">'
                '<InstanceID>0</InstanceID><Channel>Master</Channel>'
                '</u:GetVolume>'
            )
            ok, resp = self._send_soap_action(self._rendering_control_url, "urn:schemas-upnp-org:service:RenderingControl:1", "GetVolume", body)
            if ok:
                m = re.search(r"<CurrentVolume>(\d+)</CurrentVolume>", resp, re.IGNORECASE)
                if m:
                    self._dial_volume_estimate = int(m.group(1))

            body_m = (
                '<u:GetMute xmlns:u="urn:schemas-upnp-org:service:RenderingControl:1">'
                '<InstanceID>0</InstanceID><Channel>Master</Channel>'
                '</u:GetMute>'
            )
            ok_m, resp_m = self._send_soap_action(self._rendering_control_url, "urn:schemas-upnp-org:service:RenderingControl:1", "GetMute", body_m)
            if ok_m:
                m_m = re.search(r"<CurrentMute>([01]|true|false)</CurrentMute>", resp_m, re.IGNORECASE)
                if m_m:
                    self._dial_mute_estimate = m_m.group(1).lower() in ("1", "true")

        return self._dial_volume_estimate, self._dial_mute_estimate

    def set_volume_percentage(self, percent: int) -> bool:
        """Establece el volumen a un porcentaje exacto (0-100) en Cast o DIAL / Smart TV."""
        val_pct = max(0, min(100, percent))

        if self.is_cast:
            cast = self._get_cast_connection()
            if not cast:
                return False
            try:
                val = val_pct / 100.0
                cast.set_volume(val)
                log_success(f"Volumen fijado al {val_pct}% en Cast.")
                return True
            except Exception as e:
                log_error(f"Error al fijar volumen: {e}")
                return False

        # Modo DIAL: Roku ECP
        if self._check_roku():
            diff = val_pct - self._dial_volume_estimate
            key = "VolumeUp" if diff > 0 else "VolumeDown"
            for _ in range(min(15, abs(diff))):
                self._send_roku_keypress(key)
                time.sleep(0.04)
            self._dial_volume_estimate = val_pct
            log_success(f"Volumen ajustado al {val_pct}% vía Roku ECP.")
            return True

        # Modo DIAL: UPnP RenderingControl
        self._resolve_upnp_urls()
        if self._rendering_control_url:
            body = (
                '<u:SetVolume xmlns:u="urn:schemas-upnp-org:service:RenderingControl:1">'
                f'<InstanceID>0</InstanceID><Channel>Master</Channel><DesiredVolume>{val_pct}</DesiredVolume>'
                '</u:SetVolume>'
            )
            ok, _ = self._send_soap_action(self._rendering_control_url, "urn:schemas-upnp-org:service:RenderingControl:1", "SetVolume", body)
            if ok:
                self._dial_volume_estimate = val_pct
                log_success(f"Volumen fijado al {val_pct}% en Smart TV (UPnP).")
                return True

        self._dial_volume_estimate = val_pct
        log_info(f"Nivel de ganancia actualizado a {val_pct}%.")
        return True

    def change_volume(self, delta: float) -> bool:
        """Ajusta el volumen de forma incremental (+ / -) en Cast o DIAL / Smart TV."""
        if self.is_cast:
            cast = self._get_cast_connection()
            if not cast:
                return False
            current = cast.status.volume_level or 0.0
            new_vol = max(0.0, min(1.0, current + delta))
            cast.set_volume(new_vol)
            log_success(f"Volumen ajustado al {int(new_vol * 100)}%")
            return True

        # Modo DIAL: Roku
        if self._check_roku():
            key = "VolumeUp" if delta > 0 else "VolumeDown"
            steps = max(1, int(round(abs(delta) * 10)))
            for _ in range(steps):
                self._send_roku_keypress(key)
                time.sleep(0.05)
            self._dial_volume_estimate = max(0, min(100, self._dial_volume_estimate + int(delta * 100)))
            log_success(f"Volumen ajustado en Roku ({key}) -> ~{self._dial_volume_estimate}%")
            return True

        # Modo DIAL: UPnP RenderingControl
        new_vol_pct = max(0, min(100, self._dial_volume_estimate + int(delta * 100)))
        return self.set_volume_percentage(new_vol_pct)

    def toggle_mute(self) -> bool:
        """Silencia o reactiva el audio (MUTE) en Cast o DIAL / Smart TV."""
        if self.is_cast:
            cast = self._get_cast_connection()
            if not cast:
                return False
            new_mute = not cast.status.volume_muted
            cast.set_volume_muted(new_mute)
            log_success("Audio silenciado (MUTE)" if new_mute else "Audio reactivado")
            return True

        # Modo DIAL: Roku
        if self._check_roku():
            ok = self._send_roku_keypress("VolumeMute")
            if ok:
                self._dial_mute_estimate = not self._dial_mute_estimate
                log_success("Audio silenciado (MUTE)" if self._dial_mute_estimate else "Audio reactivado")
                return True

        # Modo DIAL: UPnP RenderingControl
        self._resolve_upnp_urls()
        if self._rendering_control_url:
            new_mute = not self._dial_mute_estimate
            body = (
                '<u:SetMute xmlns:u="urn:schemas-upnp-org:service:RenderingControl:1">'
                f'<InstanceID>0</InstanceID><Channel>Master</Channel><DesiredMute>{1 if new_mute else 0}</DesiredMute>'
                '</u:SetMute>'
            )
            ok, _ = self._send_soap_action(self._rendering_control_url, "urn:schemas-upnp-org:service:RenderingControl:1", "SetMute", body)
            if ok:
                self._dial_mute_estimate = new_mute
                log_success("Audio silenciado (MUTE)" if new_mute else "Audio reactivado")
                return True

        self._dial_mute_estimate = not self._dial_mute_estimate
        log_success("Audio silenciado (MUTE)" if self._dial_mute_estimate else "Audio reactivado")
        return True

    def media_control(self, action: str) -> bool:
        """Envía comandos multimedia (play, pause, stop) en Cast o DIAL / Smart TV."""
        action_clean = action.strip().lower()

        if self.is_cast:
            cast = self._get_cast_connection()
            if not cast:
                return False
            mc = cast.media_controller
            if action_clean == "play":
                mc.play()
                log_success("Comando PLAY transmitido a Google Cast.")
            elif action_clean == "pause":
                mc.pause()
                log_success("Comando PAUSE transmitido a Google Cast.")
            elif action_clean == "stop":
                mc.stop()
                log_success("Comando STOP transmitido a Google Cast.")
            return True

        # Modo DIAL: Roku ECP
        if self._check_roku():
            roku_key = "Stop" if action_clean == "stop" else "Play"
            ok = self._send_roku_keypress(roku_key)
            if ok:
                log_success(f"Comando [{action_clean.upper()}] transmitido a Roku.")
                return True

        # Modo DIAL: UPnP AVTransport (Samsung, LG, Sony, etc.)
        self._resolve_upnp_urls()
        if self._av_transport_url:
            if action_clean == "play":
                body = (
                    '<u:Play xmlns:u="urn:schemas-upnp-org:service:AVTransport:1">'
                    '<InstanceID>0</InstanceID><Speed>1</Speed>'
                    '</u:Play>'
                )
                ok, _ = self._send_soap_action(self._av_transport_url, "urn:schemas-upnp-org:service:AVTransport:1", "Play", body)
                if ok:
                    log_success("Comando PLAY transmitido vía UPnP AVTransport.")
                    return True
            elif action_clean == "pause":
                body = (
                    '<u:Pause xmlns:u="urn:schemas-upnp-org:service:AVTransport:1">'
                    '<InstanceID>0</InstanceID>'
                    '</u:Pause>'
                )
                ok, _ = self._send_soap_action(self._av_transport_url, "urn:schemas-upnp-org:service:AVTransport:1", "Pause", body)
                if ok:
                    log_success("Comando PAUSE transmitido vía UPnP AVTransport.")
                    return True
            elif action_clean == "stop":
                body = (
                    '<u:Stop xmlns:u="urn:schemas-upnp-org:service:AVTransport:1">'
                    '<InstanceID>0</InstanceID>'
                    '</u:Stop>'
                )
                ok, _ = self._send_soap_action(self._av_transport_url, "urn:schemas-upnp-org:service:AVTransport:1", "Stop", body)
                if ok:
                    log_success("Comando STOP transmitido vía UPnP AVTransport.")
                    return True

        log_warn(f"Comando [{action_clean.upper()}] transmitido hacia el target.")
        return True

# ==============================================================================
# MENÚ INTERACTIVO
# ==============================================================================

def limpiar_pantalla():
    """Limpia la pantalla de la consola para mantener una interfaz fija y limpia."""
    if sys.stdout.isatty():
        print("\033[H\033[J", end="", flush=True)

HEADER_TEXT = f"""{Style.CYAN}{'─'*52}{Style.RESET}
       {Style.BOLD}{Style.GREEN}              NET-STRIKE{Style.RESET}
{Style.CYAN}{'─'*52}{Style.RESET}"""

def make_volume_bar(level_pct: int, length: int = 15) -> str:
    """Genera una barra visual de volumen en texto."""
    filled = int(round((level_pct / 100.0) * length))
    filled = max(0, min(length, filled))
    bar = "█" * filled + "░" * (length - filled)
    return f"[{bar}] {level_pct}%"

def subinterfaz_volumen(remote: SmartTVRemote):
    """Interfaz persistente para control de volumen continuo hasta que el usuario decida salir."""
    while True:
        limpiar_pantalla()
        pct, muted = remote.get_volume_status()
        mute_label = f"{Style.RED}[SILENCIADO / MUTE]{Style.RESET}" if muted else f"{Style.GREEN}[ACTIVO]{Style.RESET}"
        bar = make_volume_bar(pct)

        print(HEADER_TEXT)
        print(f" {Style.BOLD}[CONTROL DE VOLUMEN]{Style.RESET} - {Style.BOLD}{remote.name}{Style.RESET}")
        print(f" Nivel: {Style.BOLD}{bar}{Style.RESET} | Audio: {mute_label}")
        print(f"{Style.CYAN}{'─'*52}{Style.RESET}")
        print(f"  {Style.BOLD}[+]{Style.RESET} Subir volumen (+10%)")
        print(f"  {Style.BOLD}[-]{Style.RESET} Bajar volumen (-10%)")
        print(f"  {Style.BOLD}[m]{Style.RESET} Silenciar / Reactivar audio (Mute)")
        print(f"  {Style.BOLD}[0-100]{Style.RESET} Fijar porcentaje exacto (ej. 50)")
        print(f"  {Style.BOLD}[q]{Style.RESET} Volver al menú principal")
        print(f"{Style.CYAN}{'─'*52}{Style.RESET}")

        try:
            cmd = input(f"{Style.BOLD}[VOLUMEN]> {Style.RESET}").strip().lower()
        except (KeyboardInterrupt, EOFError):
            break

        if not cmd or cmd in ("q", "0", "salir", "exit", "volver"):
            break

        if all(c == "+" for c in cmd):
            remote.change_volume(0.10 * len(cmd))
            time.sleep(0.3)
        elif all(c == "-" for c in cmd):
            remote.change_volume(-0.10 * len(cmd))
            time.sleep(0.3)
        elif cmd == "m":
            remote.toggle_mute()
            time.sleep(0.3)
        elif cmd.isdigit():
            val = int(cmd)
            if 0 <= val <= 100:
                remote.set_volume_percentage(val)
                time.sleep(0.3)
            else:
                log_warn("El valor debe estar entre 0 y 100.")
                time.sleep(1.0)
        else:
            log_warn("Comando no válido. Usa [+] [-] [m] [0-100] o [q].")
            time.sleep(1.0)

def subinterfaz_multimedia(remote: SmartTVRemote):
    """Interfaz persistente para controles multimedia continuos."""
    while True:
        limpiar_pantalla()
        title = remote.get_now_playing_title() or "En espera / Sin título activo"

        print(HEADER_TEXT)
        print(f" {Style.BOLD}[CONTROLES MULTIMEDIA]{Style.RESET} - {Style.BOLD}{remote.name}{Style.RESET}")
        print(f" Stream: {Style.WHITE}{Style.BOLD}{title}{Style.RESET}")
        print(f"{Style.CYAN}{'─'*52}{Style.RESET}")
        print(f"  {Style.BOLD}[1]{Style.RESET} Reanudar (Play)")
        print(f"  {Style.BOLD}[2]{Style.RESET} Pausar (Pause)")
        print(f"  {Style.BOLD}[3]{Style.RESET} Detener stream (Stop)")
        print(f"  {Style.BOLD}[q]{Style.RESET} Volver al menú principal")
        print(f"{Style.CYAN}{'─'*52}{Style.RESET}")

        try:
            cmd = input(f"{Style.BOLD}[MULTIMEDIA]> {Style.RESET}").strip().lower()
        except (KeyboardInterrupt, EOFError):
            break

        if not cmd or cmd in ("q", "0", "salir", "exit", "volver"):
            break

        if cmd in ("1", "play", "p"):
            remote.media_control("play")
            time.sleep(0.4)
        elif cmd in ("2", "pause", "pausa"):
            remote.media_control("pause")
            time.sleep(0.4)
        elif cmd in ("3", "stop", "detener"):
            remote.media_control("stop")
            time.sleep(0.4)
        else:
            log_warn("Comando no válido. Usa [1] [2] [3] o [q].")
            time.sleep(1.0)

def menu_interactivo(remote: SmartTVRemote):
    """Menú interactivo limpio por selección numérica con interfaz fija."""
    while True:
        limpiar_pantalla()
        print(HEADER_TEXT)
        tipo_badge = f"{Style.MAGENTA}[Cast-Protocol]{Style.RESET}" if remote.is_cast else f"{Style.BLUE}[DIAL-Protocol]{Style.RESET}"

        print(f" {Style.BOLD}[TARGET]{Style.RESET} {Style.BOLD}{remote.name}{Style.RESET} ({Style.GREEN}{remote.ip}{Style.RESET}) {tipo_badge}")

        if remote.is_cast:
            current_title = remote.get_now_playing_title()
            if current_title:
                print(f" {Style.MAGENTA}[ACTIVE-STREAM]{Style.RESET} {Style.WHITE}{Style.BOLD}{current_title}{Style.RESET}")

        print(f"{Style.CYAN}{'─'*52}{Style.RESET}")
        if remote.is_cast:
            print(f"  {Style.BOLD}[1]{Style.RESET} Encender TV")
            print(f"  {Style.BOLD}[2]{Style.RESET} YouTube (Reproducir Contenido)")
            print(f"  {Style.BOLD}[3]{Style.RESET} Netflix (Reproducir Contenido)")
            print(f"  {Style.BOLD}[4]{Style.RESET} Consultar estado de una app (YouTube / Netflix)")
            print(f"  {Style.BOLD}[5]{Style.RESET} Cerrar / Abortar app activa (YouTube / Netflix)")
            print(f"  {Style.BOLD}[6]{Style.RESET} Control de Volumen (+ / - / Silencio)")
            print(f"  {Style.BOLD}[7]{Style.RESET} Controles Multimedia (Play / Pausa / Stop)")
            print(f"  {Style.BOLD}[8]{Style.RESET} Auditar apps soportadas en la TV (DIAL App Recon)")
            print(f"  {Style.BOLD}[9]{Style.RESET} Ficha técnica e info del dispositivo (DIAL / UPnP)")
            print(f"  {Style.BOLD}[10]{Style.RESET} Cambiar Target / Re-escanear subred")
            print(f"  {Style.BOLD}[11]{Style.RESET} Salir")
            rango_op = "1-11"
        else:
            print(f"  {Style.BOLD}[1]{Style.RESET} Encender TV")
            print(f"  {Style.BOLD}[2]{Style.RESET} YouTube (Reproducir Contenido)")
            print(f"  {Style.BOLD}[3]{Style.RESET} Netflix (Reproducir Contenido)")
            print(f"  {Style.BOLD}[4]{Style.RESET} Consultar estado de una app (YouTube / Netflix)")
            print(f"  {Style.BOLD}[5]{Style.RESET} Cerrar / Abortar app activa (YouTube / Netflix)")
            print(f"  {Style.BOLD}[6]{Style.RESET} Auditar apps soportadas en la TV (DIAL App Recon)")
            print(f"  {Style.BOLD}[7]{Style.RESET} Ficha técnica e info del dispositivo (DIAL / UPnP)")
            print(f"  {Style.BOLD}[8]{Style.RESET} Cambiar Target / Re-escanear subred")
            print(f"  {Style.BOLD}[9]{Style.RESET} Salir")
            rango_op = "1-9"

        print(f"{Style.CYAN}{'─'*52}{Style.RESET}")

        try:
            opcion = input(f"{Style.BOLD}Selecciona una opción [{rango_op}]: {Style.RESET}").strip().lstrip("0") or "0"
        except (KeyboardInterrupt, EOFError):
            print(f"\n\n{Style.YELLOW}[!] Sesión abortada por el operador.{Style.RESET}")
            sys.exit(0)

        print()

        if opcion == "1":
            remote.turn_on()
            time.sleep(1.8)

        elif opcion == "2":
            try:
                enlace = input(f" {Style.BOLD}Pega la URL o ID del vídeo (Enter para solo abrir YouTube): {Style.RESET}").strip()
                if enlace:
                    remote.play_youtube(enlace)
                else:
                    remote.launch_app("YouTube")
                time.sleep(1.8)
            except (KeyboardInterrupt, EOFError):
                pass

        elif opcion == "3":
            try:
                enlace = input(f" {Style.BOLD}ID o enlace de película/serie Netflix (Enter para solo abrir): {Style.RESET}").strip()
                if enlace:
                    remote.play_netflix(enlace)
                else:
                    remote.launch_app("Netflix")
                time.sleep(1.8)
            except (KeyboardInterrupt, EOFError):
                pass

        elif opcion == "4":
            try:
                app_target = input(f" {Style.BOLD}Nombre de la app a consultar [YouTube]: {Style.RESET}").strip() or "YouTube"
                remote.check_status(app_target)
                input(f"\n {Style.DIM}Presiona Enter para continuar...{Style.RESET}")
            except (KeyboardInterrupt, EOFError):
                pass

        elif opcion == "5":
            try:
                app_target = input(f" {Style.BOLD}Nombre de la app a cerrar [YouTube]: {Style.RESET}").strip() or "YouTube"
                remote.stop_app(app_target)
                time.sleep(1.8)
            except (KeyboardInterrupt, EOFError):
                pass

        elif remote.is_cast and opcion == "6":
            subinterfaz_volumen(remote)

        elif remote.is_cast and opcion == "7":
            subinterfaz_multimedia(remote)

        elif (remote.is_cast and opcion == "8") or (not remote.is_cast and opcion == "6"):
            remote.scan_dial_apps()
            try:
                input(f" {Style.DIM}Presiona Enter para continuar...{Style.RESET}")
            except (KeyboardInterrupt, EOFError):
                pass

        elif (remote.is_cast and opcion == "9") or (not remote.is_cast and opcion == "7"):
            remote.print_device_info()
            try:
                input(f" {Style.DIM}Presiona Enter para continuar...{Style.RESET}")
            except (KeyboardInterrupt, EOFError):
                pass

        elif (remote.is_cast and opcion == "10") or (not remote.is_cast and opcion == "8"):
            print(f"  {Style.BOLD}[a]{Style.RESET} Escanear automáticamente en la red WiFi")
            print(f"  {Style.BOLD}[b]{Style.RESET} Escribir IP manualmente")
            sub = input(f" {Style.BOLD}Elige [a/b]: {Style.RESET}").strip().lower()

            if sub == "a":
                log_info("Escaneando subred local...")
                encontrados = discover_devices(timeout=2.5)
                if encontrados:
                    log_success(f"Se detectaron {len(encontrados)} objetivo(s):")
                    for idx, dev in enumerate(encontrados, 1):
                        badge = f"{Style.MAGENTA}[Cast]{Style.RESET}" if dev["is_cast"] else f"{Style.BLUE}[DIAL]{Style.RESET}"
                        print(f"   [{idx}] {Style.BOLD}{dev['name']}{Style.RESET} {badge} (IP: {dev['ip']})")
                    sel = input(f"\n {Style.BOLD}Selecciona número de objetivo (Enter para cancelar): {Style.RESET}").strip()
                    if sel.isdigit() and 1 <= int(sel) <= len(encontrados):
                        elegido = encontrados[int(sel) - 1]
                        remote.ip = elegido["ip"]
                        remote.port = int(elegido["port"])
                        remote.name = elegido["name"]
                        remote.is_cast = elegido["is_cast"]
                        remote.location = elegido.get("location")
                        remote._cast_client = None
                        remote._rendering_control_url = None
                        remote._av_transport_url = None
                        remote._is_roku = None
                        log_success(f"Target actualizado a '{remote.name}' ({remote.ip})")
                        time.sleep(1.5)
                else:
                    log_warn("No se detectaron objetivos por auto-descubrimiento.")
                    time.sleep(1.5)
            elif sub == "b":
                nueva_ip = input(f" {Style.BOLD}Ingresa la nueva IP [{remote.ip}]: {Style.RESET}").strip()
                if nueva_ip:
                    remote.ip = nueva_ip
                    remote.name = f"Target ({nueva_ip})"
                    remote.is_cast = is_google_cast_device(nueva_ip, timeout=1.0)
                    remote.location = None
                    remote._cast_client = None
                    remote._rendering_control_url = None
                    remote._av_transport_url = None
                    remote._is_roku = None
                    log_success(f"IP actualizada a {remote.ip} (Tipo: {remote.protocol_label})")
                    time.sleep(1.5)

        elif (remote.is_cast and opcion == "11") or (not remote.is_cast and opcion == "9"):
            print(f"{Style.YELLOW}[!] Sesión finalizada por el operador. Desconectado.{Style.RESET}")
            sys.exit(0)

        else:
            log_warn(f"Opción no válida. Selecciona [{rango_op}].")
            time.sleep(1.2)

def seleccionar_dispositivo_inicio() -> SmartTVRemote:
    """
    Escanea la subred al inicio y permite al usuario elegir qué objetivo controlar.
    """
    while True:
        limpiar_pantalla()
        print(HEADER_TEXT)
        log_info("Iniciando reconocimiento de subred local...")

        encontrados = discover_devices(timeout=2.5)

        print(f"\n{Style.BOLD}[*] Objetivos detectados en la subred:{Style.RESET}")
        opciones = []

        if encontrados:
            for idx, dev in enumerate(encontrados, 1):
                badge = f"{Style.MAGENTA}[Cast/Android TV]{Style.RESET}" if dev["is_cast"] else f"{Style.BLUE}[Fire TV/DIAL]{Style.RESET}"
                print(f"  {Style.BOLD}[{idx}]{Style.RESET} {Style.BOLD}{dev['name']}{Style.RESET} {badge} ({Style.GREEN}{dev['ip']}{Style.RESET})")
                opciones.append(dev)
        else:
            log_warn("No se detectaron objetivos automáticamente.")

        idx_manual = len(opciones) + 1
        idx_reintentar = len(opciones) + 2
        idx_salir = len(opciones) + 3

        print(f"  {Style.BOLD}[{idx_manual}]{Style.RESET} Asignar IP de objetivo manualmente")
        print(f"  {Style.BOLD}[{idx_reintentar}]{Style.RESET} Re-escanear subred")
        print(f"  {Style.BOLD}[{idx_salir}]{Style.RESET} Abortar / Salir")
        print(f"{Style.CYAN}{'─'*52}{Style.RESET}")

        try:
            sel = input(f"{Style.BOLD}Selecciona objetivo [1-{idx_salir}]: {Style.RESET}").strip()
        except (KeyboardInterrupt, EOFError):
            print(f"\n\n{Style.YELLOW}[!] Sesión abortada por el operador.{Style.RESET}")
            sys.exit(0)

        if not sel.isdigit():
            log_warn("Por favor ingresa un número de la lista.")
            time.sleep(1)
            continue

        sel_num = int(sel)

        if 1 <= sel_num <= len(opciones):
            elegido = opciones[sel_num - 1]
            log_success(f"Objetivo fijado: {Style.BOLD}{elegido['name']}{Style.RESET} ({elegido['ip']})")
            return SmartTVRemote(
                ip=elegido["ip"],
                port=int(elegido["port"]),
                name=elegido["name"],
                is_cast=elegido["is_cast"],
                location=elegido.get("location")
            )
        elif sel_num == idx_manual:
            ip_manual = input(f"\n{Style.BOLD}[NET-STRIKE]> Ingresa la dirección IP del objetivo: {Style.RESET}").strip()
            if ip_manual:
                is_cast = is_google_cast_device(ip_manual, timeout=1.0)
                name = f"Target ({ip_manual})"
                return SmartTVRemote(ip=ip_manual, port=DEFAULT_DIAL_PORT, name=name, is_cast=is_cast)
            else:
                log_warn("IP no válida.")
        elif sel_num == idx_reintentar:
            continue
        elif sel_num == idx_salir:
            print(f"{Style.YELLOW}[!] Sesión abortada por el operador. ¡Hasta luego!{Style.RESET}")
            sys.exit(0)
        else:
            log_warn("Opción fuera de rango.")
            time.sleep(1)

# ==============================================================================
# ENTRADA PRINCIPAL Y CLI DIRECTO
# ==============================================================================
def main():
    parser = argparse.ArgumentParser(
        description="NET-STRIKE // Smart-TV Exploit & Payload Injector Framework (DIAL / Google Cast).",
        epilog="Si no se pasan argumentos directos, se despliega la consola interactiva con escaneo de subred."
    )
    parser.add_argument("--ip", default=None, help="Dirección IP del dispositivo objetivo")
    parser.add_argument("--port", type=int, default=DEFAULT_DIAL_PORT, help=f"Puerto del servicio (por defecto: {DEFAULT_DIAL_PORT})")
    parser.add_argument("--scan", action="store_true", help="Escanear la subred local para descubrir targets y salir")
    parser.add_argument("--turn-on", action="store_true", help="Inyectar pulso de encendido / activación HDMI-CEC")
    parser.add_argument("--play", metavar="URL_OR_ID", help="Inyectar y reproducir stream en YouTube (URL o ID)")
    parser.add_argument("--netflix", metavar="ID_OR_URL", help="Inyectar y reproducir stream en Netflix (ID o URL de contenido)")
    parser.add_argument("--launch", metavar="APP", help="Desplegar una aplicación objetivo (ej. YouTube, Netflix, PrimeVideo)")
    parser.add_argument("--stop", metavar="APP", nargs="?", const="YouTube", help="Abortar/terminar proceso activo")
    parser.add_argument("--status", metavar="APP", nargs="?", const="YouTube", help="Auditar el estado detallado de un proceso/app")
    parser.add_argument("--device-info", action="store_true", help="Consultar ficha técnica y reconocimiento UPnP/DIAL del target")
    parser.add_argument("--app-scan", action="store_true", help="Auditar y listar aplicaciones soportadas en el target (DIAL App Recon)")
    parser.add_argument("--volume", metavar="+/-", choices=["+", "-"], help="Modificar ganancia de volumen (+/-) [Cast / DIAL / Smart TV]")
    parser.add_argument("--mute", action="store_true", help="Silenciar o reactivar audio [Cast / DIAL / Smart TV]")
    parser.add_argument("--media", choices=["play", "pause", "stop"], help="Control multimedia: play, pause o stop [Cast / DIAL / Smart TV]")

    args = parser.parse_args()

    if args.scan:
        log_info("Escaneando subred local en busca de dispositivos Smart TV...")
        encontrados = discover_devices(timeout=3.0)
        if encontrados:
            log_success(f"Se detectaron {len(encontrados)} objetivo(s):")
            for dev in encontrados:
                badge = "[Cast/Android TV]" if dev["is_cast"] else "[Fire TV/DIAL]"
                print(f"   [+] {Style.BOLD}{dev['name']}{Style.RESET} {badge} -> IP: {dev['ip']}:{dev['port']}")
        else:
            log_warn("No se detectaron respuestas en la subred.")
        sys.exit(0)

    # Si se llamó con argumentos CLI directos pero sin IP, escanear para elegir el primero o pedir IP
    if args.turn_on or args.play or args.netflix or args.launch or args.stop or args.status or args.device_info or args.app_scan or args.volume or args.mute or args.media:
        target_ip = args.ip
        target_location = None
        if not target_ip:
            log_info("Buscando dispositivo en la subred...")
            devs = discover_devices(timeout=2.5)
            if devs:
                target_ip = devs[0]["ip"]
                target_port = int(devs[0]["port"])
                target_name = devs[0]["name"]
                target_cast = devs[0]["is_cast"]
                target_location = devs[0].get("location")
                log_info(f"Target fijado: {target_name} ({target_ip})")
            else:
                log_error("No se encontró ningún target automáticamente. Especifica uno con --ip <IP>.")
                sys.exit(1)
        else:
            target_port = args.port
            target_name = f"Dispositivo ({target_ip})"
            target_cast = is_google_cast_device(target_ip)

        remote = SmartTVRemote(ip=target_ip, port=target_port, name=target_name, is_cast=target_cast, location=target_location)

        if args.turn_on:
            success = remote.turn_on()
            sys.exit(0 if success else 1)
        if args.play:
            success = remote.play_youtube(args.play)
            sys.exit(0 if success else 1)
        if args.netflix:
            success = remote.play_netflix(args.netflix)
            sys.exit(0 if success else 1)
        if args.launch:
            success = remote.launch_app(args.launch)
            sys.exit(0 if success else 1)
        if args.stop:
            success = remote.stop_app(args.stop)
            sys.exit(0 if success else 1)
        if args.status:
            res = remote.check_status(args.status)
            sys.exit(0 if res == "running" else (1 if res is None else 2))
        if args.device_info:
            remote.print_device_info()
            sys.exit(0)
        if args.app_scan:
            remote.scan_dial_apps()
            sys.exit(0)
        if args.volume:
            delta = 0.10 if args.volume == "+" else -0.10
            success = remote.change_volume(delta)
            sys.exit(0 if success else 1)
        if args.mute:
            success = remote.toggle_mute()
            sys.exit(0 if success else 1)
        if args.media:
            success = remote.media_control(args.media)
            sys.exit(0 if success else 1)

    # Modo Interactivo: Siempre inicia escaneando y seleccionando la pantalla deseada
    if args.ip:
        is_cast_target = is_google_cast_device(args.ip)
        remote = SmartTVRemote(ip=args.ip, port=args.port, name=f"Dispositivo ({args.ip})", is_cast=is_cast_target)
    else:
        remote = seleccionar_dispositivo_inicio()

    try:
        menu_interactivo(remote)
    except (KeyboardInterrupt, EOFError):
        print(f"\n\n{Style.YELLOW}[!] Sesión abortada por el operador.{Style.RESET}")
        sys.exit(0)

if __name__ == "__main__":
    main()