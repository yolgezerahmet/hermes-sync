#!/usr/bin/env python3
"""hermes-sync CLI — pip kurulumu sonrası entry point.

Kullanım: hermes-sync <komut> [seçenekler]   (sync_motor arayüzü)
         a2a-cli <komut> <host>              (A2A mesh client)
         inbox-worker                        (görev işleyici)
"""
import sys


def main(argv=None):
    from . import sync_motor
    sys.exit(sync_motor.main(argv))


if __name__ == "__main__":
    main()
