#!/usr/bin/env python3

import argparse
import os
import re
import subprocess

# Linux arm64 boot header
# https://www.kernel.org/doc/Documentation/arm64/booting.txt
LINUX_ARM64_HDR = {
    "CODE0": (0x0000000091005A4D, 0x04),  # Offset   0
    "CODE1": [0x0000000000000000, 0x04],  # Offset   4
    "LOAD_OFFS": [0x0000000000000000, 0x08],  # Offset   8
    "IMAGE_SIZE": [0x0000000000000000, 0x08],  # Offset  16
    "KERNEL_FLAGS": [0x0000000000000000, 0x08],  # Offset  24
    "RES2": (0x0000000000000000, 0x08),  # Offset  32
    "RES3": (0x0000000000000000, 0x08),  # Offset  40
    "RES4": (0x0000000000000000, 0x08),  # Offset  48
    "MAGIC": (0x00000000644D5241, 0x04),  # Offset  56
    "RES5": (0x0000000000000040, 0x04),  # Offset  60
}
LINUX_ARM64_HDR_SIZE = 64


# surely there's a pythonic way for that
def align_up(v, a):
    return ((v) + (a) - 1) & ~((a) - 1)


def autoint(x):
    return int(x, 0)


# Get the absolute value of symbol, as seen through `nm`
def get_sym_val(elf, sym):
    exp = r"^\s*" + r"([a-f0-9]+)" + r"\s+[A-Za-z]\s+" + sym + r"$"
    out = subprocess.check_output(["nm", elf])  # nosec

    re_out = re.findall(exp, out.decode("ASCII"), re.MULTILINE)
    if len(re_out) != 1:
        raise Exception("Found no " + sym + " symbol.")

    return int(re_out[0], 16)


# A static-PIE unikernel (OPTIMIZE_PIE) relocates itself at boot (libukreloc),
# so it loads at any base the loader picks. ET_DYN identifies it, but some
# binutils stamp a fully static, no-dynamic-linker PIE link ET_EXEC, so e_type
# alone under-detects; the .uk_reloc section is the actual load-anywhere
# contract, so its presence identifies the image too. Both readers assume a
# little-endian 64-bit ELF (the images this script wraps are arm64).
def elf_is_pie(elf):
    with open(elf, "rb") as f:
        f.seek(16)
        if int.from_bytes(f.read(2), "little") == 3:  # ET_DYN
            return True
    return elf_has_section(elf, ".uk_reloc")


def elf_has_section(elf, name):
    with open(elf, "rb") as f:
        hdr = f.read(64)
        shoff = int.from_bytes(hdr[40:48], "little")
        shentsize = int.from_bytes(hdr[58:60], "little")
        shnum = int.from_bytes(hdr[60:62], "little")
        shstrndx = int.from_bytes(hdr[62:64], "little")
        if shoff == 0 or shnum == 0 or shstrndx >= shnum:
            return False
        f.seek(shoff + shstrndx * shentsize)
        strhdr = f.read(shentsize)
        stroff = int.from_bytes(strhdr[24:32], "little")
        strsize = int.from_bytes(strhdr[32:40], "little")
        f.seek(stroff)
        strtab = f.read(strsize)
        want = name.encode()
        for i in range(shnum):
            f.seek(shoff + i * shentsize)
            name_off = int.from_bytes(f.read(4), "little")
            end = strtab.find(b"\x00", name_off)
            if strtab[name_off:end] == want:
                return True
    return False


def main():
    parser = argparse.ArgumentParser()
    # description = "Prepends image with arm64 linux boot header."
    parser.add_argument("bin", help="Raw binary to prepend header with.")
    parser.add_argument(
        "elf",
        help="The ELF image the raw binary was derived from. "
        "Required for resolving symbols used in the header.",
    )
    opt = parser.parse_args()

    ram_base = get_sym_val(opt.elf, r"_start_ram_addr")
    img_base = get_sym_val(opt.elf, r"_base_addr")
    entry = get_sym_val(opt.elf, r"_libkvmplat_entry")

    # code1
    #
    # This contains an unconditional branch to the entry point.
    # The encoding of the branch instruction according to the
    # Arm ARM (DDI0487I.a) is:
    #
    # 31           25                            0
    # ┌───────────┬───────────────────────────────┐
    # │0 0 0 1 0 1│           imm26               │
    # └───────────┴───────────────────────────────┘
    #
    # b <offs>
    #
    # where offs is encoded as "imm26" times 4, relatively
    # to the branch instruction
    #
    # The header occupies the first 64 bytes of the image itself (reserved by
    # the linker script), so the branch runs from the image base.
    pc = img_base + 4
    offs = entry - pc

    # offset must be <= +128M. We don't accept negative offsets
    # here as the header starts the image.
    assert 0 < (offs) <= ((1 << 26) / 2 - 1)

    LINUX_ARM64_HDR["CODE1"][0] = (0b101 << 26) | (int(offs / 4))

    # load_offset
    #
    # A position-independent image relocates itself (libukreloc) from wherever
    # the loader places it, so it loads at text_offset 0 -- required by the
    # "image anywhere" flag (bit 3, set below) and by loaders that reject a
    # nonzero text_offset (e.g. vz's VZLinuxBootLoader, EFI). A fixed-address
    # image must land exactly at _base_addr, so its offset spans the header and
    # the DTB reservation.
    if elf_is_pie(opt.elf):
        LINUX_ARM64_HDR["LOAD_OFFS"][0] = 0
    else:
        LINUX_ARM64_HDR["LOAD_OFFS"][0] = img_base - ram_base

    # kernel_flags
    #
    # For now assume little-endian, 4KiB pages, image anywhere in memory
    LINUX_ARM64_HDR["KERNEL_FLAGS"][0] = 0xA

    # image_size
    #
    # We arbitrarily set this to the image size aligned up to 2MiB; the header
    # is inside the image.
    total_size = os.path.getsize(opt.bin)
    LINUX_ARM64_HDR["IMAGE_SIZE"][0] = align_up(total_size, 2**21)

    # Patch the header over the space the linker script reserved at the start
    # of the image.
    with open(opt.bin, "r+b") as f:
        space = f.read(LINUX_ARM64_HDR_SIZE)
        assert space == bytes(LINUX_ARM64_HDR_SIZE), (
            "the first %d bytes of the image are not the reserved boot-header"
            " space" % LINUX_ARM64_HDR_SIZE
        )
        f.seek(0)
        for field in [k for k in LINUX_ARM64_HDR.keys()]:
            f.write(
                LINUX_ARM64_HDR[field][0].to_bytes(
                    LINUX_ARM64_HDR[field][1], "little"
                )
            )


if __name__ == "__main__":
    main()
