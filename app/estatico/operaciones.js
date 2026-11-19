/* Operaciones del dashboard estático, en paridad exacta con app/analytics.py:
 *   - tormentas(): incidencias masivas por planta/oficina (detectar_tormentas)
 *   - duplicados(): tickets duplicados (detectar_duplicados + difflib.SequenceMatcher)
 *   - fueraDeSla(): Críticas/Altas abiertas más horas de las permitidas (fuera_de_sla)
 * Trabajan sobre los registros ya expandidos por dashboard.js
 * ({id, valida, sev, cat, fecha ISO, zona, codigo, equipo, desc, criterio, campos}). */
"use strict";

const Operaciones = (() => {
  const DIA = 86400000;
  const dias = (a, b) => Math.round((Date.parse(b) - Date.parse(a)) / DIA);   // ISO AAAA-MM-DD
  const cmp = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
  const porFechaId = (x, y) => cmp(x.fecha, y.fecha) || cmp(x.id, y.id);

  // ── difflib.SequenceMatcher(None, a, b, autojunk=False).ratio() ─────────
  function ratio(a, b) {
    a = Array.from(a); b = Array.from(b);                // Puntos de código, como Python
    if (!a.length && !b.length) return 1;
    const b2j = new Map();
    b.forEach((c, j) => { if (!b2j.has(c)) b2j.set(c, []); b2j.get(c).push(j); });
    function masLarga(alo, ahi, blo, bhi) {
      let besti = alo, bestj = blo, best = 0, j2len = new Map();
      for (let i = alo; i < ahi; i++) {
        const nuevo = new Map();
        for (const j of b2j.get(a[i]) || []) {
          if (j < blo) continue;
          if (j >= bhi) break;
          const k = (j2len.get(j - 1) || 0) + 1;
          nuevo.set(j, k);
          if (k > best) { besti = i - k + 1; bestj = j - k + 1; best = k; }
        }
        j2len = nuevo;
      }
      return [besti, bestj, best];
    }
    let iguales = 0;
    const cola = [[0, a.length, 0, b.length]];
    while (cola.length) {
      const [alo, ahi, blo, bhi] = cola.pop();
      const [i, j, k] = masLarga(alo, ahi, blo, bhi);
      if (!k) continue;
      iguales += k;
      if (alo < i && blo < j) cola.push([alo, i, blo, j]);
      if (i + k < ahi && j + k < bhi) cola.push([i + k, ahi, j + k, bhi]);
    }
    return (2 * iguales) / (a.length + b.length);
  }

  const limpio = (t) => Motor.normalizar(t || "").split(/\s+/).filter(Boolean).join(" ");

  function similitud(a, b) {
    a = limpio(a); b = limpio(b);
    return a && b ? ratio(a, b) : 0;
  }

  const sintoma = (r) => (r.criterio ? r.criterio.split(" · ").slice(1).join(" · ") || r.criterio : r.cat);

  function peor(sevs, niveles) {
    const s = new Set(sevs);
    return niveles.find((n) => s.has(n)) || "";
  }

  function masRepetido(valores) {
    const m = new Map();
    for (const v of valores) m.set(v, (m.get(v) || 0) + 1);
    let mejor = null, n = -1;
    for (const [v, c] of m) if (c > n) { mejor = v; n = c; }   // Empate: el primero (Counter)
    return mejor;
  }

  // ── Tormentas ───────────────────────────────────────────────────────────
  function tormentas(registros, minimo, ventana, niveles) {
    const grupos = new Map();
    for (const r of registros) {
      if (!(r.valida && r.fecha && r.zona)) continue;
      const k = `${r.zona}\u0000${r.cat}`;
      if (!grupos.has(k)) grupos.set(k, []);
      grupos.get(k).push(r);
    }
    const salida = [];
    for (const lista of grupos.values()) {
      lista.sort(porFechaId);
      let tramo = [];
      for (const r of [...lista, null]) {
        if (r && tramo.length && dias(tramo[tramo.length - 1].fecha, r.fecha) <= ventana) { tramo.push(r); continue; }
        if (tramo.length >= minimo) salida.push({
          zona: tramo[0].zona, categoria: tramo[0].cat, desde: tramo[0].fecha, hasta: tramo[tramo.length - 1].fecha,
          sintoma: masRepetido(tramo.map(sintoma)), ids: tramo.map((x) => x.id),
          severidad: peor(tramo.map((x) => x.sev), niveles),
        });
        tramo = r ? [r] : [];
      }
    }
    return salida.sort((x, y) => y.ids.length - x.ids.length || cmp(y.hasta, x.hasta));
  }

  // ── Duplicados ──────────────────────────────────────────────────────────
  function duplicados(registros, umbral, margen) {
    const grupos = new Map();
    for (const r of registros) {
      if (!(r.valida && r.fecha)) continue;
      let clave = r.codigo;
      if (!clave && r.equipo) clave = `${Motor.normalizar(r.equipo)} @ ${Motor.normalizar(r.zona)}`;
      if (!clave) continue;
      if (!grupos.has(clave)) grupos.set(clave, []);
      grupos.get(clave).push(r);
    }
    const salida = [];
    for (const [clave, lista] of grupos) {
      if (lista.length < 2) continue;
      lista.sort(porFechaId);
      const padre = lista.map((_, i) => i);
      const raiz = (x) => { while (padre[x] !== x) { padre[x] = padre[padre[x]]; x = padre[x]; } return x; };
      const minima = new Map();
      for (let a = 0; a < lista.length; a++) {
        for (let b = a + 1; b < lista.length; b++) {
          if (dias(lista[a].fecha, lista[b].fecha) > margen) break;
          const s = similitud(lista[a].desc, lista[b].desc);
          if (s >= umbral) {
            const ra = raiz(a), rb = raiz(b);
            const previa = minima.has(ra) ? minima.get(ra) : 1;
            const deB = minima.has(rb) ? minima.get(rb) : 1;
            minima.delete(rb);
            padre[rb] = ra;
            minima.set(ra, Math.min(s, previa, deB));
          }
        }
      }
      const comp = new Map();
      lista.forEach((_, x) => { const r = raiz(x); if (!comp.has(r)) comp.set(r, []); comp.get(r).push(x); });
      for (const miembros of comp.values()) {
        if (miembros.length < 2) continue;
        const regs = miembros.sort((x, y) => x - y).map((x) => lista[x]);
        salida.push({
          equipo: clave, zona: regs[0].zona, desde: regs[0].fecha, hasta: regs[regs.length - 1].fecha,
          ids: regs.map((r) => r.id), descripcion: regs[0].desc,
          similitud: Math.min(...miembros.map((x) => (minima.has(raiz(x)) ? minima.get(raiz(x)) : 1))),
        });
      }
    }
    return salida.sort((x, y) => y.ids.length - x.ids.length || cmp(y.hasta, x.hasta));
  }

  function unicasEstimadas(validas, torm, dups) {
    const redundantes = new Set();
    for (const g of [...torm, ...dups]) g.ids.slice(1).forEach((i) => redundantes.add(i));
    return Math.max(0, validas - redundantes.size);
  }

  // ── SLA ─────────────────────────────────────────────────────────────────
  const RE_MARCA = /^\s*(\d{1,2})\/(\d{1,2})\/(\d{4})\s+(\d{1,2}):(\d{2})(?::(\d{2}))?/;

  function apertura(r) {
    const campo = r.campos.find(([n]) => n === "Marca de temps");
    const m = campo && campo[1] ? RE_MARCA.exec(campo[1]) : null;
    if (m) {
      const [d, mes, a, h, mi, s] = m.slice(1).map((x) => parseInt(x || "0", 10));
      const f = new Date(a, mes - 1, d, h, mi, s);
      if (f.getMonth() === mes - 1 && f.getDate() === d && h < 24 && mi < 60 && s < 60) return f;
    }
    if (!r.fecha) return null;
    const [a, mes, d] = r.fecha.split("-").map(Number);
    return new Date(a, mes - 1, d);
  }

  function fueraDeSla(registros, limites, niveles, ahora = new Date(), seguimiento = {}) {
    const vistos = new Set(), alertas = [];
    for (const r of registros) {
      const limite = limites[r.sev];
      if (!r.valida || limite === undefined || vistos.has(r.id)) continue;
      vistos.add(r.id);
      const estado = (seguimiento[r.id] && seguimiento[r.id].estado) || "Pendiente";
      const desde = apertura(r);
      if (estado === "Resuelta" || !desde) continue;
      const horas = (ahora - desde) / 3600000;
      if (horas > limite) alertas.push({ r, desde, horas, limite, estado });
    }
    return alertas.sort((x, y) => niveles.indexOf(x.r.sev) - niveles.indexOf(y.r.sev) || y.horas - x.horas);
  }

  function duracion(minutos) {
    if (minutos === null || minutos === undefined) return "—";
    minutos = Math.round(minutos);
    if (minutos < 60) return `${minutos} min`;
    let h = Math.floor(minutos / 60);
    const resto = minutos % 60;
    if (h < 48) return resto ? `${h} h ${resto} min` : `${h} h`;
    const d = Math.floor(h / 24); h %= 24;
    return h ? `${d} d ${h} h` : `${d} d`;
  }

  return { ratio, similitud, tormentas, duplicados, unicasEstimadas, fueraDeSla, duracion };
})();
