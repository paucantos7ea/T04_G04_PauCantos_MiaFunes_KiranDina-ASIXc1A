/* Pantalla de PIN del dashboard estático.
 *
 * La página se abre con <body class="bloqueado">: el panel queda oculto e inerte
 * hasta introducir un PIN cuyo SHA-256("sal:PIN") coincida con una de las huellas
 * embebidas (Consultor o Técnico). El rol se recuerda solo en esta pestaña
 * (sessionStorage). Barrera de cortesía: ver la nota de app/html_builder.py. */
"use strict";

(() => {
  // SHA-256 en JavaScript puro (sin crypto.subtle: así funciona también con file:// y http)
  function sha256(texto) {
    const K = [];
    let n = 2;
    const primo = (x) => { for (let d = 2; d * d <= x; d++) if (x % d === 0) return false; return true; };
    const H = [];
    while (K.length < 64) {
      if (primo(n)) {
        if (H.length < 8) H.push((Math.pow(n, 1 / 2) * 2 ** 32) | 0);
        K.push((Math.pow(n, 1 / 3) * 2 ** 32) | 0);
      }
      n++;
    }
    const bytes = Array.from(new TextEncoder().encode(texto));
    const bits = bytes.length * 8;
    bytes.push(0x80);
    while (bytes.length % 64 !== 56) bytes.push(0);
    for (let i = 7; i >= 0; i--) bytes.push(i >= 4 ? 0 : (bits >>> (i * 8)) & 0xff);
    const rotr = (x, r) => (x >>> r) | (x << (32 - r));
    const W = new Array(64);
    for (let b = 0; b < bytes.length; b += 64) {
      for (let i = 0; i < 16; i++) {
        W[i] = (bytes[b + i * 4] << 24) | (bytes[b + i * 4 + 1] << 16) | (bytes[b + i * 4 + 2] << 8) | bytes[b + i * 4 + 3];
      }
      for (let i = 16; i < 64; i++) {
        const s0 = rotr(W[i - 15], 7) ^ rotr(W[i - 15], 18) ^ (W[i - 15] >>> 3);
        const s1 = rotr(W[i - 2], 17) ^ rotr(W[i - 2], 19) ^ (W[i - 2] >>> 10);
        W[i] = (W[i - 16] + s0 + W[i - 7] + s1) | 0;
      }
      let [a, bb, c, d, e, f, g, h] = H;
      for (let i = 0; i < 64; i++) {
        const t1 = (h + (rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25)) + ((e & f) ^ (~e & g)) + K[i] + W[i]) | 0;
        const t2 = ((rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22)) + ((a & bb) ^ (a & c) ^ (bb & c))) | 0;
        h = g; g = f; f = e; e = (d + t1) | 0; d = c; c = bb; bb = a; a = (t1 + t2) | 0;
      }
      [a, bb, c, d, e, f, g, h].forEach((v, i) => { H[i] = (H[i] + v) | 0; });
    }
    return H.map((v) => (v >>> 0).toString(16).padStart(8, "0")).join("");
  }

  const D = JSON.parse(document.getElementById("datos").textContent);
  const ACCESO = D.acceso || { sal: "", huellas: [] };
  const CLAVE = "monitor-rol-" + ACCESO.sal;
  const $ = (s) => document.querySelector(s);
  const bloqueables = () => document.querySelectorAll("body > header, body > main, body > footer");
  const guardar = (rol) => { try { rol ? sessionStorage.setItem(CLAVE, rol) : sessionStorage.removeItem(CLAVE); } catch (_) { /* sin almacenamiento */ } };
  const recordado = () => { try { return sessionStorage.getItem(CLAVE); } catch (_) { return null; } };
  const ROLES = new Set(ACCESO.huellas.map((h) => h[1]));

  function desbloquear(rol) {
    document.body.classList.remove("bloqueado");
    bloqueables().forEach((n) => n.removeAttribute("inert"));
    $("#acceso").hidden = true;
    $("#rol-activo").textContent = (rol === "Técnico" ? "🛠️ " : "👁️ ") + rol;
    $("#sesion").hidden = false;
    document.documentElement.dataset.rol = rol;
    if (window.Dashboard) { window.Dashboard.ponerRol(rol); window.Dashboard.filtrar(); }  // Chart.js mide ya visible
  }

  // Tecnico es un const global de tecnico.js (no cuelga de window)
  const auditar = (rol, accion, detalle) => { if (typeof Tecnico !== "undefined") Tecnico.auditar(rol, accion, detalle); };

  function bloquear() {
    const rol = document.documentElement.dataset.rol;
    if (rol) auditar(rol, "CIERRE_SESION", `Cierre de sesión de Modo ${rol}`);
    if (window.Dashboard) window.Dashboard.ponerRol(null);
    guardar(null);
    delete document.documentElement.dataset.rol;
    document.body.classList.add("bloqueado");
    bloqueables().forEach((n) => n.setAttribute("inert", ""));
    $("#sesion").hidden = true;
    $("#acceso").hidden = false;
    $("#acceso-pin").value = "";
    $("#acceso-pin").focus();
  }

  let fallos = 0, esperaHasta = 0;
  $("#acceso-form").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const error = $("#acceso-error");
    const restante = Math.ceil((esperaHasta - Date.now()) / 1000);
    if (restante > 0) {
      error.textContent = `Demasiados intentos. Espera ${restante} s.`; error.hidden = false;
      auditar("Anónimo", "ACCESO_FALLIDO", "Intento durante el bloqueo por fuerza bruta");
      return;
    }
    const pin = $("#acceso-pin").value.trim();
    const huella = sha256(`${ACCESO.sal}:${pin}`);
    const acierto = ACCESO.huellas.find((h) => h[0] === huella);
    if (acierto) {
      fallos = 0; error.hidden = true;
      guardar(acierto[1]);
      auditar(acierto[1], "ACCESO", `Inicio de sesión en Modo ${acierto[1]}`);
      desbloquear(acierto[1]);
      return;
    }
    auditar("Anónimo", "ACCESO_FALLIDO", `PIN incorrecto (${pin.length} cifras)`);
    fallos++;
    if (fallos >= 5) { fallos = 0; esperaHasta = Date.now() + 30000; }
    error.textContent = "PIN incorrecto.";
    error.hidden = false;
    $("#acceso-pin").value = "";
  });
  $("#cerrar-sesion").addEventListener("click", bloquear);

  window.Acceso = { sha256 };                          // Para los tests
  const rol = recordado();
  if (rol && ROLES.has(rol)) desbloquear(rol); else bloquear();
})();
