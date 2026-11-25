"""Servidor web local (100 % offline / LAN) para espejar telemetría en tablets.

Usa únicamente la biblioteca estándar de Python (``http.server`` + Server-Sent
Events) y entrega una interfaz HTML5/Canvas completamente autocontenida sin
CDNs ni conexión a internet. Funciona en cualquier hotspot Wi-Fi local.
"""

from __future__ import annotations

import json
import os
import queue
import socket
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

from .protocol import Telemetry, telemetry_to_dict

_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOGO_PATH = os.path.join(_ROOT_DIR, "docs", "insignia-pepe-el-pollo-nobg.png")

_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<title>CanSat · Pepe el Pollo · Tablet</title>
<style>
  :root{
    --bg:#080e17; --card:#0f1826; --widget:#152234; --border:#2a415e; --text:#dde7f2;
    --dim:#8ea4bc; --accent:#5b9bd5; --ok:#2e9e6e; --warn:#c89643; --err:#c4525a;
  }
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,sans-serif;padding:12px}
  header{position:sticky;top:8px;z-index:10;display:flex;flex-wrap:wrap;align-items:center;
         justify-content:space-between;gap:10px;padding:10px 14px;background:var(--card);
         border:1px solid var(--border);border-radius:10px;margin-bottom:12px}
  .brand{display:flex;align-items:center;gap:12px}
  .badge3d-wrap{width:48px;height:48px;perspective:420px;flex-shrink:0}
  .badge3d{width:100%;height:100%;position:relative;transform-style:preserve-3d;
           animation:spin3d 6s linear infinite}
  .badge3d img{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;
               filter:drop-shadow(0 0 3px rgba(91,155,213,.35))}
  .badge3d .back{transform:rotateY(180deg) translateZ(2px);filter:brightness(.82)}
  .badge3d .front{transform:translateZ(2px)}
  @keyframes spin3d{from{transform:rotateY(0deg)}to{transform:rotateY(360deg)}}
  h1{font-size:15px;letter-spacing:1px}
  .brand-sub{font-size:11px;color:var(--accent);margin-top:2px}
  .pill{font-family:monospace;font-size:12px;padding:4px 10px;border-radius:999px;background:var(--widget);
        border:1px solid var(--border);color:var(--dim)}
  .pill.ok{background:#122e22;border-color:#2e9e6e;color:#7de0b4}
  .pill.warn{background:#2e2412;border-color:#c89643;color:#e5bd73}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(135px,1fr));gap:10px;margin-bottom:12px}
  .card{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:10px 12px}
  .lbl{font-size:11px;color:var(--dim);letter-spacing:.6px}
  .val{font-family:monospace;font-size:22px;font-weight:700;margin-top:4px;color:var(--accent)}
  .sub{font-family:monospace;font-size:11px;color:var(--dim);margin-top:2px}
  .panels{display:grid;grid-template-columns:1.3fr 1fr;gap:12px}
  @media (max-width:820px){.panels{grid-template-columns:1fr}}
  .panel{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:10px}
  .panel h2{font-size:12px;color:var(--dim);margin-bottom:8px;letter-spacing:.7px;display:flex;justify-content:space-between}
  canvas{width:100%;height:260px;display:block;background:#0c1522;border:1px solid #1e3148;border-radius:8px}
</style>
</head>
<body>
<header>
  <div class="brand">
    <div class="badge3d-wrap">
      <div class="badge3d">
        <img class="front" src="/logo.png" alt="Pepe el Pollo">
        <img class="back"  src="/logo.png" alt="Pepe el Pollo">
      </div>
    </div>
    <div>
      <h1>PEPE EL POLLO</h1>
      <div class="brand-sub">CanSat · Estación Tablet (LAN Offline)</div>
    </div>
  </div>
  <div style="display:flex;gap:8px;flex-wrap:wrap">
    <span id="badge-link" class="pill">CONECTANDO...</span>
    <span id="badge-stage" class="pill">ACOPLADO</span>
    <span id="badge-rf" class="pill">RF: --</span>
  </div>
</header>

<section class="grid">
  <div class="card"><div class="lbl">ALTITUD</div><div id="v-alt" class="val">--</div><div id="v-max" class="sub">máx -- m</div></div>
  <div class="card"><div class="lbl">VELOCIDAD VERT.</div><div id="v-vel" class="val">--</div><div class="sub">m/s</div></div>
  <div class="card"><div class="lbl">ACELERACIÓN</div><div id="v-acc" class="val">--</div><div class="sub">m/s²</div></div>
  <div class="card"><div class="lbl">TEMPERATURA</div><div id="v-temp" class="val">--</div><div class="sub">°C</div></div>
  <div class="card"><div class="lbl">PRESIÓN</div><div id="v-pres" class="val">--</div><div class="sub">hPa</div></div>
  <div class="card"><div class="lbl">BATERÍA</div><div id="v-vol" class="val">--</div><div id="v-pkt" class="sub">pkt 0</div></div>
</section>

<section class="panels">
  <div class="panel">
    <h2><span>PERFIL DE ALTITUD (LÍNEA 28 m)</span><span id="v-state">PRE-LANZAMIENTO</span></h2>
    <canvas id="chart"></canvas>
  </div>
  <div class="panel">
    <h2><span>CANSAT 3D · DESACOPLE</span><span id="v-att">P 0 · R 0 · Y 0</span></h2>
    <canvas id="view3d"></canvas>
  </div>
</section>

<script>
const STATES = ["PRE-LANZAMIENTO","ASCENSO","DESCENSO","ATERRIZAJE","FIN DE MISIÓN"];
const DEPLOY_LIMIT_M = 28.0;
const history = [];
let maxAlt = 0;
let latest = {pitch:0, roll:0, yaw:0, decoupled:false};
let sepProg = 0;
let rotorAng = 0;

function el(id){ return document.getElementById(id); }

function drawChart(){
  const c = el("chart"), ctx = c.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const w = c.clientWidth, h = c.clientHeight;
  if(c.width !== w*dpr || c.height !== h*dpr){ c.width = w*dpr; c.height = h*dpr; }
  ctx.setTransform(dpr,0,0,dpr,0,0);
  ctx.clearRect(0,0,w,h);

  const pad = {l:42, r:12, t:14, b:22};
  const pw = w - pad.l - pad.r, ph = h - pad.t - pad.b;
  const maxY = Math.max(35, ...history.map(p => p.alt)) * 1.15;

  // Rejilla
  ctx.strokeStyle = "#22364d"; ctx.lineWidth = 1;
  ctx.fillStyle = "#8ea4bc"; ctx.font = "11px monospace";
  for(let i=0;i<=4;i++){
    const y = pad.t + ph * (i/4);
    ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(w-pad.r, y); ctx.stroke();
    ctx.fillText((maxY*(1-i/4)).toFixed(0)+"m", 4, y+4);
  }

  // Línea de despliegue 28 m
  const y28 = pad.t + ph * (1 - DEPLOY_LIMIT_M / maxY);
  ctx.save(); ctx.setLineDash([5,4]); ctx.strokeStyle = "#c98a42";
  ctx.beginPath(); ctx.moveTo(pad.l, y28); ctx.lineTo(w-pad.r, y28); ctx.stroke();
  ctx.fillStyle = "#c98a42"; ctx.fillText("28m", w-pad.r-30, y28-4);
  ctx.restore();

  if(history.length < 2) return;
  ctx.strokeStyle = "#38bdf8"; ctx.lineWidth = 2;
  ctx.beginPath();
  history.forEach((pt, idx) => {
    const x = pad.l + (idx / (history.length - 1)) * pw;
    const y = pad.t + ph * (1 - Math.max(0, pt.alt) / maxY);
    if(idx === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.stroke();
}

function rotPoint(x, y, z, p, r, yw){
  const toR = Math.PI / 180;
  const cp=Math.cos(p*toR), sp=Math.sin(p*toR);
  const cr=Math.cos(r*toR), sr=Math.sin(r*toR);
  const cy=Math.cos(yw*toR), sy=Math.sin(yw*toR);
  // Roll (X)
  let y1 = y*cr - z*sr, z1 = y*sr + z*cr, x1 = x;
  // Pitch (Y)
  let x2 = x1*cp + z1*sp, z2 = -x1*sp + z1*cp, y2 = y1;
  // Yaw (Z)
  return [x2*cy - y2*sy, x2*sy + y2*cy, z2];
}

function project(pt, w, h){
  const scale = Math.min(w, h) * 0.24;
  const persp = 5.2 / (5.2 - pt[1] * 0.6);
  return [w/2 + pt[0]*scale*persp, h/2 - pt[2]*scale*persp];
}

function drawCylinder(ctx, w, h, zTop, zBot, rad, color, dx, dy, dz){
  const seg = 16;
  const top = [], bot = [];
  for(let i=0;i<seg;i++){
    const a = (i/seg)*Math.PI*2;
    const cx = rad*Math.cos(a) + dx, cy = rad*Math.sin(a) + dy;
    top.push(project(rotPoint(cx, cy, zTop+dz, latest.pitch, latest.roll, latest.yaw), w, h));
    bot.push(project(rotPoint(cx, cy, zBot+dz, latest.pitch, latest.roll, latest.yaw), w, h));
  }
  ctx.strokeStyle = color; ctx.fillStyle = color + "33"; ctx.lineWidth = 1.6;
  ctx.beginPath();
  top.forEach((p,i)=> i?ctx.lineTo(p[0],p[1]):ctx.moveTo(p[0],p[1])); ctx.closePath(); ctx.fill(); ctx.stroke();
  ctx.beginPath();
  bot.forEach((p,i)=> i?ctx.lineTo(p[0],p[1]):ctx.moveTo(p[0],p[1])); ctx.closePath(); ctx.fill(); ctx.stroke();
  for(let i=0;i<seg;i+=2){
    ctx.beginPath(); ctx.moveTo(top[i][0],top[i][1]); ctx.lineTo(bot[i][0],bot[i][1]); ctx.stroke();
  }
}

function draw3D(){
  const c = el("view3d"), ctx = c.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const w = c.clientWidth, h = c.clientHeight;
  if(c.width !== w*dpr || c.height !== h*dpr){ c.width = w*dpr; c.height = h*dpr; }
  ctx.setTransform(dpr,0,0,dpr,0,0);
  ctx.clearRect(0,0,w,h);

  const target = latest.decoupled ? 1.0 : 0.0;
  sepProg += (target - sepProg) * 0.08;
  if(sepProg > 0.15) rotorAng = (rotorAng + 12 * sepProg) % 360;

  // Etapa secundaria (naranja, cae en -Z al desacoplarse)
  drawCylinder(ctx, w, h, -0.58, -1.06, 0.35, "#e08e45", 0.1*sepProg, 0, -1.15*sepProg);
  // Etapa primaria (azul)
  drawCylinder(ctx, w, h, 0.56, -0.56, 0.36, "#4da3ff", 0, 0, 0);

  // 3 palas del autogiro en z = +0.62
  const hub = project(rotPoint(0, 0, 0.64, latest.pitch, latest.roll, latest.yaw), w, h);
  const open = 0.2 + 0.95 * sepProg;
  const zTip = 0.64 - 0.75 * (1 - sepProg);
  ctx.strokeStyle = "#e6eef8"; ctx.lineWidth = 3;
  for(let i=0;i<3;i++){
    const a = ((i*120 + rotorAng) * Math.PI) / 180;
    const tip = project(rotPoint(Math.cos(a)*open, Math.sin(a)*open, zTip,
                                 latest.pitch, latest.roll, latest.yaw), w, h);
    ctx.beginPath(); ctx.moveTo(hub[0], hub[1]); ctx.lineTo(tip[0], tip[1]); ctx.stroke();
  }
  requestAnimationFrame(draw3D);
}

function connect(){
  const es = new EventSource("/events");
  es.onopen = () => {
    const b = el("badge-link"); b.textContent = "ENLACE LAN OK"; b.className = "pill ok";
  };
  es.onerror = () => {
    const b = el("badge-link"); b.textContent = "RECONECTANDO..."; b.className = "pill warn";
  };
  es.onmessage = (ev) => {
    const d = JSON.parse(ev.data);
    maxAlt = Math.max(maxAlt, d.altitude_m || 0);
    el("v-alt").textContent  = d.altitude_m.toFixed(1) + " m";
    el("v-max").textContent  = "máx " + maxAlt.toFixed(1) + " m";
    el("v-vel").textContent  = (d.velocity_ms >= 0 ? "+" : "") + d.velocity_ms.toFixed(2);
    el("v-acc").textContent  = (d.accel_ms2 >= 0 ? "+" : "") + d.accel_ms2.toFixed(2);
    el("v-temp").textContent = d.temperature_c.toFixed(1);
    el("v-pres").textContent = d.pressure_hpa.toFixed(1);
    const batPct = Math.max(0, Math.min(100, Math.round((d.voltage_v - 6.5) / 2.5 * 100)));
    el("v-vol").textContent  = `${d.voltage_v.toFixed(2)} V (${batPct}%)`;
    el("v-pkt").textContent  = "pkt " + d.packet;
    el("v-state").textContent = STATES[d.state] || ("S" + d.state);
    el("v-att").textContent  = `P ${d.pitch_deg.toFixed(1)} · R ${d.roll_deg.toFixed(1)} · Y ${d.yaw_deg.toFixed(1)}`;
    el("badge-rf").textContent = (d.rssi_dbm !== null)
      ? `RF: ${d.rssi_dbm.toFixed(1)} dBm / SNR ${d.snr_db !== null ? d.snr_db.toFixed(1) : "--"} dB`
      : "RF: --";

    const decoupled = Boolean(d.satellite || d.chute || (d.state === 2 && d.altitude_m <= DEPLOY_LIMIT_M));
    latest = {pitch: d.pitch_deg, roll: d.roll_deg, yaw: d.yaw_deg, decoupled};
    const stBadge = el("badge-stage");
    stBadge.textContent = decoupled ? "DESACOPLADO · AUTOGIRO" : "ACOPLADO";
    stBadge.className = decoupled ? "pill ok" : "pill";

    history.push({t: d.mission_time_s, alt: d.altitude_m});
    if(history.length > 300) history.shift();
    drawChart();
  };
}

connect();
draw3D();
</script>
</body>
</html>
"""


def get_lan_ip() -> str:
    """Devuelve la IP LAN activa (funciona también en hotspot sin internet)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "127.0.0.1"


class WebMirrorServer:
    """Servidor HTTP + SSE en segundo plano para visualizar telemetría en tablets."""

    def __init__(self, host: str = "0.0.0.0", port: int = 8000) -> None:
        self.host = host
        self.port = int(port)
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._clients_lock = threading.Lock()
        self._clients: list[queue.Queue[str]] = []
        self._last_payload: Optional[str] = None

    @property
    def url(self) -> str:
        return f"http://{get_lan_ip()}:{self.port}"

    def start(self) -> bool:
        if self._server is not None or self.port <= 0:
            return False

        mirror = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):  # noqa: A002
                return

            def do_GET(self):  # noqa: N802
                if self.path in ("/", "/index.html"):
                    body = _DASHBOARD_HTML.encode("utf-8")
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return

                if self.path == "/logo.png":
                    if os.path.exists(_LOGO_PATH):
                        data = open(_LOGO_PATH, "rb").read()
                        self.send_response(HTTPStatus.OK)
                        self.send_header("Content-Type", "image/png")
                        self.send_header("Cache-Control", "max-age=3600")
                        self.send_header("Content-Length", str(len(data)))
                        self.end_headers()
                        self.wfile.write(data)
                        return
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return

                if self.path == "/events":
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Connection", "keep-alive")
                    self.end_headers()

                    q: queue.Queue[str] = queue.Queue(maxsize=32)
                    with mirror._clients_lock:
                        mirror._clients.append(q)
                        initial = mirror._last_payload
                    if initial:
                        try:
                            self.wfile.write(f"data: {initial}\n\n".encode("utf-8"))
                            self.wfile.flush()
                        except OSError:
                            pass
                    try:
                        while True:
                            try:
                                payload = q.get(timeout=15.0)
                                self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                            except queue.Empty:
                                self.wfile.write(b": keepalive\n\n")
                            self.wfile.flush()
                    except (OSError, BrokenPipeError, ConnectionResetError):
                        pass
                    finally:
                        with mirror._clients_lock:
                            if q in mirror._clients:
                                mirror._clients.remove(q)
                    return

                self.send_error(HTTPStatus.NOT_FOUND)

        try:
            self._server = ThreadingHTTPServer((self.host, self.port), Handler)
        except OSError:
            self._server = None
            return False

        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="CanSatWebMirror",
            daemon=True,
        )
        self._thread.start()
        return True

    def publish(self, telemetry: Telemetry) -> None:
        """Envía el paquete más reciente a todas las tablets conectadas."""
        if self._server is None:
            return
        payload = json.dumps(telemetry_to_dict(telemetry), ensure_ascii=False)
        with self._clients_lock:
            self._last_payload = payload
            for q in list(self._clients):
                try:
                    q.put_nowait(payload)
                except queue.Full:
                    try:
                        q.get_nowait()
                        q.put_nowait(payload)
                    except queue.Empty:
                        pass

    def stop(self) -> None:
        if self._server is None:
            return
        try:
            self._server.shutdown()
            self._server.server_close()
        except OSError:
            pass
        self._server = None
        self._thread = None
