import {uuidV4} from "./solicitud-financiera.js";

const moneda = new Intl.NumberFormat("es-CL", {style: "currency", currency: "CLP"});
const enteroCL = new Intl.NumberFormat("es-CL");
const fechaCL = new Intl.DateTimeFormat("es-CL", {
    dateStyle: "medium", timeStyle: "short", timeZone: "America/Santiago",
});
const metodos = new Map([["efectivo", "Efectivo"], ["tarjeta", "Tarjeta"], ["transferencia", "Transferencia"], ["credito", "Fiado"]]);
const MAX_MONTO = 999_999_999_999;
const MAX_SUBTOTAL = 9_999_999_999;
const MAX_LINEAS = 100;
const MAX_CANTIDAD = 1_000_000;
const UUID_V4 = /^[\da-f]{8}-[\da-f]{4}-4[\da-f]{3}-[89ab][\da-f]{3}-[\da-f]{12}$/i;
const rechazosDefinitivos = new Map([
    [400, new Set([
        "json_invalido", "entero_invalido", "clave_invalida", "items_invalidos", "item_invalido",
        "producto_duplicado", "modalidad_invalida", "campos_invalidos", "metodo_pago_invalido",
        "efectivo_insuficiente", "monto_pago_inexacto",
        "fecha_invalida", "texto_invalido", "abono_inicial_invalido",
    ])],
    [409, new Set(["cliente_no_elegible", "limite_credito_excedido", "cuenta_inconsistente"])],
    [413, new Set(["payload_demasiado_grande"])],
    [415, new Set(["tipo_de_contenido_invalido"])],
]);

function enteroPositivo(valor, maximo) {
    return Number.isSafeInteger(valor) && valor > 0 && valor <= maximo;
}

function montoCL(texto) {
    texto = texto.trim();
    if (!/^(?:\d+|\d{1,3}(?:\.\d{3})+)$/.test(texto)) return null;
    const monto = Number(texto.replaceAll(".", ""));
    return enteroPositivo(monto, MAX_MONTO) ? monto : null;
}

function subtotalLinea(linea, precio = linea.precio) {
    const subtotal = linea.cantidad * precio;
    return enteroPositivo(subtotal, MAX_SUBTOTAL) ? subtotal : null;
}

function datosRecuperables(datos) {
    if (!datos || !metodos.has(datos.metodo_pago)) return false;
    if (datos.metodo_pago === "credito") {
        if (!enteroPositivo(datos.cliente_id, Number.MAX_SAFE_INTEGER)
            || (datos.fecha_vencimiento !== null && (typeof datos.fecha_vencimiento !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(datos.fecha_vencimiento)))
            || typeof datos.notas !== "string" || ("monto_recibido" in datos && datos.monto_recibido !== 0)) return false;
    } else if ("monto_recibido" in datos && !enteroPositivo(datos.monto_recibido, MAX_MONTO)) return false;
    if (datos.modalidad === "rapida") return enteroPositivo(datos.monto, MAX_MONTO);
    return datos.modalidad === "detallada" && Array.isArray(datos.items)
        && datos.items.length > 0 && datos.items.length <= MAX_LINEAS
        && datos.items.every(item => item && enteroPositivo(item.producto_id, Number.MAX_SAFE_INTEGER)
            && enteroPositivo(item.precio_visto, MAX_SUBTOTAL)
            && enteroPositivo(item.cantidad, MAX_CANTIDAD));
}

function confirmacionValida(venta, status, usuario, solicitud) {
    const coincide = venta && String(venta.usuario_id) === usuario && venta.modalidad === solicitud.modalidad
        && venta.metodo_pago === solicitud.metodo_pago && venta.repetida === (status === 200)
        && typeof venta.numero_venta === "string" && venta.numero_venta.length > 0
        && typeof venta.fecha === "string" && Number.isFinite(Date.parse(venta.fecha))
        && enteroPositivo(venta.total, MAX_MONTO);
    if (!coincide) return false;
    if (solicitud.metodo_pago === "credito") {
        const total = solicitud.monto ?? solicitud.items.reduce((suma, item) => suma + item.precio_visto * item.cantidad, 0);
        return enteroPositivo(venta.id, Number.MAX_SAFE_INTEGER) && venta.total === total && venta.es_credito === true
            && venta.cliente_id === solicitud.cliente_id && enteroPositivo(venta.cuenta_id, Number.MAX_SAFE_INTEGER)
            && enteroPositivo(venta.sesion_caja_id, Number.MAX_SAFE_INTEGER) && venta.monto_recibido === 0 && venta.cambio === 0;
    }
    return enteroPositivo(venta.monto_recibido, MAX_MONTO)
        && Number.isSafeInteger(venta.cambio) && venta.cambio >= 0 && venta.cambio <= MAX_MONTO;
}

function montarPuntoVenta(raiz) {
    const elemento = nombre => raiz.querySelector(`#pos-${nombre}`);
    const formulario = elemento("formulario");
    const monto = elemento("monto");
    const recibido = elemento("recibido");
    const registrar = elemento("registrar");
    const edicion = elemento("edicion");
    const pago = elemento("pago");
    const error = elemento("error");
    const estado = elemento("estado");
    const lineas = new Map();
    const bloqueBusqueda = raiz.querySelector("[data-buscador-manual]");
    const componenteBusqueda = bloqueBusqueda.querySelector("[data-buscador-productos]");
    const consulta = componenteBusqueda.querySelector("[data-consulta]");
    const usuario = raiz.dataset.usuario;
    const panelFiado = elemento("fiado");
    const almacenamiento = `stockex.pos.pendiente.v1.${usuario}`;
    let buscador, cargaBuscador;
    let fiado, cargaFiado, restauracionFiado;
    let pendiente = null, claveEdicion = null, preciosNuevos = null;
    let enviando = false, revisarClave = false;
    let cajaAbierta = raiz.dataset.cajaAbierta === "true";

    const modalidad = () => formulario.elements.modalidad.value;
    const metodo = () => formulario.elements.metodo.value;
    const enEfectivo = () => metodo() === "efectivo";
    const bloqueado = () => Boolean(pendiente || preciosNuevos || revisarClave);
    const nombreLinea = linea => linea.nombre ?? `Producto #${linea.id}`;

    function avisar(texto = "", destino) {
        error.textContent = texto;
        destino?.focus();
    }

    function totalVisual() {
        if (modalidad() === "rapida") return montoCL(monto.value);
        let total = 0;
        for (const linea of lineas.values()) {
            const subtotal = subtotalLinea(linea);
            if (subtotal === null || linea.indisponible) return null;
            total += subtotal;
        }
        return total;
    }

    function mostrarTotales() {
        const total = totalVisual();
        const caja = enEfectivo();
        const pagoExacto = !recibido.value.trim();
        const importeRecibido = pagoExacto ? total : montoCL(recibido.value);
        const diferencia = total === null || importeRecibido === null ? null : importeRecibido - total;
        const vuelto = elemento("vuelto");
        elemento("total").textContent = total === null && modalidad() === "detallada" ? "—" : moneda.format(total ?? 0);
        elemento("caja").hidden = !caja;
        if (panelFiado) {
            panelFiado.hidden = metodo() !== "credito";
            if (!panelFiado.hidden) {
                cargarFiado();
                fiado?.actualizar(total);
            } else fiado?.cancelarBusqueda();
        }
        vuelto.textContent = diferencia === null ? "—"
            : diferencia < 0 ? `Faltan ${moneda.format(-diferencia)}` : moneda.format(diferencia);
        vuelto.parentElement.classList.toggle("invalido", diferencia < 0);
    }

    function mostrarEstado() {
        edicion.disabled = pago.disabled = bloqueado();
        bloqueBusqueda.inert = bloqueado();
        registrar.disabled = enviando || revisarClave || Boolean(preciosNuevos) || (!cajaAbierta && !pendiente);
        registrar.textContent = enviando ? "Registrando…" : pendiente ? "Reintentar registro" : "Registrar venta";
        elemento("atajo").hidden = enviando || bloqueado() || !cajaAbierta;
        formulario.setAttribute("aria-busy", String(enviando));
        elemento("estado-caja").textContent = cajaAbierta ? "Caja abierta" : "Caja cerrada";
        elemento("caja-cerrada").hidden = cajaAbierta;
    }

    const actualizarCaja = elemento("actualizar-caja");
    actualizarCaja.hidden = false;
    actualizarCaja.addEventListener("click", async () => {
        actualizarCaja.disabled = true;
        try {
            const respuesta = await fetch(raiz.dataset.estadoCaja, {
                credentials: "same-origin", redirect: "error", signal: AbortSignal.timeout(12_000),
                headers: {"X-Stockex-Account": usuario},
            });
            if (!respuesta.ok) throw new Error("Consulta rechazada");
            const datos = await respuesta.json();
            if (typeof datos.abierta !== "boolean") throw new Error("Estado desconocido");
            cajaAbierta = datos.abierta;
            avisar();
            mostrarEstado();
        } catch {
            avisar("No se pudo consultar el estado de caja. Comprueba tu conexión o vuelve a abrir el POS.", error);
        } finally {
            actualizarCaja.disabled = false;
        }
    });

    function enfocarEntrada() {
        (modalidad() === "rapida" ? monto : consulta).focus();
    }

    function cargarBuscador() {
        if (cargaBuscador) return;
        componenteBusqueda.querySelector("[data-estado]").textContent = "Cargando buscador…";
        cargaBuscador = import(raiz.dataset.moduloBuscador).then(({montarBuscador}) => {
            buscador = montarBuscador(componenteBusqueda, {enlaceDetalle: false, limpiarTrasElegir: true});
        }).catch(() => {
            componenteBusqueda.querySelector("[data-estado]").textContent =
                "No se pudo cargar el buscador. Vuelve a abrir el punto de venta.";
            elemento("sesion").hidden = false;
            cargaBuscador = null;
        });
    }

    function cargarFiado() {
        if (cargaFiado) return;
        cargaFiado = import(panelFiado.dataset.modulo).then(({montarFiado}) => {
            fiado = montarFiado(raiz, usuario);
            if (restauracionFiado) fiado.restaurar(...restauracionFiado);
            fiado.actualizar(totalVisual());
        }).catch(() => {
            avisar("No se pudo cargar el buscador de clientes. Vuelve a intentar.");
            cargaFiado = null;
        });
    }

    function mostrarModalidad() {
        const rapida = modalidad() === "rapida";
        elemento("rapida").hidden = !rapida;
        elemento("detallada").hidden = rapida;
        if (!rapida) cargarBuscador();
        mostrarTotales();
    }

    function actualizarLinea(linea) {
        const nombre = nombreLinea(linea);
        const {fila, precio, indisponible} = linea;
        const subtotal = subtotalLinea(linea);
        fila.querySelector("[data-nombre]").textContent = nombre;
        fila.querySelector("[data-indisponible]").hidden = !indisponible;
        fila.querySelector("[data-precio]").textContent = moneda.format(precio);
        fila.querySelector("[data-subtotal]").textContent = subtotal === null ? "—" : moneda.format(subtotal);
        fila.querySelector("[data-quitar]").setAttribute("aria-label", `Quitar ${nombre}`);
        linea.entrada.setAttribute("aria-label", `Cantidad de ${nombre}`);
        linea.entrada.setAttribute("aria-invalid", String(subtotal === null));
    }

    function mostrarLineas() {
        elemento("vacio").hidden = lineas.size > 0;
        elemento("columnas").hidden = lineas.size === 0;
        mostrarTotales();
    }

    function agregarLinea({id, nombre = null, precio, cantidad}) {
        const fila = elemento("plantilla-linea").content.firstElementChild.cloneNode(true);
        const entrada = fila.querySelector("[data-cantidad]");
        const linea = {id, nombre, precio, cantidad, fila, entrada, indisponible: false};
        entrada.value = cantidad;
        entrada.addEventListener("input", () => {
            const valor = /^\d+$/.test(entrada.value) ? Number(entrada.value) : null;
            linea.cantidad = enteroPositivo(valor, MAX_CANTIDAD) ? valor : null;
            actualizarLinea(linea);
            mostrarTotales();
        });
        fila.querySelector("[data-quitar]").addEventListener("click", () => {
            lineas.delete(id);
            fila.remove();
            mostrarLineas();
            consulta.focus();
        });
        lineas.set(id, linea);
        elemento("lineas").append(fila);
        actualizarLinea(linea);
    }

    componenteBusqueda.addEventListener("catalogo-actualizado", () => {
        for (const linea of lineas.values()) {
            if (linea.nombre) continue;
            linea.nombre = buscador?.productoPorId(linea.id)?.nombre ?? null;
            actualizarLinea(linea);
        }
        if (preciosNuevos) mostrarPrecios();
    });

    componenteBusqueda.addEventListener("producto-seleccionado", ({detail: producto}) => {
        if (bloqueado()) return;
        avisar();
        const linea = lineas.get(producto.id);
        if (!enteroPositivo(producto.id, Number.MAX_SAFE_INTEGER) || !enteroPositivo(producto.precio, MAX_SUBTOTAL)) {
            avisar("Este producto no tiene un precio válido para la venta.");
        } else if (linea?.indisponible) {
            avisar("Quita el producto no disponible antes de volver a agregarlo.");
        } else if (linea) {
            const siguiente = (linea.cantidad ?? 0) + 1;
            if (siguiente > MAX_CANTIDAD) {
                avisar("La cantidad máxima por producto es 1.000.000.");
            } else {
                linea.cantidad = siguiente;
                linea.entrada.value = siguiente;
                actualizarLinea(linea);
            }
        } else if (lineas.size === MAX_LINEAS) {
            avisar("La venta admite hasta 100 productos distintos.");
        } else {
            agregarLinea({...producto, cantidad: 1});
        }
        mostrarLineas();
        consulta.focus();
    });

    function invalidar(texto, control) {
        control?.setAttribute("aria-invalid", "true");
        avisar(texto, control ?? error);
        return null;
    }

    function armarDatos() {
        const datos = {modalidad: modalidad(), metodo_pago: metodo()};
        const total = totalVisual();
        if (datos.modalidad === "rapida") {
            if (total === null) return invalidar("Ingresa un monto entero positivo en CLP.", monto);
            datos.monto = total;
        } else {
            if (!lineas.size) {
                avisar("Agrega al menos un producto.", consulta);
                return null;
            }
            datos.items = [];
            for (const linea of lineas.values()) {
                if (linea.indisponible) {
                    avisar("Quita los productos no disponibles para continuar.", linea.fila.querySelector("[data-quitar]"));
                    return null;
                }
                if (subtotalLinea(linea) === null) {
                    return invalidar("Revisa la cantidad y el subtotal de la línea.", linea.entrada);
                }
                datos.items.push({producto_id: linea.id, cantidad: linea.cantidad, precio_visto: linea.precio});
            }
        }
        if (!enteroPositivo(total, MAX_MONTO)) return invalidar("El total supera el importe permitido.");
        if (datos.metodo_pago === "credito") {
            if (!fiado) {
                cargarFiado();
                return invalidar("Espera a que se cargue el buscador de clientes.");
            }
            const campos = fiado.campos(invalidar);
            if (!campos) return null;
            Object.assign(datos, campos);
        }
        if (enEfectivo() && recibido.value.trim()) {
            const efectivo = montoCL(recibido.value);
            if (efectivo === null) return invalidar("Ingresa el efectivo recibido como un entero positivo.", recibido);
            if (efectivo < total) return invalidar("El efectivo recibido es menor que el total.", recibido);
            datos.monto_recibido = efectivo;
        }
        return datos;
    }

    function guardarIntento(datos) {
        try {
            const intento = {clave: claveEdicion ?? uuidV4(), cuerpo: JSON.stringify(datos)};
            if (datos.metodo_pago === "credito") Object.assign(intento, {usuario, cliente: fiado.cliente()});
            sessionStorage.setItem(almacenamiento, JSON.stringify(intento));
            pendiente = intento;
            return true;
        } catch {
            avisar("No se pudo guardar el intento en esta pestaña. Habilita el almacenamiento de sesión.", error);
            return false;
        }
    }

    function retirarPendiente() {
        // El registro local sólo se elimina después de una respuesta definitiva o de una revisión explícita.
        sessionStorage.removeItem(almacenamiento);
        pendiente = null;
    }

    function recuperarIntento() {
        try {
            const guardado = sessionStorage.getItem(almacenamiento);
            if (!guardado) return;
            const intento = JSON.parse(guardado);
            const datos = JSON.parse(intento.cuerpo);
            if ((intento.usuario !== undefined && intento.usuario !== usuario)
                || !UUID_V4.test(intento.clave) || !datosRecuperables(datos)) throw new Error("Intento inválido");
            pendiente = {clave: intento.clave, cuerpo: intento.cuerpo};
            elemento(`modo-${datos.modalidad}`).checked = true;
            const controlMetodo = elemento(datos.metodo_pago);
            if (controlMetodo) controlMetodo.checked = true;
            if (datos.metodo_pago === "credito") restauracionFiado = [datos, intento.cliente];
            monto.value = datos.monto === undefined ? "" : enteroCL.format(datos.monto);
            recibido.value = datos.monto_recibido === undefined ? "" : enteroCL.format(datos.monto_recibido);
            for (const item of datos.items ?? []) {
                agregarLinea({id: item.producto_id, precio: item.precio_visto, cantidad: item.cantidad});
            }
            avisar("Hay una venta pendiente. Reintenta para comprobar su resultado.");
        } catch {
            mostrarConflicto("No se pudo leer el intento guardado.");
        }
    }

    function limpiarVenta() {
        claveEdicion = null;
        restauracionFiado = null;
        fiado?.limpiar();
        monto.value = recibido.value = consulta.value = "";
        monto.removeAttribute("aria-invalid");
        recibido.removeAttribute("aria-invalid");
        lineas.clear();
        elemento("lineas").replaceChildren();
        mostrarLineas();
    }

    function confirmar(venta) {
        elemento("venta-numero").textContent = venta.numero_venta;
        const fecha = elemento("venta-fecha");
        fecha.dateTime = venta.fecha;
        fecha.textContent = fechaCL.format(new Date(venta.fecha));
        elemento("venta-total").textContent = moneda.format(venta.total);
        elemento("venta-metodo").textContent = metodos.get(venta.metodo_pago);
        elemento("venta-recibido").textContent = moneda.format(venta.monto_recibido);
        elemento("venta-vuelto").textContent = moneda.format(venta.cambio);
        const efectivo = venta.metodo_pago === "efectivo";
        elemento("venta-efectivo").hidden = elemento("venta-cambio").hidden = !efectivo;
        elemento("venta-fiada").hidden = venta.metodo_pago !== "credito";
        elemento("venta-cuenta").textContent = venta.cuenta_id ? `#${venta.cuenta_id}` : "";
        elemento("ultima").hidden = false;
        estado.textContent = venta.repetida ? "Venta recuperada. Ya estaba registrada." : "Venta registrada.";
        limpiarVenta();
    }

    function mostrarPrecios() {
        const lista = elemento("lista-precios");
        lista.replaceChildren();
        let total = 0, importesValidos = true;
        for (const linea of lineas.values()) {
            const nuevoPrecio = preciosNuevos.get(linea.id);
            const subtotal = subtotalLinea(linea, nuevoPrecio ?? linea.precio);
            if (subtotal === null) importesValidos = false;
            else total += subtotal;
            if (nuevoPrecio === undefined) continue;
            const item = document.createElement("li");
            item.textContent = `${nombreLinea(linea)} · Anterior ${moneda.format(linea.precio)} · Vigente ${moneda.format(nuevoPrecio)}`;
            lista.append(item);
        }
        elemento("total-actualizado").textContent = importesValidos ? moneda.format(total) : "Fuera del límite";
        elemento("precios").hidden = false;
    }

    function mostrarConflicto(mensaje) {
        revisarClave = true;
        elemento("clave-conflicto").hidden = false;
        avisar(mensaje);
    }

    function resolverRechazo(status, datos) {
        if (status === 409 && datos.error === "clave_en_conflicto") {
            mostrarConflicto("La clave está asociada a otra solicitud. Revisa el historial antes de continuar.");
            return elemento("cerrar-intento");
        }

        const conservarClave = pendiente.clave;
        if (status === 409 && datos.error === "caja_no_abierta") {
            retirarPendiente();
            claveEdicion = conservarClave;
            cajaAbierta = false;
            avisar("La caja está cerrada. La venta no se registró y sus datos se conservan.");
            return error;
        }
        if (status === 409 && datos.error === "precio_cambiado"
            && Array.isArray(datos.productos) && datos.productos.length
            && datos.productos.every(p => lineas.has(p?.producto_id) && enteroPositivo(p.precio_vigente, MAX_SUBTOTAL))) {
            retirarPendiente();
            claveEdicion = conservarClave;
            preciosNuevos = new Map(datos.productos.map(p => [p.producto_id, p.precio_vigente]));
            mostrarPrecios();
            return elemento("aplicar-precios");
        }

        const ids = datos.error === "precio_catalogo_invalido" ? [datos.producto_id] : datos.producto_ids;
        if (status === 409 && ["productos_no_disponibles", "precio_catalogo_invalido"].includes(datos.error)
            && Array.isArray(ids) && ids.length && ids.every(id => lineas.has(id))) {
            retirarPendiente();
            claveEdicion = conservarClave;
            for (const id of ids) {
                lineas.get(id).indisponible = true;
                actualizarLinea(lineas.get(id));
            }
            mostrarTotales();
            avisar("Quita las líneas no disponibles para continuar. Los demás productos se conservan.");
            return lineas.get(ids[0]).fila.querySelector("[data-quitar]");
        }

        if (rechazosDefinitivos.get(status)?.has(datos.error)) {
            retirarPendiente();
            claveEdicion = conservarClave;
            avisar(typeof datos.mensaje === "string" ? datos.mensaje : "El servidor rechazó los datos de la venta.");
            return error;
        }
        throw new Error("Resultado desconocido");
    }

    async function enviarVenta(datos) {
        if (enviando || revisarClave || preciosNuevos || (!cajaAbierta && !pendiente)) return;
        estado.textContent = "";
        elemento("sesion").hidden = true;
        avisar();
        if (!pendiente && (!datos || !guardarIntento(datos))) return;

        enviando = true;
        mostrarEstado();
        estado.textContent = "Registrando venta…";
        const control = new AbortController();
        const limite = window.setTimeout(() => control.abort(), 12_000);
        let destino = registrar;
        let registrada = false;
        try {
            const respuesta = await fetch(raiz.dataset.registro, {
                method: "POST",
                credentials: "same-origin",
                redirect: "manual",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": document.querySelector('meta[name="csrf-token"]').content,
                    "Idempotency-Key": pendiente.clave,
                    "X-Stockex-Account": usuario,
                },
                body: pendiente.cuerpo,
                signal: control.signal,
            });
            estado.textContent = "";
            if (respuesta.type === "opaqueredirect" || respuesta.status === 401 || respuesta.status === 403) {
                elemento("sesion").hidden = false;
                avisar("La sesión venció o el acceso fue rechazado. Vuelve a abrir el punto de venta con la misma cuenta.");
            } else if (respuesta.status === 503) {
                avisar("El registro está ocupado. Reintenta para comprobar si la venta se registró.");
            } else if (respuesta.headers.get("Content-Type")?.includes("application/json")) {
                const datos = await respuesta.json();
                const status = respuesta.status;
                if ([200, 201].includes(status)
                    && confirmacionValida(datos, status, usuario, JSON.parse(pendiente.cuerpo))) {
                    retirarPendiente();
                    confirmar(datos);
                    registrada = true;
                } else {
                    destino = resolverRechazo(status, datos);
                }
            } else {
                throw new Error("Respuesta inesperada");
            }
        } catch {
            estado.textContent = "";
            avisar("No se pudo verificar el resultado. Reintenta para recuperar la misma venta.");
        } finally {
            window.clearTimeout(limite);
            enviando = false;
            mostrarEstado();
            if (registrada) enfocarEntrada();
            else destino.focus();
        }
    }

    formulario.addEventListener("submit", evento => {
        evento.preventDefault();
        if (enviando || revisarClave || preciosNuevos || (!cajaAbierta && !pendiente)) return;
        if (pendiente) return enviarVenta();
        avisar();
        const datos = armarDatos();
        if (!datos) return;
        if (datos.metodo_pago === "credito") {
            fiado.revisar(datos, totalVisual(), () => enviarVenta(datos));
        } else enviarVenta(datos);
    });

    formulario.addEventListener("keydown", evento => {
        if (evento.key === "Escape" && evento.target === consulta) evento.stopPropagation();
        if (evento.key !== "Enter") return;
        const enBusqueda = bloqueBusqueda.contains(evento.target);
        const atajo = evento.ctrlKey && !evento.shiftKey && !evento.altKey && !evento.metaKey;
        if (!atajo && evento.target.closest("button[type=button], textarea")) return;
        evento.preventDefault();
        if (atajo && !enBusqueda && !evento.repeat && !evento.isComposing && !bloqueado()) formulario.requestSubmit();
    });
    registrar.addEventListener("click", evento => {
        if (evento.detail > 1) evento.preventDefault();
    });

    formulario.addEventListener("change", ({target}) => {
        if (target.name === "modalidad") {
            avisar();
            mostrarModalidad();
            enfocarEntrada();
        } else if (target.name === "metodo") {
            avisar();
            mostrarTotales();
        }
    });

    for (const entrada of [monto, recibido]) {
        entrada.addEventListener("input", () => {
            entrada.removeAttribute("aria-invalid");
            mostrarTotales();
        });
        entrada.addEventListener("blur", () => {
            const valor = montoCL(entrada.value);
            if (valor !== null) entrada.value = enteroCL.format(valor);
        });
    }

    elemento("aplicar-precios").addEventListener("click", () => {
        for (const [id, precio] of preciosNuevos) {
            const linea = lineas.get(id);
            linea.precio = precio;
            actualizarLinea(linea);
        }
        preciosNuevos = null;
        elemento("precios").hidden = true;
        mostrarTotales();
        mostrarEstado();
        const total = totalVisual();
        if (total === null) {
            avisar("El subtotal de una línea supera el importe permitido. Revisa la cantidad.", error);
        } else if (enEfectivo() && recibido.value.trim() && (montoCL(recibido.value) ?? 0) < total) {
            invalidar("Corrige el efectivo recibido para cubrir el nuevo total.", recibido);
        } else {
            estado.textContent = "Precios actualizados. Revisa el total y registra la venta.";
            registrar.focus();
        }
    });

    elemento("cerrar-intento").addEventListener("click", () => {
        try {
            retirarPendiente();
        } catch {
            avisar("El almacenamiento de esta pestaña sigue sin estar disponible.", error);
            return;
        }
        revisarClave = false;
        elemento("clave-conflicto").hidden = true;
        avisar();
        limpiarVenta();
        mostrarEstado();
        enfocarEntrada();
    });

    // Si el navegador conserva la página en su historial, vuelve a validar la cuenta antes de mostrarla.
    window.addEventListener("pagehide", evento => {
        if (evento.persisted) raiz.hidden = true;
    });
    window.addEventListener("pageshow", evento => {
        if (evento.persisted) window.location.reload();
    });

    recuperarIntento();
    mostrarModalidad();
    mostrarLineas();
    mostrarEstado();
    if (revisarClave) elemento("cerrar-intento").focus();
    else if (pendiente) registrar.focus();
    else enfocarEntrada();
}

document.querySelectorAll("[data-punto-venta]").forEach(montarPuntoVenta);
