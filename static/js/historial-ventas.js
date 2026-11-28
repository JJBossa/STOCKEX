const historial = document.querySelector("[data-historial]");

if (historial) {
    const estado = historial.querySelector("[data-historial-estado]");
    let solicitud;

    async function actualizar(url, {navegacion = true, foco = "hist-resultados"} = {}) {
        solicitud?.abort();
        const control = new AbortController();
        solicitud = control;
        historial.setAttribute("aria-busy", "true");
        estado.classList.add("visually-hidden");
        estado.textContent = "Actualizando historial…";
        try {
            const respuesta = await fetch(url, {
                headers: {"X-Historial-Parcial": "1"},
                credentials: "same-origin",
                cache: "no-store",
                signal: control.signal,
            });
            if (respuesta.redirected || !respuesta.ok) {
                if (!control.signal.aborted) window.location.assign(respuesta.url || url);
                return;
            }
            const documento = new DOMParser().parseFromString(await respuesta.text(), "text/html");
            const contenido = documento.querySelector("[data-historial-contenido]");
            if (!contenido) throw new Error("Respuesta de historial inesperada");
            if (control.signal.aborted) return;
            historial.querySelector("[data-historial-contenido]").replaceWith(contenido);
            if (navegacion && url.href !== window.location.href) history.pushState(null, "", url);
            estado.textContent = "Historial actualizado.";
            if (foco) document.getElementById(foco)?.focus({preventScroll: true});
        } catch {
            if (control.signal.aborted) return;
            estado.classList.remove("visually-hidden");
            estado.textContent = "No se pudo actualizar. Vuelve a usar el botón Actualizar.";
            if (!navegacion) window.location.reload();
        } finally {
            if (solicitud === control) {
                historial.removeAttribute("aria-busy");
                solicitud = null;
            }
        }
    }

    historial.addEventListener("submit", evento => {
        if (!evento.target.matches("[data-historial-filtros]")) return;
        evento.preventDefault();
        const url = new URL(evento.target.action);
        url.search = new URLSearchParams(new FormData(evento.target));
        const foco = document.activeElement.matches('input[type="radio"]') ? document.activeElement.id : undefined;
        actualizar(url, {foco});
    });

    historial.addEventListener("change", evento => {
        const periodo = evento.target;
        if (periodo.name !== "periodo" || !periodo.checked) return;
        if (periodo.value === "personalizado") {
            periodo.form.elements.fecha_desde.focus();
        } else {
            periodo.form.elements.fecha_desde.value = "";
            periodo.form.elements.fecha_hasta.value = "";
            periodo.form.requestSubmit();
        }
    });

    historial.addEventListener("click", evento => {
        const enlace = evento.target.closest("a[data-historial-enlace]");
        if (!enlace || evento.button !== 0 || evento.ctrlKey || evento.metaKey || evento.shiftKey || evento.altKey) return;
        evento.preventDefault();
        actualizar(new URL(enlace.href), {foco: enlace.id || "hist-resultados"});
    });

    window.addEventListener("popstate", () => {
        actualizar(new URL(window.location.href), {navegacion: false, foco: null});
    });
}
