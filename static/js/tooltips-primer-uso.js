/**
 * Sistema de Tooltips y Indicadores de Primer Uso
 */

// ===== INICIALIZAR TOOLTIPS DE BOOTSTRAP =====
function initTooltips() {
    // Inicializar todos los tooltips
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl, {
            placement: 'top',
            trigger: 'hover focus'
        });
    });
    return tooltipTriggerList;
}

// ===== SISTEMA DE PRIMER USO =====
const PrimerUso = {
    // Verificar si es la primera vez que el usuario ve algo
    esPrimeraVez: function(feature) {
        const visto = localStorage.getItem(`primer_uso_${feature}`);
        return visto !== 'true';
    },
    
    // Marcar como visto
    marcarComoVisto: function(feature) {
        localStorage.setItem(`primer_uso_${feature}`, 'true');
    },
    
    // Mostrar mensaje de primer uso
    mostrarMensaje: function(feature, mensaje, posicion = 'top') {
        if (!this.esPrimeraVez(feature)) return;
        
        // Crear elemento de mensaje
        const mensajeDiv = document.createElement('div');
        mensajeDiv.className = 'primer-uso-mensaje alert alert-info alert-dismissible fade show position-fixed';
        mensajeDiv.style.cssText = `
            z-index: 1060;
            max-width: 350px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            animation: slideInPrimerUso 0.3s ease-out;
        `;
        
        // Posicionar según el parámetro
        if (posicion === 'top') {
            mensajeDiv.style.top = '80px';
            mensajeDiv.style.right = '20px';
        } else if (posicion === 'bottom') {
            mensajeDiv.style.bottom = '100px';
            mensajeDiv.style.right = '20px';
        } else if (posicion === 'center') {
            mensajeDiv.style.top = '50%';
            mensajeDiv.style.left = '50%';
            mensajeDiv.style.transform = 'translate(-50%, -50%)';
        }
        
        mensajeDiv.innerHTML = `
            <div class="d-flex align-items-start">
                <i class="bi bi-lightbulb-fill me-2" style="font-size: 1.2rem; color: #0dcaf0;"></i>
                <div class="flex-grow-1">
                    <strong>💡 Primera vez aquí?</strong>
                    <p class="mb-0 mt-1" style="font-size: 0.9rem;">${mensaje}</p>
                </div>
            </div>
            <button type="button" class="btn-close" data-bs-dismiss="alert" onclick="PrimerUso.marcarComoVisto('${feature}')"></button>
        `;
        
        document.body.appendChild(mensajeDiv);
        
        // Auto-cerrar después de 8 segundos
        setTimeout(() => {
            if (mensajeDiv.parentNode) {
                mensajeDiv.classList.remove('show');
                setTimeout(() => {
                    if (mensajeDiv.parentNode) {
                        mensajeDiv.remove();
                        this.marcarComoVisto(feature);
                    }
                }, 300);
            }
        }, 8000);
        
        // Marcar como visto al cerrar
        mensajeDiv.querySelector('.btn-close').addEventListener('click', () => {
            this.marcarComoVisto(feature);
        });
    }
};

// ===== MENSAJES DE PRIMER USO POR PÁGINA =====
function mostrarMensajesPrimerUso() {
    const path = window.location.pathname;
    
    // Punto de Venta
    if (path.includes('/pos/') || path.includes('punto_venta')) {
        if (PrimerUso.esPrimeraVez('pos_basico')) {
            setTimeout(() => {
                PrimerUso.mostrarMensaje(
                    'pos_basico',
                    'Escanea códigos de barras o busca productos manualmente. El carrito se limpia automáticamente después de cada venta.',
                    'top'
                );
            }, 1000);
        }
        
        // Mensaje sobre favoritos en POS
        if (PrimerUso.esPrimeraVez('pos_favoritos')) {
            setTimeout(() => {
                const favoritosBtn = document.querySelector('a[href*="mis-favoritos"]');
                if (favoritosBtn) {
                    PrimerUso.mostrarMensaje(
                        'pos_favoritos',
                        '¿Sabías que puedes marcar productos como favoritos? Así los tendrás a mano para ventas rápidas.',
                        'bottom'
                    );
                }
            }, 3000);
        }
    }
    
    // Dashboard
    if (path.includes('/dashboard/') && !path.includes('usuario')) {
        if (PrimerUso.esPrimeraVez('dashboard_personalizar')) {
            setTimeout(() => {
                PrimerUso.mostrarMensaje(
                    'dashboard_personalizar',
                    'Puedes personalizar el dashboard: haz clic en "Personalizar" para reorganizar los widgets arrastrándolos.',
                    'top'
                );
            }, 1500);
        }
    }
    
    // Inicio - Favoritos
    if (path === '/' || path.includes('/inicio')) {
        if (PrimerUso.esPrimeraVez('favoritos')) {
            setTimeout(() => {
                PrimerUso.mostrarMensaje(
                    'favoritos',
                    'Haz clic en la estrella ⭐ junto a un producto para agregarlo a favoritos y acceder rápido desde el menú.',
                    'top'
                );
            }, 2000);
        }
    }
    
    // Cotizaciones
    if (path.includes('/cotizaciones/')) {
        if (PrimerUso.esPrimeraVez('cotizaciones')) {
            setTimeout(() => {
                PrimerUso.mostrarMensaje(
                    'cotizaciones',
                    'Las cotizaciones te permiten preparar presupuestos. Puedes convertirlas en ventas cuando el cliente apruebe.',
                    'top'
                );
            }, 1500);
        }
    }
}

// ===== AGREGAR TOOLTIPS A ELEMENTOS COMUNES =====
function agregarTooltipsAutomaticos() {
    // Botones de favoritos
    document.querySelectorAll('.favorito-btn').forEach(btn => {
        if (!btn.hasAttribute('data-bs-toggle')) {
            btn.setAttribute('data-bs-toggle', 'tooltip');
            btn.setAttribute('data-bs-placement', 'top');
        }
    });
    
    // Botones de exportar
    document.querySelectorAll('a[href*="exportar"]').forEach(link => {
        if (!link.hasAttribute('data-bs-toggle')) {
            const tipo = link.href.includes('excel') ? 'Excel' : 
                        link.href.includes('pdf') ? 'PDF' : 'CSV';
            link.setAttribute('data-bs-toggle', 'tooltip');
            link.setAttribute('data-bs-placement', 'top');
            link.setAttribute('title', `Exportar datos en formato ${tipo}`);
        }
    });
}

// ===== INICIALIZACIÓN =====
document.addEventListener('DOMContentLoaded', function() {
    // Inicializar tooltips
    initTooltips();
    agregarTooltipsAutomaticos();
    
    // Reinicializar tooltips después de cambios dinámicos
    setTimeout(() => {
        initTooltips();
    }, 500);
    
    // Mostrar mensajes de primer uso
    mostrarMensajesPrimerUso();
});

// CSS para animación
const style = document.createElement('style');
style.textContent = `
    @keyframes slideInPrimerUso {
        from {
            transform: translateX(100%);
            opacity: 0;
        }
        to {
            transform: translateX(0);
            opacity: 1;
        }
    }
    
    .primer-uso-mensaje {
        border-left: 4px solid #0dcaf0;
    }
    
    .primer-uso-mensaje .btn-close {
        padding: 0.5rem 0.5rem;
    }
`;
document.head.appendChild(style);

