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
    topPor: "equipo", graficos: {}, origen: null,
  };
  ST.todos = ST.publicados;

  // ── Filtros ────────────────────────────────────────────────────────────
  const F = { texto: $("#f-texto"), estado: $("#f-estado"), sev: $("#f-sev"), cat: $("#f-cat"), marca: $("#f-marca"), anom: $("#f-anom") };

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
    rellenarSelect(F.anom, contar(ST.todos.flatMap((r) => [...new Set(r.anom.map((a) => a.tipo))].map((t) => ({ t }))), (x) => x.t), "Todo tipo de anomalía");
  }

  function filtrar() {
    const q = Motor.normalizar(F.texto.value);
    const { estado, sev, cat, marca, anom } = Object.fromEntries(Object.entries(F).map(([k, el]) => [k, el.value]));
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
      return true;
    });
    ST.pagina = 1;
    pintar();
  }

  let espera;
  F.texto.addEventListener("input", () => { clearTimeout(espera); espera = setTimeout(filtrar, 150); });
  for (const el of [F.estado, F.sev, F.cat, F.marca, F.anom]) el.addEventListener("change", filtrar);
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
      NIVELES.map((nv) => tarjeta(nv, num(val.filter((r) => r.sev === nv).length), "válidas", `var(${COLOR_NIVEL[nv]})`)).join("");
  }

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
        <th>ID</th><th>Resultado</th><th>Categoría</th><th>Marca</th><th>Equipo</th><th>Fecha</th><th>Descripción</th></tr></thead><tbody>` +
        trozo.map((r) => `<tr data-i="${ST.todos.indexOf(r)}" tabindex="0">
          <td><strong>${esc(r.id)}</strong></td><td>${etiquetaResultado(r)}</td><td>${esc(r.cat)}</td>
          <td>${esc(Motor.truncar(r.marca, 24) || "—")}</td><td>${esc(Motor.truncar(r.equipo, 24) || "—")}</td><td>${dmy(r.fecha)}</td>
          <td class="desc">${esc(Motor.truncar(r.desc, 110))}</td></tr>`).join("") + `</tbody></table></div>`;
    } else {
      cont.innerHTML = `<div class="tarjetas">` + trozo.map((r) => `
        <button class="registro" data-i="${ST.todos.indexOf(r)}" style="--color:${colorDe(r)}">
          <span class="linea"><span class="id">#${esc(r.id)}</span>${etiquetaResultado(r)}</span>
          <span class="desc">${esc(Motor.truncar(r.desc, 160) || "—")}</span>
          <span class="meta">${esc([r.cat, r.marca && Motor.truncar(r.marca, 22), r.equipo && Motor.truncar(r.equipo, 22), dmy(r.fecha)].filter(Boolean).join(" · "))}</span>
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

  // ── Reglas activas ─────────────────────────────────────────────────────
  function reglas() {
    const RG = D.config.reglas.datos, E = D.config.etiquetasListas, L = D.config.limites;
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
    $("#vista-reglas").innerHTML = `
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
    $("#filtros").hidden = $("#kpis").hidden = p === "reglas";
    if (p === "panel") graficos();             // Chart.js necesita el lienzo visible para medir
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
      const registros = Motor.analizarXML(await archivo.text());
      ST.todos = preparar(registros);
      ST.origen = archivo.name;
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
    if (e.target.id === "volver") { ST.todos = ST.publicados; ST.origen = null; aviso.hidden = true; reiniciar(); }
    if (e.target.id === "cerrar-aviso") aviso.hidden = true;
  });

  // ── Arranque ───────────────────────────────────────────────────────────
  function pintar() { kpis(); if (!$("#vista-panel").hidden) graficos(); lista(); }
  function reiniciar() { opciones(); reglas(); filtrar(); }
  reiniciar();
  window.Dashboard = { ST, abrir, filtrar };      // Para depurar desde la consola y para los tests
  document.documentElement.dataset.listo = "1";   // Señal para las pruebas automáticas
})();
