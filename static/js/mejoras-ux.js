/**
 * Mejoras de UX/UI y Accesibilidad para STOCKEX
 */

// ===== ATAJOS DE TECLADO GLOBALES =====
document.addEventListener('keydown', function(e) {
    // Solo si no estamos escribiendo en un input/textarea
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') {
        // Permitir algunos atajos incluso en inputs
        if (e.key === 'Escape') {
            // Cerrar modales o limpiar búsqueda
            const modales = document.querySelectorAll('.modal.show');
            modales.forEach(modal => {
                const bsModal = bootstrap.Modal.getInstance(modal);
                if (bsModal) bsModal.hide();
            });
            
            // Limpiar búsqueda si está enfocado
            if (e.target.type === 'text' || e.target.type === 'search') {
                e.target.value = '';
                e.target.dispatchEvent(new Event('input'));
            }
        }
        return;
    }
    
    // Atajos globales (solo fuera de inputs)
    const key = e.key.toLowerCase();
    const ctrl = e.ctrlKey || e.metaKey;
    const shift = e.shiftKey;
    
    // Ctrl/Cmd + K: Buscar (focus en búsqueda)
    if (ctrl && key === 'k') {
        e.preventDefault();
        const searchInput = document.querySelector('input[type="text"][placeholder*="Buscar"], input[type="search"]');
        if (searchInput) {
            searchInput.focus();
            searchInput.select();
        }
    }
    
    // Ctrl/Cmd + /: Mostrar ayuda
    if (ctrl && key === '/') {
        e.preventDefault();
        const helpButton = document.getElementById('btn-ayuda-flotante');
        if (helpButton) helpButton.click();
    }
    
    // G + I: Ir a Inicio
    if (key === 'g' && !ctrl && !shift) {
        e.preventDefault();
        const inicioLink = document.querySelector('a[href="/"], a.navbar-brand');
        if (inicioLink) window.location.href = inicioLink.href;
    }
    
    // G + V: Ir a Ventas (si existe)
    if (key === 'v' && !ctrl && !shift && document.querySelector('a[href*="pos/"]')) {
        e.preventDefault();
        const ventasLink = document.querySelector('a[href*="pos/"]');
        if (ventasLink) window.location.href = ventasLink.href;
    }
    
    // G + D: Ir a Dashboard
    if (key === 'd' && !ctrl && !shift) {
        e.preventDefault();
        const dashboardLink = document.querySelector('a[href*="dashboard"]');
        if (dashboardLink) window.location.href = dashboardLink.href;
    }
    
    // Escape: Cerrar modales, limpiar filtros
    if (key === 'escape') {
        const modales = document.querySelectorAll('.modal.show');
        modales.forEach(modal => {
            const bsModal = bootstrap.Modal.getInstance(modal);
            if (bsModal) bsModal.hide();
        });
    }
});

// ===== BÚSQUEDA CON AUTOCOMPLETADO =====
function initAutocompletado() {
    const searchInputs = document.querySelectorAll('input[type="text"][placeholder*="Buscar"], input[type="search"]');
    
    searchInputs.forEach(input => {
        let timeoutId = null;
        let autocompleteContainer = null;
        
        // Crear contenedor de autocompletado
        function crearAutocompleteContainer() {
            if (autocompleteContainer) return autocompleteContainer;
            
            autocompleteContainer = document.createElement('div');
            autocompleteContainer.className = 'autocomplete-container position-absolute bg-white border rounded shadow-lg';
            autocompleteContainer.style.cssText = 'z-index: 1000; max-height: 300px; overflow-y: auto; display: none; width: 100%; margin-top: 8px; top: 100%;';
            input.parentElement.style.position = 'relative';
            input.parentElement.appendChild(autocompleteContainer);
            return autocompleteContainer;
        }
        
        // Obtener sugerencias
        async function obtenerSugerencias(query) {
            if (query.length < 2) return [];
            
            try {
                const response = await fetch(`/api/buscar-productos/?q=${encodeURIComponent(query)}`);
                if (response.ok) {
                    const data = await response.json();
                    return data.productos || [];
                }
            } catch (error) {
                console.error('Error al obtener sugerencias:', error);
            }
            return [];
        }
        
        // Mostrar sugerencias
        function mostrarSugerencias(sugerencias) {
            const container = crearAutocompleteContainer();
            
            if (sugerencias.length === 0) {
                container.style.display = 'none';
                return;
            }
            
            container.innerHTML = '';
            sugerencias.slice(0, 8).forEach(producto => {
                const item = document.createElement('div');
                item.className = 'autocomplete-item p-2 border-bottom cursor-pointer';
                item.style.cssText = 'cursor: pointer; transition: background 0.2s;';
                item.innerHTML = `
                    <div class="d-flex justify-content-between align-items-center">
                        <div>
                            <strong>${producto.nombre}</strong>
                            ${producto.sku ? `<br><small class="text-muted">SKU: ${producto.sku}</small>` : ''}
                        </div>
                        <div class="text-end">
                            <strong>$${producto.precio.toLocaleString()}</strong>
                            ${producto.stock > 0 ? 
                                `<span class="badge bg-success ms-2">${producto.stock} u.</span>` : 
                                `<span class="badge bg-danger ms-2">Sin stock</span>`}
                        </div>
                    </div>
                `;
                
                item.addEventListener('mouseenter', () => {
                    item.style.backgroundColor = '#f8f9fa';
                });
                item.addEventListener('mouseleave', () => {
                    item.style.backgroundColor = '';
                });
                
                item.addEventListener('click', () => {
                    input.value = producto.nombre;
                    container.style.display = 'none';
                    // Disparar búsqueda si hay un formulario
                    const form = input.closest('form');
                    if (form) {
                        form.submit();
                    }
                });
                
                container.appendChild(item);
            });
            
            container.style.display = 'block';
        }
        
        // Evento de input
        input.addEventListener('input', function() {
            const query = this.value.trim();
            
            clearTimeout(timeoutId);
            
            if (query.length < 2) {
                if (autocompleteContainer) autocompleteContainer.style.display = 'none';
                return;
            }
            
            timeoutId = setTimeout(async () => {
                const sugerencias = await obtenerSugerencias(query);
                mostrarSugerencias(sugerencias);
            }, 300);
        });
        
        // Ocultar al hacer clic fuera
        document.addEventListener('click', function(e) {
            if (!input.contains(e.target) && (!autocompleteContainer || !autocompleteContainer.contains(e.target))) {
                if (autocompleteContainer) autocompleteContainer.style.display = 'none';
            }
        });
        
        // Navegación con teclado en autocompletado
        input.addEventListener('keydown', function(e) {
            if (!autocompleteContainer || autocompleteContainer.style.display === 'none') return;
            
            const items = autocompleteContainer.querySelectorAll('.autocomplete-item');
            const currentIndex = Array.from(items).findIndex(item => item.style.backgroundColor === 'rgb(248, 249, 250)');
            
            if (e.key === 'ArrowDown') {
                e.preventDefault();
                const nextIndex = currentIndex < items.length - 1 ? currentIndex + 1 : 0;
                items.forEach((item, idx) => {
                    item.style.backgroundColor = idx === nextIndex ? '#f8f9fa' : '';
                });
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                const prevIndex = currentIndex > 0 ? currentIndex - 1 : items.length - 1;
                items.forEach((item, idx) => {
                    item.style.backgroundColor = idx === prevIndex ? '#f8f9fa' : '';
                });
            } else if (e.key === 'Enter' && currentIndex >= 0) {
                e.preventDefault();
                items[currentIndex].click();
            }
        });
    });
}

// ===== LAZY LOADING DE IMÁGENES =====
function initLazyLoading() {
    if ('IntersectionObserver' in window) {
        const imageObserver = new IntersectionObserver((entries, observer) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    const img = entry.target;
                    if (img.dataset.src) {
                        img.src = img.dataset.src;
                        img.classList.remove('lazy');
                        img.classList.add('loaded');
                        observer.unobserve(img);
                    }
                }
            });
        }, {
            rootMargin: '50px'
        });
        
        document.querySelectorAll('img.lazy, img[data-src]').forEach(img => {
            imageObserver.observe(img);
        });
    } else {
        // Fallback para navegadores antiguos
        document.querySelectorAll('img[data-src]').forEach(img => {
            img.src = img.dataset.src;
        });
    }
}

// ===== PAGINACIÓN EFICIENTE (MEJORADA) =====
function initInfiniteScroll() {
    // Solo activar si el usuario prefiere scroll infinito
    const preferInfiniteScroll = localStorage.getItem('preferInfiniteScroll') === 'true';
    if (!preferInfiniteScroll) return;
    
    const paginationContainer = document.querySelector('.pagination');
    if (!paginationContainer) return;
    
    const nextLink = paginationContainer.querySelector('a[href*="page="]');
    if (!nextLink) return;
    
    let loading = false;
    
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting && !loading && nextLink.href) {
                loading = true;
                nextLink.click(); // Simular click para cargar siguiente página
                loading = false;
            }
        });
    }, {
        rootMargin: '300px'
    });
    
    // Observar el último elemento de la lista
    const productGrid = document.querySelector('.row.g-3, .product-grid');
    if (productGrid && productGrid.children.length > 0) {
        const lastItem = productGrid.lastElementChild;
        if (lastItem) observer.observe(lastItem);
    }
}

// ===== NAVEGACIÓN POR TECLADO MEJORADA =====
function mejorarNavegacionTeclado() {
    // Mejorar navegación Tab
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Tab') {
            // Asegurar que los elementos interactivos sean accesibles
            const focusableElements = document.querySelectorAll(
                'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
            );
            
            // Agregar indicador visual de foco
            focusableElements.forEach(el => {
                el.addEventListener('focus', function() {
                    this.style.outline = '2px solid #0d6efd';
                    this.style.outlineOffset = '2px';
                });
                el.addEventListener('blur', function() {
                    this.style.outline = '';
                    this.style.outlineOffset = '';
                });
            });
        }
    });
}

// ===== CONTRASTE Y TAMAÑOS DE FUENTE AJUSTABLES =====
function initAccesibilidad() {
    // Crear controles de accesibilidad - en la esquina superior derecha, debajo del navbar
    const navbar = document.querySelector('.navbar');
    const navbarHeight = navbar ? navbar.offsetHeight : 60;
    
    const accesibilidadHTML = `
        <div id="accesibilidad-controls" class="position-fixed" style="top: ${navbarHeight + 10}px; right: 20px; z-index: 1040;">
            <div class="btn-group shadow-sm">
                <button class="btn btn-light btn-sm border" id="btn-aumentar-fuente" title="Aumentar tamaño de fuente">
                    <i class="bi bi-type-h1"></i>
                </button>
                <button class="btn btn-light btn-sm border" id="btn-disminuir-fuente" title="Disminuir tamaño de fuente">
                    <i class="bi bi-type"></i>
                </button>
                <button class="btn btn-light btn-sm border" id="btn-alto-contraste" title="Alto contraste">
                    <i class="bi bi-circle-half"></i>
                </button>
            </div>
        </div>
    `;
    
    document.body.insertAdjacentHTML('beforeend', accesibilidadHTML);
    
    // Tamaño de fuente
    let fontSize = parseInt(localStorage.getItem('fontSize')) || 100;
    document.documentElement.style.fontSize = fontSize + '%';
    
    document.getElementById('btn-aumentar-fuente').addEventListener('click', () => {
        fontSize = Math.min(fontSize + 10, 150);
        document.documentElement.style.fontSize = fontSize + '%';
        localStorage.setItem('fontSize', fontSize);
    });
    
    document.getElementById('btn-disminuir-fuente').addEventListener('click', () => {
        fontSize = Math.max(fontSize - 10, 80);
        document.documentElement.style.fontSize = fontSize + '%';
        localStorage.setItem('fontSize', fontSize);
    });
    
    // Alto contraste
    const altoContraste = localStorage.getItem('altoContraste') === 'true';
    if (altoContraste) {
        document.body.classList.add('alto-contraste');
    }
    
    document.getElementById('btn-alto-contraste').addEventListener('click', () => {
        document.body.classList.toggle('alto-contraste');
        localStorage.setItem('altoContraste', document.body.classList.contains('alto-contraste'));
    });
}

// ===== ARIA LABELS Y ACCESIBILIDAD =====
function mejorarARIA() {
    // Agregar ARIA labels a botones sin texto
    document.querySelectorAll('button:not([aria-label]):not([title])').forEach(btn => {
        const icon = btn.querySelector('i[class*="bi-"]');
        if (icon) {
            const iconClass = Array.from(icon.classList).find(c => c.startsWith('bi-'));
            if (iconClass) {
                btn.setAttribute('aria-label', iconClass.replace('bi-', '').replace('-', ' '));
            }
        }
    });
    
    // Agregar roles ARIA a elementos interactivos
    document.querySelectorAll('.dropdown-toggle').forEach(btn => {
        if (!btn.getAttribute('aria-haspopup')) {
            btn.setAttribute('aria-haspopup', 'true');
        }
    });
}

// ===== OCULTAR CONTROLES AL ABRIR MENÚS DESPLEGABLES =====
function initOcultarControlesEnDropdowns() {
    const accesibilidadControls = document.getElementById('accesibilidad-controls');
    if (!accesibilidadControls) return;
    
    // Detectar cuando se abre cualquier dropdown
    document.addEventListener('show.bs.dropdown', function(e) {
        accesibilidadControls.style.opacity = '0';
        accesibilidadControls.style.pointerEvents = 'none';
        accesibilidadControls.style.transition = 'opacity 0.2s ease';
    });
    
    // Mostrar de nuevo cuando se cierra
    document.addEventListener('hide.bs.dropdown', function(e) {
        setTimeout(() => {
            accesibilidadControls.style.opacity = '1';
            accesibilidadControls.style.pointerEvents = 'auto';
        }, 200); // Pequeño delay para que el dropdown se cierre primero
    });
    
    // También para modales
    document.addEventListener('show.bs.modal', function(e) {
        accesibilidadControls.style.opacity = '0';
        accesibilidadControls.style.pointerEvents = 'none';
    });
    
    document.addEventListener('hide.bs.modal', function(e) {
        setTimeout(() => {
            accesibilidadControls.style.opacity = '1';
            accesibilidadControls.style.pointerEvents = 'auto';
        }, 200);
    });
}

// ===== INICIALIZACIÓN =====
document.addEventListener('DOMContentLoaded', function() {
    initAutocompletado();
    initLazyLoading();
    initInfiniteScroll();
    mejorarNavegacionTeclado();
    initAccesibilidad();
    mejorarARIA();
    initOcultarControlesEnDropdowns();
    
    // Mostrar indicador de atajos de teclado
    console.log('%cSTOCKEX - Atajos de Teclado', 'color: #667eea; font-size: 16px; font-weight: bold;');
    console.log('Ctrl+K: Buscar | Ctrl+/: Ayuda | G+I: Inicio | G+V: Ventas | G+D: Dashboard | Esc: Cerrar');
});

