/* Interfaz del dashboard estático: KPIs, gráficos (Chart.js), filtros, lista paginada,
 * modal de auditoría, reglas activas y carga de un XML local. Todo el texto que viene
 * de los datos se escapa con esc() antes de entrar en el HTML. */
"use strict";

(() => {
  const D = JSON.parse(document.getElementById("datos").textContent);
  Motor.configurar(D.config);

  const POR_PAGINA = 15;
  const NIVELES = D.config.niveles;
  const VAR = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const COLOR_NIVEL = { "Crítica": "--critica", "Alta": "--alta", "Media": "--media", "Leve": "--leve" };
  const COLOR_ANOM = {};
  const CAT = D.config.cat, TA = D.config.tipoAnomalia;
  COLOR_ANOM[TA[CAT.vacio]] = "--anom-vacio"; COLOR_ANOM[TA[CAT.fecha]] = "--anom-fecha";
  COLOR_ANOM[TA[CAT.basura]] = "--anom-basura"; COLOR_ANOM[TA[CAT.desborde]] = "--anom-desborde";
  COLOR_ANOM[TA[CAT.sinSentido]] = "--anom-sinsentido";
  const colorDe = (r) => `var(${r.valida ? COLOR_NIVEL[r.sev] || "--ok" : COLOR_ANOM[r.anom[0].tipo] || "--error"})`;

  const $ = (s) => document.querySelector(s);
  const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const num = (n) => n.toLocaleString("es-ES");
  const pct = (a, b) => (b ? `${((a / b) * 100).toFixed(1).replace(".", ",")} %` : "—");
  const dmy = (iso) => (iso ? `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(0, 4)}` : "—");
  const contar = (lista, clave) => {
    const m = new Map();
    for (const x of lista) { const k = clave(x); if (k) m.set(k, (m.get(k) || 0) + 1); }
    return [...m].sort((a, b) => b[1] - a[1]);
  };

  // ── Datos publicados (formato compacto con tabla de cadenas) ───────────
  function expandir(datos) {
    const S = datos.S, s = (i) => (i < 0 ? null : S[i]);
    return datos.I.map((x) => {
      const campos = [];
      for (let i = 0; i < x[18].length; i += 2) campos.push([S[x[18][i]], s(x[18][i + 1])]);
      return {
        id: S[x[0]], valida: !!x[1], sev: s(x[2]), inferida: !!x[3], cat: s(x[4]), marca: s(x[5]),
        equipo: s(x[6]) || "", fecha: s(x[7]), desc: s(x[8]) || "", criterio: s(x[9]), regla: s(x[10]),
        oTipo: s(x[11]), oMarca: s(x[12]), notaInfra: s(x[13]) || "", zona: s(x[14]) || "", codigo: s(x[15]) || "",
        anom: x[16].map((a) => ({ cat: S[a[0]], tipo: TA[S[a[0]]] || S[a[0]], regla: S[a[1]], campo: S[a[2]],
          valor: S[a[3]], extra: S[a[4]], motivo: S[a[5]] })),
        rep: x[17].map((r) => ({ campo: S[r[0]], antes: S[r[1]], despues: S[r[2]], motivo: S[r[3]] })),
        campos,
      };
    });
  }

  function preparar(registros) {
    for (const r of registros)
      r._busca = Motor.normalizar([r.id, ...r.campos.map((c) => c[1] || "")].join(" "));
    return registros;
  }

  const ST = {
    publicados: preparar(expandir(D)), todos: null, filtrados: [], pagina: 1,
    topPor: "equipo", graficos: {}, origen: null, sla: [], idsSla: new Set(), verTodas: false,
    rol: null, reglas: D.config.reglas, seg: Tecnico.seguimiento(), mttr: null, xmlLocal: null,
    reglasLocales: false,
  };
  ST.original = ST.publicados;                    // Análisis publicado por Python (reglas del repo)
  const ESTADOS = D.config.estadosGestion || ["Pendiente", "En curso", "Resuelta"];
  const EMOJI_REP = { "Pendiente": "⏳", "En curso": "🛠️", "Resuelta": "✅" };
  const estadoDe = (r) => (ST.seg[r.id] && ST.seg[r.id].estado) || "Pendiente";
  const esTecnico = () => ST.rol === "Técnico";
  const auditar = (accion, detalle) => Tecnico.auditar(ST.rol || "Anónimo", accion, detalle);
  const SLA = D.config.sla || {}, MAS = D.config.masivas || { minTormenta: 3, ventana: 0, umbral: 0.75, margen: 3 };
  ST.todos = ST.publicados;

  // ── Filtros ────────────────────────────────────────────────────────────
  const F = { texto: $("#f-texto"), estado: $("#f-estado"), sev: $("#f-sev"), cat: $("#f-cat"), marca: $("#f-marca"), anom: $("#f-anom"), rep: $("#f-rep") };

  function rellenarSelect(sel, pares, primero) {
    const actual = sel.value;
    sel.innerHTML = `<option value="">${esc(primero)}</option>` +
      pares.map(([v, n]) => `<option value="${esc(v)}">${esc(v)} (${num(n)})</option>`).join("");
    if ([...sel.options].some((o) => o.value === actual)) sel.value = actual;
  }

  function opciones() {
    const val = ST.todos.filter((r) => r.valida);
    rellenarSelect(F.sev, NIVELES.map((n) => [n, val.filter((r) => r.sev === n).length]), "Toda severidad");
    rellenarSelect(F.cat, contar(ST.todos, (r) => r.cat), "Toda categoría");
    rellenarSelect(F.marca, contar(val, (r) => r.marca), "Toda marca");
    rellenarSelect(F.rep, ESTADOS.map((e) => [e, val.filter((r) => estadoDe(r) === e).length]), "Toda reparación");
    rellenarSelect(F.anom, contar(ST.todos.flatMap((r) => [...new Set(r.anom.map((a) => a.tipo))].map((t) => ({ t }))), (x) => x.t), "Todo tipo de anomalía");
  }

  function filtrar() {
    const q = Motor.normalizar(F.texto.value);
    const { estado, sev, cat, marca, anom, rep } = Object.fromEntries(Object.entries(F).map(([k, el]) => [k, el.value]));
    ST.filtrados = ST.todos.filter((r) => {
      if (q) {
        if (q.startsWith("#")) { if (Motor.normalizar(r.id) !== q.slice(1).trim()) return false; }
        else if (!r._busca.includes(q)) return false;
      }
      if (estado === "validas" && !r.valida) return false;
      if (estado === "bloqueadas" && r.valida) return false;
      if (sev && !(r.valida && r.sev === sev)) return false;
      if (cat && r.cat !== cat) return false;
      if (marca && r.marca !== marca) return false;
      if (anom && !r.anom.some((a) => a.tipo === anom)) return false;
      if (rep && !(r.valida && estadoDe(r) === rep)) return false;
      return true;
    });
    ST.pagina = 1;
    ST.sla = Operaciones.fueraDeSla(ST.filtrados, SLA, NIVELES, new Date(), ST.seg);
    ST.mttr = Tecnico.mttr(ST.filtrados, ST.seg, NIVELES);
    ST.idsSla = new Set(ST.sla.map((a) => a.r.id));
    pintar();
  }

  let espera;
  F.texto.addEventListener("input", () => { clearTimeout(espera); espera = setTimeout(filtrar, 150); });
  for (const el of [F.estado, F.sev, F.cat, F.marca, F.anom, F.rep]) el.addEventListener("change", filtrar);
  $("#f-limpiar").addEventListener("click", () => { for (const el of Object.values(F)) el.value = ""; filtrar(); });

  // ── KPIs ───────────────────────────────────────────────────────────────
  function kpis() {
    const f = ST.filtrados, val = f.filter((r) => r.valida), n = f.length;
    const tarjeta = (et, valor, sub, color, clase = "") =>
      `<div class="kpi ${clase}" style="--color:${color}"><div class="etiqueta">${et}</div><div class="valor">${valor}</div><div class="sub">${sub}</div></div>`;
    $("#kpis").innerHTML =
      tarjeta("Procesadas", num(n), n === ST.todos.length ? "todas" : `de ${num(ST.todos.length)}`, "var(--acento)", "principal") +
      tarjeta("Válidas", num(val.length), pct(val.length, n), "var(--ok)") +
      tarjeta("Bloqueadas", num(n - val.length), pct(n - val.length, n), "var(--error)") +
      NIVELES.map((nv) => tarjeta(nv, num(val.filter((r) => r.sev === nv).length), "válidas", `var(${COLOR_NIVEL[nv]})`)).join("") +
      tarjeta("⏰ Fuera de SLA", num(ST.sla.length), ST.sla.length ? "críticas/altas sin resolver" : "todo dentro de SLA",
              ST.sla.length ? "var(--error)" : "var(--ok)") +
      tarjeta("⏱️ MTTR", Operaciones.duracion(ST.mttr.minutos), `${num(ST.mttr.resueltas)} resueltas medidas`, "var(--anom-fecha)");
  }

  // ── Alerta de SLA (Críticas / Altas abiertas demasiado tiempo) ─────────
  function alertaSla() {
    const limites = Object.entries(SLA).map(([n, h]) => `${n}: ${h} h`).join(" · ");
    const caja = $("#alerta-sla");
    if (!ST.sla.length) {
      caja.innerHTML = `<div class="alerta-sla ok">⏰ Ningún ticket crítico o alto supera su SLA (${esc(limites)}).</div>`;
      return;
    }
    const porNivel = contar(ST.sla, (a) => a.r.sev).map(([n, c]) => `${num(c)} ${n.toLowerCase()}s`).join(" · ");
    const filas = ST.sla.slice(0, 300).map((a) => `<tr data-i="${ST.todos.indexOf(a.r)}">
      <td><strong>#${esc(a.r.id)}</strong></td><td>${esc(a.r.sev)}</td><td>${esc(a.r.zona || "—")}</td>
      <td>${esc(Motor.truncar(a.r.desc, 80))}</td><td class="marca-sla">${Operaciones.duracion(a.horas * 60)}</td></tr>`).join("");
    caja.innerHTML = `<details class="alerta-sla"><summary>⏰ ${num(ST.sla.length)} tickets fuera de SLA sin resolver: ${esc(porNivel)} · Límites: ${esc(limites)}</summary>
      <div class="tabla-envoltorio"><table><thead><tr><th>ID</th><th>Severidad</th><th>Planta / oficina</th><th>Descripción</th><th>Abierta</th></tr></thead>
      <tbody>${filas}</tbody></table></div>
      <p class="nota">Abierta desde la «Marca de temps» del formulario. Desaparecen al marcarlas como «Resuelta» (modo Técnico, en la ficha de la incidencia).${ST.sla.length > 300 ? " Se muestran las 300 primeras." : ""}</p></details>`;
  }
  $("#alerta-sla").addEventListener("click", (e) => {
    const fila = e.target.closest("tr[data-i]");
    if (fila) abrir(ST.todos[+fila.dataset.i]);
  });

  // ── Masivas y duplicadas ───────────────────────────────────────────────
  function masivas() {
    const val = ST.filtrados.filter((r) => r.valida);
    const torm = Operaciones.tormentas(val, MAS.minTormenta, MAS.ventana, NIVELES);
    const dups = Operaciones.duplicados(val, MAS.umbral, MAS.margen);
    const unicas = Operaciones.unicasEstimadas(val.length, torm, dups);
    const fechas = (g) => (g.desde === g.hasta ? dmy(g.desde) : `${dmy(g.desde)} – ${dmy(g.hasta)}`);
    const indice = new Map(ST.todos.map((r, i) => [r.id, i]));
    const botonesIds = (ids) => `<div class="ids">${ids.map((id) => `<button type="button" data-i="${indice.get(id)}">#${esc(id)}</button>`).join("")}</div>`;
    const tarjeta = (et, valor, sub, color) =>
      `<div class="kpi" style="--color:${color}"><div class="etiqueta">${et}</div><div class="valor">${valor}</div><div class="sub">${sub}</div></div>`;

    $("#masivas-nota").textContent = `Un mismo fallo puede llegar como muchos tickets. Tormenta: ≥ ${MAS.minTormenta} incidencias válidas de la misma categoría en la misma planta u oficina ${MAS.ventana ? `a ≤ ${MAS.ventana} días entre sí` : "el mismo día"}. Duplicado: mismo equipo, fechas a ≤ ${MAS.margen} días y descripción con similitud ≥ ${Math.round(MAS.umbral * 100)} %. Se analizan las válidas con los filtros actuales.`;
    $("#masivas-kpis").innerHTML =
      tarjeta("⚡ Tormentas", num(torm.length), `${num(torm.reduce((t, g) => t + g.ids.length, 0))} incidencias`, "var(--error)") +
      tarjeta("👯 Tickets duplicados", num(dups.reduce((t, g) => t + g.ids.length - 1, 0)), `en ${num(dups.length)} grupos`, "var(--alta)") +
      tarjeta("🏢 Plantas afectadas", num(new Set(torm.map((t) => t.zona)).size), "con alguna tormenta", "var(--anom-fecha)") +
      tarjeta("🎯 Fallos reales estimados", num(unicas), `de ${num(val.length)} válidas`, "var(--ok)");

    const porZona = contar(torm.flatMap((t) => t.ids.map(() => t.zona)), (z) => z);
    $("#masivas-grafico").hidden = !porZona.length;
    if (porZona.length && hayChart()) grafico("g-tormentas", {
      type: "bar",
      data: { labels: porZona.map((z) => z[0]), datasets: [{ label: "Incidencias en tormentas", data: porZona.map((z) => z[1]), backgroundColor: VAR("--error"), borderRadius: 6 }] },
      options: opcionesBase({ indexAxis: "y", plugins: { legend: { display: false } } }),
    });

    const visibles = ST.verTodas ? torm : torm.slice(0, 20);
    $("#titulo-tormentas").textContent = `Tormentas de incidencias (${num(torm.length)})`;
    $("#lista-tormentas").innerHTML = torm.length ? visibles.map((t) => `
      <details class="grupo" style="--color:var(${COLOR_NIVEL[t.severidad] || "--error"})">
        <summary><strong>⚡ ${esc(t.zona)}</strong><span class="meta">${fechas(t)} · ${t.ids.length} incidencias · ${esc(t.categoria)} · ${esc(t.sintoma)}</span></summary>
        <p><strong>Planta / oficina:</strong> ${esc(t.zona)} · <strong>Síntoma principal:</strong> ${esc(t.sintoma)} · <strong>Severidad máx.:</strong> ${esc(t.severidad)}</p>
        <p class="nota">IDs afectados (toca uno para ver su ficha):</p>${botonesIds(t.ids)}
      </details>`).join("") + (torm.length > visibles.length ? `<button class="boton mas-grupos" id="ver-todas" type="button">Mostrar las ${num(torm.length)} tormentas</button>` : "")
      : `<p class="vacio">No hay tormentas de incidencias con estos filtros.</p>`;

    $("#titulo-duplicados").textContent = `Tickets duplicados (${num(dups.length)} grupos)`;
    $("#lista-duplicados").innerHTML = dups.length ? dups.map((g) => `
      <details class="grupo" style="--color:var(--alta)">
        <summary><strong>👯 ${esc(g.equipo)}</strong><span class="meta">${esc(g.zona || "—")} · ${fechas(g)} · ${g.ids.length} tickets · similitud ${Math.round(g.similitud * 100)} %</span></summary>
        <p><strong>Original:</strong> #${esc(g.ids[0])} · <strong>Duplicados:</strong> ${g.ids.slice(1).map((i) => "#" + esc(i)).join(", ")}</p>
        <p>«${esc(Motor.truncar(g.descripcion, 200))}»</p>${botonesIds(g.ids)}
      </details>`).join("") : `<p class="vacio">No hay tickets duplicados con estos filtros.</p>`;
  }
  $("#vista-masivas").addEventListener("click", (e) => {
    if (e.target.id === "ver-todas") { ST.verTodas = true; masivas(); return; }
    const b = e.target.closest(".ids button[data-i]");
    if (b) abrir(ST.todos[+b.dataset.i]);
  });

  // ── Gráficos ───────────────────────────────────────────────────────────
  const hayChart = () => typeof window.Chart !== "undefined";

  function grafico(id, config) {
    if (!hayChart()) return;
    const g = ST.graficos[id];
    if (g) { g.data = config.data; g.options = config.options; g.update(); return; }
    ST.graficos[id] = new Chart(document.getElementById(id), config);
  }

  function opcionesBase(extra = {}) {
    const texto = VAR("--texto-suave"), rejilla = VAR("--borde");
    return {
      responsive: true, maintainAspectRatio: false, animation: { duration: 250 },
      plugins: { legend: { labels: { color: texto, boxWidth: 12 } }, tooltip: { intersect: false } },
      scales: {
        x: { ticks: { color: texto }, grid: { color: rejilla } },
        y: { ticks: { color: texto }, grid: { color: rejilla }, beginAtZero: true },
      },
      ...extra,
    };
  }

  function graficos() {
    $("#sin-graficos").hidden = hayChart();
    if (!hayChart()) return;
    const f = ST.filtrados, val = f.filter((r) => r.valida);

    // 1. Donut validez vs. anomalías
    const partes = [["Válidas", val.length, "--ok"]];
    for (const [tipo, n] of contar(f.filter((r) => !r.valida), (r) => r.anom[0].tipo)) partes.push([tipo, n, COLOR_ANOM[tipo] || "--error"]);
    grafico("g-donut", {
      type: "doughnut",
      data: { labels: partes.map((p) => p[0]), datasets: [{ data: partes.map((p) => p[1]), backgroundColor: partes.map((p) => VAR(p[2])), borderColor: VAR("--superficie"), borderWidth: 2 }] },
      options: { responsive: true, maintainAspectRatio: false, cutout: "62%", plugins: { legend: { position: "bottom", labels: { color: VAR("--texto-suave"), boxWidth: 12 } } } },
    });

    // 2. Severidad
    grafico("g-sev", {
      type: "bar",
      data: { labels: NIVELES, datasets: [{ label: "Incidencias", data: NIVELES.map((n) => val.filter((r) => r.sev === n).length), backgroundColor: NIVELES.map((n) => VAR(COLOR_NIVEL[n])), borderRadius: 6 }] },
      options: opcionesBase({ plugins: { legend: { display: false } } }),
    });

    // 3. Evolución mensual apilada por severidad + total
    const meses = [...new Set(val.filter((r) => r.fecha).map((r) => r.fecha.slice(0, 7)))].sort();
    const porMes = (filtro) => meses.map((m) => val.filter((r) => r.fecha && r.fecha.startsWith(m) && filtro(r)).length);
    grafico("g-tiempo", {
      type: "bar",
      data: {
        labels: meses.map((m) => `${m.slice(5)}/${m.slice(0, 4)}`),
        datasets: [
          ...NIVELES.map((n) => ({ label: n, data: porMes((r) => r.sev === n), backgroundColor: VAR(COLOR_NIVEL[n]), stack: "s" })),
          { type: "line", label: "Total", data: porMes(() => true), borderColor: VAR("--texto-suave"), backgroundColor: VAR("--texto-suave"), cubicInterpolationMode: "monotone", pointRadius: 2 },
        ],
      },
      options: opcionesBase({ interaction: { mode: "index", intersect: false },
        scales: { x: { stacked: true, ticks: { color: VAR("--texto-suave") }, grid: { display: false } }, y: { stacked: true, beginAtZero: true, ticks: { color: VAR("--texto-suave") }, grid: { color: VAR("--borde") } } } }),
    });

    // 4. Top equipos / zonas / categorías / marcas
    const top = contar(val, (r) => r[ST.topPor]).slice(0, 10);
    grafico("g-top", {
      type: "bar",
      data: { labels: top.map((t) => Motor.truncar(t[0], 28)), datasets: [{ label: "Averías", data: top.map((t) => t[1]), backgroundColor: VAR("--acento"), borderRadius: 6 }] },
      options: opcionesBase({ indexAxis: "y", plugins: { legend: { display: false } } }),
    });
  }

  $("#g-top-por").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-por]");
    if (!b) return;
    ST.topPor = b.dataset.por;
    for (const x of $("#g-top-por").querySelectorAll("button")) x.setAttribute("aria-pressed", String(x === b));
    graficos();
  });

  // ── Lista paginada: tarjetas (< 768 px) o tabla ────────────────────────
  const escritorio = window.matchMedia("(min-width: 768px)");
  escritorio.addEventListener("change", () => lista());

  function etiquetaResultado(r) {
    return r.valida
      ? `<span class="insignia" style="--color:var(${COLOR_NIVEL[r.sev]})">✔ ${esc(r.sev)}</span>`
      : `<span class="insignia" style="--color:var(${COLOR_ANOM[r.anom[0].tipo] || "--error"})">⛔ ${esc(r.anom[0].tipo)}</span>`;
  }

  function lista() {
    const f = ST.filtrados, paginas = Math.max(1, Math.ceil(f.length / POR_PAGINA));
    ST.pagina = Math.min(Math.max(1, ST.pagina), paginas);
    const trozo = f.slice((ST.pagina - 1) * POR_PAGINA, ST.pagina * POR_PAGINA);
    $("#contador").textContent = `${num(f.length)} incidencias · toca una para ver por qué se clasificó así`;
    const cont = $("#lista");
    if (!trozo.length) {
      cont.innerHTML = `<p class="vacio">Ninguna incidencia con estos filtros.</p>`;
    } else if (escritorio.matches) {
      cont.innerHTML = `<div class="tabla-envoltorio"><table class="registros"><thead><tr>
        <th>ID</th><th>Resultado</th><th>Reparación</th><th>Categoría</th><th>Marca</th><th>Equipo</th><th>Fecha</th><th>Descripción</th></tr></thead><tbody>` +
        trozo.map((r) => `<tr data-i="${ST.todos.indexOf(r)}" tabindex="0">
          <td><strong>${esc(r.id)}</strong>${ST.idsSla.has(r.id) ? ' <span class="marca-sla" title="Fuera de SLA">⏰</span>' : ""}</td><td>${etiquetaResultado(r)}</td><td>${r.valida ? `${EMOJI_REP[estadoDe(r)]} ${esc(estadoDe(r))}` : "—"}</td><td>${esc(r.cat)}</td>
          <td>${esc(Motor.truncar(r.marca, 24) || "—")}</td><td>${esc(Motor.truncar(r.equipo, 24) || "—")}</td><td>${dmy(r.fecha)}</td>
          <td class="desc">${esc(Motor.truncar(r.desc, 110))}</td></tr>`).join("") + `</tbody></table></div>`;
    } else {
      cont.innerHTML = `<div class="tarjetas">` + trozo.map((r) => `
        <button class="registro" data-i="${ST.todos.indexOf(r)}" style="--color:${colorDe(r)}">
          <span class="linea"><span class="id">#${esc(r.id)}${ST.idsSla.has(r.id) ? ' <span class="marca-sla">⏰ SLA</span>' : ""}</span>${etiquetaResultado(r)}</span>
          <span class="desc">${esc(Motor.truncar(r.desc, 160) || "—")}</span>
          <span class="meta">${esc([r.valida && `${EMOJI_REP[estadoDe(r)]} ${estadoDe(r)}`, r.cat, r.marca && Motor.truncar(r.marca, 22), r.equipo && Motor.truncar(r.equipo, 22), dmy(r.fecha)].filter(Boolean).join(" · "))}</span>
        </button>`).join("") + `</div>`;
    }
    $("#paginacion").innerHTML = paginas <= 1 ? "" : `
      <button class="boton" data-ir="${ST.pagina - 1}" ${ST.pagina <= 1 ? "disabled" : ""}>‹ Anterior</button>
      <span class="estado">Página ${ST.pagina} de ${paginas}</span>
      <button class="boton" data-ir="${ST.pagina + 1}" ${ST.pagina >= paginas ? "disabled" : ""}>Siguiente ›</button>
      <form id="ir-a"><input type="number" min="1" max="${paginas}" inputmode="numeric" placeholder="Nº" aria-label="Ir a la página">
      <button class="boton" type="submit">Ir</button></form>`;
  }

  $("#lista").addEventListener("click", (e) => {
    const el = e.target.closest("[data-i]");
    if (el) abrir(ST.todos[+el.dataset.i]);
  });
  $("#lista").addEventListener("keydown", (e) => {
    const el = e.target.closest("tr[data-i]");
    if (el && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); abrir(ST.todos[+el.dataset.i]); }
  });
  $("#paginacion").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-ir]");
    if (b && !b.disabled) { ST.pagina = +b.dataset.ir; lista(); $("#vista-registros").scrollIntoView({ block: "start" }); }
  });
  $("#paginacion").addEventListener("submit", (e) => {
    e.preventDefault();
    const n = parseInt(e.target.querySelector("input").value, 10);
    if (Number.isFinite(n)) { ST.pagina = n; lista(); }
  });

  // ── Modal: ¿por qué se clasificó así? ──────────────────────────────────
  const modal = $("#modal");
  $("#modal-cerrar").addEventListener("click", () => modal.close());
  modal.addEventListener("click", (e) => { if (e.target === modal) modal.close(); });

  function abrir(r) {
    const afectados = new Set(r.anom.map((a) => a.campo));
    const reparados = new Set(r.rep.map((x) => x.campo));
    let resumen;
    if (r.valida) {
      resumen = `<strong>✔ VÁLIDA</strong> · severidad <strong>${esc(r.sev)}</strong> porque se aplicó
        <strong>${esc(r.criterio)}</strong> → ${esc(r.regla)}.<br>
        Categoría <strong>${esc(r.cat)}</strong> (${esc(r.oTipo)}) · Marca <strong>${esc(r.marca || "Sin marca")}</strong> (${esc(r.oMarca)}).`;
      if (r.notaInfra) resumen += `<br>⚠️ ${esc(r.notaInfra)}`;
    } else {
      const a = r.anom[0], donde = a.campo && a.campo !== "—" ? ` en «${esc(a.campo)}»` : "";
      resumen = `<strong>⛔ BLOQUEADA</strong> por <strong>${esc(a.tipo)}</strong>${donde}: ${esc(a.motivo)}` +
        (r.anom.length > 1 ? `<br>…y ${r.anom.length - 1} regla(s) más (detalle abajo).` : "") +
        `<br><span class="nota">Clasificación orientativa (no cuenta en las métricas): ${esc(r.sev)} · ${esc(r.cat)}.</span>`;
    }
    const pasos = [
      ["Validación", r.valida ? "Supera todas las reglas de calidad: campos obligatorios, fecha real, descripción con intención técnica y sin spam." : `Incumple ${r.anom.length} regla(s).`],
      ["Equipo", r.equipo || "Ningún campo de equipo tiene valor."],
      ["Categoría", `${r.cat} ← ${r.oTipo}`],
      ["Marca", `${r.marca || "Sin marca"} ← ${r.oMarca}`],
      ["Severidad", `${r.sev} ← ${r.criterio}: ${r.regla}`],
    ];
    $("#modal-titulo").textContent = `Incidencia #${r.id}`;
    $("#modal-cuerpo").innerHTML = `
      <div class="resumen" style="--color:${colorDe(r)}">${resumen}</div>
      ${r.anom.length ? `<div class="bloque"><h3>Reglas incumplidas</h3>${r.anom.map((a, i) => `
        <div class="motivo"><strong>${i + 1}. ${esc(a.tipo)}</strong> · campo «${esc(a.campo)}»<br>${esc(a.motivo)}
        ${a.valor ? `<br>Valor: <code>${esc(Motor.truncar(a.valor, 200))}</code>` : ""}
        ${a.extra ? `<br><em>${esc(a.extra)}</em>` : ""}</div>`).join("")}</div>` : ""}
      ${r.valida ? bloqueSeguimiento(r) : ""}
      <div class="bloque"><h3>Cómo decidió el motor</h3>${pasos.map(([e, t]) => `<div class="paso-linea"><span class="etapa">${e}</span><span>${esc(t)}</span></div>`).join("")}</div>
      ${r.rep.length ? `<div class="bloque"><h3>🔧 Auto-reparaciones aplicadas antes de validar</h3>${r.rep.map((x) => `
        <div class="paso-linea"><span class="etapa">${esc(Motor.truncar(x.campo, 24))}</span><span>«${esc(Motor.truncar(x.antes, 60))}» → «${esc(Motor.truncar(x.despues, 60))}» (${esc(x.motivo)})</span></div>`).join("")}</div>` : ""}
      <div class="bloque"><h3>Campos originales del XML</h3><table class="campos"><tbody>${r.campos.map(([n, v]) => `
        <tr class="${afectados.has(n) ? "afectado" : reparados.has(n) ? "reparado" : ""}"><td>${esc(n)}</td>
        <td>${v === null ? '<span class="vacio-campo">∅ vacío</span>' : esc(v)}</td></tr>`).join("")}</tbody></table>
        ${afectados.size ? '<p class="nota">En rojo: campos que han provocado el bloqueo. En azul: campos auto-reparados.</p>' : ""}</div>`;
    modal.showModal();
    $("#modal-cuerpo").scrollTop = 0;
  }

  // ── Seguimiento de la reparación (ficha) ───────────────────────────────
  function bloqueSeguimiento(r) {
    const g = ST.seg[r.id], estado = estadoDe(r);
    const fmt = (iso) => (iso ? iso.replace("T", " ") : "—");
    const tiempos = g ? `<p class="nota">Actualizado: ${fmt(g.actualizado)} · ▶️ Inicio: ${fmt(g.fecha_inicio)}${g.fecha_resolucion
      ? ` · ✅ Resuelta: ${fmt(g.fecha_resolucion)} · ⏱️ ${typeof g.duracion_minutos === "number" ? Operaciones.duracion(g.duracion_minutos) : "sin duración (no pasó por «En curso»)"}` : ""}</p>` : "";
    const sla = ST.idsSla.has(r.id) ? `<p class="marca-sla">⏰ Fuera de SLA</p>` : "";
    if (!esTecnico()) return `<div class="bloque"><h3>🛠️ Reparación</h3><p><strong>${EMOJI_REP[estado]} ${esc(estado)}</strong>${g && g.nota ? ` · Nota: ${esc(g.nota)}` : ""}</p>${sla}${tiempos}
      <p class="nota">🔒 Solo el modo Técnico puede cambiar el estado o la nota.</p></div>`;
    return `<div class="bloque"><h3>🛠️ Reparación</h3>${sla}
      <form class="form-reparacion" data-id="${esc(r.id)}">
        <div class="segmentado" role="radiogroup" aria-label="Estado">${ESTADOS.map((e) => `
          <label class="opcion-estado"><input type="radio" name="estado" value="${esc(e)}" ${e === estado ? "checked" : ""}> ${EMOJI_REP[e]} ${esc(e)}</label>`).join("")}</div>
        <input type="text" name="nota" maxlength="500" placeholder="Nota rápida de reparación (ej.: cambiado el cable HDMI)" value="${esc(g ? g.nota : "")}">
        <button class="boton boton-primario" type="submit">💾 Guardar</button>
      </form>${tiempos}
      <p class="nota">Se guarda en este navegador. Para compartirlo, descarga <code>gestion.json</code> en la pestaña 📜 Auditoría.</p></div>`;
  }
  $("#modal-cuerpo").addEventListener("submit", (e) => {
    const form = e.target.closest(".form-reparacion");
    if (!form) return;
    e.preventDefault();
    const id = form.dataset.id, estado = form.estado.value, nota = form.nota.value;
    try {
      const { anterior, nota_anterior: notaAnterior, registro } = Tecnico.actualizarSeguimiento(id, estado, nota, ESTADOS);
      let detalle = `ID ${id}: estado ${anterior} → ${registro.estado}`;
      if (registro.nota !== notaAnterior) detalle += `; nota «${notaAnterior}» → «${registro.nota}»`;
      else if (registro.nota) detalle += `; nota «${registro.nota}»`;
      auditar("REPARACION", detalle);
    } catch (err) { alert(err.message); return; }
    ST.seg = Tecnico.seguimiento();
    const r = ST.todos.find((x) => x.id === id);
    const pagina = ST.pagina;
    opciones(); filtrar(); ST.pagina = pagina; lista();
    if (r) abrir(r);
  });

  // ── Reglas activas ─────────────────────────────────────────────────────
  function reglas() {
    const RG = ST.reglas.datos, E = D.config.etiquetasListas, L = D.config.limites;
    const listas = { ...RG.severidad, ...RG.lexico_tecnico };
    const chips = (lista, max = 60) => lista.slice(0, max).map((p) => `<span class="chip">${esc(p)}</span>`).join("") + (lista.length > max ? " …" : "");
    const legible = (src) => src.split("|").map((p) => p.replace(/\\b|\^|\$|\(\?:|[()?]/g, "").replace(/\\s\+|\\s/g, " ").replace(/\\/g, "")).filter(Boolean);
    const anyoMax = RG.anyos.maximo || `${new Date().getFullYear()} (año actual)`;
    const valOrig = ST.todos.filter((r) => r.valida);
    const cuantas = (paso) => valOrig.filter((r) => (r.criterio || "").startsWith(`Paso ${paso} `)).length;
    const pasos = D.config.pasos.map((p) => `
      <article class="regla" style="--color:var(${COLOR_NIVEL[p.nivel]})">
        <div class="paso">Paso ${p.paso} · ${esc(p.nivel)}</div><strong>${esc(p.titulo)}</strong>
        <p>${esc(p.descripcion)}</p>
        ${p.listas.map((k) => `<div class="lista-titulo">${esc(E[k].split(" · ").pop())}</div>${chips(listas[k])}`).join("")}
        <p class="nota">📌 ${num(cuantas(p.paso))} incidencias válidas resueltas así</p>
      </article>`).join("");
    const ultimo = D.config.pasos.length + 1;
    const bloqueos = [
      [CAT.fecha, `Año anterior a ${RG.anyos.minimo} o posterior a ${anyoMax}, fecha futura, día/mes inexistente (31/02) o sin formato reconocible.`],
      [CAT.vacio, "Etiqueta vacía o de autocierre (<camp nom=\"X\"/>) en un campo obligatorio. Marca y modelo son opcionales."],
      [CAT.basura, `Binario (≥ 3 bytes), escritura amárica o expresiones prohibidas: ${Object.keys(D.config.palabrasBasura).join(", ")}.`],
      [CAT.sinSentido, `Fuerza técnica = 2 × síntomas + dispositivos. Con fuerza ≥ 2 se acepta («No funciona», «Teclat trencat»). Micro-frases planas tipo Faker con menos fuerza, párrafos ≥ ${L.minPalabrasParrafo} palabras con fuerza < 3, ≥ ${L.minPalabrasProsa} palabras sin ningún término técnico o sin ninguna palabra («69») se bloquean.`],
      [CAT.desborde, `Más de ${L.maxLongitudCorto} caracteres en un campo breve (código, equipo, marca, modelo, IP…).`],
    ];
    const porTipo = new Map(contar(ST.todos.flatMap((r) => r.anom), (a) => a.tipo));
    editorReglas();
    $("#mapa-reglas").innerHTML = `
      <h2 class="seccion-titulo">Cómo se decide la severidad</h2>
      <p class="nota">Se evalúa en orden y gana la primera regla que encaja. Palabras clave de <code>rules.json</code>, buscadas en la descripción, el equipo y su categoría, sin tildes ni mayúsculas.</p>
      <div class="reglas-rejilla">
        <article class="regla"><div class="paso">Paso 0</div><strong>Prioridad explícita del XML</strong><p>Si el XML trae un campo Prioritat / Severitat / Urgència, manda su valor.</p></article>
        ${pasos}
        <article class="regla" style="--color:var(--media)"><div class="paso">Paso ${ultimo} · Media</div><strong>Sin pistas</strong><p>Ninguna palabra clave encaja: se asume fallo genérico.</p><p class="nota">📌 ${num(cuantas(ultimo))} incidencias válidas resueltas así</p></article>
      </div>
      <h2 class="seccion-titulo">Qué bloquea una incidencia</h2>
      <p class="nota">Una sola regla incumplida basta. Antes de validar se auto-reparan fechas (→ DD/MM/AAAA), espacios y mayúsculas de marca.</p>
      <div class="reglas-rejilla">${bloqueos.map(([c, t]) => `
        <article class="regla" style="--color:var(${COLOR_ANOM[TA[c]]})"><strong>${esc(TA[c])}</strong><p>${esc(t)}</p>
        <p class="nota">📌 Detectado ${num(porTipo.get(TA[c]) || 0)} veces</p></article>`).join("")}</div>
      <h2 class="seccion-titulo">Léxico técnico, marcas y categorías</h2>
      <div class="reglas-rejilla">
        ${["sintomas", "dispositivos"].map((k) => `<details class="regla"><summary>${esc(E[k])} (${listas[k].length})</summary>${chips(listas[k], 400)}</details>`).join("")}
        <details class="regla"><summary>Marcas reconocidas (${Object.keys(RG.marcas).length})</summary>
          ${Object.entries(RG.marcas).map(([n, a]) => `<div class="lista-titulo">${esc(n)}</div>${chips(a)}`).join("")}</details>
        <details class="regla"><summary>Categorías de equipo (${D.config.tipos.length})</summary>
          ${D.config.tipos.map(([n, src]) => `<div class="lista-titulo">${esc(n)}</div>${chips(legible(src))}`).join("")}</details>
      </div>`;
  }

  // ── Pestañas ───────────────────────────────────────────────────────────
  const pestanas = document.querySelectorAll(".pestanas button");
  for (const b of pestanas) b.addEventListener("click", () => {
    for (const x of pestanas) x.setAttribute("aria-selected", String(x === b));
    const p = b.dataset.pestana;
    $("#vista-panel").hidden = p !== "panel";
    $("#vista-registros").hidden = p !== "registros";
    $("#vista-reglas").hidden = p !== "reglas";
    $("#vista-masivas").hidden = p !== "masivas";
    $("#vista-auditoria").hidden = p !== "auditoria";
    $("#filtros").hidden = $("#kpis").hidden = p === "reglas" || p === "auditoria";
    if (p === "auditoria") auditoria();
    if (p === "panel") graficos();             // Chart.js necesita el lienzo visible para medir
    if (p === "masivas") masivas();
  });

  // ── Cargar otro XML local (no se sube a ningún sitio) ──────────────────
  const aviso = $("#aviso-origen");
  function mostrarAviso(html, error = false) {
    aviso.innerHTML = html;
    aviso.classList.toggle("error", error);
    aviso.hidden = false;
  }
  $("#xml-local").addEventListener("change", async (e) => {
    const archivo = e.target.files[0];
    e.target.value = "";
    if (!archivo) return;
    try {
      const texto = await archivo.text();
      const registros = Motor.analizarXML(texto);
      ST.todos = preparar(registros);
      ST.origen = archivo.name;
      ST.xmlLocal = texto;
      mostrarAviso(`<span>Mostrando <strong>${esc(archivo.name)}</strong> (${num(registros.length)} incidencias), analizado en este navegador: no se ha subido a ningún sitio.</span>
        <button class="boton" id="volver" type="button">Volver a los datos publicados</button>`);
      reiniciar();
    } catch (err) {
      const titulo = err instanceof Motor.ErrorCarga ? err.titulo : "No se ha podido leer el archivo";
      mostrarAviso(`<span><strong>${esc(titulo)}</strong>: ${esc(err.message).replace(/\n/g, "<br>")}</span>
        <button class="boton" id="cerrar-aviso" type="button">Cerrar</button>`, true);
    }
  });
  aviso.addEventListener("click", (e) => {
    if (e.target.id === "volver") { ST.todos = ST.publicados; ST.origen = null; ST.xmlLocal = null; aviso.hidden = true; avisoReglas(); reiniciar(); }
    if (e.target.id === "reglas-publicadas") volverAReglasPublicadas();
    if (e.target.id === "cerrar-aviso") aviso.hidden = true;
  });

  // ── Arranque ───────────────────────────────────────────────────────────
  function pintar() {
    kpis(); alertaSla();
    if (!$("#vista-panel").hidden) graficos();
    if (!$("#vista-masivas").hidden) masivas();
    lista();
    if (!$("#vista-auditoria").hidden) auditoria();
  }

  // ── Tema Claro / Oscuro (Claro por defecto; se recuerda en este navegador) ──
  function ponerTema(tema) {
    if (tema === "oscuro") document.documentElement.dataset.tema = "oscuro";
    else delete document.documentElement.dataset.tema;
    for (const b of document.querySelectorAll("#selector-tema button")) b.setAttribute("aria-pressed", String(b.dataset.tema === tema));
    try { localStorage.setItem("monitor-tema", tema); } catch (_) { /* sin almacenamiento */ }
  }
  ponerTema(document.documentElement.dataset.tema === "oscuro" ? "oscuro" : "claro");
  $("#selector-tema").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-tema]");
    if (!b) return;
    ponerTema(b.dataset.tema);
    pintar();                                     // Los gráficos leen los colores del tema
  });

  // ── Informe ejecutivo (misma estructura que app/exporter.informe_estado) ──
  function informeHtml(ahora = new Date()) {
    const todos = ST.todos, val = todos.filter((r) => r.valida), total = todos.length, anom = total - val.length;
    const p = (a, b) => (b ? `${((a / b) * 100).toFixed(1).replace(".", ",")} %` : "—");
    const torm = Operaciones.tormentas(val, MAS.minTormenta, MAS.ventana, NIVELES);
    const dups = Operaciones.duplicados(val, MAS.umbral, MAS.margen);
    const mt = Tecnico.mttr(val, ST.seg, NIVELES);
    const alertas = Operaciones.fueraDeSla(val, SLA, NIVELES, ahora, ST.seg);
    const resueltas = val.filter((r) => estadoDe(r) === "Resuelta").length;
    const activas = torm.filter((t) => t.ids.some((i) => (ST.seg[i] || {}).estado !== "Resuelta"));
    const unicas = Operaciones.unicasEstimadas(val.length, torm, dups);
    const zonas = contar(val, (r) => r.zona || "Sin zona");
    const graves = new Map(contar(val.filter((r) => r.sev === "Crítica" || r.sev === "Alta"), (r) => r.zona || "Sin zona"));
    const ranking = zonas.slice(0, 8), maximo = ranking.length ? ranking[0][1] : 1;
    const porSev = new Map(contar(val, (r) => r.sev));
    const mtSev = new Map(mt.porSeveridad.map(([n, m, c]) => [n, [m, c]]));
    const COL = { "Crítica": "#d13438", "Alta": "#e8590c", "Media": "#d4a106", "Leve": "#2f74d0" };
    const fuente = ST.origen || D.meta.fuente, dur = Operaciones.duracion;
    const fh = `${pad2(ahora.getDate())}/${pad2(ahora.getMonth() + 1)}/${ahora.getFullYear()}`, hm = `${pad2(ahora.getHours())}:${pad2(ahora.getMinutes())}`;
    const frases = [`Se han procesado <b>${num(total)}</b> registros del archivo <b>${esc(fuente)}</b>: <b>${num(val.length)}</b> son incidencias válidas (${p(val.length, total)}) y <b>${num(anom)}</b> se han bloqueado como basura o datos imposibles (${p(anom, total)}).`];
    if (ranking.length) frases.push(`La ubicación más afectada es <b>${esc(ranking[0][0])}</b>, con ${num(ranking[0][1])} incidencias (${p(ranking[0][1], val.length)} de las válidas).`);
    frases.push(`Hay <b>${num(porSev.get("Crítica") || 0)}</b> incidencias críticas y <b>${num(porSev.get("Alta") || 0)}</b> altas; ` +
      (alertas.length ? `<span class='alerta'>${num(alertas.length)} superan su SLA sin resolverse</span>.` : "ninguna supera su SLA."));
    if (torm.length || dups.length) frases.push(`Se detectan <b>${num(torm.length)}</b> tormentas de incidencias (${num(activas.length)} sin resolver del todo) y <b>${num(dups.length)}</b> grupos de tickets duplicados: descontándolos, las válidas equivalen a unos <b>${num(unicas)}</b> fallos distintos.`);
    frases.push(`Reparaciones: ${num(resueltas)} resueltas de ${num(val.length)} (${p(resueltas, val.length)}); tiempo medio de resolución (MTTR): <b>${dur(mt.minutos)}</b>` +
      (mt.resueltas ? ` sobre ${num(mt.resueltas)} resueltas con tiempo medido.` : " (aún no hay reparaciones con tiempo medido)."));
    if (ST.reglasLocales) frases.push("<i>Calculado con reglas modificadas en el navegador (aún no publicadas en rules.json).</i>");
    const kpi = (e, v, sub, c) => `<div class="kpi" style="--c:${c}"><div class="e">${e}</div><div class="v">${v}</div><div class="s">${sub}</div></div>`;
    const mas = (l) => (l.length > 10 ? `<p class='nota'>… y ${num(l.length - 10)} más (ver la web).</p>` : "");
    const fechas = (g) => (g.desde === g.hasta ? dmy(g.desde) : `${dmy(g.desde)} – ${dmy(g.hasta)}`);
    return `<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Informe de estado · ${fh}<\/title>
<style>${D.informeCss}<\/style>
<\/head>
<body>
<main class="hoja">
<header>
  <div><h1>Informe ejecutivo de incidencias</h1>
  <div class="nota">Monitor XML de incidencias · fuente: ${esc(fuente)}</div></div>
  <div class="emision">Emitido el<br><b>${fh}</b> a las <b>${hm}</b></div>
</header>
<h2>Resumen ejecutivo</h2>
<div class="resumen">${frases.map((f) => `<p>${f}</p>`).join("")}</div>
<h2>Indicadores clave</h2>
<div class="kpis">${kpi("Total procesadas", num(total), esc(fuente), "#3e63dd")}${kpi("% Válidas", p(val.length, total), `${num(val.length)} incidencias`, "#30a46c")}${kpi("% Basura bloqueada", p(anom, total), `${num(anom)} registros`, "#e5484d")}${kpi("MTTR", dur(mt.minutos), `${num(mt.resueltas)} resueltas medidas`, "#8e4ec6")}</div>
<h2>Plantas y oficinas más afectadas</h2>
<table><thead><tr><th>Planta / oficina</th><th>Incid.</th><th>% válidas</th><th>Críticas + altas</th><th></th></tr></thead><tbody>${ranking.map(([z, n]) => `<tr><td>${esc(z)}</td><td class='n'>${num(n)}</td><td class='n'>${p(n, val.length)}</td><td class='n'>${num(graves.get(z) || 0)}</td><td style='width:38%'><div class='pista'><div class='barra' style='--c:#3e63dd;width:${(n / maximo * 100).toFixed(1)}%'></div></div></td></tr>`).join("")}</tbody></table>
<h2>Desglose por severidad</h2>
<table><thead><tr><th>Severidad</th><th>Incid.</th><th>%</th><th>MTTR</th><th>SLA</th><th>Fuera de SLA</th></tr></thead><tbody>${NIVELES.map((n) => `<tr><td><span class='etiqueta' style='--c:${COL[n]}'>${n}</span></td><td class='n'>${num(porSev.get(n) || 0)}</td><td class='n'>${p(porSev.get(n) || 0, val.length)}</td><td class='n'>${mtSev.has(n) ? dur(mtSev.get(n)[0]) : "—"}</td><td class='n'>${n in SLA ? `${SLA[n]} h` : "—"}</td><td class='n'>${n in SLA ? num(alertas.filter((a) => a.r.sev === n).length) : "—"}</td></tr>`).join("")}</tbody></table>
<h2>Tormentas de incidencias (incidencias masivas)</h2>
<p class="nota">≥ ${MAS.minTormenta} incidencias de la misma categoría en la misma planta u oficina el mismo día.</p>
${torm.length ? `<table><thead><tr><th>Planta / oficina</th><th>Fecha</th><th>Categoría</th><th>Síntoma principal</th><th>Incid.</th></tr></thead><tbody>${torm.slice(0, 10).map((t) => `<tr><td>${esc(t.zona)}</td><td>${fechas(t)}</td><td>${esc(t.categoria)}</td><td>${esc(t.sintoma)}</td><td class='n'>${t.ids.length}</td></tr>`).join("")}</tbody></table>${mas(torm)}` : "<p>No se detectan tormentas de incidencias.</p>"}
<h2>Tickets duplicados</h2>
<p class="nota">Mismo equipo, fechas cercanas y descripción con similitud ≥ ${Math.round(MAS.umbral * 100)} %.</p>
${dups.length ? `<table><thead><tr><th>Equipo</th><th>Planta / oficina</th><th>Original</th><th>Duplicados</th><th>Similitud</th></tr></thead><tbody>${dups.slice(0, 10).map((g) => `<tr><td>${esc(g.equipo)}</td><td>${esc(g.zona || "—")}</td><td>#${esc(g.ids[0])}</td><td>${g.ids.slice(1).map((i) => "#" + esc(i)).join(", ")}</td><td class='n'>${Math.round(g.similitud * 100)} %</td></tr>`).join("")}</tbody></table>${mas(dups)}` : "<p>No se detectan tickets duplicados.</p>"}
<h2>Tickets críticos y altos fuera de SLA</h2>
${alertas.length ? `<table><thead><tr><th>ID</th><th>Severidad</th><th>Estado</th><th>Planta / oficina</th><th>Descripción</th><th>Abierta</th></tr></thead><tbody>${alertas.slice(0, 10).map((a) => `<tr><td>#${esc(a.r.id)}</td><td><span class='etiqueta' style='--c:${COL[a.r.sev]}'>${a.r.sev}</span></td><td>${esc(a.estado)}</td><td>${esc(a.r.zona || "—")}</td><td>${esc(a.r.desc.slice(0, 90))}</td><td class='n alerta'>${dur(a.horas * 60)}</td></tr>`).join("")}</tbody></table>${mas(alertas)}` : "<p>Ningún ticket crítico o alto supera su SLA.</p>"}
<footer>Informe generado en el navegador a partir del XML, las reglas y el seguimiento de reparaciones vigentes. Para guardarlo como PDF: Imprimir → «Guardar como PDF».</footer>
</main>
<\/body>
<\/html>
`;
  }
  const pad2 = (n) => String(n).padStart(2, "0");
  $("#descargar-informe").addEventListener("click", () => {
    Tecnico.descargar("informe_estado.html", informeHtml(), "text/html");
    auditar("EXPORTACION", `Descarga de informe_estado.html (${ST.todos.length} registros)`);
  });

  // ── Editor de reglas (modo Técnico) ────────────────────────────────────
  const GRUPOS_EDITOR = [
    ["🔴 Crítica", ["critica_caida_general", "critica_caida", "critica_infraestructura", "critica_multiusuario", "afectados_multiples"]],
    ["🟠 Alta", ["alta_hardware", "alta_arranque"]],
    ["🔵 Leve", ["leve_perifericos"]],
    ["🟡 Media", ["media_generico"]],
    ["🧠 Léxico técnico (filtro anti-texto aleatorio)", ["sintomas", "dispositivos"]],
  ];
  const grupoDe = (k, d) => (k in d.severidad ? "severidad" : "lexico_tecnico");
  const CLAVE_REGLAS = "monitor-reglas";
  const mismasReglas = (a, b) => Tecnico.jsonOrdenado(a) === Tecnico.jsonOrdenado(b);

  function avisoReglas() {
    if (ST.origen) return;
    if (ST.reglasLocales) mostrarAviso(`<span>🧮 Mostrando el análisis con <strong>reglas modificadas en este navegador</strong> (aún no están en <code>rules.json</code> del repositorio).</span>
      <button class="boton" id="reglas-publicadas" type="button">Volver a las reglas publicadas</button>`);
    else aviso.hidden = true;
  }

  async function textoXml() {
    if (ST.xmlLocal) return { texto: ST.xmlLocal, exacto: true };
    try {
      const resp = await fetch(D.meta.xml, { cache: "no-store" });
      if (resp.ok) return { texto: await resp.text(), exacto: true };
    } catch (_) { /* file:// o sin conexión: se reconstruye */ }
    return { texto: Tecnico.xmlDesdeRegistros(ST.original, D.config.etiquetas), exacto: false };
  }

  /** Valida y compila `datos`, vuelve a analizar el XML en el navegador y lo pinta todo. */
  async function aplicarReglas(datos, { auditarCambio = true, motivo = "Editor de reglas" } = {}) {
    const compiladas = Tecnico.compilarReglas(datos, D.config.reglasFabrica);   // Lanza ErrorReglas
    const antes = ST.reglas.datos;
    const publicadas = mismasReglas(compiladas.datos, D.config.reglas.datos);
    Motor.configurar({ ...D.config, reglas: compiladas });
    ST.reglas = compiladas;
    const { texto, exacto } = await textoXml();
    const registros = preparar(Motor.analizarXML(texto, D.meta.hoy));
    if (ST.xmlLocal) ST.todos = registros;
    else {
      ST.publicados = publicadas && exacto ? ST.original : registros;
      ST.todos = ST.publicados;
    }
    ST.reglasLocales = !publicadas;
    Tecnico.guardarLS(CLAVE_REGLAS, publicadas ? null : compiladas.datos);
    if (auditarCambio) {
      const cambios = Tecnico.cambiosReglas(antes, compiladas.datos);
      auditar("REGLAS", `${motivo}: ${cambios.length ? cambios.join("; ") : "guardado sin cambios"}`);
    }
    avisoReglas();
    reiniciar();
    return { exacto };
  }

  function volverAReglasPublicadas() {
    Motor.configurar(D.config);
    ST.reglas = D.config.reglas;
    ST.reglasLocales = false;
    Tecnico.guardarLS(CLAVE_REGLAS, null);
    ST.publicados = ST.original;
    if (!ST.origen) ST.todos = ST.publicados;
    auditar("REGLAS", "Descartadas las reglas del navegador: se vuelve a rules.json publicado");
    avisoReglas();
    reiniciar();
  }

  function leerEditor() {
    const d = JSON.parse(JSON.stringify(ST.reglas.datos));
    const ed = $("#editor-reglas");
    const min = parseInt(ed.querySelector("#r-min").value, 10), max = parseInt(ed.querySelector("#r-max").value || "0", 10);
    d.anyos = { minimo: Number.isFinite(min) ? min : NaN, maximo: Number.isFinite(max) && max ? max : null };
    for (const ta of ed.querySelectorAll("textarea[data-lista]")) {
      const k = ta.dataset.lista;
      d[grupoDe(k, d)][k] = ta.value.split("\n").map((l) => l.trim()).filter(Boolean);
    }
    const marcas = {};
    for (const linea of ed.querySelector("#r-marcas").value.split("\n")) {
      const i = linea.indexOf(":"), nombre = (i < 0 ? linea : linea.slice(0, i)).trim();
      if (nombre) marcas[nombre] = (i < 0 ? "" : linea.slice(i + 1)).split(",").map((a) => a.trim()).filter(Boolean);
    }
    d.marcas = marcas;
    return d;
  }

  function editorReglas() {
    const ed = $("#editor-reglas");
    if (!esTecnico()) {
      ed.innerHTML = `<p class="nota">🔒 Modo Consultor: puedes consultar las reglas, pero solo el modo Técnico puede editarlas.</p>`;
      return;
    }
    const d = ST.reglas.datos, E = D.config.etiquetasListas;
    const patrones = Object.keys(d.severidad).map((k) => new RegExp(ST.reglas.patrones[k]));
    const emergentes = (D.emergentes || []).filter(([t]) => !patrones.some((re) => re.test(t)));
    const opcionesLista = Object.keys(E).map((k) => `<option value="${k}" ${k === "media_generico" ? "selected" : ""}>${esc(E[k])}</option>`).join("");
    ed.innerHTML = `
      <h2 class="seccion-titulo">✏️ Editor de reglas (rules.json)</h2>
      <p class="nota">Una palabra o expresión por línea; tildes y mayúsculas se normalizan solas. Se buscan al <b>inicio de palabra</b> («impressor» encaja con impressora e impressores); las marcas, como palabra completa. Al aplicar se vuelve a analizar todo el XML en este navegador.</p>
      <form id="form-reglas" class="editor">
        <div class="fila-anyos">
          <label>Año mínimo válido <input id="r-min" type="number" min="1" max="9999" value="${d.anyos.minimo}"></label>
          <label>Año máximo (0 = año actual) <input id="r-max" type="number" min="0" max="9999" value="${d.anyos.maximo || 0}"></label>
        </div>
        ${GRUPOS_EDITOR.map(([titulo, claves]) => `<details class="regla"><summary>${titulo}</summary>${claves.map((k) => `
          <label class="lista-titulo">${esc(E[k])} (${d[grupoDe(k, d)][k].length})
            <textarea data-lista="${k}" rows="6" spellcheck="false">${esc(d[grupoDe(k, d)][k].join("\n"))}</textarea></label>`).join("")}</details>`).join("")}
        <details class="regla"><summary>🏷️ Marcas reconocidas (${Object.keys(d.marcas).length})</summary>
          <label class="lista-titulo">Una marca por línea: «Marca: alias, alias…»
            <textarea id="r-marcas" rows="10" spellcheck="false">${esc(Object.entries(d.marcas).map(([n, a]) => `${n}: ${a.join(", ")}`).join("\n"))}</textarea></label></details>
        <div class="acciones-editor">
          <button class="boton boton-primario" type="submit">✅ Aplicar y recalcular</button>
          <button class="boton" type="button" id="r-descargar">⬇️ Descargar rules.json</button>
          <button class="boton" type="button" id="r-fabrica">↩️ Restaurar valores de fábrica</button>
          ${ST.reglasLocales ? `<button class="boton" type="button" id="r-publicadas">Volver a las publicadas</button>` : ""}
        </div>
        <p class="estado-editor" id="r-estado" role="status"></p>
      </form>
      <p class="nota">Los cambios se guardan en este navegador. Para que los vea todo el mundo, descarga <code>rules.json</code>, súbelo al repositorio y GitHub Pages se republica solo.</p>
      <h2 class="seccion-titulo">🧪 Problemas emergentes</h2>
      <p class="nota">Palabras y parejas de palabras frecuentes en las incidencias sin clasificar bien que aún no son palabra clave. Añádelas con ➕ a la lista que elijas.</p>
      ${emergentes.length ? `<label class="lista-titulo">Añadir a la lista <select id="em-destino">${opcionesLista}</select></label>
      <div class="emergentes">${emergentes.map(([t, tipo, n, ej]) => `<div class="emergente" title="${esc(ej)}"><code>${esc(t)}</code><span class="nota">${tipo === "Bigrama" ? "pareja" : "palabra"} · ${num(n)} incid.</span><button class="boton" type="button" data-emergente="${esc(t)}" aria-label="Añadir ${esc(t)}">➕</button></div>`).join("")}</div>`
      : `<p class="vacio">No hay términos nuevos frecuentes.</p>`}`;
  }

  async function conEstado(promesa, ok) {
    const estado = $("#r-estado");
    if (estado) { estado.textContent = "⏳ Recalculando…"; estado.className = "estado-editor"; }
    try {
      const { exacto } = await promesa();
      const e2 = $("#r-estado");
      if (e2) {
        e2.textContent = ok + (exacto ? "" : " (XML reconstruido desde la página: los valores de más de 600 caracteres van recortados)");
        e2.className = "estado-editor ok";
      }
    } catch (err) {
      const e2 = $("#r-estado") || estado;
      if (e2) { e2.textContent = `❌ No se ha aplicado: ${err.message}`; e2.className = "estado-editor error"; }
    }
  }

  $("#editor-reglas").addEventListener("submit", (e) => {
    if (e.target.id !== "form-reglas") return;
    e.preventDefault();
    const datos = leerEditor();
    conEstado(() => aplicarReglas(datos), "✅ Reglas aplicadas y datos recalculados.");
  });
  $("#editor-reglas").addEventListener("click", (e) => {
    const t = e.target;
    if (t.id === "r-descargar") {
      try {
        const limpio = Tecnico.validarReglas(leerEditor(), D.config.reglasFabrica);
        Tecnico.descargar("rules.json", JSON.stringify(limpio, null, 2) + "\n", "application/json");
        auditar("EXPORTACION", "Descarga de rules.json");
      } catch (err) { $("#r-estado").textContent = `❌ ${err.message}`; $("#r-estado").className = "estado-editor error"; }
    } else if (t.id === "r-fabrica") {
      if (confirm("¿Sustituir las reglas por las originales del programa?"))
        conEstado(() => aplicarReglas(D.config.reglasFabrica, { motivo: "Restaurados los valores de fábrica" }), "↩️ Reglas de fábrica aplicadas.");
    } else if (t.id === "r-publicadas") {
      volverAReglasPublicadas();
    } else if (t.dataset.emergente) {
      const destino = $("#em-destino").value, d = JSON.parse(JSON.stringify(ST.reglas.datos));
      d[grupoDe(destino, d)][destino].push(t.dataset.emergente);
      conEstado(() => aplicarReglas(d, { motivo: `Palabra emergente añadida a ${destino}` }),
        `➕ «${t.dataset.emergente}» añadida y datos recalculados.`);
    }
  });

  // ── Auditoría (modo Técnico) ───────────────────────────────────────────
  const FA = { accion: "", rol: "", texto: "" };
  function auditoria() {
    const v = $("#vista-auditoria");
    if (!esTecnico()) { v.innerHTML = ""; return; }
    const todos = Tecnico.eventos(), q = Motor.normalizar(FA.texto);
    const ev = todos.filter(([, rol, acc, det]) => (!FA.accion || acc === FA.accion) && (!FA.rol || rol === FA.rol)
      && (!q || Motor.normalizar(`${det} ${acc}`).includes(q)));
    const opc = (lista, actual, primero) => `<option value="">${primero}</option>` + lista.map((x) => `<option ${x === actual ? "selected" : ""}>${esc(x)}</option>`).join("");
    const enfoque = document.activeElement && document.activeElement.id === "a-texto";
    v.innerHTML = `
      <h2 class="seccion-titulo">📜 Auditoría de cambios</h2>
      <p class="nota">Accesos (y PINs fallidos), cambios de reparaciones y reglas y descargas hechos en <b>este navegador</b>, del más reciente al más antiguo, con el formato de <code>audit.log</code>. Para conservarlos, descarga los archivos y súbelos al repositorio.</p>
      <div class="acciones-editor">
        <button class="boton" type="button" id="d-audit">⬇️ audit.log</button>
        <button class="boton" type="button" id="d-gestion">⬇️ gestion.json (${num(Object.keys(ST.seg).length)} reparaciones)</button>
        <button class="boton" type="button" id="d-reglas">⬇️ rules.json</button>
      </div>
      <div class="filtros-auditoria">
        <select id="a-accion" aria-label="Acción">${opc(["ACCESO", "ACCESO_FALLIDO", "CIERRE_SESION", "REPARACION", "REGLAS", "EXPORTACION"], FA.accion, "Toda acción")}</select>
        <select id="a-rol" aria-label="Rol">${opc(["Técnico", "Consultor", "Anónimo"], FA.rol, "Todo rol")}</select>
        <input type="search" id="a-texto" placeholder="Buscar en el detalle…" value="${esc(FA.texto)}" aria-label="Buscar en el detalle">
      </div>
      <p class="nota">${num(ev.length)} eventos${ev.length > 1000 ? " · se muestran los 1.000 más recientes" : ""}</p>
      ${ev.length ? `<div class="tabla-envoltorio"><table class="registros"><thead><tr><th>Fecha</th><th>Rol</th><th>Acción</th><th>Detalle</th></tr></thead><tbody>${ev.slice(0, 1000).map(([f, r, a, d]) => `<tr><td>${esc(f)}</td><td>${esc(r)}</td><td>${esc(a)}</td><td class="desc">${esc(d)}</td></tr>`).join("")}</tbody></table></div>`
        : `<p class="vacio">Todavía no hay eventos con este filtro.</p>`}`;
    if (enfoque) { const i = $("#a-texto"); i.focus(); i.setSelectionRange(i.value.length, i.value.length); }
  }
  $("#vista-auditoria").addEventListener("change", (e) => {
    if (e.target.id === "a-accion") { FA.accion = e.target.value; auditoria(); }
    if (e.target.id === "a-rol") { FA.rol = e.target.value; auditoria(); }
  });
  $("#vista-auditoria").addEventListener("input", (e) => { if (e.target.id === "a-texto") { FA.texto = e.target.value; auditoria(); } });
  $("#vista-auditoria").addEventListener("click", (e) => {
    if (e.target.id === "d-audit") { auditar("EXPORTACION", "Descarga de audit.log"); Tecnico.descargar("audit.log", Tecnico.textoAuditLog()); auditoria(); }
    if (e.target.id === "d-gestion") { Tecnico.descargar("gestion.json", Tecnico.textoGestion(), "application/json"); auditar("EXPORTACION", `Descarga de gestion.json (${Object.keys(ST.seg).length} registros)`); auditoria(); }
    if (e.target.id === "d-reglas") { Tecnico.descargar("rules.json", JSON.stringify(ST.reglas.datos, null, 2) + "\n", "application/json"); auditar("EXPORTACION", "Descarga de rules.json"); auditoria(); }
  });

  // ── Rol activo (lo fija acceso.js al entrar y al cerrar sesión) ─────────
  function ponerRol(rol) {
    ST.rol = rol;
    $("#pestana-auditoria").hidden = !esTecnico();
    if (!esTecnico() && !$("#vista-auditoria").hidden) document.querySelector('[data-pestana="panel"]').click();
    editorReglas();
    if (!$("#vista-auditoria").hidden) auditoria();
    if (modal.open) modal.close();
  }
  function reiniciar() { opciones(); reglas(); filtrar(); }
  reiniciar();
  const guardadas = Tecnico.leerLS(CLAVE_REGLAS, null);
  if (guardadas) {
    let distintas = false;
    try { distintas = !mismasReglas(Tecnico.validarReglas(guardadas, D.config.reglasFabrica), D.config.reglas.datos); } catch (_) { /* dañadas */ }
    if (distintas) aplicarReglas(guardadas, { auditarCambio: false }).catch(() => Tecnico.guardarLS(CLAVE_REGLAS, null));
    else Tecnico.guardarLS(CLAVE_REGLAS, null);
  }
  window.Dashboard = { ST, abrir, filtrar, ponerRol, aplicarReglas, informeHtml };      // Para depurar desde la consola y para los tests
  document.documentElement.dataset.listo = "1";   // Señal para las pruebas automáticas
})();
