"""Deny network in qualification subprocesses, preserving socket's class API."""
import socket

class OfflineSocket(socket.socket):
    def __new__(cls, *args, **kwargs):
        raise OSError("Network denied in operating-foundation qualification")

def forbidden(*args, **kwargs):
    raise OSError("Network denied in operating-foundation qualification")

socket.socket = OfflineSocket
socket.create_connection = forbidden
socket.getaddrinfo = forbidden
