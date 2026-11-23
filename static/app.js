// ===================================================== utilidades
const $ = (id) => document.getElementById(id);
const COLORES = ["#ff3d6e", "#3dd6ff", "#ffb23d", "#3ddc97", "#b47dff", "#ff7d3d", "#7dff5a", "#ff5ad1"];
const NOMBRES_PRESET = { tiktok: "TikTok", karaoke: "Karaoke", palabra: "Palabra a palabra", frase: "Frase" };
let ESTADO = null;      // /api/estado
let P = null;           // proyecto abierto
let segSel = null;      // segmento seleccionado en la línea de tiempo
let trabajando = false;

async function api(ruta, opciones = {}) {
  const o = { ...opciones };
  if (o.json !== undefined) {
    o.body = JSON.stringify(o.json);
    o.headers = { "Content-Type": "application/json" };
    delete o.json;
  }
  const r = await fetch(ruta, o);
  let datos = null;
  try { datos = await r.json(); } catch { /* sin cuerpo */ }
  if (!r.ok) throw new Error((datos && datos.detail) || `Error ${r.status}`);
  return datos;
}

function aviso(texto, bien = false) {
  const a = $("aviso");
  a.textContent = texto;
  a.className = "aviso" + (bien ? " bien" : "");
  clearTimeout(aviso.t);
  aviso.t = setTimeout(() => a.classList.add("oculto"), bien ? 3000 : 9000);
}

function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

const fmt = (s) => {
  s = Math.max(0, +s || 0);
  const m = Math.floor(s / 60);
  return `${m}:${(s - m * 60).toFixed(2).padStart(5, "0")}`;
};
const leerTiempo = (txt) => {
  txt = String(txt).trim().replace(",", ".");
  if (txt.includes(":")) {
    const [m, s] = txt.split(":");
    return (+m) * 60 + (+s);
  }
  return +txt;
};

// ===================================================== arranque
async function cargarEstado() {
  ESTADO = await api("/api/estado");
  const c = $("chipIA");
  c.textContent = ESTADO.ia ? "IA activa" : "Sin IA (montaje automático)";
  c.className = "chip" + (ESTADO.ia ? " ok" : "");
  if (!ESTADO.ffmpeg) aviso("No encuentro FFmpeg. Ejecuta instalar.bat y reinicia el ordenador.");
}

async function mostrarInicio() {
  P = null;
  history.replaceState(null, "", "/");
  $("pantallaInicio").classList.remove("oculto");
  $("pantallaEditor").classList.add("oculto");
  $("nombreProyecto").classList.add("oculto");
  const lista = await api("/api/proyectos");
  const cont = $("listaProyectos");
  cont.innerHTML = lista.length ? "" : `<p class="ayuda">Aún no tienes vídeos. Crea el primero.</p>`;
  for (const p of lista) {
    const d = document.createElement("div");
    d.className = "tarjeta";
    d.innerHTML = `<div class="mini"></div><div class="info"><div class="nom"></div>
      <small>${p.clips} clip${p.clips === 1 ? "" : "s"} · ${new Date(p.modificado * 1000).toLocaleString()}</small></div>`;
    d.querySelector(".nom").textContent = p.nombre;
    if (p.miniatura) d.querySelector(".mini").style.backgroundImage = `url("${p.miniatura}")`;
    d.onclick = () => abrir(p.id);
    cont.appendChild(d);
  }
}

async function abrir(id) {
  P = await api(`/api/proyectos/${id}`);
  history.replaceState(null, "", `/?p=${id}`);
  $("pantallaInicio").classList.add("oculto");
  $("pantallaEditor").classList.remove("oculto");
  $("nombreProyecto").classList.remove("oculto");
  pintarTodo();
}

// ===================================================== pintar
function pintarTodo() {
  $("nombreProyecto").value = P.nombre;
  $("letra").value = P.letra || "";
  $("peticion").value = P.peticion || "";
  $("duracion").value = P.duracion || 0;
  $("idioma").value = P.idioma ?? "es";
  $("modeloVoz").value = P.modelo_voz || "small";
  pintarFormatos();
  pintarClips();
  pintarCancion();
  pintarVideo();
  pintarMontaje();
  pintarEstilo();
  pintarSubs();
  pintarExportados();
  actualizarBotones();
}

function pintarFormatos() {
  const cont = $("formatos");
  cont.innerHTML = "";
  const dims = { "9:16": [9, 16], "16:9": [16, 9], "1:1": [12, 12], "4:5": [10, 12.5] };
  for (const f of ESTADO.formatos) {
    const b = document.createElement("button");
    const [w, h] = dims[f] || [12, 12];
    b.innerHTML = `<i style="width:${w}px;height:${h}px"></i>${f}`;
    b.className = f === P.formato ? "activo" : "";
    b.onclick = async () => {
      P = await api(`/api/proyectos/${P.id}`, { method: "PUT", json: { formato: f } });
      pintarFormatos(); pintarVideo();
      if (P.plan) aviso("Formato cambiado. Pulsa «Actualizar vista previa» para verlo.", true);
    };
    cont.appendChild(b);
  }
  const clase = { "9:16": "f916", "16:9": "f169", "1:1": "f11", "4:5": "f45" }[P.formato] || "f916";
  $("marcoVideo").className = "marco " + clase;
}

function pintarClips() {
  const cont = $("listaClips");
  cont.innerHTML = "";
  P.clips.forEach((c, i) => {
    const d = document.createElement("div");
    d.className = "clip";
    d.innerHTML = `<img src="${c.miniatura}" alt="">
      <span class="num" style="background:${COLORES[i % COLORES.length]}">${i + 1}</span>
      <div class="txt"><div></div><small>${c.duracion.toFixed(1)} s · ${c.ancho}×${c.alto}${c.tiene_audio ? "" : " · sin sonido"}</small></div>
      <div class="botones">
        <button title="Subir" data-a="arriba">▲</button>
        <button title="Quitar" data-a="quitar">✕</button>
        <button title="Bajar" data-a="abajo">▼</button>
      </div>`;
    d.querySelector(".txt div").textContent = c.nombre;
    d.querySelectorAll("button").forEach((b) => (b.onclick = () => accionClip(i, b.dataset.a)));
    cont.appendChild(d);
  });
}

async function accionClip(i, accion) {
  if (trabajando) return aviso("Espera a que termine el proceso actual.");
  if (accion === "quitar") {
    if (P.plan && !confirm("Si quitas un clip habrá que volver a crear el montaje. ¿Seguir?")) return;
    P = await api(`/api/proyectos/${P.id}/clips/${i}`, { method: "DELETE" });
  } else {
    const j = accion === "arriba" ? i - 1 : i + 1;
    if (j < 0 || j >= P.clips.length) return;
    const orden = P.clips.map((_, k) => k);
    [orden[i], orden[j]] = [orden[j], orden[i]];
    P = await api(`/api/proyectos/${P.id}/clips/orden`, { method: "POST", json: { orden } });
  }
  pintarTodo();
}

function pintarCancion() {
  const c = P.cancion;
  $("infoCancion").classList.toggle("oculto", !c);
  $("zonaCancion").classList.toggle("oculto", !!c);
  $("campoInicioCancion").classList.toggle("oculto", !c);
  $("campoRitmo").classList.toggle("oculto", !c);
  if (c) {
    $("nombreCancion").textContent = "🎵 " + c.nombre;
    const a = $("audioCancion");
    if (!a.src.endsWith(c.url)) a.src = c.url;
  }
}

function pintarVideo() {
  const v = $("video");
  if (P.ultimo_render) {
    if (v.getAttribute("src") !== P.ultimo_render) v.src = P.ultimo_render;
    $("vacio").classList.add("oculto");
  } else {
    v.removeAttribute("src"); v.load();
    $("vacio").classList.remove("oculto");
    $("vacio").innerHTML = P.plan
      ? "Montaje listo.<br>Pulsa <b>Actualizar vista previa</b>."
      : "Aquí verás tu vídeo.<br>Sube clips y pulsa <b>Crear vídeo</b>.";
  }
  const ex = $("explicacion");
  const texto = P.plan && P.plan.explicacion;
  ex.classList.toggle("oculto", !texto);
  if (texto) ex.textContent = (P.plan.origen === "ia" ? "🤖 " : "⚙️ ") + texto;
}

function pintarMontaje() {
  const panel = $("panelMontaje");
  panel.classList.toggle("oculto", !P.plan);
  if (!P.plan) return;
  const pl = P.plan;
  $("inicioCancion").value = pl.inicio_cancion ?? 0;
  $("duracionMontaje").value = pl.duracion;
  $("encuadre").value = pl.encuadre || "llenar";
  const r = pl.ritmo || [];
  const unico = r.length === 1 && r[0].cada_beats;
  $("ritmo").value = unico && ["1", "2", "4", "8"].includes(String(r[0].cada_beats)) ? String(r[0].cada_beats) : "ia";
  const tl = $("timeline");
  tl.innerHTML = "";
  const total = pl.duracion || 1;
  pl.segmentos.forEach((s, i) => {
    const d = document.createElement("div");
    d.className = "seg" + (segSel === i ? " sel" : "");
    d.style.flex = `${(s.fin - s.inicio) / total} 0 0`;
    d.style.setProperty("--c", COLORES[s.clip % COLORES.length]);
    const c = P.clips[s.clip];
    if (c) d.style.backgroundImage = `url("${c.miniatura}")`;
    d.title = `Clip ${s.clip + 1} · ${(s.fin - s.inicio).toFixed(2)} s`;
    d.onclick = () => { segSel = i; pintarMontaje(); };
    tl.appendChild(d);
  });
  pintarEditorSegmento();
}

function pintarEditorSegmento() {
  const ed = $("editorSegmento");
  const s = P.plan && P.plan.segmentos[segSel];
  ed.classList.toggle("oculto", !s);
  if (!s) return;
  const opciones = P.clips.map((c, i) => `<option value="${i}" ${i === s.clip ? "selected" : ""}>Clip ${i + 1}</option>`).join("");
  ed.innerHTML = `<b style="align-self:center">Trozo ${segSel + 1}</b>
    <label>Clip<select id="sClip">${opciones}</select></label>
    <label>Desde el segundo<input id="sEntrada" type="number" step="0.1" min="0" value="${s.entrada}"></label>
    <label>Dura (s)<input id="sDur" type="number" step="0.05" min="0.2" value="${(s.fin - s.inicio).toFixed(2)}"></label>
    <button class="btn mini" id="sVer">Ver</button>
    <button class="btn mini fantasma" id="sQuitar">Quitar</button>
    <button class="btn mini fantasma" id="sCerrar">✕</button>`;
  const guardarSeg = async () => {
    const segs = P.plan.segmentos.map((x) => ({ ...x }));
    const x = segs[segSel];
    const dur = Math.max(0.2, +$("sDur").value);
    x.clip = +$("sClip").value; x.entrada = +$("sEntrada").value; x.fin = x.inicio + dur;
    await guardarSegmentos(segs);
  };
  ["sClip", "sEntrada", "sDur"].forEach((id) => ($(id).onchange = guardarSeg));
  $("sVer").onclick = () => { const v = $("video"); if (v.src) { v.currentTime = s.inicio + 0.01; v.play(); } };
  $("sQuitar").onclick = async () => {
    const segs = P.plan.segmentos.filter((_, k) => k !== segSel);
    segSel = null;
    await guardarSegmentos(segs);
  };
  $("sCerrar").onclick = () => { segSel = null; pintarMontaje(); };
}

async function guardarSegmentos(segs) {
  P = await api(`/api/proyectos/${P.id}`, { method: "PUT", json: { plan: { segmentos: segs } } });
  pintarMontaje();
  aviso("Montaje cambiado a mano. Actualiza la vista previa para verlo.", true);
}

// ---------- estilo de subtítulos
function estilo() { return (P.plan && P.plan.estilo) || ESTADO.estilo_defecto; }

function pintarEstilo() {
  const e = estilo();
  const presets = $("presets");
  presets.innerHTML = "";
  for (const [k, desc] of Object.entries(ESTADO.presets)) {
    const b = document.createElement("button");
    b.className = "preset" + (e.preset === k ? " activo" : "");
    b.innerHTML = `<b>${NOMBRES_PRESET[k] || k}</b><small>${desc}</small>`;
    b.onclick = () => cambiarEstilo({ preset: k });
    presets.appendChild(b);
  }
  $("eFuente").innerHTML = ESTADO.fuentes.map((f) => `<option ${f === e.fuente ? "selected" : ""}>${f}</option>`).join("");
  $("eTamano").value = e.tamano;
  $("ePosicion").value = e.posicion;
  $("eAnimacion").value = e.animacion;
  $("eColor").value = e.color;
  $("eResaltado").value = e.resaltado;
  $("eBordeColor").value = e.borde_color;
  $("eBorde").value = e.borde;
  $("ePalabras").value = e.palabras_por_bloque;
  $("eMayus").checked = !!e.mayusculas;
  $("subsActivos").checked = !P.plan || P.plan.subtitulos !== false;
  pintarMuestra();
}

function pintarMuestra() {
  const e = estilo();
  const t = $("muestraTexto");
  const may = (w) => (e.mayusculas ? w.toUpperCase() : w);
  const pal = ["así", "se", "verán"].map(may);
  const res = `<span style="color:${e.resaltado}">`;
  t.innerHTML = {
    tiktok: `${res}${pal[0]}</span> ${pal[1]} ${pal[2]}`,
    karaoke: `${res}${pal[0]} ${pal[1]}</span> ${pal[2]}`,
    palabra: `${res}${pal[2]}</span>`,
    frase: pal.join(" "),
  }[e.preset] || pal.join(" ");
  t.style.fontFamily = `"${e.fuente}", sans-serif`;
  t.style.fontWeight = e.fuente === "Poppins" ? 700 : 400;
  t.style.fontSize = `${Math.round(e.tamano * 0.36)}px`;
  t.style.color = e.color;
  const b = e.borde * 0.4;
  t.style.webkitTextStroke = b > 0 ? `${b}px ${e.borde_color}` : "0";
  t.style.paintOrder = "stroke fill";
  t.style.textShadow = e.sombra ? `2px 2px 0 ${e.borde_color}99` : "none";
  $("muestra").style.placeItems = { arriba: "start center", centro: "center", abajo: "end center" }[e.posicion];
  $("muestra").style.padding = "12px 0";
}

const guardarEstilo = debounce(async (cambios) => {
  if (!P.plan) return;
  P = await api(`/api/proyectos/${P.id}`, { method: "PUT", json: { plan: { estilo: cambios } } });
}, 400);
let estiloPendiente = {};
function cambiarEstilo(cambios) {
  if (!P.plan) return aviso("Crea el vídeo primero; luego podrás cambiar el estilo.");
  Object.assign(P.plan.estilo, cambios);
  estiloPendiente = { ...estiloPendiente, ...cambios };
  pintarEstilo();
  guardarEstilo(estiloPendiente);
  setTimeout(() => (estiloPendiente = {}), 450);
}

// ---------- líneas de subtítulos
function pintarSubs() {
  const cont = $("listaSubs");
  cont.innerHTML = "";
  if (!P.subtitulos || !P.subtitulos.length) {
    cont.innerHTML = `<p class="ayuda">${P.plan ? "No hay subtítulos. Añade líneas a mano o pulsa Regenerar." : "Aparecerán al crear el vídeo."}</p>`;
    return;
  }
  P.subtitulos.forEach((l, i) => {
    const d = document.createElement("div");
    d.className = "linea-sub";
    d.dataset.i = i;
    d.innerHTML = `<div class="tiempos">
        <input class="t0" value="${fmt(l.inicio)}" title="Empieza"><span class="flecha">→</span>
        <input class="t1" value="${fmt(l.fin)}" title="Termina">
        <button class="ir" title="Escuchar">▶</button><button class="del" title="Borrar">✕</button></div>
      <textarea rows="1"></textarea>`;
    const ta = d.querySelector("textarea");
    ta.value = l.texto;
    ta.oninput = () => { l.texto = ta.value; guardarSubs(); };
    d.querySelector(".t0").onchange = (ev) => { l.inicio = leerTiempo(ev.target.value); ev.target.value = fmt(l.inicio); delete l.palabras; guardarSubs(); };
    d.querySelector(".t1").onchange = (ev) => { l.fin = leerTiempo(ev.target.value); ev.target.value = fmt(l.fin); delete l.palabras; guardarSubs(); };
    d.querySelector(".ir").onclick = () => { const v = $("video"); if (v.src) { v.currentTime = l.inicio; v.play(); } };
    d.querySelector(".del").onclick = () => { P.subtitulos.splice(i, 1); pintarSubs(); guardarSubs(); };
    cont.appendChild(d);
  });
}

const guardarSubs = debounce(async () => {
  await api(`/api/proyectos/${P.id}`, { method: "PUT", json: { subtitulos: P.subtitulos } });
}, 600);

function marcarLineaActual() {
  const t = $("video").currentTime;
  document.querySelectorAll(".linea-sub").forEach((d) => {
    const l = P.subtitulos[+d.dataset.i];
    const dentro = l && t >= l.inicio && t < l.fin;
    if (dentro && !d.classList.contains("actual")) d.scrollIntoView({ block: "nearest", behavior: "smooth" });
    d.classList.toggle("actual", !!dentro);
  });
}

function pintarExportados() {
  const cont = $("exportados");
  const ex = P.exportados || [];
  cont.innerHTML = "";
  if (!ex.length) return;
  const ult = ex[ex.length - 1];
  cont.innerHTML = `<span>Último exportado: <a href="${ult.url}" target="_blank">abrir vídeo</a> ·
    <a href="#" id="abrirCarpeta">abrir carpeta</a></span>`;
  $("abrirCarpeta").onclick = (e) => { e.preventDefault(); api(`/api/proyectos/${P.id}/abrir_carpeta`, { method: "POST" }); };
}

function actualizarBotones() {
  const hayPlan = !!(P && P.plan);
  $("btnCrear").disabled = trabajando || !P.clips.length;
  $("btnCrear").textContent = hayPlan ? "✨ Volver a crear desde cero" : "✨ Crear vídeo";
  $("btnPreview").disabled = trabajando || !hayPlan;
  $("btnExportar").disabled = trabajando || !hayPlan;
  $("inputCambio").disabled = trabajando || !hayPlan;
  $("btnCambio").disabled = trabajando || !hayPlan;
  $("btnRemontar").disabled = trabajando;
  $("btnBarajar").disabled = trabajando;
  $("btnRegenerar").disabled = trabajando || !hayPlan;
  $("inputCambio").placeholder = ESTADO.ia
    ? "Pide cambios: «más cortes en el estribillo», «empieza en el segundo 45», «subtítulos abajo y en blanco»…"
    : "Para pedir cambios con texto, añade tu API key en Ajustes";
}

// ===================================================== trabajos largos
async function esperarTrabajo(tid) {
  trabajando = true;
  actualizarBotones();
  $("progreso").classList.remove("oculto");
  try {
    for (;;) {
      const t = await api(`/api/trabajos/${tid}`);
      $("progresoRelleno").style.width = `${Math.round(t.progreso * 100)}%`;
      $("progresoTexto").textContent = t.mensaje;
      if (t.estado === "hecho") return t.resultado;
      if (t.estado === "error") throw new Error(t.mensaje);
      await new Promise((r) => setTimeout(r, 700));
    }
  } finally {
    trabajando = false;
    $("progreso").classList.add("oculto");
    if (P) actualizarBotones();
  }
}

async function ejecutar(ruta, json, despues) {
  try {
    await guardarCamposPendientes();
    const { trabajo } = await api(ruta, { method: "POST", json: json || {} });
    const r = await esperarTrabajo(trabajo);
    await despues(r);
  } catch (e) {
    aviso(e.message);
  }
}

async function crearVideo() {
  await ejecutar(`/api/proyectos/${P.id}/crear`, {}, async () => {
    P = await api(`/api/proyectos/${P.id}`);
    segSel = null;
    pintarTodo();
    await vistaPrevia();
  });
}

async function vistaPrevia() {
  await ejecutar(`/api/proyectos/${P.id}/render`, { preview: true }, async (r) => {
    P.ultimo_render = r.url;
    pintarVideo();
    $("video").play().catch(() => {});
  });
}

async function exportar() {
  await ejecutar(`/api/proyectos/${P.id}/render`, { preview: false }, async () => {
    P = await api(`/api/proyectos/${P.id}`);
    pintarExportados();
    aviso("¡Vídeo exportado! Está en la carpeta «exportados» del proyecto (con su .srt).", true);
  });
}

async function pedirCambio() {
  const texto = $("inputCambio").value.trim();
  if (!texto) return;
  await ejecutar(`/api/proyectos/${P.id}/cambiar`, { peticion: texto }, async () => {
    $("inputCambio").value = "";
    P = await api(`/api/proyectos/${P.id}`);
    segSel = null;
    pintarTodo();
    await vistaPrevia();
  });
}

async function remontar(extra = {}) {
  const datos = {
    inicio_cancion: +$("inicioCancion").value || 0,
    duracion: +$("duracionMontaje").value || 0,
    encuadre: $("encuadre").value,
    ...extra,
  };
  const r = $("ritmo").value;
  if (r !== "ia") datos.ritmo = [{ hasta: 99999, cada_beats: +r }];
  await ejecutar(`/api/proyectos/${P.id}/remontar`, datos, async () => {
    P = await api(`/api/proyectos/${P.id}`);
    segSel = null;
    pintarTodo();
    await vistaPrevia();
  });
}

// ===================================================== subidas
async function subirClips(archivos) {
  if (!archivos.length) return;
  const fd = new FormData();
  for (const a of archivos) fd.append("archivos", a);
  $("zonaClips").querySelector("strong").textContent = `Subiendo ${archivos.length} vídeo(s)…`;
  try {
    P = await api(`/api/proyectos/${P.id}/clips`, { method: "POST", body: fd });
    pintarTodo();
  } catch (e) { aviso(e.message); }
  $("zonaClips").querySelector("strong").textContent = "Arrastra tus vídeos aquí";
}

async function subirCancion(archivo) {
  if (!archivo) return;
  const fd = new FormData();
  fd.append("archivo", archivo);
  $("textoCancion").textContent = "Subiendo…";
  try {
    P = await api(`/api/proyectos/${P.id}/cancion`, { method: "POST", body: fd });
    pintarTodo();
    if (P.plan) aviso("Canción cambiada. Pulsa «Volver a crear» para montarlo con ella.", true);
  } catch (e) { aviso(e.message); }
  $("textoCancion").textContent = "Añadir canción (mp3, wav, m4a…)";
}

function prepararZona(zona, input, alSoltar) {
  input.onchange = () => { alSoltar([...input.files]); input.value = ""; };
  zona.ondragover = (e) => { e.preventDefault(); zona.classList.add("encima"); };
  zona.ondragleave = () => zona.classList.remove("encima");
  zona.ondrop = (e) => { e.preventDefault(); zona.classList.remove("encima"); alSoltar([...e.dataTransfer.files]); };
}

// ===================================================== guardado de campos
const camposPendientes = {};
const guardarCampos = debounce(() => guardarCamposPendientes(), 500);
async function guardarCamposPendientes() {
  if (!P || !Object.keys(camposPendientes).length) return;
  const datos = { ...camposPendientes };
  Object.keys(camposPendientes).forEach((k) => delete camposPendientes[k]);
  P = { ...P, ...(await api(`/api/proyectos/${P.id}`, { method: "PUT", json: datos })) };
}
function campo(id, clave, conv = (v) => v) {
  $(id).addEventListener("input", () => { camposPendientes[clave] = conv($(id).value); guardarCampos(); });
}

// ===================================================== eventos
function enlazar() {
  $("irInicio").onclick = mostrarInicio;
  $("btnNuevo").onclick = async () => {
    const nombre = prompt("Nombre del vídeo", "Mi vídeo");
    if (nombre === null) return;
    const p = await api("/api/proyectos", { method: "POST", json: { nombre } });
    abrir(p.id);
  };
  $("nombreProyecto").onchange = (e) => { camposPendientes.nombre = e.target.value; guardarCampos(); };
  campo("letra", "letra");
  campo("peticion", "peticion");
  campo("duracion", "duracion", (v) => +v || 0);
  $("idioma").onchange = (e) => { camposPendientes.idioma = e.target.value; guardarCampos(); };
  $("modeloVoz").onchange = (e) => { camposPendientes.modelo_voz = e.target.value; guardarCampos(); };

  prepararZona($("zonaClips"), $("inputClips"), (f) => subirClips(f.filter((x) => x.type.startsWith("video") || /\.(mp4|mov|mkv|webm|avi|m4v)$/i.test(x.name))));
  prepararZona($("zonaCancion"), $("inputCancion"), (f) => subirCancion(f[0]));
  $("btnQuitarCancion").onclick = async () => { P = await api(`/api/proyectos/${P.id}/cancion`, { method: "DELETE" }); pintarTodo(); };

  $("btnCrear").onclick = () => {
    if (P.plan && !confirm("Se rehará el montaje y los subtítulos desde cero. ¿Seguir?")) return;
    crearVideo();
  };
  $("btnPreview").onclick = vistaPrevia;
  $("btnExportar").onclick = exportar;
  $("btnCambio").onclick = pedirCambio;
  $("inputCambio").onkeydown = (e) => { if (e.key === "Enter") pedirCambio(); };
  $("btnRemontar").onclick = () => remontar();
  $("btnBarajar").onclick = () => remontar({ semilla: Math.floor(Math.random() * 1e6) });

  $("eFuente").onchange = (e) => cambiarEstilo({ fuente: e.target.value });
  $("eTamano").oninput = (e) => cambiarEstilo({ tamano: +e.target.value });
  $("ePosicion").onchange = (e) => cambiarEstilo({ posicion: e.target.value });
  $("eAnimacion").onchange = (e) => cambiarEstilo({ animacion: e.target.value });
  $("eColor").oninput = (e) => cambiarEstilo({ color: e.target.value });
  $("eResaltado").oninput = (e) => cambiarEstilo({ resaltado: e.target.value });
  $("eBordeColor").oninput = (e) => cambiarEstilo({ borde_color: e.target.value });
  $("eBorde").oninput = (e) => cambiarEstilo({ borde: +e.target.value });
  $("ePalabras").onchange = (e) => cambiarEstilo({ palabras_por_bloque: +e.target.value });
  $("eMayus").onchange = (e) => cambiarEstilo({ mayusculas: e.target.checked });
  $("subsActivos").onchange = async (e) => {
    if (!P.plan) return;
    P = await api(`/api/proyectos/${P.id}`, { method: "PUT", json: { plan: { subtitulos: e.target.checked } } });
  };

  $("btnAnadirLinea").onclick = () => {
    if (!P.plan) return;
    const t = $("video").currentTime || (P.subtitulos.length ? P.subtitulos[P.subtitulos.length - 1].fin : 0);
    P.subtitulos.push({ inicio: +t.toFixed(2), fin: +(t + 1.5).toFixed(2), texto: "Texto nuevo" });
    P.subtitulos.sort((a, b) => a.inicio - b.inicio);
    pintarSubs(); guardarSubs();
  };
  $("btnRegenerar").onclick = () => {
    if (!confirm("Se volverán a transcribir los subtítulos y perderás tus cambios en el texto. ¿Seguir?")) return;
    ejecutar(`/api/proyectos/${P.id}/subtitulos/regenerar`, {}, async () => {
      P = await api(`/api/proyectos/${P.id}`);
      pintarSubs();
      aviso("Subtítulos regenerados. Actualiza la vista previa.", true);
    });
  };
  $("video").ontimeupdate = marcarLineaActual;

  $("btnAjustes").onclick = () => { $("modeloIA").value = ESTADO.modelo_ia || ""; $("apiKey").value = ""; $("dlgAjustes").showModal(); };
  $("btnGuardarAjustes").onclick = async (e) => {
    e.preventDefault();
    const datos = { CLAUDE_MODEL: $("modeloIA").value.trim() };
    const k = $("apiKey").value.trim();
    if (k) datos.ANTHROPIC_API_KEY = k;
    ESTADO = await api("/api/ajustes", { method: "POST", json: datos });
    $("dlgAjustes").close();
    await cargarEstado();
    if (P) actualizarBotones();
    aviso(ESTADO.ia ? "API key guardada. La IA ya está activa." : "Guardado.", true);
  };
}

(async () => {
  enlazar();
  await cargarEstado();
  const id = new URLSearchParams(location.search).get("p");
  if (id) { try { await abrir(id); return; } catch { /* proyecto borrado */ } }
  mostrarInicio();
})();
