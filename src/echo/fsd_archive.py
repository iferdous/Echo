"""Read selected original WAV members from the official split FSD50K eval ZIP."""

import re
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from http.client import HTTPException
from struct import Struct
from threading import Lock
from time import sleep
from urllib.error import HTTPError
from urllib.request import Request, urlopen

PARTS = (
    ("FSD50K.eval_audio.z01", 3_221_225_472, "3090670eaeecc013ca1ff84fe4442aeb"),
    ("FSD50K.eval_audio.zip", 3_037_675_767, "6fa47636c3a3ad5c7dfeba99f2637982"),
)
PART_URL = "https://zenodo.org/api/records/4060432/files/{name}/content"
EOCD = Struct("<4s4H2IH")
CENTRAL = Struct("<4s6H3I5H2I")
LOCAL = Struct("<4s5H3I2H")
MAX_AUDIO_BYTES = 32 * 1024 * 1024
MEMBER = re.compile(rb"FSD50K\.eval_audio/([0-9]+)\.wav")


class ArchiveError(ValueError):
    """The requested archive bytes failed structural or checksum validation."""


class ZenodoRanges:
    """Read exact byte ranges and count payload transfer across workers."""

    def __init__(self) -> None:
        self.sizes = tuple(size for _, size, _ in PARTS)
        self.payload_bytes = 0
        self.requests = 0
        self._lock = Lock()

    def read(self, disk: int, offset: int, length: int) -> bytes:
        name, size, _ = PARTS[disk]
        end = offset + length - 1
        request = Request(
            PART_URL.format(name=name),
            headers={"Range": f"bytes={offset}-{end}", "Accept-Encoding": "identity"},
        )
        for attempt in range(4):
            try:
                with urlopen(request, timeout=45) as response:
                    expected = f"bytes {offset}-{end}/{size}"
                    if (
                        response.status != 206
                        or response.headers.get("Content-Range") != expected
                    ):
                        raise ArchiveError(
                            f"{name}: wrong HTTP range response for {expected}"
                        )
                    data = response.read(length + 1)
                with self._lock:
                    self.payload_bytes += len(data)
                    self.requests += 1
                if len(data) != length:
                    raise OSError(
                        f"{name}: incomplete range response ({len(data)} of {length} bytes)"
                    )
                return data
            except (OSError, HTTPException) as error:
                if isinstance(error, HTTPError) and error.code not in {
                    429,
                    500,
                    502,
                    503,
                    504,
                }:
                    raise ArchiveError(f"{name}: {error}") from error
                if attempt == 3:
                    raise ArchiveError(f"{name}: {error}") from error
                delay = 2**attempt
                if (
                    isinstance(error, HTTPError)
                    and error.headers.get("Retry-After", "").isdigit()
                ):
                    delay = min(int(error.headers["Retry-After"]), 30)
                sleep(delay)
        raise ArchiveError(f"{name}: range retrieval exhausted")


@dataclass(frozen=True, slots=True)
class Member:
    name: bytes
    disk: int
    offset: int
    method: int
    checksum: int
    compressed_size: int
    size: int


class SplitArchive:
    def __init__(
        self, sizes: tuple[int, ...], reader: Callable[[int, int, int], bytes]
    ) -> None:
        self.sizes = sizes
        self.reader = reader

    def span(self, disk: int, offset: int, length: int) -> bytes:
        chunks = []
        while length:
            if disk >= len(self.sizes) or not 0 <= offset <= self.sizes[disk]:
                raise ArchiveError("ZIP member extends outside its archive parts")
            take = min(length, self.sizes[disk] - offset)
            if take:
                chunk = self.reader(disk, offset, take)
                if len(chunk) != take:
                    raise ArchiveError("truncated ZIP range")
                chunks.append(chunk)
                length -= take
            disk += 1
            offset = 0
        return b"".join(chunks)

    def catalog(self) -> dict[str, Member]:
        last = len(self.sizes) - 1
        tail_bytes = min(self.sizes[last], 65_557)
        tail = self.span(last, self.sizes[last] - tail_bytes, tail_bytes)
        end = tail.rfind(b"PK\x05\x06")
        if end < 0 or len(tail) - end < EOCD.size:
            raise ArchiveError("ZIP end record missing")
        _, final_disk, catalog_disk, here, total, size, start, comments = (
            EOCD.unpack_from(tail, end)
        )
        if (
            final_disk != last
            or catalog_disk > last
            or here != total
            or total == 0xFFFF
            or size > 16 * 1024 * 1024
            or end + EOCD.size + comments != len(tail)
        ):
            raise ArchiveError("unsupported split ZIP directory layout")

        directory = self.span(catalog_disk, start, size)
        members = {}
        position = 0
        for _ in range(total):
            if len(directory) - position < CENTRAL.size:
                raise ArchiveError("truncated ZIP directory entry")
            row = CENTRAL.unpack_from(directory, position)
            signature, flags, method = row[0], row[3], row[4]
            crc, compressed, length = row[7:10]
            names, extra, comment, disk = row[10:14]
            offset = row[16]
            position += CENTRAL.size
            name = directory[position : position + names]
            position += names + extra + comment
            if signature != b"PK\x01\x02" or position > len(directory):
                raise ArchiveError("invalid ZIP directory entry")
            match = MEMBER.fullmatch(name)
            if match is None:
                continue
            source = match.group(1).decode("ascii")
            if (
                source in members
                or flags & 1
                or disk > last
                or method not in {0, 8}
                or max(compressed, length) > MAX_AUDIO_BYTES
                or offset >= self.sizes[disk]
            ):
                raise ArchiveError(f"unsupported ZIP audio member {source}")
            members[source] = Member(
                name, disk, offset, method, crc, compressed, length
            )
        if position != len(directory):
            raise ArchiveError("unexpected data after ZIP directory")
        return members

    def extract(self, member: Member) -> bytes:
        remaining = sum(self.sizes[member.disk :]) - member.offset
        expected = LOCAL.size + len(member.name) + member.compressed_size
        data = self.span(member.disk, member.offset, min(remaining, expected + 256))
        if len(data) < LOCAL.size:
            raise ArchiveError("truncated ZIP local header")
        row = LOCAL.unpack_from(data)
        if row[0] != b"PK\x03\x04" or row[2] & 1 or row[3] != member.method:
            raise ArchiveError("ZIP local header differs from directory")
        name_end = LOCAL.size + row[9]
        if data[LOCAL.size : name_end] != member.name:
            raise ArchiveError("ZIP member name changed")
        start = name_end + row[10]
        end = start + member.compressed_size
        if end > len(data):
            data = self.span(member.disk, member.offset, end)
        payload = data[start:end]
        if member.method == 8:
            try:
                stream = zlib.decompressobj(-zlib.MAX_WBITS)
                payload = stream.decompress(payload, member.size + 1)
            except zlib.error as error:
                raise ArchiveError(
                    f"invalid deflate stream for {member.name!r}"
                ) from error
            if not stream.eof or stream.unused_data:
                raise ArchiveError(f"invalid deflate boundaries for {member.name!r}")
        if len(payload) != member.size or zlib.crc32(payload) != member.checksum:
            raise ArchiveError(f"ZIP size or CRC mismatch for {member.name!r}")
        return payload
