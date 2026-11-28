import {recortar, uuidV4} from "./solicitud-financiera.js";

const clp = new Intl.NumberFormat("es-CL", {style: "currency", currency: "CLP"});
const metodos = new Map([["efectivo", "Efectivo"], ["tarjeta", "Tarjeta"], ["transferencia", "Transferencia"]]);
const idValido = id => Number.isSafeInteger(id) && id > 0;
const uuidValido = clave => typeof clave === "string" && /^[\da-f]{8}-[\da-f]{4}-4[\da-f]{3}-[89ab][\da-f]{3}-[\da-f]{12}$/i.test(clave);
const montoValido = monto => Number.isSafeInteger(monto) && monto > 0 && monto <= 999_999_999_999;
const rechazosDefinitivos = new Map([
    [400, new Set(["json_invalido", "campos_invalidos", "entero_invalido", "texto_invalido", "metodo_pago_invalido", "uuid_invalido"])],
    [404, new Set(["cuenta_no_encontrada"])],
    [409, new Set(["cuenta_no_pagable", "cuenta_inconsistente", "abono_supera_saldo", "caja_no_abierta"])],
]);

function cuerpoValido(datos) {
    return datos && montoValido(datos.importe) && metodos.has(datos.metodo_pago)
        && typeof datos.referencia === "string" && typeof datos.observaciones === "string";
}

function reciboValido(respuesta, status, intento) {
    const datos = JSON.parse(intento.cuerpo);
    return respuesta && idValido(respuesta.id)
        && String(respuesta.cuenta_id) === intento.cuenta
        && respuesta.importe === datos.importe && respuesta.metodo_pago === datos.metodo_pago
        && String(respuesta.usuario_id) === intento.usuario && idValido(respuesta.sesion_caja_id)
        && typeof respuesta.fecha_registro === "string" && Number.isFinite(Date.parse(respuesta.fecha_registro))
        && /^\d{4}-\d{2}-\d{2}$/.test(respuesta.fecha_pago)
        && respuesta.referencia === datos.referencia && respuesta.observaciones === datos.observaciones
        && respuesta.repetida === (status === 200);
}

function montarAbonos(raiz) {
    const porId = nombre => raiz.querySelector("#abono-" + nombre);
    const formulario = porId("formulario");
    const campos = formulario.querySelector("fieldset");
    const dialogo = porId("confirmacion");
    const buscador = () => raiz.querySelector("#fiados-datos-cuenta");
    const usuario = raiz.dataset.usuario;
    const cuenta = buscador().dataset.cuenta;
    const almacenamiento = `stockex.abono.pendiente.v1.${usuario}`;
    const importe = porId("importe");
    const estado = porId("estado");
    const error = porId("error");
    let pendiente, borrador, enviando = false, desactualizado = false, desconocido = false;

    function montoIngresado() {
        const texto = importe.value.trim();
        return /^(?:\d+|\d{1,3}(?:\.\d{3})+)$/.test(texto) ? Number(texto.replaceAll(".", "")) : NaN;
    }

    function mostrarProyeccion() {
        const monto = montoIngresado();
        const {saldo} = buscador().dataset;
        porId("proyectado").textContent = saldo && montoValido(monto) && monto <= Number(saldo)
            ? clp.format(Number(saldo) - monto) : "—";
    }

    function mostrarEstado() {
        const {caja, pagable} = buscador().dataset;
        campos.disabled = enviando || Boolean(pendiente) || desconocido || desactualizado
            || caja !== "true" || pagable !== "true";
        const coincide = pendiente?.cuenta === cuenta;
        porId("reintentar").hidden = !coincide || Boolean(pendiente?.conflicto);
        porId("reintentar").disabled = enviando;
        porId("conciliar").hidden = !(desconocido || (coincide && pendiente?.conflicto));
        porId("conciliar").disabled = enviando;
        const enlace = porId("ir-pendiente");
        enlace.hidden = !pendiente || coincide;
        if (pendiente && !coincide) enlace.href = raiz.dataset.cuentaUrl.replace("/0/", `/${pendiente.cuenta}/`);
        formulario.setAttribute("aria-busy", String(enviando));
        mostrarProyeccion();
    }

    function avisar(texto) {
        error.textContent = texto;
        error.focus();
    }

    function leerIntento() {
        try {
            const guardado = sessionStorage.getItem(almacenamiento);
            if (guardado === null) return;
            const intento = JSON.parse(guardado);
            if (intento.usuario !== usuario || typeof intento.cuenta !== "string"
                || !/^\d+$/.test(intento.cuenta) || !idValido(Number(intento.cuenta))
                || !uuidValido(intento.clave) || typeof intento.cuerpo !== "string"
                || !cuerpoValido(JSON.parse(intento.cuerpo))) throw new Error("Intento inválido");
            pendiente = intento;
            if (intento.cuenta === cuenta) {
                const datos = JSON.parse(intento.cuerpo);
                importe.value = datos.importe;
                for (const campo of ["metodo_pago", "referencia", "observaciones"]) {
                    formulario.elements[campo].value = datos[campo];
                }
            }
            estado.textContent = intento.conflicto ? "La operación requiere conciliación."
                : "Hay un abono sin confirmar. Reintenta con la misma solicitud.";
        } catch {
            desconocido = true;
            avisar("No fue posible leer el abono guardado. Revisa el historial antes de conciliar.");
        }
    }

    function guardar(intento) {
        sessionStorage.setItem(almacenamiento, JSON.stringify(intento));
        pendiente = intento;
    }

    function retirar() {
        sessionStorage.removeItem(almacenamiento);
        pendiente = null;
        desconocido = false;
    }

    async function actualizar() {
        const url = new URL(location.href);
        url.searchParams.set("fragmento", "abono");
        url.searchParams.delete("abonos_antes_de");
        const respuesta = await fetch(url, {
            credentials: "same-origin", redirect: "error", signal: AbortSignal.timeout(12_000),
            headers: {"X-Stockex-Account": usuario},
        });
        if (!respuesta.ok) throw new Error("Consulta rechazada");
        const fragmento = new DOMParser().parseFromString(await respuesta.text(), "text/html");
        const datos = fragmento.querySelector("#fiados-datos-cuenta");
        const pagos = fragmento.querySelector("#fiados-pagos");
        if (datos?.dataset.cuenta !== cuenta || datos.dataset.usuario !== usuario || !pagos) {
            throw new Error("Consulta inesperada");
        }
        buscador().replaceWith(datos);
        raiz.querySelector("#fiados-pagos").replaceWith(pagos);
        desactualizado = false;
    }

    async function enviar() {
        if (enviando || pendiente?.cuenta !== cuenta || pendiente.conflicto) return;
        const intento = pendiente;
        enviando = true;
        error.textContent = "";
        estado.textContent = "Enviando abono…";
        mostrarEstado();
        try {
            const respuesta = await fetch(raiz.dataset.url, {
                method: "POST", credentials: "same-origin", redirect: "manual",
                signal: AbortSignal.timeout(12_000),
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": document.querySelector('meta[name="csrf-token"]').content,
                    "Idempotency-Key": intento.clave, "X-Stockex-Account": usuario,
                },
                body: intento.cuerpo,
            });
            const {status} = respuesta;
            if ([401, 403].includes(status) || respuesta.type === "opaqueredirect") {
                estado.textContent = "";
                avisar("Abono sin confirmar. Vuelve a iniciar sesión con la misma cuenta y reintenta.");
                return;
            }
            if (!respuesta.headers.get("Content-Type")?.includes("application/json")) {
                throw new Error("Respuesta inesperada");
            }
            const datos = await respuesta.json();
            if ([200, 201].includes(status) && reciboValido(datos, status, intento)) {
                retirar();
                formulario.reset();
                estado.textContent = status === 200 ? "Abono recuperado. Ya estaba registrado." : "Abono confirmado.";
                desactualizado = true;
                try {
                    await actualizar();
                    estado.focus();
                } catch {
                    avisar("El abono está confirmado. Actualiza el saldo y el historial para ver el resultado.");
                }
            } else if (status === 409 && datos.error === "clave_en_conflicto") {
                guardar({...intento, conflicto: true});
                estado.textContent = "";
                avisar("La clave está asociada a otros datos. Revisa el historial antes de conciliar.");
            } else if (rechazosDefinitivos.get(status)?.has(datos.error)) {
                retirar();
                estado.textContent = "";
                avisar(datos.mensaje ?? "El servidor rechazó el abono.");
                if ([404, 409].includes(status)) {
                    desactualizado = true;
                    await actualizar().catch(() => {
                        avisar("El abono fue rechazado. Actualiza el saldo y el historial antes de continuar.");
                    });
                }
            } else {
                throw new Error("Resultado no confirmado");
            }
        } catch {
            estado.textContent = "";
            avisar("Abono sin confirmar. Reintenta con la misma clave y los mismos datos.");
        } finally {
            enviando = false;
            mostrarEstado();
        }
    }

    importe.addEventListener("input", mostrarProyeccion);
    porId("completo").addEventListener("click", () => {
        importe.value = buscador().dataset.saldo;
        mostrarProyeccion();
        importe.focus();
    });
    formulario.addEventListener("submit", evento => {
        evento.preventDefault();
        if (campos.disabled) return;
        const monto = montoIngresado();
        const saldo = Number(buscador().dataset.saldo);
        if (!montoValido(monto) || monto > saldo) {
            avisar("Ingresa un importe entero positivo dentro del saldo pendiente.");
            importe.focus();
            return;
        }
        const metodo = formulario.elements.metodo_pago.value;
        borrador = {
            importe: monto, metodo_pago: metodo,
            referencia: recortar(formulario.elements.referencia.value),
            observaciones: recortar(formulario.elements.observaciones.value),
        };
        porId("revision").textContent =
            `Saldo anterior ${clp.format(saldo)} · Abono ${clp.format(monto)} por ${metodos.get(metodo)} · Saldo proyectado ${clp.format(saldo - monto)}.`;
        dialogo.showModal();
    });
    porId("volver").addEventListener("click", () => dialogo.close());
    porId("confirmar").addEventListener("click", () => {
        if (!dialogo.open || !borrador || campos.disabled) return;
        try {
            guardar({usuario, cuenta, clave: uuidV4(), cuerpo: JSON.stringify(borrador)});
        } catch {
            dialogo.close();
            avisar("No se pudo guardar el intento en esta pestaña. Habilita el almacenamiento de sesión.");
            return;
        }
        dialogo.close();
        enviar();
    });
    porId("reintentar").addEventListener("click", enviar);
    porId("conciliar").addEventListener("click", () => {
        if (!window.confirm("¿Ya verificaste el resultado en el historial con un responsable?")) return;
        try {
            retirar();
            location.reload();
        } catch {
            avisar("No se pudo borrar el intento guardado.");
        }
    });
    porId("actualizar").addEventListener("click", async evento => {
        evento.preventDefault();
        if (enviando) return;
        enviando = true;
        mostrarEstado();
        try {
            await actualizar();
            error.textContent = "";
        } catch {
            avisar("No se pudo actualizar el saldo. Verifica que tu sesión siga activa.");
        } finally {
            enviando = false;
            mostrarEstado();
        }
    });

    window.addEventListener("pagehide", evento => { if (evento.persisted) raiz.hidden = true; });
    window.addEventListener("pageshow", evento => { if (evento.persisted) location.reload(); });
    leerIntento();
    mostrarEstado();
}

document.querySelectorAll("[data-abonos]").forEach(montarAbonos);
