/* Funciones del modo Técnico del dashboard estático (sin servidor ni conexiones externas).
 *
 *   - Reglas: validar y compilar rules.json igual que app/rules.py, para volver a
 *     analizar el XML en el navegador con reglas nuevas.
 *   - Seguimiento de reparaciones con las marcas de tiempo de app/gestion.py.
 *   - MTTR (app/analytics.calcular_mttr) y registro de auditoría con el formato de audit.log.
 *   - Informe ejecutivo (misma estructura que app/exporter.informe_estado).
 *
 * Lo que cambia el Técnico se guarda en ESTE navegador (localStorage) y se puede
 * descargar como rules.json, gestion.json y audit.log para subirlo al repositorio. */
"use strict";

const Tecnico = (() => {
  // ── Almacenamiento local (nunca lanza: modo privado, cuota llena…) ──────
  const leerLS = (clave, defecto) => {
    try { const v = localStorage.getItem(clave); return v === null ? defecto : JSON.parse(v); } catch (_) { return defecto; }
  };
  const guardarLS = (clave, valor) => {
    try { if (valor === null) localStorage.removeItem(clave); else localStorage.setItem(clave, JSON.stringify(valor)); return true; } catch (_) { return false; }
  };

  // JSON con claves ordenadas (como json.dump(..., sort_keys=True))
  function jsonOrdenado(valor, sangria = 2) {
    const ordenar = (v) => (Array.isArray(v) ? v.map(ordenar)
      : v && typeof v === "object" ? Object.fromEntries(Object.keys(v).sort().map((k) => [k, ordenar(v[k])])) : v);
    return JSON.stringify(ordenar(valor), null, sangria);
  }

  function descargar(nombre, texto, tipo = "text/plain") {
    const url = URL.createObjectURL(new Blob([texto], { type: `${tipo};charset=utf-8` }));
    const a = Object.assign(document.createElement("a"), { href: url, download: nombre });
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  }

  // ── Reglas (app/rules.py) ───────────────────────────────────────────────
  class ErrorReglas extends Error {}
  const normClave = (p) => Motor.normalizar(String(p).replace(/’/g, "'")).trim();
  const ESPECIALES = new Set("()[]{}?*+-|^$\\.&~# \t\n\r\v\f");          // re.escape de Python
  const fragmento = (p) => [...p].map((c) => (c === " " ? "\\s+" : c === "'" || c === "-" ? "['’\\s-]?"
    : ESPECIALES.has(c) ? "\\" + c : c)).join("");

  function compilar(palabras, completa = false) {
    const limpias = [...new Set(palabras.map(normClave).filter(Boolean))]
      .sort((a, b) => [...b].length - [...a].length);
    if (!limpias.length) return "(?!x)x";
    return "(?<![a-z0-9])(?:" + limpias.map(fragmento).join("|") + ")" + (completa ? "(?![a-z0-9])" : "");
  }

  function lista(valor, donde) {
    if (!Array.isArray(valor) || !valor.every((v) => typeof v === "string"))
      throw new ErrorReglas(`«${donde}» debe ser una lista de textos.`);
    const vistas = new Set(), salida = [];
    for (const v of valor) { const c = normClave(v); if (c && !vistas.has(c)) { vistas.add(c); salida.push(c); } }
    return salida;
  }

  const esEntero = (v) => typeof v === "number" && Number.isInteger(v);

  /** Copia limpia y completa de rules.json (validar_datos de Python). */
  function validarReglas(datos, fabrica) {
    if (!datos || typeof datos !== "object" || Array.isArray(datos)) throw new ErrorReglas("El archivo debe contener un objeto JSON.");
    const base = JSON.parse(JSON.stringify(fabrica));
    const anyos = "anyos" in datos ? datos.anyos : base.anyos;
    if (!anyos || typeof anyos !== "object") throw new ErrorReglas("«anyos» debe ser un objeto {minimo, maximo}.");
    const minimo = "minimo" in anyos ? anyos.minimo : 2000;
    let maximo = anyos.maximo ?? null;
    if (!esEntero(minimo) || minimo < 1 || minimo > 9999) throw new ErrorReglas("«anyos.minimo» debe ser un año entre 1 y 9999.");
    if (maximo === 0 || maximo === null) maximo = null;
    else if (!esEntero(maximo) || maximo < 1 || maximo > 9999) throw new ErrorReglas("«anyos.maximo» debe ser un año, 0 o null (= año actual).");
    else if (maximo < minimo) throw new ErrorReglas("«anyos.maximo» no puede ser menor que «anyos.minimo».");
    base.anyos = { minimo, maximo };
    for (const grupo of ["severidad", "lexico_tecnico"]) {
      const g = datos[grupo] ?? {};
      if (!g || typeof g !== "object" || Array.isArray(g)) throw new ErrorReglas(`«${grupo}» debe ser un objeto de listas.`);
      for (const clave of Object.keys(base[grupo])) if (clave in g) base[grupo][clave] = lista(g[clave], `${grupo}.${clave}`);
    }
    if ("marcas" in datos) {
      const m = datos.marcas;
      if (!m || typeof m !== "object" || Array.isArray(m)) throw new ErrorReglas("«marcas» debe ser un objeto {Marca: [alias, ...]}.");
      const limpias = {};
      for (const [nombreBruto, alias] of Object.entries(m)) {
        const nombre = String(nombreBruto).split(/\s+/).filter(Boolean).join(" ");
        if (!nombre) continue;
        const l = lista(alias, `marcas.${nombre}`);
        if (!l.includes(normClave(nombre))) l.unshift(normClave(nombre));
        limpias[nombre] = l;
      }
      base.marcas = limpias;
    }
    return base;
  }

  /** {datos, patrones, marcas}: el bloque config.reglas que entiende Motor.configurar(). */
  function compilarReglas(datos, fabrica) {
    const limpio = validarReglas(datos, fabrica);
    const patrones = {};
    for (const grupo of ["severidad", "lexico_tecnico"])
      for (const [k, l] of Object.entries(limpio[grupo])) patrones[k] = compilar(l);
    return { datos: limpio, patrones, marcas: Object.entries(limpio.marcas).map(([n, a]) => [n, compilar(a, true)]) };
  }

  /** Cambios legibles entre dos versiones de las reglas (audit.cambios_reglas). */
  function cambiosReglas(antes, despues) {
    const cambios = [];
    const dif = (a, d, nombre) => {
      const mas = d.filter((p) => !a.includes(p)), menos = a.filter((p) => !d.includes(p));
      if (mas.length) cambios.push(`${nombre}: +${mas.join(", +")}`);
      if (menos.length) cambios.push(`${nombre}: -${menos.join(", -")}`);
    };
    for (const [campo, nombre] of [["minimo", "año mínimo"], ["maximo", "año máximo"]]) {
      const a = antes.anyos[campo], d = despues.anyos[campo];
      if (a !== d) cambios.push(`${nombre}: ${a || "año actual"} → ${d || "año actual"}`);
    }
    for (const grupo of ["severidad", "lexico_tecnico"])
      for (const k of [...new Set([...Object.keys(antes[grupo]), ...Object.keys(despues[grupo])])].sort())
        dif(antes[grupo][k] || [], despues[grupo][k] || [], k);
    const ma = antes.marcas, md = despues.marcas;
    for (const n of Object.keys(md).filter((n) => !(n in ma)).sort()) cambios.push(`marca añadida: ${n}`);
    for (const n of Object.keys(ma).filter((n) => !(n in md)).sort()) cambios.push(`marca eliminada: ${n}`);
    for (const n of Object.keys(ma).filter((n) => n in md).sort()) dif(ma[n], md[n], `alias de ${n}`);
    return cambios;
  }

  // ── Auditoría (formato de app/audit.py) ─────────────────────────────────
  const CLAVE_AUDIT = "monitor-auditoria";
  const pad = (n) => String(n).padStart(2, "0");
  const fechaHora = (d = new Date()) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  const isoLocal = (d = new Date()) => fechaHora(d).replace(" ", "T");
  const unaLinea = (t) => String(t ?? "").split(/\r\n|\r|\n/).join(" ⏎ ").trim();
  const sinCorchetes = (t) => unaLinea(t).replace(/\[/g, "(").replace(/\]/g, ")");

  function auditar(rol, accion, detalle, ahora = new Date()) {
    const ev = [fechaHora(ahora), sinCorchetes(rol) || "Anónimo", sinCorchetes(accion), unaLinea(detalle)];
    const lista = leerLS(CLAVE_AUDIT, []);
    lista.push(ev);
    guardarLS(CLAVE_AUDIT, lista.slice(-5000));
    return ev;
  }
  const eventos = () => leerLS(CLAVE_AUDIT, []).slice().reverse();              // Más reciente primero
  const textoAuditLog = () => leerLS(CLAVE_AUDIT, []).map(([f, r, a, d]) => `[${f}] [${r}] [${a}] ${d}`).join("\n") + "\n";

  // ── Seguimiento de reparaciones (app/gestion.py) ────────────────────────
  const CLAVE_SEG = "monitor-seguimiento";
  const seguimiento = () => leerLS(CLAVE_SEG, {});

  function actualizarSeguimiento(id, estado, nota, estados, ahora = new Date()) {
    if (!estados.includes(estado)) throw new Error(`Estado no válido: «${estado}».`);
    nota = String(nota ?? "").split(/\s+/).filter(Boolean).join(" ").slice(0, 500);
    const marca = isoLocal(ahora);
    const datos = seguimiento();
    const reg = datos[id] && typeof datos[id] === "object" ? datos[id] : {};
    const anterior = reg.estado || "Pendiente";
    let inicio = reg.fecha_inicio || null, resolucion = reg.fecha_resolucion || null;
    let duracion = typeof reg.duracion_minutos === "number" ? reg.duracion_minutos : null;
    if (estado === "En curso" && !inicio) inicio = marca;                    // Primera vez «En curso»
    if (estado === "Resuelta") {
      if (anterior !== "Resuelta" || !resolucion) {
        resolucion = marca; duracion = null;
        if (inicio) duracion = Math.round(Math.max(0, (ahora - new Date(inicio)) / 60000) * 10) / 10;
      }
    } else { resolucion = null; duracion = null; }                           // Abierta o reabierta
    const historial = (Array.isArray(reg.historial) ? reg.historial : []).slice(-19);
    historial.push({ fecha: marca, estado, nota });
    datos[id] = { estado, nota, actualizado: marca, fecha_inicio: inicio, fecha_resolucion: resolucion,
                  duracion_minutos: duracion, historial };
    if (!guardarLS(CLAVE_SEG, datos)) throw new Error("El navegador no permite guardar datos (¿modo privado?).");
    return { anterior, nota_anterior: reg.nota || "", registro: datos[id] };
  }
  const textoGestion = () => jsonOrdenado(seguimiento()) + "\n";

  /** MTTR global y por severidad (solo válidas resueltas con duración medida). */
  function mttr(registros, seg, niveles) {
    const porNivel = new Map(), vistos = new Set();
    for (const r of registros) {
      if (!r.valida || vistos.has(r.id)) continue;
      vistos.add(r.id);
      const g = seg[r.id];
      if (g && g.estado === "Resuelta" && typeof g.duracion_minutos === "number") {
        if (!porNivel.has(r.sev)) porNivel.set(r.sev, []);
        porNivel.get(r.sev).push(g.duracion_minutos);
      }
    }
    const todas = [...porNivel.values()].flat();
    const media = (l) => l.reduce((a, b) => a + b, 0) / l.length;
    return { minutos: todas.length ? media(todas) : null, resueltas: todas.length,
             porSeveridad: niveles.filter((n) => porNivel.has(n)).map((n) => [n, media(porNivel.get(n)), porNivel.get(n).length]) };
  }

  // ── Reconstruir el XML desde los registros (si no se puede descargar datos.xml) ──
  function xmlDesdeRegistros(registros, etiquetas) {
    const esc = (t) => String(t).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
    const partes = [`<?xml version="1.0" encoding="utf-8"?>\n<${etiquetas.raiz}>`];
    for (const r of registros) {
      const antes = new Map(r.rep.map((x) => [x.campo, x.antes]));            // Valor original
      partes.push(`  <${etiquetas.incidencia} id="${esc(r.id)}">`);
      for (const [n, v] of r.campos) {
        const valor = antes.has(n) ? antes.get(n) : v;
        partes.push(valor === null || valor === undefined
          ? `    <${etiquetas.campo} nom="${esc(n)}" />`
          : `    <${etiquetas.campo} nom="${esc(n)}">${esc(valor)}</${etiquetas.campo}>`);
      }
      partes.push(`  </${etiquetas.incidencia}>`);
    }
    partes.push(`</${etiquetas.raiz}>`);
    return partes.join("\n");
  }

  return { ErrorReglas, normClave, compilar, validarReglas, compilarReglas, cambiosReglas,
           auditar, eventos, textoAuditLog, seguimiento, actualizarSeguimiento, textoGestion,
           mttr, xmlDesdeRegistros, leerLS, guardarLS, jsonOrdenado, descargar, fechaHora };
})();
