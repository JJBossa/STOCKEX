import assert from "node:assert/strict";
import {spawn, spawnSync} from "node:child_process";
import {createWriteStream, existsSync} from "node:fs";
import {mkdtemp, readFile, rm} from "node:fs/promises";
import {createRequire} from "node:module";
import {createServer} from "node:net";
import {tmpdir} from "node:os";
import {join} from "node:path";
import {fileURLToPath} from "node:url";
import {setTimeout as esperar} from "node:timers/promises";

const raiz = fileURLToPath(new URL("../../", import.meta.url));
const require = createRequire(import.meta.url);
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const python = process.env.PYTHON || (existsSync(join(raiz, "venv/bin/python")) ? join(raiz, "venv/bin/python") : "python");
const temporal = await mkdtemp(join(tmpdir(), "stockex-caja-browser-"));
const env = {...process.env, DEBUG: "True", ALLOWED_HOSTS: "127.0.0.1",
    DATABASE_URL: "sqlite:///" + join(temporal, "caja.sqlite3")};
const admin = "pos-administrador", vendedor = "pos-vendedor-a";
const claveCaja = "stockex.caja.pendiente.v1.";
const rutaAbrir = "**/caja/abrir/";
const rutaMov = "**/caja/*/movimientos/";
const rutaCerrar = "**/caja/*/cerrar/";
const rutaVenta = "**/pos/registrar-venta/";
let navegador, django, origen;
const errores = [];

async function prueba(nombre, fn) {
    await fn();
    console.log("OK " + nombre);
}

async function iniciarDjango() {
    for (const args of [
        ["migrate", "--noinput", "--verbosity", "0"],
        ["shell", "-c", "from tests.browser.punto_venta_django import preparar_datos; preparar_datos(con_caja=False)"],
    ]) {
        const proceso = spawnSync(python, ["manage.py", ...args], {cwd: raiz, env, encoding: "utf8"});
        assert.equal(proceso.status, 0, proceso.stderr);
    }
    const puerto = createServer();
    await new Promise(resolve => puerto.listen(0, "127.0.0.1", resolve));
    const direccion = "127.0.0.1:" + puerto.address().port;
    await new Promise(resolve => puerto.close(resolve));
    origen = "http://" + direccion;
    django = spawn(python, ["manage.py", "runserver", "--noreload", direccion], {cwd: raiz, env});
    const log = createWriteStream(join(temporal, "django.log"));
    django.stdout.pipe(log, {end: false});
    django.stderr.pipe(log);
    for (let i = 0; i < 80; i++) {
        if (await fetch(origen + "/login/").then(r => r.ok).catch(() => false)) return;
        await esperar(100);
    }
    throw new Error("Django no inició.");
}

async function contexto(opciones = {}) {
    const context = await navegador.newContext({
        viewport: {width: 1366, height: 900}, locale: "es-CL", ignoreHTTPSErrors: true, ...opciones,
    });
    context.setDefaultTimeout(10_000);
    if (process.env.POS_CDN_LOCAL) {
        await context.route("https://cdn.jsdelivr.net/**", route => {
            const archivo = new URL(route.request().url()).pathname.split("/").at(-1);
            const path = join(process.env.POS_CDN_LOCAL, archivo);
            if (!existsSync(path)) return route.abort();
            const contentType = archivo.endsWith(".css") ? "text/css"
                : archivo.endsWith(".js") ? "application/javascript" : "font/woff2";
            return route.fulfill({path, contentType, headers: {"Access-Control-Allow-Origin": "*"}});
        });
    }
    context.on("page", page => page.on("pageerror", error => errores.push(String(error))));
    return context;
}

async function entrar(page, cuenta, ruta, javaScriptEnabled = true) {
    await page.context().clearCookies({name: "sessionid"});
    await page.goto(origen + "/login/");
    if (!javaScriptEnabled) {
        const csrfmiddlewaretoken = await page.locator('#main-content input[name="csrfmiddlewaretoken"]').getAttribute("value");
        const login = await page.request.post(origen + "/login/", {
            form: {username: cuenta, password: "Prueba-local-STK04B!", csrfmiddlewaretoken}, maxRedirects: 0,
        });
        assert.equal(login.status(), 302);
        return page.goto(origen + ruta);
    }
    await page.locator("#id_username").fill(cuenta);
    await page.locator("#id_password").fill("Prueba-local-STK04B!");
    await Promise.all([
        page.waitForURL(url => url.pathname === "/"),
        page.locator('form button[type="submit"]').click(),
    ]);
    return page.goto(origen + ruta);
}

const el = (page, id) => page.locator("#caja-" + id);
const btn = (page, name) => page.getByRole("button", {name, exact: true});
const texto = (loc, valor) => loc.getByText(valor, {exact: typeof valor === "string"}).waitFor();
const postUI = (page, patron, disparar) => Promise.all([
    page.waitForResponse(response => response.url().match(patron) && response.request().method() === "POST"),
    disparar(),
]).then(([response]) => response);

async function esperarEstado(page, abierto) {
    await texto(el(page, "resumen"), abierto ? /Caja abierta/ : "Caja cerrada");
}

const envio = request => ({clave: request.headers()["idempotency-key"], cuerpo: request.postData()});
function observar(page, patron) {
    const envios = [];
    page.on("request", request => {
        if (request.method() === "POST" && request.url().match(patron)) envios.push(envio(request));
    });
    return envios;
}

async function perderTrasGuardar(page, ruta) {
    await page.route(ruta, async route => {
        const respuesta = await route.fetch();
        assert.equal(respuesta.status(), 201, await respuesta.text());
        await route.abort("failed");
    }, {times: 1});
}

async function csrf(page) {
    return page.locator('meta[name="csrf-token"]').getAttribute("content");
}

async function escribir(page, ruta, data) {
    return page.request.post(origen + ruta, {
        data, headers: {"X-CSRFToken": await csrf(page), "Idempotency-Key": crypto.randomUUID()},
    });
}

async function revisar(page, importe, observaciones = "") {
    await el(page, "contado").fill(String(importe));
    await el(page, "observaciones-cierre").fill(observaciones);
    await btn(page, "Revisar cierre").click();
}

async function verificarAnchos(page, guardar) {
    for (const oscuro of [false, true]) {
        if (oscuro) {
            const antes = await page.locator("[data-gestion-caja] .card:visible").first()
                .evaluate(card => getComputedStyle(card).backgroundColor);
            await page.locator("#dark-mode-toggle").click();
            await page.waitForFunction(({color}) => [...document.querySelectorAll("[data-gestion-caja] .card")]
                .find(card => card.getClientRects().length)
                && getComputedStyle([...document.querySelectorAll("[data-gestion-caja] .card")]
                    .find(card => card.getClientRects().length)).backgroundColor !== color, {color: antes});
            await page.waitForFunction(() => {
                const fondo = getComputedStyle(document.querySelector("#caja-resumen tbody td")).backgroundColor;
                return Math.max(...fondo.match(/\d+/g).slice(0, 3).map(Number)) < 100;
            });
        }
        for (const width of [390, 768, 1366, 1920]) {
            await page.setViewportSize({width, height: 940});
            const fuera = await page.locator("[data-gestion-caja]").evaluate(raiz => {
                if (document.documentElement.scrollWidth > innerWidth) return true;
                return [...raiz.querySelectorAll("input, textarea, button, a")].some(el => {
                    const r = el.getBoundingClientRect();
                    return el.getClientRects().length && (r.left < 0 || r.right > innerWidth + 1);
                });
            });
            assert.equal(fuera, false, `${width}px · oscuro=${oscuro}`);
            if (guardar && (width === 390 || width === 1366)) {
                await page.screenshot({path: join(guardar, `caja-${width}-${oscuro}.png`), fullPage: true});
            }
        }
    }
    await page.locator("#dark-mode-toggle").click();
}

try {
    await iniciarDjango();
    navegador = await chromium.launch({executablePath: process.env.CHROMIUM_PATH, args: ["--no-sandbox"]});
    console.log(`Chromium ${navegador.version()} · Django real · SQLite temporal`);
    const gestion = await (await contexto()).newPage();
    const otraCaja = await (await contexto()).newPage();
    const pos = await (await contexto()).newPage();
    await entrar(gestion, admin, "/caja/");
    await entrar(otraCaja, admin, "/caja/");
    await entrar(pos, vendedor, "/pos/");
    const cuenta = await gestion.locator("[data-gestion-caja]").getAttribute("data-cuenta");
    const apertura = observar(gestion, /\/caja\/abrir\/$/);
    const movimientos = observar(gestion, /\/caja\/\d+\/movimientos\/$/);
    const cierres = observar(gestion, /\/caja\/\d+\/cerrar\/$/);
    const ventas = observar(pos, /\/pos\/registrar-venta\/$/);
    const pendiente = operacion => gestion.evaluate(key => JSON.parse(sessionStorage.getItem(key)),
        claveCaja + cuenta + "." + operacion);

    await prueba("apertura cero, doble clic, respuesta perdida, recarga y aislamiento por cuenta", async () => {
        await esperarEstado(gestion, false);
        assert.equal(await pos.locator("#pos-registrar").isDisabled(), true);
        assert.equal(await pos.getByRole("link", {name: "Ir a apertura"}).count(), 0);
        assert.equal(await pos.request.get(origen + "/pos/estado-caja/").then(r => r.json()).then(r => r.abierta), false);
        assert.equal((await pos.request.get(origen + "/caja/")).status(), 403);
        for (const importe of ["-1", "1,5", "1000000000000"]) {
            await el(gestion, "inicial").fill(importe);
            await btn(gestion, "Abrir caja").click();
            assert.equal(await el(gestion, "inicial").evaluate(input => input.validity.valid), false);
        }
        assert.equal(apertura.length, 0);
        await perderTrasGuardar(gestion, rutaAbrir);
        await el(gestion, "inicial").fill("0");
        await btn(gestion, "Abrir caja").evaluate(boton => { boton.click(); boton.click(); });
        await texto(el(gestion, "error"), /Resultado sin confirmar/);
        const intento = await pendiente("apertura");
        assert.equal(apertura.length, 1);
        assert.deepEqual(apertura[0], {clave: intento.clave, cuerpo: intento.cuerpo});
        await gestion.reload();
        await btn(gestion, "Reintentar").waitFor();
        assert.equal(apertura.length, 1);
        assert.equal((await entrar(gestion, "pos-administrador-b", "/caja/")).status(), 200);
        await esperarEstado(gestion, true);
        assert.equal(await btn(gestion, "Reintentar").count(), 0);
        assert.deepEqual(await pendiente("apertura"), intento);
        await entrar(gestion, admin, "/caja/");
        await btn(gestion, "Reintentar").waitFor();

        await otraCaja.reload();
        await revisar(otraCaja, 0);
        await btn(otraCaja, "Confirmar cierre").click();
        await otraCaja.waitForURL(/\/caja\/historial\/\d+\/$/);
        await texto(otraCaja.locator("main"), "Caja cuadrada");

        const repetida = await postUI(gestion, /\/caja\/abrir\/$/, () => btn(gestion, "Reintentar").click());
        assert.equal(repetida.status(), 200);
        assert.deepEqual(apertura[1], apertura[0]);
        await esperarEstado(gestion, false);
        assert.equal(await pendiente("apertura"), null);
        assert.equal(await btn(gestion, "Abrir caja").isEnabled(), true);
        await el(gestion, "inicial").fill("1.000");
        await btn(gestion, "Abrir caja").click();
        await esperarEstado(gestion, true);
        await texto(el(gestion, "mensaje"), /Apertura confirmada/);
        await gestion.getByRole("link", {name: "Ir al punto de venta"}).waitFor();
    });

    await prueba("ingreso con 503, retiro confirmado con respuesta perdida y texto escapado", async () => {
        await el(gestion, "importe").fill("200");
        await el(gestion, "motivo").fill("Fondo extra");
        await gestion.route(rutaMov, route => route.fulfill({status: 503, json: {error: "base_ocupada"}}), {times: 1});
        await btn(gestion, "Registrar movimiento").click();
        await btn(gestion, "Reintentar").waitFor();
        assert.equal(await btn(gestion, "Registrar movimiento").isDisabled(), true);
        await btn(gestion, "Reintentar").click();
        await texto(el(gestion, "mensaje"), "Ingreso confirmado.");
        assert.deepEqual(movimientos[1], movimientos[0]);
        await texto(el(gestion, "resumen"), /Ingresos adicionales \(1\)/);
        await el(gestion, "tipo").selectOption("retiro");
        await el(gestion, "importe").fill("50");
        await el(gestion, "motivo").fill("<b data-prueba-caja>Retiro</b>");
        await perderTrasGuardar(gestion, rutaMov);
        await btn(gestion, "Registrar movimiento").click();
        await texto(el(gestion, "error"), /Resultado sin confirmar/);
        await gestion.reload();
        await btn(gestion, "Reintentar").click();
        await texto(el(gestion, "mensaje"), /Retiro confirmado.*recuperado/);
        assert.deepEqual(movimientos[3], movimientos[2]);
        await gestion.getByRole("link", {name: "Ver movimientos"}).click();
        await texto(gestion.locator("main"), "<b data-prueba-caja>Retiro</b>");
        assert.equal(await gestion.locator("[data-prueba-caja]").count(), 0);
        await gestion.getByRole("link", {name: "Caja actual"}).click();
        await esperarEstado(gestion, true);
    });

    const posAntesDeCerrar = await pos.context().newPage();
    await prueba("POS refresca con un GET mínimo, sin consultas de caja durante la edición", async () => {
        const consultas = [];
        pos.on("request", request => {
            if (request.url().endsWith("/pos/estado-caja/")) consultas.push(request.method());
        });
        const consulta = pos.waitForResponse(r => r.url().endsWith("/pos/estado-caja/"));
        await pos.locator("#pos-actualizar-caja").click();
        assert.deepEqual(await (await consulta).json(), {abierta: true});
        const detallada = pos.locator('label[for="pos-modo-detallada"]');
        await detallada.click();
        await pos.getByText(/^Catálogo listo ·/).waitFor();
        await pos.locator("[data-consulta]").fill("000019");
        await pos.getByRole("option").filter({hasText: "Agua con gas"}).click();
        await pos.locator("[data-cantidad]").fill("2");
        assert.deepEqual(consultas, ["GET"]);
        await pos.locator('label[for="pos-modo-rapida"]').click();
        await pos.locator("#pos-monto").fill("1000");
        await perderTrasGuardar(pos, rutaVenta);
        await pos.locator("#pos-registrar").click();
        await texto(pos.locator("#pos-error"), /No se pudo verificar/);
        await posAntesDeCerrar.goto(origen + "/pos/");
        assert.equal(await posAntesDeCerrar.locator("#pos-registrar").isEnabled(), true);
    });

    await prueba("cierre explícito, reconfirmación con nueva huella y recuperación tras cerrar", async () => {
        await el(gestion, "actualizar").click();
        await texto(el(gestion, "resumen"), "$2.150");
        await verificarAnchos(gestion, process.env.CAJA_CAPTURAS);
        await revisar(gestion, 2151);
        assert.equal(await el(gestion, "observaciones-cierre").evaluate(c => c.validity.valueMissing), true);
        assert.equal(await gestion.getByRole("dialog").isVisible(), false);
        await texto(el(gestion, "diferencia").locator(".."), /Sobrante/);
        await revisar(gestion, 2150, "Conteo de turno");
        await gestion.getByRole("dialog", {name: "Confirmar cierre"}).waitFor();
        assert.equal(await gestion.locator(":focus").getAttribute("id"), "caja-volver");
        assert.equal(cierres.length, 0);
        await gestion.keyboard.press("Escape");
        await gestion.getByRole("dialog").waitFor({state: "hidden"});
        await btn(gestion, "Revisar cierre").click();
        await otraCaja.goto(origen + "/caja/");
        const {sesion} = await otraCaja.request.get(origen + "/caja/activa/").then(r => r.json());
        assert.equal((await escribir(otraCaja, `/caja/${sesion.id}/movimientos/`, {
            tipo: "ingreso", importe: 100, motivo: "Cambio durante la conciliación",
        })).status(), 201);
        const rechazo = await postUI(gestion, /\/caja\/\d+\/cerrar\/$/, () => btn(gestion, "Confirmar cierre").click());
        assert.equal(rechazo.status(), 409);
        assert.equal((await rechazo.json()).error, "resumen_cambiado");
        await texto(el(gestion, "cambios"), /Efectivo esperado pasó de .* a /);
        await texto(el(gestion, "diferencia").locator(".."), /Faltante/);
        assert.equal(await el(gestion, "contado").inputValue(), "2150");
        assert.equal(await el(gestion, "observaciones-cierre").inputValue(), "Conteo de turno");
        assert.equal(cierres.length, 1);
        assert.equal(await gestion.getByRole("dialog").isVisible(), false);
        await btn(gestion, "Revisar cierre").click();
        await perderTrasGuardar(gestion, rutaCerrar);
        await btn(gestion, "Confirmar cierre").click();
        await texto(el(gestion, "error"), /Resultado sin confirmar/);
        assert.notEqual(JSON.parse(cierres[0].cuerpo).huella, JSON.parse(cierres[1].cuerpo).huella);
        await gestion.reload();
        await esperarEstado(gestion, false);
        await btn(gestion, "Reintentar").click();
        await gestion.waitForURL(/\/caja\/historial\/\d+\/$/);
        await texto(gestion.locator("main"), "Faltante");
        assert.deepEqual(cierres[2], cierres[1]);
        assert.equal(await pendiente("cierre"), null);
        await gestion.getByRole("link", {name: "Ver movimientos"}).click();
        await texto(gestion.locator("main"), "Cambio durante la conciliación");
    });

    await prueba("venta pendiente recuperable con caja cerrada y venta nueva rechazada conserva el borrador", async () => {
        await pos.reload();
        await texto(pos.locator("main"), "Caja cerrada");
        await pos.getByRole("button", {name: "Reintentar registro"}).click();
        await texto(pos.locator("#pos-estado").locator(".."), /Venta recuperada/);
        assert.deepEqual(ventas[1], ventas[0]);
        await posAntesDeCerrar.locator("#pos-monto").fill("620");
        const r = await postUI(posAntesDeCerrar, /\/pos\/registrar-venta\/$/, () => posAntesDeCerrar.locator("#pos-registrar").click());
        assert.equal(r.status(), 409);
        assert.equal((await r.json()).error, "caja_no_abierta");
        await texto(posAntesDeCerrar.locator("main"), "Caja cerrada");
        assert.equal(await posAntesDeCerrar.locator("#pos-monto").inputValue(), "620");
        assert.equal(await posAntesDeCerrar.locator("#pos-registrar").isDisabled(), true);
        assert.equal(await posAntesDeCerrar.evaluate(() =>
            Object.keys(sessionStorage).some(k => k.startsWith("stockex.pos.pendiente."))), false);
    });

    await prueba("respuesta incompleta, CSRF y sesión vencida mantienen el intento exacto", async () => {
        await gestion.goto(origen + "/caja/");
        await el(gestion, "inicial").fill("300");
        await btn(gestion, "Abrir caja").click();
        await esperarEstado(gestion, true);
        await el(gestion, "importe").fill("30");
        await el(gestion, "motivo").fill("Validación de sesión");
        await gestion.route(rutaMov, route => route.fulfill({status: 200, json: {id: 2}}), {times: 1});
        await btn(gestion, "Registrar movimiento").click();
        await texto(el(gestion, "error"), /Resultado sin confirmar/);
        const original = await pendiente("ingreso");
        await gestion.route(rutaMov, route => route.continue({
            headers: {...route.request().headers(), "x-csrftoken": "invalido"},
        }), {times: 1});
        const csrfRechazado = await postUI(gestion, /\/caja\/\d+\/movimientos\/$/, () => btn(gestion, "Reintentar").click());
        assert.equal(csrfRechazado.status(), 403);
        await texto(el(gestion, "error"), /misma cuenta/);
        await gestion.context().clearCookies({name: "sessionid"});
        await btn(gestion, "Reintentar").click();
        await texto(el(gestion, "error"), /misma cuenta/);
        assert.deepEqual(await pendiente("ingreso"), original);
        await entrar(gestion, admin, "/caja/");
        await btn(gestion, "Reintentar").click();
        await texto(el(gestion, "mensaje"), "Ingreso confirmado.");
        assert.deepEqual(movimientos.slice(-4), Array(4).fill({clave: original.clave, cuerpo: original.cuerpo}));
    });

    await prueba("cierre sobrante y consultas nativas sin JavaScript", async () => {
        await revisar(gestion, 340, "Sobrante contado");
        await btn(gestion, "Confirmar cierre").click();
        await gestion.waitForURL(/\/caja\/historial\/\d+\/$/);
        await texto(gestion.locator("main"), "Sobrante");
        const sinJs = await (await contexto({javaScriptEnabled: false})).newPage();
        await entrar(sinJs, admin, "/caja/", false);
        assert.equal(await btn(sinJs, "Abrir caja").isDisabled(), true);
        await texto(sinJs.locator("main"), /Habilita JavaScript/);
        await sinJs.getByRole("link", {name: "Historial de cierres"}).press("Enter");
        await sinJs.waitForURL(/\/caja\/historial\/$/);
        const clasificacion = sinJs.getByLabel("Clasificación");
        await clasificacion.press("Home");
        await clasificacion.press("ArrowDown");
        await clasificacion.press("ArrowDown");
        assert.equal(await clasificacion.inputValue(), "faltante");
        await btn(sinJs, "Filtrar").press("Enter");
        await sinJs.waitForURL(/clasificacion=faltante/);
        assert.equal(await sinJs.locator("tbody tr").count(), 1);
        await sinJs.locator("tbody a").press("Enter");
        await sinJs.waitForURL(/\/caja\/historial\/\d+\/$/);
        await texto(sinJs.locator("main"), "Faltante");
        await sinJs.getByRole("link", {name: "Ver movimientos"}).press("Enter");
        await sinJs.waitForURL(/\/caja\/\d+\/movimientos\/listado\/$/);
        await texto(sinJs.locator("main"), "Cambio durante la conciliación");
    });

    await prueba("conflicto de clave exige conciliación y la diferencia conserva el entero exacto", async () => {
        await gestion.goto(origen + "/caja/");
        await el(gestion, "inicial").fill("0");
        await btn(gestion, "Abrir caja").click();
        await esperarEstado(gestion, true);
        await el(gestion, "tipo").selectOption("retiro");
        await el(gestion, "importe").fill("2");
        await el(gestion, "motivo").fill("Revisión de efectivo");
        await gestion.route(rutaMov, async route => {
            const datos = {...route.request().postDataJSON(), importe: 1};
            assert.equal((await route.fetch({postData: JSON.stringify(datos)})).status(), 201);
            await route.continue();
        }, {times: 1});
        await btn(gestion, "Registrar movimiento").click();
        await texto(el(gestion, "pendientes"), /Clave en conflicto/);
        assert.equal(await btn(gestion, "Reintentar").count(), 0);
        assert.equal((await pendiente("retiro")).conflicto, true);
        await gestion.reload();
        await texto(el(gestion, "pendientes"), /Clave en conflicto/);
        gestion.once("dialog", dialogo => dialogo.accept());
        await btn(gestion, "Resolver tras revisar").click();
        await el(gestion, "pendientes").waitFor({state: "hidden"});
        assert.equal(await pendiente("retiro"), null);
        await el(gestion, "contado").fill("9007199254740991");
        await texto(el(gestion, "diferencia").locator(".."), /9\.007\.199\.254\.740\.992/);
    });

    await prueba("un abono aparece en Caja y obliga a reconfirmar sin duplicar la venta fiada", async () => {
        const respuesta = await gestion.request.get(origen + "/fiados/clientes/?q=sintético");
        const {clientes: [deudor]} = await respuesta.json();
        const venta = await escribir(gestion, "/pos/registrar-venta/", {
            modalidad: "rapida", metodo_pago: "credito", monto: 500, cliente_id: deudor.id,
        });
        assert.equal(venta.status(), 201);
        const {cuenta_id: deuda} = await venta.json();
        await el(gestion, "actualizar").click();
        await texto(el(gestion, "resumen"), /Fiados \$500/);
        await revisar(gestion, 119, "Conteo verificado");
        const abono = await escribir(gestion, `/fiados/cuentas/${deuda}/abonar/`, {
            importe: 120, metodo_pago: "efectivo",
        });
        assert.equal(abono.status(), 201);
        const rechazo = await postUI(gestion, /\/caja\/\d+\/cerrar\/$/, () => btn(gestion, "Confirmar cierre").click());
        assert.equal((await rechazo.json()).error, "resumen_cambiado");
        await texto(el(gestion, "cambios"), /Abonos recibidos pasó de \$0 a \$120/);
        await texto(el(gestion, "diferencia").locator(".."), /Caja cuadrada/);
        await btn(gestion, "Revisar cierre").click();
        await btn(gestion, "Confirmar cierre").click();
        await gestion.waitForURL(/\/caja\/historial\/\d+\/$/);
        await texto(gestion.locator("main"), /Abonos \$120/);
        await texto(gestion.locator("main"), "1 venta vigente");
    });

    const rutaAbono = "**/fiados/cuentas/*/abonar/";
    const abonos = observar(otraCaja, /\/fiados\/cuentas\/\d+\/abonar\/$/);
    const fiadosPos = observar(gestion, /\/pos\/registrar-venta\/$/);
    const posCampo = nombre => gestion.locator("#pos-" + nombre);
    const elegirFiado = () => gestion.locator('label[for="pos-credito"]').click();
    let idCuenta, idCliente, rutaCuenta;

    async function cambiarCliente(page, activo) {
        const url = origen + `/clientes/${idCliente}/editar/`;
        const respuesta = await page.request.post(url, {
            form: {nombre: "Cliente <em>Alta fiado</em>", limite_credito: "1200", activo: activo ? "on" : ""},
            headers: {"X-CSRFToken": await csrf(page)}, maxRedirects: 0,
        });
        assert.equal(respuesta.status(), 302);
    }

    async function abrirParaFiados() {
        await gestion.goto(origen + "/caja/");
        await el(gestion, "inicial").fill("0");
        await btn(gestion, "Abrir caja").click();
        await esperarEstado(gestion, true);
        await gestion.goto(origen + "/pos/");
        await elegirFiado();
    }

    await prueba("fiado rápido con clientes homónimos, búsqueda fuera de orden y alta que conserva el borrador", async () => {
        await pos.goto(origen + "/pos/");
        assert.equal(await pos.locator("#pos-credito").count(), 0);
        await abrirParaFiados();
        await posCampo("monto").fill("1000");
        const modoFiado = gestion.locator('label[for="pos-credito"]');
        await gestion.locator('label[for="pos-efectivo"]').click();
        await modoFiado.click();
        const consulta = posCampo("cliente-buscar");
        let soltarVieja, terminoVieja;
        const vieja = new Promise(resolve => { soltarVieja = resolve; });
        const viejaTerminada = new Promise(resolve => { terminoVieja = resolve; });
        await gestion.route("**/fiados/clientes/?q=anterior", async route => {
            await vieja;
            await route.fulfill({json: {clientes: [{id: 901, nombre: "Resultado anterior", rut: null}]}}).catch(() => {});
            terminoVieja();
        }, {times: 1});
        const emitida = gestion.waitForRequest(r => r.url().endsWith("?q=anterior"));
        await consulta.fill("anterior");
        await emitida;
        await consulta.fill("Coincidente");
        const opciones = gestion.getByRole("option");
        await opciones.first().waitFor();
        assert.equal(await opciones.count(), 2);
        soltarVieja();
        await viejaTerminada;
        assert.equal(await gestion.getByText("Resultado anterior").count(), 0);
        assert.equal(await opciones.count(), 2);
        assert.equal(await gestion.locator("#pos-clientes em").count(), 0);
        await consulta.press("ArrowDown");
        await consulta.press("ArrowDown");
        const segunda = await opciones.nth(1).textContent();
        await consulta.press("Enter");
        assert.equal(await posCampo("cliente-nombre").textContent(), segunda);
        await btn(gestion, "Quitar cliente").click();
        await btn(gestion, "Crear cliente").click();
        await gestion.locator("#alta-nombre").fill("Cliente <em>Alta fiado</em>");
        await gestion.locator("#alta-limite").fill("1200");
        const altas = observar(gestion, /\/clientes\/crear\/$/);
        const respuesta = await postUI(gestion, /\/clientes\/crear\/$/, () =>
            btn(gestion, "Crear y seleccionar").evaluate(boton => { boton.click(); boton.click(); }));
        assert.equal(respuesta.status(), 201);
        idCliente = (await respuesta.json()).id;
        await texto(posCampo("cliente-nombre").locator(".."), /Alta fiado.*#/);
        assert.equal(altas.length, 1);
        assert.equal(await posCampo("monto").inputValue(), "1.000");
        assert.equal(await posCampo("caja").isVisible(), false);
        assert.equal(await posCampo("cliente-nombre").locator("em").count(), 0);

        await posCampo("fiado-vencimiento").fill("2024-01-01");
        await posCampo("fiado-notas").fill("Vale del turno");
        await posCampo("registrar").click();
        const dialogo = gestion.getByRole("dialog", {name: "Confirmar fiado"});
        await texto(dialogo, /Saldo proyectado \$1\.000/);
        await texto(dialogo, "No se recibe dinero en esta operación.");
        assert.equal(fiadosPos.length, 0);
        await gestion.route(rutaVenta, async route => {
            const registrada = await route.fetch();
            idCuenta = (await registrada.json()).cuenta_id;
            assert.equal(registrada.status(), 201);
            await route.abort("failed");
        }, {times: 1});
        await btn(gestion, "Confirmar fiado").click();
        await texto(posCampo("error"), /No se pudo verificar/);
        assert.equal(JSON.parse(fiadosPos[0].cuerpo).cliente_id, idCliente);
        rutaCuenta = `/fiados/gestion/cuentas/${idCuenta}/`;
    });

    await prueba("abono parcial y pago total sobre deuda vencida, con borrador y respuesta recuperable", async () => {
        await otraCaja.goto(origen + rutaCuenta);
        assert.match(await otraCaja.locator("#fiados-datos").innerText(), /Pendiente\s*·\s*Vencida/);
        await cambiarCliente(otraCaja, false);
        const inactivo = await otraCaja.request.get(origen + "/fiados/clientes/?q=Alta%20fiado");
        assert.deepEqual((await inactivo.json()).clientes, []);
        await otraCaja.locator("#abono-importe").fill("1001");
        await btn(otraCaja, "Revisar abono").click();
        await texto(otraCaja.locator("#abono-error"), /dentro del saldo pendiente/);
        assert.equal(abonos.length, 0);
        await otraCaja.locator("#abono-importe").fill("350");
        await otraCaja.locator("#abono-referencia").fill("<img src=x>");
        await otraCaja.locator("#abono-observaciones").fill("<script>x</script>");
        await btn(otraCaja, "Revisar abono").click();
        await texto(otraCaja.getByRole("dialog"), /Saldo proyectado \$650/);
        await btn(otraCaja, "Confirmar abono").evaluate(boton => { boton.click(); boton.click(); });
        await texto(otraCaja.locator("#abono-estado"), "Abono confirmado.");
        await texto(otraCaja.locator("#fiados-pagos"), "<img src=x>");
        assert.equal(abonos.length, 1);
        assert.equal(await otraCaja.locator("#fiados-pagos img, #fiados-pagos script").count(), 0);
        await btn(otraCaja, "Pagar saldo completo").click();
        assert.equal(await otraCaja.locator("#abono-importe").inputValue(), "650");
        assert.equal(abonos.length, 1);
        await otraCaja.locator("#abono-metodo").selectOption("transferencia");
        await btn(otraCaja, "Revisar abono").click();
        await perderTrasGuardar(otraCaja, rutaAbono);
        await btn(otraCaja, "Confirmar abono").click();
        await texto(otraCaja.locator("#abono-error"), /Abono sin confirmar/);
        assert.equal(abonos.length, 2);
        await entrar(otraCaja, "pos-administrador-b", rutaCuenta);
        assert.equal(await btn(otraCaja, "Reintentar abono pendiente").isVisible(), false);
        await entrar(otraCaja, admin, rutaCuenta);

        const controlCaja = await (await contexto()).newPage();
        await entrar(controlCaja, admin, "/caja/");
        await texto(el(controlCaja, "resumen"), /Abonos \$1\.000/);
        await texto(el(controlCaja, "resumen"), "1 venta vigente");
        await revisar(controlCaja, 350);
        await btn(controlCaja, "Confirmar cierre").click();
        await controlCaja.waitForURL(/\/caja\/historial\/\d+\/$/);
        await texto(controlCaja.locator("main"), "Caja cuadrada");
        await otraCaja.reload();
        await texto(otraCaja.locator("#fiados-datos"), /Caja cerrada/);
        await btn(otraCaja, "Reintentar abono pendiente").click();
        await texto(otraCaja.locator("#abono-estado"), /Abono recuperado/);
        assert.deepEqual(abonos[2], abonos[1]);
        assert.equal(await btn(otraCaja, "Revisar abono").isDisabled(), true);
        await gestion.reload();
        await texto(gestion.locator("#pos-estado-caja"), "Caja cerrada");
        await btn(gestion, "Reintentar registro").click();
        await texto(posCampo("estado"), /Venta recuperada/);
        assert.deepEqual(fiadosPos[1], fiadosPos[0]);
    });

    await prueba("fiado detallado, límite excedido y consultas nativas del panel", async () => {
        await cambiarCliente(otraCaja, true);
        await abrirParaFiados();
        await gestion.locator('label[for="pos-modo-detallada"]').click();
        await gestion.getByText(/^Catálogo listo ·/).waitFor();
        await gestion.locator("[data-consulta]").fill("000019");
        await gestion.getByRole("option").filter({hasText: "Agua con gas"}).click();
        await posCampo("cliente-buscar").fill("Alta fiado");
        await gestion.getByRole("option").filter({hasText: "Alta fiado"}).click();
        await gestion.locator("[data-cantidad]").fill("1201");
        await posCampo("registrar").click();
        await btn(gestion, "Confirmar fiado").click();
        await texto(posCampo("error"), /supera el límite de crédito/);
        await gestion.locator("[data-cantidad]").fill("10");
        await posCampo("registrar").click();
        await btn(gestion, "Confirmar fiado").click();
        await texto(posCampo("estado"), "Venta registrada.");
        await texto(posCampo("venta-metodo"), "Fiado");
        const sinJs = await (await contexto({javaScriptEnabled: false})).newPage();
        await entrar(sinJs, admin, "/fiados/?deuda=1&orden=saldo", false);
        await texto(sinJs.locator("main"), "Abonos del día en Chile");
        await sinJs.getByRole("link", {name: /Alta fiado/}).press("Enter");
        await sinJs.waitForURL(/\/fiados\/gestion\/clientes\//);
        await texto(sinJs.locator("main"), "Historial de abonos");
        const regreso = await sinJs.getByRole("link", {name: "Volver a Fiados"}).getAttribute("href");
        assert.match(regreso, /deuda=1/);
        assert.match(regreso, /orden=saldo/);
    });

    await prueba("CSRF, sesión vencida y refresco fallido tras un abono confirmado", async () => {
        const deuda = (await posCampo("venta-cuenta").textContent()).replace("#", "");
        const url = `/fiados/gestion/cuentas/${deuda}/`;
        await otraCaja.goto(origen + url);
        await otraCaja.locator("#abono-importe").fill("5");
        await btn(otraCaja, "Revisar abono").click();
        await otraCaja.route(rutaAbono, route => route.continue({
            headers: {...route.request().headers(), "x-csrftoken": "invalido"},
        }), {times: 1});
        const csrfRechazado = await postUI(otraCaja, /\/abonar\/$/, () => btn(otraCaja, "Confirmar abono").click());
        assert.equal(csrfRechazado.status(), 403);
        await texto(otraCaja.locator("#abono-error"), /misma cuenta/);
        await otraCaja.context().clearCookies({name: "sessionid"});
        await btn(otraCaja, "Reintentar abono pendiente").click();
        await texto(otraCaja.locator("#abono-error"), /misma cuenta/);
        await entrar(otraCaja, admin, url);
        await otraCaja.route("**/*fragmento=abono", route => route.fulfill({status: 503}), {times: 1});
        await btn(otraCaja, "Reintentar abono pendiente").click();
        await texto(otraCaja.locator("#abono-estado"), "Abono confirmado.");
        await texto(otraCaja.locator("#abono-error"), /El abono está confirmado/);
        assert.equal(await btn(otraCaja, "Reintentar abono pendiente").isVisible(), false);
        assert.deepEqual(abonos.at(-1), abonos.at(-2));
        assert.deepEqual(abonos.at(-2), abonos.at(-3));
        await otraCaja.getByRole("link", {name: "Actualizar saldo e historial"}).click();
        await texto(otraCaja.locator("#fiados-pagos"), "$5");
        assert.equal(await btn(otraCaja, "Revisar abono").isEnabled(), true);
    });

    await prueba("Fiados, abonos y POS en modo claro y oscuro a 390/768/1366/1920 px", async () => {
        for (const ruta of ["/fiados/", rutaCuenta, "/pos/"]) {
            await gestion.setViewportSize({width: 1366, height: 900});
            await gestion.goto(origen + ruta);
            if (ruta === "/pos/") await elegirFiado();
            for (const oscuro of [false, true]) {
                const estaOscuro = await gestion.locator("body").evaluate(body => body.classList.contains("dark-mode"));
                if (estaOscuro !== oscuro) await gestion.locator("#dark-mode-toggle").click();
                for (const width of [390, 768, 1366, 1920]) {
                    await gestion.setViewportSize({width, height: 900});
                    await gestion.waitForFunction(() => document.documentElement.scrollWidth <= innerWidth + 1);
                }
            }
        }
    });

    assert.deepEqual(errores, []);
} catch (error) {
    const log = await readFile(join(temporal, "django.log"), "utf8").catch(() => "");
    if (log) console.error(log.split("\n").slice(-20).join("\n"));
    throw error;
} finally {
    await navegador?.close();
    if (django?.exitCode === null) {
        django.kill();
        await new Promise(resolve => django.once("exit", resolve));
    }
    await rm(temporal, {recursive: true, force: true});
}
