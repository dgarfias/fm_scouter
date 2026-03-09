import os
import struct
import ctypes
import ctypes.util


class _iovec(ctypes.Structure):
    _fields_ = [("iov_base", ctypes.c_void_p), ("iov_len", ctypes.c_size_t)]


_vm_readv = None


def _init_vm_readv():
    global _vm_readv
    libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
    _vm_readv = libc.process_vm_readv
    _vm_readv.restype = ctypes.c_ssize_t
    _vm_readv.argtypes = [
        ctypes.c_int,
        ctypes.POINTER(_iovec),
        ctypes.c_ulong,
        ctypes.POINTER(_iovec),
        ctypes.c_ulong,
        ctypes.c_ulong,
    ]


class MemoryReader:
    def __init__(self, pid: int):
        self.pid = pid
        self._fd = -1
        self.has_batch_read = False

    def open(self):
        self._fd = os.open(f"/proc/{self.pid}/mem", os.O_RDONLY)
        try:
            _init_vm_readv()
            self.has_batch_read = True
        except Exception:
            self.has_batch_read = False

    def close(self):
        if self._fd >= 0:
            os.close(self._fd)
            self._fd = -1

    def read_bytes(self, address: int, size: int) -> bytes | None:
        if address < 0 or address > 0x7FFFFFFFFFFF:
            return None
        try:
            return os.pread(self._fd, size, address)
        except (OSError, OverflowError):
            return None

    def read_pointer(self, address: int) -> int | None:
        return self.read_uint64(address)

    def read_uint64(self, address: int) -> int | None:
        data = self.read_bytes(address, 8)
        if data and len(data) == 8:
            return struct.unpack('<Q', data)[0]
        return None

    def read_uint32(self, address: int) -> int | None:
        data = self.read_bytes(address, 4)
        if data and len(data) == 4:
            return struct.unpack('<I', data)[0]
        return None

    def read_string(self, address: int, max_len: int = 256) -> str | None:
        data = self.read_bytes(address, max_len)
        if data is None:
            return None
        null = data.find(b'\x00')
        if null >= 0:
            data = data[:null]
        try:
            return data.decode('utf-8')
        except UnicodeDecodeError:
            return data.decode('latin-1')

    def batch_read_u64(self, addresses: list[int]) -> list[tuple[int, int]]:
        if not addresses:
            return []

        if self.has_batch_read and _vm_readv is not None:
            results = []
            for i in range(0, len(addresses), 1024):
                chunk = addresses[i:i + 1024]
                n = len(chunk)
                buf = (ctypes.c_char * (n * 8))()
                local = (_iovec * 1)(
                    _iovec(ctypes.cast(buf, ctypes.c_void_p), n * 8)
                )
                remote = (_iovec * n)(
                    *(_iovec(ctypes.c_void_p(addr), 8) for addr in chunk)
                )
                ret = _vm_readv(
                    self.pid,
                    local, 1,
                    remote, n,
                    0,
                )
                if ret == n * 8:
                    raw = bytes(buf)
                    for j, addr in enumerate(chunk):
                        val = struct.unpack('<Q', raw[j * 8:(j + 1) * 8])[0]
                        results.append((addr, val))
                else:
                    for addr in chunk:
                        val = self.read_uint64(addr)
                        if val is not None:
                            results.append((addr, val))
            return results

        results = []
        for addr in addresses:
            val = self.read_uint64(addr)
            if val is not None:
                results.append((addr, val))
        return results

    def batch_read_fixed(self, addresses: list[int], size: int) -> dict[int, bytes]:
        if not addresses:
            return {}

        if self.has_batch_read and _vm_readv is not None:
            results = {}
            for i in range(0, len(addresses), 1024):
                chunk = addresses[i:i + 1024]
                n = len(chunk)
                total = n * size
                buf = (ctypes.c_char * total)()
                local = (_iovec * 1)(
                    _iovec(ctypes.cast(buf, ctypes.c_void_p), total)
                )
                remote = (_iovec * n)(
                    *(_iovec(ctypes.c_void_p(addr), size) for addr in chunk)
                )
                ret = _vm_readv(
                    self.pid,
                    local, 1,
                    remote, n,
                    0,
                )
                if ret == total:
                    raw = bytes(buf)
                    for j, addr in enumerate(chunk):
                        results[addr] = raw[j * size:(j + 1) * size]
                else:
                    for addr in chunk:
                        data = self.read_bytes(addr, size)
                        if data and len(data) == size:
                            results[addr] = data
            return results

        results = {}
        for addr in addresses:
            data = self.read_bytes(addr, size)
            if data and len(data) == size:
                results[addr] = data
        return results
