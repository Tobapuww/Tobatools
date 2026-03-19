import hashlib
import os
import shutil
import zipfile
import xml.etree.ElementTree as ET
from binascii import hexlify, unhexlify
from pathlib import Path
from struct import unpack
from typing import Callable, Optional

from Cryptodome.Cipher import AES


class OFPProcessor:
    def __init__(self, *, log_callback: Optional[Callable[[str], None]] = None, step_start: Optional[Callable[[str, str], None]] = None, step_finish: Optional[Callable[[str, bool, str], None]] = None):
        self._log = log_callback
        self.step_start = step_start or (lambda _i, _t: None)
        self.step_finish = step_finish or (lambda _i, _s, _m: None)
        self._stop = False

    def stop(self):
        self._stop = True

    def _emit(self, s: str):
        try:
            if self._log is not None:
                self._log(str(s))
        except Exception:
            pass

    @staticmethod
    def _hash_status_cn(s: str) -> str:
        v = (s or '').strip().lower()
        if v == 'verified':
            return '已校验'
        if v == 'bad':
            return '不匹配'
        if v == 'empty':
            return '无'
        return s

    @staticmethod
    def _op_prefix_cn(iscopy: bool) -> str:
        return '拷贝: ' if iscopy else '解密: '

    def extract(self, ofp_path: str, out_dir: str, *, mode: str = 'auto') -> bool:
        import uuid
        p = Path(str(ofp_path or '').strip())
        if not p.exists() or not p.is_file():
            raise FileNotFoundError(str(p))

        out = Path(str(out_dir or '').strip())
        if not out:
            raise ValueError('输出目录为空')
        out.mkdir(parents=True, exist_ok=True)

        m = (mode or 'auto').strip().lower()
        if m not in ('auto', 'qc', 'mtk'):
            raise ValueError(f'unknown mode: {mode}')

        sid = str(uuid.uuid4())
        self.step_start(sid, f"处理 OFP ({m})")

        try:
            if m == 'qc':
                res = self._extract_qc(p, out)
                self.step_finish(sid, res, "")
                return res
            if m == 'mtk':
                res = self._extract_mtk(p, out)
                self.step_finish(sid, res, "")
                return res

            try:
                if self._extract_qc(p, out):
                    self.step_finish(sid, True, "QC模式")
                    return True
            except Exception:
                pass
            
            res = self._extract_mtk(p, out)
            self.step_finish(sid, res, "MTK模式")
            return res
        except Exception as e:
            self.step_finish(sid, False, str(e))
            raise e

    def _check_stop(self):
        if self._stop:
            raise RuntimeError('stopped')

    @staticmethod
    def _swap(ch: int) -> int:
        return ((ch & 0xF) << 4) + ((ch & 0xF0) >> 4)

    @classmethod
    def _keyshuffle(cls, key: bytearray, hkey: bytearray) -> bytearray:
        for i in range(0, 0x10, 4):
            key[i] = cls._swap((hkey[i] ^ key[i]))
            key[i + 1] = cls._swap(hkey[i + 1] ^ key[i + 1])
            key[i + 2] = cls._swap(hkey[i + 2] ^ key[i + 2])
            key[i + 3] = cls._swap(hkey[i + 3] ^ key[i + 3])
        return key

    @staticmethod
    def _rol(x: int, n: int, bits: int = 32) -> int:
        n = bits - n
        mask = (2 ** n) - 1
        mask_bits = x & mask
        return (x >> n) | (mask_bits << (bits - n))

    @classmethod
    def _deobfuscate(cls, data: bytearray, mask: bytearray) -> bytearray:
        ret = bytearray()
        for i in range(0, len(data)):
            v = cls._rol((data[i] ^ mask[i]), 4, 8)
            ret.append(v)
        return ret

    @staticmethod
    def _aes_cfb(data: bytes, key: bytes, iv: bytes) -> bytes:
        ctx = AES.new(key, AES.MODE_CFB, iv=iv, segment_size=128)
        return ctx.decrypt(data)

    def _qc_extract_xml(self, filename: Path, key: bytes, iv: bytes) -> tuple[int, bytes]:
        filesize = filename.stat().st_size
        pagesize = 0
        with filename.open('rb') as rf:
            for x in (0x200, 0x1000):
                rf.seek(filesize - x + 0x10)
                if unpack('<I', rf.read(4))[0] == 0x7CEF:
                    pagesize = x
                    break
            if pagesize == 0:
                raise RuntimeError('unknown pagesize')

            xmloffset = filesize - pagesize
            rf.seek(xmloffset + 0x14)
            offset = unpack('<I', rf.read(4))[0] * pagesize
            length = unpack('<I', rf.read(4))[0]
            if length < 200:
                length = xmloffset - offset - 0x57
            rf.seek(offset)
            data = rf.read(length)

        dec = self._aes_cfb(data, key, iv)
        if b'<?xml' not in dec:
            return 0, b''
        return pagesize, dec

    def _qc_generate_key(self, filename: Path) -> tuple[int, bytes, bytes, bytes]:
        keys = [
            [
                'V1.4.17/1.4.27',
                '27827963787265EF89D126B69A495A21',
                '82C50203285A2CE7D8C3E198383CE94C',
                '422DD5399181E223813CD8ECDF2E4D72',
            ],
            [
                'V1.6.17',
                'E11AA7BB558A436A8375FD15DDD4651F',
                '77DDF6A0696841F6B74782C097835169',
                'A739742384A44E8BA45207AD5C3700EA',
            ],
            [
                'V1.5.13',
                '67657963787565E837D226B69A495D21',
                'F6C50203515A2CE7D8C3E1F938B7E94C',
                '42F2D5399137E2B2813CD8ECDF2F4D72',
            ],
            [
                'V1.6.6/1.6.9/1.6.17/1.6.24/1.6.26/1.7.6',
                '3C2D518D9BF2E4279DC758CD535147C3',
                '87C74A29709AC1BF2382276C4E8DF232',
                '598D92E967265E9BCABE2469FE4A915E',
            ],
            [
                'V1.7.2',
                '8FB8FB261930260BE945B841AEFA9FD4',
                'E529E82B28F5A2F8831D860AE39E425D',
                '8A09DA60ED36F125D64709973372C1CF',
            ],
            [
                'V2.0.3',
                'E8AE288C0192C54BF10C5707E9C4705B',
                'D64FC385DCD52A3C9B5FBA8650F92EDA',
                '79051FD8D8B6297E2E4559E997F63B7F',
            ],
        ]

        for dkey in keys:
            self._check_stop()
            mc = bytearray.fromhex(dkey[1])
            userkey = bytearray.fromhex(dkey[2])
            ivec = bytearray.fromhex(dkey[3])

            key = (hashlib.md5(self._deobfuscate(userkey, mc)).hexdigest()[0:16]).encode()
            iv = (hashlib.md5(self._deobfuscate(ivec, mc)).hexdigest()[0:16]).encode()

            pagesize, dec = self._qc_extract_xml(filename, key, iv)
            if pagesize != 0:
                return pagesize, key, iv, dec
        return 0, b'', b'', b''

    def _qc_parse_item(self, item: ET.Element, pagesize: int):
        sha256sum = item.attrib.get('sha256', '')
        md5sum = item.attrib.get('md5', '')

        wfilename = item.attrib.get('Path') or item.attrib.get('filename') or ''
        start = -1
        if 'FileOffsetInSrc' in item.attrib:
            start = int(item.attrib['FileOffsetInSrc']) * pagesize
        elif 'SizeInSectorInSrc' in item.attrib:
            start = int(item.attrib['SizeInSectorInSrc']) * pagesize

        rlength = int(item.attrib.get('SizeInByteInSrc') or 0)
        if 'SizeInSectorInSrc' in item.attrib:
            length = int(item.attrib['SizeInSectorInSrc']) * pagesize
        else:
            length = rlength

        decryptsize = 0x40000
        return wfilename, start, length, rlength, [sha256sum, md5sum], decryptsize

    def _qc_checkhash(self, path: Path, checksums: list[str], iscopy: bool):
        sha256sum = checksums[0]
        md5sum = checksums[1]
        prefix = self._op_prefix_cn(iscopy)

        try:
            size = path.stat().st_size
        except Exception:
            size = 0

        try:
            with path.open('rb') as rf:
                md5 = hashlib.md5(rf.read(0x40000))
                sha256bad = False
                md5bad = False
                md5status = 'empty'
                sha256status = 'empty'

                if sha256sum:
                    for x in (0x40000, size):
                        rf.seek(0)
                        sha256 = hashlib.sha256()
                        if x == 0x40000:
                            sha256.update(rf.read(x))
                        if x == size:
                            for chunk in iter(lambda: rf.read(128 * sha256.block_size), b''):
                                self._check_stop()
                                sha256.update(chunk)
                        if sha256sum != sha256.hexdigest():
                            sha256bad = True
                            sha256status = 'bad'
                        else:
                            sha256status = 'verified'
                            sha256bad = False
                            break

                if md5sum:
                    if md5sum != md5.hexdigest():
                        md5bad = True
                        md5status = 'bad'
                    else:
                        md5status = 'verified'
                        md5bad = False

                if (sha256bad and md5bad) or (sha256bad and not md5sum) or (md5bad and not sha256sum):
                    self._emit(prefix + '校验失败（hash 不匹配），文件可能损坏')
                else:
                    self._emit(prefix + f'成功 (md5: {self._hash_status_cn(md5status)} | sha256: {self._hash_status_cn(sha256status)})')
        except Exception:
            return

    def _qc_copy(self, filename: Path, out_dir: Path, wfilename: str, start: int, length: int, checksums: list[str]):
        self._emit(f'正在提取 {wfilename}')
        out_path = out_dir / wfilename
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with filename.open('rb') as rf:
            rf.seek(start)
            data = rf.read(length)
        with out_path.open('wb') as wf:
            wf.write(data)
        self._qc_checkhash(out_path, checksums, True)

    def _qc_decryptfile(
        self,
        key: bytes,
        iv: bytes,
        filename: Path,
        out_dir: Path,
        wfilename: str,
        start: int,
        length: int,
        rlength: int,
        checksums: list[str],
        decryptsize: int = 0x40000,
    ):
        self._emit(f'正在提取 {wfilename}')
        out_path = out_dir / wfilename
        out_path.parent.mkdir(parents=True, exist_ok=True)

        if rlength == length:
            tlen = length
            length = (length // 0x4 * 0x4)
            if tlen % 0x4 != 0:
                length += 0x4

        with filename.open('rb') as rf:
            rf.seek(start)
            size = decryptsize
            if rlength < decryptsize:
                size = rlength
            data = rf.read(size)
            if size % 4:
                data += (4 - (size % 4)) * b'\x00'
            outp = self._aes_cfb(data, key, iv)

            with out_path.open('wb') as wf:
                wf.write(outp[:size])
                if rlength > decryptsize:
                    remain = rlength - size
                    while remain > 0:
                        self._check_stop()
                        chunk = rf.read(min(0x100000, remain))
                        if not chunk:
                            break
                        wf.write(chunk)
                        remain -= len(chunk)

        self._qc_checkhash(out_path, checksums, False)

    def _extract_qc(self, ofp_path: Path, out_dir: Path) -> bool:
        self._emit('模式: 高通 (QC)')

        self._check_stop()
        with ofp_path.open('rb') as rf:
            head = rf.read(2)

        if head == b'PK':
            self._emit('检测到 ZIP 格式 OFP，尝试解密/解压')
            zippw = b"flash@realme$50E7F7D847732396F1582CD62DD385ED7ABB0897"
            with zipfile.ZipFile(ofp_path) as zf:
                for name in zf.namelist():
                    self._check_stop()
                    self._emit('正在提取 ' + name)
                    zf.extract(name, pwd=zippw, path=out_dir)
            return True

        pagesize, key, iv, data = self._qc_generate_key(ofp_path)
        if pagesize == 0:
            raise RuntimeError('无法识别此 OFP 的密钥')

        xml_bytes = data[: data.rfind(b'>') + 1]
        xml = xml_bytes.decode('utf-8', errors='ignore')

        try:
            profile = out_dir / 'ProFile.xml'
            profile.write_text(xml, encoding='utf-8', errors='ignore')
        except Exception:
            pass

        root = ET.fromstring(xml)
        for child in root:
            self._check_stop()
            for item in child:
                self._check_stop()
                if 'Path' not in item.attrib and 'filename' not in item.attrib:
                    for subitem in item:
                        wfilename, start, length, rlength, checksums, decryptsize = self._qc_parse_item(subitem, pagesize)
                        if not wfilename or start == -1:
                            continue
                        self._qc_decryptfile(key, iv, ofp_path, out_dir, wfilename, start, length, rlength, checksums, decryptsize)

                wfilename, start, length, rlength, checksums, decryptsize = self._qc_parse_item(item, pagesize)
                if not wfilename or start == -1:
                    continue

                if child.tag in ('Sahara',):
                    decryptsize = rlength
                if child.tag in ('Config', 'Provision', 'ChainedTableOfDigests', 'DigestsToSign', 'Firmware'):
                    length = rlength

                if child.tag in ('DigestsToSign', 'ChainedTableOfDigests', 'Firmware'):
                    self._qc_copy(ofp_path, out_dir, wfilename, start, length, checksums)
                else:
                    self._qc_decryptfile(key, iv, ofp_path, out_dir, wfilename, start, length, rlength, checksums, decryptsize)

        return True

    @staticmethod
    def _mtk_shuffle(key: bytearray, keylength: int, data: bytearray, inputlength: int) -> bytearray:
        for i in range(0, inputlength):
            k = key[(i % keylength)]
            h = (((data[i]) & 0xF0) >> 4) | (16 * ((data[i]) & 0xF))
            data[i] = k ^ h
        return data

    @staticmethod
    def _mtk_shuffle2(key: bytearray, keylength: int, data: bytearray, inputlength: int) -> bytearray:
        for i in range(0, inputlength):
            tmp = key[i % keylength] ^ data[i]
            data[i] = ((tmp & 0xF0) >> 4) | (16 * (tmp & 0xF))
        return data

    @staticmethod
    def _mtk_aes_cfb(key: bytes, iv: bytes, data: bytes, decrypt: bool = True, segment_size: int = 128) -> bytes:
        cipher = AES.new(key, AES.MODE_CFB, IV=iv, segment_size=segment_size)
        return cipher.decrypt(data) if decrypt else cipher.encrypt(data)

    def _mtk_getkey(self, index: int):
        keytables = [
            [
                '67657963787565E837D226B69A495D21',
                'F6C50203515A2CE7D8C3E1F938B7E94C',
                '42F2D5399137E2B2813CD8ECDF2F4D72',
            ],
            [
                '9E4F32639D21357D37D226B69A495D21',
                'A3D8D358E42F5A9E931DD3917D9A3218',
                '386935399137416B67416BECF22F519A',
            ],
            [
                '892D57E92A4D8A975E3C216B7C9DE189',
                'D26DF2D9913785B145D18C7219B89F26',
                '516989E4A1BFC78B365C6BC57D944391',
            ],
            [
                '27827963787265EF89D126B69A495A21',
                '82C50203285A2CE7D8C3E198383CE94C',
                '422DD5399181E223813CD8ECDF2E4D72',
            ],
            [
                '3C4A618D9BF2E4279DC758CD535147C3',
                '87B13D29709AC1BF2382276C4E8DF232',
                '59B7A8E967265E9BCABE2469FE4A915E',
            ],
            [
                '1C3288822BF824259DC852C1733127D3',
                'E7918D22799181CF2312176C9E2DF298',
                '3247F889A7B6DECBCA3E28693E4AAAFE',
            ],
            [
                '1E4F32239D65A57D37D2266D9A775D43',
                'A332D3C3E42F5A3E931DD991729A321D',
                '3F2A35399A373377674155ECF28FD19A',
            ],
            [
                '122D57E92A518AFF5E3C786B7C34E189',
                'DD6DF2D9543785674522717219989FB0',
                '12698965A132C76136CC88C5DD94EE91',
            ],
            [
                'ab3f76d7989207f2',
                '2bf515b3a9737835',
            ],
        ]

        kt = keytables[index]
        if len(kt) == 3:
            obskey = bytearray(unhexlify(kt[0]))
            encaeskey = bytearray(unhexlify(kt[1]))
            encaesiv = bytearray(unhexlify(kt[2]))
            aeskey = hexlify(hashlib.md5(self._mtk_shuffle2(obskey, 16, encaeskey, 16)).digest())[:16]
            aesiv = hexlify(hashlib.md5(self._mtk_shuffle2(obskey, 16, encaesiv, 16)).digest())[:16]
        else:
            aeskey = bytes(kt[0], 'utf-8')
            aesiv = bytes(kt[1], 'utf-8')
        return aeskey, aesiv, len(keytables)

    def _mtk_brutekey(self, rf) -> tuple[bytes, bytes]:
        rf.seek(0)
        encdata = rf.read(16)
        _, _, count = self._mtk_getkey(0)
        for keyid in range(0, count):
            self._check_stop()
            aeskey, aesiv, _ = self._mtk_getkey(keyid)
            data = self._mtk_aes_cfb(aeskey, aesiv, encdata, True)
            if data[:3] == b'MMM':
                return aeskey, aesiv
        raise RuntimeError('unknown key')

    @staticmethod
    def _cleancstring(b: bytes) -> str:
        return b.replace(b'\x00', b'').decode('utf-8', errors='ignore')

    def _extract_mtk(self, ofp_path: Path, out_dir: Path) -> bool:
        self._emit('模式: 联发科 (MTK)')

        hdrkey = bytearray(b'geyixue')
        filesize = ofp_path.stat().st_size
        hdrlength = 0x6C

        with ofp_path.open('rb') as rf:
            aeskey, aesiv = self._mtk_brutekey(rf)

            rf.seek(filesize - hdrlength)
            hdr = self._mtk_shuffle(hdrkey, len(hdrkey), bytearray(rf.read(hdrlength)), hdrlength)
            prjname, _, _, cpu, flashtype, hdr2entries, prjinfo, _ = unpack('46s Q 4s 7s 5s H 32s H', hdr)
            hdr2length = hdr2entries * 0x60

            prjname_s = self._cleancstring(prjname)
            prjinfo_s = self._cleancstring(prjinfo)
            cpu_s = self._cleancstring(cpu)
            flashtype_s = self._cleancstring(flashtype)

            if prjname_s:
                self._emit('检测到项目: ' + prjname_s)
            if prjinfo_s:
                self._emit('检测到信息: ' + prjinfo_s)
            if cpu_s:
                self._emit('检测到 CPU: ' + cpu_s)
            if flashtype_s:
                self._emit('检测到存储类型: ' + flashtype_s)

            rf.seek(filesize - hdr2length - hdrlength)
            hdr2 = self._mtk_shuffle(hdrkey, len(hdrkey), bytearray(rf.read(hdr2length)), hdr2length)

            for i in range(0, len(hdr2) // 0x60):
                self._check_stop()
                entry = hdr2[i * 0x60 : (i * 0x60) + 0x60]
                name, start, length, enclength, filename, _ = unpack('<32s Q Q Q 32s Q', entry)
                name_s = name.replace(b'\x00', b'').decode('utf-8', errors='ignore')
                filename_s = filename.replace(b'\x00', b'').decode('utf-8', errors='ignore')

                if not filename_s:
                    continue

                self._emit(f'正在写出 "{name_s}" -> "{filename_s}"')

                out_path = out_dir / filename_s
                out_path.parent.mkdir(parents=True, exist_ok=True)

                with out_path.open('wb') as wb:
                    if enclength > 0:
                        rf.seek(start)
                        encdata = rf.read(enclength)
                        if enclength % 16 != 0:
                            encdata += b'\x00' * (16 - (enclength % 16))
                        data = self._mtk_aes_cfb(aeskey, aesiv, encdata, True)
                        wb.write(data[:enclength])
                        length -= enclength
                    while length > 0:
                        self._check_stop()
                        size = 0x200000
                        if length < size:
                            size = length
                        data = rf.read(size)
                        if not data:
                            break
                        length -= len(data)
                        wb.write(data)

        return True
