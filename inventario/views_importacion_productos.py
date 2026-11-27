from django.core import signing
from django.core.exceptions import PermissionDenied, RequestDataTooBig
from django.core.files.uploadhandler import FileUploadHandler
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from django.views.decorators.http import require_http_methods

from .access import permiso_requerido
from .importacion_productos import ConflictoImportacion, importar, planificar
from .lectura_productos_excel import MAX_ARCHIVO, ExcelInvalido, leer_excel

PLANTILLA = "inventario/importar_productos_excel.html"
SALT = "inventario.importar_productos_excel.v1"
VIGENCIA = 15 * 60


class LimiteExcel(FileUploadHandler):
    """Acota la carga antes de que los manejadores de Django guarden partes."""

    recibidos = 0

    def handle_raw_input(
        self, input_data, META, content_length, boundary, encoding=None
    ):
        if content_length > MAX_ARCHIVO + 64 * 1024:
            raise RequestDataTooBig("Carga Excel demasiado grande.")

    def receive_data_chunk(self, raw_data, start):
        self.recibidos += len(raw_data)
        if self.recibidos > MAX_ARCHIVO:
            raise RequestDataTooBig("Carga Excel demasiado grande.")
        return raw_data

    def file_complete(self, file_size):
        return None


@csrf_exempt
@permiso_requerido("inventario.add_producto", administrativo=True)
@require_http_methods(["GET", "POST"])
def importar_productos_excel(request):
    if not request.user.has_perms(
        ("inventario.change_producto", "inventario.add_categoria")
    ):
        raise PermissionDenied
    # La protección interior lee el POST tras instalar el límite para esta ruta.
    if request.method == "POST":
        request.upload_handlers.insert(0, LimiteExcel(request))
    return procesar_formulario(request)


@csrf_protect
def procesar_formulario(request):
    if request.method == "GET":
        return render(request, PLANTILLA)
    archivo = request.FILES.get("archivo")
    token = request.POST.get("vista_previa")
    try:
        if not archivo or len(request.FILES.getlist("archivo")) != 1:
            raise ExcelInvalido("Selecciona un único archivo Excel.")
        catalogo = leer_excel(archivo, archivo.name)
        if request.POST.get("accion") == "confirmar":
            return confirmar(request, catalogo, token)
        plan = planificar(catalogo)
        contexto = {"resumen": plan.resumen}
        if not plan.resumen.errores:
            contexto["vista_previa"] = signing.dumps(
                [request.user.pk, catalogo.huella, plan.version], salt=SALT
            )
        return render(request, PLANTILLA, contexto)
    except ExcelInvalido as error:
        contexto = {"error": str(error)}
        if token and request.POST.get("accion") == "confirmar":
            contexto["vista_previa"] = token
        return render(request, PLANTILLA, contexto, status=400)
    except ConflictoImportacion as error:
        return render(request, PLANTILLA, {"error": str(error)}, status=409)


def confirmar(request, catalogo, token):
    try:
        usuario, huella, version = signing.loads(
            token or "", salt=SALT, max_age=VIGENCIA
        )
    except signing.BadSignature as error:
        raise ConflictoImportacion(
            "La vista previa no es válida o venció. Genera una nueva."
        ) from error
    if usuario != request.user.pk:
        raise PermissionDenied
    if huella != catalogo.huella:
        raise ConflictoImportacion(
            "El archivo difiere de la vista previa. Genera una nueva."
        )
    resumen = importar(catalogo, version=version, usuario=request.user)
    return render(request, PLANTILLA, {"resumen": resumen, "importado": True})
