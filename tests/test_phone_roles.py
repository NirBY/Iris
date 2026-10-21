from typing import Any


async def test_parent_connection_is_not_monitored_and_role_is_persisted(app_client: Any) -> None:
    response = await app_client.post(
        "/api/instances",
        json={
            "kid_name": "Example parent",
            "role": "parent",
            "openwa_base_url": "https://wa.example",
            "openwa_instance_id": "parent",
        },
    )
    assert response.status_code == 201
    parent = response.json()
    assert parent["role"] == "parent" and parent["enabled"] is False
    ident = parent["id"]
    assert (await app_client.get(f"/api/instances/{ident}")).json()["role"] == "parent"
    assert (
        await app_client.patch(f"/api/instances/{ident}", json={"enabled": True})
    ).status_code == 422
    response = await app_client.patch(f"/api/instances/{ident}", json={"role": "child"})
    assert response.json()["role"] == "child" and not response.json()["enabled"]
    assert (
        await app_client.patch(f"/api/instances/{ident}", json={"enabled": True})
    ).status_code == 200


async def test_legacy_instance_defaults_to_child(app_client: Any) -> None:
    response = await app_client.post(
        "/api/instances",
        json={
            "kid_name": "Example child",
            "openwa_base_url": "https://wa.example",
            "openwa_instance_id": "child",
        },
    )
    assert response.json()["role"] == "child" and response.json()["enabled"]


async def test_deleting_parent_clears_role_for_reused_id(app_client: Any) -> None:
    body = {
        "kid_name": "Parent",
        "role": "parent",
        "openwa_base_url": "https://wa.example",
        "openwa_instance_id": "parent",
    }
    parent = (await app_client.post("/api/instances", json=body)).json()
    assert (await app_client.delete(f"/api/instances/{parent['id']}")).status_code == 204
    body.pop("role")
    child = (await app_client.post("/api/instances", json=body)).json()
    assert child["role"] == "child" and child["enabled"]
