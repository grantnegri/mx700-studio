"""Small bounded POSIX serial transport. Never opens a device during enumeration."""
import array
import fcntl
import glob
import os
from pathlib import Path
import select
import termios
import time


def available_ports():
    preferred = sorted(glob.glob('/dev/serial/by-id/*'))
    seen = {str(Path(p).resolve()) for p in preferred}
    return preferred + [p for p in sorted(glob.glob('/dev/ttyUSB*') + glob.glob('/dev/ttyACM*')) if p not in seen]


class SerialPort:
    def __init__(self, path, baud=115200):
        if baud not in (9600, 115200):
            raise ValueError('Supported rates are 9600 and 115200')
        self.path, self.baud, self.fd, self.saved = path, baud, None, None

    def __enter__(self):
        self.fd = os.open(self.path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        try:
            fcntl.ioctl(self.fd, termios.TIOCEXCL)
            self.saved = termios.tcgetattr(self.fd)
            attrs = termios.tcgetattr(self.fd)
            attrs[0] = attrs[1] = attrs[3] = 0
            attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
            attrs[4] = attrs[5] = getattr(termios, 'B' + str(self.baud))
            attrs[6][termios.VMIN] = 0
            attrs[6][termios.VTIME] = 0
            termios.tcsetattr(self.fd, termios.TCSANOW, attrs)
            # The original editor enables DTR and RTS. The cable uses TX/RX/GND.
            fcntl.ioctl(self.fd, termios.TIOCMBIS,
                        array.array('i', [termios.TIOCM_DTR | termios.TIOCM_RTS]))
            termios.tcflush(self.fd, termios.TCIFLUSH)
            return self
        except BaseException:
            self.close()
            raise

    def read(self, count, timeout=1.0):
        # Return the available chunk so the protocol can enforce its inter-byte
        # timeout. Waiting for the whole transfer here would hide stalled gaps.
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([self.fd], [], [], remaining)[0]:
                return b''
            try:
                return os.read(self.fd, count)
            except BlockingIOError:
                continue

    def reset_input_buffer(self):
        termios.tcflush(self.fd, termios.TCIFLUSH)

    def drain_output(self, timeout=30.0):
        deadline = time.monotonic() + timeout
        while True:
            queued = array.array('i', [0])
            fcntl.ioctl(self.fd, termios.TIOCOUTQ, queued, True)
            if queued[0] == 0:
                return
            if time.monotonic() >= deadline:
                raise TimeoutError('Serial output queue did not drain')
            time.sleep(0.005)

    def write(self, data):
        view, deadline = memoryview(data), time.monotonic() + 2.0
        while view:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([], [self.fd], [], remaining)[1]:
                raise TimeoutError('Serial write timed out')
            try:
                count = os.write(self.fd, view)
            except BlockingIOError:
                continue
            if not count:
                raise OSError('Serial connection closed')
            view = view[count:]
        return len(data)

    def close(self):
        if self.fd is not None:
            try:
                if self.saved is not None:
                    termios.tcsetattr(self.fd, termios.TCSANOW, self.saved)
            finally:
                os.close(self.fd)
                self.fd = None

    def __exit__(self, exc_type, exc, traceback):
        try:
            self.close()
        except OSError:
            if exc is None:
                raise
            # Preserve the original transfer error if unplugging also makes
            # restoration of tty settings fail. close() still closes the fd.
