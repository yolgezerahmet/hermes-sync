#!/usr/bin/env python3
"""synclave CLI — pip kurulumu sonrası entry point.

Kullanım: synclave <komut> [seçenekler]   (sync_motor arayüzü)
         synclave-a2a <komut> <host>        (A2A mesh client)
         synclave-worker                    (görev işleyici)
"""
import sys


def main(argv=None):
    from . import sync_motor
    sys.exit(sync_motor.main(argv))


if __name__ == "__main__":
    main()
