from fastapi.testclient import TestClient
from coach_app.main import app


def test_hd_preview_has_setup_fallback_or_built_3d_page():
    response = TestClient(app).get('/hd')
    assert response.status_code == 200
    assert (
        'High-Fidelity 3D viewer is not built yet' in response.text
        or 'HIGH-FIDELITY STADIUM' in response.text
    )
