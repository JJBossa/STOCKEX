import {recortar, uuidV4} from "./solicitud-financiera.js";

const clp = new Intl.NumberFormat("es-CL", {style: "currency", currency: "CLP"});
const clienteValido = cliente => cliente && Number.isSafeInteger(cliente.id) && cliente.id > 0
    && typeof cliente.nombre === "string" && (cliente.rut === null || typeof cliente.rut === "string");

export function montarFiado(raiz, usuario) {
    const elemento = nombre => raiz.querySelector("#pos-" + nombre);
    const panel = elemento("fiado");
    const campo = elemento("cliente-buscar");
    const lista = elemento("clientes");
    const aviso = elemento("clientes-estado");
    const vencimiento = elemento("fiado-vencimiento");
    const notas = elemento("fiado-notas");
    const dialogo = elemento("fiado-confirmacion");
    let cliente, saldo, buscandoSaldo, controlSaldo, controlBusqueda, temporizador;
    let resultados = [], opcionActiva = -1, confirmar, totalActual = 0;

    const headers = {"X-Stockex-Account": usuario};
    const etiqueta = c => `${c.nombre}${c.rut ? " · RUT " + c.rut : ""} · #${c.id}`;

    function actualizar(total) {
        totalActual = total ?? 0;
        if (!panel.dataset.saldo) return;
        let texto = buscandoSaldo ? "Consultando saldo…" : "Saldo no disponible.";
        if (saldo) {
            texto = `Saldo anterior ${clp.format(saldo.saldo)} · Saldo proyectado ${clp.format(BigInt(saldo.saldo) + BigInt(totalActual))} · `
                + (saldo.limite_credito === 0 ? "Sin tope de crédito." : `Límite ${clp.format(saldo.limite_credito)}.`);
        }
        elemento("cliente-saldo").textContent = texto;
        elemento("fiado-revision-saldo").textContent = texto;
        elemento("fiado-confirmar").disabled = Boolean(buscandoSaldo);
    }

    function cancelarBusqueda() {
        window.clearTimeout(temporizador);
        controlBusqueda?.abort();
        controlBusqueda = null;
        resultados = [];
        opcionActiva = -1;
        lista.replaceChildren();
        lista.hidden = true;
        campo.setAttribute("aria-expanded", "false");
        campo.removeAttribute("aria-activedescendant");
    }

    function marcar(indice) {
        if (!resultados.length) return;
        opcionActiva = indice;
        [...lista.children].forEach((nodo, i) => nodo.setAttribute("aria-selected", String(i === indice)));
        const opcion = lista.children[indice];
        campo.setAttribute("aria-activedescendant", opcion.id);
        opcion.scrollIntoView({block: "nearest"});
    }

    function seleccionar(elegido, consultar = true) {
        cancelarBusqueda();
        controlSaldo?.abort();
        controlSaldo = null;
        cliente = elegido;
        elemento("cliente-elegido").hidden = !cliente;
        campo.hidden = Boolean(cliente);
        campo.removeAttribute("aria-invalid");
        campo.value = "";
        elemento("cliente-nombre").textContent = cliente ? etiqueta(cliente) : "";
        aviso.textContent = cliente ? "" : "Ingresa al menos dos caracteres.";
        saldo = null;
        buscandoSaldo = Boolean(cliente && consultar && panel.dataset.saldo);
        actualizar(totalActual);
        if (!buscandoSaldo) return;
        const peticion = controlSaldo = new AbortController();
        fetch(panel.dataset.saldo.replace("/0/", `/${cliente.id}/`), {
            credentials: "same-origin", redirect: "error",
            signal: AbortSignal.any([peticion.signal, AbortSignal.timeout(12_000)]), headers,
        }).then(async respuesta => {
            if (!respuesta.ok) return;
            const datos = await respuesta.json();
            if (controlSaldo === peticion && datos.cliente_id === cliente?.id
                && Number.isSafeInteger(datos.saldo) && datos.saldo >= 0
                && Number.isSafeInteger(datos.limite_credito) && datos.limite_credito >= 0) saldo = datos;
        }).catch(() => {}).finally(() => {
            if (controlSaldo !== peticion) return;
            buscandoSaldo = false;
            actualizar(totalActual);
        });
    }

    function elegir(elegido) {
        seleccionar(elegido);
        elemento("quitar-cliente").focus();
    }

    campo.addEventListener("input", () => {
        cancelarBusqueda();
        const consulta = recortar(campo.value);
        campo.removeAttribute("aria-invalid");
        if (consulta.length < 2) {
            aviso.textContent = "Ingresa al menos dos caracteres.";
            return;
        }
        if (consulta.length > 100) return;
        const peticion = controlBusqueda = new AbortController();
        aviso.textContent = "Buscando clientes…";
        temporizador = window.setTimeout(async () => {
            try {
                const url = new URL(panel.dataset.clientes, location.href);
                url.searchParams.set("q", consulta);
                const respuesta = await fetch(url, {
                    credentials: "same-origin", redirect: "error", headers,
                    signal: AbortSignal.any([peticion.signal, AbortSignal.timeout(12_000)]),
                });
                if (!respuesta.ok) throw new Error("Consulta rechazada");
                const datos = await respuesta.json();
                if (controlBusqueda !== peticion || peticion.signal.aborted) return;
                if (!Array.isArray(datos.clientes) || datos.clientes.length > 20
                    || !datos.clientes.every(clienteValido)) throw new Error("Resultados inválidos");
                resultados = datos.clientes;
                resultados.forEach((resultado, i) => {
                    const opcion = document.createElement("li");
                    opcion.id = `pos-cliente-opcion-${i}`;
                    opcion.setAttribute("role", "option");
                    opcion.setAttribute("aria-selected", "false");
                    opcion.className = "list-group-item list-group-item-action text-break";
                    opcion.textContent = etiqueta(resultado);
                    opcion.addEventListener("click", () => elegir(resultado));
                    lista.append(opcion);
                });
                lista.hidden = resultados.length === 0;
                campo.setAttribute("aria-expanded", String(!lista.hidden));
                aviso.textContent = resultados.length ? `${resultados.length} resultados. Usa las flechas y Enter.` : "No se encontraron clientes activos.";
            } catch {
                if (controlBusqueda === peticion && !peticion.signal.aborted) aviso.textContent = "No se pudieron consultar los clientes.";
            }
        }, 250);
    });
    campo.addEventListener("keydown", evento => {
        if (!["ArrowDown", "ArrowUp", "Enter", "Escape"].includes(evento.key) || evento.isComposing) return;
        if (evento.key === "Escape") {
            cancelarBusqueda();
            aviso.textContent = "";
            return;
        }
        evento.preventDefault();
        evento.stopPropagation();
        if (evento.key === "Enter") {
            if (opcionActiva >= 0) elegir(resultados[opcionActiva]);
        } else if (resultados.length) {
            const anterior = evento.key === "ArrowUp";
            const indice = opcionActiva < 0 ? (anterior ? resultados.length - 1 : 0)
                : (opcionActiva + (anterior ? -1 : 1) + resultados.length) % resultados.length;
            marcar(indice);
        }
    });
    elemento("quitar-cliente").addEventListener("click", () => {
        seleccionar(null);
        campo.focus();
    });
    elemento("fiado-volver").addEventListener("click", () => dialogo.close());
    elemento("fiado-confirmar").addEventListener("click", () => {
        if (!dialogo.open || !confirmar) return;
        const registrar = confirmar;
        confirmar = null;
        dialogo.close();
        registrar();
    });

    const alta = elemento("cliente-alta");
    if (alta) montarAlta(alta, elemento, headers, elegir);

    return {
        actualizar,
        cancelarBusqueda,
        cliente: () => cliente,
        campos(invalidar) {
            if (!cliente) return invalidar("Selecciona un cliente activo para registrar el fiado.", campo);
            if (!vencimiento.validity.valid) return invalidar("Revisa la fecha de vencimiento.", vencimiento);
            return {cliente_id: cliente.id, fecha_vencimiento: vencimiento.value || null, notas: recortar(notas.value)};
        },
        restaurar(datos, guardado) {
            seleccionar(clienteValido(guardado) && guardado.id === datos.cliente_id
                ? guardado : {id: datos.cliente_id, nombre: "Cliente", rut: null}, false);
            vencimiento.value = datos.fecha_vencimiento ?? "";
            notas.value = datos.notas;
        },
        revisar(datos, total, registrar) {
            confirmar = registrar;
            elemento("fiado-revision-cliente").textContent = etiqueta(cliente);
            elemento("fiado-revision-total").textContent = clp.format(total);
            elemento("fiado-revision-fecha").textContent = datos.fecha_vencimiento
                ? datos.fecha_vencimiento.split("-").reverse().join("/") : "Sin vencimiento";
            actualizar(total);
            dialogo.showModal();
        },
        limpiar() {
            seleccionar(null);
            vencimiento.value = notas.value = "";
        },
    };
}

function montarAlta(dialogo, elemento, headers, seleccionar) {
    const formulario = elemento("cliente-formulario");
    const campos = formulario.querySelector("fieldset");
    const boton = elemento("cliente-alta-confirmar");
    const error = elemento("cliente-alta-error");
    let pendiente, enviando = false;
    function actualizar() {
        campos.disabled = Boolean(pendiente);
        boton.disabled = enviando;
        boton.textContent = pendiente ? "Reintentar alta" : "Crear y seleccionar";
    }
    elemento("alta-cliente").addEventListener("click", () => {
        actualizar();
        dialogo.showModal();
    });
    elemento("cliente-alta-volver").addEventListener("click", () => dialogo.close());
    formulario.addEventListener("submit", async evento => {
        evento.preventDefault();
        if (enviando) return;
        if (!pendiente) pendiente = {clave: uuidV4(), cuerpo: JSON.stringify(Object.fromEntries(new FormData(formulario)))};
        enviando = true;
        error.textContent = "";
        actualizar();
        try {
            const respuesta = await fetch(formulario.action, {
                method: "POST", credentials: "same-origin", redirect: "manual",
                signal: AbortSignal.timeout(12_000),
                headers: {...headers, "Content-Type": "application/json",
                    "Idempotency-Key": pendiente.clave,
                    "X-CSRFToken": document.querySelector('meta[name="csrf-token"]').content},
                body: pendiente.cuerpo,
            });
            if (!respuesta.headers.get("Content-Type")?.includes("application/json")) throw new Error("Respuesta inválida");
            const datos = await respuesta.json();
            if ([200, 201].includes(respuesta.status) && clienteValido(datos) && datos.activo === true
                && datos.repetida === (respuesta.status === 200)) {
                pendiente = null;
                formulario.reset();
                dialogo.close();
                seleccionar(datos);
            } else if (respuesta.status === 400 || (respuesta.status === 409 && datos.error === "rut_en_conflicto")) {
                pendiente = null;
                error.textContent = datos.mensaje ?? "Revisa los datos del cliente.";
            } else {
                throw new Error("Alta pendiente");
            }
        } catch {
            error.textContent = "Alta sin confirmar. Reintenta con la misma solicitud o vuelve a buscar al cliente.";
        } finally {
            enviando = false;
            actualizar();
        }
    });
}
