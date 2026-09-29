"""Uji rute item."""

from __future__ import annotations


def test_read_root(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"Hello": "World"}


def test_read_item_found(client):
    response = client.get("/items/foo")
    assert response.status_code == 200
    assert response.json() == {"item_id": "foo", "name": "The Foo Wrestless"}


def test_read_item_not_found(client):
    response = client.get("/items/tidak-ada")
    assert response.status_code == 404
    assert "tidak ditemukan" in response.json()["detail"]


def test_list_items(client):
    response = client.get("/items")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"] == [{"item_id": "foo", "name": "The Foo Wrestless"}]
