from __future__ import annotations

import bz2
import hashlib
import lzma
import os
import struct
from concurrent import futures
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from multiprocessing import cpu_count
from threading import Event
from typing import Callable, Optional

import brotli
import bsdiff4.core
from zstd import ZSTD_uncompress

from . import mtio
from .future_util import wait_interruptible
from .update_metadata_pb2 import InstallOperation
from . import update_metadata_pb2 as um
from .ziputil import get_zip_stored_entry_offset


def u32(x: bytes) -> int:
    return struct.unpack('>I', x)[0]


def u64(x: bytes) -> int:
    return struct.unpack('>Q', x)[0]


BSDF2_MAGIC = b'BSDF2'


def bsdf2_decompress(alg: int, data: bytes) -> bytes:
    if alg == 0:
        return data
    if alg == 1:
        return bz2.decompress(data)
    if alg == 2:
        return brotli.decompress(data)
    raise ValueError(f'unknown algorithm {alg}')


def bsdf2_read_patch(fi):
    magic = fi.read(8)
    if magic == bsdiff4.format.MAGIC:
        alg_control = alg_diff = alg_extra = 1
    elif magic[:5] == BSDF2_MAGIC:
        alg_control = magic[5]
        alg_diff = magic[6]
        alg_extra = magic[7]
    else:
        raise ValueError('incorrect magic bsdiff/BSDF2 header')

    len_control = bsdiff4.core.decode_int64(fi.read(8))
    len_diff = bsdiff4.core.decode_int64(fi.read(8))
    len_dst = bsdiff4.core.decode_int64(fi.read(8))

    bcontrol = bsdf2_decompress(alg_control, fi.read(len_control))
    tcontrol = [
        (
            bsdiff4.core.decode_int64(bcontrol[i : i + 8]),
            bsdiff4.core.decode_int64(bcontrol[i + 8 : i + 16]),
            bsdiff4.core.decode_int64(bcontrol[i + 16 : i + 24]),
        )
        for i in range(0, len(bcontrol), 24)
    ]

    bdiff = bsdf2_decompress(alg_diff, fi.read(len_diff))
    bextra = bsdf2_decompress(alg_extra, fi.read())
    return len_dst, tcontrol, bdiff, bextra


@dataclass
class _Op:
    operation: InstallOperation
    offset: int
    length: int


class DumperCore:
    def __init__(
        self,
        *,
        payload_file: mtio.MTIOBase,
        out_dir: str,
        partitions: str = '',
        workers: int = cpu_count(),
        log_callback: Optional[Callable[[str], None]] = None,
        step_start: Optional[Callable[[str, str], None]] = None,
        step_finish: Optional[Callable[[str, bool, str], None]] = None,
        cancel_event: Optional[Event] = None,
    ):
        self.payloadfile = payload_file
        self.out = out_dir
        self.images = partitions
        self.workers = workers
        self.log = log_callback or (lambda _m: None)
        self.step_start = step_start or (lambda _i, _t: None)
        self.step_finish = step_finish or (lambda _i, _s, _m: None)
        self.cancel = cancel_event or Event()

        try:
            off, size = get_zip_stored_entry_offset(self.payloadfile, 'payload.bin')
            self.base_off = int(off)
            self.payload_size = int(size)
        except Exception:
            self.base_off = 0
            self.payload_size = int(self.payloadfile.get_size())

        self.parse_metadata()

    def _read_payload(self, rel_off: int, size: int) -> bytes:
        if rel_off < 0 or size < 0:
            raise ValueError('invalid read range')
        end = rel_off + size
        if end > self.payload_size:
            raise ValueError(f'read out of payload.bin boundary: {rel_off=} {size=} payload_size={self.payload_size}')
        return self.payloadfile.read(self.base_off + rel_off, size)

    def _check_cancel(self):
        if self.cancel.is_set():
            raise RuntimeError('cancelled')

    def parse_metadata(self):
        import uuid
        sid = str(uuid.uuid4())
        self.step_start(sid, "解析 Payload 元数据")
        try:
            head_len = 4 + 8 + 8 + 4
            fp = 0
            buffer = self._read_payload(fp, head_len)
            fp += head_len
            if len(buffer) != head_len:
                raise RuntimeError('payload header too short')
            magic = buffer[:4]
            if magic != b'CrAU':
                raise RuntimeError('invalid payload magic')

            file_format_version = u64(buffer[4:12])
            if file_format_version != 2:
                raise RuntimeError(f'unsupported payload version: {file_format_version}')

            manifest_size = u64(buffer[12:20])
            metadata_signature_size = u32(buffer[20:24])

            manifest = self._read_payload(fp, manifest_size)
            fp += manifest_size
            self.metadata_signature = self._read_payload(fp, metadata_signature_size)
            fp += metadata_signature_size
            self.data_offset = fp

            self.dam = um.DeltaArchiveManifest()
            self.dam.ParseFromString(manifest)
            self.block_size = self.dam.block_size
            self.step_finish(sid, True, f"BlockSize={self.block_size}")
        except Exception as e:
            self.step_finish(sid, False, str(e))
            raise e

    def run(self):
        if self.images == '':
            partitions = list(self.dam.partitions)
        else:
            targets = [p.strip() for p in self.images.split(',') if p.strip()]
            partitions = [p for p in self.dam.partitions if p.partition_name in targets]

        if len(partitions) == 0:
            self.log('Not operating on any partitions')
            return

        parts = []
        for partition in partitions:
            ops = []
            for operation in partition.operations:
                ops.append(
                    _Op(
                        operation=operation,
                        offset=self.data_offset + operation.data_offset,
                        length=operation.data_length,
                    )
                )
            parts.append((partition.partition_name, ops))

        for name, ops in parts:
            self._check_cancel()
            self._extract_partition(name, ops)

    def _extract_partition(self, name: str, ops: list[_Op]):
        import uuid
        sid = str(uuid.uuid4())
        self.step_start(sid, f"提取 {name}")
        # self.log(f'提取分区: {name} ops={len(ops)}')
        out_path = os.path.join(self.out, f'{name}.img')
        out_file = mtio.MTFile(out_path, 'w')
        try:
            with ThreadPoolExecutor(max_workers=self.workers) as executor:
                tasks = [executor.submit(self._do_op, op, out_file) for op in ops]
                dones, undones = wait_interruptible(tasks, return_when=futures.FIRST_EXCEPTION)
                for t in dones:
                    e = t.exception(0)
                    if e is not None:
                        raise e
                for t in undones:
                    try:
                        t.cancel()
                    except Exception:
                        pass
            self.step_finish(sid, True, "")
        except Exception as e:
            self.step_finish(sid, False, str(e))
            try:
                out_file.close()
            except Exception:
                pass
            raise e
        finally:
            try:
                out_file.close()
            except Exception:
                pass

    def _do_op(self, op: _Op, out_file: mtio.MTIOBase):
        if self.cancel.is_set():
            raise RuntimeError('cancelled')

        data = self._read_payload(op.offset, op.length)
        inst = op.operation

        if inst.data_sha256_hash:
            if hashlib.sha256(data).digest() != inst.data_sha256_hash:
                raise RuntimeError('operation data hash mismatch')

        t = inst.type
        if t == InstallOperation.REPLACE_XZ:
            dec = lzma.LZMADecompressor()
            data = dec.decompress(data)
            out_file.write(inst.dst_extents[0].start_block * self.block_size, data)
            return
        if t == InstallOperation.REPLACE_BZ:
            dec = bz2.BZ2Decompressor()
            data = dec.decompress(data)
            out_file.write(inst.dst_extents[0].start_block * self.block_size, data)
            return
        if t == InstallOperation.REPLACE:
            out_file.write(inst.dst_extents[0].start_block * self.block_size, data)
            return

        # ZSTD-compressed REPLACE
        if hasattr(InstallOperation, 'ZSTD') and t == InstallOperation.ZSTD:
            data = ZSTD_uncompress(data)
            out_file.write(inst.dst_extents[0].start_block * self.block_size, data)
            return

        # ZERO fill
        if hasattr(InstallOperation, 'ZERO') and t == InstallOperation.ZERO:
            for ext in inst.dst_extents:
                if self.cancel.is_set():
                    raise RuntimeError('cancelled')
                out_file.write(ext.start_block * self.block_size, b"\x00" * (ext.num_blocks * self.block_size))
            return

        # DISCARD: no output data, just skip
        if hasattr(InstallOperation, 'DISCARD') and t == InstallOperation.DISCARD:
            return

        # Differential OTA is out of scope for our internal extractor for now.
        if hasattr(InstallOperation, 'SOURCE_COPY') and t == InstallOperation.SOURCE_COPY:
            raise RuntimeError('differential OTA not supported (SOURCE_COPY)')
        if hasattr(InstallOperation, 'SOURCE_BSDIFF') and t == InstallOperation.SOURCE_BSDIFF:
            raise RuntimeError('differential OTA not supported (SOURCE_BSDIFF)')
        if hasattr(InstallOperation, 'BROTLI_BSDIFF') and t == InstallOperation.BROTLI_BSDIFF:
            raise RuntimeError('differential OTA not supported (BROTLI_BSDIFF)')

        raise RuntimeError(f'unsupported operation type: {t} for partition write')
