# NET-STRIKE

Herramienta de auditoria de red, reconocimiento y control de Smart TVs y dispositivos de streaming en entornos locales.

---

## Descripcion General

Netstrike es una utilidad de linea de comandos disenada para auditar y evaluar la superficie de exposicion de dispositivos Smart TV y dongles de streaming conectados a una misma red de area local (LAN/WLAN). 

Aprovecha implementaciones de protocolos abiertos y no autenticados comunmente presentes en dispositivos de consumo domestico, tales como **DIAL (Discovery and Launch)**, **Google Cast v2**, **YouTube Lounge API** y **UPnP / SSDP**, permitiendo analizar el nivel de control remoto que puede ejercerse sobre pantallas inteligentes sin requerir credenciales de usuario ni emparejamiento previo.

---

## Dispositivos Compatibles

* **Amazon Fire TV / Fire TV Stick** (Protocolo DIAL y YouTube Lounge API).
* **Google Chromecast / Google TV / Android TV** (Protocolos Google Cast v2 y DIAL).
* **Roku TV y Reproductores Roku** (Protocolo DIAL y Roku ECP).
* **Smart TVs Samsung** (Tizen OS / DIAL).
* **Smart TVs LG** (webOS / DIAL).
* **Otras Smart TVs con soporte DIAL / HbbTV** (Sony, TCL, Hisense, Philips, etc.).

---

## Funcionalidades Principales

* **Descubrimiento Automatico de Objetivos**: Escaneo pasivo y activo de la subred local mediante peticiones SSDP/UPnP en multicast (puerto 1900) y deteccion de servicios HTTP Eureka / Cast (puerto 8008).
* **Inyeccion Forzada de Streams**: Proyeccion directa e inmediata de contenidos multimedia en YouTube y Netflix mediante identificadores unicos (IDs) o URLs completas con soporte de marcas de tiempo (timestamps).
* **Sincronizacion en Tiempo Real (YouTube Lounge API)**: Capacidad de modificar el video en reproduccion en caliente sobre pantallas activas sin necesidad de reiniciar la aplicacion.
* **Control y Terminacion de Procesos**: Consulta de estado en tiempo real (ejecutandose, detenido o en segundo plano) y envio de senales de aborto forzado para cerrar aplicaciones remotamente.
* **Encendido Remoto por Hardware**: Inyeccion de senales a traves del bus HDMI-CEC para reactivar televisores en estado de reposo.
* **Auditoria de Endpoints y Apps Expuestas**: Mapeo exhaustivo de servicios DIAL registrados y protegidos en el servidor local de la pantalla.
* **Ficha Tecnica de Hardware**: Extraccion de telemetria del dispositivo, incluyendo fabricante, modelo, numero de serie UDN, endpoints de control y version del daemon DIAL.
* **Control de Volumen y Multimedia**: Interfaz para manipulacion de ganancia de audio y reproduccion en dispositivos compatibles.

---

## Requisitos del Sistema

* Python 3.8 o superior.
* Conectividad a la misma subred local (Wi-Fi o Ethernet) que los dispositivos objetivo.
* Paquetes de Python requeridos (instalables via pip):

```bash
pip install -r requirements.txt
```

---

## Instalacion

1. Clonar el repositorio localmente:

```bash
git clone https://github.com/reivaJAQM/Netstrike.git
cd Netstrike
```

2. Instalar las dependencias:

```bash
pip install -r requirements.txt
```

---

## Modos de Uso

### 1. Modo Interactivo (Consola Táctica)

Al ejecutar la herramienta sin argumentos, Netstrike inicia un escaneo automatico de la red, presenta la lista de pantallas detectadas y despliega un menu interactivo adaptado al protocolo del objetivo:

```bash
python3 netstrike.py
```

* **Dispositivos Fire TV / DIAL:**
  * `[1]` Encender TV
  * `[2]` YouTube (Reproducir Contenido)
  * `[3]` Netflix (Reproducir Contenido)
  * `[4]` Consultar estado de una app (YouTube / Netflix)
  * `[5]` Cerrar / Abortar app activa (YouTube / Netflix)
  * `[6]` Auditar apps soportadas en la TV (DIAL App Recon)
  * `[7]` Ficha tecnica e info del dispositivo (DIAL / UPnP)
  * `[8]` Cambiar Target / Re-escanear subred
  * `[9]` Salir

* **Dispositivos Google Cast / Android TV:**
  * Opciones `[1]` a `[5]` identicas.
  * `[6]` Control de Volumen (+ / - / Silencio).
  * `[7]` Controles Multimedia (Play / Pausa / Stop).
  * Opciones `[8]` a `[11]` para auditoria, ficha tecnica y seleccion de objetivo.

### 2. Modo Automatizado por Linea de Comandos (CLI)

Netstrike puede integrarse en scripts o ejecutarse de forma directa especificando la direccion IP del objetivo y las acciones deseadas:

* **Escanear la red en busca de televisores:**
  ```bash
  python3 netstrike.py --scan
  ```

* **Inyectar un video de YouTube:**
  ```bash
  python3 netstrike.py --ip 192.168.1.50 --play "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
  ```

* **Inyectar contenido en Netflix:**
  ```bash
  python3 netstrike.py --ip 192.168.1.50 --netflix "80057281"
  ```

* **Modificar volumen o silenciar (Cast / Smart TVs compatibles):**
  ```bash
  python3 netstrike.py --ip 192.168.1.50 --volume +
  python3 netstrike.py --ip 192.168.1.50 --mute
  ```

* **Control de reproduccion multimedia:**
  ```bash
  python3 netstrike.py --ip 192.168.1.50 --media pause
  ```

* **Auditar las aplicaciones soportadas por el televisor:**
  ```bash
  python3 netstrike.py --ip 192.168.1.50 --app-scan
  ```

* **Obtener ficha tecnica del hardware:**
  ```bash
  python3 netstrike.py --ip 192.168.1.50 --device-info
  ```

* **Cerrar una aplicacion activa:**
  ```bash
  python3 netstrike.py --ip 192.168.1.50 --stop YouTube
  ```

* **Despertar la pantalla mediante pulso HDMI-CEC:**
  ```bash
  python3 netstrike.py --ip 192.168.1.50 --turn-on
  ```

---

## Consideraciones Tecnicas y de Seguridad

Esta herramienta pone de manifiesto la falta de mecanismos de autenticacion granular en protocolos de red local domesticos como DIAL y Google Cast, los cuales asumen confianza implicita en cualquier host conectado a la red Wi-Fi.

Para mitigar los riesgos derivados de estos protocolos en entornos corporativos o compartidos, se recomienda:
* Habilitar el aislamiento de clientes (AP / Client Isolation) en el router Wi-Fi.
* Segmentar los dispositivos Smart TV e IoT en una VLAN dedicada independiente de la red de usuarios.

---

## Descargo de Responsabilidad

Este software ha sido desarrollado con fines exclusivamente educativos, de investigacion y para pruebas de seguridad autorizadas en dispositivos propios. El autor no se hace responsable del uso indebido o no autorizado que pueda darse a esta herramienta.
