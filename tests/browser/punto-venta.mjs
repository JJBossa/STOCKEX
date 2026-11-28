import assert from "node:assert/strict";
import {spawn, spawnSync} from "node:child_process";
import {createWriteStream, existsSync} from "node:fs";
import {mkdir, mkdtemp, readFile, rm} from "node:fs/promises";
import {createRequire} from "node:module";
import {createServer} from "node:net";
import {tmpdir} from "node:os";
import {join, resolve} from "node:path";
import {fileURLToPath} from "node:url";
import {setTimeout as esperar} from "node:timers/promises";

const root = fileURLToPath(new URL("../../", import.meta.url));
const require = createRequire(import.meta.url);
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const python = process.env.PYTHON || (existsSync(join(root, "venv/bin/python")) ? join(root, "venv/bin/python") : "python");
const temporal = await mkdtemp(join(tmpdir(), "stockex-pos-browser-"));
const entorno = {...process.env, DEBUG: "True", ALLOWED_HOSTS: "127.0.0.1",
    DATABASE_URL: "sqlite:///" + join(temporal, "pos.sqlite3")};
const salida = process.env.POS_CAPTURAS ? resolve(process.env.POS_CAPTURAS) : null;
const contrasena = "Prueba-local-STK04B!";
const usuarioA = "pos-vendedor-a", usuarioB = "pos-vendedor-b", administrador = "pos-administrador";
const registro = "**/pos/registrar-venta/";
const prefijo = "stockex.pos.pendiente.v1.";
const prueba = async (nombre, ejecutar) => { await ejecutar(); console.log("OK " + nombre); };
let chrome, django, origen;

function gestionar(...args) {
    const proceso = spawnSync(python, ["manage.py", ...args], {cwd: root, env: entorno, encoding: "utf8"});
    assert.equal(proceso.status, 0, proceso.stderr || args.join(" ") + " falló");
}

async function iniciarDjango() {
    gestionar("migrate", "--noinput", "--verbosity", "0");
    gestionar("shell", "-c", "from tests.browser.punto_venta_django import preparar_datos; preparar_datos()");
    const puerto = createServer();
    await new Promise(resolve => puerto.listen(0, "127.0.0.1", resolve));
    const direccion = "127.0.0.1:" + puerto.address().port;
    await new Promise(resolve => puerto.close(resolve));
    origen = "http://" + direccion;
    django = spawn(python, ["manage.py", "runserver", "--noreload", direccion], {cwd: root, env: entorno});
    const log = createWriteStream(join(temporal, "django.log"));
    django.stdout.pipe(log, {end: false});
    django.stderr.pipe(log);
    for (let i = 0; i < 80; i++) {
        if (await fetch(origen + "/login/").then(r => r.ok).catch(() => false)) return;
        await esperar(100);
    }
    throw new Error("Django no inició.");
}

const pos = page => page.goto(origen + "/pos/");
const control = (page, nombre) => page.locator("#pos-" + nombre);
const elegir = (page, nombre) => page.locator('label[for="pos-' + nombre + '"]').click();
const cobro = page => control(page, "registrar");
const scanner = page => page.locator("[data-consulta]");
const clave = (page, usuario) => page.evaluate(key => JSON.parse(sessionStorage.getItem(key)), prefijo + usuario);
const token = page => page.locator('meta[name="csrf-token"]').getAttribute("content");

async function contexto() {
    const context = await chrome.newContext({viewport: {width: 1366, height: 900}, locale: "es-CL", ignoreHTTPSErrors: true});
    context.setDefaultTimeout(10_000);
    if (process.env.POS_CDN_LOCAL) {
        // Copias exactas de las dependencias de base.html, con los SRI del proyecto intactos.
        await context.route("https://cdn.jsdelivr.net/**", route => {
            const archivo = new URL(route.request().url()).pathname.split("/").at(-1);
            const contentType = archivo.endsWith(".css") ? "text/css"
                : archivo.endsWith(".js") ? "application/javascript" : "font/woff2";
            return route.fulfill({path: join(process.env.POS_CDN_LOCAL, archivo), contentType});
        });
    }
    return context;
}

async function iniciarSesion(page, usuario) {
    await page.goto(origen + "/login/");
    await page.locator("#id_username").fill(usuario);
    await page.locator("#id_password").fill(contrasena);
    await Promise.all([
        page.waitForURL(url => url.pathname === "/"),
        page.locator('form button[type="submit"]').click(),
    ]);
}

async function salir(page) {
    const respuesta = await page.request.post(origen + "/logout/", {headers: {"X-CSRFToken": await token(page)}, maxRedirects: 0});
    assert.equal(respuesta.status(), 302);
}

async function detallar(page) {
    await elegir(page, "modo-detallada");
    await page.getByText(/^Catálogo listo ·/).waitFor();
}

async function buscar(page, texto, nombre = texto) {
    await scanner(page).fill(texto);
    return page.getByRole("option").filter({hasText: nombre}).first();
}

async function exito(page, importe, recuperada = false) {
    const mensaje = recuperada ? "Venta recuperada. Ya estaba registrada." : "Venta registrada.";
    await page.getByText(mensaje, {exact: true}).waitFor();
    assert.equal(await control(page, "venta-total").textContent(), importe);
    assert.match(await control(page, "venta-numero").textContent(), /^V-[a-f0-9]{32}$/);
    assert.ok(Date.parse(await control(page, "venta-fecha").getAttribute("datetime")));
}

async function ventas(admin) {
    const respuesta = await admin.request.get(origen + "/api/v1/ventas/");
    assert.equal(respuesta.status(), 200);
    return (await respuesta.json()).count;
}

async function productos(admin) {
    const datos = {};
    for (const sku of ["000019", "000020", "000021"]) {
        const url = origen + "/api/v1/productos/?search=" + sku;
        const respuesta = await admin.request.get(url);
        assert.equal(respuesta.status(), 200);
        let {results} = await respuesta.json();
        if (!results.length) ({results} = await (await admin.request.get(url + "&activo=false")).json());
        assert.equal(results.length, 1);
        datos[sku] = results[0];
    }
    return datos;
}

async function cambiarProducto(admin, id, cambio) {
    const respuesta = await admin.request.patch(origen + "/api/v1/productos/" + id + "/", {
        data: cambio, headers: {"X-CSRFToken": await token(admin)},
    });
    assert.equal(respuesta.status(), 200, await respuesta.text());
}

function peticion(request) {
    return {clave: request.headers()["idempotency-key"], cuerpo: request.postData()};
}

async function validarAncho(page, ancho) {
    await page.setViewportSize({width: ancho, height: 900});
    assert.deepEqual(await page.evaluate(() => {
        const raiz = document.querySelector(".pos");
        const controles = [...raiz.querySelectorAll("input:not(.btn-check), label.btn, button, .pos-acciones a")]
            .filter(control => control.getClientRects().length && getComputedStyle(control).visibility === "visible")
            .map(control => ({control, rect: control.getBoundingClientRect()}));
        return {
            desplazamiento: document.documentElement.scrollWidth > innerWidth,
            fuera: controles.some(({rect}) => rect.x < 0 || rect.right > innerWidth + 1),
            superpuestos: controles.some(({control, rect}, i) => controles.slice(i + 1).some(otro =>
                !control.contains(otro.control) && !otro.control.contains(control)
                && Math.min(rect.right, otro.rect.right) - Math.max(rect.left, otro.rect.left) > 1
                && Math.min(rect.bottom, otro.rect.bottom) - Math.max(rect.top, otro.rect.top) > 1)),
        };
    }), {desplazamiento: false, fuera: false, superpuestos: false}, ancho + "px");
}

try {
    await iniciarDjango();
    chrome = await chromium.launch({executablePath: process.env.CHROMIUM_PATH, args: ["--no-sandbox"]});
    console.log("Chromium " + chrome.version() + " · Django real · SQLite temporal");
    const context = await contexto();
    const page = await context.newPage();
    const erroresJS = [];
    page.on("pageerror", error => erroresJS.push(String(error)));
    const admin = await (await contexto()).newPage();
    await iniciarSesion(admin, administrador);
    assert.equal((await pos(admin)).status(), 200);
    const catalogo = await productos(admin);
    await iniciarSesion(page, usuarioA);
    await pos(page);
    const usuario = await page.locator("[data-punto-venta]").getAttribute("data-usuario");
    const envios = [], otrasEscrituras = [];
    page.on("request", request => {
        const ruta = new URL(request.url()).pathname;
        if (ruta === "/pos/registrar-venta/") envios.push(peticion(request));
        else if (request.method() === "POST" && ruta.startsWith("/pos/")) otrasEscrituras.push(ruta);
    });

    await prueba("rápida predeterminada, efectivo exacto, foco y segunda venta del mismo importe", async () => {
        await cobro(page).waitFor();
        assert.equal(await page.locator(":focus").getAttribute("id"), "pos-monto");
        assert.equal(await control(page, "monto").inputValue(), "");
        assert.equal(await scanner(page).isVisible(), false);
        assert.equal(await ventas(admin), 0);
        for (let i = 0; i < 2; i++) {
            await control(page, "monto").fill("1.900");
            assert.equal(await control(page, "total").textContent(), "$1.900");
            await (i ? control(page, "monto").press("Control+Enter") : cobro(page).click());
            await exito(page, "$1.900");
            assert.equal(await control(page, "venta-recibido").textContent(), "$1.900");
            assert.equal(await control(page, "venta-vuelto").textContent(), "$0");
            assert.equal(await control(page, "monto").inputValue(), "");
            assert.equal(await page.locator(":focus").getAttribute("id"), "pos-monto");
        }
        assert.notEqual(envios.at(-2).clave, envios.at(-1).clave);
        assert.equal(await ventas(admin), 2);
        assert.equal(await page.evaluate(() => performance.getEntriesByType("navigation").length), 1);
    });

    await prueba("efectivo insuficiente y vuelto; tarjeta y transferencia", async () => {
        await control(page, "monto").fill("1900");
        await control(page, "recibido").fill("1800");
        assert.match(await control(page, "vuelto").textContent(), /Faltan/);
        const antes = envios.length;
        await cobro(page).click();
        assert.match(await control(page, "error").textContent(), /menor que el total/);
        assert.equal(envios.length, antes);
        await control(page, "recibido").fill("2500");
        assert.equal(await control(page, "vuelto").textContent(), "$600");
        await cobro(page).click();
        await exito(page, "$1.900");
        assert.equal(await control(page, "venta-vuelto").textContent(), "$600");
        for (const [metodo, etiqueta] of [["tarjeta", "Tarjeta"], ["transferencia", "Transferencia"]]) {
            await elegir(page, metodo);
            await control(page, "monto").fill("1500");
            await cobro(page).click();
            await exito(page, "$1.500");
            assert.equal(await control(page, "venta-metodo").textContent(), etiqueta);
            assert.equal(await control(page, "venta-cambio").isVisible(), false);
            assert.equal(JSON.parse(envios.at(-1).cuerpo).monto_recibido, undefined);
        }
    });

    await prueba("Enter sin registro y doble clic protegido", async () => {
        await control(page, "monto").fill("850");
        const antes = envios.length;
        await control(page, "monto").press("Enter");
        await cobro(page).press("Enter");
        assert.equal(envios.length, antes);
        await page.route(registro, async route => {
            await esperar(300);
            await route.continue();
        }, {times: 1});
        await cobro(page).dblclick();
        await exito(page, "$850");
        assert.equal(envios.length, antes + 1);
    });

    await prueba("detallada con lector emulado, $1, stock cero y selección por categoría", async () => {
        await detallar(page);
        const antes = envios.length;
        await scanner(page).pressSequentially("000019");
        await scanner(page).press("Enter");
        assert.equal(await control(page, "total").textContent(), "$1");
        assert.equal(envios.length, antes);
        await cobro(page).click();
        await exito(page, "$1");
        assert.equal(await scanner(page).inputValue(), "");
        assert.equal(await page.locator(":focus").getAttribute("id"), "catalogo-consulta");

        await buscar(page, "bebidas frias agua", "Agua con gas");
        await scanner(page).press("ArrowDown");
        assert.equal(await scanner(page).getAttribute("aria-expanded"), "true");
        await scanner(page).press("Enter");
        await (await buscar(page, "000019", "Agua con gas")).click();
        assert.equal(await page.getByRole("textbox", {name: "Cantidad de Agua con gas"}).inputValue(), "2");
        await (await buscar(page, "Jugo de manzana")).click();
        await page.getByRole("textbox", {name: "Cantidad de Jugo de manzana"}).fill("2");
        assert.equal(await control(page, "total").textContent(), "$3.402");
        await page.getByRole("button", {name: "Quitar Agua con gas"}).click();
        assert.equal(await control(page, "total").textContent(), "$3.400");
        await (await buscar(page, "000019", "Agua con gas")).click();
        await cobro(page).click();
        await exito(page, "$3.401");
        assert.equal(JSON.parse(envios.at(-1).cuerpo).items.length, 2);
    });

    await prueba("respuesta perdida después de confirmar, recarga y aislamiento por cuenta", async () => {
        await elegir(page, "modo-rapida");
        await elegir(page, "efectivo");
        await control(page, "monto").fill("723");
        const antes = await ventas(admin);
        await page.route(registro, async route => {
            const respuesta = await route.fetch();
            assert.equal(respuesta.status(), 201, await respuesta.text());
            await route.abort("failed");
        }, {times: 1});
        await cobro(page).click();
        await page.getByRole("button", {name: "Reintentar registro"}).waitFor();
        const intento = envios.at(-1);
        assert.deepEqual(await clave(page, usuario), intento);
        assert.equal(await ventas(admin), antes + 1);
        const cantidadEnvios = envios.length;
        await page.reload();
        await page.getByRole("button", {name: "Reintentar registro"}).waitFor();
        assert.equal(await control(page, "monto").isDisabled(), true);
        assert.equal(envios.length, cantidadEnvios);
        await salir(page);
        await iniciarSesion(page, usuarioB);
        await pos(page);
        await page.getByRole("button", {name: "Registrar venta"}).waitFor();
        assert.equal(await control(page, "monto").inputValue(), "");
        assert.equal(envios.length, cantidadEnvios);
        await salir(page);
        await iniciarSesion(page, usuarioA);
        await pos(page);
        await page.getByRole("button", {name: "Reintentar registro"}).click();
        await exito(page, "$723", true);
        assert.equal(await ventas(admin), antes + 1);
        assert.deepEqual(envios.at(-1), intento);
        assert.equal(await clave(page, usuario), null);
    });

    await prueba("503 y caída de conexión conservan exactamente clave y cuerpo", async () => {
        const antes = await ventas(admin);
        await control(page, "monto").fill("724");
        await page.route(registro, route => route.fulfill({status: 503, json: {error: "registro_temporalmente_ocupado"}}), {times: 1});
        await cobro(page).click();
        await page.getByText(/registro está ocupado/).waitFor();
        const intento = envios.at(-1);
        await page.route(registro, route => route.abort("internetdisconnected"), {times: 1});
        await cobro(page).click();
        await page.getByText(/No se pudo verificar el resultado/).waitFor();
        assert.deepEqual(envios.at(-1), intento);
        await page.route(registro, route => route.fulfill({status: 200, json: {error: "respuesta_incompleta"}}), {times: 1});
        await cobro(page).click();
        await page.getByText(/No se pudo verificar el resultado/).waitFor();
        assert.deepEqual(await clave(page, usuario), intento);
        assert.equal(await ventas(admin), antes);
        await cobro(page).click();
        await exito(page, "$724");
        assert.deepEqual(envios.at(-1), intento);
        assert.equal(await ventas(admin), antes + 1);
    });

    await prueba("la espera agotada mantiene el intento sin modificar", async () => {
        await page.evaluate(() => {
            window.posRelojOriginal = window.setTimeout;
            window.setTimeout = (fn, demora, ...args) =>
                window.posRelojOriginal(fn, demora === 12_000 ? 150 : demora, ...args);
        });
        await page.route(registro, async route => {
            await esperar(350);
            await route.abort("timedout").catch(() => {});
        }, {times: 1});
        await control(page, "monto").fill("729");
        await cobro(page).click();
        await page.getByText(/No se pudo verificar el resultado/).waitFor();
        const intento = envios.at(-1);
        assert.deepEqual(await clave(page, usuario), intento);
        await page.evaluate(() => {
            window.setTimeout = window.posRelojOriginal;
            delete window.posRelojOriginal;
        });
        await cobro(page).click();
        await exito(page, "$729");
        assert.deepEqual(envios.at(-1), intento);
    });

    await prueba("precio vigente y corrección de efectivo exigen confirmación", async () => {
        await detallar(page);
        await (await buscar(page, "Jugo de manzana")).click();
        await control(page, "recibido").fill("1800");
        await cambiarProducto(admin, catalogo["000020"].id, {precio: 2500});
        const antes = await ventas(admin);
        await cobro(page).click();
        await page.getByRole("heading", {name: "Cambios de precio"}).waitFor();
        assert.match(await control(page, "lista-precios").textContent(), /Jugo de manzana.*1\.700.*2\.500/);
        assert.equal(await control(page, "total-actualizado").textContent(), "$2.500");
        assert.equal(await ventas(admin), antes);
        const intento = envios.at(-1);
        await control(page, "aplicar-precios").click();
        assert.equal(envios.at(-1), intento);
        assert.match(await control(page, "error").textContent(), /Corrige el efectivo/);
        assert.equal(await page.locator(":focus").getAttribute("id"), "pos-recibido");
        await control(page, "recibido").fill("3000");
        await cobro(page).click();
        await exito(page, "$2.500");
        assert.equal(await control(page, "venta-vuelto").textContent(), "$500");
        assert.equal(envios.at(-1).clave, intento.clave);
        assert.equal(JSON.parse(envios.at(-1).cuerpo).items[0].precio_visto, 2500);
        assert.equal(await ventas(admin), antes + 1);
    });

    await prueba("producto desactivado conserva las otras líneas, y los nombres se muestran como texto", async () => {
        await (await buscar(page, "Caja", "Caja")).click();
        assert.match(await control(page, "lineas").textContent(), /<b data-producto-prueba>/);
        assert.equal(await control(page, "lineas").locator("[data-producto-prueba]").count(), 0);
        await (await buscar(page, "000019", "Agua con gas")).click();
        await cambiarProducto(admin, catalogo["000021"].id, {activo: false});
        const antes = await ventas(admin);
        await cobro(page).click();
        await control(page, "lineas").locator("[data-indisponible]:not([hidden])").waitFor();
        assert.equal(await control(page, "lineas").locator("li").count(), 2);
        assert.equal(await ventas(admin), antes);
        await page.getByRole("button", {name: /^Quitar Caja/}).click();
        assert.equal(await control(page, "lineas").locator("li").count(), 1);
        await cobro(page).click();
        await exito(page, "$1");
    });

    await prueba("clave asociada a otro contenido exige revisión explícita", async () => {
        await elegir(page, "modo-rapida");
        await control(page, "monto").fill("725");
        const antes = await ventas(admin);
        await page.route(registro, async route => {
            const otrosDatos = {...route.request().postDataJSON(), monto: 726};
            const anterior = await route.fetch({postData: JSON.stringify(otrosDatos)});
            assert.equal(anterior.status(), 201);
            await route.continue();
        }, {times: 1});
        await cobro(page).click();
        await page.getByText(/clave está asociada a otra solicitud/).waitFor();
        const intento = envios.at(-1);
        assert.deepEqual(await clave(page, usuario), intento);
        assert.equal(await cobro(page).isDisabled(), true);
        assert.equal(await ventas(admin), antes + 1);
        await control(page, "cerrar-intento").click();
        assert.equal(await clave(page, usuario), null);
        assert.equal(await control(page, "monto").inputValue(), "");
        assert.equal(await ventas(admin), antes + 1);
    });

    await prueba("sesión vencida y rechazo por CSRF preservan el intento; roles de consulta reciben 403", async () => {
        await control(page, "monto").fill("727");
        await context.clearCookies({name: "sessionid"});
        let antes = await ventas(admin);
        await cobro(page).click();
        await page.getByText(/sesión venció o el acceso fue rechazado/).waitFor();
        const intento = envios.at(-1);
        assert.equal(await ventas(admin), antes);
        await iniciarSesion(page, usuarioA);
        await pos(page);
        await page.getByRole("button", {name: "Reintentar registro"}).click();
        await exito(page, "$727");
        assert.deepEqual(envios.at(-1), intento);

        await control(page, "monto").fill("728");
        await page.locator('meta[name="csrf-token"]').evaluate(elemento => elemento.content = "token-invalido");
        antes = await ventas(admin);
        await cobro(page).click();
        await page.getByText(/sesión venció o el acceso fue rechazado/).waitFor();
        assert.equal(await ventas(admin), antes);
        assert.equal(await control(page, "monto").isDisabled(), true);
        await page.getByRole("link", {name: "Volver a abrir el punto de venta"}).click();
        await page.getByRole("button", {name: "Reintentar registro"}).click();
        await exito(page, "$728");

        const lectura = await (await contexto()).newPage();
        await iniciarSesion(lectura, "pos-consulta");
        const permiso = await pos(lectura);
        assert.equal(permiso.status(), 403);
        assert.equal(await lectura.locator("[data-punto-venta]").count(), 0);
        await lectura.context().close();
    });

    await prueba("390, 768, 1366 y 1920 px en ambos modos; inventario intacto", async () => {
        await control(page, "monto").fill("12500");
        await control(page, "recibido").fill("15000");
        for (const ancho of [390, 768, 1366, 1920]) await validarAncho(page, ancho);
        await page.setViewportSize({width: 390, height: 900});
        await page.getByRole("button", {name: "Ayuda", exact: true}).click();
        await page.getByRole("dialog", {name: "Ayuda del punto de venta"}).waitFor();
        await page.keyboard.press("Escape");
        await page.getByRole("dialog").waitFor({state: "hidden"});
        await page.waitForFunction(() => getComputedStyle(document.querySelector("#accesibilidad-controls")).opacity === "1");
        assert.equal(await page.locator(".primer-uso-mensaje").count(), 0);
        if (salida) {
            await mkdir(salida, {recursive: true});
            await page.mouse.move(0, 0);
            await control(page, "monto").focus();
            await page.screenshot({path: join(salida, "punto-venta-movil.png"), fullPage: true});
        }

        await detallar(page);
        await elegir(page, "tarjeta");
        await (await buscar(page, "000019", "Agua con gas")).click();
        await (await buscar(page, "Jugo de manzana")).click();
        for (const ancho of [390, 768, 1366, 1920]) await validarAncho(page, ancho);
        if (salida) {
            await page.setViewportSize({width: 1366, height: 900});
            await page.screenshot({path: join(salida, "punto-venta-escritorio.png"), fullPage: true});
        }
        const actual = await productos(admin);
        for (const sku in catalogo) assert.equal(actual[sku].stock, catalogo[sku].stock);
        assert.deepEqual(erroresJS, []);
        assert.deepEqual(otrasEscrituras, []);
    });

    await medir(context);
} catch (error) {
    const log = await readFile(join(temporal, "django.log"), "utf8").catch(() => "");
    if (log) console.error(log.split("\n").slice(-24).join("\n"));
    throw error;
} finally {
    await chrome?.close();
    if (django && django.exitCode === null) {
        django.kill();
        await new Promise(resolve => django.once("exit", resolve));
    }
    await rm(temporal, {recursive: true, force: true});
}

async function medir(context) {
    const tab = await context.newPage();
    await pos(tab);
    const mediciones = {carga: [], refresco: [], rapida: [], detallada: [], listo: []};
    const mediana = lista => [...lista].sort((a, b) => a - b)[Math.floor(lista.length / 2)].toFixed(2);
    let recursos;

    for (let i = 0; i < 5; i++) {
        const peticiones = [];
        const registrarPeticion = request => peticiones.push(request.url());
        tab.on("request", registrarPeticion);
        const documento = await pos(tab);
        await tab.waitForFunction(() => document.activeElement.id === "pos-monto");
        const inicial = await tab.evaluate(() => {
            const nav = performance.getEntriesByType("navigation")[0];
            const js = performance.getEntriesByName(new URL("/static/js/punto-venta.js", location.href).href)[0];
            return {carga: nav.loadEventEnd - nav.startTime, posJs: js.decodedBodySize};
        });
        tab.off("request", registrarPeticion);
        assert.equal(peticiones.some(url => url.endsWith("/api/catalogo-productos/")), false);
        mediciones.carga.push(inicial.carga);
        recursos ??= {html: (await documento.body()).length, posJs: inicial.posJs, solicitudes: peticiones.length};
    }

    await detallar(tab);
    await (await buscar(tab, "000019", "Agua con gas")).click();
    const peticiones = [];
    const observar = request => peticiones.push(request.url());
    tab.on("request", observar);
    await scanner(tab).pressSequentially("sin coincidencias", {delay: 35});
    await tab.getByText("Sin resultados", {exact: true}).waitFor();
    for (let i = 0; i < 25; i++) {
        mediciones.refresco.push(await tab.evaluate(cantidad => new Promise(resolve => {
            requestAnimationFrame(() => {
                const inicio = performance.now();
                const campo = document.querySelector("[data-cantidad]");
                campo.value = cantidad;
                campo.dispatchEvent(new Event("input", {bubbles: true}));
                requestAnimationFrame(() => resolve(performance.now() - inicio));
            });
        }), i + 1));
    }
    await esperar(400);
    tab.off("request", observar);
    assert.deepEqual(peticiones, []);

    recursos.buscadorJs = await tab.evaluate(() =>
        performance.getEntriesByName(new URL("/static/js/buscador-productos.js", location.href).href)[0].decodedBodySize);
    await tab.evaluate(() => {
        const formulario = document.querySelector("#pos-formulario");
        new MutationObserver(() => {
            if (formulario.getAttribute("aria-busy") === "false") performance.mark("pos-listo");
        }).observe(formulario, {attributes: true, attributeFilter: ["aria-busy"]});
    });
    await elegir(tab, "tarjeta");
    for (const modalidad of ["rapida", "detallada"]) {
        await elegir(tab, "modo-" + modalidad);
        for (let i = 0; i < 10; i++) {
            if (modalidad === "rapida") await control(tab, "monto").fill("1500");
            else {
                await (await buscar(tab, "000019", "Agua con gas")).click();
                await (await buscar(tab, "Jugo de manzana")).click();
            }
            const respuesta = tab.waitForResponse(res => res.url().endsWith("/pos/registrar-venta/"));
            await cobro(tab).click();
            assert.equal((await respuesta).status(), 201);
            await exito(tab, modalidad === "rapida" ? "$1.500" : "$2.501");
            const tiempo = await tab.evaluate(() => {
                const registro = performance.getEntriesByType("resource").filter(r => r.name.endsWith("/pos/registrar-venta/")).at(-1);
                return {
                    http: registro.responseEnd - registro.startTime,
                    listo: performance.getEntriesByName("pos-listo").at(-1).startTime - registro.responseEnd,
                };
            });
            mediciones[modalidad].push(tiempo.http);
            mediciones.listo.push(tiempo.listo);
        }
    }
    console.log("Rendimiento POS (p50 en ms)", JSON.stringify({
        ...recursos, httpPorBusquedaOCantidad: 0,
        ...Object.fromEntries(Object.entries(mediciones).map(([campo, valores]) => [campo, mediana(valores)])),
    }));
    await tab.close();
}
