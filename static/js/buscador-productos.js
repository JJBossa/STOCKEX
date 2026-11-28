const LIMITE = 12;
const INTERVALO = 60_000;
const PRECIO = new Intl.NumberFormat("es-CL", {style: "currency", currency: "CLP"});

function normalizar(texto) {
    return texto.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase().trim().replace(/\s+/g, " ");
}

export function indexarProductos(productos) {
    return productos.map(producto => ({
        producto,
        sku: normalizar(producto.sku ?? ""),
        nombre: normalizar(producto.nombre),
        categoria: normalizar(producto.categoria ?? ""),
    })).sort((a, b) => {
        for (const campo of ["nombre", "sku"]) {
            if (a[campo] !== b[campo]) return a[campo] < b[campo] ? -1 : 1;
        }
        return a.producto.id - b.producto.id;
    });
}

export function buscarProductos(indice, consulta) {
    const texto = normalizar(consulta);
    if (!texto) return [];
    const palabras = texto.split(" ");
    const grupos = [[], [], [], []];
    for (const {producto, sku, nombre, categoria} of indice) {
        const campos = [sku, nombre, categoria];
        let rango;
        if (sku === texto) rango = 0;
        else if (nombre === texto) rango = 1;
        else if (campos.some(campo => campo.startsWith(texto))) rango = 2;
        else if (palabras.every(palabra => campos.some(campo => campo.includes(palabra)))) rango = 3;
        else continue;
        if (grupos[rango].length < LIMITE) grupos[rango].push(producto);
    }
    return grupos.flat().slice(0, LIMITE);
}

export function montarBuscador(raiz) {
    const entrada = raiz.querySelector("[data-consulta]");
    const lista = raiz.querySelector("[data-resultados]");
    const estado = raiz.querySelector("[data-estado]");
    const reintentar = raiz.querySelector("[data-reintentar]");
    const seleccion = raiz.querySelector("[data-seleccion]");
    let indice = null, etag = null, pendiente = null, ultimoIntento = 0;
    let resultados = [], activo = -1, abierto = false;

    function cerrar() {
        abierto = false;
        marcar(-1);
        lista.hidden = true;
        entrada.setAttribute("aria-expanded", "false");
        entrada.removeAttribute("aria-activedescendant");
    }

    function marcar(posicion) {
        if (activo >= 0) {
            lista.children[activo].classList.remove("active");
            lista.children[activo].setAttribute("aria-selected", "false");
        }
        activo = posicion;
        if (activo < 0) {
            entrada.removeAttribute("aria-activedescendant");
            return;
        }
        const opcion = lista.children[activo];
        opcion.classList.add("active");
        opcion.setAttribute("aria-selected", "true");
        entrada.setAttribute("aria-activedescendant", opcion.id);
        opcion.scrollIntoView({block: "nearest"});
    }

    function renderizar() {
        if (!indice) return;
        resultados = buscarProductos(indice, entrada.value);
        activo = -1;
        entrada.removeAttribute("aria-activedescendant");
        lista.replaceChildren(...resultados.map((producto, i) => {
            const opcion = document.createElement("li");
            opcion.id = `${lista.id}-${i}`;
            opcion.setAttribute("role", "option");
            opcion.setAttribute("aria-selected", "false");
            opcion.className = "list-group-item list-group-item-action py-1";
            opcion.dataset.posicion = i;
            const nombre = document.createElement("strong");
            nombre.textContent = producto.nombre;
            const detalles = document.createElement("small");
            detalles.className = "d-block";
            detalles.textContent = [
                producto.sku || "Sin SKU", producto.categoria || "Sin categoría", PRECIO.format(producto.precio),
            ].join(" · ");
            opcion.append(nombre, detalles);
            return opcion;
        }));
        lista.hidden = !abierto || resultados.length === 0;
        entrada.setAttribute("aria-expanded", String(!lista.hidden));
        estado.textContent = !entrada.value.trim() ? `Catálogo listo · ${indice.length} productos`
            : resultados.length === 1 ? "1 resultado visible"
                : resultados.length ? `${resultados.length} resultados visibles` : "Sin resultados";
    }

    function elegir(producto) {
        cerrar();
        if (seleccion && raiz.dataset.detalle) {
            seleccion.href = raiz.dataset.detalle.replace(/0\/$/, `${producto.id}/`);
            seleccion.textContent = `Ver ${producto.nombre}`;
            seleccion.hidden = false;
        }
        estado.textContent = `Seleccionado: ${producto.nombre}`;
        raiz.dispatchEvent(new CustomEvent("producto-seleccionado", {bubbles: true, detail: producto}));
    }

    function limpiarCatalogo() {
        indice = etag = null;
        resultados = [];
        cerrar();
        lista.replaceChildren();
        if (seleccion) {
            seleccion.hidden = true;
            seleccion.textContent = "";
            seleccion.removeAttribute("href");
        }
    }

    async function actualizar() {
        if (pendiente) return;
        ultimoIntento = Date.now();
        const control = new AbortController();
        pendiente = control;
        reintentar.hidden = true;
        raiz.setAttribute("aria-busy", "true");
        if (!indice) estado.textContent = "Cargando catálogo…";
        try {
            const respuesta = await fetch(raiz.dataset.catalogo, {
                cache: "no-store",
                credentials: "same-origin",
                redirect: "error",
                headers: etag ? {"If-None-Match": etag} : {},
                signal: control.signal,
            });
            if (respuesta.status === 304 && indice) return;
            if (!respuesta.ok) throw new Error("Catálogo no disponible");
            const datos = await respuesta.json();
            if (control.signal.aborted) return;
            indice = indexarProductos(datos.productos);
            etag = respuesta.headers.get("ETag");
            if (seleccion) seleccion.hidden = true;
            renderizar();
        } catch (error) {
            if (!control.signal.aborted) {
                limpiarCatalogo();
                estado.textContent = "No se pudo cargar el catálogo. Comprueba la conexión o la sesión.";
                reintentar.hidden = false;
            }
        } finally {
            if (pendiente === control) {
                pendiente = null;
                raiz.removeAttribute("aria-busy");
            }
        }
    }

    entrada.addEventListener("input", () => {
        abierto = true;
        if (seleccion) seleccion.hidden = true;
        renderizar();
    });
    entrada.addEventListener("blur", cerrar);
    entrada.addEventListener("keydown", evento => {
        if (evento.isComposing) return;
        if (evento.key === "Escape") {
            evento.preventDefault();
            cerrar();
        } else if (evento.key === "Enter") {
            evento.preventDefault();
            if (abierto && resultados.length) elegir(resultados[activo < 0 ? 0 : activo]);
        } else if (["ArrowDown", "ArrowUp"].includes(evento.key) && resultados.length) {
            evento.preventDefault();
            abierto = true;
            lista.hidden = false;
            entrada.setAttribute("aria-expanded", "true");
            const siguiente = evento.key === "ArrowDown" ? activo + 1 : (activo < 0 ? -1 : activo - 1);
            marcar((siguiente + resultados.length) % resultados.length);
        }
    });
    lista.addEventListener("pointerdown", evento => evento.preventDefault());
    lista.addEventListener("click", evento => {
        const opcion = evento.target.closest("[data-posicion]");
        if (opcion) elegir(resultados[Number(opcion.dataset.posicion)]);
    });
    reintentar.addEventListener("click", () => {
        entrada.focus();
        abierto = true;
        actualizar();
    });
    const revalidar = () => {
        if (!document.hidden && Date.now() - ultimoIntento >= 10_000) actualizar();
    };
    window.addEventListener("focus", revalidar);
    document.addEventListener("visibilitychange", revalidar);
    window.addEventListener("pageshow", revalidar);
    window.addEventListener("pagehide", () => {
        pendiente?.abort();
        pendiente = null;
        raiz.removeAttribute("aria-busy");
        ultimoIntento = 0;
        entrada.value = "";
        limpiarCatalogo();
    });
    window.setInterval(revalidar, INTERVALO);
    actualizar();
    return {actualizar};
}

document.querySelectorAll("[data-buscador-productos]").forEach(montarBuscador);
