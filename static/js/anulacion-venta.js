(() => {
    const formulario = document.querySelector("[data-form-anulacion]");
    if (!formulario) return;
    const confirmar = formulario.querySelector("button[type=submit]");
    const motivo = formulario.elements.motivo;
    const estado = formulario.querySelector("[data-estado-anulacion]");
    const revisar = formulario.querySelector("[data-revisar-anulacion]");
    let enviando = false;
    let requiereComprobacion = false;

    function actualizarControles() {
        confirmar.disabled = motivo.readOnly = enviando || requiereComprobacion;
        formulario.setAttribute("aria-busy", String(enviando));
        revisar.hidden = !requiereComprobacion;
        revisar.setAttribute("aria-disabled", String(enviando));
    }

    formulario.addEventListener("submit", async evento => {
        evento.preventDefault();
        if (enviando || requiereComprobacion) return;
        enviando = true;
        actualizarControles();
        estado.textContent = "Confirmando la anulación…";
        try {
            const respuesta = await fetch(formulario.action, {
                method: "POST",
                body: new FormData(formulario),
                headers: {Accept: "application/json"},
                redirect: "error",
                cache: "no-store",
                signal: AbortSignal.timeout(12_000),
            });
            const datos = await respuesta.json();
            if ([200, 201].includes(respuesta.status) && datos.cancelada === true &&
                datos.id === Number(formulario.dataset.venta)) {
                estado.textContent = "Anulación confirmada. Abriendo el detalle…";
                window.location.assign(revisar.href);
                return;
            }
            if (![400, 409, 503].includes(respuesta.status) || typeof datos.mensaje !== "string") {
                throw new Error("Resultado desconocido");
            }
            estado.textContent = datos.mensaje;
            requiereComprobacion = ["ya_anulada", "base_ocupada"].includes(datos.error);
        } catch {
            estado.textContent = "No se pudo confirmar el resultado. Comprueba el estado de la venta.";
            requiereComprobacion = true;
        }
        enviando = false;
        actualizarControles();
        if (requiereComprobacion) revisar.focus();
    });

    revisar.addEventListener("click", async evento => {
        if (evento.ctrlKey || evento.metaKey || evento.shiftKey || evento.altKey) return;
        evento.preventDefault();
        if (enviando) return;
        enviando = true;
        actualizarControles();
        estado.textContent = "Comprobando el estado…";
        try {
            const respuesta = await fetch(revisar.href, {
                cache: "no-store",
                redirect: "error",
                signal: AbortSignal.timeout(12_000),
            });
            if (!respuesta.ok) throw new Error("No se pudo consultar");
            const pagina = new DOMParser().parseFromString(await respuesta.text(), "text/html");
            const venta = pagina.querySelector("[data-estado-venta]")?.dataset.estadoVenta;
            if (venta === "anulada") {
                window.location.assign(revisar.href);
                return;
            }
            if (venta !== "vigente") throw new Error("Estado desconocido");
            requiereComprobacion = false;
            estado.textContent = "La venta sigue vigente. Puedes volver a confirmar.";
        } catch {
            estado.textContent = "No se pudo consultar la venta. Comprueba la conexión o abre el detalle en otra pestaña.";
        }
        enviando = false;
        actualizarControles();
        if (!requiereComprobacion) motivo.focus();
    });
})();
