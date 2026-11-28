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

const root = fileURLToPath(new URL("../../", import.meta.url));
const require = createRequire(import.meta.url);
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const venv = join(root, "venv/bin/python");
const python = process.env.PYTHON || (existsSync(venv) ? venv : "python");
const temporal = await mkdtemp(join(tmpdir(), "stockex-anulacion-browser-"));
const entorno = {
    ...process.env,
    DEBUG: "True",
    USE_REDIS: "False",
    ALLOWED_HOSTS: "127.0.0.1",
    DATABASE_URL: "sqlite:///" + join(temporal, "prueba.sqlite3"),
};
const password = "Prueba-local-STK05B!";
const filtros = "?periodo=todas&metodo_pago=tarjeta&page=2";
const fixture = `
from django.contrib.auth.models import Group, User
from django.core.management import call_command
from inventario.models import ItemVenta, Producto, Venta
call_command("crear_grupos_permisos")
for nombre, grupo in (("caja-admin", "Administrador"), ("caja-vendedor", "Vendedor")):
    usuario = User.objects.create_user(nombre, password="${password}")
    usuario.groups.add(Group.objects.get(name=grupo))
venta = Venta.objects.create(numero_venta="B-ANULAR", usuario=usuario, modalidad="detallada",
                             metodo_pago="tarjeta", subtotal=4000, total=4000)
producto = Producto.objects.create(nombre="Nombre actual", precio=4000)
ItemVenta.objects.create(venta=venta, producto=producto, nombre_producto="Producto registrado",
                        cantidad=1, precio_unitario=4000)
Venta.objects.bulk_create([
    Venta(numero_venta=f"B-VIGENTE-{i:02d}", usuario=usuario, modalidad="rapida",
          metodo_pago="tarjeta", subtotal=100, total=100) for i in range(51)
])
Venta.objects.create(numero_venta="B-HISTORICA", usuario=usuario,
                     metodo_pago="efectivo", total=700, cancelada=True)
Venta.objects.create(numero_venta="B-SIN-JS", usuario=usuario,
                     metodo_pago="efectivo", total=500)
`;
let django, navegador, origen;

function gestionar(...args) {
    const proceso = spawnSync(python, ["manage.py", ...args], {
        cwd: root, env: entorno, encoding: "utf8",
    });
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
    django = spawn(python, ["manage.py", "runserver", "--noreload", direccion], {
        cwd: root, env: entorno,
    });
    const log = createWriteStream(join(temporal, "django.log"));
    django.stdout.pipe(log, {end: false});
    django.stderr.pipe(log);
    for (let i = 0; i < 80; i++) {
        if (await fetch(origen + "/login/").then(r => r.ok).catch(() => false)) return;
        await esperar(100);
    }
    throw new Error("Django no inició.");
}

async function entrar(usuario, javaScriptEnabled = true) {
    const contexto = await navegador.newContext({
        javaScriptEnabled, locale: "es-CL", viewport: {width: 1366, height: 900},
    });
    if (process.env.POS_CDN_LOCAL) {
        await contexto.route("https://cdn.jsdelivr.net/**", ruta => {
            const archivo = new URL(ruta.request().url()).pathname.split("/").at(-1);
            const path = join(process.env.POS_CDN_LOCAL, archivo);
            if (!existsSync(path)) return ruta.abort();
            const contentType = archivo.endsWith(".css") ? "text/css"
                : archivo.endsWith(".js") ? "application/javascript" : "font/woff2";
            return ruta.fulfill({path, contentType});
        });
    }
    contexto.setDefaultTimeout(10_000);
    const page = await contexto.newPage();
    await page.goto(origen + "/login/");
    if (!javaScriptEnabled) {
        const csrf = await page.locator('#main-content input[name="csrfmiddlewaretoken"]').getAttribute("value");
        const sesion = await contexto.request.post(origen + "/login/", {
            form: {username: usuario, password, csrfmiddlewaretoken: csrf}, maxRedirects: 0,
        });
        assert.equal(sesion.status(), 302);
        return page;
    }
    await page.locator("#id_username").fill(usuario);
    await page.locator("#id_password").fill(password);
    await Promise.all([
        page.waitForURL(url => url.pathname === "/"),
        page.locator('form button[type="submit"]').click(),
    ]);
    return page;
}

async function comprobarPantallas(page, estado) {
    for (const modo of [false, true]) {
        // El selector del tema pertenece a la barra de escritorio.
        await page.setViewportSize({width: 1366, height: 900});
        const oscuro = await page.locator("body").evaluate(el => el.classList.contains("dark-mode"));
        if (oscuro !== modo) await page.locator("#dark-mode-toggle").click();
        const color = modo ? "rgb(45, 53, 66)" : "rgb(255, 255, 255)";
        await page.waitForFunction(
            esperado => getComputedStyle(document.querySelector(".hist-panel")).backgroundColor === esperado,
            color,
        );
        for (const width of [390, 768, 1366, 1920]) {
            await page.setViewportSize({width, height: 900});
            const resultado = await page.evaluate(() => {
                const ventas = document.querySelector("[data-estado-venta]");
                const controles = [...ventas.querySelectorAll("summary, textarea, button, a.btn")]
                    .filter(el => !el.hidden && el.getClientRects().length)
                    .map(el => el.getBoundingClientRect());
                return {
                    oscuro: document.body.classList.contains("dark-mode"),
                    color: getComputedStyle(ventas.querySelector(".hist-panel")).backgroundColor,
                    desborde: document.documentElement.scrollWidth > innerWidth,
                    fuera: controles.some(rect => rect.left < -1 || rect.right > innerWidth + 1),
                    estado: ventas.dataset.estadoVenta,
                };
            });
            assert.deepEqual(resultado, {oscuro: modo, color, desborde: false, fuera: false, estado},
                width + "px · " + (modo ? "oscuro" : "claro"));
        }
    }
}

try {
    await abrirDjango();
    navegador = await chromium.launch({
        executablePath: process.env.CHROMIUM_PATH, args: ["--no-sandbox"],
    });
    console.log("Chromium " + navegador.version() + " · Django real · SQLite temporal");
    const administrador = await entrar("caja-admin");
    const vendedor = await entrar("caja-vendedor");
    const errores = [];
    administrador.on("pageerror", error => errores.push(String(error)));
    await administrador.goto(origen + "/ventas/" + filtros);
    assert.equal(await administrador.locator("[data-total-vigente]").textContent(), "$9.100");
    await administrador.getByRole("link", {name: "Ver venta B-ANULAR"}).click();
    const urlDetalle = administrador.url();
    const formulario = administrador.locator("[data-form-anulacion]");
    const motivo = formulario.getByLabel("Motivo de la anulación");
    const confirmar = formulario.getByRole("button", {name: "Confirmar anulación"});
    const revisar = formulario.getByRole("link", {name: "Comprobar estado"});
    assert.equal(await confirmar.isVisible(), false);
    await administrador.getByText("Anular venta", {exact: true}).click();
    await formulario.getByText(/irreversible/).waitFor();
    await formulario.getByText("$4.000", {exact: true}).waitFor();
    await formulario.getByText("Tarjeta", {exact: true}).waitFor();
    await formulario.getByText("B-ANULAR", {exact: true}).waitFor();
    await formulario.getByText("Fecha y hora original · Chile").waitFor();
    await comprobarPantallas(administrador, "vigente");

    await vendedor.goto(urlDetalle);
    assert.equal(await vendedor.locator("[data-form-anulacion]").count(), 0);
    const accion = new URL(await formulario.getAttribute("action"), origen).href;
    const csrf = await vendedor.locator('meta[name="csrf-token"]').getAttribute("content");
    const prohibida = await vendedor.request.post(accion, {
        headers: {"X-CSRFToken": csrf}, form: {motivo: "No autorizada"},
    });
    assert.equal(prohibida.status(), 403);
    assert.equal(await vendedor.locator("[data-estado-venta]").getAttribute("data-estado-venta"), "vigente");

    await motivo.fill("   ");
    await confirmar.click();
    await formulario.getByRole("status").getByText(/Ingresa un motivo válido/).waitFor();
    assert.equal(await motivo.inputValue(), "   ");
    await motivo.fill("Registro duplicado <&>");

    let envios = 0;
    let fase = "antes";
    await administrador.route(url => url.href === accion, async ruta => {
        if (ruta.request().method() !== "POST") return ruta.continue();
        envios += 1;
        if (fase === "despues") {
            const respuesta = await ruta.fetch();
            assert.equal(respuesta.status(), 201);
        }
        await ruta.abort();
    });
    // El segundo evento se dispara sin esperar la respuesta ni la desactivación del botón.
    await formulario.evaluate(el => {
        el.requestSubmit();
        el.requestSubmit();
    });
    await formulario.getByRole("status").getByText(/No se pudo confirmar el resultado/).waitFor();
    assert.equal(envios, 1);
    assert.equal(await confirmar.isDisabled(), true);
    assert.equal(await motivo.inputValue(), "Registro duplicado <&>");
    await revisar.click();
    await formulario.getByRole("status").getByText(/La venta sigue vigente/).waitFor();
    assert.equal(await confirmar.isEnabled(), true);
    assert.equal(await motivo.inputValue(), "Registro duplicado <&>");

    fase = "despues";
    await confirmar.click();
    await formulario.getByRole("status").getByText(/No se pudo confirmar el resultado/).waitFor();
    assert.equal(await confirmar.isDisabled(), true);
    assert.equal(await motivo.inputValue(), "Registro duplicado <&>");
    await revisar.click();
    await administrador.locator('[data-estado-venta="anulada"]').waitFor();
    assert.equal(envios, 2);
    assert.equal(administrador.url(), urlDetalle);
    assert.equal(await administrador.locator("[data-motivo-anulacion]").textContent(), "Registro duplicado <&>");
    await administrador.getByText("caja-admin", {exact: true}).last().waitFor();
    await administrador.getByText("Producto registrado", {exact: true}).waitFor();
    assert.equal(await formulario.count(), 0);
    await comprobarPantallas(administrador, "anulada");
    await administrador.getByRole("link", {name: "Volver al historial"}).click();
    assert.equal(new URL(administrador.url()).search, filtros);
    assert.equal(await administrador.locator("[data-total-vigente]").textContent(), "$5.100");
    const fila = administrador.getByRole("row").filter({hasText: "B-ANULAR"});
    await fila.getByText("Anulada", {exact: true}).waitFor();
    await fila.getByText("$4.000", {exact: true}).waitFor();

    const nativa = await entrar("caja-admin", false);
    await nativa.goto(origen + "/ventas/?periodo=todas&metodo_pago=efectivo");
    await nativa.getByRole("link", {name: "Ver venta B-HISTORICA"}).click();
    await nativa.getByText("Anulación histórica sin información de anulación disponible.").waitFor();
    await nativa.getByRole("link", {name: "Volver al historial"}).click();
    await nativa.getByRole("link", {name: "Ver venta B-SIN-JS"}).click();
    await nativa.getByText("Anular venta", {exact: true}).click();
    await nativa.getByLabel("Motivo de la anulación").fill("  ");
    await nativa.getByRole("button", {name: "Confirmar anulación"}).click();
    await nativa.getByText(/Ingresa un motivo válido/).waitFor();
    assert.equal(await nativa.getByLabel("Motivo de la anulación").inputValue(), "  ");
    await nativa.getByLabel("Motivo de la anulación").fill("Anulación sin JavaScript");
    await nativa.getByRole("button", {name: "Confirmar anulación"}).click();
    await nativa.locator('[data-estado-venta="anulada"]').waitFor();
    assert.deepEqual(errores, []);
    console.log("OK confirmación, CSRF, permisos, doble envío, pérdida de respuesta y recuperación.");
    console.log("OK historial y filtros, modo sin JavaScript y 390/768/1366/1920 px en claro y oscuro.");
} catch (error) {
    const log = await readFile(join(temporal, "django.log"), "utf8").catch(() => "");
    console.error(log.split("\n").slice(-24).join("\n"));
    throw error;
} finally {
    await navegador?.close();
    if (django && django.exitCode === null) {
        django.kill();
        await new Promise(resolve => django.once("exit", resolve));
    }
    await rm(temporal, {recursive: true, force: true});
}
