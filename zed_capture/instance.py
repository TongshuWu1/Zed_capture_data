"""Keep one capture UI per OS user, across PyCharm and terminal launches."""
import getpass
import hashlib
from pathlib import Path

from PySide6.QtCore import QObject, QLockFile, QStandardPaths, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


class SingleInstance(QObject):
    activation_requested = Signal()

    def __init__(self, name=None, lock_directory=None):
        super().__init__()
        user = hashlib.sha256(getpass.getuser().encode()).hexdigest()[:16]
        self.name = name or f"zed-capture-{user}-v1"
        directory = Path(lock_directory or QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.TempLocation))
        directory.mkdir(parents=True, exist_ok=True)
        self.lock = QLockFile(str(directory / (self.name + ".lock")))
        # A capture may last hours; elapsed wall time must not expire its lock.
        self.lock.setStaleLockTime(0)
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.server.newConnection.connect(self._on_connection)
        self.owns_lock = False

    def acquire(self):
        if not self.lock.tryLock(0):
            connection = QLocalSocket()
            connection.connectToServer(self.name)
            if connection.waitForConnected(500):
                connection.write(b"activate")
                connection.waitForBytesWritten(500)
                connection.disconnectFromServer()
            return False
        self.owns_lock = True
        # Holding the OS lock proves no cooperating live instance owns this
        # endpoint. Remove a stale Unix socket left by a previous crash.
        QLocalServer.removeServer(self.name)
        if not self.server.listen(self.name):
            error = self.server.errorString()
            self.close()
            raise RuntimeError(f"Cannot initialize the application instance guard: {error}")
        return True

    def _on_connection(self):
        while self.server.hasPendingConnections():
            connection = self.server.nextPendingConnection()
            self.activation_requested.emit()
            connection.close()
            connection.deleteLater()

    def close(self):
        self.server.close()
        if self.owns_lock:
            self.lock.unlock()
            self.owns_lock = False
