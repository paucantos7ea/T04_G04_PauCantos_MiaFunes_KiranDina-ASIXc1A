/* Motor de análisis en el navegador: traducción línea a línea de app/parser.py y
 * app/validator.py. Solo se usa con «Cargar otro XML local»; los datos publicados
 * vienen ya analizados por Python. Las expresiones regulares y las palabras clave
 * NO están escritas aquí: llegan en la configuración que exporta html_builder.py
 * desde config.py y rules.json, así ambos motores comparten la misma fuente.
 * tests/test_html.py comprueba en Chromium que los dos dan idéntico resultado.
 */
"use strict";

const Motor = (() => {
  let C = null;            // Configuración exportada por Python
  const R = {};            // Expresiones compiladas

  const escRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  // En Python, \b \w \W entienden Unicode; en JavaScript solo ASCII ("pcが" sería
  // fin de palabra en JS y no en Python). Se traducen a su versión Unicode.
  const PAL = "[\\p{L}\\p{N}_]";
  function py(fuente, flags = "") {
    if (!/\\[bwW]/.test(fuente)) return new RegExp(fuente, flags);
    const unicode = fuente.replace(/\\\\|\\b|\\w|\\W/g, (t) =>
      t === "\\\\" ? t
        : t === "\\b" ? `(?:(?<!${PAL})(?=${PAL})|(?<=${PAL})(?!${PAL}))`
        : t === "\\w" ? PAL : "[^\\p{L}\\p{N}_]");
    return new RegExp(unicode, flags + "u");
  }
  const mk = (o) => py(o.s, o.f);
  const todas = (re, texto) => {                       // finditer -> [coincidencias]
    const g = new RegExp(re.source, re.flags.includes("g") ? re.flags : re.flags + "g");
    return [...texto.matchAll(g)].map((m) => m[0]);
  };
  const ordenUnico = (lista) => [...new Set(lista)].sort();
  const colapsar = (t) => String(t ?? "").split(/\s+/).filter(Boolean).join(" ");
  const largo = (t) => [...t].length;                  // Puntos de código, como len() de Python

  // ── Utilidades (app/utils.py) ──────────────────────────────────────────
  function normalizar(texto) {
    return colapsar(String(texto ?? "").normalize("NFD").replace(/\p{Mn}/gu, "")
      .toLowerCase().replace(/&/g, " and "));
  }
  function truncar(texto, limite = 50) {
    const t = colapsar(texto);
    return largo(t) <= limite ? t : [...t].slice(0, limite).join("") + "[...]";
  }
  const normClave = (p) => normalizar(String(p).replace(/’/g, "'")).trim();
  const claveCampo = (n) => normalizar(n.replace(/’/g, "'"));
  function valorReal(valor) {
    const limpio = colapsar(valor);
    return R.nulos.has(normalizar(limpio)) ? "" : limpio;
  }
  function canonicoConPista(texto, tabla) {
    for (const [nombre, patron] of tabla) {
      const m = patron.exec(texto);
      if (m) return [nombre, m[0]];
    }
    return null;
  }
  function decodificarBinario(valor) {
    const bytes = (valor.match(/[01]{8}/g) || []).map((b) => parseInt(b, 2));
    const texto = new TextDecoder("utf-8").decode(new Uint8Array(bytes));
    // str.isprintable() de Python: no imprimibles = categorías C* y Z* salvo el espacio
    return [...texto].map((c) => (c !== " " && /[\p{C}\p{Z}]/u.test(c) ? "·" : c)).join("");
  }
  const pad = (n, w = 2) => String(n).padStart(w, "0");
  const fechaISO = (a, m, d) => `${pad(a, 4)}-${pad(m)}-${pad(d)}`;
  const dmy = (iso) => `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(0, 4)}`;
  function fechaValida(a, m, d) {                    // ISO o null si no existe
    if (!(a >= 1 && a <= 9999 && m >= 1 && m <= 12 && d >= 1)) return null;
    const dias = new Date(Date.UTC(2000, m, 0)).getUTCDate();
    const bisiesto = (a % 4 === 0 && a % 100 !== 0) || a % 400 === 0;
    const max = m === 2 ? (bisiesto ? 29 : 28) : dias;
    return d <= max ? fechaISO(a, m, d) : null;
  }

  // ── Configuración ──────────────────────────────────────────────────────
  function configurar(config) {
    C = config;
    for (const [k, o] of Object.entries(config.re)) R[k] = mk(o);
    R.palabra = /\p{L}{2,}/gu;                        // [^\W\d_]{2,} de Python
    R.token = /\p{L}+/gu;                             // [^\W\d_]+ de Python
    R.tipos = config.tipos.map(([n, s]) => [n, py(s)]);
    R.mapaSev = config.mapaSeveridad.map(([n, s]) => [n, py(s)]);
    R.basura = new RegExp(Object.keys(config.palabrasBasura).map(escRe).join("|"));
    R.reglas = {};
    for (const [k, s] of Object.entries(config.reglas.patrones)) R.reglas[k] = py(s);
    R.marcas = config.reglas.marcas.map(([n, s]) => [n, py(s)]);
    R.marcasCanon = new Map(config.reglas.marcas.map(([n]) => [normClave(n), n]));
    R.nulos = new Set(config.valoresNulos);
    R.esperados = new Map(config.camposEsperados.map((c) => [claveCampo(c), c]));
    R.obligatorios = new Map(config.camposObligatorios.map((c) => [normalizar(c), c]));
  }
  const patron = (k) => R.reglas[k] || /(?!x)x/;

  // ── Parser (app/parser.py) ─────────────────────────────────────────────
  class ErrorCarga extends Error {
    constructor(titulo, mensaje) { super(mensaje); this.titulo = titulo; }
  }

  function parsear(textoXml) {
    const doc = new DOMParser().parseFromString(textoXml, "application/xml");
    const error = doc.getElementsByTagName("parsererror")[0];
    if (error) throw new ErrorCarga("XML malformado",
      "El documento no es un XML bien formado.\n" + colapsar(error.textContent).slice(0, 300));
    const E = C.etiquetas, raiz = doc.documentElement;
    if (raiz.tagName !== E.raiz)
      throw new ErrorCarga("Estructura incorrecta", `La raíz es <${raiz.tagName}>, debe ser <${E.raiz}>.`);
    const errores = [], incidencias = [];
    for (const nodo of raiz.children) {
      if (nodo.tagName !== E.incidencia) {
        errores.push(`<${nodo.tagName}> dentro de <${E.raiz}>: solo se admite <${E.incidencia}>.`);
        continue;
      }
      const posicion = incidencias.length + 1;
      errores.push(...erroresEstructura(nodo, posicion));
      incidencias.push(convertir(nodo, posicion));
      if (errores.length > C.limites.maxErrores) break;
    }
    if (errores.length) {
      let lista = errores.slice(0, C.limites.maxErrores).map((e) => "• " + e).join("\n");
      if (errores.length > C.limites.maxErrores) lista += "\n• ...";
      throw new ErrorCarga("Estructura incorrecta", "El XML no tiene la estructura esperada:\n" + lista);
    }
    if (!incidencias.length) throw new ErrorCarga("Sin datos", `El XML no contiene ninguna <${E.incidencia}>.`);
    return incidencias;
  }

  function textoSuelto(nodo) {
    return [...nodo.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
  }

  function erroresEstructura(nodo, posicion) {
    const E = C.etiquetas, errores = [];
    const id = (nodo.getAttribute("id") || "").trim();
    const donde = id ? `<incidencia id="${id}">` : `<incidencia> nº ${posicion}`;
    if (!id) errores.push(`${donde}: falta el atributo id.`);
    if (textoSuelto(nodo)) errores.push(`${donde}: tiene texto suelto fuera de <${E.campo}>.`);
    const vistos = new Map();
    for (const hijo of nodo.children) {
      if (hijo.tagName !== E.campo) { errores.push(`${donde}: etiqueta <${hijo.tagName}> no permitida.`); continue; }
      const nombre = (hijo.getAttribute("nom") || "").trim();
      if (!nombre) { errores.push(`${donde}: <${E.campo}> sin atributo nom.`); continue; }
      if (hijo.children.length) errores.push(`${donde}: <${E.campo} nom="${nombre}"> contiene subetiquetas.`);
      const clave = claveCampo(nombre);
      if (!R.esperados.has(clave)) errores.push(`${donde}: campo desconocido «${nombre}».`);
      vistos.set(clave, (vistos.get(clave) || 0) + 1);
    }
    for (const [clave, original] of R.esperados) {
      const n = vistos.get(clave) || 0;
      if (n === 0) errores.push(`${donde}: falta el campo «${original}».`);
      else if (n > 1) errores.push(`${donde}: el campo «${original}» está repetido.`);
    }
    return errores;
  }

  function convertir(nodo, posicion) {
    const id = (nodo.getAttribute("id") || "").trim();
    const inc = { id: id || `SIN-ID-${posicion}`, sinId: !id, campos: new Map(), vacios: [], orden: [] };
    for (const camp of nodo.children) {
      if (camp.tagName !== C.etiquetas.campo) continue;
      const nombre = (camp.getAttribute("nom") || "").trim() || "(sin nombre)";
      const valor = camp.textContent.trim();
      let clave = nombre, n = 2;
      while (inc.campos.has(clave) || inc.vacios.includes(clave)) clave = `${nombre} (${n++})`;
      inc.orden.push(clave);
      if (valor) inc.campos.set(clave, valor); else inc.vacios.push(clave);
    }
    return inc;
  }

  // ── Campos por papel ───────────────────────────────────────────────────
  function buscarCampo(inc, re, excluir = null) {
    for (const [nombre, valor] of inc.campos)
      if (re.test(nombre) && !(excluir && excluir.test(nombre))) return [nombre, valor];
    return null;
  }

  // ── 1. Reparador ───────────────────────────────────────────────────────
  function fechaReparable(valor, ctx) {
    let m, a, mes, d;
    if ((m = R.RE_FECHA_REPARABLE_ISO.exec(valor))) [, a, mes, d] = m;
    else if ((m = R.RE_FECHA_REPARABLE_EU.exec(valor))) [, d, mes, a] = m;
    else return null;
    const f = fechaValida(+a, +mes, +d);
    if (!f) return null;
    if (+a < ctx.anyoMin || +a > ctx.anyoMax || f > ctx.hoy) return null;
    return dmy(f);
  }

  function reparar(inc, ctx) {
    inc.rep = [];
    const marca = buscarCampo(inc, R.RE_CAMPO_MARCA, R.RE_CAMPO_NO_MARCA);
    for (const [nombre, valor] of [...inc.campos]) {
      let nuevo = colapsar(valor);
      if (nuevo !== valor) inc.rep.push({ campo: nombre, antes: valor, despues: nuevo,
        motivo: "Espacios duplicados, tabulaciones o saltos de línea eliminados" });
      if (R.RE_CAMPO_FECHA.test(nombre)) {
        const f = fechaReparable(nuevo, ctx);
        if (f && f !== nuevo) {
          inc.rep.push({ campo: nombre, antes: nuevo, despues: f, motivo: "Fecha normalizada al formato DD/MM/AAAA" });
          nuevo = f;
        }
      }
      if (marca && nombre === marca[0]) {
        const canonica = R.marcasCanon.get(normClave(nuevo));
        if (canonica && canonica !== nuevo) {
          inc.rep.push({ campo: nombre, antes: nuevo, despues: canonica, motivo: "Mayúsculas de marca conocida normalizadas" });
          nuevo = canonica;
        }
      }
      inc.campos.set(nombre, nuevo);
    }
  }

  // ── 2. Detector de anomalías ───────────────────────────────────────────
  const A = (cat, regla, campo = "—", valor = "", extra = "", motivo = "") =>
    ({ cat, regla, campo, valor, extra, motivo });
  const donde = (nombre) => (R.RE_CAMPO_CORTO.test(nombre) ? ` en campo de código «${nombre}»` : "");

  function anyoIncorrecto(anyo, ctx) {
    if (anyo < ctx.anyoMin)
      return [`Fecha imposible: ${pad(anyo, 4)}`, `Año ${pad(anyo, 4)} fuera de rango válido (${ctx.anyoMin}–${ctx.anyoMax}).`];
    if (anyo > ctx.anyoMax) {
      if (ctx.anyoMax < ctx.anyoHoy)
        return [`Fecha fuera de rango: ${anyo}`, `Año ${anyo} posterior al máximo permitido (${ctx.anyoMax}).`];
      return [`Fecha futura: ${anyo}`, `Año ${anyo} posterior al actual (${ctx.anyoHoy}).`];
    }
    return null;
  }

  function reglaFecha(inc, nombre, valor, ctx) {
    if (!R.RE_CAMPO_FECHA.test(nombre)) return null;
    const mal = (regla, motivo) => A(C.cat.fecha, regla, nombre, valor, "", motivo);
    const p = R.RE_FECHA.exec(valor);
    if (p) {
      const [, a, b, c] = p;
      const [anyo, mes, dia] = a.length === 4 ? [a, b, c] : [c, b, a];
      if (anyo.length !== 4)
        return mal("Fecha con formato no reconocido",
          `«${valor.trim()}» no tiene un año de 4 cifras (se espera DD/MM/AAAA o AAAA-MM-DD).`);
      const malo = anyoIncorrecto(+anyo, ctx);
      if (malo) return mal(...malo);
      const f = fechaValida(+anyo, +mes, +dia);
      if (!f) return mal(`Fecha imposible: ${valor.trim()} (día o mes inexistente)`,
        `El día ${+dia} del mes ${+mes} no existe en el calendario.`);
      if (f > ctx.hoy) return mal(`Fecha futura: ${dmy(f)}`, `${dmy(f)} es posterior a hoy (${dmy(ctx.hoy)}).`);
      inc.fecha = f;
      return null;
    }
    const anyos = valor.match(/(?<!\d)\d{4}(?!\d)/g) || [];
    if (!anyos.length)
      return mal("Fecha sin formato reconocible", `«${truncar(valor, 40)}» no contiene ninguna fecha ni año reconocible.`);
    for (const anyo of anyos) {
      const malo = anyoIncorrecto(+anyo, ctx);
      if (malo) return mal(...malo);
    }
    return null;
  }

  function reglaBinario(inc, nombre, valor) {
    if (!R.RE_BINARIO.test(valor)) return null;
    const dec = decodificarBinario(valor);
    return A(C.cat.basura, `Contenido basura${donde(nombre)}: secuencia de código binario`, nombre, valor,
      dec ? `Decodificado: «${dec}»` : "",
      `Contiene ${(valor.match(/[01]{8}/g) || []).length} bytes en binario (grupos de 8 ceros/unos) en lugar de texto humano.`);
  }

  function reglaAmarico(inc, nombre, valor) {
    const letra = R.RE_AMARICO.exec(valor);
    if (!letra) return null;
    return A(C.cat.basura, `Contenido basura${donde(nombre)}: texto en amárico`, nombre, valor, "",
      `Contiene escritura etíope (amárico, p. ej. «${letra[0]}»), ajena al idioma del formulario.`);
  }

  function reglaPalabras(inc, nombre, valor) {
    const encontradas = ordenUnico(todas(R.basura, normalizar(valor)));
    if (!encontradas.length) return null;
    const P = C.palabrasBasura;
    const tipos = ordenUnico(encontradas.map((p) => P[p]));
    const detalle = encontradas.map((p) => `"${p}" (${P[p]})`).join(", ");
    return A(C.cat.basura, `Contenido basura${donde(nombre)}: ${tipos.join(", ")}`, nombre, valor,
      "Palabras: " + encontradas.join(", "), `Contiene la expresión prohibida ${detalle}.`);
  }

  function evaluarCoherencia(texto) {
    const L = C.limites;
    const norm = normalizar(texto.replace(/’/g, "'"));
    const sintomas = ordenUnico(todas(patron("sintomas"), norm));
    const dispositivos = ordenUnico(todas(patron("dispositivos"), norm));
    const fuerza = 2 * sintomas.length + dispositivos.length;
    const palabras = texto.match(R.palabra) || [];
    if (!palabras.length)
      return ["Descripción sin palabras", `«${truncar(texto, 40)}» no contiene ninguna palabra: no describe ninguna avería.`, ""];
    const tokens = (texto.match(R.token) || []).map(normalizar);
    const esLargo = tokens.length >= L.minPalabrasParrafo;
    if (fuerza >= (esLargo ? 3 : 2)) return null;
    const tecnico = dispositivos.length
      ? `solo aparece «${dispositivos[0]}», sin ningún síntoma de avería`
      : "ninguna palabra técnica ni síntoma de avería";
    if (R.RE_FRASES_FAKER.test(texto.trim())) {
      const romanos = new Set(C.numerosRomanos), propios = new Set(C.nombresFaker);
      const sueltas = ordenUnico(tokens.filter((t) => romanos.has(t) || (largo(t) === 1 && !"aeiouy".includes(t))));
      const nombres = ordenUnico(tokens.filter((t) => propios.has(t)));
      const senales = [];
      if (nombres.length) senales.push("nombres propios/lugares al azar: " + nombres.join(", "));
      if (sueltas.length) senales.push("letras o números romanos sueltos: " + sueltas.join(", "));
      if (tokens.length < L.minPalabrasFaker && !senales.length) return null;
      const frases = Math.max(1, (texto.match(/\./g) || []).length);
      const motivo = `${tecnico[0].toUpperCase()}${tecnico.slice(1)}; ${frases} micro-frase${frases > 1 ? "s" : ""} ` +
        "de palabras inconexas sin conectores ni puntuación interna (patrón de generador aleatorio tipo Faker)" +
        (senales.length ? `; ${senales.join("; ")}` : "") + ".";
      return ["Texto aleatorio / sin sentido (tipo Faker)", motivo, senales.length ? "Señales: " + senales.join("; ") : ""];
    }
    if (esLargo || (fuerza === 0 && tokens.length >= L.minPalabrasProsa)) {
      const pistas = [...sintomas, ...dispositivos];
      const detalle = pistas.length ? `solo ${pistas.length} término técnico de pasada (${pistas.join(", ")})` : tecnico;
      return ["Texto sin relación con soporte técnico",
        `${tokens.length} palabras y ${detalle}: no describe una incidencia informática.`, ""];
    }
    return null;
  }

  function reglaSinSentido(inc, nombre, valor) {
    const desc = buscarCampo(inc, R.RE_CAMPO_DESCRIPCION);
    if (!desc || desc[0] !== nombre) return null;
    const v = evaluarCoherencia(valor);
    if (!v) return null;
    const [regla, motivo, extra] = v;
    return A(C.cat.sinSentido, regla, nombre, valor, extra, motivo);
  }

  function reglaDesborde(inc, nombre, valor) {
    const max = C.limites.maxLongitudCorto, n = largo(valor);
    if (R.RE_CAMPO_CORTO.test(nombre) && n > max)
      return A(C.cat.desborde, `Desbordamiento de texto: >${max} caracteres (${n}) en un campo breve`, nombre, valor, "",
        `Campo breve (código/identificador) con ${n} caracteres; el máximo admitido es ${max}.`);
    return null;
  }

  function validar(inc, ctx) {
    inc.anom = [];
    if (inc.sinId) inc.anom.push(A(C.cat.vacio, "Incidencia sin atributo id", "id", "", "",
      "La etiqueta <incidencia> no tiene atributo id: no se puede identificar ni deduplicar el registro."));
    if (!inc.campos.size && !inc.vacios.length)
      inc.anom.push(A(C.cat.vacio, "Incidencia sin ningún campo", "—", "", "", "La <incidencia> no contiene ningún <camp>."));
    for (const nombre of inc.vacios) {
      if (R.RE_CAMPO_OPCIONAL.test(nombre) && !R.RE_CAMPO_NO_MARCA.test(nombre)) continue;
      inc.anom.push(A(C.cat.vacio, "Campo obligatorio vacío / etiqueta de autocierre", nombre, `<camp nom="${nombre}"/>`, "",
        `El campo «${nombre}» llega vacío y es obligatorio (solo marca y modelo pueden faltar).`));
    }
    const presentes = new Set([...inc.campos.keys(), ...inc.vacios].map(normalizar));
    for (const [clave, original] of R.obligatorios)
      if (!presentes.has(clave)) inc.anom.push(A(C.cat.vacio, "Campo obligatorio ausente", original, "(no existe)", "",
        `Falta el campo obligatorio «${original}».`));
    const reglas = [reglaFecha, reglaBinario, reglaAmarico, reglaPalabras, reglaSinSentido, reglaDesborde];
    for (const [nombre, valor] of inc.campos)
      for (const regla of reglas) {
        const a = regla(inc, nombre, valor, ctx);
        if (a) inc.anom.push(a);
      }
  }

  // ── 3. Clasificador ────────────────────────────────────────────────────
  function deducir(tabla, textoEquipo, textoDesc) {
    for (const [d, texto] of [["del equipo/modelo", textoEquipo], ["de la descripción", textoDesc]]) {
      const e = canonicoConPista(texto, tabla);
      if (e) return [e[0], `Deducida ${d}: patrón "${e[1]}"`];
    }
    return null;
  }

  function categoria(inc, textoEquipo, textoDesc) {
    const campo = buscarCampo(inc, R.RE_CAMPO_TIPO);
    const real = campo ? valorReal(campo[1]) : "";
    if (real) {
      const e = canonicoConPista(normalizar(real), R.tipos);
      if (e) return [e[0], `Campo «${campo[0]}»: "${truncar(real, 60)}" (unificado)`];
      return [real, `Campo «${campo[0]}»: "${truncar(real, 60)}" (valor literal)`];
    }
    return deducir(R.tipos, textoEquipo, textoDesc) ||
      [C.defectos.categoria, "Por defecto: ni el equipo ni la descripción encajan con ninguna categoría"];
  }

  function marca(inc, textoEquipo, textoDesc) {
    const campo = buscarCampo(inc, R.RE_CAMPO_MARCA, R.RE_CAMPO_NO_MARCA);
    const real = campo ? valorReal(campo[1]) : "";
    if (real) {
      const e = canonicoConPista(normalizar(real), R.marcas);
      if (e) return [e[0], `Campo «${campo[0]}»: "${truncar(real, 60)}"`];
      return [real, `Campo «${campo[0]}»: "${truncar(real, 60)}" (marca no catalogada, literal)`];
    }
    return deducir(R.marcas, textoEquipo, textoDesc) ||
      [null, "Campo de marca vacío y ninguna marca conocida en el equipo ni la descripción"];
  }

  function buscarEn(re, fuentes) {
    for (const [d, texto] of fuentes) {
      const m = re.exec(texto);
      if (m) return [m[0], d];
    }
    return null;
  }
  const pista = (re, fuentes, respaldo) => {
    const e = buscarEn(re, fuentes);
    return e ? `Palabra clave: "${e[0]}" (en ${e[1]})` : `Palabra clave: "${respaldo}"`;
  };

  function afectadosMultiples(inc) {
    const campo = buscarCampo(inc, R.RE_CAMPO_AFECTADOS);
    if (campo && patron("afectados_multiples").test(normalizar(campo[1].replace(/’/g, "'")))) return campo[1];
    return null;
  }

  function severidad(inc, fuentes) {
    const campo = buscarCampo(inc, R.RE_CAMPO_SEVERIDAD);
    if (campo) {
      const valor = normalizar(campo[1]);
      for (const [nivel, re] of R.mapaSev) {
        const m = re.exec(valor);
        if (m) return [nivel, false, `Campo de prioridad «${campo[0]}»`, `Valor "${truncar(campo[1], 60)}" (patrón "${m[0]}")`];
      }
    }
    const desc = fuentes[0][1], equipo = fuentes[1][1];
    const texto = fuentes.map((f) => f[1]).join(" ");
    const infra = buscarEn(patron("critica_infraestructura"), [["la descripción", desc], ["el equipo", equipo]]);
    const multi = patron("critica_multiusuario").exec(desc);
    const T1 = "Paso 1 · Caída de infraestructura o corte general";
    const general = patron("critica_caida_general").exec(desc);
    if (general) return ["Crítica", true, T1, `Caída general descrita: "${general[0]}" (en la descripción)`];
    const caida = patron("critica_caida").exec(desc);
    if (caida) {
      if (infra) return ["Crítica", true, T1, `Síntoma "${caida[0]}" (en la descripción) + infraestructura "${infra[0]}" (en ${infra[1]})`];
      if (multi) return ["Crítica", true, T1, `Síntoma "${caida[0]}" + impacto multiusuario "${multi[0]}" (en la descripción)`];
    }
    const hw = patron("alta_hardware").exec(texto);
    if (hw) return ["Alta", true, "Paso 2 · Hardware crítico del equipo", pista(patron("alta_hardware"), fuentes, hw[0])];
    if (infra) {
      const afectados = multi ? null : afectadosMultiples(inc);
      if (multi || afectados) {
        const impacto = multi ? `"${multi[0]}" (en la descripción)` : `campo de afectados = "${afectados}"`;
        return ["Alta", true, "Paso 3 · Infraestructura con impacto multiusuario",
          `Infraestructura "${infra[0]}" (en ${infra[1]}) + ${impacto}, sin caída descrita`];
      }
    }
    for (const [paso, nivel, titulo, lista] of [[4, "Leve", "Periféricos y consumibles", "leve_perifericos"],
      [5, "Alta", "El equipo no arranca", "alta_arranque"], [6, "Media", "Software o error genérico", "media_generico"]]) {
      const m = patron(lista).exec(texto);
      if (m) return [nivel, true, `Paso ${paso} · ${titulo}`, pista(patron(lista), fuentes, m[0])];
    }
    return [C.defectos.severidad, true, "Paso 7 · Sin pistas", "Por defecto: fallo genérico (ninguna palabra clave reconocida)"];
  }

  function enriquecer(inc) {
    const eq = buscarCampo(inc, R.RE_CAMPO_EQUIPO, R.RE_CAMPO_NO_EQUIPO);
    inc.equipo = eq ? eq[1].trim() : "";
    const d = buscarCampo(inc, R.RE_CAMPO_DESCRIPCION);
    inc.desc = d ? d[1] : [...inc.campos.values()].reduce((a, b) => (largo(b) > largo(a) ? b : a), "");
    const modelo = buscarCampo(inc, R.RE_CAMPO_MODELO, R.RE_CAMPO_MARCA);
    const textoEquipo = normalizar([inc.equipo, modelo ? modelo[1] : ""].filter(Boolean).join(" ").replace(/’/g, "'"));
    const textoDesc = normalizar(inc.desc.replace(/’/g, "'"));
    [inc.cat, inc.oTipo] = categoria(inc, textoEquipo, textoDesc);
    [inc.marca, inc.oMarca] = marca(inc, textoEquipo, textoDesc);
    const fuentes = [["la descripción", textoDesc], ["el equipo", textoEquipo], ["la categoría", normalizar(inc.cat)]];
    [inc.sev, inc.inferida, inc.criterio, inc.regla] = severidad(inc, fuentes);
    const infra = buscarEn(patron("critica_infraestructura"), fuentes.slice(0, 2));
    inc.notaInfra = infra && inc.sev !== "Crítica" && inc.inferida
      ? `Equipo de infraestructura ("${infra[0]}"), pero la descripción no describe ninguna caída ni corte general: no se marca Crítica.`
      : "";
  }

  // ── Tubería completa ───────────────────────────────────────────────────
  function contexto(hoyISO) {
    const hoy = hoyISO || new Date().toISOString().slice(0, 10);
    const a = C.reglas.datos.anyos;
    return { hoy, anyoHoy: +hoy.slice(0, 4), anyoMin: a.minimo, anyoMax: a.maximo || +hoy.slice(0, 4) };
  }

  /** Registro con la misma forma que los datos publicados (ver html_builder.py). */
  function aRegistro(inc) {
    const zona = buscarCampo(inc, R.RE_CAMPO_ZONA), codigo = buscarCampo(inc, R.RE_CAMPO_CODIGO);
    return {
      id: inc.id, valida: !inc.anom.length, sev: inc.sev, inferida: inc.inferida, cat: inc.cat,
      marca: inc.marca, equipo: inc.equipo, fecha: inc.fecha || null, desc: inc.desc,
      criterio: inc.criterio, regla: inc.regla, oTipo: inc.oTipo, oMarca: inc.oMarca,
      notaInfra: inc.notaInfra, zona: zona ? colapsar(zona[1]) : "", codigo: codigo ? colapsar(codigo[1]).toUpperCase() : "",
      anom: inc.anom.map((a) => ({ ...a, tipo: C.tipoAnomalia[a.cat] || a.cat, motivo: a.motivo || a.regla })),
      rep: inc.rep, campos: inc.orden.map((n) => [n, inc.campos.has(n) ? inc.campos.get(n) : null]),
    };
  }

  function analizarIncidencias(lista, hoyISO) {
    const ctx = contexto(hoyISO);
    return lista.map((inc) => {
      inc.fecha = null;
      reparar(inc, ctx);
      validar(inc, ctx);
      enriquecer(inc);
      return aRegistro(inc);
    });
  }

  return {
    configurar, ErrorCarga, normalizar, truncar,
    analizarXML: (texto, hoyISO) => analizarIncidencias(parsear(texto), hoyISO),
    analizarIncidencias,
  };
})();
