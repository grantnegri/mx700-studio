import os
import pty
import termios
import unittest
from unittest.mock import patch

from mx700_studio.serial_port import SerialPort


class SerialTests(unittest.TestCase):
    def test_fragment_delivery_and_write_on_real_pty(self):
        master, slave = pty.openpty()
        name = os.ttyname(slave)
        import fcntl
        original_ioctl = fcntl.ioctl

        def ioctl(fd, request, *args):
            # A PTY has no physical modem control lines; all other operations
            # exercise actual kernel tty behavior.
            if request == termios.TIOCMBIS:
                return 0
            return original_ioctl(fd, request, *args)

        try:
            with patch('mx700_studio.serial_port.fcntl.ioctl', side_effect=ioctl):
                with SerialPort(name) as port:
                    os.write(master, b'\xaa\x01')
                    self.assertEqual(port.read(4096, .1), b'\xaa\x01')
                    self.assertEqual(port.read(1, .01), b'')
                    self.assertEqual(port.write(b'\x04\x0a\x0b\x0a\x0b'), 5)
                    self.assertEqual(os.read(master, 5), b'\x04\x0a\x0b\x0a\x0b')
                self.assertIsNone(port.fd)
        finally:
            os.close(master)
            os.close(slave)

    def test_reject_unknown_rate_without_opening(self):
        with self.assertRaises(ValueError):
            SerialPort('/not/a/device', 12345)
