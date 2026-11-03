"""Restore Bun ELF version definitions after patchelf relocates dynamic sections."""

import struct
import sys

from elftools.elf.elffile import ELFFile


def repair(path):
    with open(path, "r+b") as stream:
        elf = ELFFile(stream)
        if elf.elfclass != 64 or not elf.little_endian:
            raise ValueError(f"{path}: expected ELF64 little-endian")

        sections = list(elf.iter_sections())
        version = next(
            (section for section in sections if section["sh_type"] == "SHT_GNU_verdef"),
            None,
        )
        if version is None:
            return

        dynamic = next(
            (section for section in sections if section["sh_type"] == "SHT_DYNAMIC"),
            None,
        )
        if dynamic is None:
            raise ValueError(f"{path}: version definitions without a dynamic section")

        for index, tag in enumerate(dynamic.iter_tags()):
            if tag.entry.d_tag != "DT_VERDEF":
                continue
            address = version["sh_addr"]
            if tag.entry.d_ptr != address:
                stream.seek(dynamic["sh_offset"] + index * elf.structs.Elf_Dyn.sizeof() + 8)
                stream.write(struct.pack("<Q", address))
            return

        raise ValueError(f"{path}: version definitions without DT_VERDEF")


if __name__ == "__main__":
    repair(sys.argv[1])
