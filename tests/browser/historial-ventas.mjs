import assert from "node:assert/strict";
import {spawn, spawnSync} from "node:child_process";
import {createWriteStream, existsSync} from "node:fs";
import {mkdir, mkdtemp, readFile, rm} from "node:fs/promises";
import {createRequire} from "node:module";
import {createServer} from "node:net";
import {tmpdir} from "node:os";
import {join} from "node:path";
import {fileURLToPath} from "node:url";
import {setTimeout as esperar} from "node:timers/promises";
import {randomUUID} from "node:crypto";

const root = fileURLToPath(new URL("../../", import.meta.url));
const require = createRequire(import.meta.url);
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const python = process.env.PYTHON || (existsSync(join(root, "venv/bin/python")) ? join(root, "venv/bin/python") : "python");
const temporal = await mkdtemp(join(tmpdir(), "stockex-historial-browser-"));
const entorno = {...process.env, DEBUG: "True", ALLOWED_HOSTS: "127.0.0.1",
    DATABASE_URL: "sqlite:///" + join(temporal, "historial.sqlite3")};
const password = "Prueba-local-STK05A!";
let django, chromiumLocal, origen;
const fixture = `
from datetime import timedelta
from uuid import uuid4
from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.utils.timezone import now
from inventario.caja import abrir_caja
from inventario.historial_ventas import limites_periodo
from inventario.models import ItemVenta, Producto, Venta
call_command("crear_grupos_permisos", verbosity=0)
admin = User.objects.create_user("hist-admin", password="${password}")
admin.groups.add(Group.objects.get(name="Administrador"))
abrir_caja(admin, str(uuid4()), {"efectivo_inicial": 0})
usuarios = [User.objects.create_user("hist-" + sufijo, password="${password}") for sufijo in ("a", "b")]
for usuario in usuarios:
    usuario.groups.add(Group.objects.get(name="Vendedor"))
lote = []
for i in range(55):
    lote.append(Venta(numero_venta=f"LOTE-{i:03}", usuario=usuarios[0], modalidad="detallada", metodo_pago="tarjeta", total=100))
lote = Venta.objects.bulk_create(lote)
fecha = max(limites_periodo("hoy")[0], now())
Venta.objects.filter(pk__in=[v.pk for v in lote]).update(fecha=fecha)
producto = Producto.objects.create(nombre="Catálogo actual", precio=900)
ItemVenta.objects.create(venta=lote[4], producto=producto, nombre_producto="Descripción histórica", precio_unitario=25, cantidad=4)
Venta.objects.create(numero_venta="V-A-UNICA", usuario=usuarios[0], modalidad="rapida", metodo_pago="efectivo", total=600, monto_recibido=1000, cambio=400)
Venta.objects.create(numero_venta="V-B-PRIVADA", usuario=usuarios[1], modalidad="rapida", metodo_pago="efectivo", total=5000)
historica = Venta.objects.create(numero_venta="H-AYER", usuario=usuarios[0], metodo_pago="credito", total=725)
Venta.objects.filter(pk=historica.pk).update(fecha=limites_periodo("ayer")[0] + timedelta(hours=12))
`;

function gestionar(...args) {
    const proceso = spawnSync(python, ["manage.py", ...args], {cwd: root, env: entorno, encoding: "utf8"});
    assert.equal(proceso.status, 0, proceso.stderr || args.join(" "));
}

async function abrirDjango() {
    gestionar("migrate", "--noinput", "--verbosity", "0");
    gestionar("shell", "-c", fixture);
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

async function contexto(javaScriptEnabled = true) {
    const contexto = await chromiumLocal.newContext({javaScriptEnabled, locale: "es-CL",
        ignoreHTTPSErrors: true, viewport: {width: 1366, height: 900}});
    contexto.setDefaultTimeout(10_000);
    if (process.env.POS_CDN_LOCAL) {
        await contexto.route("https://cdn.jsdelivr.net/**", ruta => {
            const archivo = new URL(ruta.request().url()).pathname.split("/").at(-1);
            const contentType = archivo.endsWith(".css") ? "text/css"
                : archivo.endsWith(".js") ? "application/javascript" : "font/woff2";
            return ruta.fulfill({path: join(process.env.POS_CDN_LOCAL, archivo), contentType});
        });
    }
    return contexto;
}

async function login(page, usuario, javaScriptEnabled = true) {
    await page.goto(origen + "/login/");
    if (javaScriptEnabled) {
        await page.locator("#id_username").fill(usuario);
        await page.locator("#id_password").fill(password);
        await Promise.all([page.waitForURL(url => url.pathname === "/"), page.locator('form button[type="submit"]').click()]);
    } else {
        const csrfmiddlewaretoken = await page.locator('#main-content input[name="csrfmiddlewaretoken"]').getAttribute("value");
        const respuesta = await page.request.post(origen + "/login/", {
            form: {username: usuario, password, csrfmiddlewaretoken}, maxRedirects: 0,
        });
        assert.equal(respuesta.status(), 302);
    }
    await page.goto(origen + "/ventas/");
    assert.equal(await page.locator("[data-historial]").count(), 1);
}

async function parcial(page, ejecutar) {
    const pendiente = page.waitForResponse(respuesta =>
        new URL(respuesta.url()).pathname === "/ventas/" && respuesta.request().headers()["x-historial-parcial"] === "1");
    await ejecutar();
    const respuesta = await pendiente;
    assert.equal(respuesta.status(), 200);
    assert.match(respuesta.headers()["cache-control"], /no-store/);
    await page.waitForFunction(() => !document.querySelector("[data-historial]").hasAttribute("aria-busy"));
}

function total(page) {
    return page.locator("[data-total-vigente]").textContent();
}

async function verificarAncho(page, ancho) {
    await page.setViewportSize({width: ancho, height: 900});
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(resolve)));
    const medicion = await page.evaluate(() => {
        const controles = [...document.querySelectorAll(".historial-ventas :is(.hist-periodo, .btn, select, input:not([type=radio]))")]
            .filter(el => el.getClientRects().length)
            .map(el => ({rect: el.getBoundingClientRect(), etiqueta: el.id || el.textContent.trim()}));
        return {
            desborda: document.documentElement.scrollWidth > innerWidth,
            fuera: controles.filter(({rect}) => rect.left < 0 || rect.right > innerWidth + 1).map(el => el.etiqueta),
            choques: controles.flatMap(({rect: r, etiqueta}, i) => controles.slice(i + 1)
                .filter(({rect: s}) => Math.min(r.right, s.right) - Math.max(r.left, s.left) > 1
                    && Math.min(r.bottom, s.bottom) - Math.max(r.top, s.top) > 1)
                .map(el => [etiqueta, el.etiqueta])),
        };
    });
    assert.deepEqual(medicion, {desborda: false, fuera: [], choques: []}, ancho + "px");
}

try {
    await abrirDjango();
    chromiumLocal = await chromium.launch({executablePath: process.env.CHROMIUM_PATH, args: ["--no-sandbox"]});
    console.log("Chromium " + chromiumLocal.version() + " · Django real · SQLite temporal");
    const admin = await (await contexto()).newPage();
    const vendedor = await (await contexto()).newPage();
    const errores = [];
    admin.on("pageerror", err => errores.push(String(err)));
    vendedor.on("pageerror", err => errores.push(String(err)));
    await login(admin, "hist-admin");
    await login(vendedor, "hist-a");
    assert.equal(await total(admin), "$11.100");
    assert.equal(await total(vendedor), "$6.100");
    assert.equal(await vendedor.getByLabel("Vendedor", {exact: true}).count(), 0);
    assert.equal(await vendedor.getByText("V-B-PRIVADA").count(), 0);
    console.log("OK alcance de Administrador y Vendedor, hoy por defecto");

    await parcial(admin, () => admin.getByText("Ayer", {exact: true}).click());
    assert.equal(await total(admin), "$725");
    assert.match(admin.url(), /periodo=ayer/);
    await parcial(admin, () => admin.evaluate(() => history.back()));
    assert.equal(await total(admin), "$11.100");
    await parcial(admin, () => admin.getByText("Ayer", {exact: true}).click());
    await admin.getByText("Rango personalizado", {exact: true}).click();
    const ayer = await admin.locator("time").getAttribute("datetime");
    await admin.getByLabel("Desde").fill(ayer.slice(0, 10));
    await admin.getByLabel("Hasta").fill(ayer.slice(0, 10));
    await parcial(admin, () => admin.getByRole("button", {name: "Filtrar"}).click());
    assert.equal(await total(admin), "$725");
    await admin.getByLabel("Hasta").fill("2000-01-01");
    await parcial(admin, () => admin.getByRole("button", {name: "Filtrar"}).click());
    assert.match(await admin.getByRole("alert").textContent(), /igual o posterior/);
    console.log("OK rangos, actualización parcial, atrás del navegador y validación");

    await parcial(admin, () => admin.getByRole("link", {name: "Limpiar"}).click());
    await admin.getByLabel("Vendedor", {exact: true}).selectOption({label: "hist-a"});
    await admin.getByLabel("Método de pago", {exact: true}).selectOption("tarjeta");
    const solicitudes = [];
    const observar = r => { if (new URL(r.url()).pathname === "/ventas/") solicitudes.push(r.url()); };
    admin.on("request", observar);
    await admin.getByLabel("Número de venta").pressSequentially("LOTE", {delay: 70});
    await esperar(300);
    assert.deepEqual(solicitudes, []);
    admin.off("request", observar);
    await parcial(admin, () => admin.getByRole("button", {name: "Filtrar"}).click());
    assert.equal(await total(admin), "$5.500");
    assert.equal(await admin.locator("tbody tr").count(), 50);
    await parcial(admin, () => admin.getByRole("link", {name: "Siguiente"}).click());
    assert.equal(await total(admin), "$5.500");
    assert.equal(await admin.locator("tbody tr").count(), 5);
    const filtrada = new URL(admin.url());
    await admin.getByRole("link", {name: "Ver venta LOTE-004"}).click();
    await admin.getByText("Descripción histórica").waitFor();
    assert.equal(await admin.getByText("Catálogo actual").count(), 0);
    const detalle = admin.url();
    await admin.getByRole("link", {name: "Volver al historial"}).click();
    assert.deepEqual(new URL(admin.url()).searchParams, filtrada.searchParams);
    await vendedor.getByRole("link", {name: "Ver venta V-A-UNICA"}).click();
    await vendedor.getByText("Venta rápida registrada sin detalle de productos.").waitFor();
    await vendedor.getByText("$400", {exact: true}).waitFor();
    await vendedor.getByRole("link", {name: "Volver al historial"}).click();
    console.log("OK filtros combinados sin tráfico por letra, totales por página y enlaces de regreso");

    const encabezado = await vendedor.locator('meta[name="csrf-token"]').getAttribute("content");
    const nueva = await vendedor.request.post(origen + "/pos/registrar-venta/", {
        data: {modalidad: "rapida", monto: 50, metodo_pago: "efectivo"},
        headers: {"X-CSRFToken": encabezado, "Idempotency-Key": randomUUID()},
    });
    assert.equal(nueva.status(), 201, await nueva.text());
    await vendedor.evaluate(() => { window.histNavegacion = "conservada"; });
    await parcial(vendedor, () => vendedor.getByRole("link", {name: "Actualizar"}).click());
    assert.equal(await total(vendedor), "$6.150");
    assert.equal(await vendedor.evaluate(() => window.histNavegacion), "conservada");
    console.log("OK actualización de una venta nueva sin recargar");

    if (process.env.HIST_CAPTURAS) await mkdir(process.env.HIST_CAPTURAS, {recursive: true});
    for (const tema of ["claro", "oscuro"]) {
        if (tema === "oscuro") {
            await admin.evaluate(() => {
                localStorage.setItem("darkMode", "true");
                document.querySelector("#dark-mode-toggle").click();
            });
            await admin.locator("body.dark-mode").waitFor();
        }
        for (const ancho of [390, 768, 1366, 1920]) await verificarAncho(admin, ancho);
        if (process.env.HIST_CAPTURAS) {
            await admin.setViewportSize({width: tema === "claro" ? 1366 : 390, height: 900});
            await admin.screenshot({path: join(process.env.HIST_CAPTURAS, "historial-" + tema + ".png")});
        }
    }
    await admin.goto(detalle);
    for (const ancho of [390, 768, 1366, 1920]) await verificarAncho(admin, ancho);
    await admin.locator("#dark-mode-toggle").click();
    await admin.locator("body.light-mode").waitFor();
    for (const ancho of [390, 768, 1366, 1920]) await verificarAncho(admin, ancho);
    console.log("OK historial y detalle en dos temas a 390, 768, 1366 y 1920 px");

    const sinJS = await (await contexto(false)).newPage();
    await login(sinJS, "hist-a", false);
    await sinJS.getByText("Ayer", {exact: true}).click();
    await sinJS.getByRole("button", {name: "Filtrar"}).click();
    assert.match(sinJS.url(), /periodo=ayer/);
    assert.equal(await total(sinJS), "$725");
    await sinJS.getByRole("link", {name: "Ver venta H-AYER"}).click();
    await sinJS.getByText("No registrada", {exact: true}).waitFor();
    await sinJS.getByRole("link", {name: "Volver al historial"}).click();
    assert.match(sinJS.url(), /periodo=ayer/);
    assert.deepEqual(errores, []);
    console.log("OK navegación, filtros y detalle sin JavaScript");
} catch (error) {
    const log = await readFile(join(temporal, "django.log"), "utf8").catch(() => "");
    console.error(log.split("\n").slice(-28).join("\n"));
    throw error;
} finally {
    await chromiumLocal?.close();
    if (django && django.exitCode === null) {
        django.kill();
        await new Promise(resolve => django.once("exit", resolve));
    }
    await rm(temporal, {recursive: true, force: true});
}
