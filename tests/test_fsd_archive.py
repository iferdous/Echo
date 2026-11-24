from dataclasses import replace
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

import pytest

from echo.fsd_archive import CENTRAL, EOCD, ArchiveError, SplitArchive


def make_archive(method):
    stream = BytesIO()
    with ZipFile(stream, "w", compression=method) as archive:
        archive.writestr("FSD50K.eval_audio/101.wav", b"RIFF" + b"fixture data" * 20)
        archive.writestr("ignored/001.wav", b"never extract")
    return stream.getvalue()


def split_archive(data, split_at):
    # Convert the fixture to two disks while keeping a member split across them.
    data = bytearray(data)
    offset = data.rfind(b"PK\x05\x06")
    end = list(EOCD.unpack_from(data, offset))
    position = end[6]
    for _ in range(end[4]):
        row = list(CENTRAL.unpack_from(data, position))
        if row[16] >= split_at:
            row[13] = 1
            row[16] -= split_at
        CENTRAL.pack_into(data, position, *row)
        position += CENTRAL.size + sum(row[10:13])
    end[1:3] = [1, 1]
    end[6] -= split_at
    EOCD.pack_into(data, offset, *end)
    return bytes(data[:split_at]), bytes(data[split_at:])


@pytest.mark.parametrize("method", [ZIP_STORED, ZIP_DEFLATED])
def test_extracts_original_member_across_split_disk_boundary(method):
    parts = split_archive(make_archive(method), 58)
    reads = []

    def get_range(disk, offset, count):
        reads.append(disk)
        return parts[disk][offset : offset + count]

    archive = SplitArchive(tuple(map(len, parts)), get_range)
    members = archive.catalog()
    assert list(members) == ["101"]
    member = members["101"]
    assert archive.extract(member) == b"RIFF" + b"fixture data" * 20
    assert set(reads) == {0, 1}
    with pytest.raises(ArchiveError, match="CRC"):
        archive.extract(replace(member, checksum=0))


def test_incomplete_reader_rejects_truncated_ranges():
    data = make_archive(ZIP_STORED)
    archive = SplitArchive(
        (len(data),), lambda disk, offset, count: data[offset : offset + count - 1]
    )
    with pytest.raises(ArchiveError, match="truncated"):
        archive.catalog()
