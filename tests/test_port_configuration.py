from __future__ import annotations

import socket

import pytest

from mdt.runtime import PortConfigurationError, free_port, port_is_free, resolve_port


def test_requested_free_port_is_preserved():
    requested = free_port()
    assert resolve_port(requested) == requested
    assert port_is_free(requested)


def test_requested_occupied_port_fails_fast():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        occupied = int(listener.getsockname()[1])
        assert not port_is_free(occupied)
        with pytest.raises(PortConfigurationError, match="already in use"):
            resolve_port(occupied)


def test_zero_allocates_an_ephemeral_port():
    allocated = resolve_port(0)
    assert allocated >= 1024
    assert port_is_free(allocated)


def test_environment_value_is_used_when_cli_is_omitted(monkeypatch):
    requested = free_port()
    monkeypatch.setenv("MDT_PORT", str(requested))
    assert resolve_port() == requested
