import {uuidV4} from "./solicitud-financiera.js";

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const idValido = valor => /^[1-9][0-9]{0,18}$/.test(String(valor));
const fechaValida = valor => typeof valor === "string" && Number.isFinite(Date.parse(valor));
const moneda = new Intl.NumberFormat("es-CL", {style: "currency", currency: "CLP"});
const numero = new Intl.NumberFormat("es-CL");
const clasificaciones = {cuadrada: "Caja cuadrada", faltante: "Faltante", sobrante: "Sobrante"};
const clasificar = diferencia => diferencia === 0n ? "cuadrada" : diferencia < 0n ? "faltante" : "sobrante";
const operaciones = {apertura: "Apertura", ingreso: "Ingreso", retiro: "Retiro", cierre: "Cierre"};
const rechazos = new Map([
    [400, new Set(["json_invalido", "campos_invalidos", "entero_invalido", "texto_invalido",
        "uuid_invalido", "tipo_invalido", "observaciones_requeridas"])],
    [404, new Set(["sesion_no_encontrada"])],
    [409, new Set(["caja_abierta", "caja_cerrada", "resumen_cambiado"])],
    [413, new Set(["payload_demasiado_grande"])],
    [415, new Set(["tipo_de_contenido_invalido"])],
]);

function recortar(valor) {
    // Los servicios comparan los textos después de aplicar str.strip().
    return valor.replace(/^[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+|[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+$/gu, "");
}

function leerImporte(campo, minimo) {
    const texto = campo.value.trim();
    if (!/^(?:\d+|\d{1,3}(?:\.\d{3})+)$/.test(texto)) return null;
    const monto = Number(texto.replaceAll(".", ""));
    return Number.isSafeInteger(monto) && monto >= minimo && monto <= Number(campo.dataset.maximo)
        ? monto : null;
}

function esTexto(valor) {
    return typeof valor === "string";
}

function cuerpoValido(operacion, datos) {
    const entero = (valor, min) => Number.isSafeInteger(valor) && valor >= min;
    if (!datos) return false;
    if (operacion === "apertura") {
        return entero(datos.efectivo_inicial, 0) && esTexto(datos.observaciones);
    }
    if (operacion === "cierre") {
        return entero(datos.efectivo_contado, 0) && esTexto(datos.observaciones) && uuid.test(datos.huella);
    }
    return datos.tipo === operacion && entero(datos.importe, 1) && esTexto(datos.motivo);
}

function confirmacionValida(resultado, status, cuenta, pendiente) {
    const {operacion, sesion, cuerpo} = pendiente;
    const pedido = JSON.parse(cuerpo);
    if (!resultado || !idValido(resultado.id) || resultado.repetida !== (status === 200)) return false;
    if (operacion === "apertura") {
        return String(resultado.abierta_por_id) === cuenta && fechaValida(resultado.abierta_en)
            && resultado.efectivo_inicial === pedido.efectivo_inicial
            && resultado.observaciones_apertura === pedido.observaciones;
    }
    if (operacion === "cierre") {
        const r = resultado.resumen;
        return String(resultado.id) === sesion && String(resultado.cerrada_por_id) === cuenta
            && fechaValida(resultado.cerrada_en) && fechaValida(resultado.abierta_en)
            && idValido(resultado.abierta_por_id) && esTexto(resultado.observaciones_apertura)
            && resultado.efectivo_contado === pedido.efectivo_contado
            && resultado.observaciones_cierre === pedido.observaciones && resultado.huella === pedido.huella
            && Number.isInteger(r?.diferencia) && Number.isInteger(r.efectivo_esperado)
            && Number.isInteger(r.total_vigente) && Number.isInteger(r.cantidad_vigente)
            && Number.isInteger(r.efectivo_inicial) && Number.isInteger(r.ingresos) && Number.isInteger(r.retiros)
            && Number.isInteger(r.cantidad_ingresos) && Number.isInteger(r.cantidad_retiros)
            && Number.isInteger(r.cantidad_anulada) && Number.isInteger(r.monto_anulado)
            && ["efectivo", "tarjeta", "transferencia", "credito", "mixto"].every(metodo =>
                Number.isInteger(r.por_metodo?.[metodo]?.importe) && Number.isInteger(r.por_metodo[metodo].cantidad)
            )
            && r.clasificacion === clasificar(BigInt(r.diferencia));
    }
    return String(resultado.sesion_id) === sesion && String(resultado.usuario_id) === cuenta
        && resultado.tipo === operacion && resultado.importe === pedido.importe
        && resultado.motivo === pedido.motivo && fechaValida(resultado.fecha);
}

function montarCaja(raiz) {
    const elemento = nombre => raiz.querySelector("#caja-" + nombre);
    const cuenta = raiz.dataset.cuenta;
    const resumen = elemento("resumen");
    const formularios = [...raiz.querySelectorAll("form[data-operacion]")];
    const dialogo = elemento("confirmacion");
    const contado = elemento("contado");
    const aviso = elemento("error");
    const mensaje = elemento("mensaje");
    const pendientes = new Map();
    const claveLocal = operacion => `stockex.caja.pendiente.v1.${cuenta}.${operacion}`;
    const destino = (ruta, sesion) => ruta.replace("/0/", `/${sesion}/`);
    let estado = leerEstado(resumen);
    let ocupado = false;
    let requiereActualizar = false;
    let comparar = null;
    let propuesta = null;
    let almacenamientoDisponible = true;

    function leerEstado(contenedor) {
        const datos = JSON.parse(contenedor.querySelector("#caja-datos-estado").textContent);
        if (datos.cuenta !== cuenta || typeof datos.abierta !== "boolean"
            || (datos.id && (!idValido(datos.id) || !uuid.test(datos.huella) || !Array.isArray(datos.metricas)))) {
            throw new Error("Estado de caja inválido");
        }
        return datos;
    }

    function avisar(texto, enfocar = true) {
        aviso.textContent = texto;
        if (texto && enfocar) aviso.focus();
    }

    function diferenciaActual() {
        if (!estado.id || !contado) return null;
        const importe = leerImporte(contado, 0);
        return importe === null ? null : BigInt(importe) - BigInt(estado.esperado);
    }

    function mostrarDiferencia() {
        if (!contado) return;
        const diferencia = diferenciaActual();
        elemento("diferencia").textContent = diferencia === null ? "—"
            : `${clasificaciones[clasificar(diferencia)]} · ${moneda.format(diferencia)}`;
        elemento("observaciones-cierre").required = diferencia !== null && diferencia !== 0n;
    }

    function mostrarEstado() {
        for (const formulario of formularios) {
            const operacion = formulario.dataset.operacion;
            const apertura = operacion === "apertura";
            const panel = elemento(operacion);
            panel.hidden = apertura ? estado.abierta : !estado.id;
            if (!apertura) panel.querySelector("[data-sesion]").textContent = estado.id ?? "";
            formulario.querySelector("fieldset").disabled = panel.hidden || ocupado
                || requiereActualizar || !almacenamientoDisponible || pendientes.size > 0
                || (operacion === "cierre" && comparar !== null);
        }
        elemento("actualizar").setAttribute("aria-disabled", String(ocupado));
        mostrarDiferencia();
    }

    function boton(etiqueta, accion, estilo) {
        const control = document.createElement("button");
        control.type = "button";
        control.className = `btn btn-sm ${estilo}`;
        control.textContent = etiqueta;
        control.disabled = ocupado;
        control.addEventListener("click", accion);
        return control;
    }

    function mostrarPendientes() {
        elemento("pendientes").hidden = !pendientes.size;
        const lista = elemento("pendientes-lista");
        lista.replaceChildren();
        for (const [operacion, intento] of pendientes) {
            const fila = document.createElement("li");
            fila.className = "mb-2";
            const detalle = document.createElement("p");
            detalle.className = "mb-1";
            if (!intento) {
                detalle.textContent = `${operaciones[operacion]} · el intento guardado requiere revisión.`;
            } else {
                const pedido = JSON.parse(intento.cuerpo);
                const importe = pedido.efectivo_inicial ?? pedido.importe ?? pedido.efectivo_contado;
                const sesion = intento.sesion ? ` · Sesión #${intento.sesion}` : "";
                detalle.textContent = `${operaciones[operacion]}${sesion} · ${moneda.format(importe)} · `
                    + (intento.conflicto ? "Clave en conflicto. Revisa los registros." : "Resultado sin confirmar.");
            }
            const acciones = document.createElement("div");
            acciones.className = "d-flex flex-wrap gap-2";
            if (intento && !intento.conflicto) {
                acciones.append(boton("Reintentar", () => enviar(intento), "btn-primary"));
            }
            acciones.append(boton("Resolver tras revisar", () => reconciliar(operacion), "btn-outline-secondary"));
            fila.append(detalle, acciones);
            lista.append(fila);
        }
    }

    function cargarPendientes() {
        for (const operacion of Object.keys(operaciones)) {
            let guardado;
            try {
                guardado = sessionStorage.getItem(claveLocal(operacion));
            } catch {
                almacenamientoDisponible = false;
                avisar("Habilita el almacenamiento de sesión para iniciar o recuperar operaciones de caja.", false);
                return;
            }
            if (guardado === null) continue;
            try {
                const intento = JSON.parse(guardado);
                if (intento.cuenta !== cuenta || intento.operacion !== operacion || !uuid.test(intento.clave)
                    || typeof intento.cuerpo !== "string" || !cuerpoValido(operacion, JSON.parse(intento.cuerpo))
                    || (operacion === "apertura" ? intento.sesion !== null : !idValido(intento.sesion))) {
                    throw new Error("Intento inválido");
                }
                if (!Array.isArray(intento.metricas) || !intento.metricas.every(fila =>
                    Array.isArray(fila) && esTexto(fila[0]) && /^-?\d+$/.test(fila[1]) && typeof fila[2] === "boolean"
                )) delete intento.metricas;
                pendientes.set(operacion, intento);
            } catch {
                pendientes.set(operacion, null);
            }
        }
    }

    function retirar(operacion) {
        sessionStorage.removeItem(claveLocal(operacion));
        pendientes.delete(operacion);
    }

    function reconciliar(operacion) {
        if (ocupado || !window.confirm("Confirma que revisaste la caja, los movimientos o el historial y ya determinaste el resultado de este intento.")) return;
        try {
            retirar(operacion);
        } catch {
            avisar("No se pudo actualizar el almacenamiento de esta pestaña.");
            return;
        }
        requiereActualizar = true;
        actualizar();
    }

    function guardar(operacion, datos, sesion, metricas) {
        if (ocupado || pendientes.size || !almacenamientoDisponible) return;
        let intento;
        try {
            intento = {cuenta, operacion, sesion, clave: uuidV4(), cuerpo: JSON.stringify(datos)};
            if (metricas) intento.metricas = metricas;
            sessionStorage.setItem(claveLocal(operacion), JSON.stringify(intento));
        } catch {
            avisar("No se pudo guardar el intento en esta pestaña. Revisa el almacenamiento de sesión.");
            return;
        }
        pendientes.set(operacion, intento);
        enviar(intento);
    }

    function mostrarCambios(anterior) {
        const lista = elemento("diferencias");
        lista.replaceChildren();
        const nuevos = new Map(estado.metricas.map(([nombre, valor]) => [nombre, valor]));
        for (const [nombre, antes, importe] of anterior ?? []) {
            const ahora = nuevos.get(nombre);
            if (ahora === undefined || antes === ahora) continue;
            const formato = importe ? moneda : numero;
            const fila = document.createElement("li");
            fila.textContent = `${nombre} pasó de ${formato.format(BigInt(antes))} a ${formato.format(BigInt(ahora))}.`;
            lista.append(fila);
        }
        if (!lista.children.length) {
            const fila = document.createElement("li");
            fila.textContent = "Revisa los importes y cantidades del resumen actualizado.";
            lista.append(fila);
        }
        elemento("cambios").hidden = false;
        elemento("cambios").focus();
    }

    async function obtenerResumen() {
        const respuesta = await fetch(raiz.dataset.resumen, {
            credentials: "same-origin", redirect: "error", signal: AbortSignal.timeout(12_000),
        });
        if (!respuesta.ok) throw new Error("Consulta rechazada");
        const documento = new DOMParser().parseFromString(await respuesta.text(), "text/html");
        const fragmento = documento.querySelector("[data-estado-caja]");
        const nuevo = leerEstado(fragmento);
        const otraSesion = nuevo.id !== estado.id;
        estado = nuevo;
        resumen.replaceChildren(fragmento);
        if (otraSesion) {
            for (const formulario of formularios) {
                if (formulario.dataset.operacion !== "apertura") formulario.reset();
            }
            if (elemento("cambios")) elemento("cambios").hidden = true;
        }
        if (comparar) {
            if (estado.id === comparar.sesion) {
                const datos = JSON.parse(comparar.cuerpo);
                contado.value = String(datos.efectivo_contado);
                elemento("observaciones-cierre").value = datos.observaciones;
                mostrarCambios(comparar.metricas);
            } else {
                avisar(`La sesión #${comparar.sesion} ya no está activa. Consulta el historial de cierres.`);
            }
            comparar = null;
        }
        requiereActualizar = false;
    }

    async function refrescar(mensajeError) {
        try {
            await obtenerResumen();
        } catch {
            avisar(mensajeError);
        }
    }

    function establecerOcupado(valor) {
        ocupado = valor;
        mostrarEstado();
        mostrarPendientes();
    }

    async function actualizar(evento) {
        evento?.preventDefault();
        if (ocupado) return;
        avisar("");
        establecerOcupado(true);
        await refrescar("No se pudo actualizar el resumen. Vuelve a pulsar Actualizar.");
        establecerOcupado(false);
    }

    function mostrarCierre(resultado, instantanea) {
        if (raiz.dataset.detalle) {
            window.location.assign(destino(raiz.dataset.detalle, resultado.id));
            return;
        }
        const contenedor = elemento("confirmado");
        const titulo = document.createElement("h2");
        titulo.className = "h4 card-body";
        titulo.textContent = `Cierre de caja #${resultado.id}`;
        contenedor.replaceChildren(titulo, instantanea);
        contenedor.hidden = false;
    }

    async function enviar(intento) {
        if (ocupado || pendientes.get(intento.operacion) !== intento || intento.conflicto) return;
        const {operacion, sesion} = intento;
        const ruta = operacion === "apertura" ? raiz.dataset.apertura
            : destino(operacion === "cierre" ? raiz.dataset.cierre : raiz.dataset.movimiento, sesion);
        avisar("");
        mensaje.textContent = "Consultando el resultado…";
        establecerOcupado(true);
        try {
            const respuesta = await fetch(ruta, {
                method: "POST", credentials: "same-origin", redirect: "manual",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": document.querySelector('meta[name="csrf-token"]').content,
                    "X-Stockex-Account": cuenta,
                    "Idempotency-Key": intento.clave,
                },
                body: intento.cuerpo,
                signal: AbortSignal.timeout(12_000),
            });
            mensaje.textContent = "";
            const {status} = respuesta;
            if (respuesta.type === "opaqueredirect" || status === 401 || status === 403) {
                avisar("Resultado sin confirmar. Vuelve a abrir Caja con la misma cuenta y reintenta.");
                return;
            }
            if (!respuesta.headers.get("Content-Type")?.includes("application/json")) throw new Error("Respuesta inesperada");
            const datos = await respuesta.json();
            if ([200, 201].includes(status) && confirmacionValida(datos, status, cuenta, intento)) {
                let instantanea;
                if (operacion === "cierre" && !raiz.dataset.detalle) {
                    const documento = new DOMParser().parseFromString(datos.instantanea_html, "text/html");
                    instantanea = documento.querySelector("[data-instantanea-caja]");
                    if (!instantanea) throw new Error("Falta la instantánea confirmada");
                }
                retirar(operacion);
                mensaje.textContent = `${operaciones[operacion]} confirmad${operacion === "apertura" ? "a" : "o"}`
                    + (datos.repetida ? " · recuperado del servidor." : ".");
                const tipoFormulario = ["ingreso", "retiro"].includes(operacion) ? "movimiento" : operacion;
                formularios.find(f => f.dataset.operacion === tipoFormulario)?.reset();
                if (operacion === "cierre") {
                    mostrarCierre(datos, instantanea);
                    if (raiz.dataset.detalle) return;
                }
                requiereActualizar = true;
                await refrescar("Operación confirmada. Pulsa Actualizar para volver a consultar el estado de caja.");
                if (!aviso.textContent) mensaje.focus();
            } else if (status === 409 && datos.error === "clave_en_conflicto") {
                intento.conflicto = true;
                sessionStorage.setItem(claveLocal(operacion), JSON.stringify(intento));
                avisar("La clave corresponde a otros datos. Revisa los registros antes de resolver el intento.");
            } else if (rechazos.get(status)?.has(datos.error)) {
                retirar(operacion);
                if (operacion === "cierre" && datos.error === "resumen_cambiado") {
                    comparar = intento;
                    await refrescar("El cierre fue rechazado porque cambió el resumen. Pulsa Actualizar para revisar y confirmar nuevamente.");
                } else {
                    avisar(datos.mensaje || "El servidor rechazó la operación.");
                    if (["caja_abierta", "caja_cerrada"].includes(datos.error)) {
                        requiereActualizar = true;
                        await refrescar("El estado de caja cambió. Pulsa Actualizar para consultarlo.");
                    }
                }
            } else {
                throw new Error("Resultado inconcluyente");
            }
        } catch {
            mensaje.textContent = "";
            avisar("Resultado sin confirmar. Usa Reintentar para recuperar la misma solicitud.");
        } finally {
            establecerOcupado(false);
        }
    }

    for (const formulario of formularios) {
        const operacion = formulario.dataset.operacion;
        const campo = formulario.querySelector("[data-maximo]");
        const texto = formulario.querySelector("textarea");
        const minimo = operacion === "movimiento" ? 1 : 0;
        campo.addEventListener("input", () => {
            campo.setCustomValidity("");
            if (campo === contado) {
                texto.setCustomValidity("");
                mostrarDiferencia();
            }
        });
        texto.addEventListener("input", () => texto.setCustomValidity(""));
        campo.addEventListener("blur", () => {
            const importe = leerImporte(campo, minimo);
            if (importe !== null) campo.value = numero.format(importe);
        });
        formulario.addEventListener("submit", evento => {
            evento.preventDefault();
            if (formulario.querySelector("fieldset").disabled) return;
            const importe = leerImporte(campo, minimo);
            if (importe === null) {
                campo.setCustomValidity(`Ingresa un entero entre ${numero.format(minimo)} y ${numero.format(Number(campo.dataset.maximo))} CLP.`);
                campo.reportValidity();
                return;
            }
            const nota = recortar(texto.value);
            if ((texto.required && !nota) || nota.length > Number(texto.maxLength) || nota.includes("\0")) {
                texto.setCustomValidity("Ingresa un texto válido para continuar.");
                texto.reportValidity();
                return;
            }
            avisar("");
            mensaje.textContent = "";
            if (operacion === "apertura") {
                guardar(operacion, {efectivo_inicial: importe, observaciones: nota}, null);
            } else if (operacion === "movimiento") {
                const tipo = formulario.elements.tipo.value;
                guardar(tipo, {tipo, importe, motivo: nota}, estado.id);
            } else {
                propuesta = {
                    datos: {efectivo_contado: importe, observaciones: nota, huella: estado.huella},
                    sesion: estado.id,
                    metricas: estado.metricas,
                };
                const diferencia = diferenciaActual();
                elemento("confirmacion-importes").textContent = `Sesión #${estado.id} · Contado ${moneda.format(importe)} · `
                    + `${clasificaciones[clasificar(diferencia)]} ${moneda.format(diferencia)}.`;
                dialogo.showModal();
            }
        });
    }

    elemento("volver")?.addEventListener("click", () => dialogo.close());
    elemento("confirmar")?.addEventListener("click", () => {
        const cierre = propuesta;
        dialogo.close();
        guardar("cierre", cierre.datos, cierre.sesion, cierre.metricas);
    });
    elemento("actualizar").addEventListener("click", actualizar);
    window.addEventListener("pagehide", evento => {
        if (evento.persisted) raiz.hidden = true;
    });
    window.addEventListener("pageshow", evento => {
        if (evento.persisted) window.location.reload();
    });
    cargarPendientes();
    mostrarEstado();
    mostrarPendientes();
}

document.querySelectorAll("[data-gestion-caja]").forEach(montarCaja);
