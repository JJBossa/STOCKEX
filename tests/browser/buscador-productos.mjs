import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import {createServer} from "node:http";
import {createRequire} from "node:module";

const require = createRequire(import.meta.url);
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const plantilla = (await readFile(new URL("../../templates/inventario/buscador_productos.html", import.meta.url), "utf8"))
    .replace("{% url 'catalogo_productos' %}", "/catalogo")
    .replace("{% url 'detalle_producto' 0 %}", "/producto/0/");
const modulo = await readFile(new URL("../../static/js/buscador-productos.js", import.meta.url));
let productos, version, peticiones, error;

const servidor = createServer((req, res) => {
    if (req.url === "/catalogo") {
        peticiones++;
        if (error) return res.writeHead(503).end();
        const headers = {"Content-Type": "application/json", "Cache-Control": "private, no-store", ETag: version};
        if (req.headers["if-none-match"] === version) return res.writeHead(304, headers).end();
        return res.writeHead(200, headers).end(JSON.stringify({productos}));
    }
    if (req.url === "/buscador.js") return res.writeHead(200, {"Content-Type": "text/javascript"}).end(modulo);
    if (req.url !== "/") return res.writeHead(404).end();
    res.writeHead(200, {"Content-Type": "text/html; charset=utf-8"})
        .end(`<!doctype html><html lang="es"><meta charset="utf-8">${plantilla}
        <button id="siguiente">Siguiente</button><script type="module" src="/buscador.js"></script></html>`);
});
await new Promise(resolve => servidor.listen(0, "127.0.0.1", resolve));
let browser;
try {
    browser = await chromium.launch({executablePath: process.env.CHROMIUM_PATH, args: ["--no-sandbox"]});
    console.log(`Chromium ${browser.version()}`);
    for (const cantidad of [531, 5000]) {
        productos = [
            {id: 1, sku: "000019", nombre: "Bebida Limón", categoria: "Frías", precio: 1900},
            {id: 2, sku: "L2", nombre: "Limón", categoria: "Ingredientes", precio: 1},
            {id: 3, sku: "L3", nombre: "Limón dulce", categoria: "Frías", precio: 2100},
            {id: 4, sku: "L4", nombre: "<b>Texto literal</b>", categoria: null, precio: 30},
            {id: 5, sku: "L5", nombre: "000019", categoria: null, precio: 1},
        ];
        for (let i = 6; i <= cantidad; i++) {
            productos.push({id: i, sku: `${i}`.padStart(7, "0"), nombre: `Bebida sintética ${i}`, categoria: "Frías", precio: 1500});
        }
        peticiones = 0;
        version = '"a"';
        error = false;
        const page = await browser.newPage();
        await page.goto(`http://127.0.0.1:${servidor.address().port}/`);
        await page.getByText(`Catálogo listo · ${cantidad} productos`).waitFor();
        const entrada = page.getByRole("combobox");
        const opciones = page.getByRole("option");
        await entrada.fill("LIMON");
        assert.deepEqual(await opciones.locator("strong").allTextContents(), ["Limón", "Limón dulce", "Bebida Limón"]);
        await entrada.press("ArrowDown");
        await entrada.press("ArrowUp");
        assert.equal(await entrada.getAttribute("aria-activedescendant"), await opciones.last().getAttribute("id"));
        await entrada.press("Escape");
        assert.equal(await entrada.getAttribute("aria-expanded"), "false");
        await entrada.press("Tab");
        assert.equal(await page.locator(":focus").getAttribute("id"), "siguiente");
        await entrada.fill("");
        await entrada.pressSequentially("000019");
        await entrada.press("Enter");
        assert.equal(await page.getByRole("link", {name: "Ver Bebida Limón"}).getAttribute("href"), "/producto/1/");
        await entrada.press("Tab");
        assert.equal(await page.locator(":focus").textContent(), "Ver Bebida Limón");
        await entrada.fill("00001");
        assert.ok((await opciones.allTextContents()).some(texto => texto.includes("000019 · Frías")));
        await entrada.fill("bebida frias limon");
        assert.equal(await opciones.locator("strong").textContent(), "Bebida Limón");
        await entrada.fill("texto literal");
        assert.equal(await opciones.locator("strong").textContent(), "<b>Texto literal</b>");
        assert.equal(await opciones.locator("b").count(), 0);
        await entrada.fill("inexistente");
        await page.getByText("Sin resultados", {exact: true}).waitFor();
        await entrada.fill("frías");
        assert.equal(await opciones.count(), 12);
        assert.equal(peticiones, 1);

        const medidas = await page.evaluate(async registros => {
            const {indexarProductos, buscarProductos} = await import("/buscador.js");
            const indice = indexarProductos(registros);
            const input = document.querySelector("[data-consulta]");
            const consultas = ["bebida", "sintetica frias", "000019", "limon", "ausente"];
            const busqueda = [], visual = [];
            for (let i = 0; i < 100; i++) {
                const inicio = performance.now();
                buscarProductos(indice, consultas[i % consultas.length]);
                busqueda.push(performance.now() - inicio);
            }
            input.focus();
            for (let i = 0; i < 25; i++) {
                await new Promise(resolve => requestAnimationFrame(() => {
                    const inicio = performance.now();
                    input.value = consultas[i % consultas.length];
                    input.dispatchEvent(new Event("input", {bubbles: true}));
                    requestAnimationFrame(() => {
                        visual.push(performance.now() - inicio);
                        resolve();
                    });
                }));
            }
            const p95 = lista => lista.sort((a, b) => a - b)[Math.ceil(lista.length * 0.95) - 1];
            return [p95(busqueda), p95(visual)];
        }, productos);
        assert.equal(peticiones, 1);
        console.log(`STK-03 navegador ${cantidad}: búsqueda p95 ${medidas[0].toFixed(2)} ms, `
            + `actualización visual p95 ${medidas[1].toFixed(2)} ms, 0 HTTP por búsquedas`);

        async function volver(validacion) {
            await page.evaluate(() => {
                const anterior = Date.now;
                Date.now = () => anterior() + 61_000;
                window.dispatchEvent(new Event("focus"));
            });
            await validacion();
        }
        const condicional = page.waitForResponse(r => r.url().endsWith("/catalogo") && r.status() === 304);
        await volver(() => condicional);
        productos[0].precio = 4200;
        version = '"b"';
        await entrada.fill("000019");
        await volver(() => page.getByText("000019 · Frías · $4.200").waitFor());
        error = true;
        await volver(() => page.getByRole("button", {name: "Reintentar"}).waitFor());
        assert.equal(await opciones.count(), 0);
        error = false;
        await page.getByRole("button", {name: "Reintentar"}).click();
        await page.getByRole("option").filter({hasText: "$4.200"}).waitFor();
        await page.evaluate(() => window.dispatchEvent(new Event("pagehide")));
        assert.equal(await entrada.inputValue(), "");
        assert.equal(await opciones.count(), 0);
        assert.deepEqual(await page.evaluate(() => [localStorage.length, sessionStorage.length]), [0, 0]);
        await page.close();
    }
} finally {
    await browser?.close();
    await new Promise(resolve => servidor.close(resolve));
}
