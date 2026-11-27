import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_guardar_orden_dashboard(client, admin_user):
    client.force_login(admin_user)
    url = reverse("guardar_orden_dashboard")
    orden = ["ventas", "inventario"]

    response = client.post(url, {"orden": orden}, content_type="application/json")

    assert response.status_code == 200
    assert response.json() == {"success": True}
    assert client.session["dashboard_widgets_order"] == orden

    response = client.post(url, "{", content_type="application/json")

    assert response.status_code == 400
    assert response.json()["success"] is False
    assert client.session["dashboard_widgets_order"] == orden
