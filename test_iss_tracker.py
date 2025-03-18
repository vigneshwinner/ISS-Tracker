import pytest
import math
from datetime import datetime, timezone, timedelta
from iss_tracker import app, compute_speed, find_closest_epoch, get_iss_data


def test_compute_speed():
    """Tests if compute_speed correctly calculates vector magnitude."""
    assert math.isclose(compute_speed((1, 2, 2)), 3.0, rel_tol=1e-3)
    assert math.isclose(compute_speed((3, 4, 0)), 5.0, rel_tol=1e-3)
    assert math.isclose(compute_speed((6, 8, 0)), 10.0, rel_tol=1e-3)


def test_find_closest_epoch():
    """Tests if find_closest_epoch returns the closest epoch to now."""
    now = datetime.now(timezone.utc)
    sample_data = [
        {"epoch": now - timedelta(minutes=2), "position": (100, 200, 300), "velocity": (1, 2, 2)},
        {"epoch": now + timedelta(minutes=2), "position": (150, 250, 350), "velocity": (3, 4, 0)}
    ]
    closest = find_closest_epoch(sample_data, now)
    expected_epoch = min(sample_data, key=lambda d: abs(d["epoch"] - now))["epoch"]
    assert closest["epoch"] == expected_epoch


def test_get_iss_data():
    """Tests if ISS data retrieval from Redis or external source is functional."""
    data = get_iss_data()
    assert isinstance(data, list)
    if data:
        assert "epoch" in data[0]
        assert "position" in data[0]
        assert "velocity" in data[0]


def test_get_epochs():
    """Tests the /epochs endpoint (retrieves all epochs)."""
    client = app.test_client()
    response = client.get("/epochs")
    assert response.status_code == 200
    assert isinstance(response.data.decode(), str)


def test_get_epochs_subset():
    """Tests /epochs?limit=int&offset=int for retrieving a subset of epochs."""
    client = app.test_client()
    response = client.get("/epochs?limit=5&offset=2")
    data = response.data.decode().split("\n")
    data = [entry for entry in data if entry.strip()]
    assert len(data) <= 5


def test_get_specific_epoch():
    """Tests /epochs/<epoch> for retrieving state vectors of a specific epoch."""
    client = app.test_client()
    sample_data = get_iss_data()
    if sample_data:
        epoch = sample_data[0]["epoch"].isoformat()
        response = client.get(f"/epochs/{epoch}")
        assert response.status_code == 200
        assert "Epoch" in response.data.decode()
    else:
        assert True  # No data available to test


def test_get_epoch_speed():
    """Tests /epochs/<epoch>/speed for retrieving instantaneous speed."""
    client = app.test_client()
    sample_data = get_iss_data()
    if sample_data:
        epoch = sample_data[0]["epoch"].isoformat()
        response = client.get(f"/epochs/{epoch}/speed")
        assert response.status_code == 200
        assert "Speed" in response.data.decode()
    else:
        assert True  # No data available to test


def test_get_epoch_location():
    """Tests /epochs/<epoch>/location for retrieving ISS geopositioning."""
    client = app.test_client()
    sample_data = get_iss_data()
    if sample_data:
        epoch = sample_data[0]["epoch"].isoformat()
        response = client.get(f"/epochs/{epoch}/location")
        assert response.status_code == 200
        assert "Latitude" in response.data.decode()
        assert "Longitude" in response.data.decode()
        assert "Altitude" in response.data.decode()
        assert "Geoposition" in response.data.decode()
    else:
        assert True  # No data available to test


def test_get_now():
    """Tests /now endpoint for retrieving the closest epoch to the current time."""
    client = app.test_client()
    response = client.get("/now")
    assert response.status_code == 200
    data = response.data.decode()
    assert "Closest Epoch" in data
    assert "Speed" in data
    assert "Latitude" in data
    assert "Longitude" in data
    assert "Altitude" in data
    assert "Geoposition" in data
